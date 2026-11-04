async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = [];
  const check = (value, name) => {
    if (!value) throw new Error(name);
    report.push(name);
  };
  const downOutside = async (selector, name, x = 400, y = 32) => {
    await page.mouse.move(x, y);
    await page.mouse.down();
    check(await page.locator(selector).isHidden(), name);
    await page.mouse.up();
  };
  const blur = () => page.evaluate(() => window.dispatchEvent(new Event('blur')));
  const fixture = () => page.evaluate(() => {
    window.calls = [];
    window.pywebview = {api: new Proxy({}, {get: (_, method) => (...args) => {
      calls.push([method, ...args]);
      return Promise.resolve({});
    }})};
  });
  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({colorScheme, reducedMotion: 'no-preference'});
    await page.setViewportSize({width: 480, height: 600});
    await page.goto(base + 'settings.html');
    await fixture();
    const selectors = ['#source-button', '#target-button', '#shot-input-button', '#shot-display-button', '#preview-kind-button', '.combo .menu-btn'];
    for (const selector of selectors) {
      const button = page.locator(selector);
      const menu = '.menu-pop:not([hidden])';
      await button.click();
      check(await page.locator(menu).count() === 1, colorScheme + selector + ' opens');
      await downOutside(menu, colorScheme + selector + ' closes before native drag');
      await button.click();
      await blur();
      check(await page.locator(menu).count() === 0, colorScheme + selector + ' closes on blur');
      await button.click();
      await button.click();
      check(await page.locator(menu).count() === 0, colorScheme + selector + ' toggles closed');
      await button.click();
      const first = page.locator(menu + ' .menu-opt').first();
      await first.click();
      check(await page.locator(menu).count() === 0, colorScheme + selector + ' selection closes');
    }
    await page.locator('#source-button').click();
    await page.locator('#target-button').click();
    check(await page.locator('#menu-source').isHidden() && await page.locator('#menu-target').isVisible(), colorScheme + ' switching menus');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Escape');
    check(await page.locator('#menu-target').isHidden(), colorScheme + ' Escape closes');
    await page.locator('#source-button').click();
    await page.locator('[aria-label="截图热键说明"]').click();
    check(await page.locator('#menu-source').isHidden(), colorScheme + ' help click closes despite preventDefault');

    // The menu scrollbar is mounted outside the menu's DOM subtree.
    await page.setViewportSize({width: 400, height: 380});
    await page.evaluate(() => {
      const b = document.getElementById('source-button');
      document.getElementById('sheet').scrollTop += b.getBoundingClientRect().top - 160;
    });
    await page.locator('#source-button').click();
    await page.waitForTimeout(180);
    await page.evaluate(() => { document.getElementById('menu-source').scrollTop = 1; });
    await page.waitForTimeout(50);
    const startScroll = await page.locator('#menu-source').evaluate(e => ({top:e.scrollTop, height:e.clientHeight,total:e.scrollHeight}));
    const thumb = await page.evaluate(() => {
      const t = [...document.querySelectorAll('.mac-thumb')].find(e => e._intextScroller.id === 'menu-source' && !e.hidden);
      const b = t.getBoundingClientRect();
      return {x: b.x + b.width / 2, y: b.y + b.height / 2};
    });
    await page.mouse.move(thumb.x, thumb.y);
    await page.mouse.down();
    await page.mouse.move(thumb.x, thumb.y + 14);
    await page.mouse.up();
    check(await page.locator('#menu-source').isVisible(), colorScheme + ' menu scrollbar retains menu');
    const finishScroll = await page.locator('#menu-source').evaluate(e => e.scrollTop);
    check(finishScroll > startScroll.top, colorScheme + ' menu scrollbar scrolls ' + JSON.stringify({startScroll,finishScroll,thumb}));
    await page.evaluate(() => {
      const t = [...document.querySelectorAll('.mac-thumb')].find(e => e._intextScroller.id === 'sheet');
      t.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true, button: 0}));
      t.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, button: 0}));
    });
    check(await page.locator('#menu-source').isHidden(), colorScheme + ' unrelated scrollbar closes menu');

    await page.setViewportSize({width: 460, height: 312});
    await page.goto(base + 'popup.html');
    await fixture();
    await page.evaluate(() => intext.apply({seq: 1, from: '自动', to: '简体中文', source: 'hello', result: '你好', pinned: true}));
    for (const selector of ['#from', '#to', '#swap']) {
      await page.locator(selector).click();
      await downOutside('#languages', colorScheme + selector + ' closes before drag', 300, 44);
      await page.locator(selector).click();
      await blur();
      check(await page.locator('#languages').isHidden(), colorScheme + selector + ' closes on blur');
      await page.locator(selector).click();
      await page.locator(selector).click();
      check(await page.locator('#languages').isHidden(), colorScheme + selector + ' toggles closed');
      await page.locator(selector).click();
      await page.locator('#copy').focus();
      check(await page.locator('#languages').isHidden(), colorScheme + selector + ' closes on focus outside');
      await page.locator(selector).click();
      const first = page.locator('#languages .language-option').first();
      await first.click();
      check(await page.locator('#languages').isHidden(), colorScheme + selector + ' selection closes');
    }
    await page.locator('#from').click();
    await page.locator('#to').click();
    check(await page.locator('#from').getAttribute('aria-expanded') === 'false' && await page.locator('#to').getAttribute('aria-expanded') === 'true', colorScheme + ' popup switches menu');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Escape');
    check(await page.locator('#languages').isHidden(), colorScheme + ' popup Escape closes');
  }
  return {passed: true, checks: report.length, cases: report};
}
