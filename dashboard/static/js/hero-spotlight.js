(function () {
  "use strict";

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function initHeroSpotlight(hero) {
    if (!hero) return;

    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    var finePointer = window.matchMedia("(pointer: fine)");
    var bounds = hero.getBoundingClientRect();
    var pointerActive = false;
    var pointerX = 0;
    var pointerY = 0;
    var currentLightX = 0;
    var currentLightY = 0;
    var rafId = 0;

    function refreshBounds() {
      bounds = hero.getBoundingClientRect();
    }

    function updatePointer(event) {
      if (reduceMotion.matches || !finePointer.matches || window.innerWidth <= 900) return;
      var relativeX = (event.clientX - bounds.left) / bounds.width;
      var relativeY = (event.clientY - bounds.top) / bounds.height;
      pointerX = clamp((relativeX - 0.5) * 2, -1, 1);
      pointerY = clamp((relativeY - 0.42) * 2, -1, 1);
      pointerActive = true;
    }

    hero.addEventListener("pointerenter", function () {
      refreshBounds();
      pointerActive = true;
    });
    hero.addEventListener("pointermove", updatePointer, { passive: true });
    hero.addEventListener("pointerleave", function () {
      pointerActive = false;
      pointerX = 0;
      pointerY = 0;
    });
    window.addEventListener("resize", refreshBounds, { passive: true });

    function frame(timestamp) {
      var reduced = reduceMotion.matches;
      var desktopInteractive = finePointer.matches && window.innerWidth > 900 && !reduced;
      var idleX = reduced ? 0 : Math.sin(timestamp / 5200) * 12 + Math.cos(timestamp / 8400) * 7;
      var idleY = reduced ? 0 : Math.cos(timestamp / 6100) * 9 + Math.sin(timestamp / 9700) * 5;

      var targetLightX = idleX + (desktopInteractive && pointerActive ? pointerX * 28 : 0);
      var targetLightY = idleY + (desktopInteractive && pointerActive ? pointerY * 22 : 0);

      currentLightX += (targetLightX - currentLightX) * 0.055;
      currentLightY += (targetLightY - currentLightY) * 0.055;

      hero.style.setProperty("--mouse-x", currentLightX.toFixed(2) + "px");
      hero.style.setProperty("--mouse-y", currentLightY.toFixed(2) + "px");

      rafId = window.requestAnimationFrame(frame);
    }

    rafId = window.requestAnimationFrame(frame);

    window.addEventListener("pagehide", function cleanup() {
      if (rafId) window.cancelAnimationFrame(rafId);
      window.removeEventListener("pagehide", cleanup);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-spotlight-hero]").forEach(initHeroSpotlight);
  });
})();
