"""Searchable, tier-specific pickup exclusions from the local game catalog."""
from functools import lru_cache
import json
from pathlib import Path

RANGE_OPTIONS = (1.0, 1.5, 2.0)
INTERVAL_OPTIONS = (1.0, .5, .35, .15)
BATCH_OPTIONS = (0, 1, 2, 3, 4)  # 0: automatically yield by elapsed work time.


def pickup_options(config):
    def choice(name, allowed, default):
        value = config.get(name)
        return value if type(value) in (int, float) and value in allowed else default
    return {'pickup_range_multiplier': choice('pickup_range_multiplier', RANGE_OPTIONS, 2.0),
            'pickup_interval': choice('pickup_interval', INTERVAL_OPTIONS, .35),
            'pickup_batch': int(choice('pickup_batch', BATCH_OPTIONS, 0))}


@lru_cache(maxsize=1)
def codex_items():
    catalog = json.loads((Path(__file__).with_name('catalog') / 'codex-items.json').read_text(encoding='utf8'))
    return tuple(row for row in catalog['items'] if row['kind'] == 3)


@lru_cache(maxsize=1)
def codex_names():
    return frozenset(row['name'] for row in codex_items())


def codex_selection(settings):
    if settings.get('codex_selection_version') != 1 and settings.get('native', {}).get('skip_codex') is False:
        return frozenset()
    selected = settings.get('codex_exclusions')
    if isinstance(selected, list):
        return frozenset(name for name in selected if isinstance(name, str) and name)
    return codex_names() if settings.get('native', {}).get('skip_codex', False) else frozenset()


def equipment_key(row):
    return f"{int(row['tier_raw'])}:{int(row['type_id'])}:{row['name']}"


class EquipmentLibrary:
    def __init__(self, rows, selected=()):
        unique = {}
        for source in rows:
            row = {k: source[k] for k in ('name', 'label', 'tier_raw', 'tier', 'type_id', 'type_label')}
            set_name = source.get('set_name')
            if isinstance(set_name, str) and set_name:
                row['set_name'] = set_name
            if row['type_id'] == 9:
                row['type_label'] = '宝物'
            row['key'] = equipment_key(row)
            unique.setdefault(row['key'], row)
        self.rows = sorted(unique.values(), key=lambda r: (-r['tier_raw'], r['type_id'], r['label']))
        selected = selected if isinstance(selected, (list, tuple, set)) else ()
        self.selected = {value for value in selected if isinstance(value, str)}

    def find(self, query='', tier=None, type_id=None, only_selected=False, set_name=None):
        words = query.strip().casefold().split()
        def matches_set(row):
            if set_name is None:
                return True
            if set_name is True:
                return bool(row.get('set_name'))
            if set_name is False:
                return not row.get('set_name')
            return row.get('set_name') == set_name
        return [r for r in self.rows
                if (tier is None or r['tier_raw'] == tier)
                and (type_id is None or r['type_id'] == type_id)
                and (not only_selected or r['key'] in self.selected)
                and matches_set(r)
                and all(word in f"{r['label']} {r['name']} {r['tier']} {r['type_label']} {r.get('set_name', '')}".casefold()
                        for word in words)]

    def toggle(self, key):
        if key in self.selected:
            self.selected.remove(key)
        else:
            self.selected.add(key)

    def set_rows(self, rows, excluded):
        keys = {r['key'] for r in rows}
        if excluded:
            self.selected.update(keys)
        else:
            self.selected.difference_update(keys)

    def values(self):
        return sorted(self.selected)


class ExclusionLibrary(EquipmentLibrary):
    """Equipment and codex choices share a view, but use distinct saved keys."""
    def __init__(self, rows, selected=(), codex_selected=None):
        super().__init__(rows, selected)
        for row in self.rows:
            row['category'] = '装备'
        for item in codex_items():
            self.rows.append({'name': item['name'], 'label': item['label'],
                'tier_raw': 0, 'tier': '—', 'type_id': 0, 'type_label': '图鉴',
                'category': '图鉴', 'key': 'codex:' + item['name']})
        names = codex_names() if codex_selected is None else codex_selected
        self.selected.update('codex:' + name for name in names)

    def find(self, query='', tier=None, type_id=None, only_selected=False, category='全部类型'):
        if category == '图鉴':
            tier, type_id = None, None
        return [row for row in super().find(query, tier, type_id, only_selected)
                if category == '全部类型' or row['category'] == category]

    def equipment_values(self):
        return sorted(key for key in self.selected if not key.startswith('codex:'))

    def codex_values(self):
        return sorted(key[len('codex:'):] for key in self.selected if key.startswith('codex:'))
