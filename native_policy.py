"""Volatile item tracking for native lock requests; no removed-item history."""
import hashlib
import json


def identity(item):
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in ('锁定', '格子id', '格子ID')}
        return value
    return hashlib.sha256(json.dumps(stable(item), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AutoLockNotices:
    """Ten-second readback notices for commands this helper actually sent."""

    def __init__(self):
        self.groups, self.pending, self.active = {}, {}, {}

    def observe(self, items, acks, now):
        groups = {}
        for entry in items:
            if 0 <= entry['index'] < 60:
                groups.setdefault(identity(entry['item']), []).append(entry)
        for token, notice in list(self.active.items()):
            group = groups.get(notice['identity'], [])
            same_slot = next((x for x in group if x['index'] == notice['index']), None)
            found = same_slot or (group[0] if len(group) == 1 else None)
            if now >= notice['expires'] or not found or not found['item'].get('锁定'):
                del self.active[token]
            else:
                notice['index'] = found['index']
        for token, pending in list(self.pending.items()):
            group = groups.get(pending['identity'], [])
            result = acks.get(token)
            if not group or now >= pending['deadline'] or (result and result not in ('locked', 'awaiting_readback')):
                del self.pending[token]
                continue
            if result:
                pending['acknowledged'] = True
            if not pending['acknowledged']:
                continue
            locked = [x for x in group if x['item'].get('锁定')]
            if len(locked) <= len(pending['previous_locked']):
                continue
            candidates = [x for x in locked if x['index'] not in pending['previous_locked']]
            found = next((x for x in candidates if x['index'] == pending['index']), None)
            if found is None and len(group) == 1 and len(candidates) == 1:
                found = candidates[0]
            if found is not None:
                self.active[token] = {'identity': pending['identity'], 'index': found['index'], 'expires': now + 10}
                del self.pending[token]
        self.groups = groups

    def sent(self, commands, now):
        for cmd in commands:
            token = cmd['id']
            group = self.groups.get(cmd['identity'], [])
            target = next((x for x in group if x['index'] == cmd['index']), None)
            if token in self.pending or token in self.active or not target or target['item'].get('锁定'):
                continue
            self.pending[token] = {'identity': cmd['identity'], 'index': cmd['index'],
                'previous_locked': {x['index'] for x in group if x['item'].get('锁定')},
                'deadline': now + 5, 'acknowledged': False}

    def visible(self, now):
        self.active = {token: notice for token, notice in self.active.items() if now < notice['expires']}
        return {notice['index']: dict(notice) for notice in self.active.values()}


class LockPolicy:
    def __init__(self):
        self.groups, self.cooldowns, self.pending = {}, {}, set()

    def observe(self, items, now):
        groups = {}
        for entry in items:
            if not 0 <= entry['index'] < 60:
                continue
            groups.setdefault(identity(entry['item']), []).append(entry)
        for key, entries in groups.items():
            old = self.groups.get(key, [])
            old_locked = sum(bool(x['item'].get('锁定')) for x in old)
            locked = sum(bool(x['item'].get('锁定')) for x in entries)
            if locked < old_locked and len(entries) - locked > len(old) - old_locked:
                # Identical copies have no game-issued unique ID: pause the
                # entire identical group instead of relocking the wrong copy.
                self.cooldowns[key] = now + 30
                self.pending.discard(key)
            if locked > old_locked:
                self.pending.discard(key)
        self.groups = groups
        self.cooldowns = {k: t for k, t in self.cooldowns.items() if k in groups}
        self.pending.intersection_update(groups)

    def candidates(self, indices, now):
        wanted, result = set(indices), []
        for key, entries in self.groups.items():
            if key in self.pending or self.cooldowns.get(key, 0) > now:
                continue
            # One request per indistinguishable group until lock readback.
            for entry in entries:
                if entry['index'] in wanted and not entry['item'].get('锁定'):
                    result.append(entry)
                    break
        return result

    def requested(self, entry):
        self.pending.add(identity(entry['item']))
