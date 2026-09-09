"""Exercise actual Tk controls off-screen without sending input to the game."""
import copy
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
import weakref
from unittest.mock import patch

import loot_overlay
from test_upgrade import fixture


class UIUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        fixture(self.directory)
        self.base = patch.object(loot_overlay, 'BASE', self.directory)
        self.base.start()
        self.overlay = loot_overlay.Overlay()
        self.overlay.root.geometry('440x660+0+0')
        self.overlay.root.attributes('-alpha', 0)
        self.overlay.root.deiconify()
        self.overlay.apply_visibility()
        self.pump(.3)

    def pump(self, seconds=.06):
        self.overlay.root.after(int(seconds * 1000), self.overlay.root.quit)
        self.overlay.root.mainloop()

    def tearDown(self):
        self.overlay.close()
        self.base.stop()
        self.tmp.cleanup()

    def test_buttons_reopen_without_mouse_grab(self):
        for _ in range(4):
            self.overlay.display_button.invoke()
            self.assertTrue(self.overlay.display_popup.winfo_exists())
            self.assertIsNone(self.overlay.root.grab_current())
            self.overlay.settings_button.invoke()
            self.overlay.popup.attributes('-alpha', 0)
            self.assertTrue(self.overlay.popup.winfo_exists())
            self.assertIsNone(self.overlay.root.grab_current())
            self.overlay.popup.destroy()

    def test_native_combobox_popup_does_not_interrupt_marker_refresh(self):
        from tkinter import ttk
        combo = ttk.Combobox(self.overlay.root, values=('one', 'two'), state='readonly')
        combo.pack()
        self.overlay.root.update_idletasks()
        try:
            self.overlay.root.tk.call('ttk::combobox::Post', str(combo))
            popdown = self.overlay.root.tk.call('ttk::combobox::PopdownWindow', str(combo))
            self.overlay.root.tk.call('wm', 'deiconify', popdown)
            self.overlay.root.update_idletasks()
            self.overlay.root.tk.call('grab', 'set', popdown)
            self.assertIn('popdown', str(self.overlay.root.tk.call('grab', 'current', self.overlay.root._w)))
            self.overlay.next_status = 0
            self.overlay.tick()
            self.assertIsNone(self.overlay.last_error)
        finally:
            self.overlay.root.tk.call('ttk::combobox::Unpost', str(combo))
            combo.destroy()

    def test_shared_main_window_opens_native_page_without_installing_or_changing_settings(self):
        from startup_window import StartupWindow
        before = self.overlay.read_file('loot-overlay-settings.json', {})
        guide = StartupWindow(self.overlay, r'D:\Steam\Ruins of Dawn\RuinsOfDawn.exe', '0.3.0', show=False)
        try:
            with patch('native_support.install') as install:
                guide.open_native()
                dialog = self.overlay.settings_dialog
                dialog.window.attributes('-alpha', 0)
                self.pump(.05)
                self.assertEqual(dialog.features.select(), str(dialog.native_settings.tab))
                dialog.features.select(dialog.filter_page)
                guide.open_native()
                self.assertIs(dialog, self.overlay.settings_dialog)
                self.assertEqual(dialog.features.select(), str(dialog.native_settings.tab))
                install.assert_not_called()
            self.assertEqual(self.overlay.read_file('loot-overlay-settings.json', {}), before)
            self.assertIsNone(self.overlay.root.grab_current())
        finally:
            guide.window.destroy()

    def test_lower_checkbox_remains_off_through_background_save_and_reopen(self):
        o = self.overlay
        o.display_button.invoke()
        check = next(w for w in o.display_popup.winfo_children()
                     if isinstance(w, tk.Checkbutton) and w.cget('text') == '下技能')
        entered, unblock = threading.Event(), threading.Event()
        original = Path.write_text

        def slow_write(path, *args, **kwargs):
            if path.name == 'loot-overlay-settings.display.tmp':
                entered.set()
                if not unblock.wait(3):
                    raise TimeoutError('checkbox test did not release writer')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'write_text', slow_write):
            try:
                check.invoke()
                self.assertTrue(entered.wait(1))
                self.pump(.35)
                self.assertFalse(o.section_vars['lower'].get())
                self.assertNotIn('lower', o.panes.visible_keys)
            finally:
                unblock.set()
        self.pump(.2)
        o.display_popup.destroy()
        o.display_button.invoke()
        self.assertFalse(o.section_vars['lower'].get())
        self.assertNotIn('lower', o.panes.visible_keys)

    def test_scrollbar_hides_for_empty_text_scrolls_overflow_and_preserves_scroll(self):
        o = self.overlay
        sections = loot_overlay.empty_sections()
        o.render(sections, True)
        self.pump()
        self.assertFalse(o.numeric.scrollbar.shown)
        sections['numeric'] = [dict(index=i, hits=[dict(label='法术伤害', display='29%')]) for i in range(60)]
        o.render(sections, True)
        self.pump()
        self.assertTrue(o.numeric.scrollbar.shown)
        o.numeric.event_generate('<MouseWheel>', delta=-120)
        self.pump()
        self.assertGreater(o.numeric.yview()[0], 0)
        o.numeric.yview_moveto(.45)
        before = o.numeric.yview()[0]
        o.render(sections, True)
        self.pump()
        self.assertAlmostEqual(o.numeric.yview()[0], before, delta=.01)

    def test_numeric_auto_lock_notice_renders_beside_current_position(self):
        sections = loot_overlay.empty_sections()
        sections['numeric'] = [dict(index=4, auto_locked=True, hits=[dict(label='法术伤害', display='29%')]),
                               dict(index=7, hits=[dict(label='暴击伤害', display='44%')])]
        self.overlay.render(sections, True)
        rows = self.overlay.numeric.runs
        self.assertIn('（已自动锁定，10 秒后不显示）', rows[0][0])
        self.assertEqual(rows[1][0], '法术伤害 29%')
        self.assertNotIn('已自动锁定', rows[2][0])

    def test_tick_has_no_file_io_and_remains_fast_during_drag(self):
        o = self.overlay
        o.panes.start_drag(0, 100)
        with patch.object(loot_overlay, 'load', side_effect=AssertionError('Tk must not open files')), \
             patch.object(loot_overlay, 'write_json', side_effect=AssertionError('Tk must not write files')):
            before = time.perf_counter()
            for _ in range(30):
                o.tick()
            elapsed = time.perf_counter() - before
        self.assertLess(elapsed, .5)
        self.assertIsNone(o.last_error)
        o.panes.release()

    def test_fully_opaque_window_does_not_fail_native_transparency(self):
        o = self.overlay
        o.hwnd = loot_overlay.u.GetAncestor(o.root.winfo_id(), 2)
        o.settings.update(opacity=1.0, transparent_background=False)
        o.appearance_key = None
        # Tk may remove WS_EX_LAYERED after mapping a fully opaque window.
        style = loot_overlay.u.GetWindowLongPtrW(o.hwnd, -20)
        loot_overlay.u.SetWindowLongPtrW(o.hwnd, -20, style & ~0x80000)
        o.apply_appearance()
        self.assertTrue(loot_overlay.u.GetWindowLongPtrW(o.hwnd, -20) & 0x80000)

    def test_transparency_switch_updates_native_color_key_and_all_canvas_backgrounds(self):
        o = self.overlay
        o.hwnd = loot_overlay.u.GetAncestor(o.root.winfo_id(), 2)
        native_read = loot_overlay.u.GetLayeredWindowAttributes
        native_read.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
                                ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD)]
        native_read.restype = wintypes.BOOL
        for enabled in (True, False, True):
            o.settings.update(opacity=1., transparent_background=enabled)
            o.write_file('loot-overlay-settings.json', o.settings)
            o.apply_appearance()
            self.pump(.04)
            color, alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(), wintypes.DWORD()
            self.assertTrue(native_read(o.hwnd, ctypes.byref(color), ctypes.byref(alpha), ctypes.byref(flags)))
            self.assertEqual(flags.value & 1, int(enabled))
            self.assertEqual(o.panes.transparent, enabled)
            if enabled:
                self.assertEqual(color.value, 0x241A11)
                for key in o.panes.visible_keys:
                    item = o.panes.items[(key, 'bg')][0]
                    self.assertEqual(o.panes.itemcget(item, 'fill'), '#111a24')

    def test_close_releases_overlay_tcl_objects_before_next_reader_thread(self):
        o = self.overlay
        refs = [weakref.ref(value) for value in o.section_vars.values()]
        if o.panes.sash_image is not None:
            refs.append(weakref.ref(o.panes.sash_image))
        o.close()
        self.assertTrue(all(ref() is None for ref in refs))


if __name__ == '__main__':
    unittest.main()
