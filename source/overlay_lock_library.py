"""Edit complete lock rules and their equipment scope in one place."""
import copy
import json
from pathlib import Path
import math
import tkinter as tk
from tkinter import messagebox, ttk

from gear_view import catalog_data
from lock_library import LockLibrary, QUALITY_LABELS, rules_from_settings
from overlay_scroll import AutoScrollbar
from pickup_library import EquipmentLibrary, equipment_key
from ui_theme import BG, PANEL, FG, GOLD, GREEN, MUTED


class LockLibrarySettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.groups = rules_from_settings(dialog.settings) or [{'name': '保留规则 1'}]
        self.current_rule = 0
        self.loading = True
        saved = self.groups[0]
        rows = catalog_data().get('equipment', ())
        normalized = LockLibrary(rows, saved)
        self.rows_by_key = {equipment_key(row): row for row in rows if isinstance(row, dict)}
        self.model = EquipmentLibrary(rows, list(normalized.equipment_keys))
        self.thresholds = {key: dict(values) for key, values in normalized.thresholds.items()}
        self.tab = tk.Frame(dialog.features, bg=BG)
        dialog.features.add(self.tab, text='自动锁定')
        self.canvas = tk.Canvas(self.tab, bg=BG, highlightthickness=0)
        self.page_scroll = AutoScrollbar(self.tab, self.canvas)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        body_id = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(body_id, width=event.width))
        self.body.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        dialog.label(self.body, '自动锁定', size=20, bold=True).pack(anchor='w', pady=(6, 6))
        dialog.check(self.body, '启用自动锁定', dialog.native_settings.lock, self.changed).pack(
            anchor='w', pady=(0, 6))
        dialog.label(self.body, '每条规则内全部条件同时满足。只有另外添加规则，才是多种保留方案任选其一。',
                     color=MUTED, anchor='w', wraplength=650).pack(fill='x', padx=12, pady=(0, 8))
        self.rules_list = ttk.Treeview(self.body, columns=('on', 'rule'), show='headings', height=3, selectmode='browse')
        self.rules_list.heading('on', text='启用'); self.rules_list.heading('rule', text='完整保留规则（点击编辑）')
        self.rules_list.column('on', width=55, stretch=False); self.rules_list.column('rule', width=540)
        self.rules_list.pack(fill='x', padx=12, pady=(0, 5))
        self.rules_list.bind('<<TreeviewSelect>>', self.rule_selected)
        rule_actions = tk.Frame(self.body, bg=BG); rule_actions.pack(fill='x', padx=12, pady=(0, 6))
        dialog.button(rule_actions, '另外添加规则', self.add_rule).pack(side='left')
        dialog.button(rule_actions, '删除当前规则', self.delete_rule).pack(side='left')
        self.rule_enabled = tk.BooleanVar(master=self.tab, value=saved.get('enabled', True))
        dialog.check(rule_actions, '启用当前规则', self.rule_enabled, self.changed).pack(side='left', padx=10)
        self.rule_name = tk.StringVar(master=self.tab, value=saved.get('name', '保留规则 1'))
        self.rule_name.trace_add('write', lambda *_: self.changed())
        tk.Entry(self.body, textvariable=self.rule_name, bg=PANEL, fg=FG, insertbackground=FG, relief='flat').pack(
            fill='x', padx=12, pady=(0, 8), ipady=5)

        quality_box = tk.Frame(self.body, bg=PANEL)
        quality_box.pack(fill='x', padx=12, pady=(0, 10))
        dialog.label(quality_box, '当前规则的品质与范围', size=12, bold=True).pack(anchor='w', padx=12, pady=(10, 3))
        dialog.label(quality_box, '品质与 T 级必须同时满足；下方指定装备和门槛继续收紧本条规则。',
                     color=MUTED).pack(anchor='w', padx=12, pady=(0, 4))
        self.quality_vars = {
            quality: tk.BooleanVar(master=self.tab, value=quality in normalized.qualities)
            for quality in QUALITY_LABELS
        }
        quality_row = tk.Frame(quality_box, bg=PANEL)
        quality_row.pack(fill='x', padx=12, pady=(0, 5))
        for quality in QUALITY_LABELS:
            dialog.check(quality_row, quality, self.quality_vars[quality], self.changed).pack(side='left', padx=(0, 12))
        tier_rows = {}
        for row in self.model.rows:
            tier_rows[row['tier_raw']] = row['tier']
        self.quality_tier_vars = {
            raw: tk.BooleanVar(master=self.tab, value=raw in normalized.quality_tiers)
            for raw in sorted(tier_rows, reverse=True)
        }
        tier_row = tk.Frame(quality_box, bg=PANEL)
        tier_row.pack(fill='x', padx=12, pady=(0, 10))
        dialog.label(tier_row, '限定').pack(side='left', padx=(0, 9))
        for raw, variable in self.quality_tier_vars.items():
            dialog.check(tier_row, tier_rows[raw], variable, self.changed).pack(side='left', padx=(0, 9))

        conditions = tk.Frame(self.body, bg=PANEL)
        conditions.pack(fill='x', padx=12, pady=(0, 8))
        self.set_modes = {'全部装备': 'all', '仅套装': 'set', '仅非套装': 'non_set'}
        self.set_mode = tk.StringVar(master=self.tab, value=next(k for k,v in self.set_modes.items() if v == normalized.set_mode))
        scope_line = tk.Frame(conditions, bg=PANEL); scope_line.pack(fill='x', padx=12, pady=5)
        dialog.label(scope_line, '范围').pack(side='left', padx=(0, 8))
        ttk.Combobox(scope_line, textvariable=self.set_mode, values=list(self.set_modes), state='readonly', width=12).pack(side='left')
        self.set_mode.trace_add('write', lambda *_: self.changed())
        self.upper = tk.BooleanVar(master=self.tab, value=normalized.upper)
        self.lower = tk.BooleanVar(master=self.tab, value=normalized.lower)
        self.numeric = tk.BooleanVar(master=self.tab, value=normalized.numeric)
        self.keep_all = tk.BooleanVar(master=self.tab, value=normalized.keep_all)
        self.upper_ids, self.lower_ids = list(normalized.upper_ids), list(normalized.lower_ids)
        skills = tk.Frame(conditions, bg=PANEL); skills.pack(fill='x', padx=12, pady=3)
        dialog.check(skills, '有上技能', self.upper, self.changed).pack(side='left')
        self.upper_button = dialog.button(skills, '指定上技能', lambda: self.edit_skills('upper'))
        self.upper_button.pack(side='left', padx=(0, 8))
        dialog.check(skills, '有下技能', self.lower, self.changed).pack(side='left')
        self.lower_button = dialog.button(skills, '指定下技能', lambda: self.edit_skills('lower'))
        self.lower_button.pack(side='left')
        dialog.check(conditions, '红色词条达到“装备筛选”中已勾选的任一数值门槛', self.numeric, self.changed).pack(anchor='w', padx=12)
        dialog.check(conditions, '明确保留范围内所有品质（仍须满足已勾选的其他条件）', self.keep_all, self.changed).pack(anchor='w', padx=12)
        self.legacy_vars = {key: tk.BooleanVar(master=self.tab, value=key in normalized.filter_sections)
                            for key in ('numeric', 'legendary', 'lower')}
        self.legacy_box = tk.Frame(conditions, bg=PANEL)
        for key, title in (('numeric', '词条'), ('legendary', '上技能'), ('lower', '下技能')):
            dialog.check(self.legacy_box, '沿用原有' + title + '筛选', self.legacy_vars[key], self.changed).pack(side='left')
        if normalized.filter_sections:
            self.legacy_box.pack(fill='x', padx=12, pady=4)
        self.rule_description = dialog.label(self.body, '', color=GOLD, wraplength=650, justify='left', anchor='w')
        self.rule_description.pack(fill='x', padx=12, pady=(0, 8))

        library = tk.Frame(self.body, bg=BG)
        library.pack(fill='both', expand=True, padx=12, pady=(0, 4))
        dialog.label(library, '指定装备与基础属性门槛', size=12, bold=True).pack(anchor='w', pady=(0, 6))
        dialog.label(library, '勾选装备只限定范围，不会直接锁定。搜索只查找装备；批量勾选后才加入当前规则。',
                     color=MUTED, anchor='w').pack(fill='x', pady=(0, 8))
        self.query = tk.StringVar(master=self.tab)
        self.tier = tk.StringVar(master=self.tab, value='全部 T 级')
        self.part = tk.StringVar(master=self.tab, value='全部部位')
        self.set_group = tk.StringVar(master=self.tab, value='全部套装')
        self.only_selected = tk.BooleanVar(master=self.tab, value=False)
        self.tiers = {'全部 T 级': None}
        self.parts = {'全部部位': None}
        self.set_groups = {'全部套装': None, '仅套装': True, '非套装': False}
        for row in self.model.rows:
            self.tiers.setdefault(row['tier'], row['tier_raw'])
            self.parts.setdefault(row['type_label'], row['type_id'])
            set_name = row.get('set_name')
            if isinstance(set_name, str) and set_name:
                self.set_groups.setdefault(set_name, set_name)
        search = tk.Frame(library, bg=BG)
        search.pack(fill='x', pady=(0, 8))
        dialog.label(search, '搜索').pack(side='left', padx=(0, 8))
        tk.Entry(search, textvariable=self.query, bg=PANEL, fg=FG, insertbackground=FG,
                 relief='flat').pack(side='left', fill='x', expand=True, ipady=6)
        filters = tk.Frame(library, bg=BG)
        filters.pack(fill='x', pady=(0, 8))
        for variable, choices in ((self.tier, self.tiers), (self.part, self.parts), (self.set_group, self.set_groups)):
            ttk.Combobox(filters, textvariable=variable, values=list(choices), state='readonly', width=12).pack(
                side='left', padx=(0, 8))
        dialog.check(filters, '只看已勾选', self.only_selected).pack(side='left')
        actions = tk.Frame(library, bg=BG)
        actions.pack(fill='x', pady=(0, 8))
        dialog.button(actions, '勾选当前结果', lambda: self.bulk(True)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '取消当前结果', lambda: self.bulk(False)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '清空指定范围', self.clear).pack(side='left', padx=(0, 18))
        actions = tk.Frame(library, bg=BG); actions.pack(fill='x', pady=(0, 8))
        dialog.button(actions, '设置当前装备门槛', self.edit_threshold).pack(side='left', padx=(0, 8))
        dialog.button(actions, '删除当前门槛', self.remove_threshold).pack(side='left')
        container = tk.Frame(library, bg=BG)
        container.pack(fill='both', expand=True)
        style = ttk.Style(self.tab)
        style.configure('LockLibrary.Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=29, borderwidth=0)
        style.configure('LockLibrary.Treeview.Heading', background='#263541', foreground='#e6d4a2', relief='flat')
        style.map('LockLibrary.Treeview', background=[('selected', '#394b57')], foreground=[('selected', '#ffe08a')])
        self.tree = ttk.Treeview(container, columns=('selected', 'name', 'tier', 'set', 'part', 'threshold'),
                                 show='headings', selectmode='browse', style='LockLibrary.Treeview', height=8)
        for key, title, width in (
                ('selected', '范围', 64), ('name', '物品名称', 190), ('tier', 'T 级', 58),
                ('set', '套装', 86),
                ('part', '类型 / 部位', 100), ('threshold', '基础属性门槛', 290)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=48, stretch=key in ('name', 'threshold'),
                             anchor='w' if key in ('name', 'threshold') else 'center')
        self.scrollbar = AutoScrollbar(container, self.tree)
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Button-1>', self.clicked)
        self.tree.bind('<space>', self.space)
        self.counter = dialog.label(library, '', color=MUTED, anchor='w')
        self.counter.pack(fill='x', pady=(8, 2))
        self.job = None
        for variable in (self.query, self.tier, self.part, self.set_group, self.only_selected):
            variable.trace_add('write', self.schedule)
        self.tab.bind('<Destroy>', self.cleanup)
        self.loading = False
        self.redraw()

    def changed(self):
        if self.loading:
            return
        self.dialog.mark_dirty()
        self.update_count()

    def summary(self):
        parts = []
        qualities = [quality for quality in QUALITY_LABELS if self.quality_vars[quality].get()]
        if qualities:
            tiers = [f'T{raw - 4}' for raw, variable in self.quality_tier_vars.items() if variable.get()]
            parts.append('品质：' + '、'.join(qualities) + (f'（{"、".join(tiers)}）' if tiers else ''))
        if self.model.selected:
            parts.append(f'装备库 {len(self.model.selected)} 项')
        if self.thresholds:
            parts.append(f'门槛 {len(self.thresholds)} 项')
        return f'自动锁定：{sum(rule.get("enabled", True) for rule in self.groups)} 条已启用规则'

    def schedule(self, *_):
        if self.job:
            self.tab.after_cancel(self.job)
        self.job = self.tab.after(100, self.redraw)

    def results(self):
        return self.model.find(self.query.get(), self.tiers[self.tier.get()], self.parts[self.part.get()],
                               self.only_selected.get(), self.set_groups[self.set_group.get()])

    def threshold_text(self, key):
        values = self.thresholds.get(key, {})
        return '；'.join(f'{field} ≥ {value:g}' for field, value in values.items()) or '—'

    def row_values(self, row):
        return ('☑' if row['key'] in self.model.selected else '☐', row['label'], row['tier'], row.get('set_name', '—'), row['type_label'],
                self.threshold_text(row['key']))

    def redraw(self):
        if self.job:
            self.tab.after_cancel(self.job)
            self.job = None
        self.visible = self.results()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in self.visible:
            self.tree.insert('', 'end', iid=row['key'], values=self.row_values(row))
        self.update_count()

    def update_count(self):
        self.counter.configure(text=f'已勾选装备 {len(self.model.selected)} 项 · 设置门槛 {len(self.thresholds)} 项 · 当前显示 {len(getattr(self, "visible", ())) } 项')
        summary = getattr(self.dialog.native_settings, 'lock_library_summary', None)
        if summary is not None:
            summary.configure(text=self.summary())
        if not self.loading:
            self.save_current()
            self.refresh_rules()

    def toggle(self, key):
        if not key or not self.tree.exists(key):
            return
        self.model.toggle(key)
        self.dialog.mark_dirty()
        if self.only_selected.get():
            self.redraw()
            return
        row = next(row for row in self.visible if row['key'] == key)
        self.tree.item(key, values=self.row_values(row))
        self.update_count()

    def clicked(self, event):
        if self.tree.identify_region(event.x, event.y) == 'cell':
            key = self.tree.identify_row(event.y)
            self.tree.focus(key)
            self.tree.selection_set(key)
            self.tree.focus_set()
            if self.tree.identify_column(event.x) == '#1':
                self.toggle(key)
                return 'break'

    def space(self, _):
        self.toggle(self.tree.focus())
        return 'break'

    def bulk(self, selected):
        self.model.set_rows(self.results(), selected)
        self.dialog.mark_dirty()
        self.redraw()

    def clear(self):
        if self.model.selected:
            self.model.selected.clear()
            self.dialog.mark_dirty()
            self.redraw()

    def _allowed_fields(self, key):
        row = self.rows_by_key.get(key, {})
        base = row.get('base', {}) if isinstance(row, dict) else {}
        fields = base.get('基础属性', {}) if isinstance(base, dict) else {}
        return fields if isinstance(fields, dict) else {}

    def threshold_options(self, key):
        return tuple(self._allowed_fields(key))

    def threshold_label(self, key, field):
        maximum = self._allowed_fields(key).get(field)
        if (type(maximum) in (int, float) and not isinstance(maximum, bool)
                and math.isfinite(maximum)):
            return f'{field}（图鉴满值 {maximum:g}）'
        return field

    def set_threshold(self, key, values):
        allowed = self._allowed_fields(key)
        clean = {}
        if isinstance(values, dict):
            for field, value in values.items():
                if (isinstance(field, str) and field in allowed and type(value) in (int, float)
                        and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100000):
                    clean[field] = value
        if clean:
            self.thresholds[key] = clean
        else:
            self.thresholds.pop(key, None)
        self.dialog.mark_dirty()
        if self.tree.exists(key):
            row = next(row for row in self.visible if row['key'] == key)
            self.tree.item(key, values=self.row_values(row))
        self.update_count()

    def edit_threshold(self):
        key = self.tree.focus()
        fields = self._allowed_fields(key)
        if not key or not fields:
            messagebox.showinfo('基础属性门槛', '请先在列表中选择一件有基础属性的装备。', parent=self.dialog.window)
            return
        row = self.rows_by_key[key]
        window = tk.Toplevel(self.dialog.window)
        window.withdraw()
        window.title(f"{row['label']} · 基础属性门槛")
        window.configure(bg=BG)
        window.transient(self.dialog.window)
        window.attributes('-topmost', True)
        self.dialog.label(window, '下面是图鉴中的实际基础属性。勾选要比较的项目，再填写最低值；未勾选不限制。', color=MUTED).pack(
            anchor='w', padx=22, pady=(20, 12))
        variables = {}
        for field in self.threshold_options(key):
            line = tk.Frame(window, bg=BG)
            line.pack(fill='x', padx=22, pady=4)
            old = self.thresholds.get(key, {}).get(field)
            enabled = tk.BooleanVar(master=window, value=old is not None)
            self.dialog.check(line, self.threshold_label(key, field), enabled).pack(side='left')
            self.dialog.label(line, '≥').pack(side='left', padx=(0, 6))
            variable = tk.StringVar(master=window, value='' if old is None else f'{old:g}')
            entry = tk.Entry(line, textvariable=variable, width=12, bg=PANEL, fg=FG, insertbackground=FG,
                             relief='flat')
            entry.pack(side='left', ipady=5)
            def update_entry_state(enabled=enabled, entry=entry):
                entry.configure(state='normal' if enabled.get() else 'disabled')
            enabled.trace_add('write', lambda *_args, callback=update_entry_state: callback())
            update_entry_state()
            variables[field] = (enabled, variable)
        actions = tk.Frame(window, bg=BG)
        actions.pack(fill='x', padx=22, pady=(16, 20))
        def save():
            values = {}
            try:
                for field, (enabled, variable) in variables.items():
                    if not enabled.get():
                        continue
                    raw = variable.get().strip()
                    if not raw:
                        raise ValueError(f'{field}：勾选后请填写数值。')
                    value = float(raw)
                    if not math.isfinite(value) or not 0 <= value <= 100000:
                        raise ValueError(f'{field}：请输入 0 到 100000 之间的数值。')
                    values[field] = value
            except ValueError as error:
                messagebox.showerror('数值无效', str(error), parent=window)
                return
            self.set_threshold(key, values)
            window.destroy()
        self.dialog.button(actions, '保存门槛', save, gold=True).pack(side='right')
        self.dialog.button(actions, '取消', window.destroy).pack(side='right', padx=(0, 8))
        window.deiconify()
        window.grab_set()

    def remove_threshold(self):
        key = self.tree.focus()
        if key in self.thresholds:
            self.set_threshold(key, {})

    def current_values(self):
        qualities = [quality for quality in QUALITY_LABELS if self.quality_vars[quality].get()]
        tiers = [tier for tier, variable in self.quality_tier_vars.items() if variable.get()]
        thresholds = {}
        for key, values in self.thresholds.items():
            allowed = self._allowed_fields(key)
            clean = {field: value for field, value in values.items()
                     if field in allowed and type(value) in (int, float) and not isinstance(value, bool)
                     and math.isfinite(value) and 0 <= value <= 100000}
            if clean:
                thresholds[key] = clean
        return {'name': self.rule_name.get().strip() or f'保留规则 {self.current_rule + 1}',
                'enabled': self.rule_enabled.get(), 'qualities': qualities, 'quality_tiers': sorted(tiers),
                'equipment_keys': self.model.values(), 'thresholds': thresholds,
                'set_mode': self.set_modes[self.set_mode.get()], 'upper': self.upper.get(), 'lower': self.lower.get(),
                'upper_ids': list(self.upper_ids), 'lower_ids': list(self.lower_ids),
                'numeric': self.numeric.get(), 'keep_all': self.keep_all.get(),
                'filter_sections': [key for key, variable in self.legacy_vars.items() if variable.get()]}

    def save_current(self):
        if not self.loading:
            self.groups[self.current_rule] = self.current_values()

    def describe(self, rule):
        parts = []
        if rule.get('quality_tiers'):
            parts.append('/'.join(f'T{tier - 4}' if tier >= 5 else '普通' for tier in rule['quality_tiers']))
        if rule.get('qualities'):
            parts.append('/'.join(rule['qualities']))
        if rule.get('set_mode') in ('set', 'non_set'):
            parts.append('套装' if rule['set_mode'] == 'set' else '非套装')
        keys = rule.get('equipment_keys', [])
        if keys:
            parts.append('指定 ' + (keys[0].split(':', 2)[-1] if len(keys) == 1 else f'{len(keys)} 件装备'))
        if rule.get('thresholds'):
            parts.append('；'.join(key.split(':', 2)[-1] + '：' + '、'.join(f'{field}≥{value:g}' for field, value in values.items())
                                  for key, values in rule['thresholds'].items()))
        for key, label in (('upper', '上技能'), ('lower', '下技能')):
            if rule.get(key):
                ids = rule.get(key + '_ids', [])
                parts.append(label + (f'（指定 {len(ids)} 项之一）' if ids else '（任意）'))
        if rule.get('numeric'): parts.append('词条数值达标')
        labels = {'numeric': '词条', 'legendary': '上技能', 'lower': '下技能'}
        parts.extend('命中原有' + labels[key] + '筛选' for key in rule.get('filter_sections', []))
        if rule.get('keep_all'): parts.append('明确全品质保留')
        conditions = any(rule.get(key) for key in ('qualities','thresholds','upper','lower','numeric','keep_all','filter_sections'))
        return ' ＋ '.join(parts) + ('' if conditions else '（尚未设置保留条件，不会锁定）')

    def refresh_rules(self):
        for child in self.rules_list.get_children():
            if int(child) >= len(self.groups): self.rules_list.delete(child)
        for index, rule in enumerate(self.groups):
            values = ('✓' if rule.get('enabled', True) else '—', rule.get('name', f'规则 {index+1}') + '：' + self.describe(rule))
            if self.rules_list.exists(str(index)): self.rules_list.item(str(index), values=values)
            else: self.rules_list.insert('', 'end', iid=str(index), values=values)
        self.rule_description.configure(text='本条全部满足：' + self.describe(self.groups[self.current_rule]))
        self.upper_button.configure(text=f'指定上技能（{len(self.upper_ids) or "任意"}）')
        self.lower_button.configure(text=f'指定下技能（{len(self.lower_ids) or "任意"}）')

    def rule_selected(self, _event):
        chosen = self.rules_list.selection()
        if chosen and not self.loading and int(chosen[0]) != self.current_rule:
            self.select_rule(int(chosen[0]))

    def select_rule(self, index):
        self.save_current()
        self.loading = True
        self.current_rule = index
        saved = self.groups[index]
        normalized = LockLibrary(list(self.rows_by_key.values()), saved)
        self.rule_name.set(saved.get('name', f'保留规则 {index+1}'))
        self.rule_enabled.set(saved.get('enabled', True))
        for key, var in self.quality_vars.items(): var.set(key in normalized.qualities)
        for key, var in self.quality_tier_vars.items(): var.set(key in normalized.quality_tiers)
        self.model.selected = set(normalized.equipment_keys)
        self.thresholds = copy.deepcopy(normalized.thresholds)
        self.set_mode.set(next(k for k,v in self.set_modes.items() if v == normalized.set_mode))
        for key in ('upper','lower','numeric','keep_all'): getattr(self,key).set(getattr(normalized,key))
        self.upper_ids, self.lower_ids = list(normalized.upper_ids), list(normalized.lower_ids)
        for key, var in self.legacy_vars.items(): var.set(key in normalized.filter_sections)
        if normalized.filter_sections: self.legacy_box.pack(fill='x', padx=12, pady=4)
        else: self.legacy_box.pack_forget()
        self.query.set(''); self.tier.set('全部 T 级'); self.part.set('全部部位')
        self.set_group.set('全部套装'); self.only_selected.set(False)
        self.loading = False
        self.redraw()
        self.rules_list.selection_set(str(index))

    def add_rule(self):
        self.save_current()
        self.groups.append({'name': f'保留规则 {len(self.groups) + 1}'})
        self.select_rule(len(self.groups) - 1)
        self.changed()

    def delete_rule(self):
        self.groups.pop(self.current_rule)
        if not self.groups: self.groups.append({'name': '保留规则 1'})
        # Load the surviving rule without writing the deleted editor over it.
        self.loading = True
        self.current_rule = min(self.current_rule, len(self.groups)-1)
        self.select_rule(self.current_rule)
        self.changed()

    def edit_skills(self, position):
        window = tk.Toplevel(self.dialog.window); window.withdraw()
        window.title('指定上技能' if position == 'upper' else '指定下技能')
        window.configure(bg=BG); window.transient(self.dialog.window)
        self.dialog.label(window, '勾选任意一项即满足该技能条件；不选具体技能表示任意技能。', color=MUTED).pack(padx=18, pady=12)
        names = json.loads((Path(__file__).with_name('catalog') / 'skill-names.json').read_text(encoding='utf8'))
        selected = getattr(self, position + '_ids')
        for key in selected: names.setdefault(str(key), f'技能 {key}')
        choices = sorted((int(key), str(value)) for key,value in names.items() if int(key) > 0)
        listing = tk.Listbox(window, selectmode='multiple', exportselection=False, width=55, height=16,
                             bg=PANEL, fg=FG, selectbackground='#394b57')
        listing.pack(fill='both', expand=True, padx=18)
        for index, (key, label) in enumerate(choices):
            listing.insert('end', f'{label}（{key}）')
            if key in selected: listing.selection_set(index)
        actions = tk.Frame(window, bg=BG); actions.pack(fill='x', padx=18, pady=12)
        def save():
            setattr(self, position + '_ids', [choices[index][0] for index in listing.curselection()])
            getattr(self, position).set(True)
            self.changed(); window.destroy()
        self.dialog.button(actions, '任意技能', lambda: listing.selection_clear(0, 'end')).pack(side='left')
        self.dialog.button(actions, '确定', save, gold=True).pack(side='right')
        self.dialog.button(actions, '取消', window.destroy).pack(side='right')
        window.update_idletasks()
        x = self.dialog.window.winfo_rootx() + max(0, (self.dialog.window.winfo_width()-window.winfo_reqwidth())//2)
        y = self.dialog.window.winfo_rooty() + max(0, (self.dialog.window.winfo_height()-window.winfo_reqheight())//2)
        window.geometry(f'+{x}+{y}'); window.deiconify(); window.grab_set()

    def values(self):
        self.save_current()
        return {'lock_library': {'schema': 2, 'rules': copy.deepcopy(self.groups)}}

    def cleanup(self, event):
        if event.widget == self.tab and self.job:
            self.tab.after_cancel(self.job)
            self.job = None
