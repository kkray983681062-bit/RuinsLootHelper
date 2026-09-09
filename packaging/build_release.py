"""Build and verify an explicit, shareable one-folder Windows release."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.3.0'
STAGING = ROOT / ('release-staging-' + VERSION)
APP = STAGING / '破晓装备助手'
DESTINATION = ROOT / 'releases' / VERSION


def main():
    if STAGING.is_symlink() or APP.is_symlink() or APP.resolve().parent != STAGING.resolve() or STAGING.resolve().parent != ROOT.resolve():
        raise RuntimeError('Build destination must remain inside the project')
    subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(STAGING), '--workpath', str(ROOT / ('build/release-' + VERSION)),
                    str(ROOT / 'packaging/loot_helper.spec')], cwd=ROOT, check=True)
    shutil.copy2(ROOT / 'packaging/使用说明.txt', APP / '使用说明.txt')
    shutil.copy2(ROOT / 'packaging/破晓助手一键诊断.bat', APP / '破晓助手一键诊断.bat')
    shutil.copytree(ROOT / 'packaging/licenses', APP / 'licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'packaging/THIRD-PARTY-NOTICES.txt', APP / 'licenses/THIRD-PARTY-NOTICES.txt')
    shutil.copytree(ROOT / 'native', APP / '原生组件源码', dirs_exist_ok=True)
    exe = APP / '破晓装备助手.exe'
    archive = CArchiveReader(str(exe)).open_embedded_archive('PYZ.pyz')
    forbidden = ('equipment_editor', 'equipment_edit_jobs', 'equipment_spawn',
                 'feature_host', 'feature_runtime', 'feature_ui', 'overlay_splitter',
                 'change_target', 'change_worn', 'PySide', 'PyQt', 'lupa', 'ui_smoke')
    assert not [name for name in archive.toc if any(part in name for part in forbidden)]
    banned_files = {'current-loot.json', 'app-settings.json', 'continuous-status.json',
                    'feature-status.json', 'overlay-status.json', 'probe-elevated-1.json',
                    'watch-2.json', 'loot-overlay-settings.json', 'loot-filter-rules.json'}
    files = sorted(path for path in APP.rglob('*') if path.is_file())
    assert not [path for path in files if path.name in banned_files or path.suffix in ('.lock', '.flag')]
    DESTINATION.mkdir(parents=True, exist_ok=True)
    destination = DESTINATION / f'破晓装备助手-{VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in files:
            output.write(path, path.relative_to(STAGING).as_posix())
    with zipfile.ZipFile(destination) as output:
        assert output.testzip() is None
        assert len(output.infolist()) == len(files)
    manifest = {
        'version': VERSION, 'format': 'portable-onedir', 'files': len(files),
        'zip_bytes': destination.stat().st_size,
        'zip_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
        'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'private_snapshots_included': False,
        'native_automation_preview_included': True, 'native_runtime_binaries_included': False,
        'native_features_enabled_by_default': False, 'native_game_verified': False,
    }
    (DESTINATION / 'build-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(destination)


if __name__ == '__main__':
    main()
