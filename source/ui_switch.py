"""Small Tk switch, bound to the same BooleanVar used by saved settings."""
import tkinter as tk
from ui_theme import PANEL, GOLD, MUTED, BG


class Switch(tk.Canvas):
    def __init__(self, parent, variable):
        super().__init__(parent, width=42, height=24, bg=parent.cget('bg'),
                         highlightthickness=0, borderwidth=0, cursor='hand2', takefocus=True)
        self.variable = variable
        self.token = variable.trace_add('write', self.draw)
        self.bind('<Button-1>', lambda _: self.invoke())
        self.bind('<space>', lambda _: self.invoke())
        self.bind('<FocusIn>', self.draw)
        self.bind('<FocusOut>', self.draw)
        self.bind('<Destroy>', self.cleanup)
        self.draw()

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if 'state' in kwargs and hasattr(self, 'variable'):
            self.draw()
        return result

    config = configure

    def draw(self, *_):
        self.delete('all')
        on = bool(self.variable.get())
        color = '#4a5056' if self.cget('state') == 'disabled' else GOLD if on else '#525a62'
        self.create_line(12, 12, 30, 12, fill=color, width=20, capstyle='round')
        x = 30 if on else 12
        self.create_oval(x-7, 5, x+7, 19, fill=BG if on else '#deded9', outline='')
        if self.focus_get() is self:
            self.create_rectangle(1, 1, 40, 22, outline=MUTED)

    def invoke(self):
        if self.cget('state') != 'disabled':
            self.variable.set(not self.variable.get())
        return 'break'

    def cleanup(self, event):
        if event.widget is self and self.token:
            self.variable.trace_remove('write', self.token)
            self.token = None
            self.variable = None
