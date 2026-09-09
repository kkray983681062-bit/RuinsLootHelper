-- SPDX-License-Identifier: MIT
-- Native workflow policy. The adapter alone can call game functions.
local M = {}
function M.new(adapter)
    local self = { adapter = adapter, attempts = {}, seen = {}, seen_order = {}, acks = {}, last_pick = -100, last_recycle = -100, next_scan = 0, session = nil }
    function self:step(req, now, utc)
        if type(req) ~= "table" or req.protocol ~= 4 or type(req.expires) ~= "number" or utc > req.expires then
            if self.adapter.stop_grid then self.adapter:stop_grid() end
            if self.adapter.stop_bagua then self.adapter:stop_bagua() end
            return { ready = false, state = "helper_offline" }
        end
        if self.session ~= req.session then
            self.session = req.session
            self.attempts, self.seen, self.seen_order, self.acks = {}, {}, {}, {}
            self.next_scan = 0
            self.last_recycle = -100
        end
        local state = self.adapter:snapshot(req)
        if not state.valid or state.player_address ~= req.player_address then
            if self.adapter.stop_grid then self.adapter:stop_grid() end
            if self.adapter.stop_bagua then self.adapter:stop_bagua() end
            return { ready = false, state = "waiting_for_current_player" }
        end
        -- Use the game's real clock rather than the last mailbox timestamp,
        -- so a 0.15 s interval is not rounded up to the file polling period.
        if self.adapter.clock then now = self.adapter:clock() end
        if type(now) ~= "number" or now ~= now or now == math.huge or now < 0 then
            if self.adapter.stop_bagua then self.adapter:stop_bagua() end
            return {ready=false,state="invalid_clock"}
        end
        if self.last_clock and now < self.last_clock then
            self.next_scan=0;self.attempts={};self.last_recycle=-100
        end
        self.last_clock=now
        local result = { ready = true, state = "ready", player_address = state.player_address,
            backpack_open = state.backpack_open, free_slots = state.free_slots, acks = self.acks,
            auto_recycle_supported = type(self.adapter.recycle) == "function" }
        if self.adapter.bagua_step then
            result.bagua_supported = true
            local ok, marker = pcall(function() return self.adapter:bagua_step(req,now) end)
            result.bagua = ok and marker or {state='error',error=tostring(marker)}
            if not ok and self.adapter.stop_bagua then pcall(function() self.adapter:stop_bagua() end) end
        end
        if self.adapter.rift_step then
            result.rift_supported = true
            local ok, rift = pcall(function() return self.adapter:rift_step(req, now, state) end)
            result.rift = ok and rift or {state="error", checked=false, eligible=false, error=tostring(rift)}
        end
        if self.adapter.update_drop_filter then
            local ok, status = pcall(function() return self.adapter:update_drop_filter(req) end)
            result.drop_filter = ok and status or {state="error", error=tostring(status)}
        end
        if req.borderless and req.active and not self.borderless_done then
            local ok, mode = pcall(function() return self.adapter:borderless() end)
            if ok and mode ~= "unavailable" then self.borderless_done = true end
            result.fullscreen = ok and mode or "unavailable"
        elseif not req.borderless then self.borderless_done = false end
        if req.markers and state.backpack_open and req.active then
            local ok, grid, info = pcall(function() return self.adapter:grid(req) end)
            if ok then result.grid, result.grid_status = grid, info
            else
                result.grid_error = tostring(grid)
                if self.adapter.stop_grid then self.adapter:stop_grid() end
            end
        elseif self.adapter.stop_grid then
            self.adapter:stop_grid()
        end
        if req.active and not state.dragging then
            for _, cmd in ipairs(req.locks or {}) do
                if not self.seen[cmd.id] then
                    self.seen[cmd.id] = true
                    table.insert(self.seen_order, cmd.id)
                    if #self.seen_order > 256 then self.seen[table.remove(self.seen_order, 1)] = nil end
                    local ok, value = pcall(function() return self.adapter:lock(cmd) end)
                    table.insert(self.acks, { id = cmd.id, result = ok and value or "error" })
                    if #self.acks > 32 then table.remove(self.acks, 1) end
                end
            end
        end
        result.recycle_state = "off"
        if req.auto_recycle == true and req.auto_lock == true and result.auto_recycle_supported then
            result.recycle_state = req.recycle_wait or "waiting_for_inventory"
            local blocked = state.recycle_blocked
            if blocked == nil then blocked = state.blocked end
            if req.active and not blocked and not state.dragging and state.free_slots <= 1 then
                local cmd = req.recycle
                if type(cmd) == "table" and type(cmd.id) == "string" then
                    if not self.seen[cmd.id] and now >= self.last_recycle + 2 then
                        self.seen[cmd.id] = true
                        table.insert(self.seen_order, cmd.id)
                        if #self.seen_order > 256 then self.seen[table.remove(self.seen_order, 1)] = nil end
                        self.last_recycle = now
                        local ok, value = pcall(function() return self.adapter:recycle(cmd, req) end)
                        result.recycle_state = ok and value or "error"
                        table.insert(self.acks, {id=cmd.id, result=result.recycle_state})
                        if #self.acks > 32 then table.remove(self.acks, 1) end
                    else
                        result.recycle_state = "waiting_for_result"
                    end
                    -- Let the next snapshot observe the official call before more pickups.
                    result.pickup_state = req.pickup and "recycling" or "off"
                    return result
                end
            end
        end
        if not req.pickup then self.next_scan=0;result.pickup_state = "off"; return result end
        if not req.active then self.next_scan=0;result.pickup_state = "inactive"; return result end
        if state.blocked or state.backpack_open then self.next_scan=0;result.pickup_state = "menu"; return result end
        if state.free_slots <= 0 then
            self.was_full = true
            self.next_scan = 0
            result.pickup_state = "full"
            return result
        end
        if self.was_full then self.attempts = {}; self.was_full = false; self.next_scan = 0 end
        local interval = ({[1]=true,[.5]=true,[.35]=true,[.15]=true})[req.pickup_interval] and req.pickup_interval or .35
        local batch = ({[0]=true,[1]=true,[2]=true,[3]=true,[4]=true})[req.pickup_batch] and req.pickup_batch or 0
        local options = tostring(interval)..":"..batch..":"..tostring(req.pickup_radius)..":"..tostring(req.pickup_revision)
        if self.options ~= options then
            self.options=options;self.next_scan=0;self.attempts={}
        end
        if now + .000001 < self.next_scan then
            result.exclusions = self.adapter.scan_exclusions
            result.pickup_state=self.last_pickup_state or "waiting_for_loot";return result
        end
        self.next_scan = now + interval
        local deadline = batch == 0 and (os.clock() + .004) or nil
        local nearby = self.adapter:nearby(req)
        result.exclusions = self.adapter.scan_exclusions
        local present, eligible = {}, {}
        for _, target in ipairs(nearby) do
            present[target.id] = true
            local attempt = self.attempts[target.id]
            if not attempt or (attempt.count < 3 and now - attempt.time >= .6) then table.insert(eligible, target) end
        end
        for key, _ in pairs(self.attempts) do
            if not present[key] then
                self.attempts[key] = nil
                result.pickup_confirmed = true
            end
        end
        result.nearby = #nearby
        if #eligible > 0 then
            local requested = 0
            -- Automatic batches yield after about 4 ms of work, then continue
            -- on a later game-thread callback. One RPC itself cannot be split.
            local limit = math.min(batch == 0 and #eligible or batch, #eligible, state.free_slots)
            for i = 1, limit do
                local target = eligible[i]
                local outcome = self.adapter:pickup(target, req)
                if outcome == "full" then
                    self.was_full = true;result.pickup_state = "full";break
                end
                if outcome == "requested" then
                    requested = requested + 1
                    local old = self.attempts[target.id]
                    self.attempts[target.id] = { count = old and old.count + 1 or 1, time = now }
                end
                if outcome == "paused" or outcome == "waiting_for_current_player" then break end
                if deadline and os.clock() >= deadline and i < limit then
                    self.next_scan = now + .05
                    break
                end
            end
            self.last_pick = now
            result.pickup_state = result.pickup_state or (requested > 0 and "requested" or "waiting_for_result")
        else
            result.pickup_state = #nearby == 0 and "waiting_for_loot" or "waiting_for_result"
        end
        self.last_pickup_state = result.pickup_state
        return result
    end
    return self
end
return M
