// Behavioral checks for the shared tooltip. The native runner supplies a
// small, synthetic document and waits for the report to complete.
window.runTooltipEdges = function () {
  const tip = document.querySelector('#tooltip');
  const a = document.querySelector('#a');
  const child = document.querySelector('#child');
  const b = document.querySelector('#b');
  const long = document.querySelector('#long');
  const dynamic = document.querySelector('#dynamic');
  const outside = document.querySelector('#outside');
  const edge = document.querySelector('#edge');
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const event = (node, type, relatedTarget = null) => node.dispatchEvent(new PointerEvent(type, {bubbles:true, relatedTarget}));
  const enter = (node, from) => event(node, 'pointerover', from);
  const leave = (node, to) => event(node, 'pointerout', to);
  const expect = (condition, message) => { if (!condition) throw new Error(message); };
  const report = window.tooltipEdges = {done:false, cases:[]};
  async function run(name, action) {
    intextControls.resetTooltip();
    await wait(400); // Let an orphaned timer from a prior failing case expire.
    tip.classList.remove('is-scrollable');
    try { await action(); report.cases.push({name, passed:true}); }
    catch (error) { report.cases.push({name, passed:false, error:String(error)}); }
  }
  (async function () {
    await run('01 hover shows and leaves cleanly', async () => {
      enter(a, outside); await wait(340);
      expect(!tip.hidden && tip.textContent === 'alpha', 'hover did not show alpha');
      leave(a, outside); expect(tip.hidden, 'tip remained after leaving');
    });
    await run('02 leaving before delay cancels show', async () => {
      enter(a, outside); await wait(80); leave(a, outside); await wait(340);
      expect(tip.hidden, 'pending tooltip appeared after leaving');
    });
    await run('03 switching targets cancels stale work', async () => {
      enter(a, outside); await wait(80); leave(a,b); enter(b,a); await wait(340);
      expect(!tip.hidden && tip.textContent === 'beta', 'wrong target or missing tooltip');
    });
    await run('04 moving between a control and its child preserves delay', async () => {
      enter(a, outside); await wait(100); leave(a,child); enter(child,a); await wait(230);
      expect(!tip.hidden && tip.textContent === 'alpha', 'child transition canceled hover');
    });
    await run('05 quick leave after a long tooltip never flashes', async () => {
      enter(long,outside); await wait(340);
      expect(!tip.hidden && tip.classList.contains('is-scrollable'), 'long tooltip did not become scrollable');
      leave(long,a); enter(a,long); await wait(150);
      let flashes = 0;
      const observer = new MutationObserver(() => { if (!tip.hidden) flashes++; });
      observer.observe(tip,{attributes:true,attributeFilter:['hidden']});
      leave(a,outside); await wait(400); observer.disconnect();
      expect(tip.hidden && flashes === 0, 'tooltip flashed after pointer left');
    });
    await run('06 entering a scrollable tooltip keeps it open', async () => {
      enter(long,outside); await wait(340);
      expect(!tip.hidden && tip.classList.contains('is-scrollable'), 'long tooltip missing');
      leave(long,tip); tip.dispatchEvent(new PointerEvent('pointerenter'));
      await wait(240); expect(!tip.hidden, 'tooltip closed while pointer was over it');
      tip.dispatchEvent(new PointerEvent('pointerleave',{relatedTarget:outside}));
      expect(tip.hidden, 'tooltip stayed open after leaving it');
    });
    await run('07 updated tooltip text stays current while hovered', async () => {
      dynamic.dataset.tooltip = 'first'; enter(dynamic,outside); await wait(340);
      expect(!tip.hidden && tip.textContent === 'first', 'first tooltip missing');
      dynamic.dataset.tooltip = 'second'; await wait(60);
      expect(!tip.hidden && tip.textContent === 'second', 'updated tooltip disappeared or remained stale');
    });
    await run('08 removing a pending target cancels its tooltip', async () => {
      const n=document.createElement('button');n.dataset.tooltip='removed';document.body.append(n);
      enter(n,outside); await wait(80); n.remove(); await wait(340);
      expect(tip.hidden, 'removed target still showed a tooltip');
    });
    await run('09 disabling a pending target cancels its tooltip', async () => {
      b.disabled=false; enter(b,outside); await wait(80); b.disabled=true; await wait(340);
      expect(tip.hidden, 'disabled target still showed a tooltip'); b.disabled=false;
    });
    await run('10 disabling an owner removes its accessible description', async () => {
      b.disabled=false; enter(b,outside); await wait(340);
      expect(!tip.hidden, 'tooltip missing: ' + JSON.stringify({disabled:b.disabled, connected:b.isConnected, visible:document.visibilityState, rects:b.getClientRects().length, text:b.dataset.tooltip}));
      b.disabled=true; await wait(40);
      expect(tip.hidden && !(b.getAttribute('aria-describedby')||'').split(/\s+/).includes('tooltip'), 'disabled owner retained tooltip');
      b.disabled=false;
    });
    await run('11 visible transition preserves pending hover', async () => {
      enter(a,outside); document.dispatchEvent(new Event('visibilitychange')); await wait(340);
      expect(!tip.hidden && tip.textContent === 'alpha', 'visible transition canceled hover');
    });
    await run('12 native reset cancels pending hover', async () => {
      enter(a,outside); await wait(80); intextControls.resetTooltip(); await wait(340);
      expect(tip.hidden, 'tooltip appeared after native reset');
    });
    await run('13 tooltip fits the bottom and right edges', async () => {
      enter(edge,outside); await wait(340); expect(!tip.hidden,'edge tooltip missing');
      const r=tip.getBoundingClientRect();
      expect(r.left>=7 && r.top>=7 && r.right<=innerWidth-7 && r.bottom<=innerHeight-7, 'tooltip leaves viewport');
    });
    await run('14 existing accessibility descriptions survive hide', async () => {
      a.setAttribute('aria-describedby','first-description second-description');
      enter(a,outside); await wait(340);
      expect((a.getAttribute('aria-describedby')||'').split(/\s+/).includes('tooltip'), 'tooltip was not linked');
      leave(a,outside);
      expect(a.getAttribute('aria-describedby')==='first-description second-description', 'original descriptions were lost');
      a.removeAttribute('aria-describedby');
    });
    await run('15 keyboard focus survives unrelated pointer departure', async () => {
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));
      a.focus(); await wait(40);
      expect(document.hasFocus() && a.matches(':focus-visible') && !tip.hidden, 'keyboard tooltip missing: ' + JSON.stringify({focus:document.hasFocus(), focusVisible:a.matches(':focus-visible'), active:document.activeElement.id, hidden:tip.hidden}));
      enter(a,outside); leave(a,outside); await wait(40);
      expect(!tip.hidden, 'pointer departure hid keyboard-focused help');
      a.blur();
    });
    await run('16 hiding an ancestor closes help and clears its description', async () => {
      const parent=document.createElement('div'), button=document.createElement('button');
      button.dataset.tooltip='nested';parent.append(button);document.body.append(parent);
      enter(button,outside);await wait(340);expect(!tip.hidden,'nested tooltip missing');
      parent.hidden=true;await wait(40);
      expect(tip.hidden && !button.hasAttribute('aria-describedby'),'hidden ancestor retained help');
      parent.remove();
    });
    await run('17 long content can become short while shown', async () => {
      const text=long.dataset.tooltip;
      enter(long,outside);await wait(340);expect(tip.classList.contains('is-scrollable'),'long help missing');
      long.dataset.tooltip='short';await wait(40);
      expect(!tip.hidden && tip.textContent==='short' && !tip.classList.contains('is-scrollable'),'long-to-short update failed');
      long.dataset.tooltip=text;
    });
    await run('18 clearing content dismisses help and removes its description', async () => {
      dynamic.dataset.tooltip='shown';enter(dynamic,outside);await wait(340);
      expect(!tip.hidden,'dynamic help missing');dynamic.dataset.tooltip='';await wait(40);
      expect(tip.hidden && !dynamic.hasAttribute('aria-describedby'),'empty help remained visible or linked');
      dynamic.dataset.tooltip='first';
    });
    await run('19 rapid content changes settle on the newest text', async () => {
      dynamic.dataset.tooltip='start';enter(dynamic,outside);await wait(340);
      for (let i=0;i<50;i++) dynamic.dataset.tooltip='update '+i;
      await wait(60);expect(!tip.hidden && tip.textContent==='update 49','rapid updates left stale or hidden help');
    });
    await run('23 focus loss does not cancel a fresh pointer hover', async () => {
      enter(a,outside); await wait(80);
      a.dispatchEvent(new FocusEvent('focusout',{bubbles:true})); await wait(340);
      expect(!tip.hidden && tip.textContent==='alpha', 'focus loss canceled an active hover');
      leave(a,outside);
    });
    await run('24 delayed native reset does not cancel a newer hover', async () => {
      const resetRequested = Date.now(); await wait(25);
      enter(a,outside); await wait(80); intextControls.resetTooltip(resetRequested); await wait(340);
      expect(!tip.hidden && tip.textContent==='alpha', 'late reset canceled newer hover input');
      leave(a,outside);
    });
    await run('25 native reset still clears an older hover', async () => {
      enter(a,outside); await wait(40);
      intextControls.resetTooltip(Date.now()); await wait(340);
      expect(tip.hidden, 'native reset retained an older hover');
    });
    report.done=true;
  })().catch(error => { report.error=String(error); report.done=true; });
};
