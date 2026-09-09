"""Exercise eligibility and the real rift adapter without touching a running game."""
import copy
from dataclasses import replace
from pathlib import Path
import time
import tkinter as tk
import unittest
from lupa import LuaRuntime

from gear_view import DEFAULT_RULES
from native_client import PROTOCOL
from overlay_settings import Settings
import test_native_client as client_fixtures


class RiftNativeTests(unittest.TestCase):
    def setUp(self):
        path = Path('native/Mods/RuinsHelper/Scripts/rifts.lua')
        self.assertTrue(path.is_file(), 'The assistant must include its rift adapter')
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().Rifts = self.lua.execute(path.read_text(encoding='utf-8'))
        self.lua.execute('''
            function obj(t) t.IsValid=function(self) return not self.dead end; return t end
            world=obj({GetAddress=function() return 70 end,
                GetFullName=function() return 'World MAP01' end})
            calls={};scans=0
            task=obj({['服务器开启裂隙']=function(_,map,actor)
                table.insert(calls,{map=map,actor=actor.id})
                if rpc_error then error('lost acknowledgement') end
            end})
            player=obj({['等级']=49, ['任务组件']=task,
                GetAddress=function() return 123 end, GetWorld=function() return world end,
                IsLocallyControlled=function() return true end,
                K2_GetActorLocation=function() return {X=0,Y=0,Z=0} end})
            function rates(drop,elite)
                player['总属性']={['特殊属性_101_76EBA5AC4AF332228321C080A0295C7F']={
                    ['掉落率+_179_31902C37471655F1A42F5194DDE4DDB0']=drop,
                    ['极品率+_185_647BC2BD4F0D7071D6CEF0B1782B8821']=elite}}
            end
            rates(300,300)
            function door(id,x)
                return obj({id=id,x=x,['地图']=9,GetAddress=function(self) return self.id end,
                    GetFullName=function(self) return 'rift_'..self.id end,
                    GetWorld=function() return world end,
                    GetClass=function() return obj({GetFullName=function()
                        return 'BlueprintGeneratedClass /Game/Actors/裂隙/裂隙.裂隙_C' end}) end,
                    K2_GetActorLocation=function(self) return {X=self.x,Y=0,Z=0} end})
            end
            doors={door(1,1000),door(2,400),door(3,2001)}
            FindAllOf=function(name) assert(name=='裂隙_C');scans=scans+1;return doors end
            NotifyOnNewObject=function(path,cb)
                assert(path=='/Game/Actors/裂隙/裂隙.裂隙_C');new_door=cb end
            controller=Rifts.new()
            req={auto_rift=true,player_address=123,rift_run_id='helper-launch-1'}
            state={blocked=false,dragging=false}
        ''')

    def test_level_or_both_percentages_with_exact_boundary_and_invalid_values(self):
        qualify = self.lua.eval('function(level,drop,elite) player["等级"]=level;rates(drop,elite);return Rifts.qualification(player).eligible end')
        for values, expected in [((50,0,0),True), ((49,300,300),True), ((49,400,299),False),
                                 ((49,299,400),False), ((49,3,3),False), ((None,300,300),True),
                                 ((None,None,None),False), ((50,None,None),True),
                                 ((float('nan'),300,299),False), ((float('inf'),0,0),False),
                                 ((49,float('inf'),300),False), ((True,0,0),False)]:
            with self.subTest(values=values):
                self.assertEqual(qualify(*values), expected)

    def test_nearest_once_per_second_and_new_object_notification_without_repeated_full_scans(self):
        self.lua.execute('''
            controller:step(player,req,10,state)
            assert(#calls==1 and calls[1].actor==2 and calls[1].map==9)
            controller:step(player,req,10.9,state);assert(#calls==1)
            controller:step(player,req,11.01,state);assert(#calls==2 and calls[2].actor==1)
            controller:step(player,req,12.02,state);assert(#calls==2 and scans==1)
            new_door(door(4,200));controller:step(player,req,13.03,state)
            assert(#calls==3 and calls[3].actor==4 and scans==1)
        ''')

    def test_default_off_wrong_player_and_blocked_never_open(self):
        self.lua.execute('''
            req.auto_rift=nil;controller:step(player,req,1,state);assert(#calls==0 and scans==0)
            req.auto_rift=true;req.player_address=999;controller:step(player,req,3,state);assert(#calls==0)
            req.player_address=123;state.blocked=true;controller:step(player,req,4,state);assert(#calls==0)
            state.blocked=false;controller:step(player,req,5,state);assert(#calls==1)
            rates(0,0);player['等级']=1
            player.GetAddress=function() return 124 end;req.player_address=124
            controller:step(player,req,6,state);assert(#calls==2,'switching to an alt must keep this launch permission')
        ''')

    def test_permission_checked_once_and_new_helper_launch_rechecks(self):
        self.lua.execute('''
            rates(299,400)
            local denied=controller:step(player,req,1,state)
            assert(denied.checked and not denied.eligible and #calls==0)
            rates(400,400);player['等级']=50
            assert(not controller:step(player,req,2,state).eligible and #calls==0)
            req.rift_run_id='helper-launch-2'
            assert(controller:step(player,req,3,state).eligible and #calls==1)
            player['等级']=1;player['总属性']=nil
            assert(controller:step(player,req,4,state).eligible and #calls==2)
        ''')

    def test_missing_initial_character_data_waits_and_permission_survives_game_restart(self):
        self.lua.execute('''
            player['等级']=nil;player['总属性']=nil
            assert(not controller:step(player,req,1,state).checked and #calls==0)
            player['等级']=50
            local grant=controller:step(player,req,2,state)
            assert(grant.checked and grant.eligible and #calls==1)
            req.rift_permission={checked=true,eligible=true,level=grant.level,run_id=req.rift_run_id}
            controller=Rifts.new();player['等级']=1;rates(0,0)
            assert(controller:step(player,req,3,state).eligible)
        ''')

    def test_foreign_world_destroyed_and_wrong_class_targets_are_ignored(self):
        self.lua.execute('''
            doors[1].GetWorld=function() return obj({GetAddress=function() return 71 end}) end
            doors[2].dead=true
            doors[3].x=100;doors[3].GetClass=function() return obj({GetFullName=function() return 'OtherDoor' end}) end
            controller:step(player,req,1,state);assert(#calls==0)
        ''')

    def test_uncertain_rpc_is_not_repeated_and_toggle_preserves_processed_doors(self):
        self.lua.execute('''
            doors={door(1,100)};rpc_error=true
            controller:step(player,req,1,state);assert(#calls==1)
            req.auto_rift=false;controller:step(player,req,2,state)
            req.auto_rift=true;rpc_error=false;controller:step(player,req,3,state)
            assert(#calls==1)
        ''')

    def test_core_runs_rifts_with_pickup_off_and_contains_rift_errors(self):
        core = self.lua.execute(Path('native/Mods/RuinsHelper/Scripts/core.lua').read_text(encoding='utf-8'))
        self.lua.globals().Core = core
        self.lua.execute('''
            checked=0
            adapter={snapshot=function() return {valid=true,player_address=123,free_slots=60} end,
                rift_step=function() checked=checked+1;return {eligible=true,state='off'} end}
            engine=Core.new(adapter)
            q={protocol=4,session='a',expires=99,player_address=123,pickup=false,active=false}
            local report=engine:step(q,1,1)
            assert(checked==1 and report.rift_supported and report.rift.eligible)
            adapter.rift_step=function() error('unsupported property') end
            report=engine:step(q,2,2);assert(report.ready and report.rift.state=='error')
            q.expires=0;engine:step(q,3,3);assert(checked==1)
        ''')


class RiftRequestTests(unittest.TestCase):
    setUp = client_fixtures.NativeClientTests.setUp
    snapshot = client_fixtures.NativeClientTests.snapshot
    send = client_fixtures.NativeClientTests.send
    def test_only_saved_opt_in_and_live_character_enable_rift_request(self):
        snapshot = self.snapshot()
        self.assertFalse(self.send(snapshot).get('auto_rift', False))
        snapshot.settings['native']['auto_rift'] = True
        self.assertTrue(self.send(snapshot).get('auto_rift', False))
        snapshot = replace(snapshot, live=False)
        self.assertFalse(self.send(snapshot).get('auto_rift', False))

    def test_permission_latches_in_this_helper_launch_across_character_and_game_changes(self):
        snapshot=self.snapshot()
        first=self.send(snapshot)
        self.assertIsInstance(first.get('rift_run_id'),str)
        run_id=first['rift_run_id']
        status=dict(protocol=PROTOCOL,utc=time.time(),ready=True,session=self.client.session,
            game_pid=123,player_address=999,rift_supported=True,
            rift=dict(run_id=run_id,checked=True,eligible=True,level=50))
        self.assertTrue(self.send(snapshot,status)['rift_permission']['eligible'])
        snapshot.ui['ui']['player_address']=555
        later=self.send(snapshot,{})
        self.assertEqual(later['rift_run_id'],run_id)
        self.assertTrue(later['rift_permission']['eligible'])
        snapshot.status['game_pid']=456
        self.assertTrue(self.send(snapshot,{})['rift_permission']['eligible'])


class RiftSettingsTests(unittest.TestCase):
    def test_unqualified_is_disabled_qualified_can_opt_in_and_apply_persists(self):
        root = tk.Tk(); root.withdraw()
        files = {'loot-filter-rules.json': copy.deepcopy(DEFAULT_RULES)}
        class Host:
            def read_file(self, name, default=None): return copy.deepcopy(files.get(name, default))
            def write_file(self, name, value): files[name] = value
        host = Host(); host.root = root
        dialog = Settings(host, show=False)
        try:
            native = dialog.native_settings
            self.assertTrue(hasattr(native, 'rift_check'), 'Show the optional automatic rift control')
            native.refresh()
            self.assertEqual(str(native.rift_check.cget('state')), 'disabled')
            self.assertFalse(native.auto_rift.get())
            files['native-status.json'] = dict(protocol=PROTOCOL,utc=time.time(),ready=True,
                rift_supported=True,rift={'checked':True,'eligible':True,'level':50,'extra_drop_pct':0,'extra_elite_pct':0,'state':'off'})
            native.refresh()
            self.assertEqual(str(native.rift_check.cget('state')), 'normal')
            self.assertFalse(native.auto_rift.get())
            native.rift_check.invoke();self.assertTrue(native.auto_rift.get())
            dialog.apply()
            self.assertTrue(files['loot-overlay-settings.json']['native']['auto_rift'])
            dialog = Settings(host, show=False);native=dialog.native_settings
            files['native-status.json']['rift']['eligible']=False
            files['native-status.json']['rift']['level']=49
            native.refresh()
            self.assertEqual(str(native.rift_check.cget('state')), 'disabled')
            self.assertFalse(native.auto_rift.get())
        finally:
            if dialog.window.winfo_exists(): dialog.cancel()
            root.destroy()


if __name__ == '__main__':
    unittest.main()
