"""Native feature controls; installer work and status polling stay off Tk."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from native_client import fresh_status, PROTOCOL
from overlay_scroll import AutoScrollbar
from pickup_library import pickup_options, RANGE_OPTIONS, INTERVAL_OPTIONS, BATCH_OPTIONS


class NativeSettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.tab = tk.Frame(dialog.features, bg='#111a24')
        dialog.features.add(self.tab, text='原生功能')
        self.canvas = tk.Canvas(self.tab, bg='#111a24', highlightthickness=0, yscrollincrement=16)
        self.scrollbar = AutoScrollbar(self.tab, self.canvas)
        self.canvas.pack(side='left', fill='both', expand=True)
        body = tk.Frame(self.canvas, bg='#111a24')
        body_id = self.canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(body_id, width=e.width))
        settings = dialog.settings.get('native', {})
        self.pickup = tk.BooleanVar(value=settings.get('pickup', False))
        options = pickup_options(settings)
        self.range_choice = tk.DoubleVar(value=options['pickup_range_multiplier'])
        self.interval_choice = tk.DoubleVar(value=options['pickup_interval'])
        self.batch_choice = tk.IntVar(value=options['pickup_batch'])
        self.lock = tk.BooleanVar(value=settings.get('lock', False))
        self.auto_recycle = tk.BooleanVar(value=bool(settings.get('auto_recycle', False) and self.lock.get()))
        self.borderless = tk.BooleanVar(value=settings.get('borderless', False))
        self.sections = {key: tk.BooleanVar(value=settings.get('lock_sections', {}).get(key, key == 'numeric'))
                         for key in ('numeric', 'legendary', 'lower')}
        self.messages = queue.Queue()
        self.job = None
        d = dialog
        setup = tk.Frame(body, bg='#1e2b37')
        setup.pack(fill='x', padx=16, pady=(14, 8))
        tk.Label(setup, text='首次使用，请先安装游戏组件', bg='#1e2b37', fg='#ffda7c',
                 font=('Microsoft YaHei UI', 11, 'bold'), anchor='w').pack(fill='x', padx=14, pady=(12, 6))
        tk.Label(setup, text='安装组件 → 重启游戏 → 开启需要的功能', bg='#1e2b37', fg='#e3e8ee',
                 anchor='w').pack(fill='x', padx=14, pady=(0, 4))
        tk.Label(setup, text='自动拾取、自动锁定和背包自动定位均需要组件；原生功能仍为测试版。',
                 bg='#1e2b37', fg='#a4b6c7', anchor='w', justify='left', wraplength=540).pack(fill='x', padx=14, pady=(0, 9))
        self.install_button = d.button(setup, '安装／更新游戏组件（首次约 9 MB）', self.install, gold=True)
        self.install_button.pack(anchor='w', padx=14, pady=(0, 12))
        self.status = d.label(body, '正在检查连接', anchor='w', justify='left', wraplength=540)
        self.status.pack(fill='x', padx=16, pady=(5, 14))
        d.check(body, '自动拾取附近掉落（游戏原生流程）', self.pickup).pack(anchor='w', padx=12, pady=6)
        self.radio_groups = []
        for title, variable, choices, suffix in (
            ('拾取范围', self.range_choice, RANGE_OPTIONS, ' 倍'),
            ('检查 / 拾取间隔', self.interval_choice, INTERVAL_OPTIONS, ' 秒'),
            ('拾取批量', self.batch_choice, BATCH_OPTIONS, ' 件')):
            row = tk.Frame(body, bg='#111a24')
            row.pack(fill='x', padx=24, pady=4)
            d.label(row, title, width=15, anchor='w').pack(side='left')
            group = []
            for value in choices:
                label = (f'{value:.1f}' if variable is self.range_choice else f'{value:g}') + suffix
                if variable is self.batch_choice and value == 0:
                    label = '自动'
                button = tk.Radiobutton(row, text=label, variable=variable, value=value,
                    bg='#111a24', fg='#e6d4a2', selectcolor='#263541', activebackground='#263541',
                    activeforeground='#ffe08a', highlightthickness=0, takefocus=True)
                button.pack(side='left', padx=(0, 8))
                group.append(button)
            self.radio_groups.append(group)
        self.codex_summary = d.label(body, '图鉴屏蔽：与排除库同步', anchor='w')
        self.codex_summary.pack(fill='x', padx=28, pady=4)
        d.button(body, '选择屏蔽的图鉴 / 装备', self.open_exclusions).pack(anchor='w', padx=28, pady=4)
        d.label(body, '自动批量：按耗时分批连续清理范围内可拾取物品。\n切出游戏、打开菜单或背包时暂停；背包满了静默暂停，有空位后恢复。\n排除库接入官方新掉落屏蔽；地上原有物品只跳过助手拾取。',
                justify='left', anchor='w', wraplength=520).pack(fill='x', padx=18, pady=(0, 10))
        d.check(body, '自动锁定符合筛选的装备', self.lock).pack(anchor='w', padx=12, pady=6)
        row = tk.Frame(body, bg='#111a24')
        row.pack(fill='x', padx=18)
        for key, title in (('numeric', '词条'), ('legendary', '上技能'), ('lower', '下技能')):
            d.check(row, title, self.sections[key]).pack(side='left', padx=(0, 18))
        d.label(body, '自动锁定成功后，词条保留显示 10 秒；未自动锁定的照常显示。\n手动解锁后静默 30 秒；装备换格后继续跟随。\n属性完全相同的多件装备会一起暂缓，避免误锁。',
                justify='left', anchor='w').pack(fill='x', padx=18, pady=8)
        self.recycle_check = d.check(body, '背包剩 1 格或已满时，自动无视条件全部回收', self.auto_recycle)
        self.recycle_check.configure(disabledforeground='#63717e')
        self.recycle_check.pack(anchor='w', padx=12, pady=(6, 2))
        d.label(body, '默认关闭；需先开启自动锁定。确认符合筛选的装备已锁定后，\n调用官方回收，沿用游戏中的金币／经验选择。手动解锁后 30 秒内暂缓回收。',
                justify='left', anchor='w', wraplength=520).pack(fill='x', padx=18, pady=(2, 10))
        self.lock_trace = self.lock.trace_add('write', self.update_recycle_available)
        self.update_recycle_available()
        d.label(body, '连接失败时以上功能保持暂停，筛选和普通悬浮窗仍可使用。', anchor='w', wraplength=520).pack(fill='x', padx=18, pady=8)
        self.borderless_check = d.check(body, '全屏兼容：将独占全屏切换为无边框全屏', self.borderless)
        self.borderless_check.pack(anchor='w', padx=12, pady=(6, 14))
        self.last_message = None
        self.job = d.window.after(200, self.refresh)
        self.tab.bind('<Destroy>', self.cleanup)

    def open_exclusions(self):
        library = self.dialog.pickup_library
        library.category.set('图鉴')
        library.query.set('')
        library.redraw()
        self.dialog.features.select(library.tab)

    def update_recycle_available(self, *_):
        enabled = self.lock.get()
        if not enabled:
            self.auto_recycle.set(False)
        self.recycle_check.configure(state='normal' if enabled else 'disabled')

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
        self.last_message = '正在准备原生组件……'
        game, directory = saved.get('game_exe'), loot_overlay.BASE
        messages = self.messages
        def work():
            try:
                install(game, directory)
                messages.put('安装完成，下次启动游戏后自动连接。')
            except Exception as exc:
                messages.put('安装未完成：' + str(exc))
        threading.Thread(target=work, name='NativeInstaller', daemon=True).start()

    def refresh(self):
        self.job = None
        try:
            self.last_message = self.messages.get_nowait()
            self.install_button.configure(state='normal')
        except queue.Empty:
            pass
        state = self.dialog.overlay.read_file('native-status.json', {}) or {}
        if fresh_status(state) and state.get('protocol') != PROTOCOL:
            text = '原生组件版本不匹配，请更新组件并重启游戏。'
        elif fresh_status(state) and state.get('ready'):
            text = '原生组件已连接'
            code = state.get('pickup_state')
            text += {'full': ' · 拾取暂停（背包满）', 'inactive': ' · 拾取暂停（已切出游戏）',
                     'menu': ' · 拾取暂停（菜单或背包打开）', 'requested': ' · 正在拾取',
                     'waiting_for_loot': ' · 等待附近掉落', 'off': ' · 自动拾取已关闭',
                     'waiting_for_result': ' · 等待游戏确认拾取'}.get(code, '')
            skipped = state.get('exclusions', {}) or {}
            gear, codex = skipped.get('equipment', 0), skipped.get('codex', 0)
            if gear or codex:
                text += f'\n本轮按排除库跳过：装备 {gear} 件，图鉴 {codex} 件'
            blocked = state.get('drop_filter', {}) or {}
            if blocked.get('state') == 'connected':
                text += f'\n新掉落屏蔽已连接 · 已拦截 {blocked.get("blocked", 0)} 次'
            elif blocked.get('state') == 'error':
                text += '\n新掉落屏蔽未生效：' + str(blocked.get('error', '接口不兼容'))[:120]
            elif blocked.get('state') == 'waiting_for_function':
                text += '\n新掉落屏蔽：等待游戏接口'
            recycle = state.get('recycle_state')
            if self.auto_recycle.get():
                if not state.get('auto_recycle_supported'):
                    text += '\n自动回收：更新组件并重启游戏后可用'
                else:
                    text += {'requested': '\n已调用官方全部回收',
                             'unlock_grace': '\n自动回收暂缓：手动解锁静默中',
                             'waiting_for_locks': '\n自动回收：等待装备锁定',
                             'inventory_changed': '\n自动回收：背包已变化，重新检查',
                             'error': '\n自动回收未执行，等待检查组件'}.get(recycle, '')
        elif fresh_status(state) and state.get('error'):
            text = '原生连接暂不可用：' + str(state['error'])[:180]
        else:
            text = self.last_message or '未连接；安装组件后需要重新启动游戏。'
        self.status.configure(text=text)
        self.job = self.dialog.window.after(500, self.refresh)

    def cleanup(self, event):
        if event.widget == self.tab and self.lock_trace:
            self.lock.trace_remove('write', self.lock_trace)
            self.lock_trace = None
        if event.widget == self.tab and self.job:
            self.dialog.window.after_cancel(self.job)
            self.job = None

    def values(self):
        return {'native': {'pickup': self.pickup.get(), 'lock': self.lock.get(),
                           'auto_recycle': bool(self.auto_recycle.get() and self.lock.get()),
                           'pickup_range_multiplier': self.range_choice.get(),
                           'pickup_interval': self.interval_choice.get(),
                           'pickup_batch': self.batch_choice.get(),
                           'skip_codex': bool(self.dialog.pickup_library.model.codex_values()),
                           'borderless': self.borderless.get(),
                           'lock_sections': {key: value.get() for key, value in self.sections.items()}}}
