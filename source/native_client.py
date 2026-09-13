"""Local native bridge mailbox; called by the file worker, never Tk callbacks."""
import time
import uuid

from live_items import clean
from lock_library import selected_indices
from native_policy import AutoLockNotices, LockPolicy, identity
from pickup_library import codex_names, codex_selection, pickup_options

PROTOCOL = 4

NESTED = {'基础属性': '装备基础属性', '特殊属性': '装备特殊属性',
          '极品属性': '装备极品属性', '装备极品属性': '装备极品属性', '装备属性': '装备属性'}


def fresh_status(value):
    return (isinstance(value, dict) and isinstance(value.get('utc'), (float, int))
            and 0 <= time.time() - value['utc'] < 2)


def schema_document(types, pid):
    fields = types['简化物品属性']['fields']
    named = {clean(f['name']): f['name'] for f in fields}
    actor = {clean(f['name']): f['name'] for f in types.get('格子属性', {}).get('fields', [])}
    equipment = {clean(f['name']): f['name'] for f in types.get('装备属性', {}).get('fields', [])}
    return {'pid': pid, 'item_kind': named['物品类型'], 'locked': named['锁定'],
            'actor_kind': actor.get('种类'), 'actor_name': actor.get('名称'),
            'actor_equipment': actor.get('装备属性'),
            'equipment_tier': equipment.get('等阶'), 'equipment_type': equipment.get('装备类型'),
            'types': {name: [{'name': f['name'], 'kind': f['kind']} for f in row['fields']]
                      for name, row in types.items()}}


def expected_fields(item, schema, type_name='简化物品属性', prefix=()):
    result = []
    for field in schema['types'][type_name]:
        name, kind = clean(field['name']), field['kind']
        if name in ('锁定', '格子id', '格子ID'):
            continue
        path = [*prefix, field['name']]
        if kind == 'StructProperty' and name in NESTED and NESTED[name] in schema['types']:
            result.extend(expected_fields(item.get(name, {}), schema, NESTED[name], path))
        elif kind in ('IntProperty', 'FloatProperty', 'DoubleProperty', 'ByteProperty', 'BoolProperty', 'NameProperty'):
            default = 'None' if kind == 'NameProperty' else False if kind == 'BoolProperty' else 0
            result.append({'path': path, 'kind': kind, 'value': item.get(name, default)})
    return result


class NativeClient:
    def __init__(self):
        self.session = uuid.uuid4().hex
        self.policy = LockPolicy()
        self.pid = None
        self.player = None
        self.game = None
        self.sequence = 0
        self.next_send = 0
        self.last_pickup = None
        self.pickup_revision = 0
        self.locks = []
        self.awaiting = {}
        self.lock_notices = AutoLockNotices()
        self.recycle_key, self.recycle_command = None, None
        # This token and decision belong to the helper process, not a character.
        self.rift_run_id = uuid.uuid4().hex
        self.rift_permission = None

    def update(self, snapshot, schema, native):
        from loot_overlay import find_game
        from overlay_markers import foreground_matches, game_bounds, u
        now = time.monotonic()
        if now < self.next_send:
            return None
        self.next_send = now + .15
        pid = snapshot.status.get('game_pid')
        config = snapshot.settings.get('native', {})
        options = pickup_options(config)
        saved_exclusions = snapshot.settings.get('pickup_exclusions', [])
        excluded = {key: True for key in saved_exclusions if isinstance(key, str)} if isinstance(saved_exclusions, list) else {}
        selected_codex = codex_selection(snapshot.settings)
        if not snapshot.settings.get('drop_filter_enabled', True):
            excluded, selected_codex = {}, set()
        pickup_key = (options, excluded, selected_codex)
        if self.last_pickup != pickup_key:
            self.pickup_revision += 1
            self.last_pickup = pickup_key
        if pid != self.pid:
            self.pid, self.game = pid, None
            self.policy, self.locks, self.awaiting = LockPolicy(), [], {}
            self.lock_notices = AutoLockNotices()
            self.recycle_key, self.recycle_command = None, None
            self.session = uuid.uuid4().hex
        if not self.game or not u.IsWindow(self.game):
            self.game = find_game(pid) if pid else None
        bounds = game_bounds(self.game)
        active = bool(pid and bounds and foreground_matches(self.game, pid))
        ui = snapshot.ui.get('ui', {})
        player = ui.get('player_address', 0)
        if player != self.player:
            self.player = player
            self.session = uuid.uuid4().hex
            self.policy, self.locks, self.awaiting = LockPolicy(), [], {}
            self.lock_notices = AutoLockNotices()
            self.recycle_key, self.recycle_command = None, None
        usable = snapshot.live and ui.get('valid', False) and isinstance(schema, dict) and schema.get('pid') == pid
        request = {'protocol': PROTOCOL, 'session': self.session, 'game_pid': pid or 0,
            'expires': time.time() + 1, 'monotonic': now, 'player_address': player,
            'active': active and bool(usable), 'pickup': bool(config.get('pickup', False) and usable),
            'pickup_radius': int(options['pickup_range_multiplier'] * 1000),
            'pickup_interval': options['pickup_interval'], 'pickup_batch': options['pickup_batch'],
            'pickup_revision': self.pickup_revision, 'excluded_equipment': excluded,
            'skip_codex': bool(selected_codex),
            'block_drops': bool(usable and snapshot.settings.get('codex_selection_version') == 1 and (selected_codex or excluded)),
            'codex_names': {name: True for name in sorted(selected_codex)},
            'skip_unknown_codex': bool(codex_names() <= selected_codex),
            'borderless': bool(config.get('borderless', False) and usable),
            # The helper locates the header lock on screen. Stop native Tick
            # collection so automatic circles do not depend on a game restart.
            'markers': False,
            'viewport': list(bounds[2:]) if bounds else None, 'schema': schema if usable else None, 'locks': [],
            'auto_lock': bool(config.get('lock') and usable),
            'auto_recycle': bool(config.get('auto_recycle', False) and config.get('lock') and usable),
            'auto_rift': bool(config.get('auto_rift', False) and usable),
            'bagua_marker': bool(config.get('bagua_marker', False) and usable),
            'rift_run_id': self.rift_run_id,
            'rift_permission': self.rift_permission,
            'recycle': None}
        self.policy.observe(snapshot.current.get('items', []) if usable else [], now)
        selected = config.get('lock_sections', {'numeric': True, 'legendary': False, 'lower': False})
        indices = {entry['index'] for key, entries in snapshot.sections.items() if selected.get(key, False) for entry in entries}
        indices.update(selected_indices(snapshot.current.get('items', []) if usable else [],
                                       snapshot.settings.get('lock_library', {})))
        ready = (fresh_status(native) and native.get('protocol') == PROTOCOL and native.get('ready') and native.get('session') == self.session
                 and native.get('player_address') == player and native.get('game_pid') == pid)
        if ready and self.rift_permission is None:
            rift = native.get('rift')
            if (isinstance(rift, dict) and rift.get('run_id') == self.rift_run_id
                    and rift.get('checked') is True and isinstance(rift.get('eligible'), bool)):
                self.rift_permission = {key: rift.get(key) for key in
                    ('run_id', 'checked', 'eligible', 'level', 'extra_drop_pct', 'extra_elite_pct')}
                request['rift_permission'] = self.rift_permission
        acks = {ack['id']: ack.get('result') for ack in (native.get('acks', []) or [])
                if isinstance(ack, dict) and isinstance(ack.get('id'), str)} if ready else {}
        if usable:
            self.lock_notices.observe(snapshot.current.get('items', []), acks, now)
        else:
            self.lock_notices = AutoLockNotices()
        current = {entry['index']: entry['item'] for entry in snapshot.current.get('items', [])}
        self.awaiting = {key: deadline for key, deadline in self.awaiting.items()
                         if key in self.policy.pending and deadline > now}
        pending = []
        for cmd in self.locks:
            key = cmd['identity']
            if cmd['id'] in acks:
                if acks[cmd['id']] in ('locked', 'awaiting_readback', 'already_locked'):
                    self.awaiting[key] = now + 5
                else:
                    self.policy.cooldowns[key] = max(self.policy.cooldowns.get(key, 0), now + 2)
                continue
            item = current.get(cmd['index'])
            if cmd['index'] in indices and item and not item.get('锁定') and identity(item) == key and self.policy.cooldowns.get(key, 0) <= now:
                pending.append(cmd)
        self.locks = pending
        # Cancelled/moved commands must release their identity for the new slot.
        self.policy.pending = {cmd['identity'] for cmd in self.locks} | set(self.awaiting)
        if ready and config.get('lock') and active and usable:
            for entry in self.policy.candidates(indices, now):
                expected = expected_fields(entry['item'], schema)
                if len(expected) < 5:
                    continue
                self.sequence += 1
                self.locks.append({'id': f'{self.session}:{self.sequence}', 'index': entry['index'],
                                   'identity': identity(entry['item']), 'expected': expected})
                self.policy.requested(entry)
        if not config.get('lock') or not usable:
            self.locks = []
            self.awaiting = {}
            self.policy.pending.clear()
        request['locks'] = self.locks[:1] if ready and active else []
        self.lock_notices.sent(request['locks'], now)
        if request['auto_recycle'] and ready and active and native.get('auto_recycle_supported'):
            request['recycle'], request['recycle_wait'] = self.prepare_recycle(
                snapshot.current, indices, schema, now)
            if request['recycle'] is None:
                self.recycle_key, self.recycle_command = None, None
        else:
            self.recycle_key, self.recycle_command = None, None
        return request

    def prepare_recycle(self, inventory, indices, schema, now):
        """Authorize one official bulk call against the exact inspected bag."""
        items = inventory.get('items', [])
        slots = inventory.get('backpack_slot_states')
        free = inventory.get('backpack_free_slots')
        if (not isinstance(slots, list) or len(slots) != 60 or
                any(not isinstance(slot, list) or len(slot) != 2 or
                    type(slot[0]) is not int or slot[0] < 0 or type(slot[1]) is not bool for slot in slots) or
                type(free) is not int or free != sum(slot[0] == 0 for slot in slots)):
            return None, 'waiting_for_inventory'
        bag = [entry for entry in items if isinstance(entry.get('index'), int) and 0 <= entry['index'] < 60]
        current = {entry['index']: entry['item'] for entry in bag}
        # The display's item list contains equipment only. Potions, materials
        # and books still occupy slots; retain their kind/lock state separately.
        if (len(current) != len(bag) or set(current) != {i for i, slot in enumerate(slots) if slot[0] == 1} or
                any(item.get('物品类型') != 1 or bool(item.get('锁定')) != slots[index][1]
                    for index, item in current.items())):
            return None, 'waiting_for_inventory'
        if free > 1:
            self.recycle_key, self.recycle_command = None, None
            return None, 'waiting_for_space_trigger'
        if any(deadline > now for deadline in self.policy.cooldowns.values()):
            return None, 'unlock_grace'
        protected = sorted(index for index in indices if 0 <= index < 60)
        if self.locks or self.awaiting or any(not current.get(index, {}).get('锁定') for index in protected):
            return None, 'waiting_for_locks'
        if not any(kind in (1, 4) and not locked for kind, locked in slots):
            return None, 'nothing_to_recycle'
        # Store field paths once, so a complete bag remains a small mailbox message.
        columns = [{'path': field['path'], 'kind': field['kind']} for field in expected_fields({}, schema)]
        if len(columns) < 5:
            return None, 'waiting_for_inventory'
        rows = []
        for index, item in sorted(current.items()):
            expected = expected_fields(item, schema)
            fields = [{'path': f['path'], 'kind': f['kind']} for f in expected]
            if fields != columns:
                return None, 'waiting_for_inventory'
            rows.append({'index': index, 'locked': bool(item.get('锁定')),
                         'values': [field['value'] for field in expected]})
        proof = {'columns': columns, 'rows': rows, 'protected': protected, 'slots': [slot[:] for slot in slots]}
        key = identity(proof)
        if key != self.recycle_key:
            self.sequence += 1
            self.recycle_key = key
            self.recycle_command = dict(proof, id=f'{self.session}:recycle:{self.sequence}')
        return self.recycle_command, 'checking'
