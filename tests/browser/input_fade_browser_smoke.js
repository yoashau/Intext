async (page) => {
  const report = {};
  const check = (value, name) => { if (!value) throw new Error(name); report[name] = true; };
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const text = Array.from({length: 20}, (_, index) => `Line ${index + 1}: editable translation text.`).join('\n');

  for (const theme of ['light', 'dark']) {
    for (const mode of ['input', 'source']) {
      await page.setViewportSize({width: 460, height: 312});
      await page.emulateMedia({colorScheme: theme, reducedMotion: 'reduce', forcedColors: 'none'});
      await page.goto('http://127.0.0.1:8768/src/intext/assets/popup.html');
      if (mode === 'input') {
        await page.evaluate(text => intext.apply({seq: 1, mode: 'input', draft: text, enter: true}), text);
      } else {
        await page.evaluate(text => intext.apply({seq: 1, source: text, result: 'Translated result'}), text);
        await page.locator('#source').scrollIntoViewIfNeeded();
        await page.locator('#source').click({position: {x: 12, y: 9}});
      }
      const input = page.locator('#input');
      const snapshot = () => input.evaluate(el => {
        const css = getComputedStyle(el), rect = el.getBoundingClientRect();
        const row = document.querySelector('.row').getBoundingClientRect();
        const foot = document.querySelector('.foot').getBoundingClientRect();
        return {top: parseFloat(css.getPropertyValue('--scroll-fade-top')),
          bottom: parseFloat(css.getPropertyValue('--scroll-fade-bottom')),
          mask: css.maskImage, overflow: el.scrollHeight - el.clientHeight,
          topInset: parseFloat(css.paddingTop), bottomInset: parseFloat(css.paddingBottom),
          above: rect.top < row.bottom, below: rect.bottom > foot.top};
      });
      const setScroll = async value => {
        await input.evaluate((el, value) => { el.scrollTop = value === 'end' ? el.scrollHeight : value; }, value);
        await settle();
      };
      await setScroll(0);
      let edges = await snapshot();
      check(edges.overflow > 100 && edges.top === 0 && edges.bottom === 28 && edges.mask.includes('linear-gradient'),
        `${theme} ${mode}: top readable and bottom fades`);
      check(edges.topInset === 16 && edges.bottomInset === 16 && edges.below && (mode !== 'input' || edges.above),
        `${theme} ${mode}: fade extends into the toolbar gaps`);
      check(await page.evaluate(() => ['#from', '#to', '#submit', '#pin'].every(selector => {
        const button = document.querySelector(selector), rect = button.getBoundingClientRect();
        return button.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + 2));
      })), `${theme} ${mode}: extended input does not cover toolbar actions`);
      await input.hover();
      await page.mouse.wheel(0, 90);
      await settle();
      check(await input.evaluate(el => el.scrollTop > 0), `${theme} ${mode}: mouse wheel scrolls the input`);
      await setScroll(edges.overflow / 2);
      edges = await snapshot();
      check(edges.top === 28 && edges.bottom === 28, `${theme} ${mode}: both edges fade while scrolling`);
      await setScroll('end');
      edges = await snapshot();
      check(edges.top === 28 && edges.bottom === 0, `${theme} ${mode}: last line remains readable`);
      await setScroll(5);
      edges = await snapshot();
      check(Math.abs(edges.top - 5) < 1 && edges.bottom === 28, `${theme} ${mode}: fade follows remaining content`);

      await input.fill('A short line');
      await settle();
      edges = await snapshot();
      check(edges.overflow <= 1 && edges.top === 0 && edges.bottom === 0, `${theme} ${mode}: short input is not faded`);
      await input.fill(text);
      await input.focus();
      await page.keyboard.press('Control+End');
      await page.keyboard.type('!');
      await settle();
      edges = await snapshot();
      check((await input.inputValue()) === text + '!' && edges.bottom === 0, `${theme} ${mode}: typing leaves the caret edge clear`);
      const caretInClearArea = () => input.evaluate(el => {
        const css = getComputedStyle(el), line = el.value.slice(0, el.selectionStart).split('\n').length - 1;
        const y = parseFloat(css.paddingTop) + line * parseFloat(css.lineHeight) - el.scrollTop;
        return y >= parseFloat(css.getPropertyValue('--scroll-fade-top')) - 3 &&
          y + parseFloat(css.lineHeight) <= el.clientHeight - parseFloat(css.getPropertyValue('--scroll-fade-bottom')) + 3;
      });
      for (let i = 0; i < 7; i++) await page.keyboard.press('ArrowUp');
      await settle();
      check(await caretInClearArea(), `${theme} ${mode}: moving the caret up keeps it out of the fade`);
      await page.keyboard.press('Control+Home');
      for (let i = 0; i < 7; i++) await page.keyboard.press('ArrowDown');
      await settle();
      check(await caretInClearArea(), `${theme} ${mode}: moving the caret down keeps it out of the fade`);
      await page.keyboard.press('Control+Home');
      await page.keyboard.press('Shift+ArrowRight');
      check(await input.evaluate(el => el.selectionEnd - el.selectionStart === 1), `${theme} ${mode}: text remains selectable`);
      await page.keyboard.press('Backspace');
      check((await input.inputValue()) === text.slice(1) + '!', `${theme} ${mode}: selected text can be edited`);
    }
  }
  return report;
}
