let pinned = false;
let appliedSeq = -1;
let copyTimer = 0;
const panel = document.getElementById("panel");
const result = document.getElementById("result");
const source = document.getElementById("source");
const help = document.getElementById("status-help");
const tip = document.getElementById("status-tip");
const content = document.getElementById("content");
const input = document.getElementById("input");
const menu = document.getElementById("languages");
const submitButton = document.getElementById("submit");
const cancelEditButton = document.getElementById("cancel-edit");
const editNote = document.getElementById("edit-note");
const copyButton = document.getElementById("copy");
const retryButton = document.getElementById("retry");
const pinButton = document.getElementById("pin");
const announcement = document.getElementById("announcement");
document.getElementById("swap").append(window.intextControls.languageArrow(true));
const languages = { auto: "自动", zh: "简体中文", en: "英语", ja: "日语", ko: "韩语", fr: "法语", de: "德语", es: "西班牙语", ru: "俄语" };
let sourceCode = "auto", targetCode = "zh", inputMode = false, submitting = false;
let editingSource = false, editSnapshot = null, lastState = null, languageSync = false, standaloneDraft = "";
let menuAnchor = null, sourcePointer = null;

function updateEditNote() {
  const changed = editingSource && editSnapshot &&
    (input.value !== editSnapshot.text || sourceCode !== editSnapshot.source || targetCode !== editSnapshot.target);
  editNote.hidden = !(changed && lastState && lastState.result);
}

function sizeInput() {
  if (!inputMode) { input.style.removeProperty("height"); return; }
  input.style.height = "0px";
  input.style.height = Math.min(152, input.scrollHeight) + "px";
}

function keepEditorVisible() {
  if (editingSource) (editNote.hidden ? input : editNote).scrollIntoView({ block: "nearest" });
}

function validateInput() {
  // Count Unicode code points after the same normalization as translate.py.
  const length = Array.from(input.value.replace(/\r\n?/g, "\n").normalize("NFC").trim()).length;
  const invalid = length > 8000; // translate.MAX_TEXT_CHARS
  const counter = document.getElementById("input-count");
  counter.hidden = !inputMode || length < 7200;
  counter.textContent = length + " / 8000";
  counter.classList.toggle("is-invalid", invalid);
  if (invalid) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
  submitButton.disabled = submitting || languageSync || !length || invalid;
  cancelEditButton.disabled = languageSync || submitting;
  updateEditNote();
  return length > 0 && !invalid;
}

function syncEditor() {
  const standalone = inputMode && !editingSource;
  input.hidden = !inputMode;
  input.classList.toggle("is-inline", editingSource);
  source.hidden = inputMode;
  result.hidden = standalone;
  retryButton.hidden = inputMode;
  copyButton.hidden = standalone;
  submitButton.hidden = !inputMode;
  cancelEditButton.hidden = !editingSource;
  document.getElementById('shot-image').hidden = standalone || !(lastState && lastState.image);
  document.getElementById("swap").disabled = inputMode || !lastState || !lastState.result ||
    lastState.status === "正在翻译" || lastState.status === "正在识别";
  validateInput();
  sizeInput();
}

function editSource(offset) {
  if (inputMode || !source.dataset.editable) return;
  editSnapshot = {text: source.dataset.raw || "", source: sourceCode, target: targetCode};
  editingSource = inputMode = true;
  input.value = editSnapshot.text;
  setSubmitState("ready");
  syncEditor();
  input.focus({ preventScroll: true });
  const caret = Number.isInteger(offset) ? Math.min(offset, input.value.length) : input.value.length;
  input.setSelectionRange(caret, caret);
  keepEditorVisible();
}

function cancelSourceEdit() {
  if (!editingSource || languageSync || submitting) return;
  const changedLanguages = sourceCode !== editSnapshot.source || targetCode !== editSnapshot.target;
  editingSource = inputMode = false;
  editSnapshot = null;
  setSubmitState("ready");
  syncEditor();
  source.focus({ preventScroll: true });
  if (changedLanguages) api("retry_after_edit", appliedSeq);
}

function setSubmitState(state) {
  const label = state === "busy" ? "提交中…" : state === "failed" ? "重试翻译" : "翻译";
  submitButton.classList.toggle("is-busy", state === "busy");
  submitButton.classList.toggle("is-failed", state === "failed");
  submitButton.setAttribute("aria-label", label);
  submitButton.setAttribute("aria-busy", String(state === "busy"));
  submitButton.dataset.tooltip = state === "busy" ? label : label + "（Ctrl+Enter）";
}

async function submitInput() {
  if (submitting || languageSync || !validateInput()) return;
  const seq = appliedSeq;
  submitting = true;
  setSubmitState("busy");
  validateInput();
  let failed = false;
  try {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge || typeof bridge.submit_text !== "function") throw new Error("bridge unavailable");
    if (await api("submit_text", input.value, seq) === false) throw new Error("submission not started");
  } catch (error) {
    failed = true;
  } finally {
    if (seq === appliedSeq && inputMode) {
      submitting = false;
      setSubmitState(failed ? "failed" : "ready");
      announcement.textContent = failed ? "提交失败，请重试" : "";
      validateInput();
    }
  }
}

function closeLanguages() {
  menu.hidden = true;
  if (menuAnchor) menuAnchor.setAttribute("aria-expanded", "false");
  menuAnchor = null;
}

function showLanguageCodes() {
  for (const [id, code, label] of [["from", sourceCode, "原文"], ["to", targetCode, "译文"]]) {
    const button = document.getElementById(id), name = languages[code] || code;
    button.textContent = name;
    button.setAttribute("aria-label", label + "语言：" + name);
  }
}

function chooseLanguage(kind, anchor) {
  if (languageSync || submitting) return;
  if (!menu.hidden && menuAnchor === anchor) { closeLanguages(); return; }
  closeLanguages();
  menuAnchor = anchor;
  anchor.setAttribute("aria-expanded", "true");
  menu.setAttribute("aria-label", kind === "reverse" ? "指定原文语言以对调" : kind === "source" ? "原文语言" : "译文语言");
  menu.replaceChildren();
  Object.entries(languages).forEach(([code, label]) => {
    if (code === "auto" && kind !== "source") return;
    const item = document.createElement("button");
    item.type = "button";
    item.className = "language-option";
    item.tabIndex = -1;
    const mark = document.createElement("span");
    mark.className = "menu-mark";
    if (code === (kind === "target" ? targetCode : sourceCode)) {
      mark.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.6 8.2 6.4 11 12.4 4.8"/></svg>';
    }
    item.append(mark, document.createTextNode(label));
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", code === (kind === "target" ? targetCode : sourceCode) ? "true" : "false");
    item.addEventListener("click", function () {
      closeLanguages();
      if (kind === "reverse") api("swap", code);
      else if (code !== (kind === "source" ? sourceCode : targetCode)) {
        const next = { source: kind === "source" ? code : sourceCode, target: kind === "target" ? code : targetCode };
        if (editingSource) {
          const previous = {source: sourceCode, target: targetCode};
          const snapshot = editSnapshot;
          sourceCode = next.source; targetCode = next.target;
          showLanguageCodes();
          languageSync = true;
          validateInput();
          const failed = () => {
            if (!editingSource || editSnapshot !== snapshot) return;
            sourceCode = previous.source; targetCode = previous.target;
            showLanguageCodes();
            announcement.textContent = "语言设置失败，请重试";
          };
          try {
            const pending = api("set_languages", {...next, editing: true, editSeq: appliedSeq});
            if (!pending) throw new Error("bridge unavailable");
            Promise.resolve(pending).then(ok => { if (ok === false) throw new Error("stale edit"); })
              .catch(failed).finally(() => { languageSync = false; validateInput(); });
          } catch (_) {
            failed();
            languageSync = false;
            validateInput();
          }
        } else api("set_languages", next);
      }
      anchor.focus({ preventScroll: true });
    });
    item.addEventListener("keydown", function (event) {
      const items = Array.from(menu.children);
      const index = items.indexOf(item);
      let next;
      if (event.key === "ArrowDown") next = items[(index + 1) % items.length];
      if (event.key === "ArrowUp") next = items[(index + items.length - 1) % items.length];
      if (event.key === "Home") next = items[0];
      if (event.key === "End") next = items[items.length - 1];
      if (next) { event.preventDefault(); next.focus({ preventScroll: true }); next.scrollIntoView({ block: "nearest" }); }
      if (event.key === "Tab") {
        event.preventDefault();
        closeLanguages();
        window.intextControls.moveFocus(anchor, event.shiftKey);
      }
    });
    menu.append(item);
  });
  const rect = anchor.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(rect.left, innerWidth - 150)) + "px";
  menu.style.top = (rect.bottom + 5) + "px";
  menu.style.maxHeight = Math.max(40, innerHeight - rect.bottom - 13) + "px";
  menu.hidden = false;
  const selected = menu.querySelector('[aria-selected="true"]') || menu.firstElementChild;
  selected.focus({ preventScroll: true });
  selected.scrollIntoView({ block: "nearest" });
}

function resetCopy() {
  clearTimeout(copyTimer);
  copyButton.classList.remove("is-copied", "is-copy-failed");
  copyButton.setAttribute("aria-label", "复制");
  copyButton.dataset.tooltip = "复制";
}

function copyFeedback(success) {
  resetCopy();
  copyButton.classList.add(success ? "is-copied" : "is-copy-failed");
  const message = success ? "已复制" : "复制失败，请重试";
  copyButton.setAttribute("aria-label", message);
  copyButton.dataset.tooltip = message;
  announcement.textContent = message;
  copyTimer = setTimeout(resetCopy, success ? 1400 : 2500);
}

function syncPin() {
  pinButton.setAttribute("aria-pressed", pinned ? "true" : "false");
  pinButton.setAttribute("aria-label", pinned ? "取消固定" : "固定");
  pinButton.dataset.tooltip = pinned ? "取消固定" : "固定";
}

window.intext = {
  apply(state) {
    const changed = state.seq !== appliedSeq || source.dataset.raw !== (state.source || "");
    const sameSequence = typeof state.seq !== "number" || state.seq === appliedSeq;
    if (typeof state.seq === "number") {
      if (state.seq < appliedSeq) return;
      appliedSeq = state.seq;
    }
    resetCopy();
    closeLanguages();
    sourceCode = state.sourceLang || "auto";
    targetCode = state.resultLang || "zh";
    const wasInput = inputMode;
    const wasStandalone = inputMode && !editingSource;
    editingSource = editingSource && state.mode !== "input" && (sameSequence || state.mode === "edit");
    inputMode = state.mode === "input" || editingSource;
    lastState = state;
    if (!(submitting && sameSequence && inputMode)) {
      submitting = false;
      setSubmitState("ready");
    }
    if (inputMode && !editingSource) {
      if (Object.hasOwn(state, "draft")) standaloneDraft = String(state.draft || "");
      if (!wasStandalone || state.enter || Object.hasOwn(state, "draft")) input.value = standaloneDraft;
    }
    document.getElementById("from").textContent = state.from || "";
    document.getElementById("to").textContent = state.to || "";
    document.getElementById("from").setAttribute("aria-label", "原文语言：" + (state.from || "自动"));
    document.getElementById("to").setAttribute("aria-label", "译文语言：" + (state.to || ""));
    window.intextMarkdown.render(source, state.source || "");
    const canEditSource = !!state.source && !(state.shot && state.image && state.source === "图片直译");
    if (canEditSource) {
      source.dataset.editable = "true";
      source.dataset.tooltip = "点击编辑原文";
      source.tabIndex = 0;
      source.setAttribute("role", "button");
      source.setAttribute("aria-description", "按 Enter 编辑原文");
    } else {
      delete source.dataset.editable; delete source.dataset.tooltip;
      source.removeAttribute("tabindex"); source.removeAttribute("role"); source.removeAttribute("aria-description");
    }
    const shotImage = document.getElementById('shot-image');
    if (state.image && String(state.image).startsWith('data:image/png;base64,')) {
      if (shotImage.getAttribute('src') !== state.image) shotImage.src = state.image;
    }
    else shotImage.removeAttribute('src');
    source.lang = state.sourceLang || "";
    const modelButton = document.getElementById("model");
    modelButton.textContent = state.model || "设置模型";
    modelButton.dataset.tooltip = state.model || "请求设置";
    result.lang = state.resultLang || "";
    const busy = state.status === "正在翻译" || state.status === "正在识别";
    const normal = !state.status || state.status === "输入翻译";
    const failure = !normal && !busy;
    panel.dataset.resultState = state.result ? "content" : busy ? "progress" : failure ? "error" : "empty";
    const message = String(state.status || "").replace(/\s+/g, " ").trim();
    // Cache hits are implementation details. Surface only progress and
    // failures, and keep the full error behind the help control.
    tip.textContent = failure ? message : "";
    help.hidden = !failure;
    announcement.textContent = normal ? "" : message;
    panel.setAttribute("aria-busy", busy ? "true" : "false");
    retryButton.classList.toggle("is-busy", busy);
    document.getElementById("retry").disabled = busy || (!state.source && !state.shot);
    document.getElementById("copy").disabled = !state.result;
    const displayResult = state.result || (busy ? message + "…" : failure ? (message.length <= 12 ? message : "请求失败") : "");
    if (result.dataset.raw !== displayResult) {
      window.intextMarkdown.render(result, displayResult);
      result.classList.remove("is-settle");
      void result.offsetWidth;
      result.classList.add("is-settle");
    }
    if (state.enter) {
      panel.classList.remove("is-in");
      void panel.offsetWidth;
      panel.classList.add("is-in");
    }
    pinned = !!state.pinned;
    syncPin();
    syncEditor();
    if (editingSource && document.activeElement === input) keepEditorVisible();
    if (inputMode && !editingSource && (!wasInput || state.enter)) input.focus({ preventScroll: true });
    if (changed && !editingSource) content.scrollTop = 0;
  }
};

function api(name, ...args) {
  const bridge = window.pywebview && window.pywebview.api;
  if (bridge && typeof bridge[name] === "function") {
    return bridge[name](...args);
  }
}
panel.addEventListener("click", function (event) {
  const button = event.target.closest(".iconbtn, .swap, .lang");
  if (!button || button.disabled) return;
  // Keep fast mouse and keyboard activations visible after release.
  clearTimeout(button.feedbackTimer);
  button.classList.add("is-clicked");
  button.feedbackTimer = setTimeout(function () { button.classList.remove("is-clicked"); }, 180);
});
document.getElementById("retry").addEventListener("click", function () { api("retry"); });
document.getElementById("dismiss").addEventListener("click", function () { api("hide"); });
document.getElementById("model").addEventListener("click", function () { api("open_settings"); });
document.getElementById("copy").addEventListener("click", async function () {
  if (!result.textContent.trim()) return;
  const seq = appliedSeq;
  try {
    const copied = await api("copy_text", result.dataset.raw || result.textContent);
    if (seq === appliedSeq) copyFeedback(!!copied);
  } catch (error) { if (seq === appliedSeq) copyFeedback(false); }
});
document.getElementById("pin").addEventListener("click", function () {
  pinned = !pinned;
  syncPin();
  api("set_pinned", pinned);
});
document.getElementById("swap").addEventListener("click", function () {
  if (sourceCode === "auto") chooseLanguage("reverse", this);
  else api("swap");
});
["from", "to"].forEach(function (id) {
  document.getElementById(id).addEventListener("click", function () { chooseLanguage(id === "from" ? "source" : "target", this); });
});
source.addEventListener("pointerdown", function (event) {
  if (event.button === 0) sourcePointer = {id: event.pointerId, x: event.clientX, y: event.clientY, moved: false};
});
document.addEventListener("pointermove", function (event) {
  if (sourcePointer && event.pointerId === sourcePointer.id &&
      Math.hypot(event.clientX - sourcePointer.x, event.clientY - sourcePointer.y) > 4) sourcePointer.moved = true;
}, {passive: true});
document.addEventListener("pointercancel", function (event) {
  if (sourcePointer && event.pointerId === sourcePointer.id) sourcePointer = null;
});
source.addEventListener("click", function (event) {
  if (event.button !== 0 || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
  const gesture = sourcePointer; sourcePointer = null;
  if (gesture && gesture.moved) return;
  const selection = window.getSelection();
  if (!gesture && selection && !selection.isCollapsed && selection.toString()) return;
  let offset;
  const caret = document.caretRangeFromPoint && document.caretRangeFromPoint(event.clientX, event.clientY);
  if (caret && source.contains(caret.startContainer)) {
    const range = document.createRange();
    range.selectNodeContents(source); range.setEnd(caret.startContainer, caret.startOffset);
    const before = range.toString();
    if ((source.dataset.raw || "").startsWith(before)) offset = before.length;
  }
  editSource(offset);
});
source.addEventListener("keydown", function (event) {
  if (event.target !== source || event.isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" || event.key === "F2") { event.preventDefault(); editSource(); }
});
input.addEventListener("input", function () {
  if (inputMode && !editingSource) standaloneDraft = input.value;
  validateInput(); sizeInput(); keepEditorVisible();
});
document.getElementById("submit").addEventListener("click", submitInput);
cancelEditButton.addEventListener("click", cancelSourceEdit);
input.addEventListener("keydown", function (event) {
  if (event.key === "Enter" && event.ctrlKey && !event.isComposing && event.keyCode !== 229 && validateInput()) {
    event.preventDefault(); submitInput();
  }
});
document.addEventListener("keydown", function (event) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Escape" && !menu.hidden) {
    const anchor = menuAnchor;
    closeLanguages();
    if (anchor) anchor.focus({ preventScroll: true });
    event.preventDefault(); return;
  }
  if (event.key === "Escape" && editingSource) { event.preventDefault(); cancelSourceEdit(); return; }
  if (event.key === "Escape") api("hide");
});
document.addEventListener("pointerdown", function (event) {
  if (menu.hidden || menu.contains(event.target) || (menuAnchor && menuAnchor.contains(event.target))) return;
  const thumb = event.target.closest?.(".mac-thumb");
  if (thumb && thumb._intextScroller === menu) return;
  closeLanguages();
}, true);
document.addEventListener("focusin", function (event) {
  if (!menu.hidden && !menu.contains(event.target) && event.target !== menuAnchor) closeLanguages();
});
window.addEventListener("blur", closeLanguages);
window.addEventListener("resize", closeLanguages);
document.addEventListener("pointerdown", function (event) {
  if (event.button !== 0) return;
  if (event.target.closest("#languages, .mac-thumb")) return;
  if (pinned || event.target.closest("#panel")) return;
  api("hide");
});
if (window.intextScroll) window.intextScroll.mount(content, { inset: 0, size: 4, endInset: 22, fade: true });
if (window.intextScroll) window.intextScroll.mount(input, { inset: 0, size: 4, endInset: 4, fade: true });
if (window.intextScroll) window.intextScroll.mount(menu, { inset: 3, size: 3, endInset: 8, layer: 70 });
