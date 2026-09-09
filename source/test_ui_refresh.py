import copy
import tkinter as tk
import unittest

from gear_view import DEFAULT_RULES
from overlay_settings import Settings


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES),
                      'loot-overlay-settings.json': {'native': {'lock': True}}}
        class Host:
            pass
        self.host = Host()
        self.host.root = self.root
        self.host.read_file = lambda name, default=None: copy.deepcopy(self.files.get(name, default))
        self.host.write_file = lambda name, value: self.files.__setitem__(name, value)
        self.dialog = Settings(self.host, show=False)

    def tearDown(self):
        self.root.destroy()

    def test_save_remains_open_and_lower_selection_can_be_cleared(self):
        d = self.dialog
        d.lower_enabled.set(False)
        self.assertEqual(d.notice.cget('text'), '有未保存的更改')
        d.apply()
        self.assertTrue(d.window.winfo_exists())
        self.assertFalse(self.files['loot-overlay-settings.json']['lower_enabled'])
        self.assertEqual(d.notice.cget('text'), '已保存')

    def test_lock_off_disables_recycle_but_keeps_bagua_preference(self):
        n = self.dialog.native_settings
        n.auto_recycle.set(True)
        n.bagua.set(True)
        n.lock.set(False)
        self.dialog.apply()
        saved = self.files['loot-overlay-settings.json']['native']
        self.assertFalse(saved['auto_recycle'])
        self.assertTrue(saved['bagua_marker'])

    def test_page_navigation_retains_edited_threshold(self):
        d = self.dialog
        d.minimum_vars[0].set('87')
        d.features.select(d.author_tab)
        d.features.select(d.filter_page)
        self.assertEqual(d.minimum_vars[0].get(), '87')
        self.assertTrue(d.transparent.get())

    def test_lock_and_recycle_share_card(self):
        n = self.dialog.native_settings
        self.assertIs(n.lock_card, n.recycle_card)
        self.assertEqual(n.recycle_check.cget('state'), 'normal')

    def test_cold_background_feed_does_not_reset_saved_preferences(self):
        from unittest.mock import patch
        saved = {'native': {'lock': True, 'bagua_marker': True}, 'font_size': 15,
                 'lower_enabled': False}
        self.host.feed = object()
        self.host.read_file = lambda *args: None
        with patch('loot_overlay.load', side_effect=lambda name: saved if name == 'loot-overlay-settings.json' else None):
            dialog = Settings(self.host, show=False)
        try:
            self.assertTrue(dialog.native_settings.bagua.get())
            self.assertEqual(dialog.font_size.get(), 15)
            self.assertFalse(dialog.lower_enabled.get())
        finally:
            dialog.cancel()


if __name__ == '__main__':
    unittest.main()
