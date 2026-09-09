import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import native_support
from feature_policy import native_slot_rects


class NativeInstallTests(unittest.TestCase):
    def fixture(self, root):
        game = root/'game'/'RuinsOfDawn-Win64-Shipping.exe'
        game.parent.mkdir()
        game.write_bytes(b'MZ' + bytes(100))
        data = root/'data'
        data.mkdir()
        archive = root/'runtime.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            for name in native_support.RUNTIME_FILES:output.writestr(name, b'test runtime')
        return game, data, archive

    def bundle(self, root, archive):
        bundle = root / '助手 文件夹' / '_internal'
        runtime = bundle / 'runtime' / 'UE4SS-2bfa839f.zip'
        runtime.parent.mkdir(parents=True)
        shutil.copy2(archive, runtime)
        shutil.copytree(native_support.ROOT / 'native', bundle / 'native')
        return bundle, runtime

    def test_new_profile_installs_bundled_runtime_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            bundle, runtime = self.bundle(root, archive)
            with patch.object(native_support, 'ROOT', bundle), \
                    patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network unavailable')):
                receipt = native_support.install(game, data)
            self.assertEqual((game.parent / 'dwmapi.dll').read_bytes(), b'test runtime')
            self.assertEqual((game.parent / 'ue4ss/Mods/mods.txt').read_bytes(), b'RuinsHelper : 1\n')
            self.assertEqual(receipt['state'], 'installed_waiting_for_game_restart')
            self.assertTrue((data / 'native-install.json').is_file())
            self.assertEqual(runtime.read_bytes(), archive.read_bytes())

    def test_valid_bundle_ignores_damaged_old_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            bundle, _ = self.bundle(root, archive)
            cached = data / 'native-cache' / 'UE4SS-2bfa839f.zip'
            cached.parent.mkdir()
            cached.write_bytes(b'incomplete previous download')
            with patch.object(native_support, 'ROOT', bundle), \
                    patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network unavailable')):
                native_support.install(game, data)
            self.assertEqual((game.parent / 'ue4ss/UE4SS.dll').read_bytes(), b'test runtime')
            self.assertEqual(cached.read_bytes(), b'incomplete previous download')

    def test_cached_runtime_still_installs_without_bundle_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            bundle, runtime = self.bundle(root, archive)
            runtime.unlink()
            cached = data / 'native-cache' / 'UE4SS-2bfa839f.zip'
            cached.parent.mkdir()
            shutil.copy2(archive, cached)
            with patch.object(native_support, 'ROOT', bundle), \
                    patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network unavailable')):
                native_support.install(game, data)
            self.assertEqual((game.parent / 'dwmapi.dll').read_bytes(), b'test runtime')

    def test_missing_local_runtime_does_not_download_or_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            bundle, runtime = self.bundle(root, archive)
            runtime.unlink()
            with patch.object(native_support, 'ROOT', bundle), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network unavailable')):
                with self.assertRaises(ValueError):
                    native_support.install(game, data)
            self.assertEqual([p for p in game.parent.rglob('*') if p.is_file()], [game])
            self.assertFalse((data / 'native-install.json').exists())

    def test_damaged_bundle_is_rejected_without_downloading_or_changing_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            bundle, runtime = self.bundle(root, archive)
            runtime.write_bytes(b'corrupted bundled archive')
            with patch.object(native_support, 'ROOT', bundle), \
                    patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                    patch('urllib.request.urlopen', side_effect=AssertionError('network unavailable')):
                with self.assertRaises(ValueError):
                    native_support.install(game, data)
            self.assertEqual([p for p in game.parent.rglob('*') if p.is_file()], [game])
            self.assertFalse((data / 'native-install.json').exists())

    def test_checksum_failure_or_existing_mod_leaves_game_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            before = list(game.parent.iterdir())
            with self.assertRaises(ValueError):native_support.install(game, data, archive)
            self.assertEqual(list(game.parent.iterdir()), before)
            (game.parent/'dwmapi.dll').write_bytes(b'another mod')
            with self.assertRaises(ValueError):native_support.install(game, data, archive)
            self.assertEqual((game.parent/'dwmapi.dll').read_bytes(), b'another mod')

    def test_install_only_our_files_and_can_verify_repeat_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            with patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
                receipt = native_support.install(game, data, archive)
                self.assertEqual((game.parent/'ue4ss/Mods/mods.txt').read_text(), 'RuinsHelper : 1\n')
                self.assertEqual(receipt['files'], native_support.install(game, data, archive)['files'])

    def test_update_does_not_rewrite_unchanged_runtime_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            original = native_support.write_atomic
            def protect_runtime(path, content):
                if path.suffix == '.dll':
                    raise PermissionError('loaded DLL must not be rewritten')
                original(path, content)
            with patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()):
                native_support.install(game, data, archive)
                with patch.object(native_support, 'write_atomic', side_effect=protect_runtime):
                    receipt = native_support.install(game, data, archive)
                self.assertEqual(receipt['files']['dwmapi.dll'], native_support.sha(game.parent/'dwmapi.dll'))

    def test_partial_install_failure_rolls_back_and_does_not_write_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game, data, archive = self.fixture(root)
            original = native_support.write_atomic
            def fail(path, content):
                if path.name == 'main.lua':raise OSError('simulated disk failure')
                original(path, content)
            with patch.object(native_support, 'SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), \
                 patch.object(native_support, 'write_atomic', side_effect=fail):
                with self.assertRaises(OSError):native_support.install(game, data, archive)
            self.assertEqual([p for p in game.parent.rglob('*') if p.is_file()], [game])
            self.assertFalse((data/'native-install.json').exists())



class NativeGridTests(unittest.TestCase):
    def test_requires_complete_current_viewport_and_rejects_overlap(self):
        grid = {'viewport': [1000, 800], 'slots': {str(i): [100+i%10*60, 100+i//10*60,
            155+i%10*60, 155+i//10*60] for i in range(60)}}
        self.assertEqual(native_slot_rects(grid, 1000, 800)[59], (640, 400, 695, 455))
        self.assertIsNone(native_slot_rects(grid, 1200, 800))
        grid['slots']['1'] = grid['slots']['0']
        self.assertIsNone(native_slot_rects(grid, 1000, 800))


if __name__ == '__main__':unittest.main()
