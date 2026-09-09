-- SPDX-License-Identifier: MIT
-- Optional original-game rift RPC, with one eligibility decision per helper launch.
local M = {}
local CLASS = "/Game/Actors/裂隙/裂隙.裂隙_C"
local SPECIAL = "特殊属性_101_76EBA5AC4AF332228321C080A0295C7F"
local DROP = "掉落率+_179_31902C37471655F1A42F5194DDE4DDB0"
local ELITE = "极品率+_185_647BC2BD4F0D7071D6CEF0B1782B8821"
local function valid(o) return o and o:IsValid() end
local function finite(n) return type(n)=="number" and n==n and math.abs(n)<math.huge end
local function number(read)
    local ok, value = pcall(read)
    return ok and finite(value) and value or nil
end
local function qualify(level, drop, elite)
    level=finite(level) and level or nil
    drop=finite(drop) and drop or nil
    elite=finite(elite) and elite or nil
    local eligible=(level~=nil and level>=50) or (drop~=nil and elite~=nil and drop>=300 and elite>=300)
    return {eligible=eligible, checked=eligible or (level~=nil and level>=1 and drop~=nil and elite~=nil),
        level=level, extra_drop_pct=drop, extra_elite_pct=elite}
end
function M.qualification(player)
    -- Same fields used by UI/属性面板.额外掉落率 and Get_极品率_Text.
    -- Their integer values are already percent points: 300 means 300%.
    return qualify(number(function() return player["等级"] end),
        number(function() return player["总属性"][SPECIAL][DROP] end),
        number(function() return player["总属性"][SPECIAL][ELITE] end))
end
function M.new()
    local self={actors={},seen={},next_scan=0,requested=0,notified=false,fallback_at=0}
    function self:step(player,req,now,state)
        local run=req.rift_run_id
        if type(run)~="string" or #run<1 or #run>80 then return {state="waiting_for_helper",checked=false,eligible=false} end
        if self.run_id~=run then self.run_id=run;self.permission=nil;self.next_scan=0 end
        if not valid(player) or player:GetAddress()~=req.player_address or not player:IsLocallyControlled() then
            return {state="waiting_for_player",checked=false,eligible=false,run_id=run}
        end
        if not self.permission then
            local saved=req.rift_permission
            if type(saved)=="table" and saved.run_id==run and saved.checked==true then
                local restored=qualify(saved.level,saved.extra_drop_pct,saved.extra_elite_pct)
                if restored.checked and restored.eligible==saved.eligible then self.permission=restored end
            end
            if not self.permission then
                local candidate=M.qualification(player)
                if candidate.checked then self.permission=candidate end
            end
        end
        local report={run_id=run,checked=false,eligible=false,requested=self.requested,range=2000,interval=1}
        for key,value in pairs(self.permission or {}) do report[key]=value end
        if not report.checked then report.state="waiting_for_attributes";return report end
        if not report.eligible then report.state="not_qualified";return report end
        if req.auto_rift~=true then self.enabled=false;report.state="off";return report end
        if state.blocked or state.dragging then report.state="menu";return report end
        if not self.enabled or (self.last_clock and now<self.last_clock) then self.next_scan=0 end
        self.enabled=true;self.last_clock=now
        if now<self.next_scan then report.state=self.last_state or "watching";return report end
        self.next_scan=now+1
        local world=player:GetWorld()
        if not valid(world) then report.state="waiting_for_player";return report end
        local world_id=world:GetAddress()
        local reseed=self.world_id~=world_id
        if reseed then self.world_id=world_id;self.actors={} end
        if not self.notified then
            local ok=pcall(function()
                NotifyOnNewObject(CLASS,function(actor)
                    if valid(actor) then self.actors[actor:GetAddress()]=actor end
                end)
            end)
            self.notified=ok
        end
        -- Seed existing doors once; new doors arrive through the object notification.
        if reseed or (not self.notified and now>=self.fallback_at) then
            for _,actor in ipairs(FindAllOf("裂隙_C") or {}) do
                if valid(actor) then self.actors[actor:GetAddress()]=actor end
            end
            self.fallback_at=now+3
        end
        local origin=player:K2_GetActorLocation()
        if not finite(origin.X) or not finite(origin.Y) or not finite(origin.Z) then
            report.state="waiting_for_player";return report
        end
        local best
        for address,actor in pairs(self.actors) do
            if not valid(actor) then self.actors[address]=nil
            else
                local aw,cls=actor:GetWorld(),actor:GetClass()
                if not valid(aw) or aw:GetAddress()~=world_id then self.actors[address]=nil
                elseif valid(cls) and cls:GetFullName()=="BlueprintGeneratedClass "..CLASS then
                    local name=actor:GetFullName()
                    local key=tostring(world_id)..":"..tostring(address)..":"..name
                    if not self.seen[key] then
                        local pos,map=actor:K2_GetActorLocation(),actor["地图"]
                        if finite(pos.X) and finite(pos.Y) and finite(pos.Z) and finite(map) and map%1==0 and map>=0 and map<=255 then
                            local distance=(pos.X-origin.X)^2+(pos.Y-origin.Y)^2+(pos.Z-origin.Z)^2
                            if distance<=2000^2 and (not best or distance<best.distance) then
                                best={actor=actor,key=key,map=map,distance=distance}
                            end
                        end
                    end
                end
            end
        end
        report.state="watching"
        if best then
            local task=player["任务组件"]
            if not valid(task) then report.state="unavailable";return report end
            self.seen[best.key]=true
            local ok,err=pcall(function() task["服务器开启裂隙"](task,best.map,best.actor) end)
            if ok then
                self.requested=self.requested+1;report.requested=self.requested
                report.state="requested"
            else report.state="error";report.error=tostring(err) end
        end
        self.last_state=report.state
        return report
    end
    return self
end
return M
