"""Advanced feature cards. File/network work remains outside Tk callbacks."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from native_client import fresh_status, PROTOCOL
from overlay_scroll import AutoScrollbar
from pickup_library import pickup_options, RANGE_OPTIONS, INTERVAL_OPTIONS, BATCH_OPTIONS
from ui_theme import BG, PANEL, FG, MUTED, GOLD, LINE, GREEN, label
from ui_switch import Switch


def component_presentation(connected, protocol_mismatch, installation, message=None):
    """Concise, user-facing component state and matching action label."""
    if protocol_mismatch:
        return '组件需更新 · 更新后重启游戏', '更新组件'
    if connected:
        return '● 游戏组件已安装并连接', '已连接 · 更新组件'
    if isinstance(message, str) and message.startswith('安装未完成：'):
        return message, '校验 / 更新组件'
    installation = installation if isinstance(installation, dict) else {}
    state = installation.get('state')
    if state in ('installed_waiting_for_game_restart', 'installed'):
        return '● 游戏组件已安装 · 重启游戏后自动连接', '已安装 · 校验 / 更新'
    if state == 'installation_changed':
        return '⚠ 已安装文件被修改，请校验或更新组件', '校验 / 更新组件'
    if state == 'installation_missing_file':
        return '⚠ 已安装文件缺失，请校验或更新组件', '校验 / 更新组件'
    if state in ('receipt_invalid', 'installed_for_other_game'):
        return '⚠ 安装记录无效或对应其他游戏目录，请校验或更新组件', '校验 / 更新组件'
    if state == 'game_not_found':
        return '○ 未定位游戏，暂时无法核对组件', '安装 / 更新组件'
    if message:
        return message, '安装游戏组件'
    return '○ 尚未安装游戏组件', '安装游戏组件'


class NativeSettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.tab = tk.Frame(dialog.features, bg=BG)
        dialog.features.add(self.tab, text='进阶辅助')
        self.canvas = tk.Canvas(self.tab, bg=BG, highlightthickness=0, yscrollincrement=20)
        self.scrollbar = AutoScrollbar(self.tab, self.canvas)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        body_id = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.resize(e, body_id))
        settings = dialog.settings.get('native', {})
        options = pickup_options(settings)
        self.pickup = tk.BooleanVar(value=settings.get('pickup', False))
        self.range_choice = tk.DoubleVar(value=options['pickup_range_multiplier'])
        self.interval_choice = tk.DoubleVar(value=options['pickup_interval'])
        self.batch_choice = tk.IntVar(value=options['pickup_batch'])
        self.lock = tk.BooleanVar(value=settings.get('lock', False))
        self.auto_recycle = tk.BooleanVar(value=bool(settings.get('auto_recycle', False) and self.lock.get()))
        self.auto_rift = tk.BooleanVar(value=bool(settings.get('auto_rift', False)))
        self.bagua = tk.BooleanVar(value=bool(settings.get('bagua_marker', False)))
        self.drop_enabled = tk.BooleanVar(value=dialog.settings.get('drop_filter_enabled', True))
        self.borderless = tk.BooleanVar(value=settings.get('borderless', False))
        self.sections = {key: tk.BooleanVar(value=settings.get('lock_sections', {}).get(key, key == 'numeric'))
                         for key in ('numeric', 'legendary', 'lower')}
        self.messages = queue.Queue()
        self.job, self.last_message, self.mode = None, None, None
        self.installation, self.installation_checked = {}, False
        self.cards, self.wrap_labels = [], []
        label(self.body, '进阶辅助', size=20, bold=True).pack(anchor='w', pady=(6, 6))
        label(self.body, '如果你还在第一次探索，建议先保留亲手尝试的乐趣。\n这里的便利，可以晚一点再用。',
              color=MUTED, justify='left').pack(anchor='w')
        dialog.button(self.body, '阅读作者的话 →', lambda: dialog.features.select(dialog.author_tab)).pack(anchor='w', pady=(6, 12))
        setup = tk.Frame(self.body, bg=PANEL)
        setup.pack(fill='x', pady=(0, 16))
        self.status = label(setup, '游戏组件 · 正在检查连接', color=MUTED)
        self.status.pack(side='left', padx=12, pady=12)
        self.install_button = dialog.button(setup, '安装 / 更新组件', self.install)
        self.install_button.pack(side='right', padx=6, pady=6)
        self.card_grid = tk.Frame(self.body, bg=BG)
        self.card_grid.pack(fill='x')
        self.card_grid.columnconfigure(0, weight=1, uniform='cards')
        self.card_grid.columnconfigure(1, weight=1, uniform='cards')
        self.pickup_card, self.pickup_check = self.card('自动拾取', '调用游戏拾取流程，收取附近掉落。', self.pickup)
        self.pickup_status = self.text(self.pickup_card, '已关闭', GREEN)
        detail = self.details(self.pickup_card)
        self.radio_groups = []
        for title, variable, choices, suffix in (
            ('拾取范围', self.range_choice, RANGE_OPTIONS, ' 倍'),
            ('拾取间隔', self.interval_choice, INTERVAL_OPTIONS, ' 秒'),
            ('每批最多尝试', self.batch_choice, [x for x in BATCH_OPTIONS if x], ' 件')):
            self.text(detail, title)
            row = tk.Frame(detail, bg=PANEL); row.pack(fill='x')
            group = []
            for value in choices:
                text = (f'{value:.1f}' if variable is self.range_choice else f'{value:g}') + suffix
                rb = tk.Radiobutton(row, text=text, variable=variable, value=value, bg=PANEL,
                                    fg=FG, selectcolor=BG, activebackground=PANEL,
                                    activeforeground=GOLD, highlightthickness=0)
                rb.pack(side='left', padx=(0, 5)); group.append(rb)
            self.radio_groups.append(group)
        # Legacy automatic batches remain readable; new choices have explicit limits.
        if self.batch_choice.get() == 0:
            self.batch_choice.set(4)
        self.text(detail, '切出游戏、打开菜单或背包时暂停。背包满了静默暂停，有空位再恢复。')
        self.drop_card, self.drop_check = self.card('掉落屏蔽清单', '选择不想掉落的装备和图鉴。', self.drop_enabled)
        self.codex_summary = self.text(self.drop_card, '与装备、图鉴清单同步', GREEN)
        dialog.button(self.drop_card, '设置清单 →', self.open_exclusions).pack(anchor='w', padx=14, pady=(4, 14))
        self.lock_card, self.lock_check = self.card('自动锁定', '先保护筛选、品质或装备库命中的装备。', self.lock)
        self.recycle_card = self.lock_card
        self.lock_status = self.text(self.lock_card, '已关闭', GREEN)
        lock_details = self.details(self.lock_card)
        for key, title in (('numeric', '词条'), ('legendary', '上技能'), ('lower', '下技能')):
            dialog.check(lock_details, title, self.sections[key]).pack(side='top', anchor='w')
        self.text(lock_details, '手动解锁后静默 30 秒；装备换格后继续跟随。相同属性的装备会一起暂缓。')
        self.lock_library_summary = self.text(self.lock_card, '品质 / 装备库规则：未设置', GREEN)
        dialog.button(self.lock_card, '配置品质 / 装备库规则 →', self.open_lock_library).pack(
            anchor='w', padx=14, pady=(0, 4))
        tk.Frame(self.lock_card, bg=LINE, height=1).pack(fill='x', padx=14, pady=(12, 8))
        self.text(self.lock_card, '先锁定达标装备，再回收', GOLD)
        recycle_head = tk.Frame(self.lock_card, bg=PANEL)
        recycle_head.pack(fill='x', padx=14, pady=(8, 0))
        label(recycle_head, '自动回收', size=12, bold=True).pack(side='left')
        self.recycle_check = Switch(recycle_head, self.auto_recycle)
        self.recycle_check.pack(side='right')
        self.text(self.lock_card, '需先开启自动锁定。确认达标装备已锁定后，再按游戏设置回收。')
        self.recycle_status = self.text(self.lock_card, '已关闭', GREEN)
        recycle_details = self.details(self.lock_card)
        self.text(recycle_details, '背包剩 1 格或已满时，回收所有未锁定物品；沿用游戏的金币 / 经验选择。手动解锁后 30 秒内暂缓。')
        self.rift_card, self.rift_check = self.card('自动开门', '自动开启附近的空间裂隙。', self.auto_rift)
        self.rift_status = self.text(self.rift_card, '等待进入角色后检查使用条件', GREEN)
        self.rift_details = self.details(self.rift_card, '使用条件')
        self.text(self.rift_details, '满足其一：等级 ≥ 50；或额外掉落率与额外极品率均 ≥ 300%。每次助手启动检查一次，通过后切换角色仍可使用。')
        self.bagua_card, self.bagua_check = self.card('八卦入口提示', '在封印之地的小地图上标出正确入口。', self.bagua)
        self.bagua_status = self.text(self.bagua_card, '已关闭', GREEN)
        detail = self.details(self.bagua_card)
        self.text(detail, '进入八卦触发区域后显示红点，离开后隐藏。只显示入口位置，不改变传送规则。地图放大时隐藏；加入他人房间时可能读不到入口。')
        self.footer = tk.Frame(self.body, bg=BG)
        self.footer.pack(fill='x', pady=(12, 4))
        self.borderless_check = dialog.check(self.footer, '全屏兼容：切换为无边框全屏', self.borderless)
        self.borderless_check.pack(anchor='w')
        label(self.footer, '这些功能需要游戏组件；装备筛选可以独立使用。', color=MUTED).pack(anchor='w', pady=8)
        self.lock_trace = self.lock.trace_add('write', self.update_recycle_available)
        self.update_recycle_available()
        self.job = dialog.window.after(200, self.refresh)
        self.tab.bind('<Destroy>', self.cleanup)

    def card(self, title, description, variable):
        frame = tk.Frame(self.card_grid, bg=PANEL)
        head = tk.Frame(frame, bg=PANEL)
        head.pack(fill='x', padx=14, pady=(14, 4))
        label(head, title, size=12, bold=True).pack(side='left')
        control = Switch(head, variable); control.pack(side='right')
        self.text(frame, description)
        self.cards.append(frame)
        return frame, control

    def text(self, parent, text, color=MUTED):
        widget = label(parent, text, color=color, wraplength=300, justify='left')
        widget.pack(fill='x', padx=14, pady=(4, 8))
        self.wrap_labels.append(widget)
        return widget

    def details(self, card, title='设置'):
        frame = tk.Frame(card, bg=PANEL)
        def toggle():
            if frame.winfo_manager():
                frame.pack_forget(); action.configure(text=title + ' ▾')
            else:
                frame.pack(fill='x', padx=0, pady=(0, 12), after=action)
                action.configure(text=title + ' ▴')
        action = self.dialog.button(card, title + ' ▾', toggle)
        action.pack(anchor='w', padx=0, pady=(0, 6))
        return frame

    def resize(self, event, body_id):
        self.canvas.itemconfigure(body_id, width=event.width)
        if len(self.cards) < 5:
            return
        mode = event.width >= 650
        if mode != self.mode:
            self.mode = mode
            for card in self.cards:
                card.grid_forget()
            if mode:
                for card, row, col, span in ((self.pickup_card,0,0,1),(self.drop_card,1,0,1),
                         (self.lock_card,0,1,2),(self.rift_card,2,0,1),(self.bagua_card,2,1,1)):
                    card.grid(row=row, column=col, rowspan=span, sticky='nsew', padx=(0,12) if col==0 else 0, pady=(0,12))
            else:
                for row, card in enumerate((self.pickup_card,self.drop_card,self.lock_card,self.rift_card,self.bagua_card)):
                    card.grid(row=row, column=0, columnspan=2, sticky='nsew', pady=(0,12))
        width = max(230, (event.width-12)//2-28 if mode else event.width-28)
        for widget in self.wrap_labels:
            widget.configure(wraplength=width)

    def open_exclusions(self):
        self.dialog.features.select(self.dialog.pickup_library.tab)

    def open_lock_library(self):
        self.dialog.features.select(self.dialog.lock_library.tab)

    def update_recycle_available(self, *_):
        enabled = self.lock.get()
        if not enabled:
            self.auto_recycle.set(False)
        self.recycle_check.configure(state='normal' if enabled else 'disabled')
        self.recycle_status.configure(text='已关闭' if enabled else '需先开启自动锁定')

    def install(self):
        import loot_overlay
        from native_support import install
        saved = self.dialog.overlay.read_file('app-settings.json', {}) or {}
        if not saved:
            try:
                import json
                saved = json.loads((loot_overlay.BASE / 'app-settings.json').read_text(encoding='utf8'))
            except (OSError, ValueError):
                self.last_message = '尚未定位游戏，启动助手后再安装。'
                return
        self.install_button.configure(state='disabled')
        self.last_message = '正在校验并安装本地组件……'
        game, directory = saved.get('game_exe'), loot_overlay.BASE
        messages = self.messages
        def work():
            try:
                install(game, directory)
                messages.put('安装完成，下次启动游戏后自动连接。')
            except Exception as exc:
                messages.put('安装未完成：' + str(exc))
        threading.Thread(target=work, name='NativeInstaller', daemon=True).start()

    def inspect_installation(self):
        import loot_overlay
        from native_support import installation_status
        saved = self.dialog.overlay.read_file('app-settings.json', {}) or {}
        saved = saved if isinstance(saved, dict) else {}
        game = saved.get('game_exe') or getattr(self.dialog, 'game_exe', None)
        try:
            return installation_status(game, loot_overlay.BASE)
        except (OSError, ValueError):
            return {'state': 'receipt_invalid'}

    def refresh(self):
        self.job = None
        refresh_installation = not self.installation_checked
        try:
            self.last_message = self.messages.get_nowait()
            self.install_button.configure(state='normal')
            refresh_installation = True
        except queue.Empty:
            pass
        if refresh_installation:
            self.installation = self.inspect_installation()
            self.installation_checked = True
        state = self.dialog.overlay.read_file('native-status.json', {}) or {}
        connected = fresh_status(state) and state.get('protocol') == PROTOCOL and state.get('ready')
        self.update_rift_available(state)
        protocol_mismatch = fresh_status(state) and state.get('protocol') != PROTOCOL
        status, install_label = component_presentation(connected, protocol_mismatch, self.installation, self.last_message)
        self.status.configure(text=status, fg=GREEN if connected or self.installation.get('state') in
                              ('installed_waiting_for_game_restart', 'installed') else GOLD if status.startswith('⚠') else MUTED)
        self.install_button.configure(text=install_label)
        code = state.get('pickup_state')
        pickup = {'full':'背包已满，已暂停','inactive':'切出游戏，已暂停','menu':'菜单或背包打开，已暂停',
                  'requested':'正在拾取','waiting_for_loot':'等待附近掉落','waiting_for_result':'等待游戏确认',
                  'recycling':'回收中，稍后继续'}.get(code, '等待附近掉落')
        self.pickup_status.configure(text='已关闭' if not self.pickup.get() else pickup if connected else '等待游戏组件连接')
        self.lock_status.configure(text='已关闭' if not self.lock.get() else '正在保护达标装备' if connected else '等待游戏组件连接')
        library = getattr(self.dialog, 'lock_library', None)
        if library is not None:
            self.lock_library_summary.configure(text=library.summary())
        recycle = {'requested':'已调用游戏回收','unlock_grace':'手动解锁静默中','waiting_for_locks':'等待达标装备锁定',
                   'inventory_changed':'背包变化，重新检查','error':'暂不可用，请检查组件'}.get(state.get('recycle_state'), '等待背包剩余 1 格')
        self.recycle_status.configure(text='需先开启自动锁定' if not self.lock.get() else '已关闭' if not self.auto_recycle.get()
                                      else recycle if connected else '等待游戏组件连接')
        bagua = state.get('bagua', {}) or {}
        self.bagua_status.configure(text='已关闭' if not self.bagua.get() else '等待游戏组件连接' if not connected else
            '更新组件后可用' if not state.get('bagua_supported') else
            {'shown':'正确入口已标记','waiting':'等待进入八卦区域','inactive':'切出游戏，已暂停',
             'error':'入口暂不可用','stopped':'入口提示已暂停，请重新开关'}.get(bagua.get('state'), '等待进入八卦区域'))
        library = self.dialog.pickup_library.model
        selected = len(library.equipment_values()) + len(library.codex_values())
        self.codex_summary.configure(text='已关闭，清单已保留' if not self.drop_enabled.get() else
                                    f'已选择 {selected} 种物品' + (' · 已连接' if connected else ' · 等待组件'))
        status = self.dialog.overlay.read_file('continuous-status.json', {}) or {}
        self.dialog.game_status.configure(text='● 游戏已连接' if status.get('status') == 'watching' else '○ 等待游戏连接')
        self.job = self.dialog.window.after(500, self.refresh)

    def update_rift_available(self, state):
        connected = fresh_status(state) and state.get('protocol') == PROTOCOL and state.get('ready')
        rift = state.get('rift', {}) if isinstance(state.get('rift'), dict) else {}
        available = bool(connected and state.get('rift_supported') and rift.get('eligible') is True)
        self.rift_check.configure(state='normal' if available else 'disabled')
        if not connected:
            text = '等待进入角色后检查使用条件'
        elif not state.get('rift_supported'):
            text = '更新游戏组件并重启游戏后可用'
        elif available:
            text = '本次已解锁，切换角色仍可使用'
            if self.auto_rift.get():
                text += {'requested': ' · 已发出开门指令', 'watching': ' · 正在检测附近裂隙',
                         'menu': ' · 菜单打开，暂缓开门', 'error': ' · 开门调用失败'}.get(rift.get('state'), '')
        elif rift.get('checked'):
            if self.auto_rift.get():
                self.auto_rift.set(False)
            text = '未满足使用条件。换达标角色后重开助手可重新检测'
        else:
            text = '等待角色属性就绪后检测资格'
        if rift.get('checked'):
            def shown(value, suffix=''):
                return f'{value:g}{suffix}' if isinstance(value, (int, float)) and not isinstance(value, bool) else '未读取'
            text += ('\n首次检测：等级 ' + shown(rift.get('level')) +
                     ' · 额外掉落率 ' + shown(rift.get('extra_drop_pct'), '%') +
                     ' · 额外极品率 ' + shown(rift.get('extra_elite_pct'), '%'))
        self.rift_status.configure(text=text)

    def cleanup(self, event):
        if event.widget != self.tab:
            return
        if self.lock_trace:
            self.lock.trace_remove('write', self.lock_trace)
            self.lock_trace = None
        if self.job:
            self.dialog.window.after_cancel(self.job)
            self.job = None

    def values(self):
        values = dict(self.dialog.settings.get('native', {}))
        values.update(pickup=self.pickup.get(), lock=self.lock.get(), auto_rift=self.auto_rift.get(),
                      bagua_marker=self.bagua.get(), auto_recycle=bool(self.auto_recycle.get() and self.lock.get()),
                      pickup_range_multiplier=self.range_choice.get(), pickup_interval=self.interval_choice.get(),
                      pickup_batch=self.batch_choice.get(), skip_codex=bool(self.dialog.pickup_library.model.codex_values()),
                      borderless=self.borderless.get(), lock_sections={key: var.get() for key,var in self.sections.items()})
        return {'native': values, 'drop_filter_enabled': self.drop_enabled.get()}
