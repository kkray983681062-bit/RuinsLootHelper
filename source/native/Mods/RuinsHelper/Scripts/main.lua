-- SPDX-License-Identifier: MIT
-- Local JSON mailbox, no arbitrary command evaluation or OS input injection.
local json = require("json")
local adapter = require("game")
local engine = require("core").new(adapter)
local folder = (os.getenv("LOCALAPPDATA") or "") .. "/RuinsLootHelper/"
local pending, outgoing = false, nil
local function read_request()
    local file = io.open(folder.."native-request.json", "rb")
    if not file then return nil end
    local text = file:read(1048576)
    file:close()
    local ok, request = pcall(json.decode, text)
    return ok and request or nil
end
local function publish(value)
    value.protocol, value.utc = 4, os.time()
    local ok, text = pcall(json.encode, value)
    if not ok then return end
    local temp = folder.."native-status.tmp"
    local file = io.open(temp, "wb")
    if not file then return end
    file:write(text); file:close()
    os.remove(folder.."native-status.json")
    os.rename(temp, folder.."native-status.json")
end
publish({ready=false, state="loaded_waiting_for_helper"})
LoopAsync(50, function()
    if outgoing then publish(outgoing); outgoing = nil end
    if pending then return false end
    local request = read_request()
    if not request then return false end
    pending = true
    ExecuteInGameThread(function()
        local ok, result = pcall(function()
            return engine:step(request, request.monotonic or 0, os.time())
        end)
        outgoing = ok and result or {ready=false, state="adapter_error", error=tostring(result)}
        outgoing.session = request.session
        outgoing.game_pid = request.game_pid
        pending = false
    end)
    return false
end)
