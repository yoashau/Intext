async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  const check = (value, name) => {
    if (!value) throw new Error(name);
    report[name] = true;
  };
  await page.emulateMedia({colorScheme: 'light', reducedMotion: 'reduce'});
  await page.setViewportSize({width: 460, height: 312});
  await page.goto(base + 'popup.html');
  await page.bringToFront();
  const copy = await page.evaluate(async () => {
    const button = document.getElementById('copy');
    const state = {seq: 1, from: '英语', to: '简体中文', sourceLang: 'en', resultLang: 'zh', source: 'hello', result: '你好', model: 'fixture'};
    intext.apply(state);
    window.pywebview = {api: {copy_text: async () => false}};
    button.click();
    await Promise.resolve();
    const failure = button.getAttribute('aria-label') === '复制失败，请重试' && document.getElementById('result').textContent === '你好';
    window.pywebview.api.copy_text = async () => { throw new Error('clipboard unavailable'); };
    button.click();
    await Promise.resolve();
    const rejected = button.getAttribute('aria-label') === '复制失败，请重试';
    let resolveCopy;
    window.pywebview.api.copy_text = () => new Promise(resolve => { resolveCopy = resolve; });
    button.click();
    intext.apply({...state, seq: 2, result: '新译文'});
    resolveCopy(true);
    await Promise.resolve();
    const stale = !button.classList.contains('is-copied');
    window.pywebview.api.copy_text = async () => true;
    button.click();
    await Promise.resolve();
    return {failure, rejected, stale, success: button.getAttribute('aria-label') === '已复制'};
  });
  Object.entries(copy).forEach(([key, value]) => check(value, 'copy ' + key));
  const submission = await page.evaluate(async () => {
    const input = document.getElementById('input'), button = document.getElementById('submit');
    intext.apply({seq: 3, mode: 'input', from: '英语', to: '简体中文', status: '输入翻译'});
    input.value = 'draft to keep';
    input.dispatchEvent(new Event('input', {bubbles: true}));
    let calls = 0, rejectSubmit;
    window.pywebview = {api: {submit_text: () => {
      calls++;
      return new Promise((_, reject) => { rejectSubmit = reject; });
    }}};
    button.click(); button.click();
    input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true}));
    input.dispatchEvent(new Event('input', {bubbles: true}));
    const pending = calls === 1 && button.disabled && button.getAttribute('aria-label') === '提交中…' &&
      getComputedStyle(button.querySelector('.submit-wait')).display !== 'none';
    rejectSubmit(new Error('bridge unavailable'));
    await Promise.resolve();
    const recovered = !button.disabled && button.getAttribute('aria-label') === '重试翻译' &&
      getComputedStyle(button.querySelector('.submit-retry')).display !== 'none' && input.value === 'draft to keep';
    window.pywebview.api.submit_text = async () => { calls++; };
    button.click();
    await Promise.resolve();
    const retry = calls === 2 && button.getAttribute('aria-label') === '翻译' &&
      getComputedStyle(button.querySelector('.submit-icon')).display !== 'none';
    const shortcut = new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true});
    input.dispatchEvent(shortcut);
    await Promise.resolve();
    return {pending, recovered, retry, shortcut: shortcut.defaultPrevented && calls === 3};
  });
  Object.entries(submission).forEach(([key, value]) => check(value, 'submission ' + key));
  const size = await page.evaluate(() => {
    const button = document.getElementById('submit'), pin = document.getElementById('pin');
    return button.clientWidth === pin.clientWidth && button.clientHeight === pin.clientHeight &&
      getComputedStyle(button).backgroundColor === getComputedStyle(pin).backgroundColor &&
      button.getAttribute('aria-keyshortcuts') === 'Control+Enter';
  });
  check(size, 'submit icon matches toolbar size and surface and exposes shortcut');
  const optical = await page.evaluate(() => {
    const metrics = svg => {
      const paths = [...svg.querySelectorAll('path')].map(path => path.getBBox());
      const height = (Math.max(...paths.map(box => box.y + box.height)) - Math.min(...paths.map(box => box.y))) *
        svg.clientHeight / svg.viewBox.baseVal.height;
      const stroke = parseFloat(getComputedStyle(svg).strokeWidth) * svg.clientWidth / svg.viewBox.baseVal.width;
      return {height, stroke};
    };
    return [metrics(document.querySelector('#submit .submit-icon')), metrics(document.querySelector('#pin svg'))];
  });
  check(Math.abs(optical[0].height - optical[1].height) < 2 && Math.abs(optical[0].stroke - optical[1].stroke) < .2,
    'submit icon has a matching visual height and line weight');
  const sameMark = await page.evaluate(async () => {
    const source = new DOMParser().parseFromString(await (await fetch('/design/tray-icon.svg')).text(), 'image/svg+xml');
    const paths = node => [...node.querySelectorAll('path')].map(path => path.getAttribute('d').trim().replace(/\s+/g, ' '));
    return JSON.stringify(paths(document.querySelector('#submit .submit-icon'))) === JSON.stringify(paths(source));
  });
  check(sameMark, 'submit uses the application icon geometry');
  const surface = id => page.locator(id).evaluate(el => ({background: getComputedStyle(el).backgroundColor, color: getComputedStyle(el).color}));
  await page.locator('#submit').hover();
  const submitHover = await surface('#submit');
  await page.locator('#pin').hover();
  const pinHover = await surface('#pin');
  check(JSON.stringify(submitHover) === JSON.stringify(pinHover), 'submit hover matches toolbar');
  await page.locator('#submit').hover();
  await page.mouse.down();
  const submitPressed = await surface('#submit');
  await page.mouse.move(0, 0); await page.mouse.up();
  await page.locator('#pin').hover();
  await page.mouse.down();
  const pinPressed = await surface('#pin');
  await page.mouse.move(0, 0); await page.mouse.up();
  check(JSON.stringify(submitPressed) === JSON.stringify(pinPressed) && submitPressed.background !== submitHover.background,
    'submit press matches toolbar');
  await page.locator('#input').focus();
  await page.keyboard.press('Tab');
  const submitFocus = await surface('#submit');
  check(await page.locator('#submit').evaluate(el => el === document.activeElement), 'submit is keyboard reachable');
  check(await page.locator('#tooltip').isVisible() && await page.locator('#tooltip').textContent() === '翻译（Ctrl+Enter）',
    'submit explains its action on keyboard focus');
  await page.keyboard.press('Tab');
  check(JSON.stringify(submitFocus) === JSON.stringify(await surface('#pin')), 'submit keyboard focus matches toolbar');
  await page.locator('#input').fill('');
  check(await page.locator('#submit').isDisabled(), 'empty input cannot be submitted');
  await page.locator('#input').fill('draft to keep');
  await page.locator('#submit').hover();
  await page.waitForTimeout(350);
  check(await page.locator('#tooltip').isVisible() && await page.locator('#tooltip').textContent() === '翻译（Ctrl+Enter）', 'submit icon explains action on hover');
  await page.setViewportSize({width: 400, height: 380});
  await page.goto(base + 'settings.html');
  await page.bringToFront();
  const settings = await page.evaluate(() => {
    window.pywebview = {api: {save: async () => ({})}};
    intextSettings.apply({model: 'fixture', source: 'ja', target: 'en'});
    const source = document.getElementById('source-button'), target = document.getElementById('target-button');
    const named = source.getAttribute('aria-label') === '原文：日语' && target.getAttribute('aria-label') === '译文：英语';
    document.getElementById('sheet').scrollTop += source.getBoundingClientRect().top - 160;
    source.dispatchEvent(new KeyboardEvent('keydown', {key: 'End', bubbles: true, cancelable: true}));
    const menu = document.getElementById('menu-source');
    const item = document.activeElement.getBoundingClientRect(), bounds = menu.getBoundingClientRect();
    const visible = item.top >= bounds.top && item.bottom <= bounds.bottom;
    const menuName = menu.getAttribute('aria-label') === '原文';
    target.focus();
    // Explicit dispatch also supports a background browser tab without native focus events.
    target.dispatchEvent(new FocusEvent('focusin', {bubbles: true}));
    const closed = menu.hidden && source.getAttribute('aria-expanded') === 'false';
    const hotkey = document.getElementById('hotkey-select');
    hotkey.focus(); hotkey.click();
    const tab = new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true});
    hotkey.dispatchEvent(tab);
    const tabReleased = !tab.defaultPrevented && !hotkey.textContent.includes('请按键');
    const endpoint = document.getElementById('endpoint');
    endpoint.value = 'api.example.test/v1/chat/completions';
    endpoint.dispatchEvent(new Event('input', {bubbles: true}));
    const invalid = endpoint.getAttribute('aria-invalid') === 'true';
    endpoint.value = 'http://localhost:8080/v1/chat/completions';
    endpoint.dispatchEvent(new Event('input', {bubbles: true}));
    return {named, menuName, visible, closed, tabReleased, invalid, local: !endpoint.hasAttribute('aria-invalid')};
  });
  Object.entries(settings).forEach(([key, value]) => check(value, 'settings ' + key));
  const longHotkey = await page.evaluate(() => {
    intextSettings.apply({model: 'fixture', hotkey: 'ctrl+alt+shift+win+f12', hotkeyError: '已被占用'});
    const button = document.getElementById('hotkey-select');
    const a = button.getBoundingClientRect(), b = document.getElementById('hotkey-shot').getBoundingClientRect();
    const note = button.querySelector('.keycap-state');
    return {aligned: Math.abs(a.left-b.left)<1 && Math.abs(a.right-b.right)<1,
      fullReason: note.textContent==='已被占用' && note.scrollWidth<=note.clientWidth,
      completeTooltip: button.dataset.tooltip.includes('Ctrl + Alt + Shift + Win + F12')};
  });
  Object.entries(longHotkey).forEach(([key, value]) => check(value, 'long hotkey ' + key));
  await page.evaluate(() => intextSettings.apply({model: 'fixture', fields: {
    reasoning_effort: {enabled: true, value: 'custom-provider-depth'}
  }}));
  await page.locator('#field-reasoning_effort').scrollIntoViewIfNeeded();
  await page.waitForTimeout(50);
  await page.locator('#field-reasoning_effort').hover();
  await page.waitForTimeout(350);
  check(await page.locator('#tooltip').isVisible() && await page.locator('#tooltip').textContent() === 'custom-provider-depth', 'long field full-value help');
  await page.locator('#field-reasoning_effort').fill('custom-provider-depth-v2');
  check(await page.evaluate(() => intextSettings.body().reasoning_effort === 'custom-provider-depth-v2'), 'long field remains editable');
  return report;
}
