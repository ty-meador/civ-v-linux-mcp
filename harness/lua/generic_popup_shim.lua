-- Runs inside the GenericPopup Lua state (ui/ingame/popups/genericpopup.lua), which hosts every
-- popupsgeneric/*Popup.lua confirmation: BUTTONPOPUP_RETURN_CIVILIAN (keep or return a captured
-- civilian), ANNEX_CITY / PUPPET_CITY, BARBARIAN_RANSOM, MINOR_CIV_ENTER_TERRITORY, CONFIRM_COMMAND,
-- DECLAREWARMOVE ... Those layouts build their buttons with the global AddButton(text, fn) and the
-- click handlers are closures registered on the buttons -- there is no way to trigger them from Lua
-- afterwards. So AddButton is wrapped once: every button's text and handler is remembered in
-- __H_BTN until ClearButtons() (called from HideWindow) empties it. H.answer_popup(n) then calls the
-- remembered handler and closes the window exactly like a click.
if not __H_BTN_SHIM then
  __H_BTN_SHIM = true
  __H_BTN = {}
  local orig_add, orig_clear = AddButton, ClearButtons
  AddButton = function(text, fn, tip, prevent_close)
    __H_BTN[#__H_BTN + 1] = { text = text, fn = fn, prevent_close = prevent_close and true or false }
    return orig_add(text, fn, tip, prevent_close)
  end
  ClearButtons = function(...)
    __H_BTN = {}
    return orig_clear(...)
  end
end

function __H_popup_state()
  local buttons = {}
  for i, b in ipairs(__H_BTN) do buttons[i] = { id = i, text = b.text } end
  local text = Controls.PopupText and Controls.PopupText:GetText() or nil
  local shown = 0
  for i = 1, 8 do
    local c = Controls["Button" .. i]
    if c and not c:IsHidden() then shown = shown + 1 end
  end
  return { open = not ContextPtr:IsHidden(), text = text, buttons = buttons, buttons_shown = shown }
end

function __H_answer_popup(n)
  if ContextPtr:IsHidden() then return { ok = false, err = "no generic popup is open" } end
  local b = __H_BTN[n]
  if not b then
    return { ok = false, err = "no such button (the popup may have opened before the shim was installed; "
                               .. "answer it by hand with `lua` in state GenericPopup, then HideWindow())",
             buttons = #__H_BTN }
  end
  local ok, err = pcall(b.fn)
  if not b.prevent_close then HideWindow() end
  return { ok = ok, err = (not ok) and tostring(err) or nil, clicked = b.text, closed = ContextPtr:IsHidden() }
end
