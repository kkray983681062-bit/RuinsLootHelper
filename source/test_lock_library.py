import unittest

from lock_library import LockLibrary


CATALOG = [
    {
        "name": "霄引",
        "label": "霄引",
        "tier_raw": 10,
        "tier": "T6",
        "type_id": 1,
        "type_label": "武器",
        "base": {"基础属性": {"攻击上限": 45, "魔法上限": 48}},
    },
    {
        "name": "追风",
        "label": "追风",
        "tier_raw": 9,
        "tier": "T5",
        "type_id": 1,
        "type_label": "武器",
        "base": {"基础属性": {"攻击上限": 101, "魔法上限": 125}},
    },
]


def item(name="霄引", tier=10, quality=3, attack=45, magic=48):
    return {
        "物品类型": 1,
        "名字": name,
        "等阶": tier,
        "品质": quality,
        "基础属性": {"攻击上限": attack, "魔法上限": magic},
    }


class LockLibraryTests(unittest.TestCase):
    def test_quality_can_be_limited_to_t6(self):
        rules = LockLibrary(CATALOG, {"qualities": ["完美"], "quality_tiers": [10]})
        self.assertTrue(rules.matches(item()))
        self.assertFalse(rules.matches(item(tier=9)))
        self.assertFalse(rules.matches(item(quality=2)))

    def test_quality_rule_locks_unlisted_current_t6_equipment(self):
        rules = LockLibrary(CATALOG, {"qualities": ["完美"], "quality_tiers": [10]})
        for quality in (3, "完美"):
            with self.subTest(quality=quality):
                current_item = item(name="新版T6套装", tier=10, quality=quality)
                self.assertEqual(rules.reasons(current_item), ("quality",))
                self.assertTrue(rules.matches(current_item))
        self.assertFalse(rules.matches(item(name="新版T6套装", tier=9, quality=3)))

    def test_bad_item_tier_does_not_break_quality_locking(self):
        rules = LockLibrary(CATALOG, {"qualities": ["完美"], "quality_tiers": [10]})
        self.assertFalse(rules.matches(item(tier=[])))

    def test_unconditional_equipment_lock_requires_an_explicit_option(self):
        rules = LockLibrary(CATALOG, {"equipment_keys": ["9:1:追风"], "keep_all": True})
        self.assertTrue(rules.matches(item(name="追风", tier=9, quality=0)))

    def test_all_filled_thresholds_for_one_item_are_required(self):
        rules = LockLibrary(
            CATALOG,
            {"thresholds": {"10:1:霄引": {"攻击上限": 45, "魔法上限": 48}}},
        )
        self.assertTrue(rules.matches(item(attack=45, magic=48)))
        self.assertFalse(rules.matches(item(attack=46, magic=47)))

    def test_bad_or_unknown_configuration_never_matches(self):
        rules = LockLibrary(
            CATALOG,
            {
                "qualities": ["未知"],
                "equipment_keys": ["not-a-real-row"],
                "thresholds": {"10:1:霄引": {"不存在": 1, "魔法上限": -1}},
            },
        )
        self.assertFalse(rules.matches(item()))


if __name__ == "__main__":
    unittest.main()
