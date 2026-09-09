"""Project links and nonblocking update controls for the startup window."""
import os
from pathlib import Path
import time
import tkinter as tk
import webbrowser

from app_update import HOME, UpdateWorker, load_links


class UpdatePanel:
    def __init__(self, host, parent, version, directory):
        self.host, self.version = host, version
        self.links = load_links()
        self.worker = UpdateWorker(version, Path(directory) / 'downloads')
        self.last_snapshot, self.announced = None, None
        self.closed = False
        self.frame = tk.Frame(parent, bg='#24292f')
        self.frame.pack(fill='x', pady=(0, 16))
        host.label(self.frame, '项目与更新', bold=True).pack(anchor='w', padx=14, pady=(10, 4))
        host.label(self.frame, '本助手完全免费，下载和使用均不收费。', color='#86c6b5', size=9).pack(anchor='w', padx=14, pady=(0, 4))
        links = tk.Frame(self.frame, bg='#24292f')
        links.pack(fill='x', padx=8)
        host.button(links, '蓝奏云下载 ↗', lambda: self.open_link('lanzou_download_url'), primary=True).pack(side='left', padx=(0, 8))
        host.button(links, 'GitHub 项目 ↗', lambda: self.open_link('project_home_url')).pack(side='left')
        self.password_button = host.button(links, '复制密码 ' + self.links['lanzou_password'], self.copy_password)
        self.password_button.pack(side='right')
        self.status = host.label(self.frame, '当前版本 v' + version + ' · 启动后自动检查更新',
                                 color='#a4b6c7', size=9, wraplength=552)
        self.status.pack(fill='x', padx=14, pady=(7, 4))
        actions = tk.Frame(self.frame, bg='#24292f')
        actions.pack(fill='x', padx=8, pady=(0, 8))
        self.check_button = host.button(actions, '检查更新', self.worker.check)
        self.check_button.pack(side='left')
        self.download_button = host.button(actions, '下载新版', self.download, primary=True)
        self.download_button.pack(side='right')
        self.download_button.configure(state='disabled')
        self.banner = tk.Button(host.overlay.root, bg='#e0bc70', fg='#111a24', relief='flat',
                                cursor='hand2', command=self.show, font=('Microsoft YaHei UI', 10), pady=5)
        self.started = time.monotonic()
        self.job = host.overlay.root.after(200, self.poll)
        self.frame.bind('<Destroy>', self.destroyed)

    def open_link(self, key):
        if key == 'lanzou_download_url':
            self.copy_password()
        webbrowser.open(self.links[key])

    def copy_password(self):
        self.frame.clipboard_clear()
        self.frame.clipboard_append(self.links['lanzou_password'])
        self.password_button.configure(text='已复制 ' + self.links['lanzou_password'])

    def show(self):
        self.banner.pack_forget()
        main = getattr(self.host.overlay, 'main_window', None)
        (main or self.host).show_project()

    def download(self):
        snapshot = self.worker.snapshot
        if snapshot['state'] == 'downloaded':
            os.startfile(str(Path(snapshot['path']).parent))
        elif self.worker.release and (self.worker.release.get('asset') or {}).get('sha256'):
            self.worker.download()
        else:
            webbrowser.open((self.worker.release or {}).get('release_url', HOME + '/releases'))

    def poll(self):
        if self.closed:
            return
        now = time.monotonic()
        if now-self.started >= 2 and (not self.worker.last_check or now-self.worker.last_check >= 6*3600):
            self.worker.check()
        snapshot = self.worker.snapshot
        if snapshot is not self.last_snapshot:
            self.last_snapshot = snapshot
            state = snapshot['state']
            self.check_button.configure(state='disabled' if state in ('checking', 'downloading') else 'normal')
            self.download_button.configure(state='disabled', text='下载新版')
            message = {
                'idle': '当前版本 v' + self.version + ' · 启动后自动检查更新',
                'checking': '正在检查更新…',
                'unpublished': '当前版本 v' + self.version + ' · 暂无公开发行包',
                'current': '当前版本 v' + self.version + ' · 无需更新',
                'pending': 'v' + snapshot.get('version', '') + ' 已发布，完整安装包待上传。',
                'available': '发现新版本 v' + snapshot.get('version', '') + '，点击即可下载完整包。',
                'downloading': '正在下载新版：' + str(snapshot.get('progress', 0)) + '%',
                'downloaded': '下载并校验完成。打开目录，解压后运行新版；原有设置会保留。',
            }.get(state, snapshot.get('message', '暂时无法检查，请到蓝奏云查看'))
            self.status.configure(text=message)
            if state in ('available', 'pending', 'download_error'):
                verified = bool((self.worker.release or {}).get('asset') and self.worker.release['asset'].get('sha256'))
                self.download_button.configure(state='normal', text='下载新版' if verified else '前往下载页 ↗')
            elif state == 'downloaded':
                self.download_button.configure(state='normal', text='打开下载目录')
            if hasattr(self.host.overlay, 'panes') and state == 'available' and self.announced != snapshot['version']:
                self.announced = snapshot['version']
                self.banner.configure(text='发现新版 v' + snapshot['version'] + ' · 点击下载')
                self.banner.pack(fill='x', padx=10, pady=(0, 4), before=self.host.overlay.panes)
            if hasattr(self.host.overlay, 'panes') and state == 'downloaded':
                self.banner.configure(text='新版已下载 · 点击查看')
                self.banner.pack(fill='x', padx=10, pady=(0, 4), before=self.host.overlay.panes)
        self.job = self.host.overlay.root.after(250, self.poll)

    def destroyed(self, event):
        if event.widget is self.frame:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.worker.close()
        if self.job:
            try:
                self.host.overlay.root.after_cancel(self.job)
            except tk.TclError:
                pass
