"""Fresh-session, read-only backend for the distributed app. No saved addresses."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
import pathlib
import struct
import threading
import time

from continuous_watch import ContinuousWatch, atomic_text, utcnow
from game_install import EXE_NAME
from live_items import clean
from probe import Probe, configure_runtime, k, ptr, u32, u64


class PROCESSENTRY32W(c.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                ('th32DefaultHeapID', c.c_size_t), ('th32ModuleID', w.DWORD),
                ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]

k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
k.CreateToolhelp32Snapshot.restype = w.HANDLE
k.Process32FirstW.argtypes = [w.HANDLE, c.POINTER(PROCESSENTRY32W)]
k.Process32NextW.argtypes = [w.HANDLE, c.POINTER(PROCESSENTRY32W)]


def running_games(expected):
    """Pin executable identity, independent of title, foreground or monitor."""
    result = []
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    if snapshot == c.c_void_p(-1).value or not snapshot:
        return result
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = c.sizeof(entry)
        valid = k.Process32FirstW(snapshot, c.byref(entry))
        while valid:
            if entry.szExeFile.casefold() == EXE_NAME.casefold():
                handle = k.OpenProcess(0x1000, False, entry.th32ProcessID)
                if handle:
                    try:
                        length = w.DWORD(32768)
                        name = c.create_unicode_buffer(length.value)
                        if k.QueryFullProcessImageNameW(handle, 0, name, c.byref(length)) and name.value.casefold() == str(expected).casefold():
                            result.append(entry.th32ProcessID)
                    finally:
                        k.CloseHandle(handle)
            valid = k.Process32NextW(snapshot, c.byref(entry))
    finally:
        k.CloseHandle(snapshot)
    return result


def write_json(directory, name, value):
    atomic_text(pathlib.Path(directory) / name, json.dumps(value, ensure_ascii=False, indent=2))


class SessionProbe(Probe):
    REQUIRED = {'简化物品属性', '装备基础属性', '装备特殊属性', '装备极品属性'}

    def __init__(self, pid, directory, stop, progress):
        super().__init__(pid, pathlib.Path(directory) / 'discovery.json', 45)
        self.stop, self.progress = stop, progress

    def check(self):
        if self.stop.is_set():
            raise InterruptedError('应用已关闭')
        super().check()

    def save(self, stage):
        self.progress('discovering', self.pid, stage)

    def discover(self):
        from discovery_cache import fingerprint, restore_globals, cache_value
        try:
            self.open(load_sections=False)
            version = fingerprint(self.result['verified_image'])
            cache_path = self.output.parent / 'discovery-cache.json'
            try:
                cache = json.loads(cache_path.read_text(encoding='utf8'))
            except (OSError, ValueError):
                cache = {}
            hit = cache.get('schema') == 1 and cache.get('fingerprint') == version and restore_globals(self, cache)
            if not hit:
                self.names, self.blocks = {}, []
                self.load_writable_sections()
                self.find_names()
                self.find_objects()
            self.result['discovery_cache'] = {'globals_hit': bool(hit), 'fingerprint': version}
            info = self.objects
            chunks = self.read(info['chunks_address'], info['chunk_count'] * 8)
            if len(chunks) != info['chunk_count'] * 8:
                raise ValueError('无法读取当前游戏对象列表')
            classes, metadata, roots, indices = {}, {}, [], {}
            def consider(obj):
                if not obj or obj['flags'] & 0x18010:
                    return
                address = obj['class_address']
                if address not in classes:
                    classes[address] = self.object_info(address)
                cls = classes[address]
                if not cls:
                    return
                if cls['name'] in ('ScriptStruct', 'UserDefinedStruct') and obj['name'] in self.REQUIRED | {'格子属性', '装备属性'}:
                    fields = self.fields(obj['address'])
                    if fields:
                        metadata[obj['name']] = {'struct_address': obj['address'], 'fields': fields}
                        indices[obj['name']] = obj['index']
                if cls['name'] == '主UI_C':
                    fields = {clean(f['name']): f for f in self.fields(address)}
                    link, bag = fields.get('对应玩家'), fields.get('背包开启')
                    if link and link['kind'] == 'ObjectProperty' and bag and bag['kind'] == 'BoolProperty':
                        value = self.read(obj['address'] + link['offset'], 8)
                        player = self.object_info(u64(value)) if len(value) == 8 else None
                        pcls = self.object_info(player['class_address']) if player and not player['flags'] & 0x18010 else None
                        if pcls and pcls['name'] == 'BP_mypawn_C':
                            roots.append(obj)
                            indices['main_ui'] = obj['index']
            if hit:
                for name, index in cache.get('indices', {}).items():
                    if not isinstance(index, int) or not 0 <= index < info['used']:
                        continue
                    chunk = u64(chunks, index // 65536 * 8)
                    raw = self.read(chunk + index % 65536 * info['stride'], 8)
                    obj = self.object_info(u64(raw)) if len(raw) == 8 else None
                    if obj and obj['index'] == index and (name == 'main_ui' or obj['name'] == name):
                        consider(obj)
            fast = self.REQUIRED <= set(metadata) and len(roots) == 1
            if not fast:
                classes, metadata, roots, indices = {}, {}, [], {}
            for chunk_index in range(info['chunk_count']):
                if fast:
                    break
                count = min(65536, info['used'] - chunk_index * 65536)
                if count <= 0:
                    break
                items = self.read(u64(chunks, chunk_index * 8), count * info['stride'])
                for index in range(count):
                    self.check()
                    offset = index * info['stride']
                    if offset + 8 > len(items):
                        break
                    obj = self.object_info(u64(items, offset))
                    consider(obj)
                    if index % 5000 == 0:
                        self.save('正在识别当前背包')
            missing = self.REQUIRED - set(metadata)
            if missing:
                raise ValueError('游戏数据格式未就绪或版本不兼容：' + '、'.join(sorted(missing)))
            if len(roots) != 1:
                raise ValueError('请进入角色场景后等待识别' if not roots else '检测到多个角色界面，暂不读取')
            self.result['discovery_cache']['objects_hit'] = fast
            write_json(self.output.parent, 'discovery-cache.json', cache_value(self, version, indices))
            seed = {**self.result, 'reflected_types': metadata}
            instances = {'equipment_candidates': [{'outer_chain': [dict(roots[0], name='主UI_C')]}]}
            return seed, instances
        finally:
            if self.handle:
                k.CloseHandle(self.handle)
                self.handle = None


class SessionWatch(ContinuousWatch):
    def __init__(self, pid, directory, seed, instances, stop, progress):
        self.stop, self.progress = stop, progress
        self.main_ui = None
        self.next_ui = 0.0
        super().__init__(pid, directory, seed, instances)

    def check(self):
        if self.stop.is_set():
            raise InterruptedError('应用已关闭')
        super().check()

    def setup_source(self):
        self.main_ui = None
        self._sample_cache = None
        self.backpack_slot_states = None
        super().setup_source()
        self.main_ui = next(r for r in self.result['container_discovery'] if r['class_name'] == '主UI_C')
        self.bag_flag = next(f for f in self.main_ui['fields'] if f['name'] == '背包开启' and f['kind'] == 'BoolProperty')
        from native_client import schema_document
        write_json(self.output.parent, 'native-schema.json', schema_document(self.types, self.pid))

    def ui_state(self):
        if self.phase != 'watching' or not self.main_ui or not self.handle:
            return {'valid': False, 'backpack_open': False}
        expected = self.main_ui['object']
        current = self.object_info(expected['address'])
        if not current or current['flags'] & 0x18010 or any(current[key] != expected[key] for key in ('index', 'class_address')):
            return {'valid': False, 'backpack_open': False}
        value = self.read(expected['address'] + self.bag_flag['offset'], 1)
        if value not in (b'\0', b'\1') or self.player_changed():
            return {'valid': False, 'backpack_open': False}
        return {'valid': True, 'backpack_open': value == b'\1', 'player_address': self.source['owner']['address']}

    def publish_ui(self):
        try:
            ui = self.ui_state()
        except (ValueError, OSError, struct.error):
            ui = {'valid': False, 'backpack_open': False}
        write_json(self.output.parent, 'feature-status.json', {
            'status': 'running' if ui['valid'] else 'waiting', 'mode': 'read_only',
            'game_pid': self.pid, 'worker_pid': os.getpid(), 'ui': ui, 'heartbeat_utc': utcnow()})
        self.next_ui = time.monotonic() + .15

    def take(self, source):
        from loot_current import occupied_main_slots
        owner = self.object_info(source['owner']['address'])
        if not owner or owner['flags'] & 0x18010 or any(owner[key] != source['owner'][key] for key in ('index', 'class_address')):
            self._sample_cache = None
            return None
        header = self.read(source['header_address'], 16)
        if len(header) != 16:
            self._sample_cache = None
            return None
        address, count, capacity = struct.unpack('<Qii', header)
        if not (60 <= count <= capacity <= 10000) or not ptr(address):
            self._sample_cache = None
            return None
        # The main backpack is the first 60 slots; storage is not displayed.
        raw = self.read(address, 60 * source['stride'])
        if len(raw) != 60 * source['stride'] or header != self.read(source['header_address'], 16) or raw != self.read(address, len(raw)):
            self._sample_cache = None
            return None
        key = (owner['address'], owner['index'], header, raw)
        cached = getattr(self, '_sample_cache', None)
        if cached is not None and cached[0] == key:
            result = cached[1]
        else:
            decoded = [self.decode(raw[i * source['stride']:(i + 1) * source['stride']], source['type_name']) for i in range(60)]
            self.occupied = occupied_main_slots(decoded)
            self.backpack_slot_states = [[item.get('物品类型', item.get('种类', 0)), bool(item.get('锁定'))]
                                         for item in decoded]
            result = {i: self.compact(item) for i, item in enumerate(decoded)
                      if item.get('物品类型', item.get('种类')) == 1 and item.get('名字', item.get('名称')) not in (None, '', 'None')}
            self._sample_cache = key, result
        if time.monotonic() >= self.next_ui:
            self.publish_ui()
        return result

    def publish(self):
        items = self.state.export() if self.phase == 'watching' else []
        write_json(self.output.parent, 'current-loot.json', {
            'status': self.phase, 'sampled_utc': self.last_sample, 'items': items, 'count': len(items),
            'backpack_occupied_indices': self.occupied if self.phase == 'watching' else None,
            'backpack_slot_states': getattr(self, 'backpack_slot_states', None) if self.phase == 'watching' else None,
            'backpack_free_slots': 60 - len(self.occupied) if self.phase == 'watching' and self.occupied is not None else None})
        self.progress(self.phase, self.pid, self.error)
        self.publish_ui()
        self.next_publish = time.monotonic() + 1


class Backend:
    def __init__(self, game, directory):
        self.game, self.directory = str(game), pathlib.Path(directory)
        self.stop = threading.Event()
        self.thread = None
        self.state = {'status': 'starting', 'game_pid': 0}
        self.last_scan = None
        configure_runtime(game, directory)

    def progress(self, status, pid=0, detail=None):
        self.state = {'status': status, 'game_pid': pid, 'worker_pid': os.getpid(),
                      'heartbeat_utc': utcnow(), 'error': detail, 'mode': 'read_only'}
        write_json(self.directory, 'continuous-status.json', self.state)

    def clear(self, status, pid=0, detail=None):
        write_json(self.directory, 'current-loot.json', {'status': status, 'items': [], 'count': 0, 'backpack_free_slots': None})
        write_json(self.directory, 'feature-status.json', {
            'status': 'waiting', 'mode': 'read_only', 'game_pid': pid, 'ui': {'valid': False, 'backpack_open': False}, 'heartbeat_utc': utcnow()})
        self.progress(status, pid, detail)

    def start(self):
        self.clear('waiting_for_game')
        self.thread = threading.Thread(target=self.run, name='ReadOnlyInventory', daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.is_set():
                games = running_games(self.game)
                if len(games) != 1:
                    self.clear('waiting_for_game', detail='检测到多个游戏进程，请只保留一个' if games else None)
                    self.stop.wait(1)
                    continue
                pid = games[0]
                try:
                    self.clear('discovering', pid)
                    started = time.monotonic()
                    seed, instances = SessionProbe(pid, self.directory, self.stop, self.progress).discover()
                    self.last_scan = {'game_pid': pid, 'seconds': round(time.monotonic() - started, 2),
                                      'structures': sorted(seed['reflected_types']), 'fresh_discovery': True,
                                      'cache': seed.get('discovery_cache', {})}
                    SessionWatch(pid, self.directory, seed, instances, self.stop, self.progress).run()
                except InterruptedError:
                    break
                except Exception as exc:
                    self.clear('waiting_for_backpack', pid, f'{type(exc).__name__}: {exc}')
                self.stop.wait(3)
        finally:
            self.clear('stopped')
