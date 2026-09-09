"""Themed, auto-hiding scrollbar and wheel routing for transparent HUD text."""
from tkinter import ttk


def dark_scrollbars(root):
    style = ttk.Style(root)
    if style.theme_use() != 'clam':
        style.theme_use('clam')
    style.configure('Vertical.TScrollbar', background='#526675', troughcolor='#15212c',
        bordercolor='#15212c', lightcolor='#526675', darkcolor='#526675',
        arrowcolor='#a4b6c7', width=8, gripcount=0, arrowsize=10)
    style.map('Vertical.TScrollbar', background=[('active', '#8aabbd'), ('pressed', '#a5c7d8')])
    style.layout('Loot.Vertical.TScrollbar', [
        ('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
            ('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])


class AutoScrollbar(ttk.Scrollbar):
    def __init__(self, parent, target, **kwargs):
        super().__init__(parent, orient='vertical', command=target.yview,
                         style='Loot.Vertical.TScrollbar', takefocus=False, **kwargs)
        self.target = target
        self.shown = False
        self.delta = 0
        target.configure(yscrollcommand=self.set)
        target.bind('<MouseWheel>', self.wheel)
        self.bind('<MouseWheel>', self.wheel)

    def set(self, first, last):
        needed = self.target.winfo_height() > 1 and float(last) - float(first) < .9999
        if needed != self.shown:
            self.shown = needed
            if needed:
                self.pack(side='right', fill='y', before=self.target)
            else:
                self.pack_forget()
        super().set(first, last)

    def wheel(self, event):
        self.delta += event.delta
        steps = int(self.delta / 120)
        if steps:
            self.delta -= steps * 120
            self.target.yview_scroll(-steps * 3, 'units')
        return 'break'
