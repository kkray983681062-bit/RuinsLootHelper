"""Install a verified, bundled UE4SS bridge without network access or replacing mods."""
import hashlib
import json
from pathlib import Path
import zipfile

URL = 'https://github.com/UE4SS-RE/RE-UE4SS/releases/download/experimental-latest/UE4SS_v3.0.1-1127-g2bfa839f.zip'
SHA256 = '29367ce89f3637a537d507f2c79b9d33df3d145c63fd8bb0179f737a5ce46374'
ARCHIVE_NAME = 'UE4SS-2bfa839f.zip'
ROOT = Path(__file__).resolve().parent
RUNTIME_FILES = ('dwmapi.dll', 'ue4ss/UE4SS.dll', 'ue4ss/LICENSE', 'ue4ss/UE4SS-settings.ini')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.ruins-helper.tmp')
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def install(game, directory, archive=None):
    from game_install import resolve_game
    game = resolve_game(game)
    if game is None:
        raise ValueError('请先定位有效的游戏安装目录。')
    directory = Path(directory)
    target = game.parent.resolve()
    receipt_path = directory / 'native-install.json'
    previous = json.loads(receipt_path.read_text(encoding='utf8')) if receipt_path.exists() else {}
    if (target / 'dwmapi.dll').exists() and str(target) != previous.get('directory'):
        raise ValueError('游戏目录已有其他原生插件，本次未覆盖任何文件。')
    for relative, digest in previous.get('files', {}).items():
        path = (target / relative).resolve()
        if not path.is_relative_to(target):
            raise ValueError('安装记录的路径无效，未修改文件。')
        if path.exists() and sha(path) != digest:
            raise ValueError(f'原生组件已被修改，未覆盖：{relative}')
    if archive is None:
        bundled = ROOT / 'runtime' / ARCHIVE_NAME
        archive = bundled if bundled.is_file() else directory / 'native-cache' / ARCHIVE_NAME
    else:
        archive = Path(archive)
    if not archive.is_file():
        raise ValueError('离线组件包缺失，请完整解压新版助手并保留 _internal 文件夹。')
    if sha(archive) != SHA256:
        raise ValueError('离线组件包校验失败，请重新解压或下载完整助手，未安装。')
    content = {}
    with zipfile.ZipFile(archive) as package:
        for name in RUNTIME_FILES:
            content[name] = package.read(name)
    settings = content['ue4ss/UE4SS-settings.ini'].decode('utf8').replace('\r', '')
    settings = settings.replace('EnableDumping = 1', 'EnableDumping = 0')
    content['ue4ss/UE4SS-settings.ini'] = settings.encode('utf8')
    # Only this bridge; no console, cheat manager, keybind, or example mods.
    content['ue4ss/Mods/mods.txt'] = b'RuinsHelper : 1\n'
    for path in (ROOT / 'native/Mods/RuinsHelper/Scripts').glob('*.lua'):
        content['ue4ss/Mods/RuinsHelper/Scripts/' + path.name] = path.read_bytes()
    if len(content) < 9:
        raise ValueError('原生桥接脚本不完整。')
    for name in content:
        destination = (target / name).resolve()
        if not destination.is_relative_to(target.resolve()):
            raise ValueError('安装路径超出游戏目录。')
        if destination.exists() and name not in previous.get('files', {}):
            raise ValueError(f'已有文件属于其他插件，未覆盖：{name}')
    receipt = {'directory': str(target), 'game': str(game), 'framework_sha256': SHA256,
               'files': {name: hashlib.sha256(data).hexdigest() for name, data in content.items()},
               'state': 'installed_waiting_for_game_restart'}
    originals, changed = {}, []
    try:
        # Loader last. A failed first install cannot be loaded on game startup.
        for name in sorted(content, key=lambda name: name == 'dwmapi.dll'):
            destination = target / name
            originals[destination] = destination.read_bytes() if destination.exists() else None
            if originals[destination] == content[name]:
                continue  # Do not replace an unchanged DLL that the game has loaded.
            write_atomic(destination, content[name])
            changed.append(destination)
        write_atomic(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2).encode('utf8'))
    except Exception:
        for path in reversed(changed):
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, originals[path])
        raise
    return receipt
