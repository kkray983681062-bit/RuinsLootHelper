"""One main settings window, shared by startup and the transparent HUD."""
from ui_theme import center_window


class StartupWindow:
    def __init__(self, overlay, game, version, show=True, directory=None):
        from overlay_settings import Settings
        self.overlay, self.user_open = overlay, False
        self.last_state = None
        self.dialog = Settings(overlay, show=False)
        self.dialog.game_exe = str(game)
        self.window = self.dialog.window
        self.window.title('破晓装备助手 ' + version)
        self.window.protocol('WM_DELETE_WINDOW', self.exit)
        self.window.bind('<ButtonPress>', lambda _: setattr(self, 'user_open', True), add='+')
        self.updates = self.dialog.updates
        self.native_button = self.dialog.native_settings.install_button
        overlay.main_window = self
        overlay.settings_dialog = self.dialog
        overlay.popup = self.window
        overlay.project_window = self.show_project
        self.dialog.button(self.dialog.notice.master, '退出助手', self.exit).pack(side='left', padx=14)
        self.set_state({'status': 'waiting_for_game'})
        if show:
            self.window.deiconify()
            center_window(self.window, overlay.root)

    def set_state(self, state):
        phase = state.get('status')
        if phase == self.last_state:
            return
        self.last_state = phase
        text = {'watching':'● 游戏已连接', 'waiting_for_game':'○ 等待游戏启动',
                'discovering':'○ 正在连接游戏', 'waiting_for_backpack':'○ 等待进入角色',
                'monitor_failed':'○ 正在重新连接', 'game_exited':'○ 等待下次启动游戏'}.get(phase, '○ 正在连接游戏')
        self.dialog.game_status.configure(text=text)

    def show(self):
        self.user_open = True
        self.window.attributes('-topmost', True)
        was_hidden = self.window.state() == 'withdrawn'
        self.window.deiconify()
        if was_hidden:
            self.dialog.center_on_screen(self.overlay.root)
        self.window.lift()

    def open_native(self):
        self.show()
        self.dialog.features.select(self.dialog.native_settings.tab)

    def show_project(self):
        self.show()
        self.dialog.features.select(self.dialog.project_tab)

    def exit(self):
        self.user_open = False
        self.overlay.close()

    def dismiss(self):
        self.user_open = False
        self.window.attributes('-topmost', False)
        self.window.withdraw()
