-- WowVoice FPS: records the duration of every rendered frame, so the wowvoice lab can measure
-- how much the dictation engine slows the game down. Data is written to
-- WTF/Account/<account>/SavedVariables/WowVoiceFPS.lua on /reload or logout.
--
-- WowVoiceFPSDB = {
--   anchors = { {gametime, unixtime, frame}, ... }  -- at the frame where time() ticked to a new second
--   chunks  = { "16.7,16.6,...", ... }       -- frame durations in ms (0.1 ms), 2000 frames per chunk
--   startGameTime, startUnix, frames
-- }
local MAX_FRAMES = 300000            -- ~1.5 h at 50 fps, then it stops recording
local CHUNK = 2000

local f = CreateFrame("Frame")
local buf, n, total = {}, 0, 0
local lastUnix
local db

local function flushChunk()
  if n > 0 then
    table.insert(db.chunks, table.concat(buf, ",", 1, n))
    n = 0
  end
end

f:RegisterEvent("ADDON_LOADED")
f:RegisterEvent("PLAYER_LOGOUT")
f:SetScript("OnEvent", function(self, event, name)
  if event == "ADDON_LOADED" and name == "WowVoiceFPS" then
    WowVoiceFPSDB = { anchors = {}, chunks = {},
                      startGameTime = GetTime(), startUnix = time(), frames = 0 }
    db = WowVoiceFPSDB
    lastUnix = time()
    self:SetScript("OnUpdate", function(_, elapsed)
      if total >= MAX_FRAMES then return end
      n = n + 1
      total = total + 1
      buf[n] = string.format("%.1f", elapsed * 1000)
      if n >= CHUNK then flushChunk() end
      local u = time()
      if u ~= lastUnix then                      -- a new wall-clock second started: sync point
        lastUnix = u
        if #db.anchors < 20000 then table.insert(db.anchors, { GetTime(), u, total }) end
      end
    end)
  elseif event == "PLAYER_LOGOUT" and db then   -- also fires on /reload
    flushChunk()
    db.frames = total
  end
end)

SLASH_WOWVOICEFPS1 = "/wvfps"
SlashCmdList.WOWVOICEFPS = function()
  print(string.format("WowVoice FPS: %d frames recorded, now %.0f fps. Saved on /reload or logout.",
                      total, GetFramerate()))
end
