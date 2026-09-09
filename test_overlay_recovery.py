"""A brief reader-file replacement must not leave a live HUD showing old errors."""
import datetime
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch

import loot_overlay as hud


class RecoveryTests(unittest.TestCase):
    def test_same_snapshot_renders_again_after_a_failed_read(self):
        overlay = hud.Overlay.__new__(hud.Overlay)
        overlay.root = Mock()
        overlay.status_label = Mock()
        overlay.panes = Mock(visible_keys=(), dragging=None)
        overlay.markers = Mock()
        overlay.calibrating = False
        overlay.game = overlay.hwnd = None
        overlay.placed = False
        overlay.settings = {}
        overlay.last_render = overlay.last_error = None
        overlay.next_status = float('inf')
        overlay.render = Mock()
        overlay.apply_visibility = Mock()
        overlay.apply_appearance = Mock()
        overlay.read_file = Mock(return_value={})
        overlay.write_file = Mock()
        from overlay_feed import Snapshot
        overlay.feed = Mock()
        overlay.feed.snapshot = Snapshot(live=True)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        files = {'continuous-status.json': {'status': 'watching', 'heartbeat_utc': now, 'game_pid': 1},
                 'current-loot.json': {'status': 'watching', 'backpack_free_slots': 42},
                 'loot-overlay-settings.json': {}}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(hud, 'BASE', pathlib.Path(directory)), \
             patch.object(hud, 'load', side_effect=files.__getitem__) as load, \
             patch.object(hud, 'write_json'), patch.object(hud, 'find_game', return_value=None), \
             patch.object(hud, 'configured_rules', return_value=[]), \
             patch.object(hud, 'select_sections', return_value=hud.empty_sections()):
            overlay.tick()
            overlay.feed.snapshot = Snapshot(live=False, error='read failed')
            overlay.tick()
            self.assertFalse(overlay.render.call_args.args[1])
            overlay.feed.snapshot = Snapshot(live=True)
            overlay.tick()
            self.assertTrue(overlay.render.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
