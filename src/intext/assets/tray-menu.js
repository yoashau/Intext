const buttons = [...document.querySelectorAll('[data-action]')];
const startup = document.querySelector('[data-action="startup"]');
function bridge() { return window.pywebview && window.pywebview.api; }
const menu = document.querySelector('.menu');
let entrance = null;
let entranceFrame = 0;
function applyState(state) {
  startup.setAttribute('aria-checked', state.startup ? 'true' : 'false');
  if (state.error) {
    startup.setAttribute('aria-invalid', 'true');
    startup.dataset.tooltip = state.error;
  } else {
    startup.removeAttribute('aria-invalid');
    delete startup.dataset.tooltip;
  }
  document.querySelector('#announcement').textContent = state.error || '';
}
function closeMenu() {
  cancelAnimationFrame(entranceFrame);
  entranceFrame = 0;
  if (entrance) entrance.cancel();
  entrance = null;
  menu.style.opacity = '';
}
function openMenu(state) {
  closeMenu();
  applyState(state);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    menu.style.opacity = '1';
    return;
  }
  // Hidden WebViews defer this frame until the native window is visible.
  entranceFrame = requestAnimationFrame(() => {
    entranceFrame = 0;
    const offset = state.openSide === 'left' ? 4 : -4;
    entrance = menu.animate([
      { opacity: 0, transform: `translate3d(${offset}px, 0, 0)` },
      { opacity: 1, transform: 'translate3d(0, 0, 0)' }
    ], { duration: 140, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)', fill: 'both' });
  });
}
window.intextTray = { apply: applyState, open: openMenu, close: closeMenu };

buttons.forEach(button => button.addEventListener('click', async () => {
  const api = bridge();
  if (!api || !api.activate || button.disabled) return;
  buttons.forEach(item => item.disabled = true);
  try {
    const state = await api.activate(button.dataset.action);
    if (state) intextTray.apply(state);
  } finally { buttons.forEach(item => item.disabled = false); }
}));
document.addEventListener('keydown', event => {
  const api = bridge();
  if (event.key === 'Escape') { if (api) api.hide(); return; }
  let index = buttons.indexOf(document.activeElement);
  if (event.key === 'ArrowDown') index = (index + 1) % buttons.length;
  else if (event.key === 'ArrowUp') index = index < 0 ? buttons.length - 1 : (index - 1 + buttons.length) % buttons.length;
  else if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = buttons.length - 1;
  else if (event.key === 'Tab') { event.preventDefault(); if (api) api.hide(); return; }
  else return;
  event.preventDefault(); buttons[index].focus();
});
document.addEventListener('pointerdown', event => { if (!event.target.closest('.menu') && bridge()) bridge().hide(); });
