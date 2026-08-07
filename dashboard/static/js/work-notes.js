(function () {
  "use strict";

  var form = document.querySelector("[data-work-note-form]");
  if (!form) return;
  var textarea = form.querySelector("#work-note-content");
  var status = form.querySelector("[data-autosave-status]");
  var recurrence = form.querySelector("[data-recurrence-select]");
  var customRecurrence = form.querySelector("[data-custom-recurrence]");
  var draftKey = form.dataset.draftKey;
  var dirty = false;

  function setStatus(message) {
    if (status) status.textContent = message;
  }

  function serialize() {
    var data = {};
    new FormData(form).forEach(function (value, key) {
      if (value instanceof File) return;
      data[key] = value;
    });
    form.querySelectorAll('input[type="checkbox"][name]').forEach(function (field) {
      data[field.name] = field.checked ? field.value : "";
    });
    return data;
  }

  function restore(data) {
    Object.keys(data || {}).forEach(function (name) {
      var field = form.elements.namedItem(name);
      if (!field || field.type === "file" || name === "csrf_token") return;
      if (field.type === "checkbox") field.checked = data[name] === field.value;
      else field.value = data[name];
    });
    syncRecurrence();
  }

  function saveDraft() {
    if (!dirty) return;
    try {
      localStorage.setItem(draftKey, JSON.stringify({ savedAt: Date.now(), data: serialize() }));
      dirty = false;
      setStatus("자동저장됨 · " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
    } catch (_error) {
      setStatus("자동저장 공간이 부족합니다.");
    }
  }

  try {
    var stored = JSON.parse(localStorage.getItem(draftKey) || "null");
    if (stored && stored.data && window.confirm("자동저장된 작성 내용을 불러올까요?")) {
      restore(stored.data);
      setStatus("자동저장 내용을 복원했습니다.");
    }
  } catch (_error) {
    localStorage.removeItem(draftKey);
  }

  form.addEventListener("input", function () {
    dirty = true;
    setStatus("변경사항 있음 · 2분마다 자동저장");
  });
  form.addEventListener("submit", function () { localStorage.removeItem(draftKey); });
  window.setInterval(saveDraft, 120000);

  function syncRecurrence() {
    if (!customRecurrence || !recurrence) return;
    customRecurrence.hidden = recurrence.value !== "custom";
    var input = customRecurrence.querySelector("input");
    if (input) input.required = recurrence.value === "custom";
  }
  recurrence && recurrence.addEventListener("change", syncRecurrence);
  syncRecurrence();

  form.querySelectorAll("[data-clear-field]").forEach(function (button) {
    button.addEventListener("click", function () {
      var field = form.elements.namedItem(button.dataset.clearField);
      if (!field) return;
      field.value = "";
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.focus();
    });
  });

})();
