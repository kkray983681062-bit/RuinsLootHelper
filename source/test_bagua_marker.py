"""Behavioral checks for portal selection, map projection and bounded UI allocation."""
from pathlib import Path
import math
import unittest
from lupa.lua54 import LuaRuntime

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / 'native' / 'Mods' / 'RuinsHelper' / 'Scripts'


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().core = self.lua.execute((SCRIPTS / 'bagua_core.lua').read_text(encoding='utf-8'))
        self.lua.execute('''
            s={entry=3,active=true,in_arena=true,enlarged=false,ui_key='map-A',
               target={X=100,Y=0,Z=0},player={X=0,Y=0,Z=0},
               center={X=0,Y=0,Z=0},extent={X=-2776,Y=1792,Z=0},
               size=7000,fixed_size=7000,map_size=7000,origin={X=20,Y=40}}
            renderer={created=0,moved=0,hidden=0,detached=0,alive=false}
            function renderer:attach(context) self.created=self.created+1;self.alive=true end
            function renderer:valid() return self.alive end
            function renderer:move(x,y) self.moved=self.moved+1;self.x=x;self.y=y end
            function renderer:hide() self.hidden=self.hidden+1 end
            function renderer:detach() self.detached=self.detached+1;self.alive=false end
            control=core.new(renderer)
        ''')

    def test_projection_matches_minus_45_degree_game_rotation(self):
        p = self.lua.eval('core.project(s)')
        self.assertAlmostEqual(p['X'], 20 + 100 / math.sqrt(2))
        self.assertAlmostEqual(p['Y'], 40 - 100 / math.sqrt(2))

    def test_zoom_and_map_extent_scale_together(self):
        self.lua.execute('s.size=3500;s.map_size=14000')
        p = self.lua.eval('core.project(s)')
        self.assertAlmostEqual(p['X'], 20 + 25 / math.sqrt(2))
        self.assertAlmostEqual(p['Y'], 40 - 25 / math.sqrt(2))

    def test_all_eight_portals_and_no_uninitialized_guess(self):
        self.lua.execute('''
            for i=1,8 do s.entry=i;assert(core.project(s)) end
            for _,i in ipairs({0,-1,9,2.5}) do s.entry=i;assert(core.project(s)==nil) end
        ''')

    def test_inactive_wrong_arena_and_big_map_hide(self):
        for mutation in ['s.active=false', 's.in_arena=false', 's.enlarged=true']:
            with self.subTest(mutation=mutation):
                self.lua.execute('s.active=true;s.in_arena=true;s.enlarged=false;' + mutation)
                self.assertIsNone(self.lua.eval('core.project(s)'))

    def test_invalid_coordinates_and_zero_scale_are_rejected(self):
        self.lua.execute('''
            s.extent={X=0,Y=0,Z=0};assert(core.project(s)==nil)
            s.extent={X=-2776,Y=1792,Z=0};s.fixed_size=0;assert(core.project(s)==nil)
            s.fixed_size=7000;s.target.X=0/0;assert(core.project(s)==nil)
            s.target.X=math.huge;assert(core.project(s)==nil)
        ''')

    def test_ten_thousand_unchanged_updates_reuse_one_widget(self):
        self.lua.execute('for i=1,10000 do control:update(s) end')
        self.assertEqual(self.lua.eval('renderer.created'), 1)
        self.assertEqual(self.lua.eval('renderer.moved'), 1)

    def test_moving_target_updates_position_without_allocating(self):
        self.lua.execute('control:update(s);s.target.X=200;control:update(s)')
        self.assertEqual(self.lua.eval('renderer.created'), 1)
        self.assertEqual(self.lua.eval('renderer.moved'), 2)

    def test_exit_and_reentry_hide_and_reuse(self):
        self.lua.execute('control:update(s);control:update(nil);control:update(nil);control:update(s)')
        self.assertEqual(self.lua.eval('renderer.created'), 1)
        self.assertEqual(self.lua.eval('renderer.hidden'), 1)
        self.assertEqual(self.lua.eval('renderer.moved'), 2)

    def test_new_map_releases_old_marker(self):
        self.lua.execute("control:update(s);s.ui_key='map-B';control:update(s)")
        self.assertEqual(self.lua.eval('renderer.created'), 2)
        self.assertEqual(self.lua.eval('renderer.detached'), 1)

    def test_attach_failure_does_not_allocate_again_on_every_poll(self):
        self.lua.execute('''
            function renderer:attach(context) self.created=self.created+1;error('unavailable') end
            for i=1,20 do pcall(function() control:update(s) end) end
        ''')
        self.assertEqual(self.lua.eval('renderer.created'), 1)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().module = self.lua.execute((SCRIPTS / 'bagua_game.lua').read_text(encoding='utf-8'))
        self.lua.execute('''
            function obj(t,id)
                t.alive=true;t.IsValid=function(s) return s.alive end
                t.GetAddress=function() return id end;return t
            end
            player=obj({IsLocallyControlled=function() return true end,
                K2_GetActorLocation=function() return {X=0,Y=0,Z=0} end},100)
            list={player,GetArrayNum=function(s) return #s end}
            arena=obj({["已启动"]=true,["入口编号"]=1,["Other Actor"]=list},101)
            for i=1,8 do local j=i;arena['Sphere'..i]=obj({K2_GetComponentLocation=function() return {X=j*100,Y=j*10,Z=0} end},110+i) end
            anchors={Minimum={X=.5,Y=.5},Maximum={X=.5,Y=.5}}
            oldslot=obj({GetAnchors=function() return anchors end,GetPosition=function() return {X=20,Y=40} end,
                GetSize=function() return {X=10,Y=10} end,GetAlignment=function() return {X=.5,Y=.5} end},120)
            newslot=obj({},121)
            for _,n in ipairs({'SetAutoSize','SetAnchors','SetAlignment','SetSize','SetZOrder','SetPosition'}) do
                local name=n;newslot[name]=function(s,value) s[name..'Value']=value end
            end
            parent=obj({AddChildToCanvas=function(s,child) s.child=child;return newslot end},122)
            reference=obj({Slot=oldslot,GetParent=function() return parent end},123)
            normal={readonly='original brush'}
            button=obj({WidgetStyle={Normal=normal}},124)
            ui=obj({["队友0框"]=reference,["队友0"]=button,["放大"]=false,
                ["地图中心点坐标"]={X=0,Y=0,Z=0},["地图目标像素坐标"]={X=-2776,Y=1792,Z=0},
                ["尺寸"]=7000,["固定地图尺寸"]=7000,["更改地图尺寸"]=7000,
                IsVisible=function() return true end,GetOwningPlayerPawn=function() return player end,
                WidgetTree=obj({},125)},126)
            imageClass=obj({},127)
            StaticFindObject=function(path) assert(path=='/Script/UMG.Image');return imageClass end
            FName=function(name) return {typed_name=name} end
            constructor_calls=0
            StaticConstructObject=function(class,outer,name)
                assert(class==imageClass and outer==ui.WidgetTree and name.typed_name)
                constructor_calls=constructor_calls+1
                marker=obj({},128)
                for _,n in ipairs({'SetVisibility','SetBrush','SetBrushTintColor','SetColorAndOpacity'}) do
                    local k=n;marker[k]=function(s,value) s[k..'Value']=value end
                end
                marker.RemoveFromParent=function(s) s.removed=true end
                return marker
            end
            scans=0
            FindAllOf=function(name)
                scans=scans+1
                if name=='八卦_C' then return {arena} end
                assert(name=='小地图UI_C');return {ui}
            end
            game=module.new();game:discover_once()
        ''')

    def test_each_entry_uses_corresponding_sphere(self):
        self.lua.execute('''
            for i=1,8 do arena["入口编号"]=i;local s=game:snapshot()
                assert(s.entry==i and s.target.X==i*100) end
        ''')

    def test_arena_membership_is_local_player_specific(self):
        self.lua.execute("list[1]=obj({},999);assert(game:snapshot()==nil)")

    def test_multiple_active_arenas_are_not_guessed(self):
        self.lua.execute('''
            local second=obj({["已启动"]=true,["入口编号"]=2,["Other Actor"]=list},102)
            game:remember('arenas',second);assert(game:snapshot()==nil)
        ''')

    def test_no_target_when_map_is_enlarged_or_entry_unset(self):
        self.lua.execute('''
            ui["放大"]=true;assert(game:snapshot()==nil)
            ui["放大"]=false;arena["入口编号"]=0;assert(game:snapshot()==nil)
        ''')

    def test_own_marker_is_red_and_click_through(self):
        self.lua.execute('''
            local sample=game:snapshot();game:attach(sample.context);game:move(90,80)
            assert(parent.child==marker and marker.SetVisibilityValue==3)
            assert(marker.SetColorAndOpacityValue.R==1 and marker.SetColorAndOpacityValue.G<.1)
            assert(newslot.SetPositionValue.X==90 and newslot.SetPositionValue.Y==80)
            assert(button.WidgetStyle.Normal==normal and normal.readonly=='original brush')
            assert(newslot.SetSizeValue.X==10)
        ''')

    def test_snapshot_does_not_rescan_all_objects(self):
        self.lua.execute('for i=1,1000 do game:discover_once();game:snapshot() end;assert(scans==2)')

    def test_first_teammate_offset_does_not_shift_local_portal(self):
        self.lua.execute('''
            oldslot.GetPosition=function() return {X=200,Y=-100} end
            local s=game:snapshot();assert(s.origin.X==0 and s.origin.Y==0)
        ''')

    def test_dead_ui_or_arena_hides_and_drops_reference(self):
        self.lua.execute('arena.alive=false;assert(game:snapshot()==nil);assert(next(game.arenas)==nil)')


# Scheduling is now owned by the shared bridge; see test_bagua_control.py.

if __name__ == '__main__':
    unittest.main()
