"""Virtualized native list: no hundreds of Tk checkbox widgets to redraw."""
import tkinter as tk
from tkinter import ttk

from gear_view import catalog_data
from pickup_library import ExclusionLibrary, codex_names, codex_selection
from overlay_scroll import AutoScrollbar


class PickupLibrarySettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.model = ExclusionLibrary(catalog_data()['equipment'], dialog.settings.get('pickup_exclusions', []),
                                      codex_selection(dialog.settings))
        self.tab = tk.Frame(dialog.features, bg='#191d21')
        dialog.features.add(self.tab, text='掉落屏蔽清单', hidden=True)
        dialog.button(self.tab, '‹ 返回进阶辅助', lambda: dialog.features.select(dialog.native_settings.tab)).pack(anchor='w', pady=(4, 8))
        self.category = tk.StringVar(master=self.tab, value='全部类型')
        self.query = tk.StringVar(master=self.tab)
        self.tier = tk.StringVar(master=self.tab, value='全部 T 级')
        self.part = tk.StringVar(master=self.tab, value='全部部位')
        self.only_selected = tk.BooleanVar(master=self.tab, value=False)
        self.job = None
        self.visible = []
        equipment = [r for r in self.model.rows if r['category'] == '装备']
        self.tiers = {'全部 T 级': None, **{r['tier']: r['tier_raw'] for r in equipment}}
        self.parts = {'全部部位': None, **{r['type_label']: r['type_id'] for r in equipment}}
        dialog.label(self.tab, '勾选 = 屏蔽新掉落；装备按名称、T 级和部位区分。', anchor='w').pack(fill='x', padx=12, pady=(12, 3))
        dialog.label(self.tab, '地上原有物品继续跳过拾取；修改后点“保存设置”生效。', anchor='w').pack(fill='x', padx=12, pady=(0, 5))
        self.all_codex = tk.IntVar(master=self.tab)
        self.all_codex_check = dialog.check(self.tab, '屏蔽全部图鉴（63 种）', self.all_codex)
        self.all_codex_check.configure(command=self.choose_all_codex, tristatevalue=-1)
        self.all_codex_check.pack(anchor='w', padx=8, pady=(0, 6))
        search = tk.Frame(self.tab, bg='#191d21')
        search.pack(fill='x', padx=12)
        dialog.label(search, '搜索').pack(side='left', padx=(0, 8))
        self.entry = tk.Entry(search, textvariable=self.query, bg='#263541', fg='#f0e7d4', insertbackground='white', relief='flat')
        self.entry.pack(side='left', fill='x', expand=True, ipady=7)
        filters = tk.Frame(self.tab, bg='#191d21')
        filters.pack(fill='x', padx=12, pady=8)
        for variable, choices in ((self.category, ('全部类型', '装备', '图鉴')), (self.tier, self.tiers), (self.part, self.parts)):
            combo = ttk.Combobox(filters, textvariable=variable, values=list(choices), state='readonly', width=11)
            combo.pack(side='left', padx=(0, 8))
        dialog.check(filters, '只看已勾选', self.only_selected).pack(side='left')
        actions = tk.Frame(self.tab, bg='#191d21')
        actions.pack(fill='x', padx=12, pady=(0, 8))
        dialog.button(actions, '全选', lambda: self.bulk(True)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '取消全选', lambda: self.bulk(False)).pack(side='left', padx=(0, 8))
        dialog.button(actions, '清空已选', self.clear).pack(side='left')
        self.counter = dialog.label(self.tab, '', anchor='w')
        self.counter.pack(side='bottom', fill='x', padx=12, pady=8)
        container = tk.Frame(self.tab, bg='#191d21')
        container.pack(fill='both', expand=True, padx=12)
        style = ttk.Style(self.tab)
        style.configure('Pickup.Treeview', background='#24292f', fieldbackground='#24292f', foreground='#e7e2d7', rowheight=29, borderwidth=0)
        style.configure('Pickup.Treeview.Heading', background='#263541', foreground='#e6d4a2', relief='flat')
        style.map('Pickup.Treeview', background=[('selected', '#394b57')], foreground=[('selected', '#ffe08a')])
        self.tree = ttk.Treeview(container, columns=('excluded', 'name', 'tier', 'part'), show='headings', selectmode='browse', style='Pickup.Treeview')
        for key, title, width in [('excluded', '屏蔽', 68), ('name', '物品名称', 220), ('tier', 'T 级', 72), ('part', '类型 / 部位', 100)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=45, stretch=key == 'name', anchor='w' if key == 'name' else 'center')
        self.scrollbar = AutoScrollbar(container, self.tree)
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Button-1>', self.clicked)
        self.tree.bind('<space>', self.space)
        for variable in (self.query, self.category, self.tier, self.part, self.only_selected):
            variable.trace_add('write', self.schedule)
        self.tab.bind('<Destroy>', self.cleanup)
        self.redraw()

    def schedule(self, *_):
        if self.job:
            self.tab.after_cancel(self.job)
        self.job = self.tab.after(100, self.redraw)

    def results(self):
        return self.model.find(self.query.get(), self.tiers[self.tier.get()], self.parts[self.part.get()], self.only_selected.get(), self.category.get())

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

    def row_values(self, row):
        return ('☑' if row['key'] in self.model.selected else '☐', row['label'], row['tier'], row['type_label'])

    def update_count(self):
        names=set(self.model.codex_values())
        count=len(names & codex_names())
        self.all_codex.set(1 if count==len(codex_names()) else -1 if count else 0)
        self.dialog.native_settings.codex_summary.configure(text=f'图鉴屏蔽：已选 {count} / 63 种')
        self.counter.configure(text=f'已选装备 {len(self.model.equipment_values())} 项 / 图鉴 {len(names)} 项 · 当前显示 {len(self.visible)} 项')

    def choose_all_codex(self):
        self.dialog.mark_dirty()
        self.model.set_rows(self.model.find(category='图鉴'), self.all_codex.get()==1)
        self.redraw()

    def toggle(self, key):
        if not key or not self.tree.exists(key):
            return
        self.model.toggle(key)
        self.dialog.mark_dirty()
        if self.only_selected.get():
            self.redraw()
        else:
            row = next(r for r in self.visible if r['key'] == key)
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

    def bulk(self, excluded):
        self.dialog.mark_dirty()
        self.model.set_rows(self.results(), excluded)
        self.redraw()

    def clear(self):
        self.dialog.mark_dirty()
        self.model.selected.clear()
        self.redraw()

    def cleanup(self, event):
        if event.widget == self.tab and self.job:
            self.tab.after_cancel(self.job)
            self.job = None

    def values(self):
        return {'pickup_exclusions': self.model.equipment_values(), 'codex_exclusions': self.model.codex_values(),
                'codex_selection_version': 1}
