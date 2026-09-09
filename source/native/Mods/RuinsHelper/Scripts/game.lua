-- SPDX-License-Identifier: MIT
-- Ruins of Dawn 1.15 / UE 5.5 adapter. All methods execute on the game thread.
local M = { actors = {}, refresh_at = 0, notified = false }
local function valid(o) return o and o:IsValid() end
local function flag(o, key)
    local value = o[key]
    if type(value) ~= "boolean" then error("Missing boolean: " .. key) end
    return value
end
local function string_value(v)
    if type(v) == "string" then return v end
    return v:ToString()
end
local function invoke(o, name, ...) return o[name](o, ...) end
local function leaf(o, path)
    for _, key in ipairs(path) do o = o[key] end
    return o
end

function M:resolve(req)
    if valid(self.player) and self.player:GetAddress() == req.player_address and valid(self.main) then return true end
    self.main, self.player = nil, nil
    self.cached_grid, self.grid_at = nil, 0
    for _, main in ipairs(FindAllOf("主UI_C") or {}) do
        if valid(main) then
            local pawn = main["对应玩家"]
            if valid(pawn) and pawn:GetAddress() == req.player_address and pawn:IsLocallyControlled() then
                self.main, self.player = main, pawn
                break
            end
        end
    end
    return self.player ~= nil
end

function M:snapshot(req)
    if not self:resolve(req) or type(req.schema) ~= "table" then return {valid=false} end
    self.schema = req.schema
    self.bag = self.player["背包物品简化"]
    if self.bag:GetArrayNum() < 60 then return {valid=false} end
    local occupied = 0
    for i = 0, 59 do
        if self.bag[i + 1][self.schema.item_kind] ~= 0 then occupied = occupied + 1 end
    end
    local bag_open = flag(self.main, "背包开启")
    local blocked = false
    for _, key in ipairs({"角色栏开启", "技能栏开启", "设置开启", "玩家列表开启", "是否黑屏"}) do
        if flag(self.main, key) then blocked = true end
    end
    local dragging = flag(self.player, "物品拖拽中") or flag(self.player, "技能拖拽")
    for _, key in ipairs({"仓库开启", "1打开商店", "地图开关", "打开悬赏面板", "打开锻造", "服务器正在回城"}) do
        if flag(self.player, key) then blocked = true end
    end
    for name, flags in pairs({["图鉴UI"]={"打开"}, ["聊天窗口"]={"展开"},
        ["辅助设置"]={"打开设置界面"}, ["附魔"]={"开关附魔面板","开关转移面板","开关提取面板"}}) do
        local panel = self.main[name]
        if valid(panel) then
            for _, key in ipairs(flags) do if flag(panel, key) then blocked = true end end
        end
    end
    return {valid=true, player_address=self.player:GetAddress(), backpack_open=bag_open,
        blocked=blocked or bag_open or dragging, recycle_blocked=blocked or dragging,
        dragging=dragging, free_slots=60-occupied}
end

function M:update_drop_filter(req)
    if not self.drop_filter then self.drop_filter = require("drop_filter").new() end
    return self.drop_filter:update(req)
end

function M:borderless()
    local defaults = StaticFindObject("/Script/Engine.Default__GameUserSettings")
    if not valid(defaults) then return "unavailable" end
    local settings = defaults:GetGameUserSettings()
    if not valid(settings) then return "unavailable" end
    if settings:GetFullscreenMode() == 0 then
        settings:SetFullscreenMode(1)
        settings:ApplyResolutionSettings(false)
        return "borderless"
    end
    return "already_compatible"
end

function M:lock(cmd)
    if type(cmd.index) ~= "number" or cmd.index % 1 ~= 0 or cmd.index < 0 or cmd.index > 59 then return "bad_index" end
    -- UE4SS TArray indexes are Lua 1-based; the native RPC index remains 0-based.
    local item = self.bag[cmd.index + 1]
    if item[self.schema.locked] then return "already_locked" end
    if type(cmd.expected) ~= "table" or #cmd.expected < 5 then return "missing_identity" end
    for _, expected in ipairs(cmd.expected) do
        local value = leaf(item, expected.path)
        if expected.kind == "NameProperty" then value = string_value(value) end
        if type(value) == "number" and type(expected.value) == "number" then
            if math.abs(value - expected.value) > .0001 then return "item_changed" end
        elseif value ~= expected.value then return "item_changed" end
    end
    -- This native function TOGGLES lock; the explicit false check above is vital.
    invoke(self.player, "服务器锁定装备", cmd.index)
    return item[self.schema.locked] and "locked" or "awaiting_readback"
end

function M:recycle(cmd, req)
    if req.auto_recycle ~= true or req.auto_lock ~= true then return "off" end
    local state = self:snapshot(req)
    if not state.valid or state.player_address ~= req.player_address then return "waiting_for_current_player" end
    if not req.active or state.recycle_blocked or state.dragging then return "paused" end
    if state.free_slots > 1 then return "waiting_for_space_trigger" end
    if type(cmd) ~= "table" or type(cmd.columns) ~= "table" or #cmd.columns < 5 or
       type(cmd.rows) ~= "table" or #cmd.rows > 60 or
       type(cmd.slots) ~= "table" or #cmd.slots ~= 60 or
       type(cmd.protected) ~= "table" then return "invalid_proof" end
    local rows, protected = {}, {}
    for _, row in ipairs(cmd.rows) do
        local index = row.index
        if type(index) ~= "number" or index % 1 ~= 0 or index < 0 or index > 59 or rows[index] or
           type(row.locked) ~= "boolean" or type(row.values) ~= "table" or #row.values ~= #cmd.columns then
            return "invalid_proof"
        end
        rows[index] = row
    end
    for _, index in ipairs(cmd.protected) do
        if not rows[index] or not rows[index].locked then return "invalid_proof" end
        protected[index] = true
    end
    local eligible = false
    for index = 0, 59 do
        local item, row = self.bag[index + 1], rows[index]
        local kind = item[self.schema.item_kind]
        local slot = cmd.slots[index + 1]
        if type(slot) ~= "table" or #slot ~= 2 or type(slot[1]) ~= "number" or
           type(slot[2]) ~= "boolean" then return "invalid_proof" end
        if kind ~= slot[1] or item[self.schema.locked] ~= slot[2] then return "inventory_changed" end
        if kind == 1 then
            -- Every piece of equipment must have been inspected by the
            -- filter. A new item replacing a potion cannot bypass this guard.
            if not row or item[self.schema.locked] ~= row.locked then return "inventory_changed" end
            if protected[index] and not item[self.schema.locked] then return "inventory_changed" end
            for column, field in ipairs(cmd.columns) do
                local value, expected = leaf(item, field.path), row.values[column]
                if field.kind == "NameProperty" then value = string_value(value) end
                if type(value) == "number" and type(expected) == "number" then
                    if value ~= value or expected ~= expected or math.abs(value) == math.huge or
                       math.abs(expected) == math.huge or math.abs(value - expected) > .0001 then return "inventory_changed" end
                elseif value ~= expected then return "inventory_changed" end
            end
        elseif row then
            return "inventory_changed"
        end
        if not item[self.schema.locked] and (kind == 1 or kind == 4) then eligible = true end
    end
    if not eligible then return "nothing_to_recycle" end
    local panel = self.main["背包"]
    if not valid(panel) then return "waiting_for_inventory" end
    -- This is the official red button's zero-argument click event. The game
    -- reads its own gold/XP selection and calls 全部回收; it skips locks and
    -- storage slots. No helper currency setting or replacement recycle loop.
    invoke(panel, "BndEvt__背包ui_一键回收_1_K2Node_ComponentBoundEvent_7_OnButtonClickedEvent__DelegateSignature")
    return "requested"
end

function M:drop_allowed(actor, req, skipped)
    -- UE4SS marshals NameProperty arguments from FName userdata. Passing a
    -- Lua string here crashes in push_nameproperty before ActorHasTag runs.
    if not valid(actor) or not actor:ActorHasTag(FName("物品")) then return false end
    if actor:GetWorld():GetAddress() ~= self.player:GetWorld():GetAddress() then return false end
    local here, pos = self.player:K2_GetActorLocation(), actor:K2_GetActorLocation()
    local distance = (pos.X-here.X)^2 + (pos.Y-here.Y)^2 + (pos.Z-here.Z)^2
    local radius = ({[1000]=true,[1500]=true,[2000]=true})[req.pickup_radius] and req.pickup_radius or 1000
    if distance > radius^2 then return false end
    local player_name = string_value(self.player.PlayerState["名字"])
    player_name = player_name:match("_(.*)$") or player_name
    local owner = string_value(actor["归属"])
    if owner ~= "" and owner ~= player_name then return false end
    local exclusions = req.excluded_equipment or {}
    if req.skip_codex or next(exclusions) ~= nil then
        if not self.schema.actor_name or not self.schema.actor_kind then error("Drop item schema unavailable") end
        local item = actor["装备属性"]
        local kind = item[self.schema.actor_kind]
        local name = string_value(item[self.schema.actor_name])
        -- Codex row names omit the displayed suffix (e.g. 人形地魔).
        -- Use the official table's internal names, independent of UI language.
        if req.skip_codex and kind ~= 1 and ((req.codex_names or {})[name] or
            (req.skip_unknown_codex ~= false and name:match("图鉴$"))) then
            if skipped then skipped.codex = skipped.codex + 1 end
            return false
        end
        if kind == 1 and next(exclusions) ~= nil then
            if not self.schema.actor_equipment or not self.schema.equipment_tier or not self.schema.equipment_type then
                error("Equipment exclusion schema unavailable")
            end
            local gear = item[self.schema.actor_equipment]
            local tier, part = gear[self.schema.equipment_tier], gear[self.schema.equipment_type]
            local key = string.format("%d:%d:%s", tier, part, name)
            if exclusions[key] then
                if skipped then skipped.equipment = skipped.equipment + 1 end
                return false
            end
        end
    end
    return true, distance
end

function M:clock()
    if not valid(self.gameplay_statics) then
        self.gameplay_statics = StaticFindObject("/Script/Engine.Default__GameplayStatics")
    end
    if not valid(self.gameplay_statics) then error("Game clock unavailable") end
    return self.gameplay_statics:GetRealTimeSeconds(self.player)
end

function M:nearby(req)
    if not self.notified then
        local class = StaticFindObject("/Game/物品数据/物品actor/物品.物品_C")
        if valid(class) then
            NotifyOnNewObject("/Game/物品数据/物品actor/物品.物品_C", function(object)
                self.actors[object:GetAddress()] = object
            end)
            self.notified = true
        end
    end
    if os.time() >= self.refresh_at then
        self.actors = {}
        for _, actor in ipairs(FindAllOf("物品_C") or {}) do
            if valid(actor) then self.actors[actor:GetAddress()] = actor end
        end
        self.refresh_at = os.time() + 3
    end
    local result = {}
    self.scan_exclusions = {codex=0, equipment=0}
    for address, actor in pairs(self.actors) do
        if not valid(actor) then self.actors[address] = nil
        else
            local allowed, distance = self:drop_allowed(actor, req, self.scan_exclusions)
            if allowed then table.insert(result, {id=tostring(address)..":"..actor:GetFullName(), actor=actor, distance=distance}) end
        end
    end
    table.sort(result, function(a,b) return a.distance < b.distance end)
    return result
end

function M:pickup(target, req)
    local state = self:snapshot(req)
    if not state.valid or state.player_address ~= req.player_address then return "waiting_for_current_player" end
    if not req.active or not req.pickup or state.blocked then return "paused" end
    if state.free_slots <= 0 then return "full" end
    if not target or not self:drop_allowed(target.actor, req) then return "drop_changed" end
    local id = tostring(target.actor:GetAddress())..":"..target.actor:GetFullName()
    if id ~= target.id then return "drop_changed" end
    -- Native per-actor RPC performs conversion, auto-recycle, capacity checks,
    -- and removes the actor only after success. A bulk call would also collect
    -- excluded codex drops and keep its hard-coded 1000-unit radius.
    invoke(self.player, "服务器拾取物品", target.actor)
    return "requested"
end

function M:grid(req)
    local slate = StaticFindObject("/Script/UMG.Default__SlateBlueprintLibrary")
    if not valid(slate) or not req.viewport then return nil end
    local panel = self.main["背包"]
    if not valid(panel) then return nil end
    local wrap = panel["格子框"]
    if not valid(wrap) then return nil end
    -- GetAllChildren returns RemoteUnrealParam entries in pinned UE4SS, not
    -- UWidget objects (calling IsValid on those wrappers raises an error).
    -- GetChildAt returns the actual UObject directly, with a zero-based index.
    if wrap:GetChildrenCount() ~= 60 then return nil end
    local slots, count = {}, 0
    -- Traverse the active player's 60 main-bag cells, not all live widgets
    -- (storage, hidden copies and other players can reuse the same slot ids).
    -- Read geometry afresh so moving the bag does not reuse the old position.
    for i = 0, 59 do
        local widget = wrap:GetChildAt(i)
        if valid(widget) and flag(widget, "在背包") and not flag(widget, "在仓库") then
            local index = widget["格子id"]
            if type(index) == "number" and index >= 0 and index < 60 and widget:IsVisible() then
                local geometry = widget:GetCachedGeometry()
                local size = slate:GetLocalSize(geometry)
                local first, first_view, last, last_view = {}, {}, {}, {}
                slate:LocalToViewport(self.player, geometry, {X=0,Y=0}, first, first_view)
                slate:LocalToViewport(self.player, geometry, {X=size.X,Y=size.Y}, last, last_view)
                if first.X and last.X and first.Y and last.Y and last.X > first.X + 8 and last.Y > first.Y + 8 then
                    local key = tostring(index)
                    if slots[key] then return nil end
                    slots[key] = {first.X, first.Y, last.X, last.Y}
                    count = count + 1
                end
            end
        end
    end
    if count ~= 60 then return nil end
    return {slots=slots, viewport=req.viewport, player_address=self.player:GetAddress()}
end
return M
