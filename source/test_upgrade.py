"""Regression cases for responsive UI and current-session inventory reads."""
import datetime
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch


def fixture(directory):
    from loot_app import prepare_settings
    prepare_settings(directory)
    for name, value in {
        'continuous-status.json': {'status': 'watching', 'game_pid': 123,
            'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()},
        'current-loot.json': {'status': 'watching', 'items': [], 'backpack_free_slots': 60},
        'feature-status.json': {'ui': {'valid': True, 'backpack_open': False}},
    }.items():
        (directory / name).write_text(json.dumps(value), encoding='utf8')


class FeedTests(unittest.TestCase):
    def test_unlocked_match_stays_visible_without_auto_lock_timer(self):
        from overlay_feed import OverlayFeed
        from test_native_policy import item
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            feed.submit('current-loot.json', {'status': 'watching', 'items': [item(4)]})
            for now in (0, 11, 60):
                with patch('time.monotonic', return_value=now):
                    feed.poll()
                self.assertEqual([x['index'] for x in feed.snapshot.sections['numeric']], [4])
                self.assertFalse(feed.snapshot.sections['numeric'][0].get('auto_locked'))

    def test_auto_locked_numeric_row_expires_even_when_inventory_is_unchanged(self):
        from overlay_feed import OverlayFeed
        from native_policy import AutoLockNotices, identity
        from overlay_markers import marker_slots
        from test_native_policy import item
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            notices = AutoLockNotices()
            notices.observe([item(4)], {}, 0)
            notices.sent([{'id': 'one', 'identity': identity(item(4)['item']), 'index': 4}], 0)
            notices.observe([item(4, True)], {'one': 'locked'}, 1)
            feed.native_client = Mock(pid=123, player=999, lock_notices=notices)
            feed.native_client.update.return_value = None
            feed.submit('native-schema.json', {'pid': 123})
            feed.submit('feature-status.json', {'ui': {'valid': True, 'player_address': 999}})
            feed.submit('current-loot.json', {'status': 'watching', 'items': [item(4, True)]})
            with patch('time.monotonic', return_value=2):
                feed.poll()
            rows = feed.snapshot.sections['numeric']
            self.assertEqual([x['index'] for x in rows], [4])
            self.assertTrue(rows[0]['auto_locked'])
            self.assertEqual(rows[0]['hits'][0]['display'], '29%')
            self.assertEqual(marker_slots(feed.snapshot.sections, {}), [])
            self.assertEqual(feed.snapshot.sections['legendary'], [])
            self.assertEqual(feed.snapshot.sections['lower'], [])
            with patch('time.monotonic', return_value=10.99):
                feed.poll()
                self.assertEqual(len(feed.snapshot.sections['numeric']), 1)
            with patch('time.monotonic', return_value=11):
                feed.poll()
                self.assertEqual(feed.snapshot.sections['numeric'], [])

    def test_unchecking_lower_stays_visible_to_gui_while_settings_write_is_blocked(self):
        from overlay_feed import OverlayFeed
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            feed.poll()
            name = 'loot-overlay-settings.json'
            settings = feed.read(name)
            settings['section_visibility'] = {'numeric': True, 'legendary': True, 'lower': False}
            feed.submit(name, settings)
            entered, unblock = threading.Event(), threading.Event()
            original = Path.write_text

            def slow_write(path, *args, **kwargs):
                if path.name == 'loot-overlay-settings.display.tmp':
                    entered.set()
                    if not unblock.wait(3):
                        raise TimeoutError('test failed to release settings write')
                return original(path, *args, **kwargs)

            with patch.object(Path, 'write_text', slow_write):
                thread = threading.Thread(target=feed._flush)
                thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertFalse(feed.read(name)['section_visibility']['lower'])
                    newer = feed.read(name)
                    newer['section_visibility']['legendary'] = False
                    feed.submit(name, newer)
                    self.assertFalse(feed._read_changed(name)['section_visibility']['lower'])
                finally:
                    unblock.set()
                    thread.join(3)
            feed.poll()
            saved = json.loads((directory / name).read_text(encoding='utf8'))
            self.assertEqual(saved['section_visibility'], {'numeric': True, 'legendary': False, 'lower': False})

    def test_disk_refresh_cannot_replace_a_newer_local_checkbox_change(self):
        from overlay_feed import OverlayFeed
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            feed.poll()
            name = 'loot-overlay-settings.json'
            settings = feed.read(name)
            settings['section_visibility'] = {'numeric': True, 'legendary': True, 'lower': False}
            feed.stamps.pop(name)
            original = Path.read_text

            def changed_during_read(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path.name == name:
                    feed.submit(name, settings)
                return result

            with patch.object(Path, 'read_text', changed_during_read):
                self.assertFalse(feed._read_changed(name)['section_visibility']['lower'])
            self.assertFalse(feed.read(name)['section_visibility']['lower'])

    def test_unchanged_inventory_does_not_repeat_filtering(self):
        from overlay_feed import OverlayFeed
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            with patch('overlay_feed.select_sections', return_value={'numeric': [], 'legendary': [], 'lower': []}) as select:
                feed.poll()
                feed.poll()
                feed.poll()
                self.assertEqual(select.call_count, 1)
                self.assertTrue(feed.snapshot.live)

    def test_gui_reads_latest_snapshot_without_waiting_for_blocked_disk(self):
        from overlay_feed import OverlayFeed
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            feed.poll()
            entered, unblock = threading.Event(), threading.Event()
            def slow_read(*args):
                entered.set()
                unblock.wait(2)
                return {}
            with patch.object(feed, '_read_changed', side_effect=slow_read):
                thread = threading.Thread(target=feed.poll)
                thread.start()
                self.assertTrue(entered.wait(1))
                begin = time.perf_counter()
                for _ in range(1000):
                    self.assertTrue(feed.snapshot.live)
                self.assertLess(time.perf_counter() - begin, .05)
                unblock.set()
                thread.join(2)

    def test_stale_status_clears_matches_and_queued_settings_are_immediately_visible(self):
        from overlay_feed import OverlayFeed
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            fixture(directory)
            feed = OverlayFeed(directory, start=False)
            feed.poll()
            feed.submit('loot-overlay-settings.json', {'width': 999})
            self.assertEqual(feed.read('loot-overlay-settings.json')['width'], 999)
            feed.poll()
            self.assertEqual(json.loads((directory / 'loot-overlay-settings.json').read_text())['width'], 999)
            status = feed.read('continuous-status.json')
            status['heartbeat_utc'] = '2000-01-01T00:00:00+00:00'
            feed.submit('continuous-status.json', status)
            feed.poll()
            self.assertFalse(feed.snapshot.live)


class InventoryReadTests(unittest.TestCase):
    def test_primary_backpack_only_and_unchanged_blob_decoded_once(self):
        import struct
        from release_runtime import SessionWatch
        from unittest.mock import Mock
        watch = SessionWatch.__new__(SessionWatch)
        owner = {'address': 100000, 'index': 1, 'class_address': 200000, 'flags': 0}
        watch.object_info = lambda addr: owner
        watch.next_ui = float('inf')
        watch.decode = Mock(return_value={'物品类型': 0, '名字': 'None'})
        watch.compact = Mock()
        watch._sample_cache = None
        source = {'owner': owner, 'header_address': 300000, 'stride': 32, 'type_name': 'fixture'}
        header = struct.pack('<Qii', 400000, 2000, 2000)
        sizes = []
        def read(addr, size):
            sizes.append(size)
            return header if addr == 300000 else bytes(size)
        watch.read = read
        self.assertEqual(watch.take(source), {})
        self.assertEqual(watch.take(source), {})
        self.assertEqual(watch.decode.call_count, 60)
        self.assertLessEqual(max(sizes), 60 * 32)


if __name__ == '__main__':
    unittest.main()
