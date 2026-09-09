"""Current inventory must forget removed equipment and retain real duplicates."""
import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).with_name("loot_current.py")


class CurrentInventoryTests(unittest.TestCase):
    def inventory(self):
        self.assertTrue(MODULE.exists(), "Current-only inventory has not been implemented")
        spec = importlib.util.spec_from_file_location("loot_current", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.CurrentInventory()

    @staticmethod
    def item(name="冰锥法杖", locked=False):
        return {"名字": name, "锁定": locked,
                "极品属性": {"特殊属性": {"幸运": 2, "生命汲取": 2}}}

    def test_removed_equipment_and_its_attributes_disappear(self):
        state = self.inventory()
        state.replace({0: self.item()})
        self.assertEqual(state.export()[0]["item"]["名字"], "冰锥法杖")
        state.replace({})
        self.assertEqual(state.export(), [])

    def test_sorting_updates_slots_without_duplicating_equipment(self):
        state = self.inventory()
        state.replace({0: self.item()})
        state.replace({10: self.item(locked=True)})
        self.assertEqual(state.export(), [{"index": 10, "item": self.item(locked=True)}])

    def test_two_identical_items_remain_two_items_until_one_is_removed(self):
        state = self.inventory()
        state.replace({0: self.item(), 1: self.item()})
        self.assertEqual(len(state.export()), 2)
        state.replace({1: self.item()})
        self.assertEqual(state.export(), [{"index": 1, "item": self.item()}])

    def test_unreadable_inventory_clears_previous_attributes(self):
        state = self.inventory()
        state.replace({0: self.item()})
        state.clear()
        self.assertEqual(state.export(), [])

    def test_materials_books_and_locked_gear_occupy_slots_but_storage_does_not(self):
        spec = importlib.util.spec_from_file_location('loot_current', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        slots = [{} for _ in range(72)]
        slots[0] = {'物品类型': 1, '锁定': True}
        slots[3] = {'物品类型': 2, '名字': '材料'}
        slots[5] = {'物品类型': 3, '名字': '技能书'}
        slots[60] = {'物品类型': 1}
        self.assertEqual(module.occupied_main_slots(slots), [0, 3, 5])
        slots[3] = {'物品类型': 0, '名字': '已清空'}
        self.assertEqual(module.occupied_main_slots(slots), [0, 5])


if __name__ == "__main__":
    unittest.main()
