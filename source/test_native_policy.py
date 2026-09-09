import unittest
from native_policy import LockPolicy, identity


def item(index, locked=False, value=29):
    return {'index': index, 'item': {'名字': '测试', '锁定': locked, '格子id': index,
        '极品属性': {'特殊属性': {'法术伤害增加': value}}}}


class LockPolicyTests(unittest.TestCase):
    def test_manual_unlock_cooldown_follows_item_when_moved(self):
        p = LockPolicy()
        p.observe([item(1, True)], 0)
        p.observe([item(1, False)], 1)
        p.observe([item(47, False)], 2)
        self.assertEqual(p.candidates([47], 30), [])
        self.assertEqual([x['index'] for x in p.candidates([47], 31)], [47])

    def test_removed_item_is_forgotten_and_same_slot_is_not_identity(self):
        p = LockPolicy()
        p.observe([item(1, True)], 0)
        p.observe([item(1, False)], 1)
        p.observe([item(1, False, 40)], 2)
        self.assertEqual([x['index'] for x in p.candidates([1], 2)], [1])
        self.assertNotIn(identity(item(1)['item']), p.cooldowns)

    def test_duplicate_unlocks_conservatively_pause_identical_items_and_request_deduplicates(self):
        p = LockPolicy()
        p.observe([item(1, True), item(2)], 0)
        p.observe([item(1), item(2)], 1)
        self.assertEqual(p.candidates([1, 2], 10), [])
        candidate = p.candidates([1, 2], 31)[0]
        p.requested(candidate)
        self.assertEqual(p.candidates([1, 2], 32), [])
        p.observe([item(1, True), item(2)], 33)
        self.assertEqual([x['index'] for x in p.candidates([1, 2], 33)], [2])


class AutoLockNoticeTests(unittest.TestCase):
    def setUp(self):
        from native_policy import AutoLockNotices
        self.notices = AutoLockNotices()
        self.command = {'id': 'session:1', 'index': 1, 'identity': identity(item(1)['item'])}
        self.notices.observe([item(1)], {}, 0)
        self.notices.sent([self.command], 0)

    def confirm(self, now=1):
        self.notices.observe([item(1, True)], {'session:1': 'locked'}, now)

    def test_requires_success_ack_and_locked_readback_then_expires_without_refresh(self):
        self.notices.observe([item(1)], {'session:1': 'awaiting_readback'}, 1)
        self.assertEqual(self.notices.visible(1), {})
        self.notices.observe([item(1, True)], {}, 2)
        self.assertEqual(set(self.notices.visible(2)), {1})
        self.notices.observe([item(1, True)], {'session:1': 'locked'}, 8)
        self.assertEqual(set(self.notices.visible(11.99)), {1})
        self.assertEqual(self.notices.visible(12), {})

    def test_manual_lock_or_rejected_command_never_claims_auto_lock(self):
        for result in (None, 'already_locked', 'item_changed', 'error'):
            with self.subTest(result=result):
                self.setUp()
                self.notices.observe([item(1, True)], {} if result is None else {'session:1': result}, 1)
                self.assertEqual(self.notices.visible(1), {})

    def test_notice_follows_item_without_restarting_ten_seconds(self):
        self.confirm()
        self.notices.observe([item(47, True)], {}, 6)
        self.assertEqual(set(self.notices.visible(10.99)), {47})
        self.assertEqual(self.notices.visible(11), {})

    def test_unlock_removal_storage_or_replacement_clears_notice(self):
        for replacement in ([item(1)], [], [item(60, True)], [item(1, True, 40)]):
            with self.subTest(replacement=replacement):
                self.setUp()
                self.confirm()
                self.notices.observe(replacement, {}, 2)
                self.assertEqual(self.notices.visible(2), {})
                self.notices.observe([item(1, True)], {'session:1': 'locked'}, 3)
                self.assertEqual(self.notices.visible(3), {})

    def test_identical_prelocked_copy_is_not_newly_auto_locked(self):
        self.notices.observe([item(1), item(2, True)], {}, 0)
        self.command['id'] = 'session:2'
        self.notices.sent([self.command], 0)
        self.notices.observe([item(1, True), item(2, True)], {'session:2': 'locked'}, 1)
        self.assertEqual(set(self.notices.visible(1)), {1})


if __name__ == '__main__':unittest.main()
