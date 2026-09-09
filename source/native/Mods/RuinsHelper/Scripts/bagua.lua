-- SPDX-License-Identifier: MIT
-- Shared bridge lifecycle: no timer of its own and no work while disabled.
local M = {}
function M.new(game)
    game = game or require('bagua_game').new()
    local self = {game=game, control=require('bagua_core').new(game), failures=0,
                  next_at=0, registered=false, state={state='off'}}
    function self:stop()
        self.control:hide()
        self.next_at=0
        self.state={state='off'}
    end
    function self:step(req,now)
        if req.bagua_marker~=true then
            self:stop();self.failures=0;return self.state
        end
        if req.active~=true then
            self:stop();self.state={state='inactive'};return self.state
        end
        if self.failures>=3 then return {state='stopped'} end
        if self.last_now and now<self.last_now then self.next_at=0 end
        self.last_now=now
        if now<self.next_at then return self.state end
        local ok,result=pcall(function()
            if not self.registered then
                self.registered=true
                NotifyOnNewObject('/Game/Actors/八卦/八卦.八卦_C',function(o) game:remember('arenas',o) end)
                NotifyOnNewObject('/Game/MAPS/地图文件/小地图UI.小地图UI_C',function(o) game:remember('maps',o) end)
            end
            game:discover_once()
            local sample=game:snapshot()
            local shown=self.control:update(sample)
            return {state=shown and 'shown' or 'waiting',entry=shown and sample.entry or nil}
        end)
        if ok then
            self.failures=0;self.state=result
        else
            self.failures=self.failures+1
            pcall(function() self.control:hide() end)
            self.state={state='error',error=tostring(result)}
        end
        self.next_at=now+(self.control.visible and .25 or 1)
        return self.state
    end
    return self
end
return M
