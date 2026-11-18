async (page) => {
  const base = 'http://127.0.0.1:8768/src/intext/assets/';
  const report = {};
  for (const file of ['popup.html', 'shot-overlay.html']) {
    await page.goto(base + file);
    const result = await page.evaluate(async file => {
      const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 240;
      const image = canvas.toDataURL();
      const target = document.getElementById(file === 'popup.html' ? 'shot-image' : 'image');
      let writes = 0;
      const observer = new MutationObserver(changes => { writes += changes.filter(c => c.attributeName === 'src').length; });
      observer.observe(target, {attributes: true});
      const apply = file === 'popup.html' ? intext.apply : intextShot.apply;
      apply({seq: 1, image, width: 600, height: 240, busy: true, status: '正在识别'});
      await Promise.resolve();
      const first = writes;
      apply({seq: 1, image, width: 600, height: 240, busy: true, status: '正在翻译'});
      apply({seq: 1, image, width: 600, height: 240, busy: false, result: '译文', text: '译文', blocks: []});
      await Promise.resolve();
      const reused = first === 1 && writes === 1;
      apply({seq: 2, image: '', blocks: []}); await Promise.resolve();
      const cleared = !target.hasAttribute('src');
      observer.disconnect();
      return {reused, cleared};
    }, file);
    if (!result.reused || !result.cleared) throw new Error(file + ' image resource lifecycle');
    report[file] = result;
  }
  return report;
}
