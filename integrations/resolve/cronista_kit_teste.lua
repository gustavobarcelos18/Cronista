-- Script de teste do Resolve em Lua (1C; plano mestre, seção 6.5). Versão Lua de cronista_kit_teste.py.
--
-- Existe porque o Resolve gratuito 21.2 só oferece Lua no Console e não lista scripts .py no menu Scripts
-- (conferido em 2026-11-16, histórico §39). Roda DE DENTRO do Resolve.
--
-- Instalar: copiar para %APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\ e reiniciar o
-- Resolve; rodar em Área de Trabalho → Scripts. O Console do gratuito não tem `dofile`, `loadfile` nem `io`: nele só
-- dá para colar o código (versão em uma linha, gerada por gerar_linha_unica.py).
--
-- Cada passo imprime OK/FALHOU no Console (e grava resultado-script.txt só se o Lua tiver `io`).

local KIT = "D:\\EditorVideo\\data\\prod\\kit-resolve"
-- Projeto novo a cada rodada: reabrir o da rodada anterior recusa timelines de mesmo nome e mascara os resultados.
local PROJECT = "Cronista-kit-" .. os.date("%H%M%S")
local results = {}
local state = {}

local function step(name, fn)
  local ok, detail = pcall(fn)
  if ok then
    results[#results + 1] = "OK      " .. name .. (detail and (" -> " .. tostring(detail)) or "")
  else
    results[#results + 1] = "FALHOU  " .. name .. ": " .. tostring(detail)
  end
  return ok
end

local function finish()
  if io then -- o Lua do Resolve gratuito 21.2 não tem `io`: nesse caso só imprime
    local f = io.open(KIT .. "\\resultado-script.txt", "w")
    if f then
      f:write(table.concat(results, "\n") .. "\n")
      f:close()
    end
  end
  print(table.concat(results, "\n"))
end

local function count(t)
  local n = 0
  for _ in pairs(t or {}) do n = n + 1 end
  return n
end

local function main()
  if not step("variável resolve disponível (script interno)", function()
    if resolve == nil then error("resolve é nil") end
    return resolve:GetVersionString()
  end) then return finish() end

  if not step("criar projeto", function()
    local pm = resolve:GetProjectManager()
    -- CreateProject devolveu nil na 3ª rodada (projeto aberto com alterações?): usa o projeto aberto como reserva.
    state.project = pm:CreateProject(PROJECT)
    local how = "criado"
    if not state.project then
      state.project = pm:GetCurrentProject()
      how = "CreateProject devolveu nil; usando o projeto aberto"
    end
    if not state.project then error("sem projeto (CreateProject e GetCurrentProject devolveram nil)") end
    return tostring(state.project:GetName()) .. " (" .. how .. ", timelines: " .. state.project:GetTimelineCount() .. ")"
  end) then return finish() end
  local project = state.project

  step("configurar 1920x1080 a 60 fps", function()
    local ok = project:SetSettings({
      timelineResolutionWidth = "1920", timelineResolutionHeight = "1080", timelineFrameRate = "60",
    })
    return "SetSettings=" .. tostring(ok) .. "; fps lido=" .. tostring(project:GetSetting("timelineFrameRate"))
  end)

  local pool = project:GetMediaPool()

  -- Um arquivo por chamada: na 1ª passada (lista de 4) o ImportMedia devolveu vazio sem dizer qual falhou.
  state.items = {}
  for _, n in ipairs({ "A_h264.mp4", "B_h264.mp4", "C_hevc.mp4", "overlay_alfa.mov" }) do
    step("importar mídia " .. n, function()
      local got = pool:ImportMedia({ { FilePath = KIT .. "\\clips\\" .. n } })
      local noPool = count(pool:GetRootFolder():GetClipList())
      if not got or #got == 0 then error("ImportMedia não devolveu item (clipes no pool agora: " .. noPool .. ")") end
      state.items[#state.items + 1] = got[1]
      return "ok (clipes no pool: " .. noPool .. ")"
    end)
  end

  step("criar timeline vazia e anexar o primeiro clipe importado", function()
    state.timeline = pool:CreateEmptyTimeline("kit-script")
    if not state.timeline then error("CreateEmptyTimeline devolveu nil") end
    if not state.items[1] then error("nenhum clipe importado para anexar") end
    local appended = pool:AppendToTimeline({ { mediaPoolItem = state.items[1] } })
    return "anexados=" .. count(appended)
  end)

  step("marcadores coloridos com nome e nota (AddMarker)", function()
    local t = state.timeline
    if not t then error("sem timeline") end
    local r = {
      t:AddMarker(60, "Blue", "Momento", "nota de Momento", 1, "Momento|teste"),
      t:AddMarker(180, "Red", "Morte", "nota de Morte", 1, "Morte|teste"),
      t:AddMarker(300, "Green", "Conquista", "nota de Conquista", 1, "Conquista|teste"),
    }
    return "AddMarker=" .. tostring(r[1]) .. "," .. tostring(r[2]) .. "," .. tostring(r[3]) ..
      "; lidos=" .. count(t:GetMarkers())
  end)

  for _, name in ipairs({
    "01-basico", "02a-titulo", "02b-velocidade", "02c-zoom-keyframes", "02d-transicao", "02e-overlay-alfa",
    "02f-hevc", "03-audio",
  }) do
    step("importar " .. name .. ".fcpxml (ImportTimelineFromFile)", function()
      local tl = pool:ImportTimelineFromFile(KIT .. "\\" .. name .. ".fcpxml", { importSourceClips = true })
      if not tl then error("devolveu nil: o Resolve recusou o arquivo (veja o Console)") end
      if name == "01-basico" then state.timeline_basico = tl end
      return "timeline=" .. tostring(tl:GetName()) .. " video=" .. tl:GetTrackCount("video") ..
        " audio=" .. tl:GetTrackCount("audio") .. " fps=" .. tostring(tl:GetSetting("timelineFrameRate"))
    end)
  end

  step("LUT no primeiro clipe (SetLUT)", function()
    project:RefreshLUTList()
    local tl = state.timeline_basico or state.timeline
    if not tl then error("sem timeline") end
    local clip = tl:GetItemListInTrack("video", 1)[1]
    if not clip then error("sem clipe de vídeo na V1") end
    return "SetLUT=" .. tostring(clip:SetLUT(1, KIT .. "\\teste.cube"))
  end)

  step("importar legenda SRT", function()
    local items = pool:ImportMedia({ { FilePath = KIT .. "\\roteiro.srt" } })
    return "itens=" .. count(items) .. " (conferir a legenda na página Edição)"
  end)

  finish()
end

main()
