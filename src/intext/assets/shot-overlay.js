let current = null, sequence = -1, comparing = false, copyTimer = 0;
const canvas = document.getElementById('canvas'), image = document.getElementById('image');
const labels = document.getElementById('labels'), viewport = document.getElementById('viewport');
const original = document.getElementById('original'), retry = document.getElementById('retry'), copy = document.getElementById('copy');
const announcement = document.getElementById('announcement'), panel = document.getElementById('panel');
function api(name, ...args) { const bridge = window.pywebview && window.pywebview.api; if (bridge && typeof bridge[name] === 'function') return bridge[name](...args); }
function compare(value) {
  comparing = !!value; labels.hidden = comparing;
  original.setAttribute('aria-pressed', String(comparing));
  original.setAttribute('aria-label', comparing ? '查看译文' : '查看原图');
  original.dataset.tooltip = comparing ? '查看译文' : '点击切换，或按住空格查看原图';
}
function resetCopy() { clearTimeout(copyTimer); copy.classList.remove('is-copied'); copy.dataset.tooltip = '复制译文'; }
function fit() {
  if (!current || !current.width) return;
  const scale = Math.min(1, viewport.clientWidth / current.width, viewport.clientHeight / current.height);
  canvas.style.width = (current.width * scale) + 'px'; canvas.style.height = (current.height * scale) + 'px';
  labels.querySelectorAll('.region').forEach((el, index) => {
    const block = current.blocks[index]; let low = Math.max(7, 9 * scale), high = Math.max(low, Math.min(96, block.fontSize) * scale);
    for (let i = 0; i < 9; i++) {
      const size = (low + high) / 2; el.style.fontSize = size + 'px';
      if (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1) high = size; else low = size;
    }
    el.style.fontSize = low + 'px'; el.dataset.tooltip = block.text;
  });
}
window.intextShot = { apply(state) {
  if (typeof state.seq === 'number' && state.seq < sequence) return;
  sequence = state.seq; resetCopy();
  const busy = !!state.busy;
  retry.disabled = busy; retry.classList.toggle('is-busy', busy);
  copy.disabled = busy || !state.text;
  original.disabled = !state.image;
  panel.dataset.state = state.error ? 'error' : busy ? 'progress' : 'content';
  panel.setAttribute('aria-busy', String(busy));
  document.getElementById('message').hidden = !busy && !state.error;
  document.getElementById('status').textContent = state.error ? '翻译失败' : (state.status || '正在翻译…');
  document.getElementById('error').textContent = state.error || '';
  document.getElementById('error-help').hidden = !state.error;
  announcement.textContent = state.error ? '翻译失败' : busy ? (state.status || '正在翻译') : '';
  const languages = document.getElementById('languages'); languages.replaceChildren();
  if (state.from && state.to) {
    const direction = document.createElement('span'); direction.className = 'direction'; direction.setAttribute('aria-hidden', 'true'); direction.textContent = '→';
    languages.append(document.createTextNode(state.from), direction, document.createTextNode(state.to));
  } else languages.textContent = '截图翻译';
  const model = document.getElementById('model'); model.textContent = state.model || '设置模型'; model.dataset.tooltip = state.model || '请求设置';
  current = state;
  if (state.image && String(state.image).startsWith('data:image/png;base64,')) { image.src = state.image; canvas.hidden = false; }
  labels.replaceChildren();
  (state.blocks || []).forEach(block => {
    const el = document.createElement('span'); el.className = 'region'; el.tabIndex = 0; el.textContent = block.text;
    for (const key of ['left', 'top', 'width', 'height']) el.style[key] = block[key] + '%';
    el.style.background = block.background; el.style.color = block.color; labels.append(el);
  });
  compare(false); fit();
} };
image.addEventListener('load', fit); new ResizeObserver(fit).observe(viewport);
original.addEventListener('click', () => compare(!comparing));
copy.addEventListener('click', async () => {
  const seq = sequence;
  try {
    if (await api('copy_text', current && current.text || '') && seq === sequence) {
      copy.classList.add('is-copied'); copy.dataset.tooltip = '已复制'; announcement.textContent = '已复制';
      copyTimer = setTimeout(resetCopy, 1400);
    }
  } catch (_) { announcement.textContent = '复制失败'; }
});
retry.addEventListener('click', () => api('retry'));
document.getElementById('close').addEventListener('click', () => api('hide'));
document.getElementById('model').addEventListener('click', () => api('open_settings'));
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') api('hide');
  // Buttons retain their normal Space action. Compare while the image has focus.
  if (e.code === 'Space' && !e.repeat && !e.target.closest('button') && !original.disabled) { e.preventDefault(); compare(true); }
});
document.addEventListener('keyup', e => { if (e.code === 'Space' && !e.target.closest('button')) { e.preventDefault(); compare(false); } });
window.addEventListener('blur', () => compare(false));
document.querySelector('.head').addEventListener('mousedown', e => { if (e.button === 0 && !e.target.closest('button')) api('begin_drag'); });
document.querySelector('.foot').addEventListener('click', e => {
  const button = e.target.closest('.iconbtn'); if (!button || button.disabled) return;
  clearTimeout(button.feedbackTimer); button.classList.add('is-clicked');
  button.feedbackTimer = setTimeout(() => button.classList.remove('is-clicked'), 180);
});
for (const edge of ['n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se']) {
  const handle = document.createElement('div'); handle.className = 'resize resize-' + edge; handle.setAttribute('aria-hidden', 'true');
  handle.addEventListener('pointerdown', e => { if (e.button !== 0) return; e.preventDefault(); api('begin_resize', edge); }); document.body.append(handle);
}
window.addEventListener('pointerup', () => api('end_resize'));
window.addEventListener('pywebviewready', () => api('mark_ready'));
