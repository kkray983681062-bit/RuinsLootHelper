-- SPDX-License-Identifier: MIT
-- Extend the game's existing drop decision; never destroy actors or inventory.
-- Verified on 1.15: params 1=格子属性, 2=玩家, 22=是否屏蔽 (Bool out).
-- Pinned UE4SS 2bfa839f invokes Blueprint hooks after the script and exposes
-- out-parameters through RemoteUnrealParam:set (LuaMod.cpp:6284-6376).
local M = {}
local PATH = "/Game/公用/NewFunctionLibrary.NewFunctionLibrary_C:屏蔽条件判断"
local function valid(o) return o and o:IsValid() end
local function text(value)
    if type(value) == "string" then return value end
    return value:ToString()
end

function M.new()
    local self = {blocked=0, calls=0, retry_at=0}
    function self:apply(...)
        local req = self.request
        if self.error or not req or req.protocol ~= 4 or not req.block_drops or
            type(req.expires) ~= "number" or os.time() > req.expires then return end
        if select("#", ...) ~= 22 then error("Drop filter signature changed (expected 22 parameters)") end
        local args = {...}
        local player = args[2]:get()
        if not valid(player) or player:GetAddress() ~= req.player_address or not player:IsLocallyControlled() then return end
        self.calls = self.calls + 1
        local output = args[22]
        local original = output:get()
        if type(original) ~= "boolean" then error("Drop filter output is not boolean") end
        if original then return end -- Add exclusions without undoing the official ones.
        local schema, item = req.schema, args[1]:get()
        if not schema or not schema.actor_kind or not schema.actor_name then error("Drop filter item schema unavailable") end
        local kind = item[schema.actor_kind]
        local name = text(item[schema.actor_name])
        local blocked = kind == 3 and (req.codex_names or {})[name]
        if kind == 1 and next(req.excluded_equipment or {}) then
            if not schema.actor_equipment or not schema.equipment_tier or not schema.equipment_type then
                error("Drop filter equipment schema unavailable")
            end
            local gear = item[schema.actor_equipment]
            local key = string.format("%d:%d:%s", gear[schema.equipment_tier], gear[schema.equipment_type], name)
            blocked = req.excluded_equipment[key]
        end
        if blocked then
            output:set(true)
            if output:get() ~= true then error("Drop filter output readback failed") end
            self.blocked = self.blocked + 1
            self.last_name = name
        end
    end

    function self:update(req)
        if self.session ~= req.session then
            self.session, self.error, self.blocked, self.calls = req.session, nil, 0, 0
            self.last_name = nil
        end
        self.request = req
        local enabled = req.protocol == 4 and req.block_drops == true
        if enabled and not self.ids and not self.error and os.time() >= self.retry_at then
            self.retry_at = os.time() + 2
            local fn = StaticFindObject(PATH)
            if valid(fn) then
                local ok, first, last = pcall(function()
                    return RegisterHook(PATH, function(_, ...)
                        local success, err = pcall(self.apply, self, ...)
                        if not success then self.error = tostring(err) end
                    end)
                end)
                if ok and type(first) == "number" and type(last) == "number" then
                    self.ids = {first, last}
                else self.error = tostring(first) end
            end
        end
        return {state=self.error and "error" or not enabled and "off" or self.ids and "connected" or "waiting_for_function",
                blocked=self.blocked, calls=self.calls, last_name=self.last_name, error=self.error}
    end
    return self
end
return M
