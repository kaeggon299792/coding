(function () {
  "use strict";

  var form = document.querySelector("[data-work-note-form]");
  if (!form) return;
  var textarea = form.querySelector("#work-note-content");
  var status = form.querySelector("[data-autosave-status]");
  var preview = form.querySelector("[data-markdown-preview]");
  var previewDialog = form.querySelector("[data-work-note-preview-dialog]");
  var previewOpen = form.querySelector("[data-work-note-preview-open]");
  var previewClose = form.querySelector("[data-work-note-preview-close]");
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

  function replaceSelection(before, after, placeholder) {
    var start = textarea.selectionStart || 0;
    var end = textarea.selectionEnd || start;
    var selected = textarea.value.slice(start, end) || placeholder;
    var value = before + selected + after;
    textarea.setRangeText(value, start, end, "select");
    textarea.selectionStart = start + before.length;
    textarea.selectionEnd = start + before.length + selected.length;
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  var snippets = {
    heading: function () { replaceSelection("## ", "", "제목"); },
    bold: function () { replaceSelection("**", "**", "굵은 글씨"); },
    list: function () { replaceSelection("- ", "", "목록 항목"); },
    check: function () { replaceSelection("- [ ] ", "", "할 일"); },
    table: function () { replaceSelection("| 항목 | 내용 |\n| --- | --- |\n| ", " |", "값"); },
    quote: function () { replaceSelection("> ", "", "인용문"); },
    link: function () { replaceSelection("[", "](https://)", "링크 제목"); },
    code: function () { replaceSelection("```\n", "\n```", "코드"); }
  };
  form.querySelectorAll("[data-md]").forEach(function (button) {
    button.addEventListener("click", function () {
      var action = snippets[button.dataset.md];
      if (action) action();
    });
  });

  async function updatePreview() {
    if (!preview || !textarea) return;
    preview.innerHTML = '<p class="item-meta">미리보기를 불러오는 중입니다.</p>';
    var payload = new FormData();
    payload.append("content", textarea.value);
    payload.append("csrf_token", preview.dataset.previewCsrf || "");
    try {
      var response = await fetch(preview.dataset.previewEndpoint, {
        method: "POST", body: payload, credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });
      var result = await response.json();
      if (!response.ok) throw new Error(result.error || "미리보기 실패");
      preview.innerHTML = result.html || '<p class="item-meta">내용을 입력하세요.</p>';
    } catch (_error) {
      preview.textContent = "미리보기를 불러오지 못했습니다.";
    }
  }

  function openPreview() {
    if (!previewDialog) return;
    if (typeof previewDialog.showModal === "function") previewDialog.showModal();
    else previewDialog.setAttribute("open", "");
    updatePreview();
  }
  function closePreview() {
    if (!previewDialog) return;
    if (typeof previewDialog.close === "function") previewDialog.close();
    else previewDialog.removeAttribute("open");
  }
  previewOpen && previewOpen.addEventListener("click", openPreview);
  previewClose && previewClose.addEventListener("click", closePreview);
  previewDialog && previewDialog.addEventListener("click", function (event) {
    if (event.target === previewDialog) closePreview();
  });
})();
