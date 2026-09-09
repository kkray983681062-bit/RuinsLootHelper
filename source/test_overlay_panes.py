"""Native Tk split layout regression; an invisible fixture never drives the game."""
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from overlay_panes import SectionPanes


class PaneTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes('-alpha', 0.0)
        self.root.geometry('420x650+0+0')
        self.mouse_patch = patch('overlay_panes.read_pointer', return_value=(0, 0, False, 0), create=True)
        self.mouse = self.mouse_patch.start()
        self.addCleanup(self.mouse_patch.stop)
        self.saved = []
        self.pane = SectionPanes(self.root, on_layout=lambda value: self.saved.append(value))
        self.pane.pack(fill='both', expand=True)
        for key in ('numeric', 'legendary', 'lower'):
            self.pane.register(key, key)
        self.pane.set_visible(['numeric', 'legendary', 'lower'])
        self.root.deiconify()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def drag(self, index, pixels):
        start = self.pane.sash_coord(index)[1] + self.pane.hit_width // 2
        x = self.pane.winfo_rootx() + 150
        y = self.pane.winfo_rooty() + start
        self.mouse.return_value = (x, y, True, self.pane.winfo_id())
        self.pane.event_generate('<ButtonPress-1>', x=150, y=start)
        self.root.update()
        self.pane.event_generate('<B1-Motion>', x=150, y=start + pixels, state=0x100)
        self.mouse.return_value = (x, y + pixels, True, self.pane.winfo_id())
        self.root.update()
        self.mouse.return_value = (x, y + pixels, False, self.pane.winfo_id())
        self.pane.event_generate('<ButtonRelease-1>', x=150, y=start + pixels)
        self.root.update()

    def heights(self):
        return [self.pane.sections[key].winfo_height() for key in self.pane.visible_keys]

    def pointer_step(self, x, y, down, hwnd):
        self.mouse.return_value = (x, y, down, hwnd)
        self.root.after(35, self.root.quit)
        self.root.mainloop()

    def test_physical_pointer_drag_works_without_any_tk_button_event(self):
        x = self.pane.winfo_rootx() + 150
        y = self.pane.winfo_rooty() + self.pane.sash_coord(1)[1] + 4
        hwnd = self.pane.winfo_id()
        before = self.heights()
        self.pointer_step(x, y, False, hwnd)
        self.pointer_step(x, y, True, hwnd)
        self.pointer_step(x, y - 45, True, 0)  # Leave the line while holding.
        self.pointer_step(x, y - 45, False, 0)
        self.assertEqual(self.heights(), [before[0], before[1] - 45, before[2] + 45])
        self.assertIsNone(self.pane.dragging)
        self.assertIn('numeric|legendary|lower', self.saved[-1])
        # A second independent press must work after release as well.
        self.pointer_step(x, y - 45, True, hwnd)
        self.pointer_step(x, y - 20, True, 0)
        self.pointer_step(x, y - 20, False, 0)
        self.assertEqual(self.heights(), [before[0], before[1] - 20, before[2] + 20])

    def test_drag_cannot_start_in_game_or_by_crossing_line_with_button_already_held(self):
        x = self.pane.winfo_rootx() + 150
        y = self.pane.winfo_rooty() + self.pane.sash_coord(1)[1] + 4
        before = self.heights()
        self.pointer_step(x, y, True, 0)
        self.pointer_step(x, y, True, self.pane.winfo_id())
        self.pointer_step(x, y - 40, True, 0)
        self.pointer_step(x, y - 40, False, 0)
        self.assertEqual(self.heights(), before)

    def test_queued_old_motion_cannot_pull_divider_back_from_current_pointer(self):
        x = self.pane.winfo_rootx() + 150
        start = self.pane.sash_coord(1)[1] + 4
        y = self.pane.winfo_rooty() + start
        hwnd = self.pane.winfo_id()
        self.pointer_step(x, y, True, hwnd)
        self.pointer_step(x, y - 50, True, hwnd)
        current = self.pane.sashpos(1)
        # Windows has already advanced; an older queued Tk event arrives late.
        self.pane.motion(SimpleNamespace(y_root=y - 10))
        self.assertEqual(self.pane.sashpos(1), current)
        self.pointer_step(x, y - 50, False, hwnd)

    def test_one_painted_line_and_wide_target_without_child_window_relayout(self):
        self.assertEqual(self.pane.winfo_children(), [])
        self.assertEqual(self.pane.line_width, 1)
        self.assertGreaterEqual(self.pane.hit_width, 9)
        for i in range(2):
            sash = self.pane.sash_coord(i)[1]
            for offset in range(self.pane.hit_width):
                self.assertEqual(self.pane.identify(150, sash + offset), i)
        lines = [item for item in self.pane.find_withtag('sashes') if self.pane.type(item) == 'line']
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(float(self.pane.itemcget(item, 'width')) == 1 for item in lines))

    def test_scroll_thumb_drag_scrolls_only_its_section_and_reaches_end(self):
        numeric = self.pane.sections['numeric']
        numeric.set_runs([(f'装备第 {i} 条 法术伤害 29%', 'hit') for i in range(100)])
        self.root.update()
        self.assertTrue(numeric.shown)
        top, height, _ = numeric.thumb()
        x = self.pane.winfo_rootx() + self.pane.winfo_width() - 8
        y = self.pane.winfo_rooty() + top + height / 2
        hwnd = self.pane.winfo_id()
        self.pointer_step(x, y, False, hwnd)
        self.pointer_step(x, y, True, hwnd)
        self.pointer_step(x, y + 70, True, hwnd)
        self.assertGreater(numeric.yview()[0], .1)
        self.assertEqual(self.pane.sections['lower'].yview()[0], 0)
        self.pointer_step(x, y + 2000, True, 0)
        self.pointer_step(x, y + 2000, False, 0)
        self.assertAlmostEqual(numeric.yview()[1], 1.)
        self.assertIsNone(self.pane.scroll_drag)
        drawn_text = [self.pane.itemcget(item, 'text') for item in self.pane.find_withtag('numeric-rows')
                      if self.pane.itemcget(item, 'state') != 'hidden']
        self.assertIn('装备第 99 条 法术伤害 29%', drawn_text)

    def test_transparent_mode_clears_every_section_background_but_keeps_controls(self):
        self.pane.set_transparent(True)
        self.root.update()
        for key in self.pane.visible_keys:
            for layer in ('bg', 'header'):
                ident = self.pane.items[(key, layer)][0]
                self.assertEqual(self.pane.itemcget(ident, 'fill'), self.pane.cget('bg'))
        line = self.pane.items[('sash', 0)][0]
        self.assertNotEqual(self.pane.itemcget(line, 'fill'), self.pane.cget('bg'))
        self.pane.set_transparent(False)
        self.root.update()
        ident = self.pane.items[('numeric', 'bg')][0]
        self.assertNotEqual(self.pane.itemcget(ident, 'fill'), self.pane.cget('bg'))

    def test_transparent_separator_keeps_wide_hit_area_without_stealing_covered_clicks(self):
        self.pane.set_transparent(True)
        self.root.update()
        x = self.pane.winfo_rootx() + 150
        y = self.pane.winfo_rooty() + self.pane.sashpos(1) + 1
        before = self.heights()
        # The transparent gap itself hits the game. Its one-pixel line must
        # still belong to our surface before accepting the wider mouse target.
        with patch('overlay_panes.window_at', return_value=self.pane.winfo_id()):
            self.pointer_step(x, y, False, 777)
            self.pointer_step(x, y, True, 777)
            self.pointer_step(x, y - 35, True, 0)
            self.pointer_step(x, y - 35, False, 0)
        self.assertEqual(self.heights(), [before[0], before[1] - 35, before[2] + 35])
        with patch('overlay_panes.window_at', return_value=888):
            self.pointer_step(x, y - 35, True, 888)
            self.assertIsNone(self.pane.dragging)
            self.pointer_step(x, y - 35, False, 888)

    def test_repeated_lower_drag_changes_only_adjacent_regions_and_keeps_after_refresh(self):
        for delta in (-50, 30, -20):
            before = self.heights()
            self.drag(1, delta)
            self.assertEqual(self.heights(), [before[0], before[1] + delta, before[2] - delta])
            self.assertIsNone(self.pane.dragging)
            self.assertIsNone(self.root.grab_current())
            for _ in range(5):
                self.pane.set_visible(['numeric', 'legendary', 'lower'])
                self.root.update()
            self.assertEqual(self.heights(), [before[0], before[1] + delta, before[2] - delta])
        self.assertIn('numeric|legendary|lower', self.saved[-1])

    def test_native_geometry_and_saved_proportions_survive_resize_and_section_toggle(self):
        self.drag(1, -40)
        adjusted = self.pane.sash_coord(1)[1]
        self.pane.set_visible(['numeric', 'lower'])
        self.root.update()
        self.drag(0, -20)
        self.pane.set_visible(['numeric', 'legendary', 'lower'])
        self.root.update()
        self.assertAlmostEqual(self.pane.sash_coord(1)[1], adjusted, delta=1)
        for height in (480, 749, 550):
            self.root.geometry(f'437x{height}+0+0')
            self.root.update()
            for i, key in enumerate(self.pane.visible_keys[:-1]):
                upper = self.pane.sections[key]
                lower = self.pane.sections[self.pane.visible_keys[i + 1]]
                sash = self.pane.sash_coord(i)[1]
                self.assertEqual(upper.winfo_y() + upper.winfo_height(), sash)
                self.assertEqual(lower.winfo_y(), sash + self.pane.hit_width)
            self.drag(1, -10)
        first = self.pane.sash_coord(0)[1]
        self.pane.sash_place(1, 0, first - 100)
        self.root.update()
        self.assertEqual(self.pane.sections['legendary'].winfo_height(), 64)
        self.pane.set_visible([])
        self.root.update()
        self.assertEqual(len(self.pane.panes()), 0)
        self.pane.set_visible(['lower'])
        self.root.update()
        self.assertEqual(self.pane.sections['lower'].winfo_height(), self.pane.winfo_height())


if __name__ == '__main__':
    unittest.main()
