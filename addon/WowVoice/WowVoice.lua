-- WowVoice: the in-game side of the wowvoice dictation tool (~/my-steam-deck-gets-me/service/wowvoice.py).
--
-- Who does what:
--   the TOOL reads R4 and the right stick from the controller, transcribes, and presses keys:
--     signals (keys that type nothing) and the dictated text itself.
--   this ADDON decides what the ring contains (channels, names, commands: only WoW knows them), draws it,
--     and owns the DICTATION BOX: the text goes into our own edit box and we send it with SendChatMessage
--     inside the tool's key press (a hardware event, which WoW requires for /say and channels).
--   WoW's own chat box is never touched: opening it from addon code made WoW block an action
--   (native gamepad UI), and pressing Enter blind could get out of step with it.
--   If another text field has focus (bag / auction house / recipe search), WoW gives the keys to that field:
--   the box doesn't open and the dictated text simply lands in that field.
--
-- Signals:  Shift+F1..F8   highlight ring slot 1..8 (NW = 8 = Options at the top, Back in sub-rings)
--           Ctrl+Shift+F8  correction: select the chosen word (the tool then types its replacement)
--           Ctrl+Shift+F9  correction: replacement typed     F10 listening   F11 transcribing   F12 idle
--           Ctrl+Shift+F1  ring open     F2 ring close   F3 pick the highlighted slot
--           Ctrl+Shift+F4  open the box  F5 start the countdown (or "tap R4" in wait mode)
--           Ctrl+Shift+F6  send the box (no-op if it's closed)   F7 correction (stop the countdown)
-- The ring's top slots must match service/ring.py (TOP).

local VERSION = "0.5.5"
local DEFAULTS = { countdown = 2.0, mode = "countdown", channel = { type = "SAY", sector = 1 }, whispers = {}, recent = {},
                   pos = "right", button = "R4" }
local TOP = { "Say", "Party", "Guild", "Whisper", "Friends", "Recent", "World", "Options" }  -- = service/ring.py
local SUB_SLOTS = 8
local OPTIONS = { { "2 s", "countdown", 2 }, { "3 s", "countdown", 3 }, { "5 s", "countdown", 5 },
                  { "Wait for me", "wait" }, { "Send immediately", "immediate" } }
local MAX_PEOPLE = 8
-- WoW words from ~/my-steam-deck-gets-me/service/names.txt (copied in when the addon is built; used as alternatives)
local TERMS = { "Deadmines", "Scarlet Monastery", "Blackrock Depths", "Blackrock Spire", "Molten Core", "Crossroads", "Stratholme", "Ironforge", "Hinterlands", "Zul'Farrak", "Onyxia", "Stockades", "Stormwind", "Ashenvale", "Stranglethorn", "Thunder Bluff", "Linen Cloth", "Silk Cloth", "Thorium Ore", "Arcane Crystal", "Arcanite Bar", "Heavy Leather Ball", "LFM", "LF2M", "WTS", "DPS", "AFK", "brb", "ty", "lol", "Wailing Caverns", "Ragefire Chasm", "Shadowfang Keep", "Blackfathom Deeps", "Gnomeregan", "Razorfen Kraul", "Razorfen Downs", "Uldaman", "Maraudon", "Sunken Temple", "Dire Maul", "Scholomance", "Zul'Gurub", "Blackwing Lair", "Ahn'Qiraj", "Naxxramas", "Orgrimmar", "Undercity", "Darnassus", "Elwynn Forest", "Westfall", "Redridge", "Duskwood", "Wetlands", "Arathi Highlands", "Hillsbrad", "Alterac Valley", "Warsong Gulch", "Arathi Basin", "Badlands", "Searing Gorge", "Burning Steppes", "Swamp of Sorrows", "Blasted Lands", "Tanaris", "Feralas", "Desolace", "Thousand Needles", "Dustwallow Marsh", "Un'Goro Crater", "Silithus", "Winterspring", "Felwood", "Azshara", "Eastern Plaguelands", "Western Plaguelands", "Barrens", "Durotar", "Mulgore", "Teldrassil", "Darkshore", "Stonetalon", "Booty Bay", "Gadgetzan", "Tarren Mill", "Southshore", "Everlook", "Runecloth", "Mageweave", "Mithril Ore", "Black Lotus", "Devilsaur Leather", "Elixir of the Mongoose", "Major Healing Potion", "Flask of Titans", "Righteous Orb", "Lionheart Helm", "WTB", "LFG", "OOM", "CC", "AoE", "HoT", "GZ", "gratz", "inc" }
-- words speech recognition often swaps (both directions are offered)
local SOUNDALIKE = { { "need", "neat" }, { "tank", "thank" }, { "mob", "mock" }, { "mob", "mop" }, { "pull", "pool" },
  { "heal", "heel" }, { "heals", "heels" }, { "buff", "both" }, { "buff", "bluff" }, { "roll", "role" },
  { "rogue", "rouge" }, { "rogue", "rope" }, { "patrol", "petrol" }, { "lol", "lord" }, { "gratz", "grats" },
  { "wipe", "whip" }, { "wiped", "whipped" }, { "aggro", "agro" }, { "add", "ad" }, { "adds", "ads" },
  { "mana", "manna" }, { "loot", "lute" }, { "quest", "quests" }, { "group", "groups" }, { "raid", "rate" },
  { "inv", "inf" }, { "brb", "bib" }, { "afk", "a few k" }, { "ty", "tie" }, { "np", "MP" }, { "tonight", "to night" } }
local DB

local function say(msg) DEFAULT_CHAT_FRAME:AddMessage("|cff66ccffMy Steam Deck Gets Me:|r " .. msg) end

local function note(msg)                       -- diagnostic log: WowVoiceDB.log (saved on /reload)
  if not DB then return end
  DB.log = DB.log or {}
  table.insert(DB.log, date("%H:%M:%S") .. string.format(".%03d ", (GetTime() % 1) * 1000) .. msg)
  while #DB.log > 400 do table.remove(DB.log, 1) end
end

do -- record every Lua error, then pass it on as usual
  local orig = geterrorhandler()
  seterrorhandler(function(msg, ...)
    note("LUA ERROR: " .. tostring(msg) .. " | " .. (debugstack(2, 6, 0) or ""):gsub("\n", " / "))
    return orig(msg, ...)
  end)
end

------------------------------------------------------------------ channels and people
local BG_TYPE = ChatTypeInfo and ChatTypeInfo["BATTLEGROUND"] and "BATTLEGROUND" or "INSTANCE_CHAT"

local function inBattleground()
  local _, kind = IsInInstance()
  return kind == "pvp" or (UnitInBattleground and UnitInBattleground("player") ~= nil)
end

local function inGroup()
  return (IsInGroup and IsInGroup()) or (GetNumGroupMembers and GetNumGroupMembers() > 0) or UnitExists("party1")
end

local function short(name) return name and (Ambiguate and Ambiguate(name, "none") or name:gsub("%-.*", "")) end

local function remember(list, name)            -- newest first, no duplicates, no self
  name = short(name)
  if not name or name == "" or name == UnitName("player") then return end
  for i = #list, 1, -1 do if list[i] == name then table.remove(list, i) end end
  table.insert(list, 1, name)
  while #list > 20 do table.remove(list) end
end

local function channelLabel(ch)
  if not ch then return "?" end
  if ch.type == "WHISPER" then return "To " .. (ch.target or "?") end
  if ch.type == "BN_WHISPER" then return "To " .. (ch.label or "?") end
  if ch.type == "CHANNEL" then return (ch.label or ("Channel " .. tostring(ch.target))) end
  if ch.type == BG_TYPE then return "Battleground" end
  if ch.type == "NONE" then return "(nobody)" end
  return ch.type:sub(1, 1) .. ch.type:sub(2):lower()
end

local function channelColor(ch)
  local key = ch.type == "CHANNEL" and ("CHANNEL" .. tostring(ch.target)) or (ch.type == "BN_WHISPER" and "BN_WHISPER") or ch.type
  local info = ChatTypeInfo and (ChatTypeInfo[key] or ChatTypeInfo[ch.type])
  if info then return info.r, info.g, info.b end
  return 1, 1, 1
end

-- sub-ring contents: { label, action } lists (max 8)
local function requestFriends()                       -- WoW loads the list only when asked
  if C_FriendList and C_FriendList.ShowFriends then pcall(C_FriendList.ShowFriends) elseif ShowFriends then pcall(ShowFriends) end
end

local function friendsList()                           -- online first, then offline (greyed out)
  local online, offline = {}, {}
  local n = C_FriendList and C_FriendList.GetNumFriends and C_FriendList.GetNumFriends() or 0
  for i = 1, n do
    local info = C_FriendList.GetFriendInfoByIndex(i)
    if info and info.name then
      local item = { short(info.name), { type = "WHISPER", target = short(info.name) }, not info.connected }
      table.insert(info.connected and online or offline, item)
    end
  end
  -- Battle.net friends: playing WoW on this realm -> whisper the character; otherwise a Battle.net whisper
  local bn = BNGetNumFriends and BNGetNumFriends() or 0
  for i = 1, bn do
    local acc = C_BattleNet and C_BattleNet.GetFriendAccountInfo and C_BattleNet.GetFriendAccountInfo(i)
    if acc then
      local game = acc.gameAccountInfo or {}
      local name = (acc.accountName and acc.accountName ~= "" and acc.accountName) or acc.battleTag or "?"
      name = name:gsub("#%d+$", "")
      local item
      if game.isOnline and game.clientProgram == "WoW" and game.characterName and game.characterName ~= ""
         and (not game.realmName or game.realmName == GetRealmName()) then
        item = { game.characterName, { type = "WHISPER", target = game.characterName }, false }
      else
        item = { name, { type = "BN_WHISPER", target = acc.bnetAccountID, label = name }, not acc.isOnline }
      end
      table.insert(acc.isOnline and online or offline, item)
    end
  end
  for _, item in ipairs(offline) do table.insert(online, item) end
  note("friends: " .. n .. " characters, " .. bn .. " Battle.net")
  return online
end

local function peopleList(list)
  local out = {}
  for _, name in ipairs(list) do
    table.insert(out, { name, { type = "WHISPER", target = name } })
    if #out >= SUB_SLOTS then break end
  end
  return out
end

-- Whisper sub-ring: a targeted player you can whisper takes slot 1 while targeted (not saved: it only joins the
-- whisper history once you actually whisper them), then the usual whisper history.
local function whisperList()
  local out, first = {}, nil
  if UnitExists("target") and UnitIsPlayer("target") and not UnitIsUnit("target", "player")
     and UnitFactionGroup("target") == UnitFactionGroup("player") then
    first = GetUnitName("target", true)
    table.insert(out, { short(first) .. "\n(target)", { type = "WHISPER", target = first } })
  end
  for _, name in ipairs(DB.whispers) do
    if not (first and short(name):lower() == short(first):lower()) then
      table.insert(out, { name, { type = "WHISPER", target = name } })
    end
    if #out >= SUB_SLOTS then break end
  end
  return out
end

local function worldList()
  local out, t = {}, { GetChannelList() }
  for i = 1, #t, 3 do
    local id, name, disabled = t[i], t[i + 1], t[i + 2]
    if id and name and not disabled then
      table.insert(out, { id .. ". " .. name, { type = "CHANNEL", target = id, label = name } })
    end
    if #out >= SUB_SLOTS then break end
  end
  return out
end

local function targetName() return UnitExists("target") and UnitIsPlayer("target") and UnitName("target") end

local COMMANDS = {   -- run inside the tool's key press (a hardware event)
  { "Reload UI", function() ReloadUI() end },
  { "Invite target", function()
      local n = targetName()
      if not n then say("no player targeted") return end
      if C_PartyInfo and C_PartyInfo.InviteUnit then C_PartyInfo.InviteUnit(n) else InviteUnit(n) end
    end },
  { "Add friend", function()
      local n = targetName()
      if not n then say("no player targeted") return end
      C_FriendList.AddFriend(n)
    end },
  { "Roll", function() RandomRoll(1, 100) end },
  { "Ready check", function() DoReadyCheck() end },
  { "Leave group", function() if C_PartyInfo and C_PartyInfo.LeaveParty then C_PartyInfo.LeaveParty() else LeaveParty() end end },
}

------------------------------------------------------------------ the dictation box
local pendingChannel, pendingAt                -- channel picked in the ring for the next box
local corr, ind, correctionKey                -- made further down; the box's scripts use them
local box = CreateFrame("EditBox", "WowVoiceBox", UIParent)   -- own frame (InputBoxTemplate indented oddly)
box:SetAutoFocus(false)
box:SetMaxLetters(255)
box:SetHeight(28)
box:SetFrameStrata("DIALOG")
box:SetFontObject(ChatFontNormal)
box:SetMultiLine(true)                                 -- long dictations wrap; the box grows upwards
box:Hide()
do
  local bg = box:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0.06, 0.045, 0.035, 0.92)
  for _, e in ipairs({ { "TOPLEFT", "TOPRIGHT", 0, 1 }, { "BOTTOMLEFT", "BOTTOMRIGHT", 0, 1 },
                       { "TOPLEFT", "BOTTOMLEFT", 1, 0 }, { "TOPRIGHT", "BOTTOMRIGHT", 1, 0 } }) do
    local t = box:CreateTexture(nil, "BORDER")
    t:SetColorTexture(0.62, 0.45, 0.17, 1)                    -- aged gold, like the wheel
    t:SetPoint(e[1]); t:SetPoint(e[2])
    if e[3] == 1 then t:SetWidth(1.5) else t:SetHeight(1.5) end
  end
end
local header = box:CreateFontString(nil, "OVERLAY", "ChatFontNormal")  -- "Party:" inside the box, like WoW's
header:SetPoint("TOPLEFT", box, "TOPLEFT", 8, -7)
local BOX_MIN, BOX_LINES = 28, 6                        -- one line … at most 6 lines, then it scrolls
local measure = box:CreateFontString(nil, "OVERLAY", "ChatFontNormal")
measure:SetWordWrap(true)
measure:SetNonSpaceWrap(true)
measure:SetJustifyH("LEFT")
measure:Hide()
local boxInset = 14
-- Countdown bar: sits on the box's top edge (one unit with it): dark track + aged-gold frame, glossy fill
-- (Media/bar_fill, tinted gold → ember red at the end) with a spark at its tip.
local BOX_MEDIA = "Interface\\AddOns\\WowVoice\\Media\\"
local bar = CreateFrame("StatusBar", nil, box)
bar:SetStatusBarTexture(BOX_MEDIA .. "bar_fill")
bar:SetMinMaxValues(0, 1)
bar:SetHeight(6)
bar:SetPoint("BOTTOMLEFT", box, "TOPLEFT", 2, 1.5)
bar:SetPoint("BOTTOMRIGHT", box, "TOPRIGHT", -2, 1.5)
do
  local track = bar:CreateTexture(nil, "BACKGROUND")
  track:SetPoint("TOPLEFT", -2, 2); track:SetPoint("BOTTOMRIGHT", 2, -1.5)
  track:SetColorTexture(0.06, 0.045, 0.035, 0.95)
  local function line(p1, p2, x, y, horizontal)
    local t = bar:CreateTexture(nil, "BORDER")
    t:SetColorTexture(0.62, 0.45, 0.17, 1)
    t:SetPoint(p1, track, p1); t:SetPoint(p2, track, p2)
    if horizontal then t:SetHeight(1.5) else t:SetWidth(1.5) end
  end
  line("TOPLEFT", "TOPRIGHT", 0, 0, true)
  line("TOPLEFT", "BOTTOMLEFT", 0, 0, false)
  line("TOPRIGHT", "BOTTOMRIGHT", 0, 0, false)
end
local spark = bar:CreateTexture(nil, "OVERLAY")
spark:SetTexture("Interface\\CastingBar\\UI-CastingBar-Spark")
spark:SetBlendMode("ADD")
spark:SetSize(14, 22)
bar:Hide()
-- The hint above the box: a tooltip pill like the wheel's labels, with button glyphs.
local tip = CreateFrame("Frame", nil, box, BackdropTemplateMixin and "BackdropTemplate" or nil)
tip:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
                  edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16,
                  edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
tip:SetBackdropColor(0.05, 0.04, 0.03, 0.92)
tip:SetBackdropBorderColor(0.62, 0.45, 0.17, 1)
tip:SetPoint("BOTTOMLEFT", box, "TOPLEFT", 0, 12)  -- grows to the right: never off the screen
local tipText = tip:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
tipText:SetPoint("LEFT", tip, "LEFT", 10, 0)
tipText:SetShadowOffset(1, -1)
local function G(name) return "|T" .. BOX_MEDIA .. "glyph_" .. name .. ":16:16|t" end
local KEYS = G("a") .. " Send     " .. G("b") .. " Drop     " .. G("r4") .. "|cffd8c69ax2|r Correct"
local tipStatus, tipWidth = "", 0
local function setTip(statusText, keys, measure)
  -- statusText: coloured lead ("Sending in %.1f s"); measure = widest version, so the pill doesn't jitter
  local function join(a) return (a ~= "" and keys) and (a .. "     " .. keys) or (a ~= "" and a or (keys or "")) end
  tipText:SetText(join(measure or statusText))
  tipWidth = tipText:GetStringWidth()
  tip:SetSize(tipWidth + 22, math.max(26, tipText:GetStringHeight() + 12))
  tipText:SetText(join(statusText))
  tip:Show()
end
local boxChannel
local deadline, total, barMode

local function fitBox()                                -- height follows the wrapped text (grows upwards)
  local w = box:GetWidth() - boxInset - 8
  if w <= 0 then return end
  measure:SetWidth(w)
  measure:SetText((box:GetText() or "") ~= "" and box:GetText() or "X")
  local lineH = select(2, ChatFontNormal:GetFont()) or 14
  local h = math.min(measure:GetStringHeight(), lineH * BOX_LINES + 4)
  box:SetHeight(math.max(BOX_MIN, math.ceil(h) + 14))
end

local function placeBox()                              -- where WoW's own chat input box sits; grows upwards
  box:ClearAllPoints()
  local eb = ChatFrame1EditBox
  if eb and eb:GetNumPoints() > 0 then
    box:SetPoint("BOTTOMLEFT", eb, "BOTTOMLEFT", 0, 0)
    box:SetPoint("BOTTOMRIGHT", eb, "BOTTOMRIGHT", 0, 0)
    box:SetHeight(BOX_MIN)
  else
    local cf = DEFAULT_CHAT_FRAME or ChatFrame1
    box:SetPoint("TOPLEFT", cf, "BOTTOMLEFT", -2, -6)
    box:SetWidth(math.max(320, cf:GetWidth()))
    box:SetHeight(28)
  end
end

local function closeBox(why)
  if corr then corr:Hide() end
  box:ClearFocus()
  box:Hide()
  bar:Hide()
  deadline, barMode = nil, nil
  if why then note("box closed: " .. why) end
end

local function openBox()
  if box:IsShown() then return end                     -- already open: the tool types into it
  boxChannel = DB.channel or { type = "SAY", sector = 1 }
  placeBox()
  header:SetText(channelLabel(boxChannel) .. ":")
  header:SetTextColor(channelColor(boxChannel))
  box:SetFontObject(ChatFontNormal)                     -- font first: it would reset the colour
  boxInset = header:GetStringWidth() + 14
  box:SetTextInsets(boxInset, 8, 7, 7)
  box:SetTextColor(channelColor(boxChannel))
  setTip("", G("a") .. " Send     " .. G("b") .. " Drop")
  box:SetText("")
  box:Show()
  box:SetFocus()
  if ind then ind:Hide() end
  note("box open: " .. channelLabel(boxChannel))
end

local function sendBox(why)
  if not box:IsShown() then return end                  -- discarded with Esc, or already sent
  local text = strtrim((box:GetText() or ""):gsub("\n", " "))
  if text == "" then closeBox("empty"); return end
  local ch = boxChannel or DB.channel
  if ch.type == "NONE" then say("no recipient picked: not sent"); closeBox("no recipient"); return end
  local ok, err
  if ch.type == "BN_WHISPER" then
    ok, err = pcall(BNSendWhisper, ch.target, text)
  elseif ch.type == "WHISPER" or ch.type == "CHANNEL" then
    ok, err = pcall(SendChatMessage, text, ch.type, nil, ch.target)
  else
    ok, err = pcall(SendChatMessage, text, ch.type)
  end
  note("sent (" .. why .. ") to " .. channelLabel(ch) .. (ok and "" or (" FAILED: " .. tostring(err))))
  if ok then DB.channel = ch end                        -- (already the default; keeps it after a failed pick)
  closeBox()
end

box:SetScript("OnEnterPressed", function() sendBox("enter") end)
box:SetScript("OnTextChanged", function(self)
  local t = self:GetText() or ""
  if t:find("\n") then self:SetText((t:gsub("\n", " "))) return end   -- chat messages are one line
  fitBox()
end)
box:SetScript("OnEscapePressed", function() closeBox("esc") end)
-- The controller's buttons go to the game, not to text fields: while the box is open it takes them itself.
-- A = send, B = discard; other buttons do nothing while the box is open (a few seconds).
box:EnableGamePadButton(true)
box:SetScript("OnGamePadButtonDown", function(_, button)
  note("pad " .. tostring(button) .. " in box" .. (corr and corr:IsShown() and " (correction)" or ""))
  if corr and corr:IsShown() then correctionKey(button) return end
  if button == "PAD1" then sendBox("A")
  elseif button == "PAD2" then closeBox("B") end
end)

bar:SetScript("OnUpdate", function()
  if barMode ~= "countdown" then return end
  local left = deadline - GetTime()
  if left <= 0 then left = 0 end                        -- the tool presses "send" right about now
  local f = left / total
  bar:SetValue(f)
  local w = bar:GetWidth()
  spark:SetPoint("CENTER", bar, "LEFT", w * f, 0)
  spark:SetShown(f > 0.01)
  local e = f < 0.3 and (1 - f / 0.3) or 0              -- gold, warming to ember red in the last 30 %
  bar:SetStatusBarColor(1, 0.78 - 0.42 * e, 0.22 - 0.07 * e)
  tipText:SetText(("|cffffd100Sending in %.1f s|r     "):format(left) .. KEYS)
end)

local function startCountdown()
  if not box:IsShown() then return end
  if DB.mode == "wait" then
    barMode = "wait"
    bar:Hide()
    setTip("|cff5ee05eReady|r", KEYS)
    return
  else
    total = DB.countdown
    deadline, barMode = GetTime() + total, "countdown"
    bar:SetValue(1)
    setTip("|cffffd100Sending in 0.0 s|r", KEYS, "|cffffd100Sending in 00.0 s|r")
  end
  bar:Show()
end

local function stopBarForCorrection()
  if not box:IsShown() then return end
  barMode = "correction"
  bar:Hide()
  setTip("|cffffd100Correcting…|r")
end

------------------------------------------------------------------ in-game indicator (listening / transcribing)
ind = CreateFrame("Frame", "WowVoiceIndicator", UIParent)
ind:SetFrameStrata("DIALOG")
ind:Hide()
local indPlate = ind:CreateTexture(nil, "BACKGROUND")   -- Media/status_*: card with a round icon well (left)
indPlate:SetAllPoints()
local indIcon = ind:CreateTexture(nil, "ARTWORK")
indIcon:SetTexture("Interface\\AddOns\\WowVoice\\Media\\icon_round")  -- the icon's round centre, cut to fit the well
local indDot = ind:CreateTexture(nil, "OVERLAY")
local indText = ind:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
indText:SetShadowOffset(1.5, -1.5)
indText:SetJustifyH("LEFT")
local indSub = ind:CreateFontString(nil, "OVERLAY", "GameFontHighlight")   -- "to" (plain)
indSub:SetShadowOffset(1, -1)
indSub:SetJustifyH("LEFT")
indSub:SetTextColor(0.85, 0.8, 0.7)
local indPill = CreateFrame("Frame", nil, ind, BackdropTemplateMixin and "BackdropTemplate" or nil)
indPill:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
                      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16,
                      edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
indPill:SetBackdropColor(0.05, 0.04, 0.03, 0.88)
indPill:SetBackdropBorderColor(0.62, 0.45, 0.17, 1)
local indTarget = indPill:CreateFontString(nil, "OVERLAY", "GameFontHighlight")  -- the target, in its colour
indTarget:SetPoint("CENTER")
indTarget:SetShadowOffset(1, -1)
local indSince, indWhat = 0, nil
ind:SetScript("OnUpdate", function(self)
  local t = GetTime() - indSince
  if t > 20 then self:Hide() return end                -- never stays up by mistake
  indDot:SetAlpha(0.45 + 0.55 * math.abs(math.sin(t * 4)))
end)
local placeIndicator                                    -- set by the wheel's layout (same place below it)

local function indicatorDestination()
  if corr and corr:IsShown() then
    indSub:SetText("say the word again")
    indPill:Hide()
    return
  end
  local ch = DB and DB.channel
  if not ch then indSub:SetText(""); indPill:Hide() return end
  local target = channelLabel(ch):gsub("^To ", "")       -- just the target: Say, Party, Jorin, 2. Trade ...
  indSub:SetText("to")
  indTarget:SetText(target)
  indTarget:SetTextColor(channelColor(ch))
  indPill:SetSize(indTarget:GetStringWidth() + 18, indTarget:GetStringHeight() + 10)
  indPill:Show()
end

local function indicate(what)
  if what == nil then ind:Hide(); indWhat = nil return end
  if placeIndicator then placeIndicator() end
  if what ~= indWhat then indSince = GetTime() end
  indWhat = what
  if what == "listen" then
    indPlate:SetTexture("Interface\\AddOns\\WowVoice\\Media\\status_listen")
    indText:SetText("Listening...")
    indText:SetTextColor(1, 0.55, 0.48)
    indDot:SetColorTexture(1, 0.25, 0.2, 1)
  elseif what == "ready" then                        -- the tool said hello: it runs
    indPlate:SetTexture("Interface\\AddOns\\WowVoice\\Media\\status_work")
    indText:SetText("Voice ready")
    indText:SetTextColor(0.55, 1, 0.5)
    indDot:SetColorTexture(0.3, 1, 0.3, 1)
  else
    indPlate:SetTexture("Interface\\AddOns\\WowVoice\\Media\\status_work")
    indText:SetText("Transcribing...")
    indText:SetTextColor(1, 0.8, 0.35)
    indDot:SetColorTexture(1, 0.75, 0.2, 1)
  end
  indicatorDestination()
  ind:Show()
end

------------------------------------------------------------------ correction menu (double-press R4)
-- The box's sentence as words: D-pad left/right = word, up/down = alternative (applied at once),
-- hold R4 = say that word again (the tool types it over the selected word), A = done, B = undo.
corr = CreateFrame("Frame", "WowVoiceCorrection", box)
corr:SetFrameStrata("DIALOG")
corr:Hide()
do
  local bg = corr:CreateTexture(nil, "BACKGROUND")
  bg:SetAllPoints()
  bg:SetColorTexture(0.06, 0.045, 0.035, 0.94)
  for _, e in ipairs({ { "TOPLEFT", "TOPRIGHT", 0 }, { "BOTTOMLEFT", "BOTTOMRIGHT", 0 }, { "TOPLEFT", "BOTTOMLEFT", 1 },
                       { "TOPRIGHT", "BOTTOMRIGHT", 1 } }) do
    local t = corr:CreateTexture(nil, "BORDER")
    t:SetColorTexture(0.62, 0.45, 0.17, 1)
    t:SetPoint(e[1]); t:SetPoint(e[2])
    if e[3] == 1 then t:SetWidth(1.5) else t:SetHeight(1.5) end
  end
end
local corrAlts = corr:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
corrAlts:SetPoint("TOPLEFT", 12, -10)
corrAlts:SetJustifyH("LEFT")
local corrSentence = corr:CreateFontString(nil, "OVERLAY", "ChatFontNormal")
corrSentence:SetPoint("BOTTOMLEFT", 12, 30)
corrSentence:SetPoint("RIGHT", -12, 0)
corrSentence:SetJustifyH("LEFT")
local corrHint = corr:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
corrHint:SetPoint("BOTTOMLEFT", 12, 10)
corrHint:SetText("|cffd8c69a<- -> word   ·   up/down: choice   ·   hold R4: say it again   ·   A: done   ·   B: undo|r")

local words, original, sel, choice, altCache = {}, nil, 1, {}, {}

local function split(text)
  local out = {}
  for token in (text or ""):gmatch("%S+") do
    local pre, core, post = token:match("^([%p]*)(.-)([%p]*)$")
    if core == "" then pre, core, post = "", token, "" end
    table.insert(out, { pre = pre, core = core, post = post })
  end
  return out
end

local function join(list)
  local parts = {}
  for _, w in ipairs(list) do if w.core ~= "" then table.insert(parts, w.pre .. w.core .. w.post) end end
  return table.concat(parts, " ")
end

local function lev(a, b)
  local la, lb = #a, #b
  if la == 0 then return lb end
  if lb == 0 then return la end
  local prev = {}
  for j = 0, lb do prev[j] = j end
  for i = 1, la do
    local cur = { [0] = i }
    for j = 1, lb do
      local cost = a:byte(i) == b:byte(j) and 0 or 1
      cur[j] = math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
    end
    prev = cur
  end
  return prev[lb]
end

local guildNames = {}
local function nameSources()
  local seen, out = {}, {}
  local function add(n)
    n = short(n)
    if n and n ~= "" and not seen[n:lower()] then seen[n:lower()] = true; table.insert(out, n) end
  end
  for _, n in ipairs(DB.whispers) do add(n) end
  for _, n in ipairs(DB.recent) do add(n) end
  for _, item in ipairs(friendsList()) do add(item[1]); if item[2].target and item[2].type == "WHISPER" then add(item[2].target) end end
  for _, n in ipairs(guildNames) do add(n) end
  local unit = IsInRaid() and "raid" or "party"
  for i = 1, (GetNumGroupMembers and GetNumGroupMembers() or 0) do add(UnitName(unit .. i)) end
  for _, t in ipairs(TERMS) do if not t:find(" ") then add(t) end end
  return out
end

local function alternatives(core)
  local key = core:lower()
  if altCache[key] then return altCache[key] end
  local list, seen = {}, {}
  local function add(w) if w and w ~= "" and not seen[w:lower()] then seen[w:lower()] = true; table.insert(list, w) end end
  add(core)
  local learned = DB.learned and DB.learned[key]
  if learned then
    local sorted = {}
    for w, n in pairs(learned) do table.insert(sorted, { w, n }) end
    table.sort(sorted, function(a, b) return a[2] > b[2] end)
    for _, it in ipairs(sorted) do add(it[1]) end
  end
  for _, pair in ipairs(SOUNDALIKE) do
    if pair[1] == key then add(pair[2]) elseif pair[2] == key then add(pair[1]) end
  end
  if #key >= 3 then
    local scored = {}
    for _, n in ipairs(nameSources()) do
      local d = lev(key, n:lower())
      local limit = #key >= 7 and 3 or (#key >= 4 and 2 or 1)
      if d > 0 and d <= limit then table.insert(scored, { n, d }) end
    end
    table.sort(scored, function(a, b) return a[2] < b[2] end)
    for i = 1, math.min(4, #scored) do add(scored[i][1]) end
  end
  if core:sub(1, 1):match("%l") then add(core:sub(1, 1):upper() .. core:sub(2)) end
  add("(remove word)")
  altCache[key] = list
  return list
end

local function drawCorrection()
  local shown = {}
  for i, w in ipairs(words) do
    local text = w.pre .. (w.core == "" and "|cff888888(removed)|r" or w.core) .. w.post
    if i == sel then text = "|cffffd765[" .. text .. "]|r" end
    table.insert(shown, text)
  end
  corrSentence:SetText(table.concat(shown, " "))
  local w = words[sel]
  local lines = {}
  if w then
    local alts = alternatives(w.base)
    for i, a in ipairs(alts) do
      if i == (choice[sel] or 1) then table.insert(lines, "|cffffd765> " .. a .. "|r")
      else table.insert(lines, "|cffcfc4a8  " .. a .. "|r") end
    end
  end
  corrAlts:SetText(table.concat(lines, "\n"))
  local h = corrAlts:GetStringHeight() + corrSentence:GetStringHeight() + 64
  corr:SetHeight(math.max(110, h))
end

local function correctionOpen() return corr:IsShown() end

local function openCorrection()
  if not box:IsShown() then return end
  stopBarForCorrection()
  original = box:GetText()
  words = split(original)
  if #words == 0 then return end
  for _, w in ipairs(words) do w.base = w.core end
  sel, choice, altCache = 1, {}, {}
  corr:ClearAllPoints()
  corr:SetPoint("BOTTOMLEFT", box, "TOPLEFT", 0, 30)
  corr:SetPoint("BOTTOMRIGHT", box, "TOPRIGHT", 0, 30)
  drawCorrection()
  corr:Show()
  box:SetFocus()
  note("correction open: " .. #words .. " words")
end

local function applyChoice()
  local w = words[sel]
  local alts = alternatives(w.base)
  local a = alts[choice[sel] or 1]
  w.core = a == "(remove word)" and "" or a
  box:SetText(join(words))
  drawCorrection()
end

correctionKey = function(button)
  if button == "PADDLEFT" then sel = math.max(1, sel - 1); drawCorrection()
  elseif button == "PADDRIGHT" then sel = math.min(#words, sel + 1); drawCorrection()
  elseif button == "PADDUP" or button == "PADDDOWN" then
    local n = #alternatives(words[sel].base)
    local c = (choice[sel] or 1) + (button == "PADDDOWN" and 1 or -1)
    choice[sel] = (c - 1) % n + 1
    applyChoice()
  elseif button == "PAD1" then                         -- A: done; remember what was corrected
    DB.learned = DB.learned or {}
    for _, w in ipairs(words) do
      if w.core ~= w.base and w.core ~= "" then
        local k = w.base:lower()
        DB.learned[k] = DB.learned[k] or {}
        DB.learned[k][w.core] = (DB.learned[k][w.core] or 0) + 1
        local n, least, leastKey = 0, math.huge, nil      -- at most 4 suggestions per word
        for alt, c in pairs(DB.learned[k]) do n = n + 1; if c < least then least, leastKey = c, alt end end
        if n > 4 and leastKey ~= w.core then DB.learned[k][leastKey] = nil end
        note("learned: " .. w.base .. " -> " .. w.core)
      end
    end
    corr:Hide()
    setTip("|cff5ee05eReady|r", G("a") .. " Send     " .. G("b") .. " Drop")
    box:SetFocus()
  elseif button == "PAD2" then                         -- B: undo all corrections
    box:SetText(original or box:GetText())
    corr:Hide()
    setTip("|cff5ee05eReady|r", G("a") .. " Send     " .. G("b") .. " Drop")
    box:SetFocus()
  end
end

local function replaceBegin()                           -- the tool will type the word said again
  ind:Hide()
  if not correctionOpen() then return end
  local pos = 0
  for i = 1, sel - 1 do
    local w = words[i]
    if w.core ~= "" then pos = pos + #(w.pre .. w.core .. w.post) + 1 end
  end
  local w = words[sel]
  local startPos = pos + #w.pre
  box:SetFocus()
  box:HighlightText(startPos, startPos + #w.core)
  box:SetCursorPosition(startPos + #w.core)
  box:HighlightText(startPos, startPos + #w.core)
end

local function replaceDone()
  ind:Hide()
  if not correctionOpen() then return end
  local fresh = split(box:GetText())
  local w = words[sel]
  local new = fresh[sel] and fresh[sel].core or w.core
  if #fresh == #words then
    w.core = new
    altCache[w.base:lower()] = nil
    local alts = alternatives(w.base)
    local found
    for i, a in ipairs(alts) do if a == new then found = i end end
    if not found then table.insert(alts, 2, new); found = 2 end
    choice[sel] = found
  else                                                 -- the new "word" was several words: start over
    for _, x in ipairs(fresh) do x.base = x.core end
    words, choice, altCache = fresh, {}, {}
  end
  box:SetText(join(words))
  drawCorrection()
end

------------------------------------------------------------------ the ring (drawing; the tool decides the slot)
-- Look: design/handoff concept B "Recessed Stone Wedge"; artwork drawn by ~/my-steam-deck-gets-me/design/build_wheel.py
-- into Media/*.tga (512 canvas: outer radius 238, ring 210, hub 48; wedges/line point NORTH and are rotated).
local MEDIA = "Interface\\AddOns\\WowVoice\\Media\\"
local WHEEL = 430                                       -- on-screen size (UI units); /wowvoice size N
local ring = CreateFrame("Frame", "WowVoiceRing", UIParent)
ring:SetFrameStrata("DIALOG")
ring:Hide()

local function layer(file, drawLayer, sub)
  local t = ring:CreateTexture(nil, drawLayer, nil, sub or 0)
  t:SetTexture(MEDIA .. file)
  t:SetPoint("CENTER")
  return t
end
local base = layer("wheel_base", "BACKGROUND")
local stone = layer("wedge_stone", "BORDER")
local defTex = layer("wedge_active", "ARTWORK", 0)      -- the ACTIVE destination: green wedge (design "A")
local selTex = layer("wedge_select", "ARTWORK", 1)
local line = layer("line", "ARTWORK", 2)
local hubTex = layer("hub", "ARTWORK", 3)
-- The right stick: WoW's own gamepad icon (part of the game, nothing to ship). R4 isn't in WoW's sets
-- (it doesn't know the Deck's back buttons), so R4 is our own badge (Media/glyph_r4).
-- The right stick "move it": our own icon (Media/stick_base + stick_cap); the cap glides left and right.
-- (WoW's gamepad-xbox1-stick-r3 shows a stick PRESS, not a move.) R4 is our own badge too (Media/glyph_r4).
local function sway(tex, amount)                       -- loop: centre -> right -> left -> centre
  local ag = tex:CreateAnimationGroup()
  local steps = { { amount, 0.35 }, { -2 * amount, 0.7 }, { amount, 0.35 } }
  for i, st in ipairs(steps) do
    local a = ag:CreateAnimation("Translation")
    a:SetOffset(st[1], 0)
    a:SetDuration(st[2])
    a:SetOrder(i)
    a:SetSmoothing("IN_OUT")
  end
  ag:SetLooping("REPEAT")
  return ag
end
local function stickIcon(parent, layer)
  local base = parent:CreateTexture(nil, layer, nil, 2)
  base:SetTexture(MEDIA .. "stick_base")
  local cap = parent:CreateTexture(nil, layer, nil, 3)
  cap:SetTexture(MEDIA .. "stick_cap")
  cap:SetPoint("CENTER", base, "CENTER")
  return base, cap
end
local hubBase, hubCap = stickIcon(ring, "OVERLAY")     -- the right stick in the middle of the wheel
hubBase:SetPoint("CENTER")
local hubSway
local hintBar = ring:CreateTexture(nil, "BACKGROUND")
hintBar:SetTexture(MEDIA .. "hintbar")
local hintRows = {}
for r = 1, 2 do
  local row = CreateFrame("Frame", nil, ring)
  row.a = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  row.b = row:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  if r == 1 then
    row.icon, row.cap = stickIcon(row, "OVERLAY")
    row.a:SetText("Use"); row.b:SetText("to aim and release to choose")
  else
    row.icon = row:CreateTexture(nil, "OVERLAY")
    row.icon:SetTexture(MEDIA .. "glyph_r4")
    row.a:SetText("Hold"); row.b:SetText("until you're done talking, then release.")
  end
  for _, fs in ipairs({ row.a, row.b }) do fs:SetTextColor(0.93, 0.84, 0.63); fs:SetShadowOffset(1, -1) end
  hintRows[r] = row
end
local hintSway
local title = ring:CreateFontString(nil, "OVERLAY", "GameFontNormal")     -- level name, above the wheel
local status = ring:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
status:Hide()

local slots = {}
for i = 1, 8 do
  local s = {}
  s.icon = ring:CreateTexture(nil, "OVERLAY", nil, 1)
  s.tag = CreateFrame("Frame", nil, ring)                -- green "ACTIVE" tag under the active label
  s.tag.bg = s.tag:CreateTexture(nil, "ARTWORK")
  s.tag.bg:SetAllPoints()
  s.tag.bg:SetTexture(MEDIA .. "active_tag")
  s.tag.text = s.tag:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  s.tag.text:SetPoint("CENTER", 0, 0)
  s.tag.text:SetText("ACTIVE")
  s.tag.text:SetTextColor(0.75, 1, 0.75)
  s.tag:Hide()
  -- the label sits in a small pill: WoW's own tooltip frame (classic look, nothing to ship)
  s.pill = CreateFrame("Frame", nil, ring, BackdropTemplateMixin and "BackdropTemplate" or nil)
  s.pill:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
                       edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16,
                       edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
  s.pill:SetBackdropColor(0.05, 0.04, 0.03, 0.88)
  s.text = s.pill:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  s.text:SetPoint("CENTER", s.pill, "CENTER", 0, 0)
  s.text:SetShadowOffset(1, -1)
  s.text:SetShadowColor(0, 0, 0, 0.9)
  s.text:SetJustifyH("CENTER")
  slots[i] = s
end

local function layout()
  local size = (DB and DB.wheelSize) or WHEEL
  local k = size / 512
  ring:SetSize(size, size + 130 * k)
  for _, t in ipairs({ base, stone, defTex, selTex, line }) do t:SetSize(size, size) end
  hubTex:SetSize(size * 136 / 512, size * 136 / 512)     -- the hub is its own sharp 256 px texture
  ring:ClearAllPoints()
  if DB.pos == "left" then ring:SetPoint("LEFT", UIParent, "LEFT", 40, 30)
  elseif DB.pos == "center" then ring:SetPoint("CENTER", UIParent, "CENTER", 0, 30)
  else ring:SetPoint("RIGHT", UIParent, "RIGHT", -40, 30) end
  hintBar:ClearAllPoints()
  hintBar:SetSize(size * 0.98, size * 0.98 / 8 * 2.1)          -- two lines
  hubBase:SetSize(size * 0.17, size * 0.17)
  hubCap:SetSize(size * 0.17, size * 0.17)
  -- (the hub's stick does not move; only the hint's stick does)
  hintBar:SetPoint("TOP", ring, "CENTER", 0, -size / 2 - 6 * k)
  local g = math.floor(size / 512 * 40 + 0.5)            -- icon size in the hint rows
  for r, row in ipairs(hintRows) do
    row.icon:SetSize(g, g)
    if row.cap then row.cap:SetSize(g, g) end
    row.a:ClearAllPoints(); row.icon:ClearAllPoints(); row.b:ClearAllPoints()
    row.a:SetPoint("LEFT", row, "LEFT", 0, 0)
    row.icon:SetPoint("LEFT", row.a, "RIGHT", 4, 0)
    row.b:SetPoint("LEFT", row.icon, "RIGHT", 4, 0)
    row:SetSize(row.a:GetStringWidth() + g + row.b:GetStringWidth() + 8, g)
    row:ClearAllPoints()
    row:SetPoint("CENTER", hintBar, "CENTER", 0, (r == 1 and 1 or -1) * g * 0.5)
  end
  if not hintSway then hintSway = sway(hintRows[1].cap, g * 0.12) end
  title:ClearAllPoints()
  title:SetPoint("BOTTOM", ring, "CENTER", 0, size / 2 + 4 * k)
  status:ClearAllPoints()
  status:SetPoint("TOP", hintBar, "BOTTOM", 0, -2)
  for i, s in ipairs(slots) do
    local a = math.rad((i - 1) * 45)
    local cx, cy = 140 * k * math.sin(a), 140 * k * math.cos(a)
    s.icon:SetSize(50 * k, 50 * k)
    s.icon:ClearAllPoints()
    s.icon:SetPoint("CENTER", ring, "CENTER", cx, cy + 16 * k)
    s.tag:SetSize(76 * k, 19 * k)
    s.tag:ClearAllPoints()
    s.tag:SetPoint("TOP", s.pill, "BOTTOM", 0, 1 * k)
    s.pill:ClearAllPoints()
    s.pill:SetPoint("TOP", s.icon, "BOTTOM", 0, 1 * k)
  end
  -- the indicator sits below the hint bar, in the same spot whether the wheel is open or not
  placeIndicator = function()
    local hintH = size * 0.98 / 8 * 2.1
    local w = size * 0.8
    local h = w / 4                                       -- the card art is 512 x 128
    local u = h / 128                                     -- one art pixel
    ind:SetSize(w, h)
    ind:ClearAllPoints()
    ind:SetPoint("TOP", ring, "CENTER", 0, -size / 2 - 6 * k - hintH - 8 * k)
    indIcon:SetSize(86 * u, 86 * u)                      -- fills the round well (r = 44)
    indIcon:ClearAllPoints()
    indIcon:SetPoint("CENTER", ind, "LEFT", 64 * u, 0)
    indDot:SetSize(18 * u, 18 * u)
    indDot:ClearAllPoints()
    indDot:SetPoint("CENTER", ind, "LEFT", 64 * u + 32 * u, -32 * u)
    indText:ClearAllPoints()
    indText:SetPoint("BOTTOMLEFT", ind, "LEFT", 140 * u, 2 * u)
    indSub:ClearAllPoints()
    indSub:SetPoint("TOPLEFT", ind, "LEFT", 140 * u, -12 * u)
    indPill:ClearAllPoints()
    indPill:SetPoint("LEFT", indSub, "RIGHT", 6, 0)
  end
  stone:SetRotation(math.rad(45))                       -- art points north; NW = 45 deg counter-clockwise
  stone:Hide()                                          -- user: Options looks like the other sectors
end

local level, entries, highlight = "top", {}, nil       -- entries[i] = { label, value, kind, disabled, icon } or false
local SECTOR = { Whisper = 4, Friends = 5, Recent = 6, World = 7 }

local ICON = { Say = "say", Party = "party", Raid = "raid", Battleground = "battleground", Guild = "guild",
               Whisper = "whisper", Friends = "friends", Recent = "recent", World = "world", Options = "options" }

local function topEntries()
  local e = {}
  e[1] = { "Say", { type = "SAY" }, "channel", false, "say" }
  if inBattleground() then e[2] = { "Battleground", { type = BG_TYPE }, "channel", false, "battleground" }
  elseif IsInRaid() then e[2] = { "Raid", { type = "RAID" }, "channel", false, "raid" }
  else e[2] = { "Party", { type = "PARTY" }, "channel", not inGroup(), "party" } end
  e[3] = { "Guild", { type = "GUILD" }, "channel", not IsInGuild(), "guild" }
  e[4] = { "Whisper", "Whisper", "sub", false, "whisper" }
  e[5] = { "Friends", "Friends", "sub", false, "friends" }
  e[6] = { "Recent\nPeople", "Recent", "sub", false, "recent" }
  e[7] = { "World\nChats", "World", "sub", false, "world" }
  e[8] = { "Options", "Options", "sub", false, "options" }
  return e
end

local ctxState = { outdated = false }                  -- voice context (see "voice context" below)

local function subEntries(name)
  local e = {}
  if name == "Options" then
    for i, o in ipairs(OPTIONS) do e[i] = { o[1], o, "option", false, "clock" } end
    e[6] = { (ctxState.outdated and "|cffffa040Refresh context|r" or "Refresh context")
             .. "\n|cffb0a890(reloads your UI)|r",
             function() ReloadUI() end, "command", false, "commands" }   -- saves the context for the tool
    e[7] = { "Commands", "Commands", "sub", false, "commands" }   -- W, next to Back (NW)
  elseif name == "Commands" then
    for i, c in ipairs(COMMANDS) do if i <= 7 then e[i] = { c[1], c[2], "command", false, "commands" } end end
  else
    local list = {}
    if name == "Whisper" then list = whisperList()
    elseif name == "Friends" then list = friendsList()
    elseif name == "Recent" then list = peopleList(DB.recent)
    elseif name == "World" then list = worldList() end
    for i, item in ipairs(list) do
      if i <= 7 then e[i] = { item[1], item[2], "channel", item[3] or false, name == "World" and "channel" or "person" } end
    end
  end
  for i = 1, 7 do if e[i] == nil then e[i] = false end end
  e[8] = { "Back", "back", "back", false, "back" }
  return e
end

local function sameChannel(a, b)
  return a and b and a.type == b.type and tostring(a.target or "") == tostring(b.target or "")
end

local function isSelected(i, e)
  if not e then return false end
  local ch = DB.channel
  if level == "top" then return ch and ch.sector == i end
  if e[3] == "option" then
    local o = e[2]
    return DB.mode == o[2] and (o[2] ~= "countdown" or DB.countdown == o[3])
  end
  return e[3] == "channel" and sameChannel(e[2], ch)
end

local function draw()
  local activeSlot
  for i = 1, 8 do
    local s, e = slots[i], entries[i]
    local active = isSelected(i, e) and true or false
    s.tag:SetShown(active)
    if active then activeSlot = i end
    if e then
      local label = e[1]
      s.icon:SetTexture(MEDIA .. "icon_" .. (e[5] or "person"))
      s.icon:SetDesaturated(e[4] and true or false)
      s.icon:SetAlpha(e[4] and 0.45 or 1)
      s.text:SetText(label)
      s.pill:SetSize(s.text:GetStringWidth() + 18, s.text:GetStringHeight() + 10)
      if e[4] then
        s.text:SetTextColor(0.55, 0.52, 0.47); s.pill:SetBackdropBorderColor(0.4, 0.4, 0.4, 0.9)
      elseif i == highlight then
        s.text:SetTextColor(1, 0.98, 0.9); s.pill:SetBackdropBorderColor(1, 0.82, 0.15, 1)
      else
        s.text:SetTextColor(0.97, 0.94, 0.84); s.pill:SetBackdropBorderColor(0.62, 0.45, 0.17, 1)
      end
      s.icon:Show(); s.pill:Show()
    else
      s.icon:Hide(); s.pill:Hide(); s.tag:Hide()
    end
  end
  if activeSlot then                                    -- the green wedge on the active destination
    defTex:SetRotation(-math.rad((activeSlot - 1) * 45)); defTex:Show()
  else
    defTex:Hide()
  end
  if highlight then
    local r = -math.rad((highlight - 1) * 45)            -- WoW rotates counter-clockwise
    selTex:SetRotation(r); line:SetRotation(r)
    selTex:Show(); line:Show()
  else
    selTex:Hide(); line:Hide()
  end
  title:SetText(level == "top" and "" or (level == "Recent" and "Recent People" or level == "World" and "World Chats" or level))
end

local function flash(msg) end                          -- (the status line sat on top of the card: removed)

local function openRing()
  note(string.format("ring: IsInGroup=%s members=%s party1=%s raid=%s guild=%s", tostring(IsInGroup and IsInGroup()),
       tostring(GetNumGroupMembers and GetNumGroupMembers()), tostring(UnitExists("party1")), tostring(IsInRaid()), tostring(IsInGuild())))
  layout()
  level, entries, highlight = "top", topEntries(), nil
  flash("Now: " .. channelLabel(DB.channel))
  draw()
  ring:Show()
  if hintSway then hintSway:Play() end
end

local function closeRing() ring:Hide(); highlight = nil end

local function highlightSlot(i)
  if not ring:IsShown() or i > 8 then return end
  if i ~= highlight then highlight = i; draw() end
end

local highlightIndex
local function pick()                                  -- the tool picked the highlighted slot
  if not ring:IsShown() or not highlight then return end
  highlightIndex = highlight
  local e = entries[highlight]
  highlight = nil
  if not e then                                        -- empty slot: nothing changes, the default stays
    flash("|cffff8060nobody there|r  ·  still: " .. channelLabel(DB.channel))
    draw()
    return
  end
  note("pick " .. level .. ": " .. tostring(e[1]))
  if e[3] == "back" then
    level = level == "Commands" and "Options" or "top"
    entries = level == "top" and topEntries() or subEntries(level)
    flash("")
    draw()
  elseif e[3] == "sub" then
    if e[2] == "Friends" then requestFriends() end
    level, entries = e[2], subEntries(e[2])
    local empty = true
    for i = 1, 7 do if entries[i] then empty = false end end
    flash(empty and "|cffff8060(nobody yet)|r" or "")
    draw()
  elseif e[3] == "channel" then
    local ch = {}
    for k, v in pairs(e[2]) do ch[k] = v end
    ch.sector = level == "top" and highlightIndex or SECTOR[level]
    DB.channel = ch                                    -- the pick is the new default (disabled ones too:
    flash("Now: " .. channelLabel(ch))                  -- WoW then says why it can't send)
    if ind:IsShown() then indicatorDestination() end
    draw()
  elseif e[3] == "command" then
    local ok, err = pcall(e[2])
    if not ok then note("command failed: " .. tostring(err)) end
  elseif e[3] == "option" then
    local o = e[2]
    DB.mode = o[2]
    if o[3] then DB.countdown = o[3] end
    say("send: " .. o[1])
  end
end

------------------------------------------------------------------ WoW's own chat sets the default too
-- Whatever the player last sent (by voice or typed in WoW's chat) is "the selected destination".
local SECTOR_OF = { SAY = 1, YELL = 1, PARTY = 2, RAID = 2, RAID_WARNING = 2, BATTLEGROUND = 2, INSTANCE_CHAT = 2,
                    GUILD = 3, OFFICER = 3, WHISPER = 4, CHANNEL = 7 }
hooksecurefunc("SendChatMessage", function(_, chatType, _, target)
  if not DB or not chatType or not SECTOR_OF[chatType] then return end
  local ch = { type = chatType, sector = SECTOR_OF[chatType] }
  if chatType == "WHISPER" then
    ch.target = target and tostring(target)
    remember(DB.whispers, ch.target)
  elseif chatType == "CHANNEL" then
    ch.target = tonumber(target) or target
    local _, name = GetChannelName(ch.target)
    ch.label = name
  end
  DB.channel = ch
end)
if BNSendWhisper then
  hooksecurefunc("BNSendWhisper", function(id)
    if not DB or not id then return end
    local acc = C_BattleNet and C_BattleNet.GetAccountInfoByID and C_BattleNet.GetAccountInfoByID(id)
    local label = acc and ((acc.accountName ~= "" and acc.accountName) or acc.battleTag) or "Battle.net"
    DB.channel = { type = "BN_WHISPER", target = id, label = (label:gsub("#%d+$", "")), sector = 5 }
  end)
end

------------------------------------------------------------------ signals
local CS = { F1 = openRing, F2 = closeRing, F3 = pick, F4 = openBox, F5 = startCountdown,
             F6 = function() if correctionOpen() then corr:Hide() end sendBox("tool") end,
             F7 = function() openCorrection() end, F8 = replaceBegin, F9 = replaceDone,
             F10 = function() indicate("listen") end, F11 = function() indicate("work") end,
             F12 = function() indicate(nil) end }
local SH = {}
for i = 1, 8 do SH["F" .. i] = function() highlightSlot(i) end end
local AS = {}                                           -- Alt+Shift+F<n>: more signals (F1 = R4 tapped: dialog focus)
-- Shift+F9 = hello: the tool runs (it says so a few times after every login and /reload; the first one counts)
local helloSeen = false
SH.F9 = function()
  if helloSeen then return end
  helloSeen = true
  if not ind:IsShown() then
    indicate("ready")
    C_Timer.After(4, function() if indWhat == "ready" then indicate(nil) end end)
  end
end

local function onSignal(map, key, via)
  local h = map[key]
  if not h then return end
  note((map == CS and "C-S-" or "S-") .. key .. " via " .. via)
  local ok, err = pcall(h)
  if not ok then note("HANDLER ERROR " .. key .. ": " .. tostring(err)) end
end

-- our box has focus: the keys arrive here
box:SetScript("OnKeyDown", function(_, key)
  if IsShiftKeyDown() and IsControlKeyDown() then onSignal(CS, key, "box")
  elseif IsShiftKeyDown() and IsAltKeyDown() then onSignal(AS, key, "box")
  elseif IsShiftKeyDown() then onSignal(SH, key, "box") end
end)

-- nothing has focus: override bindings to hidden buttons (a key binding click is a hardware event)
local owner = CreateFrame("Frame")
local function bindKeys()
  for map, prefix in pairs({ [CS] = "CTRL-SHIFT-", [SH] = "SHIFT-", [AS] = "ALT-SHIFT-" }) do
    for key in pairs(map) do
      local name = "WowVoice" .. prefix:gsub("%-", "") .. key
      local b = _G[name] or CreateFrame("Button", name, UIParent)
      b:SetScript("OnClick", function() onSignal(map, key, "binding") end)
      SetOverrideBindingClick(owner, true, prefix .. key, name)
    end
  end
end

------------------------------------------------------------------ voice context
-- The tool can't ask WoW anything (sandbox), but it reads this addon's saved file, which WoW writes on /reload
-- and logout. So at logout/reload the addon saves what is relevant right now: quest titles + objectives (items,
-- creatures), zone, bag items, items of the last vendors, online guild members, friends, group. The tool adds
-- them to its names list. When the quest log or a vendor brings new words, the context is "outdated": a small
-- pill under the listening card says so; Options › Refresh context (= /reload) saves a fresh one.
-- The quest log is read WHILE PLAYING (on every change) and kept in DB.questTerms: at logout/reload it may already
-- be empty (v0.4.19 saved no quests at all). Old API (GetQuestLogTitle) or new (C_QuestLog.GetInfo), whichever exists.
local function questList()
  local list = {}                                      -- { {title=, header=, objectives={...}} }
  local Q = C_QuestLog
  local n = (GetNumQuestLogEntries and GetNumQuestLogEntries())
         or (Q and Q.GetNumQuestLogEntries and Q.GetNumQuestLogEntries()) or 0
  for i = 1, n do
    local title, isHeader, questID
    if GetQuestLogTitle then
      local _
      title, _, _, isHeader, _, _, _, questID = GetQuestLogTitle(i)
    elseif Q and Q.GetInfo then
      local info = Q.GetInfo(i)
      if info then title, isHeader, questID = info.title, info.isHeader, info.questID end
    end
    if title then
      local q = { title = title, header = isHeader, objectives = {} }
      if not isHeader then
        if GetNumQuestLeaderBoards and GetQuestLogLeaderBoard then
          for j = 1, (GetNumQuestLeaderBoards(i) or 0) do
            local text = GetQuestLogLeaderBoard(j, i)
            if text then table.insert(q.objectives, text) end
          end
        end
        if #q.objectives == 0 and questID and Q and Q.GetQuestObjectives then
          for _, o in ipairs(Q.GetQuestObjectives(questID) or {}) do
            if o.text then table.insert(q.objectives, o.text) end
          end
        end
      end
      table.insert(list, q)
    end
  end
  return list
end

local function questTermsNow()
  local out = {}
  for _, q in ipairs(questList()) do
    table.insert(out, q.title)
    for _, text in ipairs(q.objectives) do
      table.insert(out, (text:gsub(":%s*%d+%s*/%s*%d+%s*$", ""):gsub("^%d+%s*/%s*%d+%s+", ""):gsub("%s+slain$", "")))
    end
  end
  return out
end

local function snapshotQuests()
  local ok, terms = pcall(questTermsNow)
  if not ok then note("quest read failed: " .. tostring(terms)) return end
  if #terms == 0 then return end                       -- logging out / not loaded yet: keep the last copy
  local joined = table.concat(terms, ";")
  if joined ~= DB.questTermsJoined then
    DB.questTerms, DB.questTermsJoined = terms, joined
    note("quests read: " .. #terms .. " terms (" .. (GetQuestLogTitle and "old" or "C_QuestLog") .. " API)")
  end
  local zone, sub = GetRealZoneText and GetRealZoneText(), GetSubZoneText and GetSubZoneText()
  if zone and zone ~= "" then DB.zoneTerms = { zone, sub } end
end

local function ctxTerms()
  local seen, out = {}, {}
  local function add(t)
    if type(t) ~= "string" then return end
    t = strtrim((t:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub(";", " ")))
    if #t >= 3 and #t <= 40 and not seen[t:lower()] then seen[t:lower()] = true; table.insert(out, t) end
  end
  snapshotQuests()
  for _, t in ipairs(DB.questTerms or {}) do add(t) end
  for _, t in ipairs(DB.zoneTerms or {}) do add(t) end
  add(GetRealZoneText()); add(GetSubZoneText())
  local C = C_Container
  local numSlots = (C and C.GetContainerNumSlots) or GetContainerNumSlots
  local itemLink = (C and C.GetContainerItemLink) or GetContainerItemLink
  for bag = 0, 4 do
    for slot = 1, (numSlots and numSlots(bag) or 0) do
      local link = itemLink(bag, slot)
      if link then add(link:match("%[(.-)%]")) end
    end
  end
  for _, name in ipairs(DB.vendorItems or {}) do add(name) end
  for i = 1, (GetNumGuildMembers and GetNumGuildMembers() or 0) do
    local name, _, _, _, _, _, _, _, online = GetGuildRosterInfo(i)
    if name and online then add(short(name)) end
  end
  for _, item in ipairs(friendsList()) do if not item[3] then add(item[1]) end end
  local unit = IsInRaid() and "raid" or "party"
  for i = 1, (GetNumGroupMembers and GetNumGroupMembers() or 0) do add(UnitName(unit .. i)) end
  return out
end

local function questSig()
  local t = {}
  local ok, list = pcall(questList)
  for _, q in ipairs(ok and list or {}) do if not q.header then table.insert(t, q.title) end end
  table.sort(t)
  return table.concat(t, ";")
end

local ctxSaved, ctxQuestSig = nil, nil                  -- what the tool has (from the last save)
local ctxPill = CreateFrame("Frame", nil, ind, BackdropTemplateMixin and "BackdropTemplate" or nil)
ctxPill:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
                      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16,
                      edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
ctxPill:SetBackdropColor(0.05, 0.04, 0.03, 0.92)
ctxPill:SetBackdropBorderColor(1, 0.55, 0.15, 1)
ctxPill:SetPoint("TOP", ind, "BOTTOM", 0, -4)
local ctxText = ctxPill:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
ctxText:SetPoint("CENTER")
ctxText:SetText("|cffffa040Voice context outdated|r  ·  Options › Refresh context |cffb0a890(reloads your UI)|r")
ctxPill:SetSize(ctxText:GetStringWidth() + 20, ctxText:GetStringHeight() + 12)
ctxPill:Hide()

local function setOutdated(why)
  if ctxState.outdated then return end
  ctxState.outdated = true
  ctxPill:Show()
  note("context outdated: " .. why)
end

local function saveContext()
  local ok, terms = pcall(ctxTerms)
  if ok then
    DB.ctx = table.concat(terms, ";")
    DB.ctxAt = time()
  else
    note("context failed: " .. tostring(terms))
  end
end

local function seeVendor()
  local names = {}
  for i = 1, (GetMerchantNumItems and GetMerchantNumItems() or 0) do
    local name = GetMerchantItemInfo(i)
    if name then table.insert(names, name) end
  end
  if #names == 0 then return end
  DB.vendorItems = DB.vendorItems or {}
  local have = {}
  for _, n in ipairs(DB.vendorItems) do have[n] = true end
  local new = 0
  for i = #names, 1, -1 do
    if not have[names[i]] then table.insert(DB.vendorItems, 1, names[i]); new = new + 1 end
  end
  if new > 0 then note("vendor seen: " .. new .. " new items") end
  while #DB.vendorItems > 150 do table.remove(DB.vendorItems) end
  if new > 0 and ctxSaved then
    for _, n in ipairs(names) do if not ctxSaved[n:lower()] then setOutdated("vendor " .. n) break end end
  end
end

------------------------------------------------------------------ dialog (updates): tap R4 to focus it, A / B answer
-- Many addon popups need a mouse; this one doesn't. It never blocks play: only after a tap on R4 (the app reads R4
-- and sends Alt+Shift+F1) does it take A / B. Not the game's own navigation (View, auto-highlight): an addon frame
-- hooked into it taints the game's code for the session (see GamepadSuite's notes). Out of combat only.
local showDialog
local dialog = CreateFrame("Frame", "WowVoiceDialog", UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
dialog:SetSize(460, 190)
dialog:SetPoint("CENTER", 0, 160)
dialog:SetFrameStrata("DIALOG")
dialog:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
                     tile = true, tileSize = 16, edgeSize = 16, insets = { left = 4, right = 4, top = 4, bottom = 4 } })
dialog:SetBackdropColor(0.05, 0.04, 0.03, 0.95)
dialog:SetBackdropBorderColor(0.85, 0.65, 0.25, 1)
dialog:Hide()
local dlgTitle = dialog:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
dlgTitle:SetPoint("TOP", 0, -18)
local dlgText = dialog:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
dlgText:SetPoint("TOP", dlgTitle, "BOTTOM", 0, -12)
dlgText:SetWidth(410)
dlgText:SetSpacing(3)
local dlgHint = dialog:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
dlgHint:SetPoint("BOTTOM", 0, 54)
dlgHint:SetTextColor(0.85, 0.75, 0.5)
local dlgA = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
dlgA:SetSize(180, 26)
local dlgB = CreateFrame("Button", nil, dialog, "UIPanelButtonTemplate")
dlgB:SetSize(180, 26)
dlgB:SetPoint("BOTTOMLEFT", dialog, "BOTTOM", 6, 18)
local dlgQueue, dlgCurrent = {}, nil
local function dlgLook(focused)
  if focused then dialog:SetBackdropBorderColor(0.35, 1, 0.35, 1) else dialog:SetBackdropBorderColor(0.85, 0.65, 0.25, 1) end
end

local function dlgClose(which)
  local d = dlgCurrent
  dialog:EnableGamePadButton(false)
  dlgLook(false)
  dialog:Hide()
  dlgCurrent = nil
  if d and d[which] then d[which]() end
  if #dlgQueue > 0 then C_Timer.After(0.3, function() if not dlgCurrent then showDialog(table.remove(dlgQueue, 1)) end end) end
end
AS.F1 = function()                                       -- R4 tapped: now A / B answer the dialog
  if not dlgCurrent or InCombatLockdown() then return end
  dialog:EnableGamePadButton(true)
  dlgLook(true)
  dlgHint:SetText(G("a") .. " " .. (dlgCurrent.a or "OK") .. (dlgCurrent.b and ("        " .. G("b") .. " " .. dlgCurrent.b) or ""))
end
dialog:SetScript("OnGamePadButtonDown", function(_, button)
  if button == "PAD1" then dlgClose("onA")
  elseif button == "PAD2" and dlgCurrent and dlgCurrent.b then dlgClose("onB") end
end)
dlgA:SetScript("OnClick", function() dlgClose("onA") end)
dlgB:SetScript("OnClick", function() dlgClose("onB") end)

showDialog = function(d)
  if dlgCurrent or InCombatLockdown() then table.insert(dlgQueue, d) return end
  dlgCurrent = d
  dlgTitle:SetText(d.title)
  dlgText:SetText(d.text or "")
  dlgA:SetText(d.a or "OK")
  dlgA:ClearAllPoints()
  if d.b then
    dlgB:SetText(d.b); dlgB:Show()
    dlgA:SetPoint("BOTTOMRIGHT", dialog, "BOTTOM", -6, 18)
  else
    dlgB:Hide()
    dlgA:SetPoint("BOTTOM", 0, 18)
  end
  dialog:SetHeight(dlgText:GetStringHeight() + 130)
  dlgHint:SetText("Tap " .. G("r4") .. " to answer with your controller")
  dlgLook(false)
  dialog:Show()
end

-- what the app tells us (Shift+F10..F12, see the app's updater.py)
SH.F10 = function()
  showDialog({ title = "Update finished", text = "Reload to use the new version.", a = "Reload now", onA = ReloadUI,
               b = "Later" })
end
SH.F11 = function()
  showDialog({ title = "Update failed", text = "Nothing was changed. The details are in the app's log:\n"
               .. "~/my-steam-deck-gets-me/.cache/service.log" })
end
SH.F12 = function()
  showDialog({ title = "Addon and app don't fit", text = "This addon version doesn't work with the installed app.\n"
               .. "Update the addon (CurseForge), or run the app's installer again." })
end

local function offerUpdate(always)                      -- the app left an offer in our saved file (WowVoiceUpdate)
  local U = WowVoiceUpdate
  if not (U and U.version) then
    if always then say("no update waiting.") end
    return
  end
  if not always and DB.updateSnooze and time() - DB.updateSnooze < 12 * 3600 then return end
  local text = (U.notes and U.notes ~= "" and (U.notes .. "\n\n") or "")
    .. (U.addon and "The app and this addon are updated; the game reloads once."
        or "This updates the app. The addon came from elsewhere: update it there (CurseForge).")
  showDialog({ title = "Update available: v" .. U.version, text = text, a = "Update now", b = "Later",
    onA = function()
      DB.updateRequest = U.version                       -- the app sees it as soon as WoW saves (the reload)
      WowVoiceUpdate = nil
      ReloadUI()
    end,
    onB = function() DB.updateSnooze = time() end })
end

local function afterUpdate()                            -- first start of a new version: what's left to do
  local R = WowVoiceRelease
  if not (R and R.version == VERSION) or DB.seenRelease == VERSION then return end
  local first = DB.seenRelease == nil                   -- a fresh install: nothing to report
  DB.seenRelease = VERSION
  if first then return end
  if R.after == "restart_wow" then
    showDialog({ title = "One more step", text = "Updated to v" .. VERSION .. ". Quit WoW completely and start it again"
                 .. " to finish the update." })
  elseif R.after == "restart_steam" then
    showDialog({ title = "One more step", text = "Updated to v" .. VERSION .. ". Restart Steam to finish the update"
                 .. " (Desktop Mode: Steam menu > Exit; Game Mode: restart the Deck)." })
  else
    say("updated to v" .. VERSION .. (R.notes and R.notes ~= "" and (": " .. R.notes) or ""))
  end
end

------------------------------------------------------------------ events
owner:RegisterEvent("ADDON_LOADED")
owner:RegisterEvent("PLAYER_LOGOUT")
owner:RegisterEvent("QUEST_LOG_UPDATE")
owner:RegisterEvent("MERCHANT_SHOW")
owner:RegisterEvent("MERCHANT_UPDATE")
owner:RegisterEvent("PLAYER_LOGIN")
owner:RegisterEvent("PLAYER_REGEN_ENABLED")
owner:RegisterEvent("ADDON_ACTION_BLOCKED")
owner:RegisterEvent("ADDON_ACTION_FORBIDDEN")
for _, ev in ipairs({ "CHAT_MSG_WHISPER", "CHAT_MSG_WHISPER_INFORM", "CHAT_MSG_SAY", "CHAT_MSG_YELL",
                      "CHAT_MSG_PARTY", "CHAT_MSG_PARTY_LEADER", "CHAT_MSG_RAID", "CHAT_MSG_RAID_LEADER",
                      "CHAT_MSG_GUILD", "GROUP_ROSTER_UPDATE", "PLAYER_TARGET_CHANGED", "FRIENDLIST_UPDATE", "GUILD_ROSTER_UPDATE" }) do
  owner:RegisterEvent(ev)
end
owner:SetScript("OnEvent", function(self, event, a1, a2)
  if event == "ADDON_ACTION_BLOCKED" or event == "ADDON_ACTION_FORBIDDEN" then
    note(event .. ": " .. tostring(a1) .. " " .. tostring(a2))
  elseif event == "ADDON_LOADED" and a1 == "WowVoice" then
    WowVoiceDB = WowVoiceDB or {}
    for k, v in pairs(DEFAULTS) do if WowVoiceDB[k] == nil then WowVoiceDB[k] = v end end
    if WowVoiceDB.cameraSaved then                     -- left by v0.2.3
      for name, value in pairs(WowVoiceDB.cameraSaved) do pcall(SetCVar, name, value) end
      WowVoiceDB.cameraSaved = nil
    end
    DB = WowVoiceDB
    DB.updateRequest = nil                             -- it reached the app with the save of the reload that sent it
    DB.log = {}
    note("loaded v" .. VERSION)
    DB.unitMenu = nil
    ctxSaved = {}
    for t in (DB.ctx or ""):gmatch("[^;]+") do ctxSaved[t:lower()] = true end
  elseif event == "PLAYER_REGEN_ENABLED" then
    if not dlgCurrent and #dlgQueue > 0 then showDialog(table.remove(dlgQueue, 1)) end
  elseif event == "PLAYER_LOGIN" then
    C_Timer.After(8, function() afterUpdate(); offerUpdate() end)
    bindKeys()
    requestFriends()
    layout()
    if IsInGuild() then
      if C_GuildInfo and C_GuildInfo.GuildRoster then pcall(C_GuildInfo.GuildRoster) elseif GuildRoster then pcall(GuildRoster) end
    end
    say("v" .. VERSION .. " ready · double-press & hold R4 = ring · /wowvoice")
    C_Timer.After(90, function()                       -- the tool says hello within a minute of every UI load
      if not helloSeen then
        say("|cffff8060no contact with the My Steam Deck Gets Me tool.|r Is it installed and running? (Desktop Mode: "
            .. "systemctl --user status my-steam-deck-gets-me)")
      end
    end)
    if not DB.ctx then setOutdated("never saved") end
  elseif not DB then
    return
  elseif event == "CHAT_MSG_WHISPER" or event == "CHAT_MSG_WHISPER_INFORM" then
    remember(DB.whispers, a2)
  elseif event:find("^CHAT_MSG_") then
    remember(DB.recent, a2)
  elseif event == "GROUP_ROSTER_UPDATE" then
    local n = GetNumGroupMembers and GetNumGroupMembers() or 0
    local unit = IsInRaid() and "raid" or "party"
    for i = 1, n do remember(DB.recent, UnitName(unit .. i)) end
  elseif event == "GUILD_ROSTER_UPDATE" then
    wipe(guildNames)
    for i = 1, (GetNumGuildMembers and GetNumGuildMembers() or 0) do
      local n = GetGuildRosterInfo(i)
      if n then table.insert(guildNames, short(n)) end
    end
  elseif event == "FRIENDLIST_UPDATE" then
    if ring:IsShown() and level == "Friends" then entries = subEntries("Friends"); draw() end
  elseif event == "PLAYER_TARGET_CHANGED" then
    if targetName() then remember(DB.recent, targetName()) end
  elseif event == "PLAYER_LOGOUT" then                 -- also on /reload: WoW writes the file right after
    saveContext()
  elseif event == "QUEST_LOG_UPDATE" then
    snapshotQuests()
    local sig = questSig()
    if ctxQuestSig == nil then ctxQuestSig = sig        -- the quest log as it was saved
    elseif sig ~= ctxQuestSig then setOutdated("quest log changed") end
  elseif event == "MERCHANT_SHOW" or event == "MERCHANT_UPDATE" then
    seeVendor()
  end
end)

SLASH_WOWVOICE1 = "/wowvoice"
SlashCmdList.WOWVOICE = function(msg)
  if msg == "ring" then openRing() return end
  if msg == "update" then offerUpdate(true) return end
  local where = msg:match("^pos%s+(%a+)")
  if where == "left" or where == "center" or where == "right" then
    DB.pos = where; say("wheel position: " .. where); if ring:IsShown() then layout() end return
  end
  local n = tonumber(msg:match("^size%s+(%d+)"))
  if n then DB.wheelSize = n; say("wheel size " .. n); if ring:IsShown() then layout(); draw() end return end
  if msg == "close" then closeRing(); closeBox() return end
  say("v" .. VERSION .. " · last channel: " .. channelLabel(DB.channel) .. " · mode " .. DB.mode ..
      (DB.mode == "countdown" and (" " .. DB.countdown .. " s") or "") .. ".  /wowvoice ring · close · size N · pos left|center|right")
end
