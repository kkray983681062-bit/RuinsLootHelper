"""Enable/disable, connection loss and throttling around the accepted marker."""
from pathlib import Path
import unittest
from lupa.lua54 import LuaRuntime


class BaguaControlTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        path = Path('native/Mods/RuinsHelper/Scripts').resolve().as_posix()
        self.lua.execute(f"package.path = '{path}/?.lua;' .. package.path")
        self.lua.execute('''
            registrations=0
            function NotifyOnNewObject() registrations=registrations+1 end
            game={reads=0,discovered=0,hidden=0,detached=0,created=0,moves=0}
            function game:remember() end
            function game:discover_once() self.discovered=self.discovered+1 end
            function game:snapshot() self.reads=self.reads+1; if fail then error('invalid') end; return sample end
            function game:valid() return self.created>0 end
            function game:attach() self.created=self.created+1 end
            function game:move() self.moves=self.moves+1 end
            function game:hide() self.hidden=self.hidden+1 end
            function game:detach() self.detached=self.detached+1 end
            sample={entry=3,active=true,in_arena=true,enlarged=false,ui_key='map',
               target={X=100,Y=0,Z=0},player={X=0,Y=0,Z=0},
               center={X=0,Y=0,Z=0},extent={X=-2776,Y=1792,Z=0},
               size=7000,fixed_size=7000,map_size=7000,origin={X=20,Y=40}}
            control=require('bagua').new(game)
            req={bagua_marker=true,active=true}
        ''')

    def test_disabled_never_reads_world_and_enable_reads_once(self):
        self.lua.execute('control:step({bagua_marker=false},0)')
        self.assertEqual(self.lua.eval('game.reads'), 0)
        self.assertEqual(self.lua.eval('registrations'), 0)
        self.lua.execute('control:step(req,1);control:step(req,1.1)')
        self.assertEqual(self.lua.eval('game.reads'), 1)
        self.assertEqual(self.lua.eval('registrations'), 2)

    def test_disconnect_hides_a_visible_marker_immediately(self):
        self.lua.execute('control:step(req,1);control:stop()')
        self.assertEqual(self.lua.eval('game.hidden'), 1)
        self.assertFalse(self.lua.eval('control.control.visible'))

    def test_leave_region_hides_marker_and_idle_scans_once_per_second(self):
        self.lua.execute('control:step(req,1);sample=nil;control:step(req,1.3);control:step(req,1.8)')
        self.assertEqual(self.lua.eval('game.reads'), 2)
        self.assertEqual(self.lua.eval('game.hidden'), 1)

    def test_repeated_errors_pause_until_explicit_disable(self):
        self.lua.execute('fail=true;control:step(req,0);control:step(req,1);control:step(req,2);control:step(req,3)')
        self.assertEqual(self.lua.eval('game.reads'), 3)
        self.lua.execute('control:step({bagua_marker=false},4);fail=false;control:step(req,5)')
        self.assertEqual(self.lua.eval('game.reads'), 4)


if __name__ == '__main__':
    unittest.main()


class SharedBridgeTests(unittest.TestCase):
    def test_marker_uses_bridge_and_hides_on_expired_or_wrong_character(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().core = lua.execute(Path('native/Mods/RuinsHelper/Scripts/core.lua').read_text(encoding='utf-8'))
        lua.execute('''
            hidden=0;checked=0
            adapter={snapshot=function() return {valid=true,player_address=9,free_slots=3} end,
                     bagua_step=function() checked=checked+1;return {state='waiting'} end,
                     stop_bagua=function() hidden=hidden+1 end}
            engine=core.new(adapter)
            req={protocol=4,expires=10,session='s',player_address=9,pickup=false}
            local result=engine:step(req,1,1)
            assert(result.ready and result.bagua_supported and result.bagua.state=='waiting')
            req.player_address=2;engine:step(req,2,2);assert(hidden==1 and checked==1)
            engine:step(req,3,11);assert(hidden==2 and checked==1)
        ''')


from dataclasses import replace
import test_native_client as fixtures


class MarkerRequestTests(unittest.TestCase):
    setUp = fixtures.NativeClientTests.setUp
    snapshot = fixtures.NativeClientTests.snapshot
    send = fixtures.NativeClientTests.send

    def test_marker_requires_saved_opt_in_and_current_live_character(self):
        snapshot = self.snapshot()
        self.assertFalse(self.send(snapshot)['bagua_marker'])
        snapshot.settings['native']['bagua_marker'] = True
        self.assertTrue(self.send(snapshot)['bagua_marker'])
        self.assertFalse(self.send(replace(snapshot, live=False))['bagua_marker'])

    def test_disable_drop_filter_preserves_selection_and_stops_both_filters(self):
        snapshot = self.snapshot()
        snapshot.settings.update(pickup_exclusions=['9:1:追风'], codex_exclusions=['人形地魔'],
                                 codex_selection_version=1, drop_filter_enabled=False)
        request = self.send(snapshot)
        self.assertEqual(request['excluded_equipment'], {})
        self.assertEqual(request['codex_names'], {})
        self.assertFalse(request['block_drops'])
        self.assertEqual(snapshot.settings['pickup_exclusions'], ['9:1:追风'])
