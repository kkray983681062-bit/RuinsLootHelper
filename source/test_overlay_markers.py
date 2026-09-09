import datetime
import time
import unittest
import tkinter as tk
from unittest.mock import Mock, patch
import overlay_markers as markers


class MarkerTests(unittest.TestCase):
    def test_native_layer_maps_canvas_without_taking_focus_or_mouse(self):
        root = tk.Tk()
        root.withdraw()
        layer = markers.MarkerLayer(root)
        feature = {'status': 'running', 'game_pid': 123,
                   'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'ui': {'valid': True, 'backpack_open': True}}
        try:
            with patch.object(markers, 'game_bounds', return_value=(-10000, -10000, 600, 400)), \
                 patch.object(markers, 'foreground_matches', return_value=True):
                layer.update(1, {'enabled': True, 'grid': [.1, .1, .5, .6]},
                             {'numeric': [{'index': 39}]}, True, feature)
                root.update()
                style = markers.u.GetWindowLongPtrW(layer.hwnd, -20)
                self.assertEqual(style & (0x80000 | 0x20 | 0x08000000), 0x80000 | 0x20 | 0x08000000)
                self.assertNotEqual(markers.u.GetForegroundWindow(), layer.hwnd)
                self.assertTrue(layer.canvas.winfo_ismapped())
                self.assertEqual(len(layer.canvas.find_all()), 2)
                self.assertEqual(layer.canvas.coords(layer.canvas.find_all()[-1]), [333, 163, 357, 197])
                layer.update(1, {'enabled': True, 'grid': [.1, .1, .5, .6]}, {}, True, feature)
                self.assertFalse(layer.visible)
                self.assertEqual(layer.canvas.find_all(), ())
        finally:
            layer.close()
            root.destroy()

    def test_current_slots_only_and_selected_sections(self):
        sections = {'numeric': [{'index': 39}, {'index': 4, 'locked': True}, {'index': 60}],
                    'legendary': [{'index': 39}, {'index': 12}], 'lower': [{'index': 17}]}
        self.assertEqual(markers.marker_slots(sections, {'sections': {'lower': False}}), [12, 39])
        self.assertEqual(markers.marker_slots({'numeric': [{'index': 3}]}, {}), [3])
        self.assertEqual(markers.marker_slots({}, {}), [])

    def test_closing_bag_or_losing_fresh_state_clears_layer(self):
        layer = markers.MarkerLayer.__new__(markers.MarkerLayer)
        layer.window = Mock()
        layer.canvas = Mock()
        layer.hwnd = 2
        layer.visible = False
        layer.last_key = None
        layer.slots = []
        layer.reason = None
        feature = {'status': 'running', 'game_pid': 123,
                   'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'ui': {'valid': True, 'backpack_open': True}}
        config = {'enabled': True, 'grid': [0, 0, .5, .5]}
        sections = {'numeric': [{'index': 39}]}
        with patch.object(markers, 'game_bounds', return_value=(10, 20, 1000, 800)), \
             patch.object(markers, 'foreground_matches', return_value=True), patch.object(markers, 'u'):
            layer.update(1, config, sections, True, feature)
            self.assertEqual(layer.slots, [39])
            layer.update(1, config, {}, True, feature)
            self.assertEqual(layer.slots, [])
            feature['ui']['backpack_open'] = False
            layer.update(1, config, sections, True, feature)
            self.assertFalse(layer.visible)
            feature['ui']['backpack_open'] = True
            feature['heartbeat_utc'] = '2000-01-01T00:00:00+00:00'
            layer.update(1, config, sections, True, feature)
            self.assertEqual(layer.slots, [])

    def test_automatic_mode_never_reuses_static_calibration_when_live_grid_is_missing(self):
        layer = markers.MarkerLayer.__new__(markers.MarkerLayer)
        layer.window, layer.canvas = Mock(), Mock()
        layer.hwnd, layer.visible, layer.last_key = 2, False, None
        layer.slots = []
        feature = {'status': 'running', 'game_pid': 123,
                   'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'ui': {'valid': True, 'backpack_open': True, 'player_address': 88}}
        with patch.object(markers, 'game_bounds', return_value=(10, 20, 1000, 800)), \
             patch.object(markers, 'foreground_matches', return_value=True), patch.object(markers, 'u'):
            layer.update(1, {'enabled': True, 'automatic': True, 'grid': [0, 0, .5, .5]},
                         {'numeric': [{'index': 39}]}, True, feature)
            self.assertFalse(layer.visible)
            self.assertEqual(layer.slots, [])
            self.assertIn('自动识别', layer.reason)
            layer.canvas.create_oval.assert_not_called()
            layer.update(1, {'enabled': True, 'automatic': True},
                         {'numeric': [{'index': 39}]}, True, feature)
            self.assertFalse(layer.visible, 'no saved or native coordinates means no guessed circles')

    def test_unlock_restores_circle_and_follows_item_move_with_automatic_grid(self):
        from gear_view import select_sections
        layer = markers.MarkerLayer.__new__(markers.MarkerLayer)
        layer.window, layer.canvas = Mock(), Mock()
        layer.hwnd, layer.visible, layer.last_key = 2, False, None
        layer.slots = []
        native = {'game_pid': 123, 'player_address': 88, 'utc': time.time(),
                  'grid': {'viewport': [1200, 900], 'slots': {
                      str(i): [100+i%10*60, 100+i//10*60, 154+i%10*60, 154+i//10*60]
                      for i in range(60)}}}
        feature = {'status': 'running', 'game_pid': 123,
                   'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'ui': {'valid': True, 'backpack_open': True, 'player_address': 88},
                   'native': native}
        config = {'enabled': True, 'automatic': True, 'grid': [0, 0, .5, .5]}
        item = {'名字': '项链', '锁定': False, '极品属性': {'特殊属性': {'幸运': 4}}}
        entry = {'index': 44, 'item': item}
        payload = {'items': [entry]}
        layer.automatic_boxes = lambda *_: {int(k): tuple(v) for k,v in native['grid']['slots'].items()}
        with patch.object(markers, 'game_bounds', return_value=(10, 20, 1200, 900)), \
             patch.object(markers, 'foreground_matches', return_value=True), patch.object(markers, 'u'):
            layer.update(1, config, select_sections(payload), True, feature)
            self.assertEqual(layer.slots, [44])
            layer.canvas.create_oval.assert_called_with(344, 344, 390, 390, outline='#ffdb62', width=3)
            item['锁定'] = True
            layer.update(1, config, select_sections(payload), True, feature)
            self.assertEqual(layer.slots, [])
            item['锁定'] = False
            layer.update(1, config, select_sections(payload), True, feature)
            self.assertEqual(layer.slots, [44])
            self.assertTrue(layer.visible)
            for box in native['grid']['slots'].values():
                box[0] += 170
                box[2] += 170
                box[1] += 85
                box[3] += 85
            layer.update(1, config, select_sections(payload), True, feature)
            layer.canvas.create_oval.assert_called_with(514, 429, 560, 475, outline='#ffdb62', width=3)
            entry['index'] = 41
            layer.update(1, config, select_sections(payload), True, feature)
            self.assertEqual(layer.slots, [41])
            payload['items'].clear()
            layer.update(1, config, select_sections(payload), True, feature)
            self.assertEqual(layer.slots, [])


if __name__ == '__main__':
    unittest.main()
