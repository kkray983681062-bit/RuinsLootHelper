"""Standalone Windows entry point: locate Steam, discover a fresh session, show HUD."""
import argparse
import ctypes
import json
import msvcrt
import multiprocessing
import os
from pathlib import Path
import sys
import time
import traceback

from game_install import discover, resolve_game
from release_runtime import write_json
from worker_process import ProcessBackend

VERSION = '0.3.5'
TITLE = '破晓装备助手'
DATA_NAME = 'RuinsLootHelper'


def user_directory():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / DATA_NAME


def load_json(path, default=None):
    for attempt in range(4):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError:
            if attempt < 3:
                time.sleep(.01)
        except (OSError, ValueError):
            return default
    return default


def prepare_settings(directory):
    directory.mkdir(parents=True, exist_ok=True)
    from gear_view import configured_rules
    defaults = load_json(Path(__file__).with_name('release-defaults.json'), {})
    settings = {
        'columns': 10, 'include_locked': False, 'include_storage': False,
        'width': 420, 'height': 700, 'bottom_margin': 160, 'font_size': 12,
        'opacity': 1.0, 'transparent_background': True,
        'legendary_enabled': True, 'legendary_pairs': ['9:1', '9:4', '9:6', '9:9'],
        'lower_enabled': True,
        'section_visibility': {'numeric': True, 'legendary': True, 'lower': True},
        'backpack_markers': {'enabled': False, 'grid': None, 'sections': {'numeric': True, 'legendary': True, 'lower': True}},
    }
    settings.update(defaults.get('settings', {}))
    # Never ship somebody else's desktop position or screen calibration.
    settings.pop('x', None)
    settings.pop('y', None)
    settings.pop('auto_pickup', None)
    settings['backpack_markers']['enabled'] = False
    settings['backpack_markers']['grid'] = None
    for name, default in (('loot-overlay-settings.json', settings),
                          ('loot-filter-rules.json', configured_rules(defaults.get('rules')))):
        if not (directory / name).exists():
            write_json(directory, name, default)
    # Migrate old application preferences if an earlier build wrote pickup data.
    saved = load_json(directory / 'loot-overlay-settings.json', {})
    if 'auto_pickup' in saved:
        saved.pop('auto_pickup')
        write_json(directory, 'loot-overlay-settings.json', saved)


def choose_game(directory):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    saved = load_json(directory / 'app-settings.json', {})
    matches = discover(saved.get('game_exe'))
    if len(matches) == 1:
        return matches[0]
    root = tk.Tk()
    from tk_lifecycle import guard_tk
    guard_tk(root)
    root.title(TITLE + ' · 选择游戏')
    root.geometry('670x300')
    root.minsize(520, 270)
    root.option_add('*Font', ('Microsoft YaHei UI', 10))
    chosen = []
    message = tk.StringVar(value='找到多个游戏目录，请选择一个。' if matches else '未在 Steam 游戏库中找到游戏，可手动选择 Ruins of Dawn 文件夹。')
    ttk.Label(root, textvariable=message, wraplength=600).pack(fill='x', padx=22, pady=(22, 12))
    value = tk.StringVar(value=str(matches[0]) if matches else '')
    ttk.Combobox(root, values=[str(x) for x in matches], textvariable=value).pack(fill='x', padx=22, pady=8)

    def browse():
        selected = filedialog.askdirectory(parent=root, title='选择 Steam 中的 Ruins of Dawn 游戏文件夹')
        if selected:
            value.set(selected)

    def rescan():
        found = discover()
        if len(found) == 1:
            value.set(str(found[0]))
            message.set('已找到游戏，点击开始。')
        else:
            message.set('没有找到唯一的游戏目录，请手动选择。')

    def accept():
        game = resolve_game(value.get().strip().strip('"'))
        if game is None:
            messagebox.showerror(TITLE, '此目录中没有找到 Ruins of Dawn 游戏程序，请选择正确的游戏文件夹。', parent=root)
            return
        chosen.append(game)
        root.destroy()

    bar = ttk.Frame(root)
    bar.pack(fill='x', padx=22, pady=16)
    ttk.Button(bar, text='选择游戏目录', command=browse).pack(side='left')
    ttk.Button(bar, text='重新检测', command=rescan).pack(side='left', padx=8)
    ttk.Button(bar, text='开始', command=accept).pack(side='right')
    ttk.Label(root, text='游戏安装目录只用于识别进程；设置保存在当前 Windows 用户目录。', wraplength=600).pack(fill='x', padx=22)
    root.mainloop()
    return chosen[0] if chosen else None


def run_overlay(directory, backend, close_after=None):
    import loot_overlay
    from startup_window import StartupWindow
    loot_overlay.BASE = directory

    class PackagedOverlay(loot_overlay.Overlay):
        def tick(self):
            current_pid = backend.state.get('game_pid', 0)
            if current_pid != getattr(self, 'session_pid', None):
                self.session_pid = current_pid
                self.game = None
                self.placed = False
            super().tick()

        def close(self):
            backend.stop.set()
            super().close()

    overlay = PackagedOverlay()
    startup = StartupWindow(overlay, backend.game, VERSION, directory=directory)
    window = startup.window

    def update():
        state = backend.state
        if state['status'] == 'watching' and overlay.placed and overlay.root.winfo_viewable() and not startup.user_open:
            window.withdraw()
        else:
            startup.set_state(state)
            if window.state() == 'withdrawn':
                window.deiconify()
            if not state.get('game_pid'):
                overlay.game = None
                overlay.placed = False
                overlay.root.withdraw()
        overlay.root.after(500, update)

    overlay.root.after(500, update)
    if close_after:
        overlay.root.after(int(close_after * 1000), overlay.close)
    overlay.root.mainloop()


def self_test(output):
    import tkinter as tk
    from gear_view import catalog_data, configured_rules, skill_view
    from overlay_settings import Settings
    from overlay_markers import MarkerLayer
    from overlay_panes import SectionPanes
    root = tk.Tk()
    root.withdraw()
    root.update()
    catalog = catalog_data()
    result = {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
              'tk': root.tk.call('info', 'patchlevel'), 'affixes': len(catalog['affixes']),
              'equipment': len(catalog['equipment']), 'rules': len(configured_rules()),
              'skill_64': skill_view(64), 'game_paths': [str(x) for x in discover()],
              'features': ['filter', 'backpack_markers', 'native_bridge_preview'],
              'native_game_verified': False, 'success': True}
    root.destroy()
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--self-test', type=Path)
    parser.add_argument('--smoke-test', type=Path)
    parser.add_argument('--seconds', type=float, default=45)
    parser.add_argument('--replace-running', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test(args.self_test)
        if not args.smoke_test:
            return
    directory = (args.data_dir or user_directory()).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if args.replace_running:
        # Preflight the UI/catalog before asking the previous helper to close.
        self_test(directory / 'upgrade-self-test.json')
        previous = load_json(directory / 'overlay-status.json', {}) or {}
        if previous.get('status') == 'running':
            signal = directory / 'overlay-stop.flag'
            signal.write_text('replace with ' + VERSION, encoding='utf8')
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                current = load_json(directory / 'overlay-status.json', {}) or {}
                if current.get('status') == 'stopped':
                    break
                time.sleep(.1)
            else:
                signal.unlink(missing_ok=True)
                raise RuntimeError('旧助手未正常关闭，已取消替换；请关闭旧助手后启动新版本。')
            time.sleep(.5)
            signal.unlink(missing_ok=True)
    lock = (directory / 'app.lock').open('a+b')
    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        ctypes.windll.user32.MessageBoxW(None, '装备助手已经在运行，请查看游戏旁的悬浮框。', TITLE, 0x40)
        lock.close()
        return
    backend = None
    try:
        prepare_settings(directory)
        game = choose_game(directory)
        if game is None:
            return
        write_json(directory, 'app-settings.json', {'game_exe': str(game), 'version': VERSION})
        backend = ProcessBackend(game, directory)
        backend.start()
        if args.smoke_test:
            start = time.monotonic()
            observed = None
            while time.monotonic() - start < min(args.seconds, 120):
                if backend.state['status'] == 'watching':
                    current = load_json(directory / 'current-loot.json', {})
                    if current.get('status') == 'watching':
                        observed = {'inventory': current, 'ui': load_json(directory / 'feature-status.json', {})}
                        break
                time.sleep(.2)
            report = {'success': observed is not None, 'frozen': bool(getattr(sys, 'frozen', False)),
                      'discovery': backend.last_scan, 'state': backend.state, 'observed': observed}
            args.smoke_test.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            run_overlay(directory, backend)
    finally:
        if backend:
            backend.close()
        lock.close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        directory = user_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'startup-error.txt').write_text(error, encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None, '启动失败。错误记录：\n' + str(directory / 'startup-error.txt'), TITLE, 0x10)
        raise
