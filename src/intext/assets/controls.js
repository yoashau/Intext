/* One tooltip surface for help text and action labels on both pages. */
(function () {
  window.intextControls = {
    languageArrow(bidirectional = false) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 20 20");
      svg.setAttribute("aria-hidden", "true");
      svg.classList.add("translation-arrow");
      // Both directions use the same softly rounded arrowhead.
      const path = "M3.5 10h12.3M13.5 7.5l2.15 2.15q.35.35 0 .7L13.5 12.5";
      for (let index = 0; index < (bidirectional ? 2 : 1); index++) {
        const stroke = document.createElementNS(svg.namespaceURI, "path");
        stroke.setAttribute("d", path);
        if (bidirectional) stroke.setAttribute("transform", index ? "translate(0 3.5) rotate(180 10 10)" : "translate(0 -3.5)");
        svg.append(stroke);
      }
      return svg;
    },
    moveFocus(anchor, backward) {
      const items = Array.from(document.querySelectorAll("button, input, textarea, select, a[href], [tabindex]"))
        .filter(node => node.tabIndex >= 0 && !node.disabled && node.getClientRects().length && getComputedStyle(node).visibility !== "hidden");
      const index = items.indexOf(anchor);
      const next = items[(index + (backward ? -1 : 1) + items.length) % items.length];
      if (next) next.focus();
    }
  };
  const tooltip = document.createElement("div");
  tooltip.id = "tooltip";
  tooltip.className = "tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.append(tooltip);
  let owner = null;
  let timer = 0;
  let keyboardNavigation = false;
  let hoveredOwner = null;
  let lastPointerEntry = 0;

  // WebView restores focus when a native window opens, even for a tray click.
  // :focus-visible alone also matches that programmatic focus.
  document.addEventListener("keydown", function (event) {
    if (!event.isComposing && !event.altKey && !event.ctrlKey && !event.metaKey &&
        ["Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) {
      keyboardNavigation = true;
    }
  }, true);
  document.addEventListener("pointerdown", function () { keyboardNavigation = false; }, true);

  function hide() {
    clearTimeout(timer);
    tooltip.hidden = true;
    tooltip.classList.remove("is-scrollable");
    if (owner) {
      const ids = (owner.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== tooltip.id);
      if (ids.length) owner.setAttribute("aria-describedby", ids.join(" "));
      else owner.removeAttribute("aria-describedby");
    }
    owner = null;
  }

  function show(button) {
    if (owner !== button || !button.isConnected || button.disabled ||
        document.visibilityState === "hidden") return;
    const source = button.querySelector(".tip");
    const text = source ? source.textContent.trim() : button.dataset.tooltip;
    if (!text) { hide(); return; }
    const rect = button.getBoundingClientRect();
    if (rect.bottom <= 0 || rect.top >= innerHeight) { hide(); return; }
    tooltip.textContent = text;
    tooltip.classList.remove("is-scrollable");
    tooltip.scrollTop = 0;
    tooltip.hidden = false;
    tooltip.classList.toggle("is-scrollable", tooltip.scrollHeight > tooltip.clientHeight + 1);
    const bounds = tooltip.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, innerWidth - bounds.width - 8));
    const below = rect.bottom + 6;
    const top = below + bounds.height <= innerHeight - 8 ? below : rect.top - bounds.height - 6;
    tooltip.style.left = left + "px";
    tooltip.style.top = Math.max(8, Math.min(top, innerHeight - bounds.height - 8)) + "px";
    const ids = (button.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
    if (!ids.includes(tooltip.id)) ids.push(tooltip.id);
    button.setAttribute("aria-describedby", ids.join(" "));
  }

  function target(event) {
    return event.target.closest(".help, [data-tooltip]");
  }

  function keyboardOwnsTooltip() {
    return !!owner && keyboardNavigation && document.hasFocus() &&
      document.activeElement === owner && owner.matches(":focus-visible");
  }

  document.addEventListener("pointerover", function (event) {
    const button = target(event);
    if (!button || button.disabled) return;
    hoveredOwner = button;
    lastPointerEntry = Date.now();
    // Moving onto a child (the ? glyph, for example) must not cancel a
    // pending show. Only cancel a pending hide for an already visible tip.
    if (button === owner) { if (!tooltip.hidden) clearTimeout(timer); return; }
    hide();
    owner = button;
    timer = setTimeout(function () { show(button); }, 280);
  });
  document.addEventListener("pointerout", function (event) {
    if (hoveredOwner && hoveredOwner.contains(event.target) &&
        (!event.relatedTarget || !hoveredOwner.contains(event.relatedTarget))) hoveredOwner = null;
    if (owner && owner.contains(event.target) && (!event.relatedTarget || !owner.contains(event.relatedTarget))) {
      if (keyboardOwnsTooltip()) return;
      if (!tooltip.hidden && tooltip.classList.contains("is-scrollable")) {
        clearTimeout(timer);
        timer = setTimeout(hide, 180);
      } else hide();
    }
  });
  tooltip.addEventListener("pointerenter", function () { clearTimeout(timer); });
  tooltip.addEventListener("pointerleave", function (event) {
    if (keyboardOwnsTooltip() || (owner && event.relatedTarget && owner.contains(event.relatedTarget))) return;
    hide();
  });
  document.addEventListener("focusin", function (event) {
    const button = target(event);
    if (!button || !keyboardNavigation || !document.hasFocus() || !button.matches(":focus-visible")) return;
    hide();
    owner = button;
    show(button);
  });
  document.addEventListener("focusout", function (event) {
    if (owner === event.target && hoveredOwner !== owner &&
        !(tooltip.classList.contains("is-scrollable") && tooltip.matches(":hover"))) hide();
  });
  document.addEventListener("pointerdown", function (event) {
    if (tooltip.classList.contains("is-scrollable") && tooltip.contains(event.target)) return;
    hide();
    if (event.button !== 0) return;
    const focused = document.activeElement;
    if (focused && focused.matches(".help")) focused.blur();
    // Help has no click action. Mouse focus must not latch its tooltip open.
    if (event.target.closest(".help")) event.preventDefault();
  });
  document.addEventListener("keydown", function (event) {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape" && !tooltip.hidden) {
      event.preventDefault();
      event.stopImmediatePropagation();
      hide();
      return;
    }
    if (tooltip.hidden || !tooltip.classList.contains("is-scrollable") || document.activeElement !== owner) return;
    const steps = { ArrowDown: 32, ArrowUp: -32, PageDown: tooltip.clientHeight - 24, PageUp: 24 - tooltip.clientHeight };
    if (Object.hasOwn(steps, event.key)) {
      event.preventDefault();
      tooltip.scrollTop += steps[event.key];
    }
  });
  document.addEventListener("scroll", function (event) { if (event.target !== tooltip) hide(); }, true);
  function deactivate() {
    keyboardNavigation = false;
    hide();
  }
  window.intextControls.resetTooltip = function (requestedAt) {
    keyboardNavigation = false;
    // WebView2 may run the native reset after a newer mouse entry has
    // already arrived. Keep that user's hover; clear only older state.
    if (typeof requestedAt === "number" && lastPointerEntry >= requestedAt &&
        hoveredOwner && hoveredOwner === owner && document.visibilityState === "visible") return;
    hide();
  };
  window.addEventListener("blur", deactivate);
  window.addEventListener("pagehide", deactivate);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") deactivate();
  });
  window.addEventListener("resize", hide);
  new MutationObserver(function () {
    if (!owner) return;
    const source = owner.querySelector(".tip");
    const text = source ? source.textContent.trim() : owner.dataset.tooltip;
    if (!owner.isConnected || owner.disabled || !owner.getClientRects().length || !text) hide();
    else if (!tooltip.hidden && text !== tooltip.textContent) show(owner);
  }).observe(document.body, { subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: ["hidden", "disabled", "data-tooltip"] });
})();
