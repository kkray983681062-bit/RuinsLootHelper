import copy
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from gear_view import DEFAULT_RULES
from native_client import PROTOCOL
from overlay_settings import Settings
import test_native_client as client_fixture
import test_native_game as game_fixture
import test_native_lua as lua_fixture


class RecycleSettingsTests(unittest.TestCase):
    def test_independent_default_off_checkbox_requires_lock_and_apply(self):
        root = tk.Tk(); root.withdraw()
        files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES)}
        class Host:
            def read_file(self, name, default=None): return copy.deepcopy(files.get(name, default))
            def write_file(self, name, value): files[name] = value
        host = Host(); host.root = root
        try:
            d = Settings(host, show=False); n = d.native_settings
            self.assertFalse(n.auto_recycle.get())
            self.assertEqual(n.recycle_check.cget('state'), 'disabled')
            n.recycle_check.invoke(); self.assertFalse(n.auto_recycle.get())
            n.lock.set(True)
            self.assertEqual(n.recycle_check.cget('state'), 'normal')
            self.assertFalse(n.auto_recycle.get(), 'enabling lock must not opt in to recycling')
            n.recycle_check.invoke(); self.assertTrue(n.auto_recycle.get())
            self.assertNotIn('loot-overlay-settings.json', files)
            d.apply()
            self.assertTrue(files['loot-overlay-settings.json']['native']['auto_recycle'])
            d = Settings(host, show=False); n = d.native_settings
            self.assertTrue(n.auto_recycle.get())
            n.lock.set(False)
            self.assertEqual(n.recycle_check.cget('state'), 'disabled')
            self.assertFalse(n.auto_recycle.get())
            n.lock.set(True); self.assertFalse(n.auto_recycle.get())
            d.cancel()
        finally: root.destroy()


class RecycleClientTests(unittest.TestCase):
    setUp = client_fixture.NativeClientTests.setUp
    send = client_fixture.NativeClientTests.send
    snapshot = client_fixture.NativeClientTests.snapshot

    def full_bag(self, count=59):
        s = self.snapshot(0, locked=True)
        s.current['items'] = [{'index': i, 'item': {'物品类型': 1, 'ID': i + 100, '锁定': i == 0}}
                              for i in range(count)]
        s.current['backpack_slot_states'] = [[1 if i < count else 0, i == 0] for i in range(60)]
        s.current['backpack_free_slots'] = 60 - count
        s.settings['native']['auto_recycle'] = True
        self.send(s)  # establish this player's session
        return s

    def state(self, **kw):
        return dict(protocol=PROTOCOL, ready=True, utc=time.time(), session=self.client.session,
                    player_address=999, game_pid=123, auto_recycle_supported=True, **kw)

    def test_only_opt_in_nearly_full_bag_with_confirmed_locks_gets_a_request(self):
        s = self.full_bag()
        for count in (59, 60):
            s = self.full_bag(count)
            req = self.send(s, self.state())
            self.assertTrue(req['auto_lock'])
            self.assertTrue(req['auto_recycle'])
            self.assertEqual(len(req['recycle']['rows']), count)
            self.assertEqual(req['recycle']['protected'], [0])
        for change in ('off', 'lock_off', 'room', 'unlocked', 'legacy', 'inactive'):
            with self.subTest(change=change):
                s = self.full_bag(); st = self.state()
                if change == 'off': s.settings['native'].pop('auto_recycle')
                if change == 'lock_off': s.settings['native']['lock'] = False
                if change == 'room':
                    s.current['items'].pop()
                    s.current['backpack_slot_states'][58] = [0, False]
                    s.current['backpack_free_slots'] = 2
                if change == 'unlocked': s.current['items'][0]['item']['锁定'] = False
                if change == 'legacy': st.pop('auto_recycle_supported')
                with patch('overlay_markers.foreground_matches', return_value=change != 'inactive'):
                    self.assertIsNone(self.send(s, st)['recycle'])

    def test_full_bag_includes_potions_and_materials_not_just_equipment(self):
        for free in (0, 1):
            with self.subTest(free=free):
                s = self.full_bag(60-free)
                s.current['items'] = s.current['items'][:56-free]
                for i in range(56-free, 60-free):
                    s.current['backpack_slot_states'][i] = [2 if i % 2 else 3, False]
                req = self.send(s, self.state())
                self.assertIsNotNone(req['recycle'], req.get('recycle_wait'))
                self.assertEqual(len(req['recycle']['rows']), 56-free)
                self.assertEqual(req['recycle']['slots'], s.current['backpack_slot_states'])

    def test_books_can_be_recycled_but_missing_inventory_metadata_cannot(self):
        s = self.full_bag(60)
        s.current['items'] = []; s.sections.clear()
        s.current['backpack_slot_states'] = [[3, False] for _ in range(60)]
        s.current['backpack_slot_states'][59] = [4, False]
        req = self.send(s, self.state())
        self.assertIsNotNone(req['recycle'], req.get('recycle_wait'))
        self.assertEqual(req['recycle']['rows'], [])
        for invalid in ('missing', 'short', 'inconsistent_count', 'missing_gear'):
            sample = copy.deepcopy(s)
            if invalid == 'missing': sample.current.pop('backpack_slot_states')
            if invalid == 'short': sample.current['backpack_slot_states'].pop()
            if invalid == 'inconsistent_count': sample.current['backpack_free_slots'] = 1
            if invalid == 'missing_gear': sample.current['backpack_slot_states'][59] = [1, False]
            self.assertIsNone(self.send(sample, self.state())['recycle'], invalid)

    def test_manual_unlock_grace_blocks_recycle_even_after_relocking(self):
        s = self.full_bag(); now = time.monotonic()
        with patch('native_client.time.monotonic', return_value=now):
            self.send(s, self.state())
            s = copy.deepcopy(s)
            s.current['items'][0]['item']['锁定'] = False
            self.assertIsNone(self.send(s, self.state())['recycle'])
            s = copy.deepcopy(s)
            s.current['items'][0]['item']['锁定'] = True
            self.assertIsNone(self.send(s, self.state())['recycle'])
        with patch('native_client.time.monotonic', return_value=now+30.1):
            self.assertIsNotNone(self.send(s, self.state())['recycle'])

    def test_unchanged_command_is_not_duplicated_and_bad_inventory_is_rejected(self):
        s = self.full_bag()
        first = self.send(s, self.state())['recycle']
        self.assertEqual(self.send(s, self.state())['recycle']['id'], first['id'])
        s.current['items'][-1]['item']['ID'] += 1
        self.assertNotEqual(self.send(s, self.state())['recycle']['id'], first['id'])
        s.current['items'][-1]['index'] = 0
        self.assertIsNone(self.send(s, self.state())['recycle'])


class RecycleInventoryTests(unittest.TestCase):
    def test_full_slot_states_are_published_from_the_same_stable_read(self):
        import json
        import pathlib
        import struct
        import tempfile
        from unittest.mock import Mock
        from loot_current import CurrentInventory
        from release_runtime import SessionWatch
        watch = SessionWatch.__new__(SessionWatch)
        owner = {'address': 100000, 'index': 1, 'class_address': 200000, 'flags': 0}
        source = {'owner': owner, 'header_address': 300000, 'stride': 8, 'type_name': 'fixture'}
        watch.object_info = lambda _: owner
        watch.next_ui = float('inf')
        watch.read = lambda addr, size: struct.pack('<Qii', 400000, 60, 60) if addr == 300000 else bytes(size)
        decoded = ([{'物品类型': 1, '名字': '装备', '锁定': True}] +
                   [{'物品类型': 1, '名字': '装备'} for _ in range(55)] +
                   [{'物品类型': 2}, {'物品类型': 3}, {'物品类型': 4}, {'物品类型': 0}])
        watch.decode = Mock(side_effect=decoded); watch.compact = lambda item: item
        watch.state = CurrentInventory(); watch.state.replace(watch.take(source))
        self.assertEqual(watch.take(source), watch.state.slots)
        self.assertEqual(watch.decode.call_count, 60, 'unchanged reads must keep the cache')
        watch.phase = 'watching'; watch.last_sample = '2026-09-09'; watch.pid = 1; watch.error = None
        watch.progress = Mock(); watch.publish_ui = Mock()
        with tempfile.TemporaryDirectory() as tmp:
            watch.output = pathlib.Path(tmp) / 'current-loot.json'
            watch.publish()
            value = json.loads(watch.output.read_text(encoding='utf8'))
            self.assertEqual(len(value['items']), 56)
            self.assertEqual(value['backpack_free_slots'], 1)
            self.assertEqual(value['backpack_slot_states'][0], [1, True])
            self.assertEqual(value['backpack_slot_states'][56:], [[2, False], [3, False], [4, False], [0, False]])
            watch.phase = 'waiting'; watch.publish()
            value = json.loads(watch.output.read_text(encoding='utf8'))
            self.assertIsNone(value['backpack_slot_states'])


class RecycleGameTests(unittest.TestCase):
    def setUp(self):
        game_fixture.NativeGameTests.setUp(self)
        self.lua.execute('''
            for i=1,59 do items[i].kind=1 end
            items[1].locked=true
            request.active=true;request.auto_lock=true;request.auto_recycle=true
            recycled=0;mode=nil;official_mode=0
            main["背包"]=object({
                ["BndEvt__背包ui_一键回收_1_K2Node_ComponentBoundEvent_7_OnButtonClickedEvent__DelegateSignature"]=function(_, ...)
                    assert(select('#',...)==0,"the helper must not pass its own currency choice")
                    recycled=recycled+1;mode=official_mode
                end})
            proof={id="r1",columns={},rows={},protected={0},slots={}}
            for i=1,60 do proof.slots[i]={items[i].kind,items[i].locked} end
            for _,key in ipairs({"kind","a","b","c","d"}) do
                table.insert(proof.columns,{path={key},kind="IntProperty"})
            end
            for i=1,59 do table.insert(proof.rows,{index=i-1,locked=i==1,values={1,0,0,0,0}}) end
        ''')

    def test_calls_official_entry_once_with_game_currency_choice(self):
        self.lua.execute('''
            assert(adapter:recycle(proof,request)=="requested")
            assert(recycled==1 and mode==0)
            official_mode=1
            assert(adapter:recycle(proof,request)=="requested")
            assert(recycled==2 and mode==1)
            assert(items[1].locked,"must never unlock equipment")
            main["背包开启"]=true
            assert(adapter:recycle(proof,request)=="requested")
            main["设置开启"]=true
            assert(adapter:recycle(proof,request)=="paused" and recycled==3)
        ''')

    def test_last_moment_new_drop_or_manual_unlock_blocks_official_call(self):
        self.lua.execute('''
            items[60].kind=1
            assert(adapter:recycle(proof,request)=="inventory_changed")
            items[60].kind=0;items[1].locked=false
            assert(adapter:recycle(proof,request)=="inventory_changed")
            items[1].locked=true;items[2].a=9
            assert(adapter:recycle(proof,request)=="inventory_changed")
            assert(recycled==0)
        ''')

    def test_mixed_bag_uses_actual_free_slots_and_rechecks_omitted_kinds(self):
        self.lua.execute('''
            for i=57,59 do
                items[i].kind=3;proof.slots[i]={3,false};table.remove(proof.rows)
            end
            items[60].kind=2;proof.slots[60]={2,false}
            assert(adapter:recycle(proof,request)=="requested", "56 equipment plus four other occupied slots is full")
            items[60].kind=1
            assert(adapter:recycle(proof,request)=="inventory_changed", "new equipment must be filtered before recycling")
            items[60].kind=2;items[2].a=8
            assert(adapter:recycle(proof,request)=="inventory_changed")
            assert(recycled==1)
        ''')

    def test_official_recycle_can_clear_books_without_any_equipment(self):
        self.lua.execute('''
            proof.rows={};proof.protected={}
            for i=1,60 do items[i].kind=3;items[i].locked=false;proof.slots[i]={3,false} end
            items[60].kind=4;proof.slots[60]={4,false}
            assert(adapter:recycle(proof,request)=="requested")
            items[60].locked=true;proof.slots[60][2]=true
            assert(adapter:recycle(proof,request)=="nothing_to_recycle")
            assert(recycled==1)
        ''')

    def test_no_mutation_without_toggle_identity_or_complete_guard(self):
        self.lua.execute('''
            request.auto_lock=false;assert(adapter:recycle(proof,request)=="off")
            request.auto_lock=true;request.auto_recycle=false;assert(adapter:recycle(proof,request)=="off")
            request.auto_recycle=true;request.player_address=999
            assert(adapter:recycle(proof,request)=="waiting_for_current_player")
            request.player_address=123;proof.rows[59].index=0
            assert(adapter:recycle(proof,request)=="invalid_proof")
            assert(recycled==0)
        ''')


class RecycleCoreTests(unittest.TestCase):
    setUp = lua_fixture.NativeLuaTests.setUp

    def test_recycle_is_independent_of_pickup_once_per_command_and_yields(self):
        self.lua.execute('''
            adapter.recycles=0
            function adapter:recycle(cmd,req) self.recycles=self.recycles+1;return "requested" end
            adapter.current.free_slots=1;request.auto_lock=true;request.auto_recycle=true
            request.recycle={id="recycle1"};request.pickup=false
            local result=engine:step(request,1,1)
            assert(result.auto_recycle_supported and result.recycle_state=="requested")
            assert(adapter.recycles==1 and adapter.picks==0)
            engine:step(request,1.1,1.1);assert(adapter.recycles==1)
            request.recycle={id="recycle2"};request.pickup=true
            engine:step(request,1.2,1.2);assert(adapter.recycles==1,"cooldown between bulk calls")
            engine:step(request,3.2,3.2);assert(adapter.recycles==2 and adapter.picks==0)
        ''')

    def test_recycle_never_runs_while_disabled_dragging_or_menu_active(self):
        self.lua.execute('''
            adapter.recycles=0
            function adapter:recycle() self.recycles=self.recycles+1;return "requested" end
            adapter.current.free_slots=0;request.recycle={id="r"};request.pickup=false
            request.auto_recycle=true;engine:step(request,1,1)
            request.auto_lock=true;request.active=false;engine:step(request,2,2)
            request.active=true;adapter.current.dragging=true;engine:step(request,3,3)
            adapter.current.dragging=false;adapter.current.blocked=true;engine:step(request,4,4)
            assert(adapter.recycles==0)
        ''')


if __name__ == '__main__': unittest.main()
