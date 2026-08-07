(function () {
  "use strict";

  var MONTHS = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"];
  var WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function toISO(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function fromISO(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
    if (!match) return null;
    var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return toISO(date) === value ? date : null;
  }

  function startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function addDays(date, amount) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate() + amount);
  }

  function createButton(text, className, label) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = text;
    if (label) button.setAttribute("aria-label", label);
    return button;
  }

  document.querySelectorAll("[data-diary-date-button]").forEach(function (trigger, index) {
    var wrapper = trigger.closest(".diary-date-picker");
    var input = wrapper && wrapper.querySelector("[data-diary-date]");
    var label = trigger.querySelector("[data-diary-date-label]");
    if (!input || !label) return;

    var today = new Date();
    var selected = fromISO(input.value);
    var view = startOfMonth(selected || today);
    var popup = document.createElement("div");
    var popupId = "diary-calendar-" + index;
    popup.id = popupId;
    popup.className = "diary-calendar-popover";
    popup.setAttribute("role", "dialog");
    popup.setAttribute("aria-label", "날짜 선택");
    popup.hidden = true;
    trigger.setAttribute("aria-controls", popupId);

    var header = document.createElement("div");
    header.className = "diary-calendar-caption";
    var previous = createButton("‹", "diary-calendar-nav", "이전 달");
    var caption = document.createElement("div");
    caption.className = "diary-calendar-caption-selects";
    var yearSelect = document.createElement("select");
    yearSelect.setAttribute("aria-label", "연도");
    var monthSelect = document.createElement("select");
    monthSelect.setAttribute("aria-label", "월");
    MONTHS.forEach(function (month, monthIndex) {
      var option = document.createElement("option");
      option.value = String(monthIndex);
      option.textContent = month;
      monthSelect.appendChild(option);
    });
    var currentYear = today.getFullYear();
    for (var year = 1900; year <= currentYear + 10; year += 1) {
      var yearOption = document.createElement("option");
      yearOption.value = String(year);
      yearOption.textContent = year + "년";
      yearSelect.appendChild(yearOption);
    }
    caption.append(yearSelect, monthSelect);
    var next = createButton("›", "diary-calendar-nav", "다음 달");
    header.append(previous, caption, next);

    var weekdays = document.createElement("div");
    weekdays.className = "diary-calendar-weekdays";
    WEEKDAYS.forEach(function (weekday) {
      var cell = document.createElement("span");
      cell.textContent = weekday;
      weekdays.appendChild(cell);
    });
    var grid = document.createElement("div");
    grid.className = "diary-calendar-grid";
    grid.setAttribute("role", "grid");
    var footer = document.createElement("div");
    footer.className = "diary-calendar-footer";
    var todayButton = createButton("오늘", "diary-calendar-footer-button");
    var closeButton = createButton("닫기", "diary-calendar-footer-button");
    footer.append(todayButton, closeButton);
    popup.append(header, weekdays, grid, footer);
    document.body.appendChild(popup);

    wrapper.classList.add("is-calendar-enhanced");

    function syncLabel() {
      label.textContent = input.value || "날짜 선택";
    }

    function position() {
      if (popup.hidden) return;
      var rect = trigger.getBoundingClientRect();
      var gap = 6;
      var width = Math.min(310, window.innerWidth - 16);
      popup.style.width = width + "px";
      var left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
      var estimatedHeight = popup.offsetHeight || 350;
      var below = rect.bottom + gap;
      var top = below + estimatedHeight <= window.innerHeight - 8
        ? below
        : Math.max(8, rect.top - estimatedHeight - gap);
      popup.style.left = Math.round(left) + "px";
      popup.style.top = Math.round(top) + "px";
    }

    function selectDate(date) {
      selected = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      view = startOfMonth(selected);
      input.value = toISO(selected);
      syncLabel();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      close();
      trigger.focus({ preventScroll: true });
    }

    function render(focusISO) {
      yearSelect.value = String(view.getFullYear());
      monthSelect.value = String(view.getMonth());
      grid.replaceChildren();
      var first = startOfMonth(view);
      var gridStart = addDays(first, -first.getDay());
      var selectedISO = selected ? toISO(selected) : "";
      var todayISO = toISO(today);
      for (var cellIndex = 0; cellIndex < 42; cellIndex += 1) {
        var date = addDays(gridStart, cellIndex);
        var iso = toISO(date);
        var day = createButton(String(date.getDate()), "diary-calendar-day", iso);
        day.dataset.date = iso;
        day.setAttribute("role", "gridcell");
        day.tabIndex = iso === (focusISO || selectedISO || todayISO) ? 0 : -1;
        if (date.getMonth() !== view.getMonth()) day.classList.add("is-outside");
        if (iso === todayISO) day.classList.add("is-today");
        if (iso === selectedISO) {
          day.classList.add("is-selected");
          day.setAttribute("aria-selected", "true");
        }
        day.addEventListener("click", function (event) {
          selectDate(fromISO(event.currentTarget.dataset.date));
        });
        grid.appendChild(day);
      }
      position();
      if (focusISO) {
        var focusTarget = grid.querySelector('[data-date="' + focusISO + '"]');
        if (focusTarget) focusTarget.focus({ preventScroll: true });
      }
    }

    function open() {
      if (!popup.hidden) {
        close();
        return;
      }
      selected = fromISO(input.value);
      view = startOfMonth(selected || today);
      popup.hidden = false;
      popup.dataset.state = "open";
      trigger.setAttribute("aria-expanded", "true");
      render();
      requestAnimationFrame(position);
    }

    function close() {
      popup.hidden = true;
      delete popup.dataset.state;
      trigger.setAttribute("aria-expanded", "false");
    }

    function moveMonth(amount) {
      view = new Date(view.getFullYear(), view.getMonth() + amount, 1);
      render();
    }

    previous.addEventListener("click", function () { moveMonth(-1); });
    next.addEventListener("click", function () { moveMonth(1); });
    yearSelect.addEventListener("change", function () {
      view = new Date(Number(yearSelect.value), view.getMonth(), 1);
      render();
    });
    monthSelect.addEventListener("change", function () {
      view = new Date(view.getFullYear(), Number(monthSelect.value), 1);
      render();
    });
    todayButton.addEventListener("click", function () { selectDate(today); });
    closeButton.addEventListener("click", function () {
      close();
      trigger.focus({ preventScroll: true });
    });
    trigger.addEventListener("click", open);
    grid.addEventListener("keydown", function (event) {
      var active = event.target.closest("[data-date]");
      if (!active) return;
      var date = fromISO(active.dataset.date);
      var nextDate = null;
      if (event.key === "ArrowLeft") nextDate = addDays(date, -1);
      if (event.key === "ArrowRight") nextDate = addDays(date, 1);
      if (event.key === "ArrowUp") nextDate = addDays(date, -7);
      if (event.key === "ArrowDown") nextDate = addDays(date, 7);
      if (event.key === "Home") nextDate = addDays(date, -date.getDay());
      if (event.key === "End") nextDate = addDays(date, 6 - date.getDay());
      if (event.key === "PageUp") nextDate = new Date(date.getFullYear(), date.getMonth() - 1, date.getDate());
      if (event.key === "PageDown") nextDate = new Date(date.getFullYear(), date.getMonth() + 1, date.getDate());
      if (!nextDate) return;
      event.preventDefault();
      view = startOfMonth(nextDate);
      render(toISO(nextDate));
    });
    document.addEventListener("pointerdown", function (event) {
      if (!popup.hidden && !popup.contains(event.target) && !trigger.contains(event.target)) close();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !popup.hidden) {
        close();
        trigger.focus({ preventScroll: true });
      }
    });
    window.addEventListener("resize", position, { passive: true });
    window.addEventListener("scroll", position, { passive: true });
    syncLabel();
  });

  document.querySelectorAll("[data-diary-timeline-excerpt]").forEach(function (wrapper) {
    var content = wrapper.querySelector(".community-markdown");
    var button = wrapper.querySelector("[data-diary-timeline-expand]");
    var label = button && button.querySelector("[data-diary-timeline-expand-label]");
    if (!content || !button || !label) return;

    function syncCollapsibleState() {
      var limit = parseFloat(getComputedStyle(wrapper).getPropertyValue("--diary-timeline-collapse-height")) || 360;
      var collapsible = content.scrollHeight > limit + 8;
      wrapper.classList.toggle("is-collapsible", collapsible);
      button.hidden = !collapsible;
      if (!collapsible) {
        wrapper.classList.remove("is-expanded");
        button.setAttribute("aria-expanded", "false");
        label.textContent = "전체 보기";
      }
    }

    button.addEventListener("click", function () {
      var expanded = wrapper.classList.toggle("is-expanded");
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
      label.textContent = expanded ? "접기" : "전체 보기";
      if (!expanded) wrapper.scrollIntoView({ block: "nearest", behavior: "auto" });
    });

    syncCollapsibleState();
    if (typeof ResizeObserver === "function") {
      var observer = new ResizeObserver(syncCollapsibleState);
      observer.observe(content);
    } else {
      window.addEventListener("load", syncCollapsibleState, { once: true });
    }
  });
})();
