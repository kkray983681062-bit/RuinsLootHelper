"""One drawing surface for resizable HUD sections and their scrollbars."""
import ctypes as c
from ctypes import wintypes as w
import tkinter as tk
from tkinter import font as tkfont
from overlay_canvas_text import COLORS, SectionView

_user = c.WinDLL('user32', use_last_error=True)
_user.GetCursorPos.argtypes = [c.POINTER(w.POINT)]
_user.GetCursorPos.restype = w.BOOL
_user.GetAsyncKeyState.argtypes = [c.c_int]
_user.GetAsyncKeyState.restype = c.c_short
_user.GetSystemMetrics.argtypes = [c.c_int]
_user.WindowFromPoint.argtypes = [w.POINT]
_user.WindowFromPoint.restype = w.HWND


def window_at(x, y):
    return int(_user.WindowFromPoint(w.POINT(int(x), int(y))) or 0)


def read_pointer():
    point = w.POINT()
    if not _user.GetCursorPos(c.byref(point)):
        return 0, 0, False, 0
    button = 2 if _user.GetSystemMetrics(23) else 1
    return point.x, point.y, bool(_user.GetAsyncKeyState(button) & 0x8000), window_at(point.x, point.y)


class SectionPanes(tk.Canvas):
    line_width = 1
    hit_width = 9
    minimum_height = 64

    def __init__(self, parent, layouts=None, on_layout=None, **kwargs):
        super().__init__(parent, bg='#111a24', borderwidth=0, highlightthickness=0, takefocus=False, **kwargs)
        self.sections, self.layouts = {}, dict(layouts or {})
        self.visible_keys, self.positions = (), []
        self.on_layout = on_layout
        self.dragging, self.scroll_drag = None, None
        self.last_drag_pixels, self.drag_events = 0, []
        self.layout_job, self.paint_job, self.layout_size = None, None, None
        self.sash_image = None
        self.items, self.paint_count = {}, 0
        self.font_size = 12
        self.transparent = False
        self.fonts = {
            'normal': tkfont.Font(self, family='Microsoft YaHei UI', size=12),
            'hit': tkfont.Font(self, family='Microsoft YaHei UI', size=12, weight='bold'),
            'title': tkfont.Font(self, family='Microsoft YaHei UI', size=12, weight='bold')}
        self.header_height = self.fonts['title'].metrics('linespace') + 14
        self.bind('<Configure>', self.schedule_layout)
        self.bind('<ButtonPress-1>', self.press)
        self.bind('<B1-Motion>', self.motion)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Motion>', self.hover)
        self.mouse_was_down = read_pointer()[2]
        self.mouse_job = self.after(16, self.track_pointer)

    def register(self, key, title):
        view = SectionView(self, key, title)
        self.sections[key] = view
        return view

    def panes(self):
        return self.visible_keys

    def set_font(self, size):
        if size == self.font_size:
            return
        self.font_size = size
        self.fonts['normal'].configure(size=size)
        self.fonts['hit'].configure(size=size)
        self.request_paint()

    def set_transparent(self, enabled):
        if self.transparent != bool(enabled):
            self.transparent = bool(enabled)
            self.request_paint()

    def set_visible(self, keys):
        keys = tuple(keys)
        if keys == self.visible_keys:
            return
        self.release()
        self.remember()
        self.visible_keys = keys
        self.positions = [0] * max(0, len(keys) - 1)
        self.drag_events = [dict(press=0, move=0, release=0, pointer_press=0) for _ in self.positions]
        self.layout_size = None
        self.schedule_layout()

    def schedule_layout(self, event=None):
        if event is not None and (event.width, event.height) == self.layout_size:
            return
        if self.layout_job:
            self.after_cancel(self.layout_job)
        self.layout_job = self.after_idle(self.restore)

    def _minimum(self):
        count = max(1, len(self.visible_keys))
        return min(self.minimum_height, max(1, (self.winfo_height() - self.hit_width * (count - 1)) // count))

    def restore(self):
        self.layout_job = None
        self.layout_size = (self.winfo_width(), self.winfo_height())
        count, height = len(self.visible_keys), self.winfo_height()
        if count > 1 and self.dragging is None:
            ratios = self.layouts.get('|'.join(self.visible_keys))
            if not isinstance(ratios, list) or len(ratios) != count - 1:
                weights = [1.5 if key == 'numeric' else 1 for key in self.visible_keys]
                ratios = [sum(weights[:i + 1]) / sum(weights) for i in range(count - 1)]
            minimum, previous = self._minimum(), -self.hit_width
            for i, ratio in enumerate(ratios):
                low = previous + self.hit_width + minimum
                high = height - (count - i - 1) * (minimum + self.hit_width)
                previous = max(low, min(high, round(height * float(ratio))))
                self.positions[i] = previous
        self.layout_sections()

    def layout_sections(self):
        top = 0
        for i, key in enumerate(self.visible_keys):
            bottom = self.positions[i] if i < len(self.positions) else self.winfo_height()
            view = self.sections[key]
            view.top, view.height = top, max(1, bottom - top)
            top = bottom + self.hit_width
        self.request_paint()

    def sashpos(self, index, value=None):
        if value is not None:
            self.sash_place(index, 0, value)
        return self.positions[index]

    def sash_coord(self, index):
        return 0, self.positions[index]

    def sash_place(self, index, x, y):
        minimum = self._minimum()
        low = (self.positions[index - 1] + self.hit_width if index else 0) + minimum
        high = (self.positions[index + 1] if index + 1 < len(self.positions) else self.winfo_height()) - self.hit_width - minimum
        value = max(low, min(high, int(y)))
        if value != self.positions[index]:
            self.positions[index] = value
            self.layout_sections()

    def identify(self, x, y):
        if 0 <= x < self.winfo_width():
            for i, pos in enumerate(self.positions):
                if pos <= y < pos + self.hit_width:
                    return i
        return ''

    def section_at(self, x, y):
        if 0 <= x < self.winfo_width():
            for key in self.visible_keys:
                view = self.sections[key]
                if view.body_top <= y < view.top + view.height:
                    return view

    def pointer_press(self, x, y):
        index = self.identify(x, y)
        if index != '':
            self.start_drag(index, self.winfo_rooty() + y)
            return
        view = self.section_at(x, y)
        if view and view.shown and x >= self.winfo_width() - 16:
            thumb_y, thumb_h, _ = view.thumb()
            if thumb_y <= y <= thumb_y + thumb_h:
                self.scroll_drag = (view.key, y - thumb_y)
            else:
                view.scroll((-1 if y < thumb_y else 1) * view.viewport * .9)

    def control_hit(self, x, y, target):
        if target == self.winfo_id():
            return True
        if self.transparent:
            index = self.identify(x - self.winfo_rootx(), y - self.winfo_rooty())
            if index != '':
                # Color-key holes hit the game. Check the actual painted line
                # for occlusion before treating its nine-pixel gap as a handle.
                center = self.winfo_rooty() + self.positions[index] + self.hit_width // 2
                return window_at(x, center) == self.winfo_id()
        return False

    def press(self, event):
        # A late Tk event must not begin a second drag or page-scroll twice.
        if not self.mouse_was_down:
            x, y, down, target = read_pointer()
            if down and self.control_hit(x, y, target):
                self.pointer_press(x - self.winfo_rootx(), y - self.winfo_rooty())
                self.mouse_was_down = True
        return 'break'

    def start_drag(self, index, root_y):
        if self.dragging is not None:
            return
        self.dragging = (index, root_y, self.positions[index])
        self.last_drag_pixels = 0
        self.drag_events[index]['press'] += 1

    def track_pointer(self):
        self.mouse_job = None
        try:
            x, y, down, target = read_pointer()
            if down and not self.mouse_was_down and self.dragging is None and self.scroll_drag is None and self.control_hit(x, y, target):
                self.pointer_press(x - self.winfo_rootx(), y - self.winfo_rooty())
                if self.dragging is not None:
                    self.drag_events[self.dragging[0]]['pointer_press'] += 1
            if self.dragging is not None:
                old = self.last_drag_pixels
                self.drag_handle(y)
                if old != self.last_drag_pixels:
                    self.drag_events[self.dragging[0]]['move'] += 1
            if self.scroll_drag is not None:
                self.scroll_handle(y)
            if not down:
                self.release()
            self.mouse_was_down = down
        finally:
            if self.winfo_exists():
                self.mouse_job = self.after(16, self.track_pointer)

    def motion(self, event):
        # Only the physical pointer frame loop moves a divider/scroll thumb.
        return 'break'

    def hover(self, event):
        self.configure(cursor='sb_v_double_arrow' if self.identify(event.x, event.y) != '' else 'arrow')

    def drag_handle(self, root_y):
        index, start_y, original = self.dragging
        self.sash_place(index, 0, original + root_y - start_y)
        self.last_drag_pixels = self.positions[index] - original

    def scroll_handle(self, root_y):
        key, grab = self.scroll_drag
        view = self.sections[key]
        _, _, travel = view.thumb()
        y = root_y - self.winfo_rooty()
        fraction = max(0., min(1., (y - view.body_top - grab) / max(1, travel)))
        view.offset = fraction * max(0, view.content_height - view.viewport)
        self.request_paint()

    def wheel(self, event):
        view = self.section_at(event.x, event.y)
        if view:
            view.wheel_delta += event.delta
            steps = int(view.wheel_delta / 120)
            if steps:
                view.wheel_delta -= steps * 120
                view.scroll(-steps * 3 * self.fonts['normal'].metrics('linespace'))
        return 'break'

    def release(self, event=None):
        if event is not None:
            y = read_pointer()[1]
            if self.dragging is not None:
                self.drag_handle(y)
            if self.scroll_drag is not None:
                self.scroll_handle(y)
            self.mouse_was_down = False
        self.scroll_drag = None
        if self.dragging is not None:
            index, _, original = self.dragging
            self.last_drag_pixels = self.positions[index] - original
            self.drag_events[index]['release'] += 1
            self.dragging = None
            self.remember()
        return 'break' if event is not None else None

    def remember(self):
        if len(self.visible_keys) < 2 or self.winfo_height() < 100:
            return
        self.layouts['|'.join(self.visible_keys)] = [p / self.winfo_height() for p in self.positions]
        if self.on_layout:
            self.on_layout(dict(self.layouts))

    def request_paint(self):
        if self.paint_job is None:
            self.paint_job = self.after_idle(self.paint)

    def draw_item(self, key, kind, coords, tag, **options):
        self.used_items.add(key)
        item = self.items.get(key)
        if item is None:
            ident = getattr(self, 'create_' + kind)(*coords, tags=(tag,), **options)
            self.items[key] = (ident, tuple(coords), options, True)
            return
        ident, old_coords, old_options, shown = item
        if tuple(coords) != old_coords:
            self.coords(ident, *coords)
        if options != old_options or not shown:
            self.itemconfigure(ident, state='normal', **options)
        self.items[key] = (ident, tuple(coords), options, True)

    def paint(self):
        self.paint_job = None
        self.used_items = set()
        width = self.winfo_width()
        body_color = '#111a24' if self.transparent else '#121b25'
        header_color = '#111a24' if self.transparent else '#111a25'
        for key in self.visible_keys:
            view = self.sections[key]
            view.layout()
            view.clamp()
            self.draw_item((key, 'bg'), 'rectangle', (0, view.top, width, view.top + view.height), key + '-bg', fill=body_color, outline='')
            for index, (y, text, tag, _) in view.visible_rows():
                self.draw_item((key, 'row', index), 'text', (8, view.body_top + y - view.offset), key + '-rows',
                               anchor='nw', text=text, fill=COLORS[tag], font=self.fonts['hit' if tag == 'hit' else 'normal'])
            self.draw_item((key, 'header'), 'rectangle', (0, view.top, width, view.body_top), key + '-header', fill=header_color, outline='')
            self.draw_item((key, 'title'), 'text', (8, view.top + 7), key + '-title', anchor='nw', text=view.title, fill='#ffde83', font=self.fonts['title'])
            if view.shown:
                y, height, _ = view.thumb()
                self.draw_item((key, 'track'), 'rectangle', (width - 12, view.body_top, width - 4, view.body_top + view.viewport), key + '-scroll', fill='#1c2b36', outline='')
                self.draw_item((key, 'thumb'), 'rectangle', (width - 12, y, width - 4, y + height), key + '-scroll', fill='#728e9e', outline='')
            # Header masks a partial first line; the next section masks the last.
            for layer in ('bg', 'rows', 'header', 'title', 'scroll'):
                self.tag_raise(key + '-' + layer)
        for i, pos in enumerate(self.positions):
            self.draw_item(('sash-bg', i), 'rectangle', (0, pos, width, pos + self.hit_width), 'sashes', fill=header_color, outline='')
            self.draw_item(('sash', i), 'line', (0, pos + self.hit_width // 2, width, pos + self.hit_width // 2), 'sashes', fill='#90a3b0', width=1)
        self.tag_raise('sashes')
        for key in self.items.keys() - self.used_items:
            ident, coords, options, shown = self.items[key]
            if shown:
                self.itemconfigure(ident, state='hidden')
                self.items[key] = ident, coords, options, False
        self.paint_count += 1

    def destroy(self):
        for name in ('layout_job', 'paint_job', 'mouse_job'):
            if getattr(self, name, None):
                self.after_cancel(getattr(self, name))
                setattr(self, name, None)
        self.items.clear()
        self.sections.clear()
        self.fonts.clear()
        super().destroy()
