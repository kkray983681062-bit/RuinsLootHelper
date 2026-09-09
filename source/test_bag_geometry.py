"""Native widget geometry must survive UE4SS's opaque FGeometry boundary."""
from pathlib import Path
import unittest
from lupa import LuaRuntime


class Geometry:
    def __init__(self, x, y, w=54, h=54):
        self.x, self.y, self.w, self.h = x, y, w, h


class BagGeometryTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().Geometry = Geometry
        self.lua.globals().module = self.lua.execute(
            Path('native/Mods/RuinsHelper/Scripts/bag_geometry.lua').read_text(encoding='utf8'))
        self.lua.execute('''
            function object(t) t.IsValid=function() return true end;return t end
            now, registrations, conversions = 10,0,0
            callbacks={};cells={};dx,dy=0,0
            local tick=object({GetFullName=function() return "Function /Game/UI/Cell.Cell_C:Tick" end})
            for i=0,59 do
                local cell=object({["在背包"]=true,["在仓库"]=false,["格子ID"]=i,Tick=tick})
                cell.GetAddress=function() return 1000+i end
                cell.IsVisible=function() return true end
                -- This is the actual pinned bridge failure: opaque return
                -- structs become empty tables and lose their native fields.
                cell.GetCachedGeometry=function() error("Do not round-trip opaque FGeometry through a Lua table") end
                cells[i+1]=cell
            end
            wrap=object({GetAddress=function() return 800 end,
                GetChildrenCount=function() return #cells end,GetChildAt=function(_,i) return cells[i+1] end})
            player=object({GetAddress=function() return 123 end})
            slate=object({GetLocalSize=function(_,g)
                    assert(type(g)=="userdata", "FGeometry must retain its raw struct wrapper")
                    return {X=g.w,Y=g.h}
                end,
                LocalToViewport=function(_,p,g,v,out,view)
                    conversions=conversions+1;assert(p==player and type(g)=="userdata")
                    out.X=g.x+v.X;out.Y=g.y+v.Y
                end})
            RegisterHook=function(path,callback)
                registrations=registrations+1;callbacks[path]=callback;return 11,12
            end
            tracker=module.new(slate,function() return now end)
            request={session="test",player_address=123,viewport={1200,900}}
            function frame()
                for i,cell in ipairs(cells) do
                    local n=i-1
                    local g=Geometry(100+n%10*60+dx,100+math.floor(n/10)*60+dy)
                    local context={get=function() return cell end}
                    local geometry={get=function() return g end}
                    assert(callbacks["/Game/UI/Cell.Cell_C:Tick"](context,geometry)==nil)
                end
            end
        ''')

    def test_current_sixty_cells_follow_drag_without_any_saved_calibration(self):
        self.lua.execute('''
            local grid,info=tracker:read(wrap,player,request)
            assert(grid==nil and info.state=="waiting_for_tick")
            frame()
            grid=tracker:read(wrap,player,request)
            assert(grid.slots["0"][1]==100 and grid.slots["59"][2]==400)
            now=10.06;dx=170;dy=85;frame()
            grid=tracker:read(wrap,player,request)
            assert(grid.slots["0"][1]==270 and grid.slots["59"][2]==485)
            assert(registrations==1 and grid.source=="widget_tick")
        ''')

    def test_geometry_wrapper_is_consumed_inside_callback_and_only_numbers_remain(self):
        self.lua.execute('''
            tracker:read(wrap,player,request);frame()
            Geometry=function() error("A callback-scoped geometry cannot be re-read later") end
            local grid=tracker:read(wrap,player,request)
            for _,box in pairs(grid.slots) do
                for _,v in ipairs(box) do assert(type(v)=="number") end
            end
            assert(conversions==120)
        ''')

    def test_other_bags_and_disabled_or_expired_capture_do_no_coordinate_work(self):
        self.lua.execute('''
            tracker:read(wrap,player,request)
            local other=object({GetAddress=function() return 9999 end})
            local bad={get=function() error("must not read unrelated geometry") end}
            local callback=callbacks["/Game/UI/Cell.Cell_C:Tick"]
            callback({get=function() return other end},bad)
            assert(conversions==0)
            frame();local count=conversions
            tracker:stop();frame();assert(conversions==count)
            tracker:read(wrap,player,request);now=11;frame();assert(conversions==count)
            local grid,info=tracker:read(wrap,player,request)
            assert(grid==nil and info.state=="waiting_for_tick")
        ''')

    def test_new_viewport_session_or_widget_tree_invalidates_old_coordinates(self):
        self.lua.execute('''
            tracker:read(wrap,player,request);frame()
            request.viewport={1400,1000};assert(tracker:read(wrap,player,request)==nil)
            now=10.06;frame();assert(tracker:read(wrap,player,request)~=nil)
            request.session="new";assert(tracker:read(wrap,player,request)==nil)
            now=10.12;frame();assert(tracker:read(wrap,player,request)~=nil)
            cells[1].GetAddress=function() return 9000 end
            assert(tracker:read(wrap,player,request)==nil)
            assert(registrations==1)
        ''')

    def test_incomplete_duplicate_hidden_and_stale_cells_never_return_partial_grid(self):
        self.lua.execute('''
            tracker:read(wrap,player,request);frame()
            local saved=cells[60];cells[60]=nil
            assert(tracker:read(wrap,player,request)==nil)
            cells[60]=saved;tracker:read(wrap,player,request)
            now=10.06;frame()
            cells[60]["格子ID"]=58;assert(tracker:read(wrap,player,request)==nil)
            cells[60]["格子ID"]=59;tracker:read(wrap,player,request)
            now=10.12;frame()
            cells[60].IsVisible=function() return false end
            assert(tracker:read(wrap,player,request)==nil)
            cells[60].IsVisible=function() return true end
            tracker:read(wrap,player,request);now=10.18;frame()
            now=11;assert(tracker:read(wrap,player,request)==nil)
        ''')

    def test_bad_geometry_is_reported_and_never_changes_game_tick_result(self):
        self.lua.execute('''
            tracker:read(wrap,player,request)
            local callback=callbacks["/Game/UI/Cell.Cell_C:Tick"]
            assert(callback({get=function() return cells[1] end},{get=function() return {} end})==nil)
            local grid,info=tracker:read(wrap,player,request)
            assert(grid==nil and info.error and info.error:find("geometry"))
        ''')


if __name__ == '__main__':
    unittest.main()
