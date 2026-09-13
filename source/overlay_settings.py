"""Local settings: categorized numeric filters, tier/slot pairs, transparent HUD."""
import math
import tkinter as tk
from tkinter import messagebox, ttk
from gear_view import catalog_data, configured_rules, LEGENDARY_TYPES
from overlay_scroll import dark_scrollbars, AutoScrollbar
from tk_lifecycle import guard_tk

from ui_theme import BG, PANEL, FG, GOLD, MUTED, setup, center_window, button as themed_button
from ui_pages import PageStack

class Settings:
    def __init__(self, overlay, show=True):
        guard_tk(overlay.root)
        self.overlay = overlay
        self.catalog = catalog_data()
        self.write = overlay.write_file
        def load_settings(name, default=None):
            value = overlay.read_file(name, None)
            # Startup can beat the first asynchronous file read. Never replace
            # existing preferences with defaults merely because the feed is cold.
            if value is None and hasattr(overlay, 'feed'):
                from loot_overlay import load
                value = load(name)
            return default if value is None else value
        self.load = load_settings
        self.rules = configured_rules(self.load('loot-filter-rules.json', None))
        self.settings = self.load('loot-overlay-settings.json', {})
        self.window = tk.Toplevel(overlay.root)
        self.window.withdraw()
        self.window.title('破晓装备助手 · 功能设置')
        self.window.attributes('-topmost', True)
        self.window.configure(bg=BG)
        self.window.geometry('1060x760')
        self.window.minsize(720, 520)
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        setup(self.window)
        dark_scrollbars(self.window)
        from ui_theme import label
        header = tk.Frame(self.window, bg=BG)
        header.pack(fill='x', padx=24, pady=(20, 8))
        label(header, '破晓装备助手', size=19, bold=True).pack(side='left')
        label(header, '免费 · 开源', color=GOLD, size=9).pack(side='left', padx=14)
        from loot_app import VERSION
        label(header, 'v' + VERSION, color=MUTED, size=9).pack(side='right')
        connection = tk.Frame(self.window, bg=BG)
        connection.pack(fill='x', padx=24, pady=(0, 16))
        status = self.load('continuous-status.json', {}) or {}
        self.game_status = label(connection, '● 游戏已连接' if status.get('status') == 'watching' else '○ 等待游戏连接', color=MUTED)
        self.game_status.pack(side='left')
        self.button(connection, '连接详情', self.show_connection).pack(side='right')
        self.features = PageStack(self.window, sidebar=True)
        self.features.pack(fill='both', expand=True, padx=(0, 24))
        self.filter_page = tk.Frame(self.features, bg=BG)
        self.features.add(self.filter_page, text='装备筛选')
        label(self.filter_page, '装备筛选', size=20, bold=True).pack(anchor='w', pady=(6, 6))
        label(self.filter_page, '挑出值得留下的装备，再到背包里找到它。', color=MUTED).pack(anchor='w', pady=(0, 12))
        self.tabs = PageStack(self.filter_page)
        self.tabs.pack(fill='both', expand=True)
        self.numeric_tab = self.tab('词条')
        self.legend_tab = self.tab('上技能')
        self.lower_tab = self.tab('下技能')
        self.enabled_vars = [tk.BooleanVar(value=x['enabled']) for x in self.rules]
        self.minimum_vars = [tk.StringVar(value=f"{x['min']:g}") for x in self.rules]
        self.numeric_settings()
        self.legendary_settings()
        self.lower_settings()
        from overlay_features import FeatureSettings
        self.feature_settings = FeatureSettings(self)
        from overlay_native import NativeSettings
        self.native_settings = NativeSettings(self)
        self.visual_tab = tk.Frame(self.features, bg=BG)
        self.features.add(self.visual_tab, text='悬浮窗')
        label(self.visual_tab, '悬浮窗', size=20, bold=True).pack(anchor='w', pady=(6, 8))
        self.visual_settings()
        from author_page import populate
        self.author_tab = tk.Frame(self.features, bg=BG)
        self.features.add(self.author_tab, text='作者的话', separator=True)
        self.author_scrollbar = populate(self.author_tab)
        self.project_tab = tk.Frame(self.features, bg=BG)
        self.features.add(self.project_tab, text='项目与更新')
        label(self.project_tab, '项目与更新', size=20, bold=True).pack(anchor='w', pady=(6, 18))
        self.build_project_page(VERSION)
        from overlay_pickup_library import PickupLibrarySettings
        self.pickup_library = PickupLibrarySettings(self)
        from overlay_lock_library import LockLibrarySettings
        self.lock_library = LockLibrarySettings(self)
        bottom = tk.Frame(self.window, bg=BG)
        bottom.pack(side='bottom', fill='x', padx=24, pady=14, before=self.features)
        self.notice = tk.Label(bottom, text='已保存', bg=BG, fg=MUTED, anchor='w')
        self.notice.pack(side='left')
        self.save_button = self.button(bottom, '保存设置', self.apply, gold=True)
        self.save_button.pack(side='right', padx=(10, 0))
        self.button(bottom, '关闭', self.cancel).pack(side='right')
        self._traces = []
        for owner in (self, self.feature_settings, self.native_settings):
            for name, value in list(vars(owner).items()):
                if name in ('query', 'lower_query'):
                    continue
                values = value.values() if isinstance(value, dict) else value if isinstance(value, list) else (value,)
                for var in list(values):
                    if isinstance(var, tk.Variable):
                        token = var.trace_add('write', self.mark_dirty)
                        self._traces.append((var, token))
        self.window.bind('<MouseWheel>', self.wheel)
        self.center_job = self.window.after(0, self.center_on_screen)
        self.window.bind('<Destroy>', self.cancel_pending_layout)
        if show:
            self.window.deiconify()

    def mark_dirty(self, *_):
        self.notice.configure(text='有未保存的更改', fg=GOLD)

    def build_project_page(self, version):
        from ui_theme import label
        from update_panel import UpdatePanel
        import loot_overlay
        self.version = version
        # Adapt the existing update worker to this page without creating another window.
        self.updates = UpdatePanel(self, self.project_tab, version, loot_overlay.BASE)
        label(self.project_tab, '蓝奏云为主要下载入口。无法检查版本时，也可以直接打开下载页。',
              color=MUTED, wraplength=640, justify='left').pack(fill='x', pady=12)

    def show_project(self):
        self.features.select(self.project_tab)
        self.window.deiconify()
        self.window.lift()

    def show_connection(self):
        from ui_theme import label
        window = tk.Toplevel(self.window)
        window.withdraw()
        window.title('连接详情')
        window.configure(bg=BG)
        window.geometry('580x260')
        window.attributes('-topmost', True)
        saved = self.load('app-settings.json', {}) or {}
        label(window, '游戏位置 · 已记住', size=12, bold=True).pack(anchor='w', padx=24, pady=(24, 12))
        label(window, str(getattr(self, 'game_exe', None) or saved.get('game_exe') or '等待定位游戏'), color=MUTED,
              wraplength=520, justify='left').pack(fill='x', padx=24)
        label(window, '装备筛选可以独立使用；进阶辅助需要安装游戏组件。',
              wraplength=520, color=MUTED).pack(fill='x', padx=24, pady=16)
        self.button(window, '关闭', window.destroy).pack(anchor='e', padx=24, pady=12)
        window.deiconify()
        center_window(window, self.window)

    def center_on_screen(self, anchor=None):
        if self.center_job:
            self.window.after_cancel(self.center_job)
        self.center_job = None
        center_window(self.window, anchor if anchor is not None else self.overlay.root)

    def cancel_pending_layout(self, event):
        if event.widget != self.window:
            return
        if self.center_job:
            self.window.after_cancel(self.center_job)
            self.center_job = None
        if getattr(self, 'updates', None):
            self.updates.close()
        for var, token in self._traces:
            var.trace_remove('write', token)
        self._traces.clear()
        # Child pages refer back to this dialog, forming Python cycles. Release
        # Tcl variables here on the UI thread, before a file-worker GC can run.
        for owner in (self, getattr(self, 'feature_settings', None), getattr(self, 'native_settings', None),
                      getattr(self, 'pickup_library', None), getattr(self, 'lock_library', None)):
            if owner is None:
                continue
            for name, value in list(vars(owner).items()):
                if isinstance(value, tk.Variable):
                    setattr(owner, name, None)
                elif isinstance(value, dict) and any(isinstance(v, tk.Variable) for v in value.values()):
                    value.clear()
                elif isinstance(value, list) and any(isinstance(v, tk.Variable) for v in value):
                    value.clear()

    def tab(self, label):
        frame = tk.Frame(self.tabs, bg=BG)
        self.tabs.add(frame, text=label)
        return frame

    def label(self, parent, text, **kwargs):
        color = kwargs.pop('color', MUTED)
        size, bold = kwargs.pop('size', None), kwargs.pop('bold', False)
        if size or bold:
            kwargs['font'] = ('Microsoft YaHei UI', size or 10, 'bold' if bold else 'normal')
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color, **kwargs)

    def button(self, parent, text, command, gold=False, primary=False):
        return themed_button(parent, text, command, primary=gold or primary)

    def check(self, parent, text, variable, command=None):
        return tk.Checkbutton(parent, text=text, variable=variable, command=command,
                              bg=parent.cget('bg'), fg=FG, selectcolor=PANEL,
                              activebackground=parent.cget('bg'), activeforeground=GOLD,
                              disabledforeground=MUTED, anchor='w', highlightthickness=0,
                              cursor='hand2', padx=2, pady=4)

    def numeric_settings(self):
        search_bar = tk.Frame(self.numeric_tab, bg=BG)
        search_bar.pack(fill='x', pady=(12, 8))
        self.label(search_bar, '搜索词条').pack(side='left', padx=(4, 8))
        self.query = tk.StringVar()
        entry = tk.Entry(search_bar, textvariable=self.query, bg=PANEL, fg=FG, insertbackground=FG, relief='flat')
        entry.pack(side='left', fill='x', expand=True, ipady=5)
        self.counter = self.label(search_bar, '')
        self.counter.pack(side='right', padx=10)
        body = tk.Frame(self.numeric_tab, bg=BG)
        body.pack(fill='both', expand=True)
        self.category = tk.Listbox(body, width=16, bg=PANEL, fg=FG, selectbackground='#445263',
                                   selectforeground=GOLD, borderwidth=0, highlightthickness=0, exportselection=False,
                                   activestyle='none')
        self.category.pack(side='left', fill='y', padx=(0, 10))
        self.categories = ['全部词条', '已勾选'] + self.catalog['categories']
        for text in self.categories:
            self.category.insert('end', text)
        self.category.selection_set(0)
        self.category.bind('<<ListboxSelect>>', lambda _: self.draw_rules())
        right = tk.Frame(body, bg=BG)
        right.pack(side='left', fill='both', expand=True)
        actions = tk.Frame(right, bg=BG)
        actions.pack(fill='x', pady=(0, 6))
        self.button(actions, '勾选本页', lambda: self.select_visible(True)).pack(side='left')
        self.button(actions, '取消本页', lambda: self.select_visible(False)).pack(side='left', padx=6)
        self.label(actions, '达到任一项就提示').pack(side='right')
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=0, borderwidth=0)
        self.numeric_scrollbar = AutoScrollbar(right, self.canvas)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.rows = tk.Frame(self.canvas, bg=BG)
        self.rows_id = self.canvas.create_window((0, 0), window=self.rows, anchor='nw')
        self.rows.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.rows_id, width=e.width))
        self.rows.columnconfigure(0, weight=1)
        self.query.trace_add('write', lambda *_: self.draw_rules())
        self.label(self.numeric_tab, '只筛下方数值词条；攻击、防御区间按右侧数值比较。', anchor='w').pack(fill='x', pady=(8, 2))
        self.label(self.numeric_tab, '支持搜索与分类；满足任意一条已启用规则即可显示。', anchor='w', font=('Microsoft YaHei UI', 9)).pack(fill='x', pady=(0, 6))
        self.draw_rules()

    def filtered_indices(self):
        selection = self.category.curselection()
        category = self.categories[selection[0]] if selection else '全部词条'
        query = self.query.get().strip().lower()
        return [i for i, rule in enumerate(self.rules)
                if (category == '全部词条' or category == '已勾选' and self.enabled_vars[i].get() or rule['category'] == category)
                and (not query or query in (rule['label'] + rule['field'] + rule['source_label']).lower())]

    def draw_rules(self):
        for child in self.rows.winfo_children():
            child.destroy()
        indices = self.filtered_indices()
        for row, index in enumerate(indices):
            rule = self.rules[index]
            label = rule['label']
            if rule['enum_id'] in (11, 13, 15, 17, 62):
                label += '（固定）'
            cb = self.check(self.rows, label, self.enabled_vars[index], self.update_count)
            cb.grid(row=row, column=0, sticky='ew', pady=4)
            self.label(self.rows, '≥').grid(row=row, column=1, padx=5)
            tk.Spinbox(self.rows, from_=0, to=100000, textvariable=self.minimum_vars[index], width=7,
                       bg=PANEL, fg=FG, insertbackground=FG, buttonbackground=PANEL, relief='flat').grid(row=row, column=2, padx=4, ipady=3)
            self.label(self.rows, rule['unit'] or '数值', width=4, anchor='w').grid(row=row, column=3, padx=(4, 1))
        if not indices:
            self.label(self.rows, '没有符合条件的词条').grid(row=0, column=0, pady=18)
        self.canvas.yview_moveto(0)
        self.update_count()

    def update_count(self):
        count = sum(v.get() for v in self.enabled_vars)
        self.counter.configure(text=f'已选 {count} / {len(self.rules)}')

    def select_visible(self, enabled):
        for i in self.filtered_indices():
            self.enabled_vars[i].set(enabled)
        self.draw_rules()

    def wheel(self, event):
        if self.features.select() == str(self.native_settings.tab):
            return self.native_settings.scrollbar.wheel(event)
        if self.features.select() == str(self.author_tab):
            return self.author_scrollbar.wheel(event)
        if self.features.select() != str(self.filter_page):
            return
        if self.tabs.select() == str(self.numeric_tab):
            if event.widget == self.category:
                return
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        elif self.tabs.select() == str(self.lower_tab):
            self.lower_canvas.yview_scroll(-int(event.delta / 120), 'units')

    def legendary_settings(self):
        self.legend_enabled = tk.BooleanVar(value=self.settings.get('legendary_enabled', True))
        self.check(self.legend_tab, '提示装备上方自带的传说技能', self.legend_enabled).pack(anchor='w', pady=(14, 6))
        self.label(self.legend_tab, '按“T 级 × 部位”组合勾选，下面可自行添加的技能不计入。', anchor='w').pack(fill='x', padx=6)
        actions = tk.Frame(self.legend_tab, bg=BG)
        actions.pack(fill='x', padx=5, pady=12)
        self.button(actions, '只选 T5', lambda: self.choose_pairs('t5')).pack(side='left')
        self.button(actions, '全部', lambda: self.choose_pairs('all')).pack(side='left', padx=7)
        self.button(actions, '清空', lambda: self.choose_pairs('none')).pack(side='left')
        matrix = tk.Frame(self.legend_tab, bg=BG)
        matrix.pack(fill='x', padx=6)
        self.types = [{'id': kind, 'label': label} for kind, label in LEGENDARY_TYPES.items()]
        selected = self.settings.get('legendary_pairs')
        self.pair_vars = {}
        for column, kind in enumerate(self.types, 1):
            matrix.columnconfigure(column, weight=1)
            self.label(matrix, kind['label'], font=('Microsoft YaHei UI', 10)).grid(row=0, column=column, padx=1, pady=5)
        for row, tier in enumerate(range(5, 10), 1):
            self.label(matrix, f'T{tier - 4}').grid(row=row, column=0, padx=(0, 12), pady=7)
            for column, kind in enumerate(self.types, 1):
                key = f"{tier}:{kind['id']}"
                var = tk.BooleanVar(value=(tier == 9 if selected is None else key in selected))
                self.pair_vars[key] = var
                self.check(matrix, '', var, self.update_pair_count).grid(row=row, column=column, padx=3)
        self.pair_count = self.label(self.legend_tab, '', anchor='w')
        self.pair_count.pack(fill='x', padx=6, pady=(12, 5))
        self.label(self.legend_tab, '显示：第 2 行第 3 格 · T4 武器\n冲刺无冷却', justify='left', anchor='w').pack(fill='x', padx=6, pady=8)
        self.update_pair_count()

    def choose_pairs(self, which):
        for key, var in self.pair_vars.items():
            var.set(which == 'all' or which == 't5' and key.startswith('9:'))
        self.update_pair_count()

    def update_pair_count(self):
        self.pair_count.configure(text=f'已选 {sum(v.get() for v in self.pair_vars.values())} 种组合 · 可独立选择 T4 武器、T5 项链')

    def lower_settings(self):
        self.lower_enabled = tk.BooleanVar(value=self.settings.get('lower_enabled', True))
        self.check(self.lower_tab, '提示装备下方的技能', self.lower_enabled).pack(anchor='w', pady=(14, 6))
        self.label(self.lower_tab, '只匹配下方技能，与上技能的 T 级和部位选择独立。', anchor='w').pack(fill='x', padx=6)
        search = tk.Frame(self.lower_tab, bg=BG)
        search.pack(fill='x', padx=6, pady=10)
        self.label(search, '搜索技能').pack(side='left', padx=(0, 8))
        self.lower_query = tk.StringVar()
        tk.Entry(search, textvariable=self.lower_query, bg=PANEL, fg=FG, insertbackground=FG,
                 relief='flat').pack(side='left', fill='x', expand=True, ipady=5)
        actions = tk.Frame(self.lower_tab, bg=BG)
        actions.pack(fill='x', padx=6, pady=(0, 8))
        self.button(actions, '全部', lambda: self.choose_lower_skills(True)).pack(side='left')
        self.button(actions, '清空', lambda: self.choose_lower_skills(False)).pack(side='left', padx=7)
        self.lower_count = self.label(actions, '')
        self.lower_count.pack(side='right')
        selected = self.settings.get('lower_skill_ids')
        self.lower_skill_vars = {skill['id']: tk.BooleanVar(value=selected is None or skill['id'] in selected)
                                 for skill in self.catalog['skills']}
        body = tk.Frame(self.lower_tab, bg=BG)
        body.pack(fill='both', expand=True, padx=6)
        self.lower_canvas = tk.Canvas(body, bg=BG, borderwidth=0, highlightthickness=0)
        self.lower_scrollbar = AutoScrollbar(body, self.lower_canvas)
        self.lower_canvas.pack(side='left', fill='both', expand=True)
        self.lower_rows = tk.Frame(self.lower_canvas, bg=BG)
        self.lower_rows_id = self.lower_canvas.create_window((0, 0), window=self.lower_rows, anchor='nw')
        self.lower_rows.bind('<Configure>', lambda _: self.lower_canvas.configure(scrollregion=self.lower_canvas.bbox('all')))
        self.lower_canvas.bind('<Configure>', self.resize_lower_rows)
        self.lower_query.trace_add('write', lambda *_: self.draw_lower_skills())
        self.label(self.lower_tab, '名称来自游戏技能目录；仅当技能实际出现在装备下方时提示。',
                   anchor='w', font=('Microsoft YaHei UI', 9)).pack(fill='x', padx=6, pady=(8, 3))
        self.label(self.lower_tab, '显示：背包行列位置 · T 级、部位 + 选中的下技能', anchor='w').pack(fill='x', padx=6, pady=(0, 8))
        self.draw_lower_skills()

    def resize_lower_rows(self, event):
        self.lower_canvas.itemconfigure(self.lower_rows_id, width=event.width)
        for child in self.lower_rows.winfo_children():
            if isinstance(child, tk.Checkbutton):
                child.configure(wraplength=max(200, event.width - 40))

    def draw_lower_skills(self):
        for child in self.lower_rows.winfo_children():
            child.destroy()
        query = self.lower_query.get().strip().lower()
        for skill in self.catalog['skills']:
            if query and query not in skill['label'].lower():
                continue
            cb = self.check(self.lower_rows, skill['label'], self.lower_skill_vars[skill['id']], self.update_lower_count)
            cb.configure(justify='left', wraplength=max(200, self.lower_canvas.winfo_width() - 40))
            cb.pack(fill='x', pady=3)
        if not self.lower_rows.winfo_children():
            self.label(self.lower_rows, '没有符合搜索的技能').pack(anchor='w', pady=12)
        self.lower_canvas.yview_moveto(0)
        self.update_lower_count()

    def choose_lower_skills(self, selected):
        for variable in self.lower_skill_vars.values():
            variable.set(selected)
        self.update_lower_count()

    def update_lower_count(self):
        self.lower_count.configure(text=f'已选 {sum(v.get() for v in self.lower_skill_vars.values())} / {len(self.lower_skill_vars)}')

    def visual_settings(self):
        self.transparent = tk.BooleanVar(value=self.settings.get('transparent_background', True))
        self.check(self.visual_tab, '完全透明背景（关闭后使用半透明深色底）', self.transparent).pack(anchor='w', padx=8, pady=(18, 12))
        self.label(self.visual_tab, '深色模式不透明度（完全透明背景时，文字保持清晰）', anchor='w').pack(fill='x', padx=12)
        self.opacity = tk.DoubleVar(value=self.settings.get('opacity', .86) * 100)
        tk.Scale(self.visual_tab, from_=30, to=100, orient='horizontal', variable=self.opacity, resolution=1,
                 bg=BG, fg=FG, troughcolor=PANEL, highlightthickness=0, activebackground=GOLD).pack(fill='x', padx=12)
        self.font_size = tk.IntVar(value=self.settings.get('font_size', 12))
        font = tk.Frame(self.visual_tab, bg=BG)
        font.pack(fill='x', padx=12, pady=(16, 12))
        self.label(font, '文字大小').pack(side='left', padx=(0, 12))
        tk.Spinbox(font, from_=9, to=18, textvariable=self.font_size, width=6, bg=PANEL, fg=FG, buttonbackground=PANEL, relief='flat').pack(side='left')
        self.label(self.visual_tab, '窗口始终置顶；拖动标题栏移动，拉边框缩放。\n宽度变化时文字自动换行，栏目之间可拖动分隔线。',
                   anchor='w', justify='left').pack(fill='x', padx=12, pady=10)
        self.label(self.visual_tab, '关闭此设置页后继续后台检测。', anchor='w').pack(fill='x', padx=12, pady=8)

    def apply(self):
        try:
            changed = []
            for rule, enabled, minimum in zip(self.rules, self.enabled_vars, self.minimum_vars):
                raw = minimum.get().strip()
                if not raw and not enabled.get():
                    value = float(rule.get('min', 0))
                elif not raw:
                    raise ValueError(f"{rule['label']}：请填写数值，或取消勾选这一项。")
                else:
                    value = float(raw)
                if not math.isfinite(value) or not 0 <= value <= 100000:
                    raise ValueError(f"{rule['label']}：请输入 0 到 100000 之间的数值。")
                changed.append(dict(rule, min=value, enabled=enabled.get()))
            opacity, font_size = float(self.opacity.get()), int(self.font_size.get())
            if not 30 <= opacity <= 100 or not 9 <= font_size <= 18:
                raise ValueError('请检查透明度和文字大小。')
            feature_values = self.feature_settings.values()
        except (ValueError, tk.TclError) as error:
            messagebox.showerror('设置无效', str(error), parent=self.window)
            return
        settings = self.load('loot-overlay-settings.json', {})
        lower_ids = [key for key, var in self.lower_skill_vars.items() if var.get()]
        settings.update(legendary_enabled=self.legend_enabled.get(),
                        legendary_pairs=[key for key, var in self.pair_vars.items() if var.get()],
                        lower_enabled=self.lower_enabled.get(),
                        lower_skill_ids=None if len(lower_ids) == len(self.lower_skill_vars) else lower_ids,
                        transparent_background=self.transparent.get(), opacity=opacity / 100, font_size=font_size)
        settings.update(feature_values)
        settings.update(self.native_settings.values())
        settings.update(self.pickup_library.values())
        settings.update(self.lock_library.values())
        settings.pop('auto_pickup', None)
        self.write('loot-filter-rules.json', changed)
        self.write('loot-overlay-settings.json', settings)
        self.settings = settings
        self.rules = changed
        self.notice.configure(text='已保存', fg=MUTED)

    def cancel(self):
        main = getattr(self.overlay, 'main_window', None)
        if main and main.window is self.window:
            main.dismiss()
        else:
            self.window.destroy()


def open_settings(overlay):
    dialog = Settings(overlay)
    overlay.settings_dialog = dialog
    return dialog.window
