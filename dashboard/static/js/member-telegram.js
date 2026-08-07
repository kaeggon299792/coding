(function () {
  "use strict";

  var page = document.querySelector("[data-telegram-awaiting]");
  if (!page) return;

  var statusUrl = page.getAttribute("data-telegram-status-url");
  var stopped = false;
  var startedAt = Date.now();
  var timer = 0;

  function schedule(delay) {
    window.clearTimeout(timer);
    if (!stopped && Date.now() - startedAt < 120000) {
      timer = window.setTimeout(check, delay);
    }
  }

  function check() {
    if (stopped || document.hidden || !statusUrl) return;
    fetch(statusUrl, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) throw new Error("status unavailable");
        return response.json();
      })
      .then(function (payload) {
        if (payload && payload.connected) {
          stopped = true;
          window.location.reload();
          return;
        }
        schedule(2500);
      })
      .catch(function () { schedule(5000); });
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) check();
  });
  window.addEventListener("pageshow", check);
  window.addEventListener("pagehide", function () {
    stopped = true;
    window.clearTimeout(timer);
  }, { once: true });
  schedule(1500);
}());
