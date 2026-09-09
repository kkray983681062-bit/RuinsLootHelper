"""Backpack positioning page in the existing Tk settings dialog."""
import tkinter as tk
from tkinter import messagebox
from overlay_markers import fresh
from feature_policy import slot_rect


class FeatureSettings:
    def __init__(self, dialog):
        self.dialog = dialog
        self.overlay = dialog.overlay
        self.settings = dialog.settings
        self.marker_tab = tk.Frame(dialog.features, bg='#111a24')
        dialog.features.add(self.marker_tab, text='背包定位')
        markers = self.settings.get('backpack_markers', {})
        self.marker_enabled = tk.BooleanVar(value=markers.get('enabled', False))
        self.automatic = tk.BooleanVar(value=markers.get('automatic', True))
        self.marker_sections = {key: tk.BooleanVar(value=markers.get('sections', {}).get(key, True))
                                for key in ('numeric', 'legendary', 'lower')}
        self.grid = markers.get('grid')
        self.marker_page()

    def label(self, parent, text, **kwargs):
        label = self.dialog.label(parent, text, anchor='w', justify='left', **kwargs)
        label.pack(fill='x', padx=16, pady=6)
        return label

    def marker_page(self):
        d = self.dialog
        d.check(self.marker_tab, '在背包里圈出符合筛选的装备', self.marker_enabled).pack(anchor='w', padx=12, pady=(20, 12))
        d.check(self.marker_tab, '自动定位格子（需要连接原生组件）', self.automatic).pack(anchor='w', padx=12, pady=(0, 10))
        row = tk.Frame(self.marker_tab, bg='#111a24')
        row.pack(fill='x', padx=16, pady=8)
        for key, title in (('numeric', '词条'), ('legendary', '上技能'), ('lower', '下技能')):
            d.check(row, title, self.marker_sections[key]).pack(side='left', padx=(0, 24))
        self.label(self.marker_tab, '沿用“筛选设置”的条件，标记只显示在打开的主背包中。\n装备整理、换格后标记跟着更新；锁定、回收、移出后清除。')
        d.button(self.marker_tab, '校准背包位置', self.calibrate).pack(anchor='w', padx=16, pady=12)
        self.grid_label = self.label(self.marker_tab, '已保存手动校准位置' if self.grid else '自动模式读取当前角色的 60 个背包格子；手动模式可框选 10 列 × 6 行。', wraplength=620)
        self.label(self.marker_tab, '自动模式下，拖动背包面板后会重新读取格子位置。\n连接中断时暂停画圈，避免使用旧坐标。\n手动模式下，移动背包面板后需要重新校准。圈圈不挡鼠标。', wraplength=620)

    def calibrate(self):
        status = self.overlay.read_file('feature-status.json', {}) or {}
        if not fresh(status.get('heartbeat_utc')) or not status.get('ui', {}).get('valid') or not status.get('ui', {}).get('backpack_open'):
            messagebox.showinfo('校准背包', '请先在游戏里打开背包，再点击“校准背包位置”。', parent=self.dialog.window)
            return
        from overlay_markers import GridCalibration
        def finished(grid):
            if grid:
                self.grid = grid
                self.marker_enabled.set(True)
                self.grid_label.configure(text='位置已校准，点击“应用”保存并开启标记。')
        GridCalibration(self.overlay, self.dialog.window, finished)

    def values(self):
        if self.marker_enabled.get() and not self.automatic.get() and slot_rect(0, self.grid, 1000, 1000) is None:
            raise ValueError('请先校准背包位置。')
        return {'backpack_markers': {'enabled': self.marker_enabled.get(), 'grid': self.grid,
                                    'automatic': self.automatic.get(),
                                    'sections': {key: var.get() for key, var in self.marker_sections.items()}}}
