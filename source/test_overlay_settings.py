import copy
import tkinter as tk
import unittest
import weakref
from gear_view import DEFAULT_RULES
from overlay_settings import Settings


class SettingsTests(unittest.TestCase):
    def test_closed_settings_release_tk_variables_on_ui_thread(self):
        root = tk.Tk()
        root.withdraw()
        class Host:
            def read_file(self, name, default=None):return copy.deepcopy(DEFAULT_RULES) if name == 'loot-filter-rules.json' else {}
            def write_file(self, name, value):pass
        host = Host()
        host.root = root
        try:
            dialog = Settings(host, show=False)
            refs = [weakref.ref(dialog.enabled_vars[0]), weakref.ref(dialog.native_settings.pickup),
                    weakref.ref(dialog.feature_settings.marker_enabled)]
            dialog.cancel()
            self.assertTrue(all(ref() is None for ref in refs))
        finally:
            root.destroy()

    def test_apply_button_stays_inside_every_page_at_small_window_sizes(self):
        root = tk.Tk()
        root.withdraw()
        class Host:
            def read_file(self, name, default=None):
                return copy.deepcopy(DEFAULT_RULES) if name == 'loot-filter-rules.json' else {}
            def write_file(self, name, value):
                pass
        host = Host()
        host.root = root
        try:
            dialog = Settings(host, show=False)
            buttons = [child for frame in dialog.window.winfo_children() for child in frame.winfo_children()
                       if isinstance(child, tk.Button) and child.cget('text') == '保存设置']
            self.assertEqual(len(buttons), 1)
            apply = buttons[0]
            dialog.window.geometry('720x610+-10000+-10000')
            dialog.window.deiconify()
            for width, height in ((720, 610), (590, 460), (1000, 800)):
                dialog.window.geometry(f'{width}x{height}+-10000+-10000')
                for tab in dialog.features.tabs():
                    dialog.features.select(tab)
                    root.update()
                    self.assertTrue(apply.winfo_ismapped(), f'Apply hidden on {dialog.features.tab(tab, "text")} at {width}x{height}')
                    top = apply.winfo_rooty() - dialog.window.winfo_rooty()
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(top + apply.winfo_height(), dialog.window.winfo_height())
                    self.assertGreaterEqual(apply.winfo_height(), 25)
                    self.assertLessEqual(dialog.features.winfo_y() + dialog.features.winfo_height(), apply.master.winfo_y())
                    if tab == str(dialog.native_settings.tab):
                        native = dialog.native_settings
                        native.canvas.yview_moveto(1)
                        root.update()
                        check = native.borderless_check
                        self.assertGreaterEqual(check.winfo_rooty(), native.canvas.winfo_rooty())
                        self.assertLessEqual(check.winfo_rooty() + check.winfo_height(),
                                             native.canvas.winfo_rooty() + native.canvas.winfo_height())
        finally:
            root.destroy()

    def test_categories_keep_values_and_apply_tier_slot_pairs_independently(self):
        root = tk.Tk()
        root.withdraw()
        files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES), 'loot-overlay-settings.json': {'opacity': .9, 'auto_pickup': {'enabled': True, 'key': 'F'}}}
        class Host:
            def read_file(self, name, default=None):
                return copy.deepcopy(files.get(name, default))
            def write_file(self, name, value):
                files[name] = value
        host = Host()
        host.root = root
        try:
            dialog = Settings(host, show=False)
            self.assertEqual(dialog.window.title(), '破晓装备助手 · 功能设置')
            self.assertEqual([dialog.features.tab(tab, 'text') for tab in dialog.features.tabs()],
                             ['装备筛选', '背包定位', '进阶辅助', '自动锁定', '悬浮窗', '作者的话', '项目与更新', '掉落屏蔽清单'])
            self.assertIn(str(dialog.lock_library.tab), dialog.features.buttons)
            self.assertIn('下技能', [dialog.tabs.tab(tab, 'text') for tab in dialog.tabs.tabs()])
            self.assertEqual(len(dialog.enabled_vars), 74)
            self.assertEqual(sum(x.get() for x in dialog.enabled_vars), 11)
            self.assertEqual([x['label'] for x in dialog.types], ['武器', '项链', '戒指', '宝物'])
            self.assertEqual(len(dialog.pair_vars), 24)
            self.assertEqual(sum(x.get() for x in dialog.pair_vars.values()), 4)
            dialog.choose_pairs('t6')
            self.assertEqual(
                [key for key, variable in dialog.pair_vars.items() if variable.get()],
                ['10:1', '10:4', '10:6', '10:9'],
            )
            dialog.query.set('物理伤害')
            i = next(i for i, x in enumerate(dialog.rules) if x['field'] == '近战伤害增加')
            dialog.enabled_vars[i].set(True)
            dialog.minimum_vars[i].set('29')
            dialog.query.set('法术')
            dialog.choose_pairs('none')
            dialog.pair_vars['8:1'].set(True)
            dialog.pair_vars['9:4'].set(True)
            dialog.pair_vars['10:1'].set(True)
            dialog.transparent.set(True)
            dialog.choose_lower_skills(False)
            dialog.lower_skill_vars[11].set(True)
            dialog.lower_skill_vars[83].set(True)
            dialog.feature_settings.marker_enabled.set(True)
            dialog.feature_settings.grid = [.01, .18, .37, .39]
            dialog.feature_settings.marker_sections['lower'].set(False)
            dialog.native_settings.range_choice.set(1.5)
            dialog.native_settings.interval_choice.set(.5)
            dialog.native_settings.batch_choice.set(3)
            library = dialog.pickup_library
            library.all_codex_check.invoke()
            library.query.set('追风')
            library.tier.set('T5')
            library.part.set('武器')
            library.redraw()
            self.assertEqual(library.tree.get_children(), ('9:1:追风',))
            library.toggle('9:1:追风')
            self.assertEqual(library.tree.item('9:1:追风', 'values')[0], '☑')
            library.query.set('树叶')
            library.redraw()
            self.assertIn('9:1:追风', library.model.selected)
            library.category.set('图鉴')
            library.query.set('人形地魔')
            library.redraw()
            self.assertEqual(library.tree.get_children(), ('codex:人形地魔',))
            library.toggle('codex:人形地魔')
            dialog.apply()
            saved = next(x for x in files['loot-filter-rules.json'] if x['field'] == '近战伤害增加')
            self.assertEqual((saved['min'], saved['enabled']), (29, True))
            self.assertEqual(files['loot-overlay-settings.json']['legendary_pairs'], ['8:1', '9:4', '10:1'])
            self.assertEqual(files['loot-overlay-settings.json']['lower_skill_ids'], [11, 83])
            self.assertTrue(files['loot-overlay-settings.json']['lower_enabled'])
            self.assertNotIn('auto_pickup', files['loot-overlay-settings.json'])
            self.assertEqual(files['loot-overlay-settings.json']['backpack_markers']['grid'], [.01, .18, .37, .39])
            self.assertFalse(files['loot-overlay-settings.json']['backpack_markers']['sections']['lower'])
            self.assertEqual(files['loot-overlay-settings.json']['native']['pickup_range_multiplier'], 1.5)
            self.assertEqual(files['loot-overlay-settings.json']['native']['pickup_interval'], .5)
            self.assertEqual(files['loot-overlay-settings.json']['native']['pickup_batch'], 3)
            self.assertTrue(files['loot-overlay-settings.json']['native']['skip_codex'])
            self.assertEqual(files['loot-overlay-settings.json']['pickup_exclusions'], ['9:1:追风'])
            self.assertEqual(len(files['loot-overlay-settings.json']['codex_exclusions']), 62)
            self.assertNotIn('人形地魔', files['loot-overlay-settings.json']['codex_exclusions'])
            self.assertEqual(files['loot-overlay-settings.json']['codex_selection_version'], 1)
            reopened = Settings(host, show=False)
            self.assertIn('9:1:追风', reopened.pickup_library.model.selected)
            self.assertNotIn('codex:人形地魔', reopened.pickup_library.model.selected)
            self.assertEqual(reopened.native_settings.range_choice.get(), 1.5)
            self.assertEqual(reopened.native_settings.interval_choice.get(), .5)
            self.assertEqual(reopened.native_settings.batch_choice.get(), 3)
            groups = reopened.native_settings.radio_groups
            self.assertEqual([len(group) for group in groups], [3, 4, 4])
            groups[0][0].invoke()
            self.assertEqual(reopened.native_settings.range_choice.get(), 1.0)
            self.assertEqual(reopened.native_settings.interval_choice.get(), .5)
            self.assertEqual(reopened.native_settings.batch_choice.get(), 3)
            groups[2][0].invoke()
            self.assertEqual(reopened.native_settings.batch_choice.get(), 1)
            self.assertEqual(reopened.native_settings.values()['native']['pickup_batch'], 1)
            reopened.cancel()
        finally:
            root.destroy()

    def test_complete_lock_rule_persists_with_all_its_conditions(self):
        root = tk.Tk()
        root.withdraw()
        files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES), 'loot-overlay-settings.json': {}}
        class Host:
            def read_file(self, name, default=None):
                return copy.deepcopy(files.get(name, default))
            def write_file(self, name, value):
                files[name] = value
        host = Host()
        host.root = root
        try:
            dialog = Settings(host, show=False)
            self.assertTrue(hasattr(dialog, 'lock_library'))
            library = dialog.lock_library
            library.quality_vars['完美'].set(True)
            library.quality_tier_vars[10].set(True)
            library.query.set('霄引')
            library.tier.set('T6')
            library.part.set('武器')
            library.redraw()
            self.assertEqual(library.tree.get_children(), ('10:1:霄引',))
            self.assertIn('灭世', library.set_groups)
            library.query.set('')
            library.part.set('全部部位')
            library.set_group.set('灭世')
            library.redraw()
            self.assertEqual(set(library.tree.get_children()), {
                '10:2:灭世甲', '10:3:灭世头盔', '10:4:灭世项链', '10:5:灭世手镯',
                '10:6:灭世戒指', '10:7:灭世腰带', '10:8:灭世靴',
            })
            library.set_group.set('全部套装')
            library.query.set('霄引')
            library.part.set('武器')
            library.redraw()
            self.assertEqual(library.threshold_options('10:1:霄引'),
                             ('攻击下限', '攻击上限', '魔法下限', '魔法上限'))
            self.assertEqual(library.threshold_label('10:1:霄引', '魔法上限'),
                             '魔法上限（图鉴满值 48）')
            library.toggle('10:1:霄引')
            library.set_threshold('10:1:霄引', {'魔法上限': 48})
            dialog.apply()
            saved = files['loot-overlay-settings.json']['lock_library']['rules'][0]
            self.assertEqual(saved['qualities'], ['完美'])
            self.assertEqual(saved['quality_tiers'], [10])
            self.assertEqual(saved['equipment_keys'], ['10:1:霄引'])
            self.assertEqual(saved['thresholds']['10:1:霄引'], {'魔法上限': 48})
            reopened = Settings(host, show=False)
            self.assertIn('10:1:霄引', reopened.lock_library.model.selected)
            self.assertTrue(reopened.lock_library.quality_vars['完美'].get())
            self.assertTrue(reopened.lock_library.quality_tier_vars[10].get())
            self.assertEqual(reopened.lock_library.thresholds['10:1:霄引'], {'魔法上限': 48})
            reopened.cancel()
        finally:
            root.destroy()

    def test_switching_rules_and_saving_keeps_separate_conditions(self):
        from lock_library import selected_indices
        from test_lock_library import item
        root = tk.Tk(); root.withdraw()
        files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES)}
        class Host:
            def read_file(self, name, default=None): return copy.deepcopy(files.get(name, default))
            def write_file(self, name, value): files[name] = copy.deepcopy(value)
        host = Host(); host.root = root
        try:
            dialog = Settings(host, show=False)
            editor = dialog.lock_library
            editor.quality_vars['完美'].set(True)
            editor.quality_tier_vars[10].set(True)
            editor.add_rule()
            editor.query.set('霄引'); editor.redraw(); editor.toggle('10:1:霄引')
            editor.set_threshold('10:1:霄引', {'魔法上限': 48})
            editor.upper.set(True)
            editor.select_rule(0)
            self.assertTrue(editor.quality_vars['完美'].get())
            self.assertFalse(editor.upper.get())
            dialog.apply()
            reopened = Settings(host, show=False)
            reopened.lock_library.select_rule(1)
            self.assertTrue(reopened.lock_library.upper.get())
            self.assertEqual(reopened.lock_library.thresholds, {'10:1:霄引': {'魔法上限': 48}})
            rules = reopened.lock_library.values()['lock_library']
            ordinary = item(quality=1)
            self.assertEqual(selected_indices([{'index': 4, 'item': ordinary}], rules), set())
            ordinary['技能1'] = 64
            self.assertEqual(selected_indices([{'index': 4, 'item': ordinary}], rules), {4})
            reopened.cancel(); dialog.cancel()
        finally:
            root.destroy()

    def test_deleting_rule_keeps_survivor_and_equipment_name_click_does_not_toggle_scope(self):
        from types import SimpleNamespace
        root = tk.Tk(); root.withdraw()
        class Host:
            def read_file(self, name, default=None):
                return copy.deepcopy(DEFAULT_RULES) if name == 'loot-filter-rules.json' else {}
            def write_file(self, name, value): pass
        host = Host(); host.root = root
        try:
            dialog = Settings(host, show=False); editor = dialog.lock_library
            editor.quality_vars['完美'].set(True)
            editor.add_rule(); editor.upper.set(True)
            editor.select_rule(0); editor.delete_rule()
            self.assertTrue(editor.upper.get())
            self.assertFalse(editor.quality_vars['完美'].get())
            dialog.window.geometry('1000x800+-10000+-10000'); dialog.window.deiconify()
            dialog.features.select(editor.tab)
            editor.query.set('霄引'); editor.redraw(); root.update()
            box = editor.tree.bbox('10:1:霄引', 'name')
            self.assertTrue(box)
            editor.clicked(SimpleNamespace(x=box[0]+10, y=box[1]+10))
            self.assertNotIn('10:1:霄引', editor.model.selected)
            box = editor.tree.bbox('10:1:霄引', 'selected')
            editor.clicked(SimpleNamespace(x=box[0]+10, y=box[1]+10))
            self.assertIn('10:1:霄引', editor.model.selected)
            dialog.cancel()
        finally:
            root.destroy()

    def test_codex_all_checkbox_tracks_rows_and_has_no_second_enable_switch(self):
        root = tk.Tk();root.withdraw()
        class Host:
            def read_file(self, name, default=None):
                return copy.deepcopy(DEFAULT_RULES) if name == 'loot-filter-rules.json' else {}
            def write_file(self, name, value):pass
        host=Host();host.root=root
        try:
            dialog=Settings(host,show=False);library=dialog.pickup_library
            self.assertEqual(library.all_codex.get(),0)
            library.all_codex_check.invoke()
            self.assertEqual(library.all_codex.get(),1)
            library.all_codex_check.invoke()
            self.assertEqual(library.model.codex_values(),[])
            self.assertFalse(dialog.native_settings.values()['native']['skip_codex'])
            library.category.set('图鉴');library.redraw()
            library.toggle('codex:人形地魔')
            self.assertEqual(library.all_codex.get(),-1)
            self.assertTrue(dialog.native_settings.values()['native']['skip_codex'])
            self.assertIn('1 / 63',dialog.native_settings.codex_summary.cget('text'))
            library.all_codex_check.invoke()
            self.assertEqual(len(library.model.codex_values()),63)
            self.assertEqual(library.all_codex.get(),1)
            library.clear()
            self.assertEqual(library.all_codex.get(),0)
            self.assertFalse(dialog.native_settings.values()['native']['skip_codex'])
            dialog.cancel()
        finally:root.destroy()


if __name__ == '__main__':
    unittest.main()
