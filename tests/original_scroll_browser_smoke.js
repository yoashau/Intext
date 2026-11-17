async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  const check = (ok, name) => { if (!ok) throw new Error(name); report[name] = true; };
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.bringToFront();
  await page.emulateMedia({reducedMotion: 'reduce', forcedColors: 'none'});

  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({colorScheme});
    await page.setViewportSize({width: 640, height: 440});
    await page.goto(base + 'shot-overlay.html');
    await page.evaluate(() => {
      window.calls = [];
      window.pywebview = {api: new Proxy({}, {get: (_, key) => (...args) => {
        calls.push([key, ...args]); return Promise.resolve(true);
      }})};
      const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 240;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 600, 240);
      ctx.fillStyle = '#171714'; ctx.font = '28px sans-serif';
      ctx.fillText('Original source words', 30, 60); ctx.fillText('第二行原文', 30, 140);
      window.shotState = {seq: 1, width: 600, height: 240, image: canvas.toDataURL(), text: '译文第一行\nTranslated second line',
        blocks: [{text: '译文第一行', original: 'Original source words', left: 5, top: 13, width: 48, height: 13, fontSize: 28, background: 'white', color: 'black'},
          {text: 'Translated second line', original: '第二行原文', left: 5, top: 46, width: 28, height: 13, fontSize: 28, background: 'white', color: 'black'}]};
      intextShot.apply(shotState);
    });
    await page.locator('#original').click();
    const sourcePixels = await page.locator('#canvas').screenshot();
    await page.evaluate(() => { document.getElementById('original-labels').style.visibility = 'hidden'; });
    const barePixels = await page.locator('#canvas').screenshot();
    await page.evaluate(() => { document.getElementById('original-labels').style.visibility = ''; });
    check(sourcePixels.equals(barePixels), colorScheme + ' selectable source preserves image pixels');
    const selector = '#original-labels .region';
    await page.locator(selector).first().dblclick({position: {x: 20, y: 10}});
    const selected = await page.evaluate(() => getSelection().toString());
    check(selected.length > 0 && 'Original source words'.includes(selected), colorScheme + ' original mouse selection');
    await page.keyboard.press('Control+c');
    check(await page.evaluate(text => calls.at(-1)?.[0] === 'copy_text' && calls.at(-1)[1] === text && !calls.some(c => c[0] === 'begin_drag'), selected), colorScheme + ' original partial copy');
    await page.evaluate(() => getSelection().removeAllRanges());
    const box = await page.locator(selector).first().boundingBox();
    await page.mouse.move(box.x + box.width * .2, box.y + box.height / 2);
    await page.mouse.down(); await page.mouse.move(box.x + box.width * .65, box.y + box.height / 2, {steps: 10}); await page.mouse.up();
    const dragged = await page.evaluate(() => getSelection().toString());
    await page.keyboard.press('Control+c');
    check(dragged.length > 0 && dragged.length < 'Original source words'.length && 'Original source words'.includes(dragged) &&
      await page.evaluate(text => calls.at(-1)?.[1] === text, dragged), colorScheme + ' original freely dragged substring copy');

    const multiple = await page.evaluate(() => {
      const rows = document.querySelectorAll('#original-labels .region span');
      const range = document.createRange(); range.setStart(rows[0].firstChild, 9); range.setEnd(rows[1].firstChild, 3);
      getSelection().removeAllRanges(); getSelection().addRange(range);
      return getSelection().toString();
    });
    await page.keyboard.press('Control+Insert');
    check(multiple.includes('source words') && multiple.includes('第二行') && await page.evaluate(text => calls.at(-1)?.[1] === text, multiple), colorScheme + ' original multiline copy');
    check(await page.evaluate(() => [...document.querySelectorAll('#original-labels .region')].every(el => {
      const style = getComputedStyle(el), text = el.firstElementChild.getBoundingClientRect(), box = el.getBoundingClientRect();
      return style.color === 'rgba(0, 0, 0, 0)' && style.backgroundColor === 'rgba(0, 0, 0, 0)' && Math.abs(text.width - box.width) < 1 && text.height <= box.height + 1;
    })), colorScheme + ' source pixels unobscured and selection aligned');
    await page.setViewportSize({width: 420, height: 340}); await settle();
    check(await page.evaluate(() => [...document.querySelectorAll('#original-labels .region')].every(el => Math.abs(el.firstElementChild.getBoundingClientRect().width - el.getBoundingClientRect().width) < 1)), colorScheme + ' original resize alignment');
    await page.locator('#original').click();
    check(await page.evaluate(() => getSelection().toString() === '' && document.getElementById('original-labels').hidden && !document.getElementById('labels').hidden), colorScheme + ' switching clears hidden selection');
    await page.locator('#labels .region').first().dblclick({position: {x: 15, y: 7}});
    const translation = await page.evaluate(() => getSelection().toString());
    await page.keyboard.press('Control+c');
    check(translation.length > 0 && await page.evaluate(text => calls.at(-1)?.[1] === text, translation), colorScheme + ' translation copying retained');
    await page.locator('#viewport').focus();
    await page.keyboard.down('Space');
    check(await page.locator('#original-labels').isVisible(), colorScheme + ' hold space source selection');
    await page.keyboard.up('Space');
    check(!await page.locator('#original-labels').isVisible(), colorScheme + ' release space translation');
    await page.evaluate(() => intextShot.apply({...shotState, seq: 2, busy: true, blocks: []}));
    check(await page.locator('#original-labels .region').count() === 0, colorScheme + ' new screenshot removes old source text');

    await page.setViewportSize({width: 460, height: 320});
    await page.goto(base + 'popup.html');
    await page.evaluate(() => intext.apply({seq: 1, source: 'Original source', result: ('A long translated paragraph with readable text.\n\n').repeat(30)}));
    await settle();
    const fade = () => page.evaluate(() => {
      const el = document.getElementById('content'), style = getComputedStyle(el);
      return {top: parseFloat(style.getPropertyValue('--scroll-fade-top')), bottom: parseFloat(style.getPropertyValue('--scroll-fade-bottom')), mask: style.maskImage, overflow: el.scrollHeight - el.clientHeight};
    });
    let edges = await fade();
    check(edges.overflow > 100 && edges.top === 0 && edges.bottom === 28 && edges.mask.includes('linear-gradient'), colorScheme + ' top text clear and bottom fades');
    check(await page.evaluate(() => {
      const el = document.getElementById('content'), box = el.getBoundingClientRect();
      const head = document.querySelector('.row').getBoundingClientRect(), foot = document.querySelector('.foot').getBoundingClientRect();
      const first = document.getElementById('result').getBoundingClientRect();
      const button = document.getElementById('copy'), tool = button.getBoundingClientRect();
      return Math.abs(box.top - head.bottom + 6) < 1 && Math.abs(box.bottom - foot.top - 6) < 1 &&
        Math.abs(first.top - head.bottom - 13) < 1 && button.contains(document.elementFromPoint(tool.x + tool.width / 2, tool.y + 2));
    }), colorScheme + ' fade borrows toolbar gaps without moving text or covering tools');
    await page.locator('#content').hover(); await page.mouse.wheel(0, 120); await settle();
    edges = await fade();
    check(edges.top === 28 && edges.bottom === 28, colorScheme + ' scrolling fades both edges');
    await page.evaluate(() => { const el = document.getElementById('content'); el.scrollTop = el.scrollHeight; }); await settle();
    edges = await fade();
    check(edges.top === 28 && edges.bottom === 0, colorScheme + ' bottom text fully readable');
    await page.evaluate(() => { document.getElementById('content').scrollTop = 5; }); await settle();
    edges = await fade();
    check(Math.abs(edges.top - 5) < 1 && edges.bottom === 28, colorScheme + ' fade depth follows remaining content');
    await page.evaluate(() => intext.apply({seq: 1, source: 'Original source', result: 'Short result'})); await settle();
    edges = await fade();
    check(edges.top === 0 && edges.bottom === 0, colorScheme + ' short replacement has no fade');
    await page.evaluate(() => intext.apply({seq: 2, mode: 'input', enter: true})); await settle();
    edges = await fade();
    check(edges.top === 0 && edges.bottom === 0 && await page.locator('#input').isEditable(), colorScheme + ' input mode remains readable');
  }
  await page.emulateMedia({forcedColors: 'active', colorScheme: 'light'});
  await page.goto(base + 'shot-overlay.html');
  await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 360; canvas.height = 120;
    const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, 360, 120);
    ctx.fillStyle = '#000'; ctx.font = '24px sans-serif'; ctx.fillText('Original words', 20, 50);
    intextShot.apply({seq: 1, width: 360, height: 120, image: canvas.toDataURL(),
      blocks: [{text: '译文', original: 'Original words', left: 5, top: 20, width: 60, height: 25, fontSize: 24, background: 'white', color: 'black'}]});
    document.getElementById('original').click();
  });
  const sourcePixels = await page.locator('#canvas').screenshot();
  await page.evaluate(() => { document.getElementById('original-labels').style.visibility = 'hidden'; });
  const barePixels = await page.locator('#canvas').screenshot();
  check(sourcePixels.equals(barePixels), 'high contrast keeps source selection transparent');
  await page.evaluate(() => { document.getElementById('original-labels').style.visibility = ''; });
  await page.locator('#original-labels .region').first().dblclick({position: {x: 18, y: 10}});
  check((await page.evaluate(() => getSelection().toString())).length > 0, 'high contrast source text remains selectable');
  await page.emulateMedia({forcedColors: 'none'});
  return report;
}
