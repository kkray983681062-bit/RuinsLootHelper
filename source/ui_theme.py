"""Shared desktop styling and monitor-aware placement."""
import ctypes as c
from ctypes import wintypes as w
import tkinter as tk
from tkinter import ttk

BG = '#191d21'
SIDEBAR = '#15181c'
PANEL = '#24292f'
HOVER = '#343b43'
FG = '#ede9df'
MUTED = '#a2a8ae'
GOLD = '#dab66b'
GREEN = '#8cbbab'
LINE = '#3c4248'


def setup(root):
    root.option_add('*Font', ('Microsoft YaHei UI', 10))
    style = ttk.Style(root)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    style.configure('TCombobox', fieldbackground=PANEL, background=PANEL,
                    foreground=FG, arrowcolor=MUTED, bordercolor=LINE, padding=4)
    style.map('TCombobox', fieldbackground=[('readonly', PANEL)],
              foreground=[('readonly', FG)], selectbackground=[('readonly', PANEL)],
              selectforeground=[('readonly', FG)])


def label(parent, text, color=FG, size=10, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color, anchor='w',
                    font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kwargs)


def button(parent, text, command, primary=False):
    return tk.Button(parent, text=text, command=command, bg=GOLD if primary else PANEL,
                     fg=BG if primary else FG, activebackground='#ebca83' if primary else HOVER,
                     activeforeground=BG if primary else FG, relief='flat', borderwidth=0,
                     highlightthickness=0, cursor='hand2', padx=14, pady=8)


def dark_titlebar(window):
    try:
        u = c.windll.user32
        u.GetAncestor.argtypes = [w.HWND, w.UINT]
        u.GetAncestor.restype = w.HWND
        hwnd = u.GetAncestor(window.winfo_id(), 2)
        dwm = c.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]
        for attr, number in ((20, 1), (35, 0x211d19), (36, 0xdfe9ed)):
            value = w.DWORD(number)
            dwm.DwmSetWindowAttribute(hwnd, attr, c.byref(value), c.sizeof(value))
    except (OSError, AttributeError):
        pass


def center_window(window, anchor):
    """Use physical work-area coordinates, including negative monitor origins."""
    class Info(c.Structure):
        _fields_ = [('cbSize', w.DWORD), ('rcMonitor', w.RECT), ('rcWork', w.RECT), ('dwFlags', w.DWORD)]
    u = c.windll.user32
    u.GetAncestor.argtypes = [w.HWND, w.UINT]
    u.GetAncestor.restype = w.HWND
    u.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    u.MonitorFromWindow.restype = w.HANDLE
    u.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(Info)]
    u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
    window.update_idletasks()
    hwnd = u.GetAncestor(window.winfo_id(), 2)
    anchor_hwnd = u.GetAncestor(anchor.winfo_id(), 2)
    info = Info(); info.cbSize = c.sizeof(info)
    if not u.GetMonitorInfoW(u.MonitorFromWindow(anchor_hwnd, 2), c.byref(info)):
        return
    outer, client = w.RECT(), w.RECT()
    if not u.GetWindowRect(hwnd, c.byref(outer)) or not u.GetClientRect(hwnd, c.byref(client)):
        return
    work = info.rcWork
    width = min(outer.right - outer.left, work.right - work.left - 24)
    height = min(outer.bottom - outer.top, work.bottom - work.top - 24)
    frame_w = outer.right - outer.left - client.right
    frame_h = outer.bottom - outer.top - client.bottom
    old_w, old_h = window.minsize()
    window.minsize(max(1, min(old_w, width-frame_w)), max(1, min(old_h, height-frame_h)))
    u.SetWindowPos(hwnd, None, work.left+(work.right-work.left-width)//2,
                   work.top+(work.bottom-work.top-height)//2, width, height, 0x0014)
    dark_titlebar(window)
