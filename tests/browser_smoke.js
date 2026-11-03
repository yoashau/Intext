// Run with a Playwright page while the project is served on localhost:8768.
async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const base = "http://127.0.0.1:8768/src/intext/assets/";
  await page.setViewportSize({ width: 460, height: 312 });
  await page.goto(base + "popup.html");
  const popup = await page.evaluate(async () => {
    window.calls = [];
    window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => {
      if (["hide", "retry", "open_settings"].includes(name) && args.length) throw new Error(name + " expects no arguments");
      calls.push([name, args[0]]); return Promise.resolve(true);
    } }) };
    intext.apply({ seq: 1, from: "英语", to: "简体中文", source: "Paragraph one.\n\nParagraph two.",
      result: "第一段。\n\n第二段。\n".repeat(30), model: "a-model-name-that-is-too-long-to-fit-in-the-footer".repeat(2), status: "未缓存", pinned: false });
    const content = document.querySelector("#content");
    content.scrollTop = 100;
    content.dispatchEvent(new Event("scroll"));
    const thumb = document.querySelector(".mac-thumb");
    thumb.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerId: 1 }));
    thumb.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, button: 0, pointerId: 1 }));
    const scrollbarDidNotHide = !calls.some(([name]) => name === "hide");
    document.querySelector(".row").dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    document.querySelector("#copy").click();
    await Promise.resolve();
    const copied = document.querySelector("#copy").classList.contains("is-copied") &&
      getComputedStyle(document.querySelector(".copy-check")).display !== "none";
    const clickFeedback = document.querySelector('#copy').classList.contains('is-clicked');
    const noCacheLabel = !document.querySelector("#status") && !document.querySelector("#announcement").textContent.includes("缓存");
    const footer = document.querySelector(".foot").getBoundingClientRect();
    const bounds = document.querySelector("#panel").getBoundingClientRect();
    const paragraphs = document.querySelector("#result").innerText.includes("\n\n");
    intext.apply({ seq: 2, from: "英语", to: "简体中文", source: "next", status: "正在翻译", pinned: true });
    const disabled = ["retry", "copy", "swap"].every(id => document.getElementById(id).disabled);
    const reset = content.scrollTop === 0;
    intext.apply({ seq: 1, source: "stale", result: "stale" });
    const fresh = document.querySelector("#source").textContent === "next";
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    document.querySelector("#dismiss").click();
    const closesWhilePinned = calls.filter(([name]) => name === "hide").length === 2;
    const busyFeedback = document.querySelector("#retry").classList.contains("is-busy") && document.querySelector("#result").textContent === "正在翻译…";
    return { scrollbarDidNotHide, paragraphs, copied, clickFeedback, noCacheLabel, disabled, reset, fresh, closesWhilePinned, busyFeedback,
      footerVisible: footer.bottom <= bounds.bottom && footer.top > bounds.top,
      noOverflow: document.body.scrollWidth === innerWidth,
      drags: calls.filter(([name]) => name === "begin_drag").length,
      hides: calls.filter(([name]) => name === "hide").length };
  });
  Object.entries(popup).forEach(([key, value]) => check(key === "drags" ? value === 1 : key === "hides" ? value === 2 : value, "Popup: " + key));

  const errorsAndPin = await page.evaluate(() => {
    intext.apply({seq: 2, from: "英语", to: "简体中文", source: "hello", status: "请求超时", pinned: false});
    const errorVisible = document.querySelector("#result").textContent === "请求超时" && !document.querySelector("#status-help").hidden;
    document.querySelector("#pin").click();
    const pin = document.querySelector("#pin");
    pin.classList.remove('is-clicked');
    const pinStyle = getComputedStyle(pin);
    const dot = document.querySelector('#dismiss');
    const noDecorations = getComputedStyle(dot, '::before').backgroundImage === 'none' &&
      ['none', 'normal', '""'].includes(getComputedStyle(dot, '::after').content) &&
      ['none', 'normal', '""'].includes(getComputedStyle(document.querySelector('#status-help'), '::before').content);
    intext.apply({seq:2, from:'自动', to:'简体中文', source:'hello', status:'未配置', pinned:true});
    document.querySelector('#model').click();
    const settingsEntry = document.querySelector('#model').textContent === '设置模型' && calls.some(([name])=>name==='open_settings');
    return {errorVisible, pinBorderless: pinStyle.backgroundColor === 'rgba(0, 0, 0, 0)', noDecorations, settingsEntry,
      pinSelected: pin.getAttribute("aria-pressed") === "true" && pin.getAttribute("aria-label") === "取消固定"};
  });
  Object.entries(errorsAndPin).forEach(([key, value]) => check(value, "Errors/pin: " + key));

  async function focusStyles() {
    await page.keyboard.press('Tab');
    return page.evaluate(() => {
      const styles = [];
      for (const el of document.querySelectorAll('button, input, textarea, select, [tabindex]')) {
        if (!el.getClientRects().length || el.disabled || el.closest('[hidden]') || el.classList.contains('native-select')) continue;
        el.focus({preventScroll: true});
        const css = getComputedStyle(el.closest(".combo") || el);
        if (el.classList.contains('window-dot')) {
          if (css.outlineStyle !== 'none') throw new Error('Window dot must not have a focus outline');
          continue;
        }
        if (el.matches(':focus-visible')) styles.push({id: el.id || el.className, color: css.outlineColor, width: css.outlineWidth, style: css.outlineStyle, offset: css.outlineOffset});
      }
      return styles;
    });
  }
  const popupFocus = await focusStyles();
  check(popupFocus.length > 5 && popupFocus.every(s => s.color === popupFocus[0].color && parseFloat(s.width) >= 1 && parseFloat(s.width) <= 1.5 && s.style === 'solid' && s.offset === '0px'), 'Popup: consistent focus');

  async function checkHelp() {
    await page.keyboard.press('Tab');
    const state = await page.evaluate(async () => {
      const button = document.querySelector('.help:not([hidden])');
      const tip = document.querySelector('#tooltip');
      button.scrollIntoView({block:'nearest'});
      button.focus({preventScroll:true});
      const keyboardOpens = getComputedStyle(tip).display === 'block';
      const press = new PointerEvent('pointerdown', {button:0,bubbles:true,cancelable:true});
      button.dispatchEvent(press);
      button.click();
      const mouseDoesNotLatch = press.defaultPrevented && document.activeElement !== button && getComputedStyle(tip).display === 'none';
      button.focus({preventScroll:true});
      document.body.dispatchEvent(new PointerEvent('pointerdown', {button:0,bubbles:true,cancelable:true}));
      const outsideCloses = document.activeElement !== button && getComputedStyle(tip).display === 'none';
      button.dispatchEvent(new PointerEvent('pointerover', {bubbles:true}));
      const glyph = button.querySelector('[aria-hidden="true"]');
      if (glyph) glyph.dispatchEvent(new PointerEvent('pointerover', {bubbles:true}));
      await new Promise(resolve => setTimeout(resolve, 320));
      const hoverOpens = !tip.hidden && tip.textContent === button.querySelector('.tip').textContent.trim();
      const signature = () => { const c=getComputedStyle(tip); return [c.backgroundColor,c.color,c.fontSize,c.padding,c.borderRadius,c.boxShadow].join('|'); };
      const helpStyle = signature();
      button.dispatchEvent(new PointerEvent('pointerout', {bubbles:true,relatedTarget:document.body}));
      const hoverLeavesClose = tip.hidden;
      const dot = document.querySelector('.window-dot');
      dot.dispatchEvent(new PointerEvent('pointerover', {bubbles:true}));
      await new Promise(resolve => setTimeout(resolve, 320));
      const dotUsesSameTooltip = !tip.hidden && tip.textContent === dot.dataset.tooltip && signature() === helpStyle;
      const bounds = tip.getBoundingClientRect();
      const staysInside = bounds.left >= 8 && bounds.top >= 8 && bounds.right <= innerWidth-7 && bounds.bottom <= innerHeight-7;
      dot.dispatchEvent(new PointerEvent('pointerout', {bubbles:true,relatedTarget:document.body}));
      const noNativeTitles = !document.querySelector('[title]');
      return {keyboardOpens, mouseDoesNotLatch, outsideCloses, hoverOpens, hoverLeavesClose, dotUsesSameTooltip, staysInside, noNativeTitles};
    });
    Object.entries(state).forEach(([key,value]) => check(value, 'Help: '+key));
    return state;
  }
  const popupHelp = await checkHelp();

  const longHelp = await page.evaluate(async () => {
    intext.apply({seq: 2, from: "英语", to: "简体中文", source: "hello", status: "请求失败：" + "详细的连接信息。".repeat(120)});
    const button = document.querySelector('#status-help');
    const tip = document.querySelector('#tooltip');
    button.focus({preventScroll: true});
    const canScroll = tip.classList.contains('is-scrollable') && tip.scrollHeight > tip.clientHeight;
    const press = new KeyboardEvent('keydown', {key:'PageDown',bubbles:true,cancelable:true});
    button.dispatchEvent(press);
    const keyboardScrolls = press.defaultPrevented && tip.scrollTop > 0 && !tip.hidden;
    button.dispatchEvent(new PointerEvent('pointerout', {bubbles:true,relatedTarget:tip}));
    tip.dispatchEvent(new PointerEvent('pointerenter'));
    await new Promise(resolve => setTimeout(resolve, 220));
    const canEnter = !tip.hidden;
    tip.scrollTop = tip.scrollHeight;
    tip.dispatchEvent(new Event('scroll'));
    const canReadEnd = !tip.hidden && tip.scrollTop + tip.clientHeight >= tip.scrollHeight - 1;
    tip.dispatchEvent(new PointerEvent('pointerleave', {relatedTarget:document.body}));
    return {canScroll, keyboardScrolls, canEnter, canReadEnd, leavesClose:tip.hidden};
  });
  Object.entries(longHelp).forEach(([key,value]) => check(value, 'Long help: '+key));

  const inputAndLanguages = await page.evaluate(() => {
    calls.length = 0;
    intext.apply({ seq: 3, mode: "input", draft: "", from: "自动", to: "简体中文", sourceLang: "", resultLang: "zh", status: "输入翻译" });
    const editor = document.querySelector("#input");
    editor.value = "First paragraph.\n\nSecond paragraph.";
    editor.dispatchEvent(new Event("input", { bubbles: true }));
    const submit = document.querySelector("#submit");
    const ready = !submit.disabled && !editor.hidden;
    editor.focus({preventScroll: true});
    const inputStyle = getComputedStyle(editor);
    const inputFocus = inputStyle.outlineStyle === 'solid' && parseFloat(inputStyle.outlineWidth) <= 1.5 &&
      parseFloat(inputStyle.outlineOffset) < 0 && parseFloat(inputStyle.outlineOffset) + parseFloat(inputStyle.outlineWidth) <= 0.01;
    const submitFits = submit.clientWidth >= submit.scrollWidth && getComputedStyle(submit).whiteSpace === "nowrap";
    document.querySelector("#to").click();
    const options = [...document.querySelectorAll(".language-option")];
    const menuFocus = options.every(el => { el.focus({preventScroll:true}); return getComputedStyle(el).outlineStyle === 'solid'; });
    const automaticTargetOmitted = !options.some(el => el.textContent === "自动");
    options.find(el => el.textContent === "日语").click();
    const targetSelected = calls.some(([name, payload]) => name === "set_languages" && payload.target === "ja");
    intext.apply({ seq: 3, mode: "input", from: "自动", to: "日语", resultLang: "ja", status: "输入翻译" });
    const draftPreserved = editor.value === "First paragraph.\n\nSecond paragraph.";
    editor.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, bubbles: true, cancelable: true }));
    const submitted = calls.some(([name, payload]) => name === "submit_text" && payload === editor.value);
    intext.apply({ seq: 4, from: "自动", to: "简体中文", resultLang: "zh", source: "こんにちは", result: "你好", status: "未缓存" });
    document.querySelector("#swap").click();
    const asksBeforeSwap = !document.querySelector("#languages").hidden && !calls.some(([name]) => name === "swap");
    [...document.querySelectorAll(".language-option")].find(el => el.textContent === "日语").click();
    const reverseSelected = calls.some(([name, code]) => name === "swap" && code === "ja");
    return { ready, menuFocus, inputFocus, submitFits, automaticTargetOmitted, targetSelected, draftPreserved, submitted, asksBeforeSwap, reverseSelected };
  });
  Object.entries(inputAndLanguages).forEach(([key, value]) => check(value, "Input/languages: " + key));

  await page.setViewportSize({ width: 480, height: 600 });
  await page.goto(base + "settings.html");
  const settings = await page.evaluate(async () => {
    window.saves = [];
    window.pywebview = { api: { save(payload) {
      saves.push(payload);
      return Promise.resolve({ hotkey: payload.hotkey, shotHotkey: payload.shotHotkey, hotkeyError: "", shotHotkeyError: "" });
    } } };
    const model = document.querySelector("#model");
    model.value = " m ";
    model.dispatchEvent(new Event("change", { bubbles: true }));
    const defaultsOmitted = !Object.hasOwn(intextSettings.body(), "temperature") && !Object.hasOwn(intextSettings.body(), "reasoning_effort");
    const source = document.querySelector("#source");
    const menu = source.parentElement.querySelector(".menu-btn");
    menu.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    document.activeElement.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    document.activeElement.click();
    const languageSelected = source.value === "zh" && menu.getAttribute("aria-expanded") === "false";
    const field = document.querySelector('[data-key="temperature"]');
    field.querySelector(".value").value = "not-a-number";
    field.querySelector(".switch").click();
    const invalidOmitted = !Object.hasOwn(intextSettings.body(), "temperature");
    const invalidMarked = field.classList.contains('is-invalid') && field.querySelector('.value').getAttribute('aria-invalid') === 'true';
    field.querySelector('.switch').click();
    const disablingClearsInvalid = !field.classList.contains('is-invalid') && !field.querySelector('.value').hasAttribute('aria-invalid');
    document.querySelector("#hotkey-select").click();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "e", code: "KeyE", ctrlKey: true, altKey: true, bubbles: true, cancelable: true }));
    const duplicateVisible = document.querySelector("#hotkey-select").getAttribute("aria-invalid") === "true";
    await Promise.resolve();
    return { defaultsOmitted, languageSelected, invalidOmitted, invalidMarked, disablingClearsInvalid, duplicateVisible,
      previewTrimmed: intextSettings.body().model === "m",
      noHiddenTabStops: [...document.querySelectorAll(".native-select")].every(el => el.tabIndex === -1),
      noOverflow: document.body.scrollWidth === innerWidth };
  });
  Object.entries(settings).forEach(([key, value]) => check(value, "Settings: " + key));
  const reasoning = await page.evaluate(async () => {
    intextSettings.apply({model: "custom-model", fields: {reasoning_effort: {enabled: true, value: "custom_effort"}}});
    const line = document.querySelector('[data-key="reasoning_effort"]');
    const input = line.querySelector(".value");
    const button = line.querySelector(".menu-btn");
    const restored = input.value === "custom_effort" && intextSettings.body().reasoning_effort === "custom_effort";
    input.value = "  xhigh  ";
    input.dispatchEvent(new Event("input", {bubbles: true}));
    await new Promise(resolve => setTimeout(resolve, 240));
    const customSaved = saves.at(-1).fields.reasoning_effort.value === "  xhigh  " && intextSettings.body().reasoning_effort === "xhigh";
    button.click();
    const pop = document.querySelector("#" + input.getAttribute("aria-controls"));
    const customNotMisrepresented = !pop.hidden && !pop.querySelector('[aria-selected="true"]');
    const rect = input.getBoundingClientRect();
    const arrow = button.getBoundingClientRect();
    const other = document.querySelector('[data-key="temperature"] .value').getBoundingClientRect();
    const aligned = arrow.left === rect.left && arrow.right < rect.right && rect.right === other.right && getComputedStyle(input).textAlign === "right";
    const menuFits = pop.getBoundingClientRect().width === rect.width && pop.getBoundingClientRect().top >= 8 && pop.getBoundingClientRect().bottom <= innerHeight - 7;
    input.dispatchEvent(new KeyboardEvent("keydown", {key:"ArrowDown",bubbles:true,cancelable:true}));
    const keyboardOpens = document.activeElement.textContent === "low";
    document.dispatchEvent(new KeyboardEvent("keydown", {key:"Escape",bubbles:true,cancelable:true}));
    const escapePreserves = pop.hidden && input.value === "  xhigh  " && input.getAttribute("aria-expanded") === "false";
    button.click();
    [...pop.querySelectorAll(".menu-opt")].find(el => el.textContent === "high").click();
    const presetSelected = input.value === "high" && intextSettings.body().reasoning_effort === "high" && pop.hidden && document.activeElement === input;
    input.value = " ";
    input.dispatchEvent(new Event("change", {bubbles:true}));
    const blankOmitted = input.getAttribute("aria-invalid") === "true" && !Object.hasOwn(intextSettings.body(),"reasoning_effort");
    line.querySelector(".switch").click();
    const disabledOmitted = !input.hasAttribute("aria-invalid") && !Object.hasOwn(intextSettings.body(),"reasoning_effort");
    return {restored,customSaved,customNotMisrepresented,aligned,menuFits,keyboardOpens,escapePreserves,presetSelected,blankOmitted,disabledOmitted};
  });
  Object.entries(reasoning).forEach(([key,value]) => check(value, "Reasoning: " + key));
  const settingsFocus = await focusStyles();
  check(settingsFocus.length > 15 && settingsFocus.every(s => s.color === popupFocus[0].color && parseFloat(s.width) >= 1 && parseFloat(s.width) <= 1.5 && s.style === 'solid' && s.offset === '0px'), 'Settings: consistent focus');
  const settingsHelp = await checkHelp();
  await page.setViewportSize({width:248,height:160});
  await page.goto(base + 'tray-menu.html');
  const trayMenu = await page.evaluate(async () => {
    const actions = [];
    window.pywebview = {api:{activate(action) {actions.push(action);return Promise.resolve({startup:true});},hide(){actions.push('hide');}}};
    intextTray.open({startup:false,openSide:"right"});
    const option = document.querySelector('[data-action="startup"]');
    const defaultOff = option.getAttribute('aria-checked') === 'false';
    option.click();
    await Promise.resolve(); await Promise.resolve();
    const toggled = option.getAttribute('aria-checked') === 'true' && actions.includes('startup');
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
    const keyboardMenu = document.activeElement.dataset.action === 'input';
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    const menu = document.querySelector('.menu').getBoundingClientRect();
    return {defaultOff,toggled,keyboardMenu,escCloses:actions.includes('hide'),
      exactActions:[...document.querySelectorAll('[data-action]')].map(el=>el.dataset.action).join(',')==='input,startup,quit',
      fits:menu.left>=0&&menu.top>=0&&menu.right<=innerWidth&&menu.bottom<=innerHeight};
  });
  Object.entries(trayMenu).forEach(([key,value]) => check(value, 'Tray menu: '+key));
  return { popup, errorsAndPin, inputAndLanguages, settings, reasoning, popupHelp, longHelp, settingsHelp, trayMenu, focusCounts: {popup:popupFocus.length, settings:settingsFocus.length}, focus:popupFocus[0] };
}
