async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  const check = (ok, name) => { if (!ok) throw new Error(name); report[name] = true; };
  await page.setViewportSize({width: 460, height: 400});
  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({colorScheme, forcedColors: 'none', reducedMotion: 'reduce'});
    await page.goto(base + 'popup.html');
    await page.evaluate(() => intext.apply({seq: 1, mode: 'input', draft: 'Editable translation text'}));
    const input = page.locator('#input');
    const style = () => input.evaluate(el => {
      const css = getComputedStyle(el);
      return {background: css.backgroundColor, image: css.backgroundImage, opacity: css.opacity,
        filter: css.filter, shadow: css.boxShadow, border: css.borderWidth, outline: css.outlineStyle};
    });
    await input.evaluate(el => el.blur());
    const unfocused = await style();
    await input.click();
    const focused = await style();
    check(['background', 'image', 'opacity', 'filter'].every(key => focused[key] === unfocused[key]), colorScheme + ' focused input keeps its material');
    check(focused.background === 'rgba(0, 0, 0, 0)' && focused.shadow === 'none' && focused.border === '0px' &&
      focused.outline === 'none', colorScheme + ' editor has no inner surface');
    await input.fill('Hello');
    await page.keyboard.type(' world');
    check(await input.inputValue() === 'Hello world', colorScheme + ' input remains editable');
    const singleLine = await input.evaluate(el => el.clientHeight);
    await input.fill('First line\nSecond line\nThird line');
    const multiLine = await input.evaluate(el => el.clientHeight);
    await input.fill(('A longer line of text\n').repeat(18));
    const overflow = await input.evaluate(el => el.clientHeight <= 152 && el.scrollHeight > el.clientHeight);
    await input.fill('Hello');
    check(multiLine > singleLine && overflow && await input.evaluate(el => el.clientHeight) === singleLine,
      colorScheme + ' editor grows and shrinks with text and scrolls long input');
    check(!await page.locator('#input-count').isVisible(), colorScheme + ' ordinary input has no distracting counter');
    await input.fill('x'.repeat(7200));
    check(await page.locator('#input-count').isVisible(), colorScheme + ' length limit remains discoverable');
    await input.fill('Hello');
    await input.evaluate(el => el.blur());
    check((await style()).shadow === 'none', colorScheme + ' editor remains unframed on blur');
    await page.emulateMedia({forcedColors: 'active'});
    await input.focus();
    check((await style()).outline !== 'none', colorScheme + ' high contrast focus remains visible');
    await page.emulateMedia({forcedColors: 'none'});
    await page.evaluate(() => intext.apply({seq: 2, source: 'Original text', result: '译文'}));
    await page.keyboard.press('Tab');
    const content = page.locator('#content');
    await content.focus();
    check(await content.evaluate(el => {
      const css = getComputedStyle(el);
      return el.matches(':focus-visible') && css.backgroundColor === 'rgba(0, 0, 0, 0)' &&
        css.backgroundImage === 'none' && css.boxShadow === 'none' && css.borderWidth === '0px';
    }), colorScheme + ' keyboard focus adds no inner surface to the result');
    const source = page.locator('#source');
    const before = await source.evaluate(el => {
      const rect = el.getBoundingClientRect(), css = getComputedStyle(el);
      return {x: rect.x + parseFloat(css.paddingLeft), y: rect.y + parseFloat(css.paddingTop), size: css.fontSize, line: css.lineHeight, color: css.color};
    });
    await source.click({position: {x: 12, y: 9}});
    const after = await input.evaluate(el => {
      const rect = el.getBoundingClientRect(), css = getComputedStyle(el);
      return {x: rect.x + parseFloat(css.paddingLeft), y: rect.y + parseFloat(css.paddingTop), size: css.fontSize, line: css.lineHeight, color: css.color};
    });
    check(Math.abs(before.x - after.x) < 1 && Math.abs(before.y - after.y) < 1 &&
      before.size === after.size && before.line === after.line && before.color === after.color,
      colorScheme + ' source stays aligned and styled the same when editing');
    const inline = await style();
    check(inline.background === 'rgba(0, 0, 0, 0)' && inline.image === 'none' &&
      inline.shadow === 'none' && inline.border === '0px', colorScheme + ' inline editor has no inner surface');
  }
  await page.emulateMedia({forcedColors: 'none'});
  return report;
}
