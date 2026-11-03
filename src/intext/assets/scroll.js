/* Overlay scrollbar. macOS draws no track and no arrows. The thumb is a thin
   translucent capsule that appears while scrolling and fades out. */
(function () {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const style = document.createElement("style");
  style.textContent = [
    "* { scrollbar-width: none; }",
    "*::-webkit-scrollbar { width: 0; height: 0; display: none; background: transparent; }",
    ".mac-thumb {",
    "  position: fixed;",
    "  z-index: 40;",
    "  border-radius: 999px;",
    "  background: var(--scroll-thumb);",
    "  opacity: 0;",
    "  pointer-events: none;",
    "  transition: opacity 520ms ease, background 160ms ease;",
    "}",
    ".mac-thumb.is-on { opacity: 1; pointer-events: auto; transition-duration: 80ms, 160ms; }",
    ".mac-thumb.is-hot { background: var(--scroll-thumb-hot); }",
    "@media (prefers-reduced-motion: reduce) { .mac-thumb { transition: none; } }"
  ].join("\n");
  document.head.appendChild(style);

  function mount(scroller, options) {
    if (!scroller) return;
    const inset = (options && options.inset) || 4;
    const size = (options && options.size) || 4;
    const endInset = (options && options.endInset) || 14;
    const y = document.createElement("div");
    const x = document.createElement("div");
    y.className = "mac-thumb";
    x.className = "mac-thumb";
    y.setAttribute("aria-hidden", "true");
    x.setAttribute("aria-hidden", "true");
    const layer = String((options && options.layer) || 40);
    y.style.zIndex = layer;
    x.style.zIndex = layer;
    document.body.append(y, x);

    let frame = 0;
    let hideTimer = 0;
    let dragging = null;

    function axis(name) {
      const rect = scroller.getBoundingClientRect();
      const vertical = name === "y";
      const overflow = vertical
        ? scroller.scrollHeight - scroller.clientHeight
        : scroller.scrollWidth - scroller.clientWidth;
      const span = vertical ? rect.height : rect.width;
      const track = Math.max(0, span - endInset * 2);
      const view = vertical ? scroller.clientHeight : scroller.clientWidth;
      const total = vertical ? scroller.scrollHeight : scroller.scrollWidth;
      const thumb = total > 0 ? Math.max(28, Math.min(track, track * (view / total))) : track;
      const travel = Math.max(1, track - thumb);
      const pos = overflow > 1 ? ((vertical ? scroller.scrollTop : scroller.scrollLeft) / overflow) * travel : 0;
      return { rect, overflow, thumb, travel, pos };
    }

    function place() {
      const yM = axis("y");
      const xM = axis("x");
      if (yM.overflow > 4 && yM.rect.width > 0 && yM.rect.height > 0) {
        y.hidden = false;
        y.style.width = size + "px";
        y.style.height = Math.round(yM.thumb) + "px";
        y.style.left = Math.round(yM.rect.right - size - inset) + "px";
        y.style.top = Math.round(yM.rect.top + endInset + yM.pos) + "px";
      } else {
        y.hidden = true;
        y.classList.remove("is-on", "is-hot");
      }
      if (xM.overflow > 4 && xM.rect.width > 0 && xM.rect.height > 0) {
        x.hidden = false;
        x.style.height = size + "px";
        x.style.width = Math.round(xM.thumb) + "px";
        x.style.top = Math.round(xM.rect.bottom - size - inset) + "px";
        x.style.left = Math.round(xM.rect.left + endInset + xM.pos) + "px";
      } else {
        x.hidden = true;
        x.classList.remove("is-on", "is-hot");
      }
    }

    function schedulePlace() {
      if (frame) return;
      frame = requestAnimationFrame(function () {
        frame = 0;
        place();
      });
    }

    function show() {
      place();
      if (!y.hidden) y.classList.add("is-on");
      if (!x.hidden) x.classList.add("is-on");
      clearTimeout(hideTimer);
    }

    function scheduleHide() {
      clearTimeout(hideTimer);
      if (dragging) return;
      hideTimer = setTimeout(function () {
        if (dragging) return;
        y.classList.remove("is-on", "is-hot");
        x.classList.remove("is-on", "is-hot");
      }, reduced ? 0 : 520);
    }

    scroller.addEventListener("scroll", function () {
      show();
      scheduleHide();
    }, { passive: true });
    document.addEventListener("scroll", schedulePlace, true);
    window.addEventListener("resize", schedulePlace);
    if (window.ResizeObserver) new ResizeObserver(schedulePlace).observe(scroller);
    if (window.MutationObserver) {
      new MutationObserver(schedulePlace).observe(scroller, { childList: true, subtree: true, characterData: true });
    }

    function bindDrag(thumb, name) {
      thumb.addEventListener("click", function (event) { event.stopPropagation(); });
      thumb.addEventListener("pointerdown", function (event) {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const m = axis(name);
        dragging = {
          name: name,
          start: name === "y" ? event.clientY : event.clientX,
          scroll: name === "y" ? scroller.scrollTop : scroller.scrollLeft,
          travel: m.travel,
          overflow: m.overflow
        };
        thumb.classList.add("is-hot");
        try { thumb.setPointerCapture(event.pointerId); } catch (e) {}
        show();
      });
      thumb.addEventListener("pointermove", function (event) {
        if (!dragging || dragging.name !== name) return;
        const delta = (name === "y" ? event.clientY : event.clientX) - dragging.start;
        const next = dragging.scroll + delta * (dragging.overflow / dragging.travel);
        if (name === "y") scroller.scrollTop = next;
        else scroller.scrollLeft = next;
      });
      function end() {
        if (!dragging || dragging.name !== name) return;
        dragging = null;
        thumb.classList.remove("is-hot");
        scheduleHide();
      }
      thumb.addEventListener("pointerup", end);
      thumb.addEventListener("pointercancel", end);
      thumb.addEventListener("lostpointercapture", end);
    }
    bindDrag(y, "y");
    bindDrag(x, "x");
    function bindWheel(thumb) {
      thumb.addEventListener("wheel", function (event) {
        if (thumb.hidden) return;
        event.preventDefault();
        scroller.scrollTop += event.deltaY || 0;
        scroller.scrollLeft += event.deltaX || 0;
        show();
        scheduleHide();
      }, { passive: false });
    }
    bindWheel(y);
    bindWheel(x);
    function bindHover(thumb) {
      thumb.addEventListener("pointerenter", function () {
        clearTimeout(hideTimer);
        show();
      });
      thumb.addEventListener("pointerleave", function () {
        if (!dragging) scheduleHide();
      });
    }
    bindHover(y);
    bindHover(x);
    schedulePlace();
  }


  const interactive = "input, textarea, select, option, button, a, .code, .resize, .choice, .switch, .keycap, .menu-pop, .result, .source, .content, .tip, .mac-thumb";
  document.addEventListener("dragstart", function (event) {
    event.preventDefault();
  });
  document.addEventListener("mousedown", function (event) {
    if (event.button !== 0) return;
    const target = event.target;
    if (!target || !target.closest) return;
    if (target.closest(interactive)) return;
    if (!target.closest(".sheet, .head, .glass, .stage")) return;
    event.preventDefault();
    const api = window.pywebview && window.pywebview.api;
    if (api && api.begin_drag) api.begin_drag();
  });

  window.intextScroll = { mount: mount };
})();
