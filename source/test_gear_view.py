import importlib.util
import pathlib
import unittest


class FilterTests(unittest.TestCase):
    def module(self):
        path = pathlib.Path(__file__).with_name('gear_view.py')
        self.assertTrue(path.exists(), 'Live numeric filter is not implemented yet')
        spec = importlib.util.spec_from_file_location('gear_view', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_thresholds_are_inclusive_and_any_one_can_match(self):
        m = self.module()
        item = {'名字': '法杖', '极品属性': {'特殊属性': {'法术伤害增加': 25, '暴击伤害': 39}}}
        hits = m.match_item(item, m.DEFAULT_RULES)
        self.assertEqual([(x['key'], x['value']) for x in hits], [('spell_percent', 25)])

    def test_weapon_base_attack_does_not_count_as_an_affix(self):
        m = self.module()
        item = {'名字': '武器', '基础属性': {'攻击上限': 101, '魔法上限': 125},
                '特殊属性': {'施法速度+': 80}, '极品属性': {}}
        self.assertEqual(m.match_item(item, m.DEFAULT_RULES), [])

    def test_attack_uses_the_right_hand_upper_value_and_zero_lower_is_kept(self):
        m = self.module()
        item = {'名字': '追风', '极品属性': {'基础属性': {'魔法上限': 24}}}
        hit = m.match_item(item, m.DEFAULT_RULES)[0]
        self.assertEqual((hit['key'], hit['value'], hit['display']), ('magic_attack', 24, '0–24'))

    def test_inherent_skill_and_addable_skills_stay_separate(self):
        m = self.module()
        item = {'名字': '追风', '技能1': 64, '极品属性': {'技能1': 83, '技能2': 64}}
        view = m.normalize_item({'index': 3, 'item': item})
        self.assertEqual([x['id'] for x in view['inherent_skills']], [64])
        self.assertEqual([x['id'] for x in view['addable_skills']], [83, 64])
        self.assertEqual(view['inherent_skills'][0]['name'], '冲刺无冷却')

    def test_removed_items_are_absent_from_current_match_results(self):
        m = self.module()
        first = {'items': [{'index': 0, 'item': {'名字': '项链', '极品属性': {'特殊属性': {'幸运': 4}}}}]}
        self.assertEqual(len(m.build_items(first)), 1)
        self.assertEqual(m.build_items({'items': []}), [])

    def test_t5_inherent_skills_are_independent_of_numeric_hits_and_lower_skills(self):
        m = self.module()
        self.assertTrue(hasattr(m, 'select_sections'), 'Independent T5 skill section is missing')
        data = {'items': [
            {'index': 0, 'item': {'名字': '追风', '等阶': 9, '技能1': 64}},
            {'index': 1, 'item': {'名字': '天神法杖', '等阶': 9, '极品属性': {'技能1': 64}}},
            {'index': 2, 'item': {'名字': '非T5自带', '等阶': 7, '技能1': 64}},
            {'index': 3, 'item': {'名字': '数值项链', '等阶': 7, '极品属性': {'特殊属性': {'幸运': 4}}}},
        ]}
        result = m.select_sections(data)
        self.assertEqual([x['index'] for x in result['numeric']], [3])
        self.assertEqual([x['index'] for x in result['legendary']], [0])

    def test_ten_columns_and_storage_have_distinct_coordinates(self):
        m = self.module()
        self.assertEqual(m.position(0, 10), '背包 · 第 1 行第 1 格')
        self.assertEqual(m.position(59, 10), '背包 · 第 6 行第 10 格')
        self.assertEqual(m.position(69, 10), '储物格 · 第 4 行第 1 格')

    def test_complete_catalog_preserves_user_choices_and_disables_added_rules(self):
        m = self.module()
        old = [{'key': 'spell_percent', 'group': '特殊属性', 'field': '法术伤害增加', 'enabled': False, 'min': 33}]
        rules = m.configured_rules(old)
        self.assertEqual(len(rules), 74)
        spell = next(x for x in rules if x['field'] == '法术伤害增加')
        self.assertEqual((spell['enabled'], spell['min']), (False, 33))
        physical = next(x for x in rules if x['field'] == '近战伤害增加')
        self.assertFalse(physical['enabled'])

    def test_physical_damage_percent_is_separate_from_flat_attack(self):
        m = self.module()
        rules = m.configured_rules([])
        physical = next(x for x in rules if x['field'] == '近战伤害增加')
        physical.update(enabled=True, min=29)
        item = {'基础属性': {'攻击上限': 18}, '极品属性': {'特殊属性': {'近战伤害增加': 29}}}
        hits = m.match_item(item, rules)
        self.assertEqual([(x['label'], x['display']) for x in hits], [('物理伤害', '29%')])

    def test_selected_tier_slot_pairs_do_not_cross_match(self):
        m = self.module()
        catalog = m.catalog_data()['equipment']
        chosen = []
        for tier, slot in [(8, 1), (9, 4), (8, 4), (9, 1)]:
            row = next(x for x in catalog if x['tier_raw'] == tier and x['type_id'] == slot)
            chosen.append({'index': len(chosen), 'item': {'名字': row['name'], '等阶': tier, '技能1': 64}})
        payload = {'items': chosen}
        result = m.select_sections(payload, settings={'legendary_pairs': ['8:1', '9:4']})
        self.assertEqual([x['index'] for x in result['legendary']], [0, 1])
        self.assertEqual(m.select_sections(payload, settings={'legendary_pairs': []})['legendary'], [])

    def test_t6_inherent_skill_can_be_selected_by_tier_and_slot(self):
        m = self.module()
        t6_weapon = next(x for x in m.catalog_data()['equipment']
                         if x['tier_raw'] == 10 and x['type_id'] == 1)
        payload = {'items': [
            {'index': 0, 'item': {'名字': t6_weapon['name'], '等阶': 10, '技能1': 64}},
        ]}
        self.assertEqual(
            [x['index'] for x in m.select_sections(payload, settings={'legendary_pairs': ['10:1']})['legendary']],
            [0],
        )
        self.assertEqual(m.select_sections(payload, settings={'legendary_pairs': ['9:1']})['legendary'], [])

    def test_catalog_skill_names_are_from_enum_values_not_editor_suffixes(self):
        m = self.module()
        self.assertEqual(m.skill_view(64)['name'], '冲刺无冷却')
        self.assertEqual(m.skill_view(11)['name'], '天雷伤害-10%，连续施法+1')

    def test_catalog_includes_current_official_t6_equipment(self):
        m = self.module()
        catalog = m.catalog_data()
        self.assertEqual(catalog['source_build'], '25281393')
        t6 = [row for row in catalog['equipment'] if row['tier_raw'] == 10]
        self.assertEqual(len(t6), 24)
        xiaoyin = next(row for row in t6 if row['name'] == '霄引')
        self.assertEqual(xiaoyin['base']['基础属性']['魔法上限'], 48)
        self.assertEqual(next(row for row in t6 if row['name'] == '灭世戒指')['set_name'], '灭世')
        self.assertEqual(next(row for row in t6 if row['name'] == '星陨法衣')['set_name'], '星陨')
        self.assertEqual(next(row for row in t6 if row['name'] == '冥墟头盔')['set_name'], '冥墟')

    def test_locked_gear_is_hidden_in_both_sections(self):
        m = self.module()
        item = {'名字': '追风', '等阶': 9, '技能1': 64, '锁定': True, '极品属性': {'特殊属性': {'幸运': 4}}}
        self.assertEqual(m.select_sections({'items': [{'index': 0, 'item': item}]}), {'numeric': [], 'legendary': [], 'lower': []})

    def test_legendary_prompt_only_allows_the_four_supported_types(self):
        m = self.module()
        for kind in range(11):
            item = {'type_id': kind, 'tier_raw': 9, 'inherent_skills': [{'id': 64}]}
            self.assertEqual(m.legend_allowed(item, {'legendary_pairs': [f'9:{kind}']}), kind in (1, 4, 6, 9))
        treasure = next(x for x in m.catalog_data()['equipment'] if x['type_id'] == 9)
        view = m.normalize_item({'index': 0, 'item': {'名字': treasure['name'], '等阶': treasure['tier_raw']}})
        self.assertEqual(view['type_label'], '宝物')

    def test_lower_skill_selection_filters_only_lower_results(self):
        m = self.module()
        payload = {'items': [
            {'index': 38, 'item': {'名字': '追风', '等阶': 9, '技能1': 64,
                                  '极品属性': {'技能1': 11, '技能2': 83, '特殊属性': {'幸运': 4}}}},
            {'index': 39, 'item': {'名字': '追风', '等阶': 9, '极品属性': {'技能1': 64}}},
        ]}
        chosen = m.select_sections(payload, settings={'lower_skill_ids': [11]})
        self.assertEqual([x['index'] for x in chosen['lower']], [38])
        self.assertEqual([x['id'] for x in chosen['lower'][0]['addable_skills']], [11])
        self.assertEqual([x['index'] for x in chosen['numeric']], [38])
        self.assertEqual([x['index'] for x in chosen['legendary']], [38])
        self.assertEqual(m.select_sections(payload, settings={'lower_skill_ids': []})['lower'], [])
        self.assertEqual(m.select_sections(payload, settings={'lower_enabled': False})['lower'], [])
        self.assertEqual(len(m.select_sections(payload)['lower']), 2)

    def test_lower_skills_are_independent_and_keep_inventory_position(self):
        m = self.module()
        payload = {'items': [
            {'index': 38, 'item': {'名字': '疾风戒指', '等阶': 5, '极品属性': {'技能1': 83, '技能3': 64}}},
            {'index': 15, 'item': {'名字': '追风', '等阶': 9, '技能1': 64}},
            {'index': 20, 'item': {'名字': '追风', '等阶': 9, '锁定': True, '极品属性': {'技能1': 83}}},
            {'index': 61, 'item': {'名字': '追风', '等阶': 9, '极品属性': {'技能1': 83}}},
        ]}
        result = m.select_sections(payload, settings={'legendary_pairs': []})
        self.assertEqual(result['legendary'], [])
        self.assertEqual([x['index'] for x in result['lower']], [38])
        self.assertEqual([x['id'] for x in result['lower'][0]['addable_skills']], [83, 64])
        self.assertEqual(m.position(result['lower'][0]['index'], 10), '背包 · 第 4 行第 9 格')
        self.assertEqual(m.select_sections({'items': []})['lower'], [])


if __name__ == '__main__':
    unittest.main()
