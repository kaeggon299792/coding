(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const CLOSE_DURATION = 120;
  let openSelect = null;
  let nextId = 0;

  function createIcon(name) {
    const paths = name === "check"
      ? [["path", {d: "m20 6-11 11-5-5"}]]
      : [["path", {d: "m6 9 6 6 6-6"}]];
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("ui-icon", `ui-icon-${name}`);
    paths.forEach(([tag, attributes]) => {
      const node = document.createElementNS(SVG_NS, tag);
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
      svg.append(node);
    });
    return svg;
  }

  function enhanceSelect(root) {
    const native = root.querySelector("[data-vega-select-native]");
    if (!native || native.dataset.vegaSelectReady === "true") return;

    const id = ++nextId;
    const triggerId = `vega-select-trigger-${id}`;
    const listboxId = `vega-select-listbox-${id}`;
    const valueId = `vega-select-value-${id}`;
    const label = native.id ? document.querySelector(`label[for="${CSS.escape(native.id)}"]`) : null;
    if (label && !label.id) label.id = `vega-select-label-${id}`;

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.id = triggerId;
    trigger.className = "vega-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", listboxId);
    trigger.disabled = native.disabled;

    const value = document.createElement("span");
    value.id = valueId;
    value.className = "vega-select-value";
    trigger.append(value, createIcon("chevron-down"));
    trigger.setAttribute("aria-labelledby", label ? `${label.id} ${valueId}` : valueId);

    const listbox = document.createElement("div");
    listbox.id = listboxId;
    listbox.className = "vega-select-content";
    listbox.setAttribute("role", "listbox");
    listbox.setAttribute("tabindex", "-1");
    listbox.setAttribute("aria-labelledby", label ? label.id : valueId);
    listbox.dataset.state = "closed";
    listbox.hidden = true;
    document.body.append(listbox);

    const items = Array.from(native.options).map((option, index) => {
      const item = document.createElement("div");
      item.id = `${listboxId}-option-${index}`;
      item.className = "vega-select-option";
      item.setAttribute("role", "option");
      item.setAttribute("tabindex", "-1");
      item.setAttribute("aria-selected", option.selected ? "true" : "false");
      if (option.disabled) item.setAttribute("aria-disabled", "true");
      item.dataset.value = option.value;
      item.dataset.index = String(index);
      item.append(createIcon("check"), document.createTextNode(option.textContent.trim()));
      listbox.append(item);
      return item;
    });

    let activeIndex = Math.max(0, native.selectedIndex);
    let closeTimer = null;

    function sync() {
      const selectedIndex = Math.max(0, native.selectedIndex);
      activeIndex = selectedIndex;
      value.textContent = native.options[selectedIndex]?.textContent.trim() || "";
      items.forEach((item, index) => {
        item.setAttribute("aria-selected", index === selectedIndex ? "true" : "false");
      });
    }

    function setActive(index, shouldFocus = false) {
      const enabled = items
        .map((item, itemIndex) => item.getAttribute("aria-disabled") === "true" ? -1 : itemIndex)
        .filter((itemIndex) => itemIndex >= 0);
      if (!enabled.length) return;
      const normalized = enabled.includes(index) ? index : enabled[0];
      activeIndex = normalized;
      items.forEach((item, itemIndex) => item.classList.toggle("is-active", itemIndex === normalized));
      listbox.setAttribute("aria-activedescendant", items[normalized].id);
      if (shouldFocus) items[normalized].focus({preventScroll: true});
      items[normalized].scrollIntoView({block: "nearest"});
    }

    function moveActive(delta) {
      const enabled = items
        .map((item, itemIndex) => item.getAttribute("aria-disabled") === "true" ? -1 : itemIndex)
        .filter((itemIndex) => itemIndex >= 0);
      if (!enabled.length) return;
      const current = enabled.indexOf(activeIndex);
      const next = enabled[(current + delta + enabled.length) % enabled.length];
      setActive(next, true);
    }

    function positionListbox() {
      if (listbox.hidden) return;
      const gap = 5;
      const edge = 8;
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(Math.max(rect.width, 164), window.innerWidth - edge * 2);
      listbox.style.width = `${width}px`;
      listbox.style.maxHeight = `${Math.max(80, window.innerHeight - edge * 2)}px`;
      const contentHeight = listbox.offsetHeight;
      const spaceBelow = window.innerHeight - rect.bottom - edge;
      const spaceAbove = rect.top - edge;
      const side = spaceBelow < Math.min(contentHeight + gap, 180) && spaceAbove > spaceBelow
        ? "top"
        : "bottom";
      const available = side === "top" ? spaceAbove - gap : spaceBelow - gap;
      listbox.style.maxHeight = `${Math.max(80, available)}px`;
      const measuredHeight = Math.min(listbox.scrollHeight, Math.max(80, available));
      const top = side === "top" ? rect.top - measuredHeight - gap : rect.bottom + gap;
      const left = Math.min(Math.max(edge, rect.left), window.innerWidth - width - edge);
      listbox.dataset.side = side;
      listbox.style.setProperty("--vega-transform-origin", side === "top" ? "bottom center" : "top center");
      listbox.style.top = `${Math.max(edge, top)}px`;
      listbox.style.left = `${left}px`;
    }

    function close({restoreFocus = false, immediate = false} = {}) {
      if (trigger.getAttribute("aria-expanded") !== "true" && listbox.hidden) return;
      clearTimeout(closeTimer);
      trigger.setAttribute("aria-expanded", "false");
      listbox.dataset.state = "closed";
      items.forEach((item) => item.classList.remove("is-active"));
      if (openSelect?.root === root) openSelect = null;
      const finish = () => {
        listbox.hidden = true;
        if (restoreFocus) trigger.focus({preventScroll: true});
      };
      if (immediate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
      else closeTimer = window.setTimeout(finish, CLOSE_DURATION);
    }

    function open({focusOption = false} = {}) {
      if (native.disabled) return;
      if (openSelect && openSelect.root !== root) openSelect.close({immediate: true});
      clearTimeout(closeTimer);
      listbox.hidden = false;
      listbox.dataset.state = "closed";
      trigger.setAttribute("aria-expanded", "true");
      openSelect = {root, trigger, listbox, close};
      sync();
      positionListbox();
      requestAnimationFrame(() => {
        listbox.dataset.state = "open";
        setActive(native.selectedIndex, focusOption);
      });
    }

    function selectIndex(index) {
      const option = native.options[index];
      if (!option || option.disabled) return;
      native.value = option.value;
      sync();
      close({restoreFocus: true, immediate: true});
      native.dispatchEvent(new Event("input", {bubbles: true}));
      native.dispatchEvent(new Event("change", {bubbles: true}));
    }

    trigger.addEventListener("click", () => {
      if (trigger.getAttribute("aria-expanded") === "true") close({restoreFocus: true});
      else open();
    });

    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        if (trigger.getAttribute("aria-expanded") !== "true") open({focusOption: true});
        else moveActive(event.key === "ArrowDown" ? 1 : -1);
      } else if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        if (trigger.getAttribute("aria-expanded") === "true") close({restoreFocus: true});
        else open({focusOption: true});
      } else if (event.key === "Escape") {
        event.preventDefault();
        close({restoreFocus: true});
      }
    });

    listbox.addEventListener("click", (event) => {
      const item = event.target.closest(".vega-select-option");
      if (item) selectIndex(Number(item.dataset.index));
    });

    listbox.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        moveActive(event.key === "ArrowDown" ? 1 : -1);
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        const index = event.key === "Home" ? 0 : items.length - 1;
        setActive(index, true);
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIndex(activeIndex);
      } else if (event.key === "Escape") {
        event.preventDefault();
        close({restoreFocus: true});
      } else if (event.key === "Tab") {
        close({immediate: true});
      }
    });

    native.addEventListener("change", sync);
    native.form?.addEventListener("reset", () => window.setTimeout(sync));
    root.append(trigger);
    root.classList.add("is-enhanced");
    native.dataset.vegaSelectReady = "true";
    native.setAttribute("aria-hidden", "true");
    native.tabIndex = -1;
    if (label) label.htmlFor = triggerId;
    sync();
  }

  function closeFromOutside(event) {
    if (!openSelect) return;
    if (openSelect.root.contains(event.target) || openSelect.listbox.contains(event.target)) return;
    openSelect.close({immediate: true});
  }

  function repositionOpenSelect() {
    if (!openSelect) return;
    const trigger = openSelect.trigger;
    const listbox = openSelect.listbox;
    const rect = trigger.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      openSelect.close({immediate: true});
      return;
    }
    const gap = 5;
    const edge = 8;
    const width = Math.min(Math.max(rect.width, 164), window.innerWidth - edge * 2);
    const spaceBelow = window.innerHeight - rect.bottom - edge;
    const spaceAbove = rect.top - edge;
    const contentHeight = listbox.scrollHeight;
    const side = spaceBelow < Math.min(contentHeight + gap, 180) && spaceAbove > spaceBelow ? "top" : "bottom";
    const available = Math.max(80, (side === "top" ? spaceAbove : spaceBelow) - gap);
    const height = Math.min(contentHeight, available);
    listbox.style.width = `${width}px`;
    listbox.style.maxHeight = `${available}px`;
    listbox.style.left = `${Math.min(Math.max(edge, rect.left), window.innerWidth - width - edge)}px`;
    listbox.style.top = `${Math.max(edge, side === "top" ? rect.top - height - gap : rect.bottom + gap)}px`;
    listbox.dataset.side = side;
    listbox.style.setProperty("--vega-transform-origin", side === "top" ? "bottom center" : "top center");
  }

  function init() {
    document.querySelectorAll("[data-vega-select]").forEach(enhanceSelect);
    document.addEventListener("pointerdown", closeFromOutside);
    window.addEventListener("resize", repositionOpenSelect, {passive: true});
    window.addEventListener("scroll", repositionOpenSelect, {passive: true, capture: true});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once: true});
  else init();
})();
