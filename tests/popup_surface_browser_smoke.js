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
        filter: css.filter, shadow: css.boxShadow, outline: css.outlineStyle};
    });
    await input.evaluate(el => el.blur());
    const unfocused = await style();
    await input.click();
    const focused = await style();
    check(['background', 'image', 'opacity', 'filter'].every(key => focused[key] === unfocused[key]), colorScheme + ' focused input keeps its material');
    check(focused.shadow !== unfocused.shadow && focused.outline === 'none', colorScheme + ' focused input has a subtle border');
    await input.fill('Hello');
    await page.keyboard.type(' world');
    check(await input.inputValue() === 'Hello world', colorScheme + ' input remains editable');
    await input.evaluate(el => el.blur());
    check((await style()).shadow === unfocused.shadow, colorScheme + ' border returns to normal on blur');
    await page.emulateMedia({forcedColors: 'active'});
    await input.focus();
    check((await style()).outline !== 'none', colorScheme + ' high contrast focus remains visible');
  }
  await page.emulateMedia({forcedColors: 'none'});
  return report;
}
