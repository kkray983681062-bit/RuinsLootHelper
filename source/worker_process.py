"""Spawn the inventory reader outside Tk's process/GIL; bound its lifetime."""
import multiprocessing as mp
import os
from pathlib import Path
import queue
import time
import traceback


def reader_main(game, directory, stop, messages):
    from release_runtime import Backend

    class Worker(Backend):
        def progress(self, status, pid=0, detail=None):
            super().progress(status, pid, detail)
            value = dict(self.state, last_scan=self.last_scan)
            try:
                messages.put_nowait(value)
            except queue.Full:
                pass  # Disk heartbeat is also available; never stall sampling.

    try:
        backend = Worker(game, directory)
        backend.stop = stop
        backend.run()
    except BaseException:
        Path(directory, 'worker-error.txt').write_text(traceback.format_exc(), encoding='utf8')
        raise


class ProcessBackend:
    def __init__(self, game, directory):
        self.game, self.directory = str(game), Path(directory)
        context = mp.get_context('spawn')
        self.context = context
        self.stop = context.Event()
        self.messages = context.Queue(maxsize=32)
        self.process = None
        self._state = {'status': 'starting', 'game_pid': 0}
        self.last_scan = None
        self.restart_at = 0

    def start(self):
        self.process = self.context.Process(target=reader_main,
            args=(self.game, str(self.directory), self.stop, self.messages),
            name='RuinsInventoryReader', daemon=True)
        self.process.start()

    @property
    def state(self):
        while True:
            try:
                state = self.messages.get_nowait()
            except queue.Empty:
                break
            self.last_scan = state.pop('last_scan', self.last_scan)
            self._state = state
        if self.process and not self.process.is_alive() and not self.stop.is_set():
            self._state = {'status': 'monitor_failed', 'game_pid': 0,
                'error': f'读取进程已退出（{self.process.exitcode}），正在恢复'}
            if not self.restart_at:
                self.restart_at = time.monotonic() + 5
            elif time.monotonic() >= self.restart_at:
                self.process.join(0)
                self.start()
                self.restart_at = 0
        return self._state

    def close(self):
        self.stop.set()
        if self.process:
            self.process.join(3)
            if self.process.is_alive():
                # Only this helper's own child; never the game process.
                self.process.terminate()
                self.process.join(2)
        self.messages.close()
