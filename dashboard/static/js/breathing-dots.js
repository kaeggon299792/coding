/*
 * Breathing dots background adapted for CASINO IN from:
 * https://github.com/mattrossman/breathing-dots-tutorial
 *
 * Original concept and rounded square wave equation integration:
 * Copyright (c) 2009-2020 Codrops, MIT License.
 * The full license is preserved in static/vendor/breathing-dots/LICENSE.
 */
(function () {
  "use strict";

  var TWO_PI = Math.PI * 2;

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function roundedSquareWave(time, delta, amplitude, frequency) {
    return ((2 * amplitude) / Math.PI) *
      Math.atan(Math.sin(TWO_PI * time * frequency) / delta);
  }

  function deterministicNoise(index) {
    var value = Math.sin(index * 12.9898 + 78.233) * 43758.5453;
    return value - Math.floor(value);
  }

  function initBreathingDots(canvas) {
    var context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    var hero = canvas.closest("[data-spotlight-hero]");
    if (!hero) return;

    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    var finePointer = window.matchMedia("(pointer: fine)");
    var points = [];
    var width = 0;
    var height = 0;
    var pixelRatio = 1;
    var pointerTargetX = 0;
    var pointerTargetY = 0;
    var pointerX = 0;
    var pointerY = 0;
    var isVisible = true;
    var rafId = 0;
    var lastFrame = 0;

    function rebuildPoints() {
      points = [];
      var mobile = window.innerWidth <= 700;
      var spacing = mobile ? 25 : 21;
      var columns = Math.ceil(width / spacing) + 4;
      var rows = Math.ceil(height / spacing) + 4;
      var maximum = mobile ? 900 : 2200;
      var total = Math.min(columns * rows, maximum);

      for (var index = 0; index < total; index += 1) {
        var column = index % columns;
        var row = Math.floor(index / columns);
        var jitterX = (deterministicNoise(index) - 0.5) * spacing * 0.22;
        var jitterY = (deterministicNoise(index + 4096) - 0.5) * spacing * 0.22;
        points.push({
          x: (column - 2) * spacing + jitterX,
          y: (row - 2) * spacing + (column % 2) * spacing * 0.5 + jitterY
        });
      }
    }

    function resize() {
      var bounds = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(bounds.width));
      height = Math.max(1, Math.round(bounds.height));
      pixelRatio = Math.min(window.devicePixelRatio || 1, window.innerWidth <= 700 ? 1.15 : 1.5);
      canvas.width = Math.round(width * pixelRatio);
      canvas.height = Math.round(height * pixelRatio);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      rebuildPoints();
    }

    function updatePointer(event) {
      if (reduceMotion.matches || !finePointer.matches || window.innerWidth <= 900) return;
      var bounds = hero.getBoundingClientRect();
      var normalizedX = clamp((event.clientX - bounds.left) / bounds.width, 0, 1) - 0.5;
      var normalizedY = clamp((event.clientY - bounds.top) / bounds.height, 0, 1) - 0.5;
      pointerTargetX = normalizedX * 52;
      pointerTargetY = normalizedY * 40;
    }

    function resetPointer() {
      pointerTargetX = 0;
      pointerTargetY = 0;
    }

    function draw(timestamp) {
      rafId = window.requestAnimationFrame(draw);
      if (!isVisible || document.hidden) return;
      if (timestamp - lastFrame < 30 && !reduceMotion.matches) return;
      lastFrame = timestamp;

      context.clearRect(0, 0, width, height);
      pointerX += (pointerTargetX - pointerX) * 0.045;
      pointerY += (pointerTargetY - pointerY) * 0.045;

      var time = reduceMotion.matches ? 1.4 : timestamp / 1000;
      var centerX = width * 0.5 + pointerX;
      var centerY = height * 0.34 + pointerY;
      var darkTheme = document.documentElement.dataset.theme !== "light";
      var color = darkTheme ? "222,228,234" : "44,49,55";
      var maxDistance = Math.max(width, height) * 0.72;

      for (var index = 0; index < points.length; index += 1) {
        var point = points[index];
        var deltaX = point.x - centerX;
        var deltaY = point.y - centerY;
        var distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
        var angle = Math.atan2(deltaY, deltaX);
        var shapedDistance = distance + Math.cos(angle * 8) * 11;
        var wave = roundedSquareWave(time - shapedDistance / 330, 0.22 + distance / 2200, 0.052, 0.16);
        var falloff = clamp(1 - distance / maxDistance, 0, 1);
        var scale = 1 + wave * falloff;
        var x = centerX + deltaX * scale;
        var y = centerY + deltaY * scale;
        var pulse = 0.5 + 0.5 * Math.sin(time * 0.82 - shapedDistance * 0.032);
        var alpha = (0.24 + pulse * 0.34) * (0.42 + falloff * 0.58);
        var radius = 0.85 + falloff * 0.95 + pulse * 0.3;

        context.beginPath();
        context.arc(x, y, radius, 0, TWO_PI);
        context.fillStyle = "rgba(" + color + "," + alpha.toFixed(3) + ")";
        context.fill();
      }

      if (reduceMotion.matches && rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
    }

    hero.addEventListener("pointermove", updatePointer, { passive: true });
    hero.addEventListener("pointerleave", resetPointer, { passive: true });
    window.addEventListener("resize", resize, { passive: true });

    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        isVisible = entries[0] ? entries[0].isIntersecting : true;
      }, { rootMargin: "160px 0px" });
      observer.observe(hero);
    }

    resize();
    rafId = window.requestAnimationFrame(draw);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-breathing-dots]").forEach(initBreathingDots);
  });
})();
