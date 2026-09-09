"""Independent click-through bag marks; calibration is a separate interactive window."""
import ctypes as c
from ctypes import wintypes as w
import datetime
import time
import tkinter as tk
from feature_policy import slot_rect, native_slot_rects
from overlay_panes import read_pointer

u = c.WinDLL('user32', use_last_error=True)
u.GetForegroundWindow.restype = w.HWND
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.IsWindow.argtypes = [w.HWND]
u.IsIconic.argtypes = [w.HWND]
u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongPtrW.restype = c.c_ssize_t
u.SetWindowLongPtrW.argtypes = [w.HWND, c.c_int, c.c_ssize_t]
u.SetWindowLongPtrW.restype = c.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.GetAsyncKeyState.argtypes = [c.c_int]
u.GetAsyncKeyState.restype = c.c_short


def fresh(timestamp, limit=1):
    try:
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(timestamp)).total_seconds()
        return 0 <= age < limit
    except (TypeError, ValueError):
        return False


def foreground_matches(hwnd, pid):
    owner = w.DWORD()
    foreground = u.GetForegroundWindow()
    if not hwnd or not foreground or u.IsIconic(hwnd):
        return False
    u.GetWindowThreadProcessId(foreground, c.byref(owner))
    return owner.value == pid


def game_bounds(hwnd):
    rect, origin = w.RECT(), w.POINT()
    if not hwnd or not u.IsWindow(hwnd) or not u.GetClientRect(hwnd, c.byref(rect)) or not u.ClientToScreen(hwnd, c.byref(origin)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    return (origin.x, origin.y, width, height) if width > 0 and height > 0 else None


def marker_slots(sections, config):
    selected = config.get('sections', {})
    return sorted({item['index'] for key in ('numeric', 'legendary', 'lower')
                   if selected.get(key, True) for item in sections.get(key, [])
                   if isinstance(item.get('index'), int) and 0 <= item['index'] < 60 and not item.get('locked', False)})


class MarkerLayer:
    COLOR_KEY = '#010203'

    def __init__(self, root):
        from marker_window import MarkerWindow
        self.window = MarkerWindow()
        self.canvas = self.window.canvas
        self.hwnd = self.window.hwnd
        self.visible = False
        self.last_key = None
        self.slots = []
        self.reason = '已关闭'

    def hide(self, reason='未显示'):
        u.ShowWindow(self.hwnd, 0)
        if self.last_key is not None:
            self.canvas.delete('all')
        self.visible = False
        self.last_key = None
        self.slots = []
        self.reason = reason

    def update(self, game, config, sections, live, feature):
        if not config.get('enabled', False):
            return self.hide('已关闭')
        if not live or feature.get('status') != 'running' or not fresh(feature.get('heartbeat_utc')) or not feature.get('ui', {}).get('valid'):
            return self.hide('等待读取')
        if not feature['ui'].get('backpack_open') or not foreground_matches(game, feature.get('game_pid')):
            return self.hide('背包未打开或游戏不在前台')
        bounds = game_bounds(game)
        if not bounds:
            return self.hide('等待游戏窗口')
        native = feature.get('native', {})
        grid = native.get('grid')
        boxes = None
        automatic = config.get('automatic', False)
        if (automatic and native.get('game_pid') == feature.get('game_pid')
                and native.get('player_address') == feature.get('ui', {}).get('player_address')
                and isinstance(native.get('utc'), (int, float))
                and 0 <= time.time() - native['utc'] < 1.5):
            boxes = native_slot_rects(grid, *bounds[2:])
        calibrated = boxes is None
        if calibrated:
            if not slot_rect(0, config.get('grid'), *bounds[2:]):
                return self.hide('请校准背包位置，或开启自动定位')
            boxes = {slot: slot_rect(slot, config['grid'], *bounds[2:]) for slot in range(60)}
        slots = marker_slots(sections, config)
        if not slots:
            return self.hide('当前没有符合筛选的未锁定装备')
        key = (bounds, tuple((slot, boxes[slot]) for slot in slots))
        if key != self.last_key:
            x, y, width, height = bounds
            self.window.geometry(f'{width}x{height}{x:+d}{y:+d}')
            self.canvas.delete('all')
            for slot in slots:
                left, top, right, bottom = boxes[slot]
                pad = max(3, round(min(right - left, bottom - top) * .075))
                box = (left + pad, top + pad, right - pad, bottom - pad)
                self.canvas.create_oval(*box, outline='#251b05', width=5)
                self.canvas.create_oval(*box, outline='#ffdb62', width=3)
            self.window.update_idletasks()
            if self.window.state() == 'withdrawn':
                self.window.deiconify()
                self.window.update_idletasks()
            # Never activate or capture mouse input, including on the colored rings.
            u.SetWindowPos(self.hwnd, w.HWND(-1), x, y, width, height, 0x0010 | 0x0040)
            self.last_key = key
        self.visible = True
        self.slots = slots
        self.reason = '已标记（使用校准位置）' if calibrated else '已标记'

    def close(self):
        self.hide()
        self.window.destroy()


class GridCalibration:
    def __init__(self, overlay, settings_window, finished):
        self.overlay, self.settings_window, self.finished = overlay, settings_window, finished
        self.bounds = game_bounds(overlay.game)
        if not self.bounds:
            finished(None)
            return
        self.closed = False
        self.start = None
        self.job = None
        self.was_down = read_pointer()[2]
        self.overlay.calibrating = True
        self.overlay.markers.hide('正在校准')
        self.overlay.root.withdraw()
        settings_window.withdraw()
        self.window = tk.Toplevel(overlay.root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True, '-alpha', .45)
        x, y, width, height = self.bounds
        self.window.geometry(f'{width}x{height}{x:+d}{y:+d}')
        self.canvas = tk.Canvas(self.window, bg='#142333', cursor='crosshair', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(width // 2, 45, text='拖出主背包 10 列 × 6 行的整个格子区，松手确认；Esc 取消',
                                fill='white', font=('Microsoft YaHei UI', 18, 'bold'))
        self.window.bind('<Escape>', lambda event: self.finish(None))
        self.window.deiconify()
        self.window.update_idletasks()
        self.hwnd = u.GetAncestor(self.window.winfo_id(), 2)
        self.window.focus_force()
        self.poll()

    def poll(self):
        self.job = None
        if self.closed:
            return
        if u.GetAsyncKeyState(27) & 0x8000 or not u.IsWindow(self.overlay.game) or u.IsIconic(self.overlay.game):
            self.finish(None)
            return
        sx, sy, down, target = read_pointer()
        ox, oy, width, height = self.bounds
        x, y = max(0, min(width, sx - ox)), max(0, min(height, sy - oy))
        if down and not self.was_down and u.GetAncestor(target, 2) == self.hwnd:
            self.start = (x, y)
        if self.start:
            x0, x1 = sorted((self.start[0], x))
            y0, y1 = sorted((self.start[1], y))
            self.canvas.delete('grid')
            for i in range(11):
                xx = x0 + (x1 - x0) * i / 10
                self.canvas.create_line(xx, y0, xx, y1, fill='#ffdc63', tags='grid')
            for i in range(7):
                yy = y0 + (y1 - y0) * i / 6
                self.canvas.create_line(x0, yy, x1, yy, fill='#ffdc63', tags='grid')
            if not down and self.was_down:
                if x1 - x0 >= 200 and y1 - y0 >= 120:
                    self.finish([x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height])
                    return
                self.start = None
        self.was_down = down
        self.job = self.window.after(16, self.poll)

    def finish(self, grid):
        if self.closed:
            return
        self.closed = True
        if self.job:
            self.window.after_cancel(self.job)
        self.window.destroy()
        self.overlay.calibrating = False
        self.overlay.root.deiconify()
        if self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
        self.finished(grid)
