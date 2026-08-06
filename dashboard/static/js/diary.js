(function () {
  "use strict";

  document.querySelectorAll("[data-diary-date-button]").forEach(function (button) {
    var picker = button.closest(".diary-date-picker");
    var input = picker && picker.querySelector("[data-diary-date]");
    if (!input) return;

    button.addEventListener("click", function () {
      input.focus({ preventScroll: true });
      if (typeof input.showPicker === "function") {
        try {
          input.showPicker();
          return;
        } catch (_error) {
          // Some mobile browsers expose showPicker but reject programmatic use.
        }
      }
      input.click();
    });
  });
})();
