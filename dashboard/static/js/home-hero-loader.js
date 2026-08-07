(() => {
  "use strict";

  const slot = document.getElementById("home-hero-slot");
  if (!slot) return;

  const allowed = ["spotlight", "event-horizon", "mesh-gradient"];
  const selected = allowed.includes(window.CasinoHomeHeroSelection)
    ? window.CasinoHomeHeroSelection
    : "spotlight";
  const template = slot.querySelector(`template[data-home-hero-template="${selected}"]`);
  if (!template) return;

  slot.dataset.homeHero = selected;
  slot.prepend(template.content.cloneNode(true));
  slot.querySelectorAll("template[data-home-hero-template]").forEach((item) => item.remove());

  const loadScript = (source, type = "text/javascript") => new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = source;
    script.type = type;
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

  if (selected === "mesh-gradient") {
    loadScript(slot.dataset.meshGradientSrc, "module").catch(() => {
      slot.querySelector(".mesh-gradient-hero")?.classList.add("is-shader-fallback");
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
