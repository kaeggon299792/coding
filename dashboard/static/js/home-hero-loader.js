(() => {
  "use strict";

  const slot = document.getElementById("home-hero-slot");
  if (!slot) return;

  const selected = window.CasinoHomeHeroSelection === "event-horizon"
    ? "event-horizon"
    : "spotlight";
  const template = slot.querySelector(`template[data-home-hero-template="${selected}"]`);
  if (!template) return;

  slot.dataset.homeHero = selected;
  slot.prepend(template.content.cloneNode(true));
  slot.querySelectorAll("template[data-home-hero-template]").forEach((item) => item.remove());

  if (selected === "event-horizon") {
    document.querySelector("[data-home-sitemap]")?.remove();
  }

  const loadScript = (source) => new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = source;
    script.async = true;
    script.dataset.homeHeroAsset = selected;
    script.addEventListener("load", resolve, { once: true });
    script.addEventListener("error", reject, { once: true });
    document.head.appendChild(script);
  });

  if (selected === "event-horizon") {
    loadScript(slot.dataset.eventHorizonSrc).catch(() => {
      slot.querySelector(".event-horizon-hero")?.classList.add("is-webgl-fallback");
    });
    return;
  }

  loadScript(slot.dataset.spotlightSrc).catch(() => {});
  loadScript(slot.dataset.threeSrc)
    .then(() => loadScript(slot.dataset.waveSrc))
    .catch(() => {
      document.body.classList.add("webgl-wave-fallback");
      document.documentElement.dataset.webglWave = "fallback";
    });
})();
