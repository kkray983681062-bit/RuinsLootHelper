"""Lock decisions must satisfy a complete rule, never just one selected field."""
import copy
import unittest

from lock_library import LockLibrary, selected_indices, rules_from_settings
from test_lock_library import CATALOG, item


class CombinedLockTests(unittest.TestCase):
    def rule(self, **extra):
        return dict(qualities=['完美'], quality_tiers=[10],
                    equipment_keys=['10:1:霄引'],
                    thresholds={'10:1:霄引': {'魔法上限': 48}}, **extra)

    def test_quality_scope_and_threshold_must_all_match(self):
        model = LockLibrary(CATALOG, self.rule())
        for candidate, wanted in ((item(), True), (item(magic=47), False),
                                  (item(quality=1), False), (item(tier=9), False),
                                  (item(name='别的装备'), False)):
            with self.subTest(candidate=candidate):
                self.assertEqual(model.matches(candidate), wanted)

    def test_selected_equipment_without_conditions_is_not_an_unconditional_lock(self):
        model = LockLibrary(CATALOG, {'equipment_keys': ['10:1:霄引']})
        self.assertFalse(model.matches(item(quality=0)))

    def test_upper_and_lower_skills_must_come_from_the_correct_location(self):
        model = LockLibrary(CATALOG, self.rule(upper=True, upper_ids=[64], lower=True, lower_ids=[11]))
        candidate = item()
        self.assertFalse(model.matches(candidate))
        candidate.update(技能1=64, 极品属性={'技能1': 11})
        self.assertTrue(model.matches(candidate))
        candidate['技能1'] = 11
        candidate['极品属性']['技能1'] = 64
        self.assertFalse(model.matches(candidate))

    def test_invalid_threshold_does_not_silently_remove_a_restriction(self):
        for value in (float('nan'), -1, True, '48'):
            config = self.rule()
            config['thresholds']['10:1:霄引']['魔法上限'] = value
            self.assertFalse(LockLibrary(CATALOG, config).matches(item()))

    def test_missing_base_value_is_not_zero_even_when_minimum_is_zero(self):
        config = self.rule()
        config['thresholds']['10:1:霄引']['魔法上限'] = 0
        candidate = item()
        candidate['基础属性'] = {}
        self.assertFalse(LockLibrary(CATALOG, config).matches(candidate))

    def test_set_and_non_set_scopes_are_actual_conditions(self):
        rows = copy.deepcopy(CATALOG)
        rows[0]['set_name'] = '测试套装'
        self.assertTrue(LockLibrary(rows, {'qualities': ['完美'], 'set_mode': 'set'}).matches(item()))
        self.assertFalse(LockLibrary(rows, {'qualities': ['完美'], 'set_mode': 'non_set'}).matches(item()))

    def test_only_explicit_additional_rules_can_accept_a_nonperfect_item(self):
        entries = [{'index': 4, 'item': item(quality=1)}, {'index': 5, 'item': item(magic=47)}]
        config = {'schema': 2, 'rules': [self.rule()]}
        self.assertEqual(selected_indices(entries, config), set())
        config['rules'].append({'equipment_keys': ['10:1:霄引'], 'thresholds': {'10:1:霄引': {'魔法上限': 48}}})
        self.assertEqual(selected_indices(entries, config), {4})

    def test_disabled_rule_does_not_protect_items(self):
        config = {'schema': 2, 'rules': [self.rule(enabled=False)]}
        self.assertEqual(selected_indices([{'index': 4, 'item': item()}], config), set())

    def test_migration_does_not_add_a_bypass_to_existing_equipment_conditions(self):
        settings = {'native': {'lock': True, 'lock_sections': {'numeric': True}}, 'lock_library': self.rule()}
        migrated = {'schema': 2, 'rules': rules_from_settings(settings)}
        entries = [{'index': 4, 'item': item(quality=1)}]
        self.assertEqual(selected_indices(entries, migrated, {'numeric': [{'index': 4}]}), set())

    def test_malformed_lists_fail_closed_instead_of_crashing_or_widening_scope(self):
        for field, value in (('qualities', 3), ('quality_tiers', [10, 'bad']), ('equipment_keys', [None])):
            rule = self.rule()
            rule[field] = value
            self.assertFalse(LockLibrary(CATALOG, rule).matches(item()))


if __name__ == '__main__':
    unittest.main()
