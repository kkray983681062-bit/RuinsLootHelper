"""Non-activating Win32/GDI ring layer; no Tk window mapping or input capture."""
import ctypes as c
from ctypes import wintypes as w
import re

u, g, k = c.WinDLL('user32'), c.WinDLL('gdi32'), c.WinDLL('kernel32')
LRESULT = c.c_ssize_t
PROC = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WNDCLASS(c.Structure):
    _fields_ = [('style', w.UINT), ('proc', PROC), ('cls_extra', c.c_int), ('wnd_extra', c.c_int),
        ('instance', w.HINSTANCE), ('icon', w.HICON), ('cursor', w.HANDLE), ('background', w.HBRUSH),
        ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]


class PAINT(c.Structure):
    _fields_ = [('dc', w.HDC), ('erase', w.BOOL), ('rect', w.RECT), ('restore', w.BOOL),
               ('inc_update', w.BOOL), ('reserved', c.c_byte * 32)]


k.GetModuleHandleW.argtypes = [w.LPCWSTR]
k.GetModuleHandleW.restype = w.HMODULE
u.RegisterClassW.argtypes = [c.POINTER(WNDCLASS)]
u.RegisterClassW.restype = w.ATOM
u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int,
                             w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
u.CreateWindowExW.restype = w.HWND
u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.DefWindowProcW.restype = LRESULT
u.BeginPaint.argtypes = [w.HWND, c.POINTER(PAINT)]
u.BeginPaint.restype = w.HDC
u.EndPaint.argtypes = [w.HWND, c.POINTER(PAINT)]
u.FillRect.argtypes = [w.HDC, c.POINTER(w.RECT), w.HBRUSH]
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.SetLayeredWindowAttributes.argtypes = [w.HWND, w.DWORD, c.c_ubyte, w.DWORD]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.DestroyWindow.argtypes = [w.HWND]
u.IsWindowVisible.argtypes = [w.HWND]
u.InvalidateRect.argtypes = [w.HWND, c.POINTER(w.RECT), w.BOOL]
u.UpdateWindow.argtypes = [w.HWND]
g.CreateSolidBrush.argtypes = [w.DWORD]
g.CreateSolidBrush.restype = w.HBRUSH
g.CreatePen.argtypes = [c.c_int, c.c_int, w.DWORD]
g.CreatePen.restype = w.HPEN
g.GetStockObject.argtypes = [c.c_int]
g.GetStockObject.restype = w.HGDIOBJ
g.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
g.SelectObject.restype = w.HGDIOBJ
g.DeleteObject.argtypes = [w.HGDIOBJ]
g.Ellipse.argtypes = [w.HDC, c.c_int, c.c_int, c.c_int, c.c_int]
_windows = {}
_registered = False


@PROC
def callback(hwnd, message, wp, lp):
    if message == 0x84:  # WM_NCHITTEST: even the colored rings pass through.
        return -1
    if message == 0x21:  # WM_MOUSEACTIVATE
        return 3
    if message == 0xF:
        paint = PAINT()
        dc = u.BeginPaint(hwnd, c.byref(paint))
        try:
            canvas = _windows.get(int(hwnd))
            if canvas:
                canvas.paint(dc)
        finally:
            u.EndPaint(hwnd, c.byref(paint))
        return 0
    return u.DefWindowProcW(hwnd, message, wp, lp)


class RingCanvas:
    def __init__(self, window):
        self.window, self.shapes, self.sequence = window, {}, 0

    def delete(self, _):
        self.shapes.clear()
        self.refresh()

    def create_oval(self, *box, outline, width):
        self.sequence += 1
        self.shapes[self.sequence] = (tuple(box), outline, width)
        return self.sequence

    def find_all(self):
        return tuple(self.shapes)

    def coords(self, key):
        return list(self.shapes[key][0])

    def winfo_ismapped(self):
        return bool(u.IsWindowVisible(self.window.hwnd))

    def refresh(self):
        u.InvalidateRect(self.window.hwnd, None, False)

    def paint(self, dc):
        rect = w.RECT()
        u.GetClientRect(self.window.hwnd, c.byref(rect))
        brush = g.CreateSolidBrush(0x030201)
        u.FillRect(dc, c.byref(rect), brush)
        g.DeleteObject(brush)
        old_brush = g.SelectObject(dc, g.GetStockObject(5))  # NULL_BRUSH
        for box, color, width in self.shapes.values():
            rgb = int(color[1:], 16)
            colorref = (rgb >> 16) | (rgb & 0xff00) | ((rgb & 0xff) << 16)
            pen = g.CreatePen(0, width, colorref)
            old_pen = g.SelectObject(dc, pen)
            g.Ellipse(dc, *[round(v) for v in box])
            g.SelectObject(dc, old_pen)
            g.DeleteObject(pen)
        g.SelectObject(dc, old_brush)


class MarkerWindow:
    def __init__(self):
        global _registered
        instance = k.GetModuleHandleW(None)
        if not _registered:
            cls = WNDCLASS(0, callback, 0, 0, instance, None, None, None, None, 'RuinsHelperRings')
            if not u.RegisterClassW(c.byref(cls)):
                raise c.WinError()
            _registered = True
        self.hwnd = u.CreateWindowExW(0x80000 | 0x20 | 0x08000000 | 0x80,
            'RuinsHelperRings', '背包装备标记', 0x80000000, 0, 0, 1, 1, None, None, instance, None)
        if not self.hwnd:
            raise c.WinError()
        u.SetLayeredWindowAttributes(self.hwnd, 0x030201, 255, 1)
        self.canvas = RingCanvas(self)
        _windows[int(self.hwnd)] = self.canvas

    def geometry(self, value):
        match = re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', value)
        if match:
            width, height, x, y = map(int, match.groups())
            u.SetWindowPos(self.hwnd, w.HWND(-1), x, y, width, height, 0x10)

    def update_idletasks(self):
        self.canvas.refresh()
        u.UpdateWindow(self.hwnd)

    def state(self):
        return 'normal' if u.IsWindowVisible(self.hwnd) else 'withdrawn'

    def deiconify(self):
        u.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE

    def destroy(self):
        _windows.pop(int(self.hwnd), None)
        u.DestroyWindow(self.hwnd)
