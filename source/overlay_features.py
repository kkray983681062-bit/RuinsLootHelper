"""Backpack positioning page in the existing Tk settings dialog."""
import tkinter as tk
from tkinter import messagebox
from overlay_markers import fresh
from feature_policy import slot_rect
from ui_theme import BG, label


class FeatureSettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.overlay = dialog.overlay
        self.settings = dialog.settings
        self.marker_tab = tk.Frame(dialog.features, bg=BG)
        dialog.features.add(self.marker_tab, text='背包定位')
        markers = self.settings.get('backpack_markers', {})
        self.marker_enabled = tk.BooleanVar(value=markers.get('enabled', False))
        self.automatic = tk.BooleanVar(value=markers.get('automatic', True))
        self.marker_sections = {key: tk.BooleanVar(value=markers.get('sections', {}).get(key, True))
                                for key in ('numeric', 'legendary', 'lower')}
        self.grid = markers.get('grid')
        label(self.marker_tab, '背包定位', size=20, bold=True).pack(anchor='w', pady=(6, 8))
        self.marker_page()

    def label(self, parent, text, **kwargs):
        label = self.dialog.label(parent, text, anchor='w', justify='left', **kwargs)
        label.pack(fill='x', padx=16, pady=6)
        return label

    def marker_page(self):
        d = self.dialog
        d.check(self.marker_tab, '在背包里圈出符合筛选的装备', self.marker_enabled).pack(anchor='w', padx=12, pady=(20, 12))
        d.check(self.marker_tab, '自动定位格子（识别顶部的锁，跟随移动和缩放）', self.automatic).pack(anchor='w', padx=12, pady=(0, 10))
        row = tk.Frame(self.marker_tab, bg=BG)
        row.pack(fill='x', padx=16, pady=8)
        for key, title in (('numeric', '词条'), ('legendary', '上技能'), ('lower', '下技能')):
            d.check(row, title, self.marker_sections[key]).pack(side='left', padx=(0, 24))
        self.label(self.marker_tab, '沿用“装备筛选”的条件，标记只显示在打开的主背包中。\n装备整理、换格后标记跟着更新；锁定、回收、移出后清除。')
        d.button(self.marker_tab, '识别失败时：辅助校准', self.calibrate).pack(anchor='w', padx=16, pady=12)
        self.grid_label = self.label(self.marker_tab, '首次打开背包会自动识别，无需先手动校准。', wraplength=620)
        self.label(self.marker_tab, '自动识别顶部的锁，并核对下方 60 格。\n拖动背包、改变分辨率或界面缩放后，自动重扫位置和格子大小。\n识别失败时，点“辅助校准”再点一下顶部的锁。\n关闭自动定位时，辅助校准可手动框选背包。圈圈不挡鼠标。', wraplength=620)

    def calibrate(self):
        status = self.overlay.read_file('feature-status.json', {}) or {}
        if not fresh(status.get('heartbeat_utc')) or not status.get('ui', {}).get('valid') or not status.get('ui', {}).get('backpack_open'):
            messagebox.showinfo('校准背包', '请先在游戏里打开背包，再点击“识别失败时：辅助校准”。', parent=self.dialog.window)
            return
        from overlay_markers import GridCalibration, LockCalibration
        if self.automatic.get():
            def locked(point):
                if point:
                    if self.overlay.markers.anchor is None:
                        from backpack_anchor import AnchorWorker
                        self.overlay.markers.anchor = AnchorWorker()
                    self.overlay.markers.anchor.set_hint(point)
                    self.grid_label.configure(text='已指定顶部锁的位置，切回游戏后会自动核对格子。')
            LockCalibration(self.overlay, self.dialog.window, locked)
            return
        def finished(grid):
            if grid:
                self.grid = grid
                self.marker_enabled.set(True)
                self.grid_label.configure(text='位置已校准，点击“保存设置”保存并开启标记。')
        GridCalibration(self.overlay, self.dialog.window, finished)

    def values(self):
        if self.marker_enabled.get() and not self.automatic.get() and slot_rect(0, self.grid, 1000, 1000) is None:
            raise ValueError('请先校准背包位置。')
        return {'backpack_markers': {'enabled': self.marker_enabled.get(), 'grid': self.grid,
                                    'automatic': self.automatic.get(),
                                    'sections': {key: var.get() for key, var in self.marker_sections.items()}}}
