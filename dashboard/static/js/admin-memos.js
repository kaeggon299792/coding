(() => {
  "use strict";

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("copy failed");
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-memo]");
    if (!button) return;
    const code = button.closest(".admin-memo-card")?.querySelector("pre code");
    if (!code) return;
    const originalLabel = button.textContent;
    try {
      await copyText(code.textContent || "");
      button.textContent = "복사 완료";
    } catch (_) {
      button.textContent = "복사 실패";
    }
    window.setTimeout(() => { button.textContent = originalLabel; }, 1600);
  });
})();
