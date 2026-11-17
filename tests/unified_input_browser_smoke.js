async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  const check = (ok, name) => { if (!ok) throw new Error(name); report[name] = true; };
  await page.emulateMedia({colorScheme: 'light', reducedMotion: 'reduce', forcedColors: 'none'});
  await page.setViewportSize({width: 460, height: 312});
  await page.goto(base + 'popup.html');
  await page.evaluate(() => {
    window.calls = [];
    window.pywebview = {api: {
      copy_text: text => { calls.push(['copy_text', text]); return Promise.resolve(true); },
      submit_text: text => { calls.push(['submit_text', text]); return Promise.resolve(true); },
      set_languages: value => { calls.push(['set_languages', value]); return Promise.resolve(true); },
      retry_after_edit: seq => { calls.push(['retry_after_edit', seq]); return Promise.resolve(true); },
      hide: () => { calls.push(['hide']); }, begin_drag: () => { calls.push(['begin_drag']); }
    }};
    window.resultState = {seq: 1, source: 'Original words to translate', result: '初始译文',
      from: '英语', to: '简体中文', sourceLang: 'en', resultLang: 'zh', status: '未缓存'};
    intext.apply(resultState);
  });
  const input = page.locator('#input'), source = page.locator('#source');
  check(await source.isVisible() && !await input.isVisible() && await page.locator('#result').isVisible() &&
    !await page.locator('#submit').isVisible(), 'ordinary selection keeps the existing result view');

  const box = await source.boundingBox();
  await page.mouse.move(box.x + 4, box.y + 9); await page.mouse.down();
  await page.mouse.move(box.x + 80, box.y + 9, {steps: 12}); await page.mouse.up();
  const selected = await page.evaluate(() => getSelection().toString());
  check(selected.length > 0 && !await input.isVisible(), 'drag selects source without opening the editor');
  await page.keyboard.press('Control+c');
  check(await page.evaluate(text => calls.some(c => c[0] === 'copy_text' && c[1] === text), selected), 'dragged source copies with Ctrl+C');
  await source.click({position: {x: 15, y: 9}});
  check(await input.isVisible(), 'a click can edit after copying a source selection');
  await page.keyboard.press('Escape');
  await source.dblclick({position: {x: 18, y: 9}});
  check(await input.isVisible() && await input.evaluate(el => el.selectionEnd > el.selectionStart),
    'double-click still selects a word in the editable source');
  await page.keyboard.press('Escape');
  await source.click({position: {x: 15, y: 9}});
  check(await input.isVisible() && await input.inputValue() === 'Original words to translate' &&
    await page.locator('#result').isVisible() && await page.locator('#result').textContent() === '初始译文' &&
    await page.locator('#submit').isVisible() && await page.locator('#cancel-edit').isVisible(), 'click edits source in place while retaining the result');
  check(!await page.locator('#edit-note').isVisible(), 'unchanged source has no stale-result note');
  await input.fill('Modified source');
  check(await page.locator('#edit-note').isVisible(), 'changed source marks the old translation as pending');
  await page.evaluate(() => intext.apply({...resultState, result: '刚返回的旧译文'}));
  check(await input.inputValue() === 'Modified source' && await page.locator('#result').textContent() === '刚返回的旧译文' &&
    await page.locator('#edit-note').isVisible(), 'late result updates do not overwrite the draft');

  await page.evaluate(() => {
    pywebview.api.set_languages = value => {
      calls.push(['set_languages', value]);
      if (!value.editing) return Promise.resolve(true);
      return new Promise(resolve => { window.finishLanguage = () => {
        intext.apply({...resultState, seq: 2, mode: 'edit', result: '刚返回的旧译文', to: '日语', resultLang: 'ja'});
        resolve(true);
      }; });
    };
  });
  await page.locator('#to').click();
  await page.locator('.language-option').filter({hasText: '日语'}).click();
  check(await page.locator('#submit').isDisabled(), 'submission waits for the chosen language to be saved');
  await input.fill('Edited while language saves');
  await page.keyboard.press('Control+Enter');
  check(await page.evaluate(() => !calls.some(c => c[0] === 'submit_text')), 'shortcut cannot submit with stale language settings');
  await page.evaluate(() => finishLanguage());
  await page.waitForFunction(() => !document.getElementById('submit').disabled);
  check(await input.inputValue() === 'Edited while language saves' && await page.locator('#to').textContent() === '日语',
    'language change preserves the live draft');
  await page.locator('#cancel-edit').click();
  check(!await input.isVisible() && await source.isVisible() && await page.evaluate(() =>
    calls.some(c => c[0] === 'retry_after_edit' && c[1] === 2)),
    'cancel restores the source and applies the selected language');

  await page.evaluate(() => {
    intext.apply({...resultState, seq: 3});
    pywebview.api.submit_text = text => {
      calls.push(['submit_text', text]);
      intext.apply({...resultState, seq: 4, source: text, result: '', status: '正在翻译'});
      return Promise.resolve(true);
    };
  });
  await source.click({position: {x: 12, y: 9}});
  await input.fill('Changed original');
  const imeSafe = await page.evaluate(() => {
    const event = new KeyboardEvent('keydown', {key:'Enter', ctrlKey:true, keyCode:229, bubbles:true, cancelable:true});
    document.getElementById('input').dispatchEvent(event);
    return !event.defaultPrevented && !calls.some(c => c[0] === 'submit_text');
  });
  check(imeSafe, 'IME composition cannot submit accidentally');
  await page.keyboard.press('Control+Enter');
  check(await page.evaluate(() => calls.some(c => c[0] === 'submit_text' && c[1] === 'Changed original')) &&
    !await input.isVisible() && await page.locator('#result').isVisible(), 'edited source submits with Ctrl+Enter');
  await page.evaluate(() => intext.apply({...resultState, seq: 4, source: 'Changed original', result: '修改后的译文'}));
  await source.click({position: {x: 12, y: 9}});
  check(await input.inputValue() === 'Changed original', 'translated source can immediately be edited again');
  await input.fill('Unsaved change');
  await page.keyboard.press('Escape');
  check(!await input.isVisible() && await source.textContent() === 'Changed original' &&
    await page.evaluate(() => !calls.some(c => c[0] === 'hide')), 'Escape cancels editing before closing the window');

  await page.evaluate(() => intext.apply({seq: 5, mode: 'input', draft: 'old draft', from: '自动', to: '简体中文'}));
  await input.fill('Unsent manual draft');
  await page.evaluate(() => intext.apply({...resultState, seq: 6, source: 'Other selection'}));
  await source.click({position: {x: 12, y: 9}});
  await input.fill('Other edit');
  await page.keyboard.press('Escape');
  await page.evaluate(() => intext.apply({seq: 7, mode: 'input', from: '自动', to: '简体中文'}));
  check(await input.inputValue() === 'Unsent manual draft', 'editing a selection preserves a separate manual draft');

  await page.evaluate(() => intext.apply({...resultState, seq: 8, source: '**Bold** and `code`'}));
  await source.click({position: {x: 10, y: 9}});
  check(await input.inputValue() === '**Bold** and `code`', 'editing retains the exact original Markdown');
  await input.fill('x'.repeat(8001));
  check(await page.locator('#submit').isDisabled() && await input.getAttribute('aria-invalid') === 'true', 'long edited source retains input validation');
  await input.fill('Ready to retry');
  await page.evaluate(() => { pywebview.api.submit_text = () => {
    calls.push(['pending_submit']); return new Promise(resolve => { window.finishSubmit = resolve; });
  }; });
  await page.locator('#submit').click();
  await page.evaluate(() => intext.apply({...resultState, seq: 8, source: '**Bold** and `code`', result: '旧请求返回'}));
  await input.focus();
  await page.keyboard.press('Control+Enter');
  check(await page.locator('#submit').isDisabled() && await page.locator('#submit').getAttribute('aria-label') === '提交中…' &&
    await page.evaluate(() => calls.filter(c => c[0] === 'pending_submit').length === 1),
    'a late result cannot re-enable a pending submission');
  await page.evaluate(() => finishSubmit(false));
  check(await page.locator('#submit').getAttribute('aria-label') === '重试翻译' && await input.inputValue() === 'Ready to retry',
    'a rejected submission keeps the draft and offers retry');

  await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 20;
    intext.apply({...resultState, seq: 9, shot: true, image: canvas.toDataURL(), source: '图片直译'});
  });
  await source.click({position: {x: 12, y: 9}});
  check(!await input.isVisible(), 'image-only placeholder is not treated as recognized source text');

  await page.evaluate(() => {
    intext.apply({...resultState, seq: 10});
    pywebview.api.set_languages = () => new Promise((_, reject) => { window.failLanguage = reject; });
  });
  await source.click({position: {x: 12, y: 9}});
  await input.fill('Keep this draft');
  await page.locator('#to').click();
  await page.locator('.language-option').filter({hasText: '日语'}).click();
  await page.evaluate(() => failLanguage(new Error('settings unavailable')));
  await page.waitForFunction(() => !document.getElementById('submit').disabled);
  check(await input.inputValue() === 'Keep this draft' && await page.locator('#to').textContent() === '简体中文' &&
    await page.locator('#to').getAttribute('aria-label') === '译文语言：简体中文', 'failed language change restores labels and keeps the draft');
  await page.locator('#to').click();
  await page.locator('.language-option').filter({hasText: '日语'}).click();
  await page.evaluate(() => {
    intext.apply({...resultState, seq: 11, source: 'New selection', from: '法语', to: '英语', sourceLang: 'fr', resultLang: 'en'});
    failLanguage(new Error('late failure'));
  });
  await page.waitForFunction(() => document.getElementById('to').textContent === '英语');
  check(await source.textContent() === 'New selection' && await page.locator('#from').textContent() === '法语' &&
    await page.locator('#to').getAttribute('aria-label') === '译文语言：英语', 'late language failure cannot overwrite a newer selection');

  await page.evaluate(() => intext.apply({...resultState, seq: 12,
    source: ('Original source line.\n').repeat(18), result: ('Translated paragraph.\n\n').repeat(8)}));
  await source.scrollIntoViewIfNeeded();
  await source.click({position: {x: 18, y: 9}});
  await input.fill(('Edited source text.\n').repeat(18));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  check(await page.evaluate(() => {
    const content = document.getElementById('content'), field = document.getElementById('input');
    const note = document.getElementById('edit-note'), bounds = content.getBoundingClientRect();
    const visibleTextBottom = field.getBoundingClientRect().bottom - parseFloat(getComputedStyle(field).paddingBottom);
    return visibleTextBottom <= bounds.bottom - 18 && note.getBoundingClientRect().bottom <= bounds.bottom - 16 &&
      parseFloat(getComputedStyle(content).getPropertyValue('--scroll-fade-bottom')) === 0;
  }), 'long edited source and its stale-result note remain visible without fading');
  return report;
}
