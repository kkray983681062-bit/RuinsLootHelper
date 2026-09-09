"""User-selected affix filters. Skills above/below the divider never merge."""
import copy
import json
import pathlib
import time


DEFAULT_RULES = [
    {'key': 'spell_percent', 'label': '法术伤害', 'group': '特殊属性', 'field': '法术伤害增加', 'min': 25, 'unit': '%'},
    {'key': 'crit_damage', 'label': '暴击伤害', 'group': '特殊属性', 'field': '暴击伤害', 'min': 40, 'unit': '%'},
    {'key': 'magic_attack', 'label': '魔法攻击', 'group': '基础属性', 'field': '魔法上限', 'lower_field': '魔法下限', 'min': 21, 'unit': ''},
    {'key': 'physical_attack', 'label': '物理攻击', 'group': '基础属性', 'field': '攻击上限', 'lower_field': '攻击下限', 'min': 21, 'unit': ''},
    {'key': 'spirit_attack', 'label': '精神攻击', 'group': '基础属性', 'field': '精神上限', 'lower_field': '精神下限', 'min': 21, 'unit': ''},
    {'key': 'cast_speed', 'label': '施法速度', 'group': '特殊属性', 'field': '施法速度+', 'min': 43, 'unit': '%'},
    {'key': 'drop_rate', 'label': '掉落率', 'group': '特殊属性', 'field': '掉落率+', 'min': 25, 'unit': '%'},
    {'key': 'rare_rate', 'label': '掉落极品率', 'group': '特殊属性', 'field': '极品率+', 'min': 25, 'unit': '%'},
    {'key': 'luck', 'label': '幸运', 'group': '特殊属性', 'field': '幸运', 'min': 4, 'unit': ''},
    {'key': 'damage_reduction', 'label': '伤害减免增加', 'group': '特殊属性', 'field': '伤害减免增加', 'min': 11, 'unit': '%'},
    {'key': 'all_resistance', 'label': '全抗性', 'group': '特殊属性', 'field': '全抗性', 'min': 47, 'unit': '%'},
]

# Correlated with the user's screenshot and live item, not guessed from IDs.
KNOWN_SKILLS = {64: '冲刺无冷却'}
_skill_cache = {'next_check': 0, 'names': dict(KNOWN_SKILLS)}
_catalog = None
_equipment_index = None
LEGENDARY_TYPES = {1: '武器', 4: '项链', 6: '戒指', 9: '宝物'}


def catalog_data():
    global _catalog
    if _catalog is None:
        path = pathlib.Path(__file__).with_name('catalog') / 'filter-catalog.json'
        _catalog = json.loads(path.read_text(encoding='utf-8'))
    return _catalog


def configured_rules(saved=None):
    """Migrate old filters by their actual field; newly discovered fields stay off."""
    defaults = {(x['group'], x['field']): x for x in DEFAULT_RULES}
    previous = {(x['group'], x['field']): x for x in (DEFAULT_RULES if saved is None else saved)}
    result = []
    for source in catalog_data()['affixes']:
        rule = copy.deepcopy(source)
        pair = (rule['group'], rule['field'])
        if pair in defaults:
            rule['key'] = defaults[pair]['key']
            rule['min'] = defaults[pair]['min']
        if pair in previous:
            rule.update(min=previous[pair]['min'], enabled=previous[pair].get('enabled', True))
        result.append(rule)
    return result


def equipment_info(name, tier):
    global _equipment_index
    if _equipment_index is None:
        _equipment_index = {}
        for row in catalog_data()['equipment']:
            key = (row['name'], row['tier_raw'])
            if key in _equipment_index:
                assert _equipment_index[key]['type_id'] == row['type_id'], key
            _equipment_index[key] = row
    return _equipment_index.get((name, tier), {})


def legend_allowed(item, settings):
    if not settings.get('legendary_enabled', True) or not item['inherent_skills']:
        return False
    if item['type_id'] not in LEGENDARY_TYPES:
        return False
    pairs = settings.get('legendary_pairs')
    if pairs is None:
        return item['tier_raw'] == 9
    return f"{item['tier_raw']}:{item['type_id']}" in pairs


def skill_view(value):
    if time.monotonic() >= _skill_cache['next_check']:
        _skill_cache['next_check'] = time.monotonic() + 2
        source = pathlib.Path(__file__).with_name('catalog') / 'skill-names.json'
        if source.exists():
            _skill_cache['names'].update({int(k): v for k, v in json.loads(source.read_text(encoding='utf-8')).items()})
    value = int(value)
    names = _skill_cache['names']
    return {'id': value, 'name': names.get(value, f'技能 {value}（名称待核对）'), 'name_verified': value in names}


def match_item(item, rules=None):
    bonus = item.get('极品属性', {})
    hits = []
    for rule in DEFAULT_RULES if rules is None else rules:
        if not rule.get('enabled', True):
            continue
        fields = bonus.get(rule['group'], {})
        if rule['field'] not in fields:
            continue
        value = fields[rule['field']]
        if value >= rule['min']:
            shown = f"{fields.get(rule['lower_field'], 0):g}–{value:g}" if 'lower_field' in rule else f'{value:g}'
            hits.append({'key': rule['key'], 'label': rule['label'], 'value': value,
                         'minimum': rule['min'], 'display': shown + rule['unit']})
    return hits


def normalize_item(entry, rules=None):
    item = entry['item']
    bonus = item.get('极品属性', {})
    inherent = [skill_view(item['技能1'])] if item.get('技能1') else []
    addable = [skill_view(bonus[key]) for key in ('技能1', '技能2', '技能3') if bonus.get(key)]
    name = item.get('名字', item.get('名称', '未识别装备'))
    tier = item.get('等阶', 0)
    equipment = equipment_info(name, tier)
    return {'index': entry['index'], 'name': name, 'quality': item.get('品质'),
            'tier_raw': tier, 'tier_label': equipment.get('tier', f'T{tier - 4}' if 5 <= tier <= 9 else '其他'),
            'type_id': equipment.get('type_id'),
            'type_label': LEGENDARY_TYPES.get(equipment.get('type_id'), equipment.get('type_label', '部位待识别')),
            'locked': bool(item.get('锁定')),
            'inherent_skills': inherent, 'addable_skills': addable,
            'hits': match_item(item, rules), 'item': copy.deepcopy(item)}


def build_items(payload, rules=None):
    return [normalize_item(entry, rules) for entry in payload.get('items', [])]


def select_sections(payload, rules=None, settings=None):
    settings = settings or {}
    items = [item for item in build_items(payload, rules)
             if (settings.get('include_locked', False) or not item['locked'])
             and (settings.get('include_storage', False) or item['index'] < 60)]
    items.sort(key=lambda x: (x['locked'], x['index']))
    lower = []
    if settings.get('lower_enabled', True):
        selected = settings.get('lower_skill_ids')
        for item in items:
            skills = [skill for skill in item['addable_skills'] if selected is None or skill['id'] in selected]
            if skills:
                lower.append(dict(item, addable_skills=skills))
    return {'numeric': [x for x in items if x['hits']],
            'legendary': [x for x in items if legend_allowed(x, settings)],
            'lower': lower}


def position(index, columns=None):
    if index >= 60:
        return f'储物格 · 第 {(index - 60) // 3 + 1} 行第 {(index - 60) % 3 + 1} 格'
    if not columns:
        return f'背包第 {index + 1} 格 · 行列待校准'
    return f'背包 · 第 {index // columns + 1} 行第 {index % columns + 1} 格'
