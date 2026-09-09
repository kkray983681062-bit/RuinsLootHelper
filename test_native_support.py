import hashlib
from pathlib import Path
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
