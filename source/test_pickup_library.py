import unittest
from pickup_library import EquipmentLibrary, equipment_key


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            dict(name='追风', label='追风', tier_raw=9, tier='T5', type_id=1, type_label='武器'),
            dict(name='追风', label='追风', tier_raw=8, tier='T4', type_id=1, type_label='武器'),
            dict(name='生命树叶', label='生命树叶', tier_raw=9, tier='T5', type_id=9, type_label='法宝')]
        self.library = EquipmentLibrary(self.rows)

    def test_search_tier_and_slot_filters_combine_without_losing_other_selections(self):
        self.library.toggle(equipment_key(self.rows[2]))
        result = self.library.find('追风', tier=9, type_id=1)
        self.assertEqual([row['tier'] for row in result], ['T5'])
        self.library.set_rows(result, True)
        self.assertEqual(len(self.library.selected), 2)
        self.library.set_rows(self.library.find('t4 武器'), False)
        self.assertIn(equipment_key(self.rows[2]), self.library.selected)
        self.assertEqual(len(self.library.find(only_selected=True)), 2)
        self.assertEqual(self.library.find('宝物')[0]['name'], '生命树叶')

    def test_duplicate_catalog_rows_and_saved_keys_round_trip_without_name_collision(self):
        selected = [equipment_key(self.rows[0]), '9:1:新版本装备']
        library = EquipmentLibrary(self.rows + [self.rows[0]], selected)
        self.assertEqual(len(library.rows), 3)
        self.assertNotIn(equipment_key(self.rows[1]), library.selected)
        self.assertEqual(library.values(), sorted(selected))
        library.toggle(equipment_key(self.rows[0]))
        self.assertEqual(library.values(), ['9:1:新版本装备'])

    def test_actual_catalog_has_consistent_unique_equipment_keys(self):
        from gear_view import catalog_data
        library = EquipmentLibrary(catalog_data()['equipment'])
        self.assertGreater(len(library.rows), 400)
        result = library.find('追风', tier=9, type_id=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['key'], '9:1:追风')

    def test_current_t6_set_members_are_grouped_and_filterable(self):
        from gear_view import catalog_data
        library = EquipmentLibrary(catalog_data()['equipment'])
        result = library.find(tier=10, set_name='灭世')
        self.assertEqual({row['name'] for row in result}, {
            '灭世甲', '灭世头盔', '灭世项链', '灭世手镯', '灭世戒指', '灭世腰带', '灭世靴',
        })
        self.assertEqual({row['set_name'] for row in result}, {'灭世'})

    def test_codex_selection_is_searchable_and_kept_separate_from_equipment(self):
        from pickup_library import ExclusionLibrary, codex_selection
        library = ExclusionLibrary(self.rows, ['9:1:追风'])
        self.assertEqual(len(library.find(category='图鉴')), 63)
        self.assertEqual(len(library.codex_values()), 63)
        self.assertEqual(library.equipment_values(), ['9:1:追风'])
        library.toggle('codex:人形地魔')
        self.assertNotIn('人形地魔', library.codex_values())
        matches = library.find('人形', category='图鉴')
        self.assertEqual([r['label'] for r in matches], ['人形地魔图鉴'])
        saved = {'codex_exclusions': library.codex_values()}
        self.assertEqual(len(codex_selection(saved)), 62)
        library.set_rows(library.find(category='图鉴'), False)
        self.assertEqual(library.codex_values(), [])
        self.assertEqual(library.equipment_values(), ['9:1:追风'])
        self.assertEqual(codex_selection({'codex_exclusions': []}), frozenset())
        self.assertEqual(codex_selection({}), frozenset())
        self.assertEqual(len(codex_selection({'native': {'skip_codex': True}})), 63)

    def test_old_disabled_switch_migrates_to_no_selection_and_new_rows_are_authoritative(self):
        from pickup_library import codex_selection
        settings = {'native': {'skip_codex': False}, 'codex_exclusions': ['人形地魔']}
        self.assertEqual(codex_selection(settings), frozenset())
        settings['codex_selection_version'] = 1
        self.assertEqual(codex_selection(settings), {'人形地魔'})


if __name__ == '__main__':
    unittest.main()
