"""Quality, exact-equipment, and base-attribute lock rules."""
import math
import tkinter as tk
from tkinter import messagebox, ttk

from gear_view import catalog_data
from lock_library import LockLibrary, QUALITY_LABELS
from overlay_scroll import AutoScrollbar
from pickup_library import EquipmentLibrary, equipment_key
from ui_theme import BG, PANEL, FG, GOLD, GREEN, MUTED


class LockLibrarySettings:
    def __init__(self, dialog):
        self.dialog = dialog
        saved = dialog.settings.get('lock_library', {})
        saved = saved if isinstance(saved, dict) else {}
        rows = catalog_data().get('equipment', ())
        normalized = LockLibrary(rows, saved)
        self.rows_by_key = {equipment_key(row): row for row in rows if isinstance(row, dict)}
        self.model = EquipmentLibrary(rows, list(normalized.equipment_keys))
        self.thresholds = {key: dict(values) for key, values in normalized.thresholds.items()}
        self.tab = tk.Frame(dialog.features, bg=BG)
        dialog.features.add(self.tab, text='品质装备锁定', hidden=True)
        dialog.button(self.tab, '‹ 返回进阶辅助', lambda: dialog.features.select(dialog.native_settings.tab)).pack(
            anchor='w', pady=(4, 8))
        dialog.label(self.tab, '三种规则相互独立；任一命中就自动锁定，仍遵守手动解锁静默。',
                     color=MUTED, anchor='w').pack(fill='x', padx=12, pady=(2, 10))

        quality_box = tk.Frame(self.tab, bg=PANEL)
        quality_box.pack(fill='x', padx=12, pady=(0, 10))
        dialog.label(quality_box, '品质保留', size=12, bold=True).pack(anchor='w', padx=12, pady=(10, 3))
        dialog.label(quality_box, '勾选品质后可再限定 T 级；不勾 T 级表示所有 T 级。',
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

        library = tk.Frame(self.tab, bg=BG)
        library.pack(fill='both', expand=True, padx=12, pady=(0, 4))
        dialog.label(library, '装备库与单装备门槛', size=12, bold=True).pack(anchor='w', pady=(0, 6))
        dialog.label(library, '勾选装备会直接保留；门槛只显示该装备图鉴里有的基础属性。勾选要比较的项目，未勾选不限制。',
                     color=MUTED, anchor='w').pack(fill='x', pady=(0, 8))
        self.query = tk.StringVar(master=self.tab)
        self.tier = tk.StringVar(master=self.tab, value='全部 T 级')
        self.part = tk.StringVar(master=self.tab, value='全部部位')
        self.only_selected = tk.BooleanVar(master=self.tab, value=False)
        self.tiers = {'全部 T 级': None}
        self.parts = {'全部部位': None}
        for row in self.model.rows:
            self.tiers.setdefault(row['tier'], row['tier_raw'])
            self.parts.setdefault(row['type_label'], row['type_id'])
        search = tk.Frame(library, bg=BG)
        search.pack(fill='x', pady=(0, 8))
        dialog.label(search, '搜索').pack(side='left', padx=(0, 8))
        tk.Entry(search, textvariable=self.query, bg=PANEL, fg=FG, insertbackground=FG,
                 relief='flat').pack(side='left', fill='x', expand=True, ipady=6)
        filters = tk.Frame(library, bg=BG)
        filters.pack(fill='x', pady=(0, 8))
        for variable, choices in ((self.tier, self.tiers), (self.part, self.parts)):
            ttk.Combobox(filters, textvariable=variable, values=list(choices), state='readonly', width=12).pack(
                side='left', padx=(0, 8))
        dialog.check(filters, '只看已勾选', self.only_selected).pack(side='left')
        actions = tk.Frame(library, bg=BG)
        actions.pack(fill='x', pady=(0, 8))
        dialog.button(actions, '勾选当前结果', lambda: self.bulk(True)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '取消当前结果', lambda: self.bulk(False)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '清空勾选装备', self.clear).pack(side='left', padx=(0, 18))
        dialog.button(actions, '设置当前装备门槛', self.edit_threshold).pack(side='left', padx=(0, 8))
        dialog.button(actions, '删除当前门槛', self.remove_threshold).pack(side='left')
        container = tk.Frame(library, bg=BG)
        container.pack(fill='both', expand=True)
        style = ttk.Style(self.tab)
        style.configure('LockLibrary.Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=29, borderwidth=0)
        style.configure('LockLibrary.Treeview.Heading', background='#263541', foreground='#e6d4a2', relief='flat')
        style.map('LockLibrary.Treeview', background=[('selected', '#394b57')], foreground=[('selected', '#ffe08a')])
        self.tree = ttk.Treeview(container, columns=('selected', 'name', 'tier', 'part', 'threshold'),
                                 show='headings', selectmode='browse', style='LockLibrary.Treeview')
        for key, title, width in (
                ('selected', '保留', 64), ('name', '物品名称', 190), ('tier', 'T 级', 58),
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
        for variable in (self.query, self.tier, self.part, self.only_selected):
            variable.trace_add('write', self.schedule)
        self.tab.bind('<Destroy>', self.cleanup)
        self.redraw()

    def changed(self):
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
        return '品质 / 装备库规则：' + ' · '.join(parts) if parts else '品质 / 装备库规则：未设置'

    def schedule(self, *_):
        if self.job:
            self.tab.after_cancel(self.job)
        self.job = self.tab.after(100, self.redraw)

    def results(self):
        return self.model.find(self.query.get(), self.tiers[self.tier.get()], self.parts[self.part.get()],
                               self.only_selected.get())

    def threshold_text(self, key):
        values = self.thresholds.get(key, {})
        return '；'.join(f'{field} ≥ {value:g}' for field, value in values.items()) or '—'

    def row_values(self, row):
        return ('☑' if row['key'] in self.model.selected else '☐', row['label'], row['tier'], row['type_label'],
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

    def values(self):
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
        return {'lock_library': {'qualities': qualities, 'quality_tiers': sorted(tiers),
                                 'equipment_keys': self.model.values(), 'thresholds': thresholds}}

    def cleanup(self, event):
        if event.widget == self.tab and self.job:
            self.tab.after_cancel(self.job)
            self.job = None
