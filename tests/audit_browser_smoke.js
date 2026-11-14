async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const check = (value, name) => { if (!value) throw new Error(name); };
  await page.setViewportSize({width: 460, height: 312});
  await page.goto(base + 'popup.html');
  const languages = await page.evaluate(() => {
    const calls = [];
    window.pywebview = {api: {set_languages: p => calls.push(p)}};
    intext.apply({seq: 1, from: '英语', to: '简体中文', sourceLang: 'en', resultLang: 'zh', source: 'hello', result: '你好'});
    const select = (anchor, label) => {
      document.getElementById(anchor).click();
      [...document.querySelectorAll('.language-option')].find(el => el.textContent === label).click();
    };
    select('from', '英语');
    select('to', '简体中文');
    const unchanged = calls.length === 0;
    select('to', '日语');
    return unchanged && calls.length === 1 && calls[0].target === 'ja';
  });
  check(languages, 'Only changed languages request translation');

  await page.setViewportSize({width: 480, height: 600});
  await page.goto(base + 'settings.html');
  const initialization = await page.evaluate(async () => {
    const sent = [];
    window.pywebview = {api: {save: async p => { sent.push(p); return {}; }}};
    intextSettings.languages({source: 'en', target: 'ja'});
    await Promise.resolve();
    const savedBeforeInitialization = sent.length;
    intextSettings.apply({model: 'saved-model', apiKey: 'fixture-key', source: 'en', target: 'zh'});
    const pendingTarget = document.getElementById('target').value;
    intextSettings.languages({source: 'en', target: 'fr'});
    await Promise.resolve();
    return {savedBeforeInitialization, savedAfterIdleChange: sent.length, pendingTarget,
      model: document.getElementById('model').value, key: document.getElementById('api-key').value,
      target: document.getElementById('target').value};
  });
  check(initialization.savedBeforeInitialization === 0 && initialization.savedAfterIdleChange === 0 &&
        initialization.model === 'saved-model' && initialization.key === 'fixture-key' &&
        initialization.pendingTarget === 'ja' && initialization.target === 'fr',
        'Language updates cannot save uninitialized defaults or trigger an unnecessary idle save');

  await page.goto(base + 'settings.html');
  const debounced = await page.evaluate(async () => {
    const sent = [];
    window.pywebview = {api: {save: async p => { sent.push(p); return {}; }}};
    intextSettings.apply({model: 'old', source: 'en', target: 'zh'});
    const input = document.getElementById('model');
    input.value = 'edited';
    input.dispatchEvent(new Event('input', {bubbles: true}));
    intextSettings.languages({source: 'en', target: 'ja'});
    await new Promise(resolve => setTimeout(resolve, 220));
    return sent;
  });
  check(debounced.length === 1 && debounced[0].target === 'ja' && debounced[0].model === 'edited',
        'Pending debounced edit and language change save together');

  await page.goto(base + 'settings.html');
  const saves = await page.evaluate(async () => {
    const sent = [];
    let finish;
    window.pywebview = {api: {save: p => {
      sent.push(p);
      return sent.length === 1 ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({});
    }}};
    intextSettings.apply({model: 'old', source: 'en', target: 'zh'});
    const input = document.getElementById('model');
    input.value = 'edited';
    input.dispatchEvent(new Event('change', {bubbles: true}));
    await Promise.resolve();
    intextSettings.languages({source: 'en', target: 'ja'});
    finish({});
    await new Promise(resolve => setTimeout(resolve, 20));
    return {count: sent.length, final: sent.at(-1), displayed: input.value};
  });
  check(saves.count === 2 && saves.final.target === 'ja' && saves.final.model === 'edited' && saves.displayed === 'edited',
        'Queued autosave preserves popup language change and edited model');

  await page.setViewportSize({width: 1000, height: 750});
  await page.goto(base + 'shot-overlay.html');
  const initial = await page.evaluate(() => {
    const blocks = Array.from({length: 200}, (_, i) => ({text: '区域 ' + i + ' 的测试译文，包含较长的句子。',
      left: i % 10 * 10, top: Math.floor(i / 10) * 5, width: 9, height: 4,
      fontSize: 26, background: 'white', color: 'black'}));
    const png = document.createElement('canvas').toDataURL('image/png');
    const start = performance.now();
    intextShot.apply({seq: 1, width: 1600, height: 1000, image: png, blocks, text: 'translated'});
    const elapsed = performance.now() - start;
    const before = [...document.querySelectorAll('.region')].map(el => el.style.fontSize);
    const width = document.getElementById('canvas').clientWidth;
    document.getElementById('original').click();
    return {elapsed, before, width};
  });
  await page.setViewportSize({width: 1200, height: 900});
  // Explicitly exercise the same resize callback in a hidden automation tab.
  await page.evaluate(() => fit());
  const compared = await page.evaluate(() => {
    const during = [...document.querySelectorAll('.region')].map(el => el.style.fontSize);
    const originalWidth = document.getElementById('canvas').clientWidth;
    document.getElementById('original').click();
    const after = [...document.querySelectorAll('.region')].map(el => parseFloat(el.style.fontSize));
    const canvas = document.getElementById('canvas');
    return {during, after, originalWidth, width: canvas.clientWidth, height: canvas.clientHeight,
      viewportWidth: document.getElementById('viewport').clientWidth, viewportHeight: document.getElementById('viewport').clientHeight};
  });
  check(JSON.stringify(initial.before) === JSON.stringify(compared.during), 'Hidden translation keeps its font sizes');
  check(compared.originalWidth > initial.width && compared.originalWidth === compared.width,
        'Original image follows viewport changes during comparison');
  check(compared.width <= compared.viewportWidth && compared.height <= compared.viewportHeight && compared.after.some(size => size > 7),
        'Returning from original comparison fits resized viewport');
  const busyOriginal = await page.evaluate(() => {
    const png = document.createElement('canvas').toDataURL('image/png');
    intextShot.apply({seq: 2, width: 3000, height: 1000, image: png, blocks: [], busy: true});
    document.getElementById('original').click();
    const canvas = document.getElementById('canvas'), viewport = document.getElementById('viewport');
    const scale = Math.min(1, viewport.clientWidth / 3000, viewport.clientHeight / 1000);
    return Math.abs(canvas.clientWidth - 3000 * scale) < 1 && Math.abs(canvas.clientHeight - 1000 * scale) < 1;
  });
  check(busyOriginal, 'Original image fits while translation is still in progress');
  return {languages: true, initialization: true, debouncedSave: true, queuedSave: true,
    comparisonResize: true, busyOriginal: true, regions: 200, layoutMs: initial.elapsed};
}
