"""Borderless navigation with the small page API used by settings."""
import tkinter as tk
from ui_theme import BG, SIDEBAR, PANEL, FG, MUTED, GOLD, LINE


class PageStack(tk.Frame):
    def __init__(self, parent, sidebar=False, on_select=None):
        super().__init__(parent, bg=BG, borderwidth=0)
        self.sidebar, self.on_select = sidebar, on_select
        self.pages, self.buttons, self.titles = {}, {}, {}
        self.current = None
        self.nav = tk.Frame(self, bg=SIDEBAR if sidebar else BG)
        if sidebar:
            self.nav.configure(width=156)
            self.nav.pack(side='left', fill='y', padx=(0, 24))
            self.nav.pack_propagate(False)
            tk.Label(self.nav, text='功能', bg=SIDEBAR, fg=MUTED, anchor='w',
                     font=('Microsoft YaHei UI', 9)).pack(fill='x', padx=16, pady=(12, 10))
        else:
            self.nav.pack(fill='x', pady=(0, 12))
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill='both', expand=True)

    def add(self, page, text, hidden=False, separator=False):
        key = str(page)
        self.pages[key], self.titles[key] = page, text
        if not hidden:
            if separator:
                tk.Frame(self.nav, bg=LINE, height=1).pack(fill='x', padx=16, pady=16)
            b = tk.Button(self.nav, text=text, command=lambda: self.select(key),
                          bg=SIDEBAR if self.sidebar else BG, fg=MUTED,
                          activebackground=PANEL, activeforeground=FG, relief='flat',
                          borderwidth=0, highlightthickness=0, padx=16, pady=10,
                          anchor='w' if self.sidebar else 'center', cursor='hand2')
            b.pack(fill='x' if self.sidebar else None,
                   side='top' if self.sidebar else 'left', padx=6, pady=2)
            self.buttons[key] = b
        if self.current is None:
            self.select(key)

    def select(self, page=None):
        if page is None:
            return self.current or ''
        key = str(page)
        if key not in self.pages:
            raise tk.TclError('Unknown page ' + key)
        if self.current:
            self.pages[self.current].pack_forget()
        self.current = key
        self.pages[key].pack(in_=self.content, fill='both', expand=True)
        for name, b in self.buttons.items():
            selected = name == key
            b.configure(bg=PANEL if selected else SIDEBAR if self.sidebar else BG,
                        fg=GOLD if selected else MUTED)
        if self.on_select:
            self.on_select(key)
        return key

    def tabs(self):
        return tuple(self.pages)

    def tab(self, page, option):
        if option == 'text':
            return self.titles[str(page)]
        raise tk.TclError('Unsupported page option')
