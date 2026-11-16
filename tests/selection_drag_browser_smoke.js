async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  const check = (ok, name) => { if (!ok) throw new Error(name); report[name] = true; };
  await page.setViewportSize({width: 640, height: 440});
  await page.emulateMedia({reducedMotion: 'reduce'});

  for (const file of ['popup.html', 'shot-overlay.html']) {
    await page.goto(base + file);
    await page.evaluate(file => {
      window.calls = [];
      window.pywebview = {api: new Proxy({}, {get: (_, key) => (...args) => {
        calls.push([key, ...args]); return Promise.resolve(true);
      }})};
      if (file === 'popup.html') {
        intext.apply({seq: 1, source: 'Original words', result: '**Translated** selection\n\nSecond paragraph', model: 'fixture'});
      } else {
        const c = document.createElement('canvas'); c.width = 360; c.height = 120;
        window.shotState = {seq: 1, width: 360, height: 120, image: c.toDataURL(), text: 'Overlay selection\nSecond region',
          blocks: [{text: 'Overlay selection', left: 5, top: 10, width: 90, height: 35, fontSize: 22, background: 'white', color: 'black'},
            {text: 'Second region', left: 5, top: 55, width: 90, height: 35, fontSize: 22, background: 'white', color: 'black'}]};
        intextShot.apply(shotState);
      }
    }, file);
    const selector = file === 'popup.html' ? '#result' : '.region';
    // An actual mouse gesture must select text without initiating a window move.
    await page.locator(selector).first().dblclick({position: {x: 18, y: 10}});
    check(await page.evaluate(() => getSelection().toString().length > 0 && !calls.some(c => c[0] === 'begin_drag')), file + ' mouse selection');
    const selected = await page.evaluate(() => getSelection().toString());
    await page.keyboard.press('Control+c');
    check(await page.evaluate(text => calls.filter(c => c[0] === 'copy_text').at(-1)?.[1] === text, selected), file + ' partial shortcut');

    const selectionChecks = await page.evaluate(async selector => {
      function select(start, end) {
        const walker = document.createTreeWalker(document.querySelector(selector), NodeFilter.SHOW_TEXT);
        const text = walker.nextNode(), range = document.createRange(); range.setStart(text, start); range.setEnd(text, end);
        getSelection().removeAllRanges(); getSelection().addRange(range);
        return getSelection().toString();
      }
      function key(options = {}) {
        const event = new KeyboardEvent('keydown', {key: 'c', ctrlKey: true, bubbles: true, cancelable: true, ...options});
        document.body.dispatchEvent(event); return event.defaultPrevented;
      }
      calls.length = 0;
      const first = select(1, 4), handled = key();
      await Promise.resolve();
      const exact = handled && calls.length === 1 && calls[0][1] === first && getSelection().toString() === first;
      const second = select(0, 2); key({key: 'Insert'}); await Promise.resolve();
      const fresh = calls.at(-1)[1] === second && calls.length === 2;
      key({key: 'с', code: 'KeyC'}); await Promise.resolve();
      const keyboardLayout = calls.at(-1)[1] === second && calls.length === 3;
      const regions = document.querySelectorAll(selector === '#result' ? '#result p' : '.region');
      const range = document.createRange(); range.setStart(regions[0].firstChild, 0); range.setEnd(regions[1].firstChild, 3);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      const across = getSelection().toString(); key(); await Promise.resolve();
      const multipleNodes = calls.at(-1)[1] === across;
      select(0, 2);
      const count = calls.length;
      const ignored = [{shiftKey: true}, {altKey: true}, {isComposing: true}, {keyCode: 229}, {ctrlKey: false}]
        .every(options => !key(options)) && calls.length === count;
      getSelection().removeAllRanges();
      const empty = !key() && calls.length === count;
      select(0, 2);
      window.pywebview.api = {copy_text: () => Promise.resolve(false)};
      key(); await Promise.resolve();
      const failed = document.getElementById('announcement').textContent === '复制失败，请重试' && getSelection().toString() === second;
      window.pywebview.api.copy_text = () => Promise.reject(new Error('clipboard busy'));
      key(); await Promise.resolve();
      const rejected = getSelection().toString() === second;
      delete window.pywebview;
      const nativeFallback = !key();
      window.pywebview = {api: {copy_text: text => { calls.push(['copy_text', text]); return Promise.resolve(true); },
        begin_drag: () => calls.push(['begin_drag'])}};
      return {exact, fresh, keyboardLayout, multipleNodes, ignored, empty, failed, rejected, nativeFallback};
    }, selector);
    Object.entries(selectionChecks).forEach(([name, ok]) => check(ok, file + ' selection ' + name));

    const routing = await page.evaluate(file => {
      const results = {};
      function down(selector, button = 0) {
        calls.length = 0;
        const event = new MouseEvent('mousedown', {button, bubbles: true, cancelable: true});
        document.querySelector(selector).dispatchEvent(event);
        return calls.filter(c => c[0] === 'begin_drag').length;
      }
      const draggable = file === 'popup.html' ? ['#panel', '.row', '.foot'] : ['#panel', '.head', '.foot', '#viewport'];
      const protectedAreas = file === 'popup.html' ? ['#result strong', '#source', '.content', '#copy svg', '#model', '#dismiss'] :
        ['#image', '#labels', '.region', '#copy svg', '#model', '#close', '.resize-n'];
      results.panel = draggable.every(selector => down(selector) === 1);
      results.content = protectedAreas.every(selector => down(selector) === 0);
      results.otherButtons = [1, 2].every(button => down('#panel', button) === 0);
      results.transparentMargin = down('.stage') === 0;
      const text = document.createElement('span'); text.style.userSelect = 'text'; text.id = 'future-text'; text.textContent = 'selectable';
      document.getElementById('panel').append(text);
      results.futureSelectable = down('#future-text') === 0; text.remove();
      if (file === 'shot-overlay.html') {
        for (const state of [{busy: true, status: '正在翻译…'}, {error: 'fixture failure'}]) {
          intextShot.apply({...shotState, ...state, blocks: []});
          // Test actual hit targets including the status text, rather than
          // dispatching directly to a container underneath a blocking layer.
          const box = document.getElementById('viewport').getBoundingClientRect();
          const points = [[box.x + 5, box.y + 5], [box.x + box.width / 2, box.y + box.height / 2], [box.right - 5, box.bottom - 5]];
          results[state.busy ? 'loadingPanel' : 'errorPanel'] = document.getElementById('image-frame').hidden && points.every(([x, y]) => {
            calls.length = 0;
            document.elementFromPoint(x, y).dispatchEvent(new MouseEvent('mousedown', {button: 0, bubbles: true, cancelable: true}));
            return calls.filter(c => c[0] === 'begin_drag').length === 1;
          });
        }
        intextShot.apply({...shotState, seq: 2});
        const image = document.getElementById('image-frame').getBoundingClientRect();
        const viewport = document.getElementById('viewport').getBoundingClientRect();
        calls.length = 0;
        document.elementFromPoint(viewport.x + 2, (image.top + image.bottom) / 2)
          .dispatchEvent(new MouseEvent('mousedown', {button: 0, bubbles: true, cancelable: true}));
        results.letterbox = calls.filter(c => c[0] === 'begin_drag').length === 1;
      }
      return results;
    }, file);
    Object.entries(routing).forEach(([name, ok]) => check(ok, file + ' drag ' + name));
  }

  await page.goto(base + 'popup.html');
  const editing = await page.evaluate(() => {
    intext.apply({seq: 1, mode: 'input', enter: true});
    const input = document.getElementById('input'); input.value = 'Editable draft'; input.setSelectionRange(0, 8);
    let calls = 0; window.pywebview = {api: {copy_text: () => { calls++; }}};
    const key = new KeyboardEvent('keydown', {key: 'c', ctrlKey: true, bubbles: true, cancelable: true});
    input.dispatchEvent(key);
    return !key.defaultPrevented && calls === 0 && input.selectionStart === 0 && input.selectionEnd === 8;
  });
  check(editing, 'editable input retains native copying');

  await page.goto(base + 'settings.html');
  const settings = await page.evaluate(() => {
    let calls = 0; window.pywebview = {api: {begin_drag: () => { calls++; }}};
    const down = selector => { const before = calls; document.querySelector(selector).dispatchEvent(new MouseEvent('mousedown', {button: 0, bubbles: true, cancelable: true})); return calls - before; };
    return down('#sheet') === 1 && ['#endpoint', '#live code', '#hotkey-select', '#target', '.resize-n'].every(selector => down(selector) === 0);
  });
  check(settings, 'settings shared drag preserves controls and code');
  return report;
}
