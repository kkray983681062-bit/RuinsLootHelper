"""Complete lock rules: AND within a rule, OR only between explicit rules."""
import copy
from functools import lru_cache
import math

from gear_view import catalog_data
from pickup_library import equipment_key


QUALITY_LABELS = ("陈旧", "普通", "精良", "完美")
QUALITY_BY_VALUE = {0: "陈旧", 1: "普通", 2: "精良", 3: "完美"}


def _number(value):
    return (type(value) in (int, float) and not isinstance(value, bool)
            and math.isfinite(value))


def _quality(value):
    if type(value) is int:
        return QUALITY_BY_VALUE.get(value)
    if isinstance(value, str):
        value = value.strip()
        return value if value in QUALITY_LABELS else None
    return None


def _base_fields(row):
    base = row.get("base")
    if not isinstance(base, dict):
        return {}
    fields = base.get("基础属性")
    return fields if isinstance(fields, dict) else {}


def _item_base(item):
    direct = item.get("基础属性")
    if isinstance(direct, dict):
        return direct
    equipment = item.get("装备属性")
    if isinstance(equipment, dict):
        nested = equipment.get("基础属性")
        if isinstance(nested, dict):
            return nested
    return {}


def _build_index(rows):
    by_key, by_name_tier, ambiguous = {}, {}, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name, tier = row.get("name"), row.get("tier_raw")
        if not isinstance(name, str) or not name or type(tier) is not int:
            continue
        try:
            key = equipment_key(row)
        except (KeyError, TypeError, ValueError):
            continue
        by_key.setdefault(key, row)
        identity = (name, tier)
        previous = by_name_tier.get(identity)
        if previous is None:
            by_name_tier[identity] = key
        elif previous != key:
            ambiguous.add(identity)
    for identity in ambiguous:
        by_name_tier.pop(identity, None)
    return by_key, by_name_tier


@lru_cache(maxsize=1)
def _catalog_index():
    return _build_index(catalog_data().get("equipment", ()))


class LockLibrary:
    """One rule. Selecting equipment only narrows its scope."""
    def __init__(self, rows, config=None, index=None):
        self.rows, self.by_name_tier = index or _build_index(rows)
        config = config if isinstance(config, dict) else {}
        self.valid = True
        self.enabled = config.get('enabled', True) is True
        self.keep_all = config.get('keep_all', False) is True
        self.set_mode = config.get('set_mode', 'all')
        if self.set_mode not in ('all', 'set', 'non_set'):
            self.valid = False
        self.upper = config.get('upper', False) is True
        self.lower = config.get('lower', False) is True
        self.upper_ids = self._ids(config.get('upper_ids', []))
        self.lower_ids = self._ids(config.get('lower_ids', []))
        self.numeric = config.get('numeric', False) is True
        self.filter_sections = config.get('filter_sections', [])
        if (not isinstance(self.filter_sections, list)
                or any(key not in ('numeric', 'legendary', 'lower') for key in self.filter_sections)):
            self.valid = False
            self.filter_sections = []
        qualities = config.get("qualities", ())
        self.qualities = frozenset(value for value in qualities if isinstance(value, str) and value in QUALITY_LABELS) \
            if isinstance(qualities, (list, tuple, set)) else frozenset()
        if qualities and (not self.qualities or len(self.qualities) != len(set(map(str, qualities)))):
            self.valid = False
        quality_tiers = config.get("quality_tiers", ())
        self.quality_tiers = frozenset(value for value in quality_tiers
                                       if type(value) is int and 0 <= value <= 99) \
            if isinstance(quality_tiers, (list, tuple, set)) else frozenset()
        if quality_tiers and (not isinstance(quality_tiers, (list, tuple, set))
                              or any(type(value) is not int or not 0 <= value <= 99 for value in quality_tiers)):
            self.valid = False
        keys = config.get("equipment_keys", ())
        self.equipment_keys = frozenset(value for value in keys if isinstance(value, str)) \
            if isinstance(keys, (list, tuple, set)) else frozenset()
        if keys and (not isinstance(keys, (list, tuple, set)) or any(not isinstance(value, str) for value in keys)):
            self.valid = False
        self.thresholds = self._thresholds(config.get("thresholds", {}))

    def _ids(self, values):
        if not isinstance(values, (list, tuple)) or any(type(v) is not int or v <= 0 for v in values):
            self.valid = False
            return ()
        return tuple(values)

    def _thresholds(self, raw):
        if not isinstance(raw, dict):
            self.valid = False
            return {}
        result = {}
        for key, fields in raw.items():
            row = self.rows.get(key)
            if not isinstance(key, str) or row is None or not isinstance(fields, dict):
                self.valid = False
                continue
            allowed = _base_fields(row)
            values = {field: value for field, value in fields.items()
                      if isinstance(field, str) and field in allowed and _number(value)
                      and 0 <= value <= 100000}
            if values:
                result[key] = values
            if len(values) != len(fields):
                self.valid = False
        return result

    def key_for_item(self, item):
        if not isinstance(item, dict):
            return None
        name, tier = item.get("名字", item.get("名称")), item.get("等阶")
        if not isinstance(name, str) or type(tier) is not int:
            return None
        return self.by_name_tier.get((name, tier))

    def reasons(self, item, filter_hits=()):
        if not self.enabled or not self.valid or not isinstance(item, dict):
            return ()
        reasons = []
        quality = _quality(item.get("品质"))
        item_tier = item.get("等阶")
        if self.quality_tiers and (type(item_tier) is not int or item_tier not in self.quality_tiers):
            return ()
        if self.qualities:
            if quality not in self.qualities:
                return ()
            reasons.append("quality")
        key = self.key_for_item(item)
        if self.equipment_keys and key not in self.equipment_keys:
            return ()
        row = self.rows.get(key)
        if self.set_mode != 'all':
            if row is None or bool(row.get('set_name')) != (self.set_mode == 'set'):
                return ()
        if self.thresholds and not self.equipment_keys and key not in self.thresholds:
            return ()
        required = self.thresholds.get(key)
        actual = _item_base(item)
        if required:
            if not all(_number(actual.get(field)) and actual[field] >= minimum for field, minimum in required.items()):
                return ()
            reasons.append("threshold")
        for position, needed, selected in (('upper', self.upper, self.upper_ids), ('lower', self.lower, self.lower_ids)):
            if not needed:
                continue
            source = item if position == 'upper' else item.get('极品属性', {})
            fields = ('技能1',) if position == 'upper' else ('技能1', '技能2', '技能3')
            skills = [source.get(field) for field in fields] if isinstance(source, dict) else []
            if not any(type(value) is int and value > 0 and (not selected or value in selected) for value in skills):
                return ()
            reasons.append(position)
        needed_filters = set(self.filter_sections) | ({'numeric'} if self.numeric else set())
        if not needed_filters <= set(filter_hits):
            return ()
        reasons.extend(sorted(needed_filters))
        if self.keep_all:
            reasons.append('explicit_all')
        return tuple(reasons)

    def matches(self, item):
        return bool(self.reasons(item))


def rules_from_settings(settings):
    """Make older lock routes visible as named rules without changing saved files."""
    saved = settings.get('lock_library', {})
    saved = saved if isinstance(saved, dict) else {}
    if saved.get('schema') == 2:
        rules = saved.get('rules', [])
        return copy.deepcopy(rules) if isinstance(rules, list) else []
    result = []
    if any(saved.get(key) for key in ('qualities', 'equipment_keys', 'thresholds')):
        result.append(dict(copy.deepcopy(saved), name='原有装备保留'))
        # Existing equipment restrictions form one complete rule. Do not create
        # extra legacy filter routes that bypass its quality or numeric gates.
        return result
    native = settings.get('native', {})
    if isinstance(native, dict) and native.get('lock'):
        selected = native.get('lock_sections', {'numeric': True})
        for key, title in (('numeric', '原有词条保留'), ('legendary', '原有上技能保留'), ('lower', '原有下技能保留')):
            if selected.get(key, False):
                result.append({'name': title, 'filter_sections': [key]})
    return result


def selected_indices(entries, config, sections=None):
    """Return inventory slots protected by the additional library rules."""
    if not isinstance(entries, list) or not isinstance(config, dict):
        return set()
    rows, names = _catalog_index()
    raw_rules = config.get('rules', []) if config.get('schema') == 2 else [config]
    if not isinstance(raw_rules, list):
        return set()
    libraries = [LockLibrary((), rule, index=(rows, names)) for rule in raw_rules if isinstance(rule, dict)]
    filter_indices = {name: {entry.get('index') for entry in entries if isinstance(entry, dict)}
                      for name, entries in (sections or {}).items()}
    result = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index, item = entry.get("index"), entry.get("item")
        if type(index) is not int or not 0 <= index < 60 or not isinstance(item, dict):
            continue
        kind = item.get("物品类型")
        if kind is not None and kind != 1:
            continue
        hits = {name for name, indices in filter_indices.items() if index in indices}
        if any(library.reasons(item, hits) for library in libraries):
            result.add(index)
    return result
