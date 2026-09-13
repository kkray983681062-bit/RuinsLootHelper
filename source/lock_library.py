"""Independent quality, equipment-library, and per-equipment auto-lock rules."""
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
    """A normalized rule set; each source is an independent reason to lock."""
    def __init__(self, rows, config=None, index=None):
        self.rows, self.by_name_tier = index or _build_index(rows)
        config = config if isinstance(config, dict) else {}
        qualities = config.get("qualities", ())
        self.qualities = frozenset(value for value in qualities if value in QUALITY_LABELS) \
            if isinstance(qualities, (list, tuple, set)) else frozenset()
        known_tiers = {row["tier_raw"] for row in self.rows.values()}
        quality_tiers = config.get("quality_tiers", ())
        self.quality_tiers = frozenset(value for value in quality_tiers
                                       if type(value) is int and value in known_tiers) \
            if isinstance(quality_tiers, (list, tuple, set)) else frozenset()
        keys = config.get("equipment_keys", ())
        self.equipment_keys = frozenset(value for value in keys if isinstance(value, str) and value in self.rows) \
            if isinstance(keys, (list, tuple, set)) else frozenset()
        self.thresholds = self._thresholds(config.get("thresholds", {}))

    def _thresholds(self, raw):
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, fields in raw.items():
            row = self.rows.get(key)
            if not isinstance(key, str) or row is None or not isinstance(fields, dict):
                continue
            allowed = _base_fields(row)
            values = {field: value for field, value in fields.items()
                      if isinstance(field, str) and field in allowed and _number(value)
                      and 0 <= value <= 100000}
            if values:
                result[key] = values
        return result

    def key_for_item(self, item):
        if not isinstance(item, dict):
            return None
        name, tier = item.get("名字", item.get("名称")), item.get("等阶")
        if not isinstance(name, str) or type(tier) is not int:
            return None
        return self.by_name_tier.get((name, tier))

    def reasons(self, item):
        key = self.key_for_item(item)
        if key is None:
            return ()
        row = self.rows[key]
        reasons = []
        quality = _quality(item.get("品质"))
        if quality in self.qualities and (not self.quality_tiers or row["tier_raw"] in self.quality_tiers):
            reasons.append("quality")
        if key in self.equipment_keys:
            reasons.append("equipment")
        required = self.thresholds.get(key)
        actual = _item_base(item)
        if required and all(_number(actual.get(field)) and actual[field] >= minimum
                            for field, minimum in required.items()):
            reasons.append("threshold")
        return tuple(reasons)

    def matches(self, item):
        return bool(self.reasons(item))


def selected_indices(entries, config):
    """Return inventory slots protected by the additional library rules."""
    if not isinstance(entries, list) or not isinstance(config, dict):
        return set()
    rows, names = _catalog_index()
    library = LockLibrary((), config, index=(rows, names))
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
        if library.matches(item):
            result.add(index)
    return result
