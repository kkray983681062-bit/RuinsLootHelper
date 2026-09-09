"""Steam installation discovery. Reads manifests, never modifies the game."""
import os
import pathlib
import re
import winreg

APP_ID = '4364910'
EXE_NAME = 'RuinsOfDawn-Win64-Shipping.exe'
SHIPPING = pathlib.Path('RuinsOfDawn/Binaries/Win64') / EXE_NAME


def parse_vdf(text):
    tokens = re.findall(r'//[^\r\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', text.lstrip('\ufeff'))
    tokens = [x for x in tokens if not x.startswith('//')]
    index = 0

    def word(token):
        return re.sub(r'\\([\\"])', r'\1', token[1:-1]) if token.startswith('"') else token

    def block(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == '}':
                if nested:
                    return result
                raise ValueError('Unexpected closing brace')
            if key == '{' or index == len(tokens):
                raise ValueError('Invalid KeyValues pair')
            value = tokens[index]
            index += 1
            if value == '}':
                raise ValueError('Missing KeyValues value')
            result[word(key)] = block(True) if value == '{' else word(value)
        if nested:
            raise ValueError('Unclosed KeyValues block')
        return result

    return block()


def read_vdf(path):
    try:
        return parse_vdf(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, ValueError):
        return {}


def steam_roots():
    result = []
    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                result.append(pathlib.Path(winreg.QueryValueEx(handle, value)[0]))
        except OSError:
            pass
    for env in ('ProgramFiles(x86)', 'ProgramFiles'):
        if os.environ.get(env):
            result.append(pathlib.Path(os.environ[env]) / 'Steam')
    return result


def resolve_game(path):
    if not path:
        return None
    path = pathlib.Path(path).expanduser()
    choices = [path] if path.name.casefold() == EXE_NAME.casefold() else [path / SHIPPING, path / 'Binaries/Win64' / EXE_NAME, path / EXE_NAME]
    for candidate in choices:
        try:
            if candidate.is_file() and candidate.name.casefold() == EXE_NAME.casefold():
                with candidate.open('rb') as file:
                    if file.read(2) == b'MZ':
                        return candidate.resolve()
        except OSError:
            pass
    return None


def discover(saved=None, roots=None):
    saved = resolve_game(saved)
    if saved:
        return [saved]
    roots = steam_roots() if roots is None else roots
    libraries = set()
    for root in roots:
        root = pathlib.Path(root)
        libraries.add(root)
        vdf = read_vdf(root / 'steamapps/libraryfolders.vdf').get('libraryfolders', {})
        if isinstance(vdf, dict):
            for key, entry in vdf.items():
                if str(key).isdigit():
                    path = entry.get('path') if isinstance(entry, dict) else entry
                    if isinstance(path, str) and path:
                        libraries.add(pathlib.Path(path))
    found = set()
    for library in libraries:
        data = read_vdf(library / 'steamapps' / f'appmanifest_{APP_ID}.acf').get('AppState', {})
        if not isinstance(data, dict) or str(data.get('appid', APP_ID)) != APP_ID:
            continue
        folder = data.get('installdir', '')
        if not isinstance(folder, str) or not folder or any(x in folder for x in ('..', '/', '\\', ':')):
            continue
        game = resolve_game(library / 'steamapps/common' / folder)
        if game:
            found.add(game)
    return sorted(found, key=lambda p: str(p).casefold())
