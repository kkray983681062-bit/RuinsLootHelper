"""Exercise the Lua adapter's mutation boundary with checked mock UObjects."""
from pathlib import Path
import json
import unittest
from lupa import LuaRuntime


class EngineName:
    """Typed engine-name stand-in exposed to Lua as userdata, not a string."""

    def __init__(self, value):
        self.value = value

    def ToString(self):
        return self.value


class NativeGameTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().FName = EngineName
        self.lua.globals().adapter = self.lua.execute(Path('native/Mods/RuinsHelper/Scripts/game.lua').read_text(encoding='utf8'))
        self.lua.execute('''
            function object(t) t.IsValid=function() return true end; return t end
            items = {}
            for i=1,60 do items[i]={kind=0,locked=false,a=0,b=0,c=0,d=0} end
            items[1].kind=1
            count, reads, toggles = 60,0,0
            bag=setmetatable({GetArrayNum=function() return count end}, {__index=function(_,index)
                assert(index>=1 and index<=count, "TArray out of range")
                reads=reads+1;return items[index]
            end})
            player=object({GetAddress=function() return 123 end,IsLocallyControlled=function() return true end,
                ["背包物品简化"]=bag, ["服务器锁定装备"]=function(_,index)
                    toggles=toggles+1;items[index+1].locked=not items[index+1].locked
                end})
            for _,k in ipairs({"物品拖拽中","技能拖拽","仓库开启","1打开商店","地图开关",
                "打开悬赏面板","打开锻造","服务器正在回城"}) do player[k]=false end
            main=object({["对应玩家"]=player})
            for _,k in ipairs({"背包开启","角色栏开启","技能栏开启","设置开启","玩家列表开启","是否黑屏"}) do main[k]=false end
            FindAllOf=function(name) assert(name=="主UI_C"); return {main} end
            request={player_address=123,schema={item_kind="kind",locked="locked"}}
            command={index=0,expected={}}
            for _,k in ipairs({"kind","a","b","c","d"}) do
                table.insert(command.expected,{path={k},kind="IntProperty",value=items[1][k]})
            end
        ''')

    def test_tarray_one_based_native_rpc_zero_based_and_never_unlocks(self):
        self.lua.execute('''
            assert(adapter:snapshot(request).free_slots==59)
            assert(reads==60)
            assert(adapter:lock(command)=="locked")
            assert(adapter:lock(command)=="already_locked")
            assert(toggles==1 and items[1].locked==true)
        ''')

    def test_short_inventory_wrong_slot_and_changed_item_do_not_call_rpc(self):
        self.lua.execute('''
            count=59;assert(adapter:snapshot(request).valid==false);assert(reads==0)
            count=60;adapter:snapshot(request)
            command.index=-1;assert(adapter:lock(command)=="bad_index")
            command.index=60;assert(adapter:lock(command)=="bad_index")
            command.index=0;items[1].a=99
            assert(adapter:lock(command)=="item_changed" and toggles==0)
        ''')

    def setup_drops(self):
        self.lua.execute('''
            adapter:snapshot(request)
            request.schema.actor_kind="kind";request.schema.actor_name="name"
            request.pickup_radius=2000;request.skip_codex=true
            request.active=true;request.pickup=true
            world=object({GetAddress=function() return 900 end})
            player.GetWorld=function() return world end
            player.K2_GetActorLocation=function() return {X=0,Y=0,Z=0} end
            player.PlayerState=object({["名字"]="Steam_Hero"})
            called={}
            player["服务器拾取物品"]=function(_,actor) table.insert(called,actor.id) end
            function drop(id,x,name,kind,owner)
                local a=object({id=id,x=x,["归属"]=owner or "",["装备属性"]={name=name,kind=kind}})
                a.GetAddress=function() return id end
                a.GetFullName=function() return "Drop_"..id end
                a.GetWorld=function() return world end
                a.K2_GetActorLocation=function() return {X=a.x,Y=0,Z=0} end
                a.ActorHasTag=function(_,tag)
                    -- Pinned UE4SS push_nameproperty(Set) requires FName
                    -- userdata; a Lua string dereferences null in native code.
                    assert(type(tag)=="userdata", "ActorHasTag requires FName userdata, not a Lua string")
                    return tag:ToString()=="物品"
                end
                return a
            end
            drops={drop(1,1500,"追风",1),drop(2,1500,"魔化精英图鉴",3),
                   drop(3,2001,"追风",1),drop(4,500,"追风",1,"Other")}
            adapter.notified=true;adapter.refresh_at=math.huge;adapter.actors={}
            for _,a in ipairs(drops) do adapter.actors[a.id]=a end
        ''')

    def test_new_drop_scan_marshals_tag_as_fname_before_pickup(self):
        self.setup_drops()
        ok, targets = self.lua.execute('return pcall(function() return adapter:nearby(request) end)')
        self.assertTrue(ok, targets)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[1]['id'], '1:Drop_1')
        self.assertEqual(self.lua.eval('#called'), 0)

    def test_all_official_codex_internal_names_are_excluded_before_pickup(self):
        self.setup_drops()
        rows = json.loads(Path('catalog/codex-items.json').read_text(encoding='utf8'))['items']
        self.lua.globals().codex_names = self.lua.table_from({row['name']: True for row in rows})
        self.lua.execute('request.codex_names=codex_names')
        for row in rows:
            with self.subTest(name=row['name']):
                self.lua.globals().codex_name = row['name']
                self.assertFalse(self.lua.eval('function() drops[2]["装备属性"].name=codex_name;return adapter:drop_allowed(drops[2],request) end')())
        self.lua.execute('''
            drops[2]["装备属性"].name="人形地魔"
            request.skip_codex=false;assert(adapter:drop_allowed(drops[2],request))
            request.skip_codex=true;drops[2]["装备属性"].kind=1
            assert(adapter:drop_allowed(drops[2],request), "same-name equipment is not a codex")
        ''')

    def test_double_radius_excludes_codex_and_other_owners_before_native_pickup(self):
        self.setup_drops()
        self.lua.execute('''
            local targets=adapter:nearby(request)
            assert(#targets==1 and targets[1].distance==1500^2)
            assert(adapter:pickup(targets[1],request)=="requested")
            assert(#called==1 and called[1]==1)
            request.skip_codex=false;assert(#adapter:nearby(request)==2)
            request.pickup_radius=1000;assert(#adapter:nearby(request)==0)
        ''')

    def test_selected_codex_and_equipment_report_skip_counts_without_rpc(self):
        self.setup_drops()
        self.lua.execute('''
            request.codex_names={["人形地魔"]=true};request.skip_unknown_codex=false
            drops[2]["装备属性"].name="人形地魔"
            request.schema.actor_equipment="gear"
            request.schema.equipment_tier="tier";request.schema.equipment_type="part"
            request.excluded_equipment={["9:1:追风"]=true}
            drops[1]["装备属性"].gear={tier=9,part=1}
            assert(#adapter:nearby(request)==0)
            assert(adapter.scan_exclusions.codex==1 and adapter.scan_exclusions.equipment==1)
            assert(#called==0)
            request.codex_names={}
            assert(#adapter:nearby(request)==1)
            assert(adapter.scan_exclusions.codex==0 and adapter.scan_exclusions.equipment==1)
            drops[2]["装备属性"].name="人形地魔图鉴"
            assert(adapter:drop_allowed(drops[2],request), "partial selection must not exclude every codex suffix")
        ''')

    def test_rechecks_drop_range_ownership_type_and_capacity_before_each_rpc(self):
        self.setup_drops()
        self.lua.execute('''
            local target=adapter:nearby(request)[1]
            drops[1].x=2001;assert(adapter:pickup(target,request)~="requested")
            drops[1].x=1500;drops[1]["归属"]="Other"
            assert(adapter:pickup(target,request)~="requested")
            drops[1]["归属"]="";drops[1]["装备属性"]={name="魔化精英图鉴",kind=3}
            assert(adapter:pickup(target,request)~="requested")
            drops[1]["装备属性"]={name="追风",kind=1}
            for _,item in ipairs(items) do item.kind=1 end
            assert(adapter:pickup(target,request)=="full")
            assert(#called==0)
        ''')

    def test_current_bag_cells_follow_panel_movement_and_ignore_other_bags(self):
        from test_bag_geometry import Geometry
        self.lua.globals().Geometry = Geometry
        self.lua.execute('''
            package.path=package.path..";native/Mods/RuinsHelper/Scripts/?.lua"
            adapter:snapshot(request)
            local cells={};local dx,dy,now=0,0,10
            os.clock=function() return now end
            local callback
            RegisterHook=function(_,fn) callback=fn;return 1,2 end
            local tick=object({GetFullName=function() return "Function /Game/UI/Cell.Cell_C:Tick" end})
            for i=0,59 do
                local cell=object({["在背包"]=true,["在仓库"]=false,["格子ID"]=i,Tick=tick})
                cell.GetAddress=function() return 1000+i end
                cell.IsVisible=function() return true end
                cell.GetCachedGeometry=function() return {} end
                cells[i+1]=cell
            end
            -- Pinned UE4SS returns a list of RemoteUnrealParam wrappers here.
            -- The wrappers deliberately have no IsValid method.
            local wrap=object({GetAllChildren=function()
                local wrapped={}
                for i,cell in ipairs(cells) do wrapped[i]={get=function() return cell end} end
                return wrapped
            end, GetAddress=function() return 700 end, GetChildrenCount=function() return #cells end,
                GetChildAt=function(_,i) return cells[i+1] end})
            main["背包"]=object({["格子框"]=wrap})
            local slate=object({GetLocalSize=function() return {X=54,Y=54} end,
                LocalToViewport=function(_,pawn,g,p,out,view) out.X=g.x+p.X;out.Y=g.y+p.Y end})
            StaticFindObject=function() return slate end
            FindAllOf=function() error("Must use the current player's bag tree") end
            request.viewport={1200,900};request.monotonic=10
            local function frame()
                for n,cell in ipairs(cells) do
                    local i=n-1
                    local g=Geometry(100+i%10*60+dx,100+math.floor(i/10)*60+dy)
                    callback({get=function() return cell end},{get=function() return g end})
                end
            end
            assert(adapter:grid(request)==nil);frame()
            local first=adapter:grid(request)
            assert(first and first.slots["0"][1]==100 and first.slots["59"][2]==400)
            dx=150;dy=45;request.monotonic=10.1;now=10.1;frame()
            local moved=adapter:grid(request)
            assert(moved.slots["0"][1]==250 and moved.slots["59"][2]==445)
            local last=cells[60];cells[60]=nil
            assert(adapter:grid(request)==nil, "an incomplete bag must not reuse old positions")
            cells[60]=last
            cells[5]["格子ID"]=3
            assert(adapter:grid(request)==nil)
        ''')

    def test_equipment_exclusion_matches_exact_name_tier_and_part(self):
        self.setup_drops()
        self.lua.execute('''
            request.schema.actor_equipment="gear"
            request.schema.equipment_tier="tier";request.schema.equipment_type="part"
            request.excluded_equipment={["9:1:追风"]=true}
            drops[1]["装备属性"].gear={tier=9,part=1}
            assert(#adapter:nearby(request)==0)
            drops[1]["装备属性"].gear.tier=8
            local targets=adapter:nearby(request);assert(#targets==1)
            drops[1]["装备属性"].gear.tier=9
            assert(adapter:pickup(targets[1],request)~="requested")
            assert(#called==0)
        ''')

    def test_one_point_five_range_has_its_own_boundary(self):
        self.setup_drops()
        self.lua.execute('''
            request.pickup_radius=1500
            assert(#adapter:nearby(request)==1)
            drops[1].x=1501;assert(#adapter:nearby(request)==0)
        ''')


if __name__ == '__main__':unittest.main()
