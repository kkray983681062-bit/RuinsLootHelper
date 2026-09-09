-- SPDX-License-Identifier: MIT
-- Pure projection and a one-widget lifecycle. No engine lookup or I/O here.
local M = {}
local function finite(x) return type(x)=="number" and x==x and math.abs(x)<1e12 end
local function vector(v) return type(v)=="table" and finite(v.X) and finite(v.Y) and finite(v.Z or 0) end
local ROOT_HALF = math.sqrt(.5)
local REFERENCE_LENGTH = math.sqrt(2776*2776+1792*1792)

function M.project(s)
    if type(s)~="table" or not s.active or not s.in_arena or s.enlarged or
       not finite(s.entry) or s.entry%1~=0 or s.entry<1 or s.entry>8 or not s.ui_key or
       not vector(s.target) or not vector(s.player) or not vector(s.center) or not vector(s.extent) or
       type(s.origin)~="table" or not finite(s.origin.X) or not finite(s.origin.Y) then return nil end
    for _,k in ipairs({"size","fixed_size","map_size"}) do
        if not finite(s[k]) or s[k]<=0 then return nil end
    end
    local ex,ey,ez=s.extent.X-s.center.X,s.extent.Y-s.center.Y,(s.extent.Z or 0)-(s.center.Z or 0)
    local span=math.sqrt(ex*ex+ey*ey+ez*ez)
    if span<1 then return nil end
    -- Same -45 degree world rotation and scale as the game's teammate markers.
    local scale=s.size/s.fixed_size*REFERENCE_LENGTH/span*7000/s.map_size
    local dx,dy=s.target.X-s.player.X,s.target.Y-s.player.Y
    local x=s.origin.X+(dx+dy)*ROOT_HALF*scale
    local y=s.origin.Y+(dy-dx)*ROOT_HALF*scale
    if not finite(x) or not finite(y) then return nil end
    return {X=x,Y=y,entry=s.entry}
end

function M.new(renderer)
    local self={renderer=renderer,visible=false,key=nil,attempted=nil,last=nil}
    function self:hide()
        if self.visible then self.renderer:hide() end
        self.visible=false;self.last=nil
    end
    function self:update(s)
        local point=M.project(s)
        if not point then self:hide();return false end
        if self.key~=s.ui_key then
            if self.key then self.renderer:detach() end
            self.key=s.ui_key;self.attempted=nil;self.visible=false;self.last=nil
        end
        if not self.renderer:valid() then
            if self.attempted==s.ui_key then return false end
            self.attempted=s.ui_key
            self.renderer:attach(s.context)
            if not self.renderer:valid() then return false end
        end
        local x,y=math.floor(point.X+.5),math.floor(point.Y+.5)
        local signature=table.concat({x,y,s.entry},":")
        if not self.visible or self.last~=signature then
            self.renderer:move(x,y)
            self.last=signature;self.visible=true
        end
        return true
    end
    function self:stop()
        self:hide()
        self.renderer:detach()
        self.key=nil;self.attempted=nil
    end
    return self
end
return M
