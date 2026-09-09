"""Exercise selected exclusions at the official filter's boolean output."""
import unittest
from lupa import LuaRuntime


class NativeDropFilterTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
            package.path="native/Mods/RuinsHelper/Scripts/?.lua;"..package.path
            Filter=require("drop_filter")
            ticks=100;os.time=function() return ticks end
            player={IsValid=function() return true end,GetAddress=function() return 123 end,
                IsLocallyControlled=function() return true end}
            local fn={IsValid=function() return true end}
            StaticFindObject=function(path) return fn end
            registered=0
            RegisterHook=function(path,callback)
                registered=registered+1;hook=callback;hook_path=path;return 10,10
            end
            filter=Filter.new()
            request={protocol=4,session="session",player_address=123,expires=101,
                block_drops=true,codex_names={["人形地魔"]=true},
                excluded_equipment={["9:1:追风"]=true},
                schema={actor_kind="kind",actor_name="name",actor_equipment="gear",
                    equipment_tier="tier",equipment_type="part"}}
            function wrap(value)
                return {get=function() return value end,set=function(_,v) value=v end}
            end
            function apply(item,owner,blocked)
                local args={wrap(item),wrap(owner or player)}
                for i=3,21 do args[i]=wrap({}) end
                args[22]=wrap(blocked or false)
                hook(wrap({}),table.unpack(args))
                return args[22]:get()
            end
        ''')

    def test_blocks_selected_codex_and_exact_equipment_preserving_official_results(self):
        self.lua.execute('''
            assert(filter:update(request).state=="connected" and registered==1)
            assert(apply({kind=3,name="人形地魔"}))
            assert(not apply({kind=3,name="魔化主帅"}))
            assert(not apply({kind=3,name="药水"}))
            assert(apply({kind=1,name="追风",gear={tier=9,part=1}}))
            assert(not apply({kind=1,name="追风",gear={tier=8,part=1}}))
            assert(apply({kind=3,name="药水"},player,true),"never undo official blocking")
            assert(filter:update(request).blocked==2)
            assert(registered==1)
        ''')

    def test_no_block_for_expired_requests_other_players_disabled_or_changed_player(self):
        self.lua.execute('''
            filter:update(request)
            local item={kind=3,name="人形地魔"}
            local other={IsValid=function() return true end,GetAddress=function() return 456 end,
                IsLocallyControlled=function() return true end}
            assert(not apply(item,other))
            ticks=102;assert(not apply(item));ticks=100
            request.block_drops=false;filter:update(request);assert(not apply(item))
            request.block_drops=true;request.player_address=456;filter:update(request)
            assert(not apply(item,player))
        ''')

    def test_checkbox_changes_apply_without_rehook_and_empty_selection_preserves_drop(self):
        self.lua.execute('''
            filter:update(request)
            assert(apply({kind=3,name="人形地魔"}))
            request.codex_names={};request.excluded_equipment={};request.block_drops=false
            assert(filter:update(request).state=="off")
            assert(not apply({kind=3,name="人形地魔"}))
            request.codex_names={["魔化主帅"]=true};request.block_drops=true
            filter:update(request)
            assert(apply({kind=3,name="魔化主帅"}))
            assert(registered==1)
        ''')

    def test_schema_error_or_signature_mismatch_leaves_original_output_untouched(self):
        self.lua.execute('''
            filter:update(request)
            assert(not apply({kind=3}))
            local state=filter:update(request)
            assert(state.error and state.state=="error")
            local output=wrap(false)
            hook(wrap({}),wrap({kind=3,name="人形地魔"}),wrap(player),output)
            assert(not output:get())
        ''')


if __name__=='__main__':unittest.main()
