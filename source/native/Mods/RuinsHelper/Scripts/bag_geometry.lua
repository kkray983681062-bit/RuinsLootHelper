-- SPDX-License-Identifier: MIT
-- Read each current bag cell's live Tick geometry. No game data is modified.
-- UE4SS 2bfa839f converts struct return values to reflected Lua tables.
-- FGeometry has no reflected fields, so GetCachedGeometry() loses its data.
-- A Tick parameter's :get() retains the native UScriptStruct wrapper. Consume
-- it inside the callback and retain only the resulting viewport numbers.
local M = {}
local function valid(o) return o and o:IsValid() end
local function finite(n) return type(n)=="number" and n==n and math.abs(n)<math.huge end

function M.new(slate, clock)
    local self = {slate=slate, clock=clock or os.clock, hooks={}, cells={}, samples={}}

    function self:stop()
        self.active, self.key, self.player, self.error = false, nil, nil, nil
        self.cells, self.samples = {}, {}
    end

    function self:capture(context, geometry)
        local now=self.clock()
        if not self.active or now>self.until_at then return end
        local cell=context:get()
        if not valid(cell) then return end
        local id=self.cells[cell:GetAddress()]
        if id==nil then return end
        local previous=self.samples[id]
        if previous and now-previous.at<.04 then return end
        if not valid(self.player) then self:stop();return end
        local g=geometry:get()
        if type(g)~="userdata" then error("Missing native geometry wrapper") end
        local size=self.slate:GetLocalSize(g)
        if not finite(size.X) or not finite(size.Y) or size.X<=0 or size.Y<=0 then
            self.samples[id]=nil;return
        end
        local a,av,b,bv={},{},{},{}
        self.slate:LocalToViewport(self.player,g,{X=0,Y=0},a,av)
        self.slate:LocalToViewport(self.player,g,{X=size.X,Y=size.Y},b,bv)
        if finite(a.X) and finite(a.Y) and finite(b.X) and finite(b.Y) and b.X>a.X+8 and b.Y>a.Y+8 then
            self.samples[id]={box={a.X,a.Y,b.X,b.Y},at=now}
        else self.samples[id]=nil end
    end

    function self:hook(cell)
        local fn=cell["Tick"]
        if not valid(fn) then error("Bag cell Tick unavailable") end
        local path=(fn:GetFullName() or ""):match("^Function (.+:Tick)$")
        if not path then error("Bag cell Tick path unavailable") end
        if self.hooks[path] then return end
        local pre,post=RegisterHook(path,function(context,geometry)
            -- This is an observation callback. Never return a value (which
            -- would override the game's event), and never retain its params.
            local ok,err=pcall(function() self:capture(context,geometry) end)
            if not ok then self.error=tostring(err) end
        end)
        self.hooks[path]={pre,post}
    end

    function self:read(wrap,player,req)
        if not valid(wrap) or not valid(player) or not valid(self.slate) or
           player:GetAddress()~=req.player_address or type(req.viewport)~="table" or
           not finite(req.viewport[1]) or not finite(req.viewport[2]) or
           req.viewport[1]<=0 or req.viewport[2]<=0 then
            self:stop();return nil,{state="waiting_for_bag"}
        end
        if wrap:GetChildrenCount()~=60 then
            self:stop();return nil,{state="incomplete_bag"}
        end
        local cells,ids,widgets,parts={},{},{},{tostring(req.session),tostring(req.player_address),
            tostring(wrap:GetAddress()),tostring(req.viewport[1]),tostring(req.viewport[2])}
        for i=0,59 do
            local cell=wrap:GetChildAt(i)
            if not valid(cell) or cell["在背包"]~=true or cell["在仓库"]~=false or not cell:IsVisible() then
                self:stop();return nil,{state="incomplete_bag"}
            end
            local id=cell["格子ID"]
            if type(id)~="number" or id%1~=0 or id<0 or id>59 or ids[id] then
                self:stop();return nil,{state="invalid_cell_id"}
            end
            local address=cell:GetAddress()
            if cells[address]~=nil then self:stop();return nil,{state="duplicate_cell"} end
            ids[id],cells[address]=true,id
            widgets[#widgets+1]=cell;parts[#parts+1]=tostring(address)..":"..id
        end
        local key=table.concat(parts,"|")
        if self.key~=key then self:stop();self.key=key end
        local now=self.clock()
        self.cells,self.player,self.active,self.until_at=cells,player,true,now+.3
        for _,cell in ipairs(widgets) do self:hook(cell) end
        local slots,count,oldest={},0,now
        for id=0,59 do
            local sample=self.samples[id]
            if sample and now>=sample.at and now-sample.at<.2 then
                slots[tostring(id)]=sample.box;count=count+1;oldest=math.min(oldest,sample.at)
            end
        end
        local info={state=count==60 and "ready" or "waiting_for_tick",cells=count,error=self.error}
        if count~=60 then return nil,info end
        self.error=nil
        return {slots=slots,viewport=req.viewport,player_address=req.player_address,
            source="widget_tick",age=now-oldest},info
    end
    return self
end
return M
