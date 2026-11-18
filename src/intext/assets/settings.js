const LABELS = {
  auto: "自动",
  zh: "简体中文",
  "zh-Hans": "简体中文",
  en: "英语",
  ja: "日语",
  ko: "韩语",
  fr: "法语",
  de: "德语",
  es: "西班牙语",
  ru: "俄语"
};
const SOURCE_OPTIONS = ["auto", "zh", "en", "ja", "ko", "fr", "de", "es", "ru"];
const TARGET_OPTIONS = ["zh", "en", "ja", "ko", "fr", "de", "es", "ru"];
const SPECS = [
  { key: "temperature", label: "温度", kind: "number", value: "1", hint: "部分模型不接受。" },
  { key: "top_p", label: "top_p", kind: "number", value: "1", hint: "通常与温度只开一个。" },
  { key: "max_tokens", label: "最大长度", kind: "number", value: "1024", hint: "启用时填写正整数，不启用则由模型决定。" },
  { key: "reasoning_effort", label: "思考强度", kind: "combo", value: "medium", options: ["low", "medium", "high"], hint: "可选择预设或输入模型支持的值；不接受就保持关闭。" },
  { key: "frequency_penalty", label: "频率惩罚", kind: "number", value: "0", hint: "降低重复用词。" },
  { key: "presence_penalty", label: "存在惩罚", kind: "number", value: "0", hint: "鼓励新内容。" }
];
const state = {
  endpoint: "https://api.openai.com/v1/chat/completions",
  apiKey: "",
  model: "",
  source: "auto",
  target: "zh",
  hotkey: "ctrl+alt+q",
  shotHotkey: "ctrl+alt+e",
  shotInput: "ocr",
  shotDisplay: "popup",
  hotkeyError: "",
  shotHotkeyError: "",
  hotkeyShown: "",
  shotHotkeyShown: "",
  fields: Object.fromEntries(SPECS.map((spec) => [spec.key, { enabled: false, value: spec.value }]))
};
let saveTimer = 0;
let saveQueue = Promise.resolve();
let saveVersion = 0;
let editVersion = 0;
let pendingSaves = 0;
let initialized = false;
let pendingLanguages = null;

function showSaveError(failed) {
  const button = document.getElementById("save-error");
  if (!failed && document.activeElement === button) document.getElementById("stash").focus({ preventScroll: true });
  button.hidden = !failed;
  document.getElementById("save-announcement").textContent = failed ? "设置保存失败，请重试" : "";
}

function languageLabel(code) {
  return LABELS[code] || code;
}

function systemPrompt(source, target) {
  const targetName = languageLabel(target);
  if (!source || source === "auto") {
    return "Translate the user's text into " + targetName + ". " + intextPolicy.structure;
  }
  return "Translate the user's text from " + languageLabel(source) + " into " + targetName + ". " + intextPolicy.structure;
}

// Same spelling rule as fields.NUMBER_TEXT. Do not use Number() on raw text.
const NUMBER_TEXT = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function coerce(spec, raw) {
  const text = String(raw == null ? "" : raw).trim();
  if (!text) return null;
  if (spec.kind === "number") {
    if (!NUMBER_TEXT.test(text)) return null;
    const number = Number(text);
    if (!Number.isFinite(number)) return null;
    if (spec.key === "max_tokens" && (number <= 0 || !Number.isInteger(number))) return null;
    return Number.isInteger(number) ? number : number;
  }
  return text;
}

function requestBody() {
  const body = {
    model: state.model.trim(),
    messages: [
      { role: "system", content: systemPrompt(state.source, state.target) },
      { role: "user", content: "<选中文字>" }
    ]
  };
  if (document.getElementById('preview-kind').value === 'shot') {
    if (state.shotDisplay === 'overlay' || state.shotInput === 'image') {
      const overlay = state.shotDisplay === 'overlay';
      body.messages[0].content += ' ' + (overlay ? intextPolicy.blocks : intextPolicy.image);
      const text = overlay ? '{"regions": [{"id": 0, "text": "<截图文字区域>"}]}' : 'Translate the selected image.';
      body.messages[1].content = state.shotInput === 'image' ? [{type:'text',text}, {type:'image_url',image_url:{url:'data:image/png;base64,<截图PNG>'}}] : text;
    } else body.messages[1].content = '<截图识别文字>';
  }
  SPECS.forEach((spec) => {
    const item = state.fields[spec.key];
    if (!item || !item.enabled) return;
    const value = coerce(spec, item.value);
    if (value === null) return;
    body[spec.key] = value;
  });
  return body;
}

function highlight(text) {
  const pattern = /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}\[\],:]|\s+/g;
  const code = document.querySelector("#live code");
  code.replaceChildren();
  let match;
  let last = 0;
  const tokens = [];
  while ((match = pattern.exec(text))) {
    if (match.index > last) tokens.push(text.slice(last, match.index));
    tokens.push(match[0]);
    last = match.index + match[0].length;
  }
  if (last < text.length) tokens.push(text.slice(last));
  const fragment = document.createDocumentFragment();
  tokens.forEach((token, index) => {
    let className = "";
    if (token[0] === '"') {
      let next = index + 1;
      while (next < tokens.length && /^\s+$/.test(tokens[next])) next += 1;
      className = tokens[next] === ":" ? "tok-key" : "tok-str";
    } else if (/^-?\d/.test(token)) {
      className = "tok-num";
    } else if (token === "true" || token === "false" || token === "null") {
      className = "tok-lit";
    }
    if (!className) {
      fragment.append(document.createTextNode(token));
      return;
    }
    const span = document.createElement("span");
    span.className = className;
    span.textContent = token;
    fragment.append(span);
  });
  code.append(fragment);
}

function renderCode() {
  const text = JSON.stringify(requestBody(), null, 2);
  const live = document.getElementById("live");
  if (live.dataset.signature === text) return;
  live.dataset.signature = text;
  highlight(text);
}

const SELECT_TIP = "需要修饰键。Esc 取消录制。";
const SHOT_TIP = "拖动选择矩形，按住 Ctrl 可自由圈选。Esc 或右键取消截图；录制快捷键时 Esc 取消录制。";
const ERROR_TIPS = {
  "已被占用": "注册失败，可能已被其他程序占用。",
  "注册失败": "没有注册成功。",
  "无效": "这个组合无法注册。",
  "重复": "不能和另一个快捷键相同。"
};

function hotkeyLabel(spec) {
  const names = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", win: "Win" };
  return String(spec || "").split("+").filter(Boolean).map((part) => names[part] || part.toUpperCase()).join(" + ");
}

let recording = "";

function paintKey(button, recordingNow, spec, error) {
  const failed = !recordingNow && !!error;
  button.replaceChildren();
  const keys = document.createElement("span");
  keys.className = "keycap-keys";
  keys.textContent = recordingNow ? "请按键" : hotkeyLabel(spec);
  button.dataset.tooltip = recordingNow ? "Esc 取消录制" : hotkeyLabel(spec) + (failed ? " · " + error : "");
  button.append(keys);
  button.classList.toggle("is-on", recordingNow);
  button.classList.toggle("is-bad", failed);
  if (failed) {
    button.setAttribute("aria-invalid", "true");
    const note = document.createElement("span");
    note.className = "keycap-state";
    note.textContent = error;
    button.append(note);
  } else {
    button.removeAttribute("aria-invalid");
  }
}

function renderKeys() {
  const selectError = recording === "hotkey" ? "" : state.hotkeyError;
  const shotError = recording === "shotHotkey" ? "" : state.shotHotkeyError;
  paintKey(
    document.getElementById("hotkey-select"),
    recording === "hotkey",
    state.hotkeyShown || state.hotkey,
    selectError
  );
  paintKey(
    document.getElementById("hotkey-shot"),
    recording === "shotHotkey",
    state.shotHotkeyShown || state.shotHotkey,
    shotError
  );
  document.getElementById("select-tip").textContent = selectError ? (ERROR_TIPS[selectError] || SELECT_TIP) : SELECT_TIP;
  document.getElementById("shot-tip").textContent = shotError ? (ERROR_TIPS[shotError] || SHOT_TIP) : SHOT_TIP;
}

function recordKey(name) {
  recording = name;
  renderKeys();
}

function cancelRecording() {
  if (!recording) return;
  recording = "";
  renderKeys();
}

function adoptOne(key, errorKey, shownKey, asked, returned, error, fromKeys) {
  if (!fromKeys && state[shownKey]) return;
  if (fromKeys && error && returned && returned !== asked) {
    state[shownKey] = asked;
    state[key] = returned;
    state[errorKey] = error;
    return;
  }
  state[shownKey] = "";
  state[key] = returned || asked;
  state[errorKey] = error;
}

function adoptHotkeys(value, askedSelect, askedShot, fromKeys) {
  if (!value) return;
  adoptOne("hotkey", "hotkeyError", "hotkeyShown", askedSelect, value.hotkey, value.hotkeyError || "", fromKeys);
  adoptOne("shotHotkey", "shotHotkeyError", "shotHotkeyShown", askedShot, value.shotHotkey, value.shotHotkeyError || "", fromKeys);
  renderKeys();
}

function pushSave(fromKeys) {
  const bridge = window.pywebview && window.pywebview.api;
  if (bridge && typeof bridge.save === "function") {
    const sentSelect = state.hotkey;
    const sentShot = state.shotHotkey;
    const payload = JSON.parse(JSON.stringify(state));
    delete payload.hotkeyShown;
    delete payload.shotHotkeyShown;
    delete payload.hotkeyError;
    delete payload.shotHotkeyError;
    const version = ++saveVersion;
    pendingSaves++;
    saveQueue = saveQueue.then(() => bridge.save(payload)).then(function (value) {
      if (version === saveVersion) {
        adoptHotkeys(value, sentSelect, sentShot, !!fromKeys);
        showSaveError(false);
      }
      return true;
    }).catch(() => { if (version === saveVersion) showSaveError(true); return false; })
      .finally(() => { pendingSaves--; });
    return saveQueue;
  }
  showSaveError(true);
  return Promise.resolve(false);
}

async function saveAndHide() {
  clearTimeout(saveTimer);
  saveTimer = 0;
  const version = saveVersion + 1, edits = editVersion;
  if (await pushSave() && version === saveVersion && edits === editVersion) api("hide");
}

let pendingHotkeys = null;

function applyHotkeys(next) {
  if (!next) return;
  pendingHotkeys = next;
  if (!state.hotkeyShown && next.hotkey === state.hotkey && Object.prototype.hasOwnProperty.call(next, "hotkeyError")) {
    state.hotkeyError = next.hotkeyError || "";
  }
  if (!state.shotHotkeyShown && next.shotHotkey === state.shotHotkey && Object.prototype.hasOwnProperty.call(next, "shotHotkeyError")) {
    state.shotHotkeyError = next.shotHotkeyError || "";
  }
  renderKeys();
}

function paintField(line, spec) {
  const field = line.querySelector(".value");
  if (field.scrollWidth > field.clientWidth) field.dataset.tooltip = field.value;
  else delete field.dataset.tooltip;
  const enabled = line.querySelector(".switch").getAttribute("aria-checked") === "true";
  const invalid = enabled && coerce(spec, field.value) === null;
  line.classList.toggle("is-off", !enabled);
  line.classList.toggle("is-invalid", invalid);
  const visual = field;
  if (invalid) visual.setAttribute("aria-invalid", "true");
  else visual.removeAttribute("aria-invalid");
  line.querySelector(".tip").textContent = invalid
    ? (spec.key === "max_tokens" ? "请输入正整数。" : spec.kind === "number" ? "请输入有效数字。" : "请输入思考强度。") + spec.hint
    : spec.hint;
}

function paintEndpoint() {
  const input = document.getElementById("endpoint");
  const value = input.value.trim();
  let valid = false;
  try {
    const address = new URL(value);
    valid = /^https?:\/\//i.test(value) && !!address.hostname && !/\s/.test(value);
  } catch (_) {}
  if (valid) input.removeAttribute("aria-invalid");
  else input.setAttribute("aria-invalid", "true");
  document.getElementById("endpoint-tip").textContent = valid ? "完整的 chat completions 地址。"
    : value ? "接口地址无效，请填写以 http:// 或 https:// 开头的完整地址。" : "请填写完整的 chat completions 地址。";
}

function readControls(debounce) {
  editVersion++;
  state.model = document.getElementById("model").value;
  state.endpoint = document.getElementById("endpoint").value;
  paintEndpoint();
  state.apiKey = document.getElementById("api-key").value;
  state.source = document.getElementById("source").value;
  state.target = document.getElementById("target").value;
  state.shotInput = document.getElementById('shot-input').value;
  state.shotDisplay = document.getElementById('shot-display').value;
  SPECS.forEach((spec) => {
    const line = document.querySelector('[data-key="' + spec.key + '"]');
    state.fields[spec.key] = {
      enabled: line.querySelector(".switch").getAttribute("aria-checked") === "true",
      value: line.querySelector(".value").value
    };
    paintField(line, spec);
  });
  renderCode();
  clearTimeout(saveTimer);
  saveTimer = 0;
  if (debounce) saveTimer = setTimeout(() => { saveTimer = 0; pushSave(); }, 180);
  else pushSave();
}


let openMenu = null;

let menuAnchor = null;

function closeMenu() {
  if (!openMenu) return;
  if (menuAnchor) {
    menuAnchor.setAttribute("aria-expanded", "false");
    if (menuAnchor._comboInput) menuAnchor._comboInput.setAttribute("aria-expanded", "false");
  }
  openMenu.hidden = true;
  openMenu._below = null;
  openMenu._aligned = false;
  openMenu = null;
  menuAnchor = null;
}

function mountMenu(select) {
  let host = select.parentElement;
  if (!host.classList.contains("choice")) {
    host = document.createElement("div");
    host.className = "choice";
    select.replaceWith(host);
    host.append(select);
  }
  select.classList.add("native-select");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");
  let button = host.querySelector(".menu-btn");
  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.className = "menu-btn";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    const label = document.querySelector('label[for="' + select.id + '"]');
    button.id = select.id + "-button";
    button.setAttribute("aria-label", label ? label.textContent : select.closest(".line").querySelector(".name").firstChild.textContent);
    button.dataset.label = button.getAttribute("aria-label");
    button.setAttribute("aria-controls", "menu-" + select.id);
    if (label) label.htmlFor = button.id;
    button.innerHTML = '<span class="menu-label"></span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.6 6.2 8 9.7 11.4 6.2"/></svg>';
    host.append(button);
    bindMenu(select, button);
  }
  const selected = select.selectedOptions[0];
  button.querySelector(".menu-label").textContent = selected ? selected.textContent : "";
  button.setAttribute("aria-label", button.dataset.label + (selected ? "：" + selected.textContent : ""));
}

function bindMenu(select, button) {
  button.addEventListener("click", function (event) {
    event.preventDefault();
    event.stopPropagation();
    const pop = ensurePop(select, button);
    if (openMenu === pop) {
      closeMenu();
      return;
    }
    closeMenu();
    menuAnchor = button;
    pop._aligned = false;
    placeMenu(pop, button);
    pop.hidden = false;
    openMenu = pop;
    button.setAttribute("aria-expanded", "true");
    if (button._comboInput) button._comboInput.setAttribute("aria-expanded", "true");
  });
  button.addEventListener("keydown", function (event) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    if (openMenu !== button._pop || !openMenu) button.click();
    const items = Array.from(openMenu.querySelectorAll(".menu-opt"));
    const selected = openMenu.querySelector(".is-on");
    const item = event.key === "Home" ? items[0] : event.key === "End" ? items[items.length - 1] : selected || (event.key === "ArrowUp" ? items[items.length - 1] : items[0]);
    if (item) {
      item.focus({ preventScroll: true });
      item.scrollIntoView({ block: "nearest" });
    }
  });
}

function mountCombo(input, spec) {
  const host = document.createElement("div");
  host.className = "choice combo";
  input.replaceWith(host);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "menu-btn";
  button.setAttribute("aria-label", "选择" + spec.label);
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", "menu-" + input.id);
  button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.6 6.2 8 9.7 11.4 6.2"/></svg>';
  button._comboInput = input;
  input._presets = spec.options.map(value => ({ value, textContent: value }));
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "none");
  input.setAttribute("aria-haspopup", "listbox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", "menu-" + input.id);
  input.autocomplete = "off";
  host.append(input, button);
  bindMenu(input, button);
  input.addEventListener("keydown", function (event) {
    if (!["ArrowDown", "ArrowUp"].includes(event.key) || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    button.dispatchEvent(new KeyboardEvent("keydown", { key: event.key, bubbles: true, cancelable: true }));
  });
  input.addEventListener("input", closeMenu);
}

function ensurePop(select, button) {
  let pop = button._pop;
  if (!pop) {
    pop = document.createElement("div");
    pop.className = "menu-pop";
    pop.hidden = true;
    pop.setAttribute("role", "listbox");
    pop.id = "menu-" + select.id;
    pop.setAttribute("aria-label", button.dataset.label || button.getAttribute("aria-label"));
    document.body.append(pop);
    pop.addEventListener("mousedown", function (event) { event.stopPropagation(); });
    pop.addEventListener("click", function (event) { event.stopPropagation(); });
    if (window.intextScroll) window.intextScroll.mount(pop, { inset: 3, size: 3, endInset: 8, layer: 60 });
    button._pop = pop;
  }
  pop.replaceChildren();
  const value = select.value.trim();
  Array.from(select.options || select._presets).forEach(function (option) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "menu-opt" + (option.value === value ? " is-on" : "");
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", option.value === value ? "true" : "false");
    item.tabIndex = -1;
    const mark = document.createElement("span");
    mark.className = "menu-mark";
    if (option.value === value) {
      mark.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.6 8.2 6.4 11 12.4 4.8"/></svg>';
    }
    const label = document.createElement("span");
    label.textContent = option.textContent;
    item.append(mark, label);
    item.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      select.value = option.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (select.tagName === "SELECT") mountMenu(select);
      closeMenu();
      (button._comboInput || button).focus({ preventScroll: true });
    });
    item.addEventListener("keydown", function (event) {
      const items = Array.from(pop.querySelectorAll(".menu-opt"));
      let next;
      if (event.key === "ArrowDown") next = items[(items.indexOf(item) + 1) % items.length];
      if (event.key === "ArrowUp") next = items[(items.indexOf(item) + items.length - 1) % items.length];
      if (event.key === "Home") next = items[0];
      if (event.key === "End") next = items[items.length - 1];
      if (next) {
        event.preventDefault();
        next.focus({ preventScroll: true });
        next.scrollIntoView({ block: "nearest" });
      }
      if (event.key === "Tab") {
        event.preventDefault();
        closeMenu();
        window.intextControls.moveFocus(button._comboInput || button, event.shiftKey);
      }
    });
    pop.append(item);
  });
  return pop;
}

function placeMenu(pop, button) {
  const rect = (button._comboInput ? button.parentElement : button).getBoundingClientRect();
  const gap = 4;
  const margin = 8;
  const below = Math.max(0, window.innerHeight - rect.bottom - gap - margin);
  const above = Math.max(0, rect.top - gap - margin);
  let openBelow = pop._below;
  if (openBelow == null) openBelow = below >= above;
  if (openBelow && below < 88 && above > below) openBelow = false;
  else if (!openBelow && above < 88 && below > above) openBelow = true;
  pop._below = openBelow;
  pop.style.transformOrigin = openBelow ? "left top" : "left bottom";
  pop.style.setProperty("--menu-offset", openBelow ? "4px" : "-4px");
  const room = Math.max(0, Math.min(window.innerHeight - margin * 2, Math.floor(openBelow ? below : above)));
  pop.style.width = rect.width + "px";
  pop.style.minWidth = "0";
  pop.style.maxHeight = room + "px";
  pop.style.left = rect.left + "px";
  pop.hidden = false;
  const height = Math.min(pop.scrollHeight, room);
  const top = openBelow ? rect.bottom + gap : rect.top - gap - height;
  pop.style.top = Math.max(margin, Math.min(window.innerHeight - margin - height, top)) + "px";
  if (!pop._aligned) {
    const current = pop.querySelector(".is-on");
    if (current) {
      const top = current.offsetTop;
      const bottom = top + current.offsetHeight;
      if (top < pop.scrollTop) pop.scrollTop = Math.max(0, top - 4);
      else if (bottom > pop.scrollTop + pop.clientHeight) pop.scrollTop = bottom - pop.clientHeight + 4;
    }
    pop._aligned = true;
  }
}

function fillSelect(id, options, selected) {
  const select = document.getElementById(id);
  select.replaceChildren();
  options.forEach((option) => {
    const node = document.createElement("option");
    node.value = option;
    node.textContent = languageLabel(option);
    select.append(node);
  });
  select.value = options.indexOf(selected) === -1 ? options[0] : selected;
  mountMenu(select);
}

function buildFields() {
  const root = document.getElementById("fields");
  SPECS.forEach((spec) => {
    const line = document.createElement("div");
    line.className = "line is-off";
    line.dataset.key = spec.key;
    const name = document.createElement("div");
    name.className = "name";
    name.append(document.createTextNode(spec.label));
    const help = document.createElement("button");
    help.type = "button";
    help.className = "help";
    help.setAttribute("aria-label", spec.label + "说明");
    help.append(document.createTextNode("?"));
    const tip = document.createElement("span");
    tip.className = "tip";
    tip.textContent = spec.hint;
    help.append(tip);
    name.append(help);
    const input = document.createElement("input");
    input.className = "value";
    input.id = "field-" + spec.key;
    input.setAttribute("aria-label", spec.label);
    input.type = "text";
    if (spec.kind === "number") input.inputMode = "decimal";
    input.spellcheck = false;
    input.value = state.fields[spec.key].value;
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "switch";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", "false");
    toggle.setAttribute("aria-label", "启用" + spec.label);
    toggle.addEventListener("click", function () {
      const on = toggle.getAttribute("aria-checked") !== "true";
      toggle.setAttribute("aria-checked", on ? "true" : "false");
      readControls(false);
    });
    line.append(name, input, toggle);
    if (spec.kind === "combo") mountCombo(input, spec);
    root.append(line);
  });
}

function apply(next) {
  if (!next) return;
  if (Object.hasOwn(next, "endpoint")) state.endpoint = String(next.endpoint || "");
  state.apiKey = next.apiKey || next.api_key || "";
  state.model = next.model || "";
  state.source = (pendingLanguages && pendingLanguages.source) || next.source || "auto";
  state.target = (pendingLanguages && pendingLanguages.target) || next.target || "zh";
  pendingLanguages = null;
  initialized = true;
  state.hotkey = next.hotkey || state.hotkey;
  state.shotHotkey = next.shotHotkey || next.shot_hotkey || state.shotHotkey;
  state.shotInput = (next.shotInput || next.shot_input) === 'image' ? 'image' : 'ocr';
  state.shotDisplay = (next.shotDisplay || next.shot_display) === 'overlay' ? 'overlay' : 'popup';
  if (Object.prototype.hasOwnProperty.call(next, "hotkeyError")) state.hotkeyError = next.hotkeyError || "";
  if (Object.prototype.hasOwnProperty.call(next, "shotHotkeyError")) state.shotHotkeyError = next.shotHotkeyError || "";
  state.hotkeyShown = "";
  state.shotHotkeyShown = "";
  if (pendingHotkeys) applyHotkeys(pendingHotkeys);
  const incoming = next.fields || {};
  SPECS.forEach((spec) => {
    const item = incoming[spec.key] || {};
    state.fields[spec.key] = {
      enabled: !!item.enabled,
      value: item.value == null ? spec.value : String(item.value)
    };
  });
  document.getElementById("model").value = state.model;
  document.getElementById("endpoint").value = state.endpoint;
  paintEndpoint();
  document.getElementById("api-key").value = state.apiKey;
  fillSelect("source", SOURCE_OPTIONS, state.source);
  fillSelect("target", TARGET_OPTIONS, state.target);
  document.getElementById('shot-input').value = state.shotInput;
  document.getElementById('shot-display').value = state.shotDisplay;
  mountMenu(document.getElementById('shot-input'));
  mountMenu(document.getElementById('shot-display'));
  state.source = document.getElementById("source").value;
  state.target = document.getElementById("target").value;
  renderKeys();
  SPECS.forEach((spec) => {
    const line = document.querySelector('[data-key="' + spec.key + '"]');
    const field = line.querySelector(".value");
    field.value = state.fields[spec.key].value;
    line.querySelector(".switch").setAttribute("aria-checked", state.fields[spec.key].enabled ? "true" : "false");
    paintField(line, spec);
  });
  renderCode();
}

function api(name) {
  const bridge = window.pywebview && window.pywebview.api;
  if (bridge && typeof bridge[name] === "function") return bridge[name]();
}

fillSelect("source", SOURCE_OPTIONS, state.source);
fillSelect("target", TARGET_OPTIONS, state.target);
['shot-input', 'shot-display', 'preview-kind'].forEach(id => mountMenu(document.getElementById(id)));
['shot-input', 'shot-display'].forEach(id => document.getElementById(id).addEventListener('change', () => {
  document.getElementById('preview-kind').value = 'shot';
  mountMenu(document.getElementById('preview-kind'));
}));
document.getElementById("endpoint").value = state.endpoint;
renderKeys();
buildFields();
document.getElementById("sheet").addEventListener("submit", function (event) { event.preventDefault(); });
document.getElementById("sheet").addEventListener("input", function () { readControls(true); });
document.getElementById("sheet").addEventListener("change", function () { readControls(false); });
document.getElementById("stash").addEventListener("click", saveAndHide);
document.getElementById("save-error").addEventListener("click", function () { clearTimeout(saveTimer); saveTimer = 0; pushSave(); });
document.getElementById("sheet").addEventListener("scroll", function () {
  const sheet = document.getElementById("sheet");
  sheet.classList.toggle("is-scrolled", sheet.scrollTop > 1);
  if (!openMenu || !menuAnchor) return;
  const buttonRect = menuAnchor.getBoundingClientRect();
  const sheetRect = sheet.getBoundingClientRect();
  const headBottom = document.querySelector(".head").getBoundingClientRect().bottom;
  if (buttonRect.top < headBottom || buttonRect.top >= sheetRect.bottom - 4) {
    closeMenu();
    return;
  }
  placeMenu(openMenu, menuAnchor);
}, { passive: true });
window.addEventListener("resize", function () {
  if (openMenu && menuAnchor) placeMenu(openMenu, menuAnchor);
});
document.addEventListener("wheel", function (event) {
  if (!openMenu || openMenu.hidden) return;
  const rect = openMenu.getBoundingClientRect();
  const over = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
  if (!over) return;
  event.preventDefault();
  event.stopPropagation();
  const max = openMenu.scrollHeight - openMenu.clientHeight;
  if (max <= 0) return;
  const next = Math.max(0, Math.min(max, openMenu.scrollTop + (event.deltaY || 0)));
  if (next !== openMenu.scrollTop) openMenu.scrollTop = next;
}, { capture: true, passive: false });
document.addEventListener("click", function () { closeMenu(); });
document.addEventListener("pointerdown", function (event) {
  if (!openMenu || openMenu.contains(event.target) || menuAnchor.contains(event.target)) return;
  const thumb = event.target.closest?.(".mac-thumb");
  if (thumb && thumb._intextScroller === openMenu) return;
  closeMenu();
}, true);
document.addEventListener("focusin", function (event) {
  if (openMenu && !openMenu.contains(event.target) && event.target !== menuAnchor &&
      event.target !== menuAnchor._comboInput) closeMenu();
});
document.addEventListener("pointerdown", function (event) {
  if (!recording) return;
  if (event.target.closest("#hotkey-select, #hotkey-shot")) return;
  cancelRecording();
});
window.addEventListener("blur", cancelRecording);
window.addEventListener("blur", closeMenu);
document.getElementById("hotkey-select").addEventListener("click", function () { recordKey("hotkey"); });
document.getElementById("hotkey-shot").addEventListener("click", function () { recordKey("shotHotkey"); });
// Recording owns Escape even when the shared tooltip is visible.
document.addEventListener("keydown", function (event) {
  if (!recording || event.isComposing || event.keyCode === 229 || event.key !== "Escape") return;
  event.preventDefault();
  event.stopImmediatePropagation();
  cancelRecording();
  window.intextControls.resetTooltip();
}, true);
document.addEventListener("keydown", function (event) {
  if (event.isComposing || event.keyCode === 229) return;
  if (recording) {
    if (event.key === "Tab" && !event.ctrlKey && !event.altKey && !event.metaKey) {
      cancelRecording();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (["Control", "Alt", "Shift", "Meta"].indexOf(event.key) !== -1) return;
    const parts = [];
    if (event.ctrlKey) parts.push("ctrl");
    if (event.altKey) parts.push("alt");
    if (event.shiftKey) parts.push("shift");
    if (event.metaKey) parts.push("win");
    if (!parts.length) return;
    let key = event.key.toLowerCase();
    if (event.code && event.code.indexOf("Key") === 0) key = event.code.slice(3).toLowerCase();
    if (event.code && event.code.indexOf("Digit") === 0) key = event.code.slice(5);
    if (/^f([1-9]|1[0-2])$/i.test(event.key)) key = event.key.toLowerCase();
    if (!/^([a-z0-9]|f(?:[1-9]|1[0-2]))$/.test(key)) {
      const spec = parts.concat(key).join("+");
      if (recording === "hotkey") {
        state.hotkeyShown = spec;
        state.hotkeyError = "无效";
      } else {
        state.shotHotkeyShown = spec;
        state.shotHotkeyError = "无效";
      }
      recording = "";
      renderKeys();
      return;
    }
    parts.push(key);
    const spec = parts.join("+");
    const other = recording === "hotkey" ? (state.shotHotkeyShown || state.shotHotkey) : (state.hotkeyShown || state.hotkey);
    if (spec === other) {
      if (recording === "hotkey") {
        state.hotkeyShown = spec;
        state.hotkeyError = "重复";
      } else {
        state.shotHotkeyShown = spec;
        state.shotHotkeyError = "重复";
      }
      recording = "";
      renderKeys();
      return;
    }
    state[recording] = spec;
    if (recording === "hotkey") {
      state.hotkeyShown = "";
      state.hotkeyError = "";
    } else {
      state.shotHotkeyShown = "";
      state.shotHotkeyError = "";
    }
    recording = "";
    renderKeys();
    pushSave(true);
    return;
  }
  if (event.key === "Escape" && openMenu) {
    const anchor = menuAnchor;
    closeMenu();
    if (anchor) anchor.focus({ preventScroll: true });
    event.preventDefault();
    return;
  }
  if (event.key === "Escape") {
    saveAndHide();
  }
});
function applyLanguages(next) {
  if (!initialized) {
    pendingLanguages = { source: next.source, target: next.target };
    return;
  }
  state.source = next.source;
  state.target = next.target;
  fillSelect("source", SOURCE_OPTIONS, state.source);
  fillSelect("target", TARGET_OPTIONS, state.target);
  renderCode();
  // Only replay when an earlier settings save could overwrite the
  // language change, which the popup has already persisted itself.
  if (saveTimer || pendingSaves) {
    clearTimeout(saveTimer);
    saveTimer = 0;
    pushSave();
  }
}
window.intextSettings = { apply: apply, hotkeys: applyHotkeys, languages: applyLanguages, body: requestBody };
renderCode();
if (window.intextScroll) {
  window.intextScroll.mount(document.getElementById("sheet"), { inset: 4, size: 4, endInset: 18 });
  window.intextScroll.mount(document.getElementById("live"), { inset: 4, size: 4, endInset: 8 });
}
["n", "s", "e", "w", "nw", "ne", "sw", "se"].forEach(function (edge) {
  const node = document.createElement("div");
  node.className = "resize resize-" + edge;
  node.addEventListener("mousedown", function (event) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const cursors = { n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize", ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize" };
    document.documentElement.classList.add("is-resizing");
    document.documentElement.style.cursor = cursors[edge];
    const bridge = window.pywebview && window.pywebview.api;
    if (bridge && bridge.begin_resize) bridge.begin_resize(edge);
    function up() {
      window.removeEventListener("mouseup", up);
      window.removeEventListener("blur", up);
      document.documentElement.classList.remove("is-resizing");
      document.documentElement.style.cursor = "";
      if (bridge && bridge.end_resize) bridge.end_resize();
    }
    window.addEventListener("mouseup", up);
    window.addEventListener("blur", up);
  });
  node.addEventListener("wheel", function (event) {
    const sheet = document.getElementById("sheet");
    if (!sheet) return;
    event.preventDefault();
    sheet.scrollTop += event.deltaY || 0;
    sheet.scrollLeft += event.deltaX || 0;
  }, { passive: false });
  document.body.appendChild(node);
});
