# Build with the isolated .venv-build environment. Data is explicitly allowlisted.
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / 'loot_app.py')], pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'catalog/filter-catalog.json'), 'catalog'),
           (str(root / 'assets/backpack-lock.png'), 'assets'),
           (str(root / 'catalog/codex-items.json'), 'catalog'),
           (str(root / 'catalog/skill-names.json'), 'catalog'),
           (str(root / 'release-defaults.json'), '.'),
           (str(root / 'project-links.json'), '.'),
           (str(root / 'packaging/使用说明.txt'), '.'),
           (str(root / 'runtime/UE4SS-2bfa839f.zip'), 'runtime'),
           (str(root / 'native/Mods/RuinsHelper/Scripts'), 'native/Mods/RuinsHelper/Scripts')],
    hiddenimports=['loot_overlay', 'overlay_settings', 'overlay_features', 'overlay_markers', 'overlay_panes'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6', 'PyQt6', 'PyQt5', 'PIL', 'pytest', 'unittest', 'lupa', 'ui_smoke'],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='破晓装备助手', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    uac_admin=True,
    version=str(root / 'packaging/version.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='破晓装备助手')
