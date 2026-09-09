from pathlib import Path
import unittest
from lupa import LuaRuntime


class NativeLuaTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        core = Path('native/Mods/RuinsHelper/Scripts/core.lua').read_text(encoding='utf8')
        self.lua.globals().Core = self.lua.execute(core)
        self.lua.execute('''
            adapter = { picks = 0, locks = 0, current = {valid=true,player_address=123,
                backpack_open=false,blocked=false,dragging=false,free_slots=2}, targets={{id="drop1"}} }
            function adapter:snapshot(req) return self.current end
            function adapter:nearby() return self.targets end
            function adapter:pickup(target) self.picks = self.picks + 1; return "requested" end
            function adapter:lock(cmd) self.locks = self.locks + 1; return "locked" end
            function adapter:grid(req) return {} end
            engine = Core.new(adapter)
            request = {protocol=4,session="test",expires=1000,player_address=123,active=true,pickup=true,pickup_interval=.15,pickup_batch=4}
        ''')

    def test_full_bag_pauses_and_resumes_without_os_input(self):
        self.lua.execute('''
            adapter.current.free_slots = 0
            assert(engine:step(request,1,1).pickup_state == "full")
            assert(adapter.picks == 0)
            adapter.current.free_slots = 1
            engine:step(request,2,2)
            assert(adapter.picks == 1)
        ''')

    def test_grid_capture_stops_on_closed_bag_inactive_disabled_and_stale_requests(self):
        self.lua.execute('''
            stopped=0
            function adapter:stop_grid() stopped=stopped+1 end
            function adapter:grid() return nil,{state="waiting_for_tick",cells=59} end
            request.markers=true;adapter.current.backpack_open=true
            assert(engine:step(request,1,1).grid_status.cells==59 and stopped==0)
            adapter.current.backpack_open=false;engine:step(request,2,2);assert(stopped==1)
            adapter.current.backpack_open=true;request.active=false
            engine:step(request,3,3);assert(stopped==2)
            request.active=true;request.markers=false
            engine:step(request,4,4);assert(stopped==3)
            request.markers=true;request.expires=0
            engine:step(request,5,5);assert(stopped==4)
        ''')

    def test_drop_filter_updates_independently_of_pickup_and_focus(self):
        self.lua.execute('''
            updated=0
            function adapter:update_drop_filter(req)
                updated=updated+1;return {state="connected",blocked=2}
            end
            request.pickup=false;request.active=false
            local status=engine:step(request,1,1)
            assert(updated==1 and status.drop_filter.blocked==2 and adapter.picks==0)
            request.expires=0;engine:step(request,2,2)
            assert(updated==1,"expired request must not refresh filter lifetime")
        ''')

    def test_older_helper_protocol_is_rejected_before_touching_game(self):
        self.lua.execute('''
            request.protocol=3
            function adapter:snapshot(req) error("must not touch the game") end
            assert(engine:step(request,1,1).ready==false)
            assert(adapter.picks==0 and adapter.locks==0)
        ''')

    def test_inactive_menu_or_stale_request_never_picks(self):
        self.lua.execute('''
            request.active=false; engine:step(request,1,1)
            request.active=true; adapter.current.backpack_open=true; engine:step(request,2,2)
            adapter.current.backpack_open=false; adapter.current.blocked=true; engine:step(request,3,3)
            adapter.current.blocked=false; engine:step(request,1001,1001)
            assert(adapter.picks == 0)
        ''')

    def test_bound_retries_and_once_only_lock_toggle(self):
        self.lua.execute('''
            request.locks={{id="lock1",index=4}}
            for i=1,10 do engine:step(request,i,i) end
            assert(adapter.picks == 3)
            assert(adapter.locks == 1)
            adapter.targets={}
            assert(engine:step(request,11,11).pickup_confirmed == true)
            adapter.targets={{id="drop2"}}
            engine:step(request,12,12)
            assert(adapter.picks == 4)
        ''')

    def test_wrong_player_or_drag_does_not_lock(self):
        self.lua.execute('''
            request.locks={{id="lock1",index=4}}
            request.player_address=999
            engine:step(request,1,1)
            assert(adapter.locks==0)
            request.player_address=123; adapter.current.dragging=true
            engine:step(request,2,2)
            assert(adapter.locks==0)
        ''')

    def test_per_actor_batch_is_limited_by_free_slots_and_stops_when_bag_fills(self):
        self.lua.execute('''
            adapter.targets={{id="one"},{id="two"},{id="three"},{id="four"},{id="five"}}
            adapter.current.free_slots=60
            engine:step(request,1,1);assert(adapter.picks==4)
            engine:step(request,1.2,1.2);assert(adapter.picks==5)
            engine=Core.new(adapter);adapter.picks=0;adapter.current.free_slots=1
            engine:step(request,2,2);assert(adapter.picks==1)
            engine=Core.new(adapter);adapter.picks=0;adapter.current.free_slots=60
            function adapter:pickup(target)
                if self.picks==1 then return "full" end
                self.picks=self.picks+1;return "requested"
            end
            assert(engine:step(request,3,3).pickup_state=="full")
            assert(adapter.picks==1)
        ''')

    def test_scan_interval_and_batch_are_independent(self):
        self.lua.execute('''
            request.pickup_interval=1;request.pickup_batch=1;adapter.scans=0
            adapter.current.free_slots=60
            adapter.targets={{id="one"},{id="two"},{id="three"}}
            function adapter:nearby() self.scans=self.scans+1;return self.targets end
            engine:step(request,1,1)
            engine:step(request,1.2,1.2)
            engine:step(request,1.4,1.4)
            assert(adapter.scans==1 and adapter.picks==1)
            engine:step(request,2.01,2.01)
            assert(adapter.scans==2 and adapter.picks==2)
            request.active=false;engine:step(request,3,3)
            assert(adapter.scans==2 and adapter.picks==2)
        ''')

    def test_every_user_interval_and_batch_combination(self):
        self.lua.execute('''
            for _,interval in ipairs({1,.5,.35,.15}) do
                for _,batch in ipairs({1,2,3,4}) do
                    engine=Core.new(adapter);adapter.picks=0;adapter.scans=0
                    adapter.current.free_slots=60
                    adapter.targets={{id="one"},{id="two"},{id="three"},{id="four"}}
                    function adapter:nearby() self.scans=self.scans+1;return self.targets end
                    request.pickup_interval=interval;request.pickup_batch=batch
                    engine:step(request,10,10)
                    engine:step(request,10+interval-.01,10+interval-.01)
                    assert(adapter.scans==1 and adapter.picks==batch)
                    engine:step(request,10+interval+.01,10+interval+.01)
                    assert(adapter.scans==2)
                end
            end
        ''')

    def test_native_clock_controls_interval_when_mailbox_timestamp_is_unchanged(self):
        self.lua.execute('''
            adapter.clock_value=10;adapter.scans=0
            adapter.clock=function(self) return self.clock_value end
            adapter.nearby=function(self) self.scans=self.scans+1;return self.targets end
            engine:step(request,1,1)
            adapter.clock_value=10.1;engine:step(request,1,1)
            assert(adapter.scans==1)
            adapter.clock_value=10.151;engine:step(request,1,1)
            assert(adapter.scans==2)
            adapter.clock_value=.1;engine:step(request,1,1)
            assert(adapter.scans==3)
        ''')

    def test_auto_batch_clears_more_than_four_when_calls_are_fast(self):
        self.lua.execute('''
            request.pickup_batch=0; adapter.current.free_slots=60; adapter.targets={}
            for i=1,12 do table.insert(adapter.targets,{id="drop"..i}) end
            os.clock=function() return 0 end
            engine:step(request,1,1)
            assert(adapter.picks==12, "automatic batch must not fall back to two or four")
        ''')

    def test_auto_batch_yields_slow_calls_and_continues_remaining_drops(self):
        self.lua.execute('''
            request.pickup_batch=0;request.pickup_interval=1
            adapter.current.free_slots=60;adapter.targets={};spent=0
            for i=1,12 do table.insert(adapter.targets,{id="drop"..i}) end
            os.clock=function() return spent end
            function adapter:pickup(target)
                self.picks=self.picks+1;spent=spent+.005
                return "requested"
            end
            engine:step(request,1,1)
            assert(adapter.picks==1, "slow calls must yield to the game")
            engine:step(request,1.051,1.051)
            assert(adapter.picks==2, "remaining drops must continue without the idle scan wait")
            request.active=false;engine:step(request,1.102,1.102)
            assert(adapter.picks==2)
            request.active=true;adapter.current.free_slots=0
            assert(engine:step(request,1.153,1.153).pickup_state=="full")
            assert(adapter.picks==2)
        ''')


if __name__ == '__main__':unittest.main()
