"""One-time reader upgrade. Preflight succeeds before the existing reader stops."""
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
import os
import pathlib
import time
from continuous_watch import ContinuousWatch, atomic_text
from probe import k

BASE = pathlib.Path(__file__).resolve().parent


def report(phase, error=None):
    atomic_text(BASE / 'reader-upgrade-status.json', json.dumps(dict(
        phase=phase, pid=os.getpid(), error=error,
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat()), ensure_ascii=False))


def main():
    if (BASE / 'stop.flag').exists():
        raise RuntimeError('An explicit stop flag is already present')
    previous = json.loads((BASE / 'continuous-status.json').read_text(encoding='utf-8'))
    if previous['status'] != 'watching':
        raise RuntimeError('Existing reader is not watching')
    worker = ContinuousWatch(previous['game_pid'], BASE, BASE / 'probe-elevated-1.json', BASE / 'live-items-1.json')
    report('preflight')
    worker.save = lambda stage: None  # Preflight must not replace the old reader's live files.
    try:
        worker.open()
    finally:
        del worker.save
    if not worker.game_alive():
        raise RuntimeError('Game process is no longer running')
    k.CloseHandle(worker.handle)
    worker.handle = None
    k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k.OpenProcess.restype = w.HANDLE
    old = k.OpenProcess(0x00100000, False, previous['worker_pid'])  # SYNCHRONIZE only
    if not old:
        raise RuntimeError('Cannot wait for the previous reader')
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    try:
        report('switching')
        (BASE / 'stop.flag').write_text('Reader version upgrade', encoding='utf-8')
        if k.WaitForSingleObject(old, 10000) != 0:
            raise RuntimeError('Previous reader did not stop; no second reader was started')
        if (BASE / 'reader-upgrade.cancel').exists():
            report('cancelled')
            return
        (BASE / 'stop.flag').unlink()
    finally:
        k.CloseHandle(old)
    report('running_new_reader')
    worker.run()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        report('failed', f'{type(exc).__name__}: {exc}')
        raise
