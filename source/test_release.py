import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from game_install import APP_ID, SHIPPING, discover, parse_vdf, resolve_game


class InstallDiscoveryTests(unittest.TestCase):
    def make_game(self, library, folder='Ruins of Dawn'):
        game = library / 'steamapps' / 'common' / folder / SHIPPING
        game.parent.mkdir(parents=True)
        game.write_bytes(b'MZ')
        (library / 'steamapps' / f'appmanifest_{APP_ID}.acf').write_text(
            '"AppState" { "appid" "' + APP_ID + '" "installdir" "' + folder + '" }', encoding='utf8')
        return game.resolve()

    def test_new_and_legacy_secondary_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            steam, second = root / 'Steam', root / '游戏库 two'
            (steam / 'steamapps').mkdir(parents=True)
            expected = self.make_game(second)
            escaped = str(second).replace('\\', '\\\\')
            vdf = steam / 'steamapps' / 'libraryfolders.vdf'
            for value in (f'{{ "path" "{escaped}" "apps" {{ "{APP_ID}" "1" }} }}', f'"{escaped}"'):
                vdf.write_text(f'"libraryfolders" {{ "1" {value} }}', encoding='utf8')
                self.assertEqual(discover(roots=[steam]), [expected])

    def test_saved_path_move_duplicates_and_manual_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            expected = self.make_game(root)
            self.assertEqual(discover(saved=root / 'gone.exe', roots=[root, root]), [expected])
            self.assertEqual(resolve_game(root / 'steamapps/common/Ruins of Dawn'), expected)
            self.assertEqual(resolve_game(expected), expected)
            self.assertIsNone(resolve_game(root / 'not-the-game.exe'))

    def test_malformed_manifest_and_path_traversal_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / 'steamapps').mkdir()
            manifest = root / 'steamapps' / f'appmanifest_{APP_ID}.acf'
            for text in ('"AppState" {', '"AppState" { "installdir" "../../elsewhere" }'):
                manifest.write_text(text)
                self.assertEqual(discover(roots=[root]), [])

    def test_comments_and_escaped_quoted_strings(self):
        self.assertEqual(parse_vdf('// header\n"a" { "x" "C:\\\\Games" }'), {'a': {'x': 'C:\\Games'}})
        with self.assertRaises(ValueError):
            parse_vdf('"a" { "x" }')


class ReleaseLifecycleTests(unittest.TestCase):
    def test_upgrade_saves_combined_rules_and_preserves_original_preferences(self):
        from loot_app import prepare_settings
        from lock_library import selected_indices
        from test_lock_library import item
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            old = {'width': 512, 'native': {'lock': True, 'lock_sections': {'numeric': True}},
                   'lock_library': {'qualities': ['完美'], 'quality_tiers': [10],
                                    'equipment_keys': ['10:1:霄引'], 'thresholds': {'10:1:霄引': {'魔法上限': 48}}}}
            path = directory / 'loot-overlay-settings.json'
            path.write_text(json.dumps(old), encoding='utf8')
            prepare_settings(directory)
            saved = json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(saved['width'], 512)
            self.assertEqual(saved['lock_library']['schema'], 2)
            self.assertEqual(selected_indices([{'index': 4, 'item': item(magic=47)}], saved['lock_library']), set())
            self.assertEqual(json.loads((directory/'loot-overlay-settings.pre-lock-rules-v2.json').read_text(encoding='utf8')), old)
            prepare_settings(directory)
            self.assertEqual(json.loads(path.read_text(encoding='utf8')), saved)

    def test_new_profile_has_no_old_coordinates_or_automatic_pickup(self):
        from loot_app import prepare_settings
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            prepare_settings(directory)
            saved = json.loads((directory / 'loot-overlay-settings.json').read_text(encoding='utf8'))
            self.assertNotIn('auto_pickup', saved)
            self.assertNotIn('x', saved)
            self.assertNotIn('y', saved)
            self.assertIsNone(saved['backpack_markers']['grid'])
            saved['width'] = 512
            (directory / 'loot-overlay-settings.json').write_text(json.dumps(saved), encoding='utf8')
            prepare_settings(directory)
            self.assertEqual(json.loads((directory / 'loot-overlay-settings.json').read_text(encoding='utf8'))['width'], 512)

    def test_game_restart_requires_new_discovery_and_exit_clears_results(self):
        from release_runtime import Backend
        with tempfile.TemporaryDirectory() as tmp, patch('release_runtime.configure_runtime'):
            directory = pathlib.Path(tmp)
            backend = Backend('verified-game.exe', directory)
            decoded_pids = []

            def scan(pid, *_):
                decoded_pids.append(pid)
                probe = MagicMock()
                probe.discover.return_value = ({'pid': pid, 'reflected_types': {}}, {})
                return probe

            def watch(pid, directory, seed, instances, stop, progress):
                self.assertEqual(seed['pid'], pid)
                monitor = MagicMock()
                def run():
                    if pid == 200:
                        stop.set()
                monitor.run.side_effect = run
                return monitor

            with patch('release_runtime.running_games', side_effect=[[100], [200]]), \
                    patch('release_runtime.SessionProbe', side_effect=scan), \
                    patch('release_runtime.SessionWatch', side_effect=watch):
                backend.run()
            self.assertEqual(decoded_pids, [100, 200])
            current = json.loads((directory / 'current-loot.json').read_text(encoding='utf8'))
            self.assertEqual(current['items'], [])
            self.assertIsNone(current['backpack_free_slots'])
            ui = json.loads((directory / 'feature-status.json').read_text(encoding='utf8'))
            self.assertFalse(ui['ui']['valid'])

    def test_old_main_ui_identity_cannot_show_markers(self):
        from release_runtime import SessionWatch
        watcher = object.__new__(SessionWatch)
        watcher.phase, watcher.handle = 'watching', 1
        watcher.main_ui = {'object': {'address': 100000, 'index': 1, 'class_address': 200000}}
        watcher.object_info = lambda _: {'index': 2, 'class_address': 200000, 'flags': 0}
        self.assertEqual(watcher.ui_state(), {'valid': False, 'backpack_open': False})

    def test_release_does_not_keep_equipment_moved_into_storage(self):
        from release_runtime import SessionWatch
        import struct
        watcher = object.__new__(SessionWatch)
        watcher.next_ui = float('inf')
        owner = {'address': 100000, 'index': 1, 'class_address': 200000, 'flags': 0}
        source = {'owner': owner, 'header_address': 300000, 'stride': 8, 'type_name': 'fixture'}
        watcher.object_info = lambda _: owner
        watcher.read = lambda addr, size: struct.pack('<Qii', 400000, 61, 61) if addr == 300000 else bytes(size)
        watcher.decode = MagicMock(side_effect=[{'物品类型': 1, '名字': '背包装备'}] + [{}] * 59 + [{'名字': '已移入储物箱'}])
        watcher.compact = lambda item: item
        self.assertEqual(watcher.take(source), {0: {'物品类型': 1, '名字': '背包装备'}})
        self.assertEqual(watcher.decode.call_count, 60)

    def test_overlay_opens_at_physical_coordinates_on_left_hand_monitor(self):
        import ctypes
        from ctypes import wintypes
        import loot_overlay
        from loot_app import prepare_settings
        with tempfile.TemporaryDirectory() as tmp, patch.object(loot_overlay, 'BASE', pathlib.Path(tmp)):
            prepare_settings(pathlib.Path(tmp))
            overlay = loot_overlay.Overlay()
            original = loot_overlay.u.GetWindowRect
            def rect_for_game(hwnd, output):
                if hwnd == 1:
                    rect = ctypes.cast(output, ctypes.POINTER(wintypes.RECT)).contents
                    rect.left, rect.top, rect.right, rect.bottom = -2200, -1100, -900, 0
                    return True
                return original(hwnd, output)
            try:
                overlay.game = 1
                with patch.object(loot_overlay.u, 'GetWindowRect', side_effect=rect_for_game):
                    overlay.place()
                actual = wintypes.RECT()
                original(overlay.hwnd, ctypes.byref(actual))
                self.assertEqual((actual.left, actual.top), (-1760, -900))
            finally:
                for callback in overlay.root.tk.call('after', 'info'):
                    overlay.root.tk.call('after', 'cancel', callback)
                overlay.close()


if __name__ == '__main__':
    unittest.main()
