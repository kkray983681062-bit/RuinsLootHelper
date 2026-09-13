import time
import unittest
from unittest.mock import patch

from native_client import NativeClient, PROTOCOL, expected_fields
from overlay_feed import Snapshot


SCHEMA = {'pid': 123, 'types': {'简化物品属性': [
    {'name': name, 'kind': 'IntProperty'} for name in ('物品类型', 'ID', '数量', '难度', '品质')]}}


class NativeClientTests(unittest.TestCase):
    def setUp(self):
        self.client = NativeClient()
        self.patches = [patch('loot_overlay.find_game', return_value=1),
                        patch('overlay_markers.game_bounds', return_value=(0, 0, 1000, 800)),
                        patch('overlay_markers.foreground_matches', return_value=True),
                        patch('overlay_markers.u.IsWindow', return_value=True)]
        for p in self.patches:p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def snapshot(self, index=4, locked=False):
        return Snapshot(status={'game_pid': 123}, live=True,
            current={'items': [{'index': index, 'item': {'物品类型': 1, 'ID': 13, '锁定': locked}}]},
            ui={'ui': {'valid': True, 'player_address': 999}},
            settings={'native': {'lock': True, 'skip_codex': True}}, sections={'numeric': [{'index': index}]})

    def send(self, snapshot, native=None):
        self.client.next_send = 0
        if native is None:
            native = {'protocol': PROTOCOL, 'ready': True, 'utc': time.time(), 'session': self.client.session,
                      'player_address': 999, 'game_pid': 123}
        return self.client.update(snapshot, SCHEMA, native)

    def test_moved_item_can_be_requested_at_new_slot(self):
        self.send(self.snapshot())
        first = self.send(self.snapshot())['locks'][0]
        new = self.send(self.snapshot(20))['locks']
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['index'], 20)
        self.assertNotEqual(first['id'], new[0]['id'])

    def test_ack_error_can_retry_after_backoff_and_manual_unlock_cools_down(self):
        self.send(self.snapshot())
        command = self.send(self.snapshot())['locks'][0]
        state = {'protocol': PROTOCOL, 'ready': True, 'utc': time.time(), 'session': self.client.session,
                 'player_address': 999, 'game_pid': 123,
                 'acks': [{'id': command['id'], 'result': 'item_changed'}]}
        self.assertEqual(self.send(self.snapshot(), state)['locks'], [])
        self.send(self.snapshot(locked=True))
        self.assertEqual(self.send(self.snapshot())['locks'], [])

    def test_malformed_future_or_wrong_pid_status_never_queues_lock(self):
        self.send(self.snapshot())
        for state in ({'utc': 'broken', 'acks': [None]},
                      {'utc': time.time()+30}, {'utc': time.time(), 'game_pid': 888}):
            state = dict(ready=True, session=self.client.session, player_address=999, **state)
            self.assertEqual(self.send(self.snapshot(), state)['locks'], [])

    def test_identity_includes_zero_default_fields(self):
        actual = expected_fields({'物品类型': 1, 'ID': 13}, SCHEMA)
        self.assertEqual(len(actual), 5)
        self.assertEqual(actual[-1]['value'], 0)

    def test_auto_lock_notice_uses_sent_command_ack_and_current_readback(self):
        self.send(self.snapshot())
        command = self.send(self.snapshot())['locks'][0]
        state = {'protocol': PROTOCOL, 'ready': True, 'utc': time.time(), 'session': self.client.session,
                 'player_address': 999, 'game_pid': 123,
                 'acks': [{'id': command['id'], 'result': 'locked'}]}
        now = time.monotonic()
        with patch('native_client.time.monotonic', return_value=now):
            self.send(self.snapshot(locked=True), state)
        self.assertEqual(set(self.client.lock_notices.visible(now + 9.99)), {4})
        self.assertEqual(self.client.lock_notices.visible(now + 10), {})

    def test_lost_inventory_clears_auto_lock_notices(self):
        self.send(self.snapshot())
        command = self.send(self.snapshot())['locks'][0]
        state = {'protocol': PROTOCOL, 'ready': True, 'utc': time.time(), 'session': self.client.session,
                 'player_address': 999, 'game_pid': 123,
                 'acks': [{'id': command['id'], 'result': 'locked'}]}
        self.send(self.snapshot(locked=True), state)
        self.assertEqual(len(self.client.lock_notices.visible(time.monotonic())), 1)
        snapshot = self.snapshot(locked=True)
        snapshot = Snapshot(**dict(snapshot.__dict__, live=False))
        self.send(snapshot, state)
        self.assertEqual(self.client.lock_notices.visible(time.monotonic()), {})

    def test_older_bridge_cannot_receive_new_actions(self):
        snapshot = self.snapshot()
        snapshot.settings['native']['pickup'] = True
        self.send(snapshot)
        old = {'protocol': PROTOCOL - 1, 'ready': True, 'utc': time.time(), 'session': self.client.session,
               'player_address': 999, 'game_pid': 123}
        request = self.send(snapshot, old)
        self.assertEqual(request['protocol'], PROTOCOL)
        self.assertEqual(request['locks'], [])

    def test_pickup_range_and_codex_preferences_reach_native_request(self):
        snapshot = self.snapshot()
        request = self.send(snapshot)
        self.assertEqual(request['pickup_radius'], 2000)
        self.assertTrue(request['skip_codex'])
        snapshot.settings['native'].update(pickup=True, pickup_range_multiplier=1, skip_codex=False)
        request = self.send(snapshot)
        self.assertEqual(request['pickup_radius'], 1000)
        self.assertFalse(request['skip_codex'])

    def test_all_independent_options_and_equipment_exclusions_reach_game_request(self):
        snapshot = self.snapshot()
        snapshot.settings['pickup_exclusions'] = ['9:1:追风', '8:4:疾风项链']
        for multiplier in (1, 1.5, 2):
            for interval in (1, .5, .35, .15):
                for batch in (1, 2, 3, 4):
                    snapshot.settings['native'].update(pickup_range_multiplier=multiplier,
                        pickup_interval=interval, pickup_batch=batch)
                    request = self.send(snapshot)
                    self.assertEqual((request['pickup_radius'], request['pickup_interval'], request['pickup_batch']),
                                     (int(multiplier * 1000), interval, batch))
                    self.assertEqual(request['excluded_equipment'], {'9:1:追风': True, '8:4:疾风项链': True})

    def test_auto_batch_and_official_codex_names_reach_the_game(self):
        snapshot = self.snapshot()
        snapshot.settings['native'].update(pickup_batch=0, skip_codex=True)
        request = self.send(snapshot)
        self.assertEqual(request['pickup_batch'], 0)
        self.assertIn('人形地魔', request['codex_names'])
        self.assertIn('魔化议员法师', request['codex_names'])
        self.assertEqual(len(request['codex_names']), 63)
        self.assertTrue(request['skip_unknown_codex'])
        snapshot.settings['codex_exclusions'] = ['人形地魔']
        selective = self.send(snapshot)
        self.assertEqual(selective['codex_names'], {'人形地魔': True})
        self.assertFalse(selective['skip_unknown_codex'])
        self.assertGreater(selective['pickup_revision'], request['pickup_revision'])
        snapshot.settings['codex_exclusions'] = []
        self.assertEqual(self.send(snapshot)['codex_names'], {})

    def test_native_drop_blocking_uses_saved_selection_without_a_second_switch(self):
        snapshot=self.snapshot()
        snapshot.settings['native'].update(skip_codex=False,pickup=False)
        snapshot.settings.update(codex_exclusions=['人形地魔'],codex_selection_version=1)
        request=self.send(snapshot)
        self.assertTrue(request['skip_codex'])
        self.assertTrue(request['block_drops'])
        self.assertFalse(request['pickup'])
        snapshot.settings['codex_exclusions']=[]
        self.assertFalse(self.send(snapshot)['block_drops'])
        snapshot.settings['pickup_exclusions']=['9:1:追风']
        self.assertTrue(self.send(snapshot)['block_drops'])
        snapshot.settings.pop('codex_selection_version')
        self.assertFalse(self.send(snapshot)['block_drops'], 'old pickup-only choices must not silently change world drops')
        snapshot.settings['native']['skip_codex'] = False
        self.assertEqual(self.send(snapshot)['codex_names'], {})

    def test_quality_library_rule_adds_a_lock_without_numeric_filter_hit(self):
        snapshot = Snapshot(
            status={'game_pid': 123}, live=True,
            current={'items': [{'index': 4, 'item': {
                '物品类型': 1, 'ID': 13, '锁定': False, '名字': '霄引', '等阶': 10,
                '品质': 3, '基础属性': {'攻击上限': 45, '魔法上限': 48},
            }}]},
            ui={'ui': {'valid': True, 'player_address': 999}},
            settings={
                'native': {'lock': True, 'skip_codex': True},
                'lock_library': {'qualities': ['完美'], 'quality_tiers': [10]},
            },
            sections={'numeric': [], 'legendary': [], 'lower': []},
        )
        self.send(snapshot)
        command = self.send(snapshot)['locks']
        self.assertEqual(len(command), 1)
        self.assertEqual(command[0]['index'], 4)


if __name__ == '__main__':unittest.main()
