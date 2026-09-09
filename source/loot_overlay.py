"""Resizable local overlay for separate numeric, upper-skill and lower-skill views."""
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
import os
import pathlib
import time
import traceback
import tkinter as tk
from gear_view import configured_rules, position, select_sections
from overlay_panes import SectionPanes
from overlay_markers import MarkerLayer
from overlay_feed import OverlayFeed
from overlay_scroll import dark_scrollbars
from tk_lifecycle import guard_tk

BASE = pathlib.Path(__file__).resolve().parent
SECTION_TITLES = {'numeric': '词条', 'legendary': '上技能', 'lower': '下技能'}


def empty_sections():
    return {key: [] for key in SECTION_TITLES}


u = c.WinDLL('user32', use_last_error=True)
u.GetAncestor.argtypes = [w.HWND, w.UINT]
u.GetAncestor.restype = w.HWND
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetWindowRect.restype = w.BOOL
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.GetWindowLongPtrW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongPtrW.restype = c.c_ssize_t
u.SetWindowLongPtrW.argtypes = [w.HWND, c.c_int, c.c_ssize_t]
u.SetWindowLongPtrW.restype = c.c_ssize_t
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
u.SetWindowPos.restype = w.BOOL
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, c.c_ubyte, w.DWORD]
u.SetLayeredWindowAttributes.restype = w.BOOL
u.IsWindow.argtypes = [w.HWND]
u.IsWindowVisible.argtypes = [w.HWND]
u.IsIconic.argtypes = [w.HWND]
EnumCallback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [EnumCallback, w.LPARAM]

def load(name):
    for attempt in range(4):
        try:
            return json.loads((BASE / name).read_text(encoding='utf-8'))
        except PermissionError:
            # The 20 Hz reader atomically replaces its snapshots. Windows can
            # briefly deny a concurrent open while that replacement completes.
            if attempt == 3:
                raise
            time.sleep(0.005)

def write_json(name, payload):
    path = BASE / name
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(4):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 3:
                raise
            time.sleep(0.01)

def find_game(pid):
    found = []
    @EnumCallback
    def callback(hwnd, _):
        process = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, c.byref(process))
        if process.value == pid and u.IsWindowVisible(hwnd):
            rect = w.RECT()
            if u.GetWindowRect(hwnd, c.byref(rect)):
                area = (rect.right - rect.left) * (rect.bottom - rect.top)
                if area > 200000:
                    found.append((area, hwnd))
        return True
    u.EnumWindows(callback, 0)
    return max(found)[1] if found else None

class Overlay:
    BG = '#111a24'
    def __init__(self):
        try:
            u.SetProcessDpiAwarenessContext(c.c_void_p(-4))
        except AttributeError:
            pass
        self.settings = load('loot-overlay-settings.json')
        self.closed = False
        self.root = tk.Tk()
        self.root.withdraw()
        guard_tk(self.root)
        self.feed = OverlayFeed(BASE)
        self.root.title('空位：读取中 · 免费助手')
        self.root.configure(bg=self.BG)
        self.root.minsize(320, 230)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', self.settings.get('opacity', 0.86))
        self.root.option_add('*Font', ('Microsoft YaHei UI', 11))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.report_callback_exception = self.callback_error
        bar = tk.Frame(self.root, bg=self.BG)
        bar.pack(fill='x', padx=12, pady=(9, 4))
        self.status_label = tk.Label(bar, text='正在读取', fg='#d5eee3', bg=self.BG, font=('Microsoft YaHei UI', 9))
        self.status_label.pack(anchor='w')
        actions = tk.Frame(bar, bg=self.BG)
        actions.pack(fill='x', pady=(5, 0))
        self.settings_button = tk.Button(actions, text='功能设置', command=self.edit_rules, bg='#263541', fg='#e6d4a2', relief='flat', padx=9, takefocus=False)
        self.settings_button.pack(side='right')
        self.display_button = tk.Button(actions, text='显示栏目', command=self.show_sections, bg='#263541', fg='#e6d4a2', relief='flat', padx=7, takefocus=False)
        self.display_button.pack(side='right', padx=(0, 5))
        self.display_popup = None
        self.section_vars = {}
        for key, title in SECTION_TITLES.items():
            variable = tk.BooleanVar(value=self.settings.get('section_visibility', {}).get(key, True))
            self.section_vars[key] = variable
        self.panes = SectionPanes(self.root, layouts=self.settings.get('section_layouts'), on_layout=self.save_layout)
        dark_scrollbars(self.root)
        self.panes.pack(fill='both', expand=True, padx=10, pady=(2, 8))
        self.numeric_title, self.numeric = self.section('numeric', '词条')
        self.legendary_title, self.legendary = self.section('legendary', '上技能')
        self.lower_title, self.lower = self.section('lower', '下技能')
        self.text_widgets = (self.numeric, self.legendary, self.lower)
        self.game = None
        self.hwnd = None
        self.placed = False
        self.last_render = None
        self.last_error = None
        self.next_status = 0
        self.save_job = None
        self.popup = None
        self.appearance_key = None
        self.free_slots = None
        self.calibrating = False
        self.markers = MarkerLayer(self.root)
        self.root.bind('<Configure>', self.geometry_changed)
        self.tick_job = self.root.after(100, self.tick)

    def callback_error(self, kind, value, tb):
        self.last_error = ''.join(traceback.format_exception(kind, value, tb))
        self.feed.submit('ui-error.json', {'error': self.last_error, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        self.status_label.configure(text='界面操作失败，可重试')

    def show_sections(self):
        if self.display_popup and self.display_popup.winfo_exists():
            self.display_popup.destroy()
            self.display_popup = None
            return
        self.panes.release()
        popup = tk.Toplevel(self.root)
        self.display_popup = popup
        popup.withdraw()
        popup.title('显示栏目')
        popup.configure(bg='#1e2b37')
        popup.attributes('-topmost', True)
        popup.resizable(False, False)
        for key, title in SECTION_TITLES.items():
            tk.Checkbutton(popup, text=title, variable=self.section_vars[key], command=self.change_visibility,
                bg='#1e2b37', fg='#e3e8ee', activebackground='#354450', activeforeground='#ffde83',
                selectcolor='#263541', anchor='w', padx=18, pady=5).pack(fill='x')
        popup.geometry(f'150x132{self.display_button.winfo_rootx():+d}{self.display_button.winfo_rooty()+30:+d}')
        popup.deiconify()
        popup.lift()
        # No global/local grab: a menu must never capture subsequent HUD clicks.

    def section(self, key, title):
        return title, self.panes.register(key, title)

    def render(self, sections, live):
        numeric, skills, lower = sections['numeric'], sections['legendary'], sections['lower']
        numeric_rows, skill_rows, lower_rows = [], [], []
        columns = self.settings.get('columns', 10)
        for item in numeric:
            notice = '（已自动锁定，10 秒后不显示）' if item.get('auto_locked') else ''
            numeric_rows.append((position(item['index'], columns) + notice, 'place'))
            numeric_rows.append(('  ·  '.join(f"{x['label']} {x['display']}" for x in item['hits']), 'hit'))
        for item in skills:
            skill_rows.append((position(item['index'], columns) + f" · {item['tier_label']} {item['type_label']}", 'place'))
            skill_rows.append(('；'.join(x['name'] for x in item['inherent_skills']), 'hit'))
        for item in lower:
            lower_rows.append((position(item['index'], columns) + f" · {item['tier_label']} {item['type_label']}", 'place'))
            lower_rows.append(('；'.join(x['name'] for x in item['addable_skills']), 'hit'))
        if not numeric:
            numeric_rows.append(('暂无达标装备' if live else '等待读取，旧结果已清空', 'muted'))
        if not skills:
            skill_rows.append(('暂无符合条件的上技能' if live else '等待读取', 'muted'))
        if not lower:
            lower_rows.append(('当前背包没有符合筛选的下技能装备' if live else '等待读取', 'muted'))
        for widget, rows in zip(self.text_widgets, (numeric_rows, skill_rows, lower_rows)):
            widget.set_runs(rows)

    def change_visibility(self):
        settings = self.read_file('loot-overlay-settings.json', self.settings)
        settings['section_visibility'] = {key: var.get() for key, var in self.section_vars.items()}
        self.write_file('loot-overlay-settings.json', settings)
        self.settings = settings
        self.apply_visibility()

    def apply_visibility(self):
        visible = self.settings.get('section_visibility', {})
        keys = [key for key in SECTION_TITLES if visible.get(key, True)]
        for key, var in self.section_vars.items():
            if var.get() != (key in keys):
                var.set(key in keys)
        if tuple(keys) == self.panes.visible_keys:
            return
        self.root.minsize(320, max(130, 76 * len(keys) + 70))
        self.panes.set_visible(keys)

    def save_layout(self, layouts):
        settings = self.read_file('loot-overlay-settings.json', self.settings)
        settings['section_layouts'] = layouts
        self.write_file('loot-overlay-settings.json', settings)
        self.settings = settings

    def geometry_changed(self, event):
        if event.widget != self.root or not self.placed:
            return
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(600, self.save_geometry)

    def save_geometry(self):
        self.save_job = None
        settings = self.read_file('loot-overlay-settings.json', self.settings)
        settings.update(width=self.root.winfo_width(), height=self.root.winfo_height(),
                        x=self.root.winfo_x(), y=self.root.winfo_y(), window_position_version=1)
        self.write_file('loot-overlay-settings.json', settings)
        self.settings = settings

    def place(self):
        rect = w.RECT()
        if not self.game or not u.GetWindowRect(self.game, c.byref(rect)):
            return
        width = max(320, self.settings.get('width', 460))
        height = max(230, self.settings.get('height', 480))
        x = rect.left + (rect.right - rect.left - width) // 2
        y = rect.top + (rect.bottom - rect.top - height) // 2
        # Center once after upgrading; subsequent user moves keep their position.
        if self.settings.get('window_position_version') == 1:
            x = self.settings.get('x', x)
            y = self.settings.get('y', y)
        x = max(rect.left, min(x, rect.right - 120))
        y = max(rect.top + 20, min(y, rect.bottom - 100))
        # Tk accepts signed offsets, but treats negative offsets as distances
        # from the far screen edge. SetWindowPos below pins physical coordinates.
        self.root.geometry(f'{width}x{height}{x:+d}{y:+d}')
        self.root.update_idletasks()
        self.hwnd = u.GetAncestor(self.root.winfo_id(), 2)
        style = u.GetWindowLongPtrW(self.hwnd, -20)
        # An ordinary interactive window: Windows/Tk manage focus and capture.
        u.SetWindowLongPtrW(self.hwnd, -20, style & ~(0x00000080 | 0x08000000))
        self.root.deiconify()
        self.root.update_idletasks()
        self.hwnd = u.GetAncestor(self.root.winfo_id(), 2)
        u.SetWindowLongPtrW(self.hwnd, -20, u.GetWindowLongPtrW(self.hwnd, -20) & ~(0x80 | 0x08000000))
        u.SetWindowPos(self.hwnd, w.HWND(-1), int(x), int(y), 0, 0, 0x0010 | 0x0040 | 0x0001)
        self.panes.schedule_layout()
        self.placed = True

    def read_file(self, name, default=None):
        return self.feed.read(name, default)

    def write_file(self, name, payload):
        self.feed.submit(name, payload)

    def apply_appearance(self):
        key = (bool(self.settings.get('transparent_background', False)),
               max(.3, min(1., float(self.settings.get('opacity', .86)))),
               max(9, min(18, int(self.settings.get('font_size', 12)))))
        if key == self.appearance_key:
            return
        transparent, opacity, font = key
        if transparent:
            opacity = 1.0
        if not self.hwnd:
            self.root.attributes('-alpha', opacity)
            self.root.attributes('-transparentcolor', self.BG if transparent else '')
        self.panes.set_font(font)
        self.panes.set_transparent(transparent)
        if self.hwnd:
            # A fully opaque Tk window can lose WS_EX_LAYERED when mapped.
            # Use one native owner for alpha/color-key updates once HWND exists.
            style = u.GetWindowLongPtrW(self.hwnd, -20)
            if not style & 0x80000:
                u.SetWindowLongPtrW(self.hwnd, -20, style | 0x80000)
            if not u.SetLayeredWindowAttributes(self.hwnd, 0x241A11 if transparent else 0, round(opacity * 255), 3 if transparent else 2):
                raise OSError(c.get_last_error(), 'Cannot apply overlay transparency')
            dwm = c.WinDLL('dwmapi')
            dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]
            dark = w.BOOL(True)
            dwm.DwmSetWindowAttribute(self.hwnd, 20, c.byref(dark), c.sizeof(dark))
            # Native caption stays draggable/resizable and uses the same dark palette.
            for attribute, color in ((35, 0x241A11), (36, 0xC7B6A4), (34, 0x241A11)):
                value = w.DWORD(color)
                dwm.DwmSetWindowAttribute(self.hwnd, attribute, c.byref(value), c.sizeof(value))
            self.appearance_key = key

    def edit_rules(self):
        self.panes.release()
        if getattr(self, 'main_window', None):
            self.main_window.show()
            return
        if self.display_popup and self.display_popup.winfo_exists():
            self.display_popup.destroy()
            self.display_popup = None
        if self.popup and self.popup.winfo_exists():
            self.popup.deiconify()
            self.popup.lift()
            return
        from overlay_settings import open_settings
        self.popup = open_settings(self)

    def tick(self):
        if getattr(self, 'closed', False):
            return
        if getattr(self, 'tick_job', None):
            self.root.after_cancel(self.tick_job)
            self.tick_job = None
        started = time.perf_counter()
        try:
            snapshot = self.feed.snapshot
            if snapshot.stop_requested:
                self.close()
                return
            status, current = snapshot.status, snapshot.current
            self.settings = self.read_file('loot-overlay-settings.json', self.settings)
            live, rules, sections = snapshot.live, snapshot.rules, snapshot.sections
            self.apply_visibility()
            key = (live, sections)
            if key != self.last_render and self.panes.dragging is None:
                self.render(sections, live)
                self.write_file('matches-current.json', dict(sections, live=live))
                self.last_render = key
            status_text = f"正在筛选 · 已启用{sum(x.get('enabled', True) for x in rules)}条规则" if live else '等待读取'
            if self.status_label.cget('text') != status_text:
                self.status_label.configure(text=status_text)
            self.free_slots = current.get('backpack_free_slots') if live else None
            title = f"空位：{self.free_slots if self.free_slots is not None else '读取中'} · 免费助手"
            if self.root.title() != title:
                self.root.title(title)
            if not self.game or not u.IsWindow(self.game):
                self.game = find_game(status.get('game_pid', 0))
            if not self.placed and self.game:
                self.place()
            self.apply_appearance()
            if self.hwnd and self.game:
                desired = not u.IsIconic(self.game) and not self.calibrating
                if bool(u.IsWindowVisible(self.hwnd)) != desired:
                    u.ShowWindow(self.hwnd, 4 if desired else 0)
            if self.calibrating:
                self.markers.hide('正在校准')
            else:
                self.markers.update(self.game, self.settings.get('backpack_markers', {}), sections, live,
                                    snapshot.ui)
            if time.monotonic() >= self.next_status:
                self.write_file('overlay-status.json', {'status': 'running', 'pid': os.getpid(), 'hwnd': int(self.hwnd) if self.hwnd else None,
                    'game_hwnd': int(self.game) if self.game else None,
                    'native_window_visible': bool(self.hwnd and u.IsWindowVisible(self.hwnd)),
                    'topmost': bool(self.hwnd and u.GetWindowLongPtrW(self.hwnd, -20) & 8),
                    'live': live, 'numeric_matches': len(sections['numeric']), 'legendary_matches': len(sections['legendary']),
                    'lower_matches': len(sections['lower']), 'visible_sections': list(self.panes.visible_keys),
                    'marker_status': self.markers.reason, 'marker_slots': self.markers.slots,
                    'marker_hwnd': int(self.markers.hwnd),
                    'divider_positions': [self.panes.sash_coord(i)[1] for i in range(max(0, len(self.panes.visible_keys) - 1))],
                    'dragging_divider': self.panes.dragging is not None, 'last_drag_pixels': self.panes.last_drag_pixels,
                    'pane_hwnd': self.panes.winfo_id(),
                    'pane_bounds': [self.panes.winfo_rootx(), self.panes.winfo_rooty(), self.panes.winfo_width(), self.panes.winfo_height()],
                    'divider_line_width': self.panes.line_width,
                    'divider_hit_width': self.panes.hit_width,
                    'divider_implementation': 'tk.Canvas',
                    'section_bounds': {key: [self.panes.sections[key].winfo_y(),
                                             self.panes.sections[key].winfo_height()]
                                       for key in self.panes.visible_keys},
                    'divider_events': self.panes.drag_events,
                    # ttk creates its popup in Tcl without a Python Widget;
                    # grab_current() tries to resolve it and raises KeyError.
                    'tk_grab': str(self.root.tk.call('grab', 'current', self.root._w)), 'last_error': self.last_error,
                    'free_slots': self.free_slots, 'rule_count': len(rules), 'enabled_rules': sum(x.get('enabled', True) for x in rules),
                    'transparent_background': self.settings.get('transparent_background', False),
                    'opacity': self.settings.get('opacity', .86), 'font_size': self.settings.get('font_size', 12),
                    'include_locked': self.settings.get('include_locked', False),
                    'columns': self.settings.get('columns'), 'width': self.root.winfo_width(), 'height': self.root.winfo_height(),
                    'ui_tick_ms': round((time.perf_counter() - started) * 1000, 2),
                    'heartbeat_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'error': snapshot.error})
                self.next_status = time.monotonic() + 1
        except Exception as exc:
            self.markers.hide('等待读取')
            self.last_error = f'{type(exc).__name__}: {exc}'
            self.last_render = None
            self.render(empty_sections(), False)
            self.status_label.configure(text='等待读取')
            self.write_file('overlay-status.json', {'status': 'display_error', 'pid': os.getpid(), 'error': f'{type(exc).__name__}: {exc}'})
        self.tick_job = self.root.after(100, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.tick_job:
            self.root.after_cancel(self.tick_job)
            self.tick_job = None
        if self.save_job:
            self.root.after_cancel(self.save_job)
            self.save_geometry()
        self.write_file('overlay-status.json', {'status': 'stopped', 'pid': os.getpid()})
        self.write_file('matches-current.json', dict(empty_sections(), live=False))
        self.feed.close()
        self.markers.close()
        self.root.destroy()
        # These objects otherwise survive in widget/callback cycles and can be
        # finalized by another thread when the helper is reopened in-process.
        self.section_vars.clear()
        self.panes.sash_image = None
        self.settings_dialog = None
        self.popup = None

if __name__ == '__main__':
    Overlay().root.mainloop()
