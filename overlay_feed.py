"""Latest-value mailbox: file I/O and filtering never run in Tk callbacks."""
import copy
from dataclasses import dataclass, field, replace
import datetime as dt
import json
from pathlib import Path
import threading
import time

from gear_view import configured_rules, normalize_item, select_sections
from native_policy import identity


def empty():
    return {key: [] for key in ('numeric', 'legendary', 'lower')}


@dataclass(frozen=True)
class Snapshot:
    status: dict = field(default_factory=dict)
    current: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    ui: dict = field(default_factory=dict)
    rules: list = field(default_factory=list)
    sections: dict = field(default_factory=empty)
    live: bool = False
    error: str | None = None
    stop_requested: bool = False


class OverlayFeed:
    NAMES = ('continuous-status.json', 'current-loot.json', 'feature-status.json',
             'loot-overlay-settings.json', 'loot-filter-rules.json', 'native-status.json', 'native-schema.json')

    def __init__(self, directory, start=True):
        self.directory = Path(directory)
        self.snapshot = Snapshot()
        self.raw, self.stamps, self.pending = {}, {}, {}
        self.inflight = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.previous_input = None
        self.previous_rules = None
        self.rules = []
        self.sections = empty()
        self.native_client = None
        if start:
            self.thread = threading.Thread(target=self.run, name='OverlayFiles', daemon=True)
            self.thread.start()

    def read(self, name, default=None):
        with self.lock:
            value = self.pending.get(name, self.inflight.get(name, self.raw.get(name, default)))
        return copy.deepcopy(value)

    def submit(self, name, value):
        value = copy.deepcopy(value)
        with self.lock:
            self.pending[name] = value
        self.wake.set()

    def _flush(self):
        with self.lock:
            pending, self.pending = self.pending, {}
            # Keep a local edit readable while slow disk I/O is in progress.
            # New submissions still take precedence over this older batch.
            self.inflight.update(pending)
        for name, value in pending.items():
            path = self.directory / name
            temporary = path.with_suffix('.display.tmp')
            try:
                temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
                temporary.replace(path)
                with self.lock:
                    self.raw[name] = value
                    self.inflight.pop(name, None)
                self.stamps.pop(name, None)
            except OSError:
                with self.lock:
                    self.pending.setdefault(name, value)
                    self.inflight.pop(name, None)

    def _read_changed(self, name):
        with self.lock:
            if name in self.pending or name in self.inflight:
                return self.pending.get(name, self.inflight.get(name))
        path = self.directory / name
        try:
            info = path.stat()
            stamp = (info.st_mtime_ns, info.st_size)
            if self.stamps.get(name) != stamp:
                value = json.loads(path.read_text(encoding='utf8'))
                with self.lock:
                    # A checkbox may change between opening and parsing the
                    # old file. Never let that disk value undo the local edit.
                    if name not in self.pending and name not in self.inflight:
                        self.raw[name] = value
                        self.stamps[name] = stamp
        except (OSError, ValueError):
            # Atomic replacement may transiently deny an open on Windows.
            # Retain the last sample, but the heartbeat still expires below.
            pass
        with self.lock:
            return self.pending.get(name, self.inflight.get(name, self.raw.get(name)))

    def poll(self):
        self._flush()
        values = {name: self._read_changed(name) for name in self.NAMES}
        status = values['continuous-status.json'] or {}
        current = values['current-loot.json'] or {}
        settings = values['loot-overlay-settings.json'] or {}
        saved_rules = values['loot-filter-rules.json']
        if not self.rules or saved_rules != self.previous_rules:
            self.rules = configured_rules(saved_rules)
            self.previous_rules = saved_rules
        try:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(status['heartbeat_utc'])).total_seconds()
            live = status.get('status') == 'watching' and 0 <= age < 3 and current.get('status') == 'watching'
        except (KeyError, ValueError, TypeError):
            live = False
        # Ignore timestamps and free-slot counters: they do not change matches.
        inputs = (live, current.get('items', []), self.rules, settings)
        if inputs != self.previous_input:
            self.sections = select_sections(current, self.rules, settings) if live else empty()
            self.previous_input = inputs
        snapshot = Snapshot(status=status, current=current, settings=settings,
            ui=dict(values['feature-status.json'] or {}, native=values['native-status.json'] or {}),
            rules=self.rules, sections=self.sections, live=live,
            stop_requested=any((self.directory / name).exists() for name in ('stop.flag', 'overlay-stop.flag')))
        if values['native-schema.json']:
            if self.native_client is None:
                from native_client import NativeClient
                self.native_client = NativeClient()
            request = self.native_client.update(snapshot, values['native-schema.json'], values['native-status.json'])
            if request is not None:
                self.submit('native-request.json', request)
            if live and self.native_client.pid == status.get('game_pid') and self.native_client.player == snapshot.ui.get('ui', {}).get('player_address'):
                notices = self.native_client.lock_notices.visible(time.monotonic())
                retained = []
                for entry in current.get('items', []) if notices else []:
                    notice = notices.get(entry['index'])
                    if notice and entry['item'].get('锁定') and identity(entry['item']) == notice['identity']:
                        item = normalize_item(entry, self.rules)
                        if item['hits']:
                            retained.append(dict(item, auto_locked=True))
                if retained:
                    indices = {item['index'] for item in retained}
                    numeric = [item for item in self.sections['numeric'] if item['index'] not in indices] + retained
                    snapshot = replace(snapshot, sections=dict(self.sections, numeric=sorted(numeric, key=lambda item: item['index'])))
        # Publish once after adding notices. The original filter result stays
        # cached for lock decisions; notice expiry still runs every poll.
        self.snapshot = snapshot

    def run(self):
        while not self.stop.is_set():
            try:
                self.poll()
            except Exception as exc:
                self.previous_input = None
                self.snapshot = Snapshot(settings=self.snapshot.settings, error=f'{type(exc).__name__}: {exc}')
            self.wake.wait(.1)
            self.wake.clear()
        self._flush()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(2)
        else:
            self._flush()
