"""Startup status and a direct route to native-component setup."""
import ctypes as c
from ctypes import wintypes as w
import tkinter as tk

BG = '#111a24'
PANEL = '#1e2b37'
FG = '#e3e8ee'
MUTED = '#a4b6c7'
GOLD = '#e0bc70'


class StartupWindow:
    def __init__(self, overlay, game, version, show=True):
        self.overlay = overlay
        self.window = tk.Toplevel(overlay.root)
        self.window.withdraw()
        self.window.title('破晓装备助手 ' + version)
        self.window.configure(bg=BG)
        self.window.resizable(False, False)
        self.window.protocol('WM_DELETE_WINDOW', overlay.close)
        self.last_state = None
        body = tk.Frame(self.window, bg=BG)
        body.pack(fill='both', expand=True, padx=24, pady=22)
        header = tk.Frame(body, bg=BG)
        header.pack(fill='x')
        self.label(header, '破晓装备助手', size=19, bold=True).pack(side='left')
        self.label(header, 'v' + version, color=MUTED, size=9).pack(side='right', anchor='s', pady=6)
        self.label(body, '装备筛选 · 背包定位 · 原生功能加强', color=MUTED, size=9).pack(anchor='w', pady=(4, 20))

        status_row = tk.Frame(body, bg=BG)
        status_row.pack(fill='x')
        self.dot = tk.Canvas(status_row, width=15, height=22, bg=BG, highlightthickness=0)
        self.dot.create_oval(2, 8, 9, 15, fill=GOLD, outline='', tags='status')
        self.dot.pack(side='left', padx=(0, 6))
        self.status = self.label(status_row, '', size=12, bold=True)
        self.status.pack(side='left')
        self.detail = self.label(body, '', color=MUTED, wraplength=580)
        self.detail.pack(fill='x', pady=(7, 17))

        location = tk.Frame(body, bg=PANEL)
        location.pack(fill='x', pady=(0, 16))
        self.label(location, '游戏位置 · 已记住', color=MUTED, size=9).pack(anchor='w', padx=14, pady=(11, 5))
        self.label(location, str(game), size=9, wraplength=552).pack(fill='x', padx=14, pady=(0, 12))

        setup = tk.Frame(body, bg=PANEL)
        setup.pack(fill='x', pady=(0, 19))
        tk.Frame(setup, bg=GOLD, width=3).pack(side='left', fill='y')
        content = tk.Frame(setup, bg=PANEL)
        content.pack(fill='both', expand=True, padx=14, pady=13)
        self.label(content, '首次使用：安装游戏组件', color=GOLD, bold=True).pack(anchor='w')
        self.label(content, '自动拾取、自动锁定和背包自动定位需要此组件。', wraplength=550).pack(anchor='w', pady=(8, 5))
        self.label(content, '功能设置 → 原生功能 → 安装／更新游戏组件', color=MUTED, size=9).pack(anchor='w')
        action = tk.Frame(content, bg=PANEL)
        action.pack(fill='x', pady=(12, 0))
        self.label(action, '安装完成后，重启游戏即可连接。', color=MUTED, size=9).pack(side='left')
        self.native_button = self.button(action, '前往原生功能 →', self.open_native, primary=True)
        self.native_button.pack(side='right')

        footer = tk.Frame(body, bg=BG)
        footer.pack(fill='x')
        self.button(footer, '功能设置', overlay.edit_rules).pack(side='left')
        self.button(footer, '退出助手', overlay.close).pack(side='right')
        self.set_state({'status': 'waiting_for_game'})
        self.window.update_idletasks()
        self.window.geometry(f'640x{max(470, self.window.winfo_reqheight())}')
        self.dark_titlebar()
        if show:
            self.window.deiconify()

    @staticmethod
    def label(parent, text, color=FG, size=10, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color, anchor='w', justify='left',
                        font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kwargs)

    @staticmethod
    def button(parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, relief='flat', borderwidth=0,
                         bg=GOLD if primary else PANEL, fg=BG if primary else FG,
                         activebackground='#f1d394' if primary else '#344653',
                         activeforeground=BG if primary else FG, cursor='hand2',
                         padx=14, pady=8, font=('Microsoft YaHei UI', 10),
                         highlightthickness=1, highlightbackground=parent.cget('bg'), highlightcolor=GOLD)

    def dark_titlebar(self):
        try:
            user = c.windll.user32
            user.GetAncestor.argtypes = [w.HWND, w.UINT]
            user.GetAncestor.restype = w.HWND
            hwnd = user.GetAncestor(self.window.winfo_id(), 2)
            dwm = c.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]
            for attribute, number in ((20, 1), (35, 0x241a11), (36, 0xeee8e3)):
                value = w.DWORD(number)
                dwm.DwmSetWindowAttribute(hwnd, attribute, c.byref(value), c.sizeof(value))
        except (OSError, AttributeError):
            pass

    def set_state(self, state):
        phase, error = state.get('status'), state.get('error')
        key = phase, str(error or '')[:120]
        if key == self.last_state:
            return
        self.last_state = key
        title, description = {
            'waiting_for_game': ('等待游戏启动', '已记住游戏位置。启动游戏并进入角色后，助手会自动连接。'),
            'discovering': ('正在连接游戏', '正在识别本次游戏的装备数据，首次连接通常需要几秒。'),
            'waiting_for_backpack': ('等待进入角色', '进入角色场景后，助手会开始读取背包装备。'),
            'monitor_failed': ('连接暂时中断', '正在重新识别装备数据，请保持游戏运行。'),
            'game_exited': ('等待下一次启动', '游戏已退出。助手会保持待命，下次启动游戏后自动连接。'),
            'watching': ('游戏已连接', '正在准备装备悬浮窗。'),
        }.get(phase, ('正在连接游戏', '连接成功后，将自动显示装备悬浮窗。'))
        if error and phase in ('waiting_for_backpack', 'monitor_failed', 'waiting_for_game'):
            description += '\n' + str(error)[:120]
        self.status.configure(text=title)
        self.detail.configure(text=description)
        self.dot.itemconfigure('status', fill='#86c6b5' if phase == 'watching' else GOLD)

    def open_native(self):
        self.overlay.edit_rules()
        dialog = self.overlay.settings_dialog
        dialog.features.select(dialog.native_settings.tab)
        dialog.native_settings.canvas.yview_moveto(0)
        dialog.native_settings.install_button.focus_set()
        dialog.window.lift()
