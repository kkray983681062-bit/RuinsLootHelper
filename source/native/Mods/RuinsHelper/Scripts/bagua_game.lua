-- SPDX-License-Identifier: MIT
-- Reads the game's selected portal. Mutations are restricted to our own UImage.
local M={}
local function valid(o) return o and o:IsValid() end
local function addr(o) return valid(o) and o:GetAddress() or 0 end
local function xyz(v) return {X=v.X,Y=v.Y,Z=v.Z or 0} end
local function xy(v) return {X=v.X,Y=v.Y} end

function M.new()
    local self={arenas={},maps={},discovered=false,stats={snapshots=0,created=0,moved=0}}
    function self:remember(kind,object)
        if valid(object) then self[kind][object:GetAddress()]=object end
    end
    function self:discover_once()
        if self.discovered then return end
        self.discovered=true
        for _,o in ipairs(FindAllOf("八卦_C") or {}) do self:remember("arenas",o) end
        for _,o in ipairs(FindAllOf("小地图UI_C") or {}) do self:remember("maps",o) end
    end
    function self:belongs(arena,player)
        local list=arena["Other Actor"]
        local count=list:GetArrayNum()
        if count<1 or count>16 then return false end
        for i=1,count do if addr(list[i])==addr(player) then return true end end
        return false
    end
    function self:snapshot()
        self.stats.snapshots=self.stats.snapshots+1
        local ui,player,reference,button
        for id,o in pairs(self.maps) do
            if not valid(o) then self.maps[id]=nil
            elseif o:IsVisible() and o["放大"]==false and valid(o["队友0框"]) and valid(o["队友0"]) then
                local p=o:GetOwningPlayerPawn()
                if valid(p) and p:IsLocallyControlled() then
                    -- Multiple live local maps are ambiguous: do not choose an old UI.
                    if ui then return nil end
                    ui,player,reference,button=o,p,o["队友0框"],o["队友0"]
                end
            end
        end
        if not ui then return nil end
        local arena,index
        for id,o in pairs(self.arenas) do
            if not valid(o) then self.arenas[id]=nil
            elseif o["已启动"]==true then
                local n=o["入口编号"]
                if type(n)=="number" and n%1==0 and n>=1 and n<=8 and self:belongs(o,player) then
                    if arena then return nil end
                    arena,index=o,n
                end
            end
        end
        if not arena then return nil end
        local gate=arena["Sphere"..tostring(index)]
        if not valid(gate) then return nil end
        local slot=reference.Slot
        local parent=reference:GetParent()
        if not valid(slot) or not valid(parent) then return nil end
        local anchors=slot:GetAnchors()
        if anchors.Minimum.X~=anchors.Maximum.X or anchors.Minimum.Y~=anchors.Maximum.Y then return nil end
        local size,alignment=slot:GetSize(),slot:GetAlignment()
        -- Teammate 0 need not be the local pawn. Its slot position is a moving
        -- relative offset; copy only the common anchor, never that teammate offset.
        local origin={X=(.5-alignment.X)*size.X,Y=(.5-alignment.Y)*size.Y}
        return {entry=index,active=true,in_arena=true,enlarged=false,ui_key=tostring(ui:GetAddress()),
            player=xyz(player:K2_GetActorLocation()),target=xyz(gate:K2_GetComponentLocation()),
            center=xyz(ui["地图中心点坐标"]),extent=xyz(ui["地图目标像素坐标"]),
            size=ui["尺寸"],fixed_size=ui["固定地图尺寸"],map_size=ui["更改地图尺寸"],origin=origin,
            context={ui=ui,parent=parent,button=button,anchors={Minimum=xy(anchors.Minimum),Maximum=xy(anchors.Maximum)}}}
    end
    function self:valid() return valid(self.marker) and valid(self.slot) end
    function self:attach(context)
        if not context or not valid(context.ui) or not valid(context.parent) or not valid(context.button) then return end
        local class=StaticFindObject("/Script/UMG.Image")
        local tree=context.ui.WidgetTree
        if not valid(class) or not valid(tree) then error("Marker image class/widget tree unavailable") end
        local marker=StaticConstructObject(class,tree,FName("RuinsBaguaCorrectPortal"))
        if not valid(marker) then error("Marker image construction failed") end
        self.marker=marker
        marker:SetVisibility(2)
        -- Copy the game's small map-point brush; never alter the original player dot.
        marker:SetBrush(context.button.WidgetStyle.Normal)
        marker:SetBrushTintColor({SpecifiedColor={R=1,G=1,B=1,A=1},ColorUseRule=0})
        marker:SetColorAndOpacity({R=1,G=.025,B=.015,A=1})
        local slot=context.parent:AddChildToCanvas(marker)
        if not valid(slot) then error("Marker canvas slot unavailable") end
        self.slot=slot
        slot:SetAutoSize(false)
        slot:SetAnchors(context.anchors)
        slot:SetAlignment({X=.5,Y=.5})
        slot:SetSize({X=10,Y=10})
        slot:SetZOrder(99)
        self.stats.created=self.stats.created+1
    end
    function self:move(x,y)
        if not self:valid() then return end
        self.slot:SetPosition({X=x,Y=y})
        self.marker:SetVisibility(3) -- HitTestInvisible: cannot intercept clicks.
        self.stats.moved=self.stats.moved+1
    end
    function self:hide()
        if valid(self.marker) then self.marker:SetVisibility(2) end
    end
    function self:detach()
        if valid(self.marker) then self.marker:RemoveFromParent() end
        self.marker,self.slot=nil,nil
    end
    return self
end
return M
