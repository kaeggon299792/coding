(() => {
  "use strict";

  const namespace = window.CasinoHeroEffects || (window.CasinoHeroEffects = {});
  let activeInstance = null;

  function initEventHorizonHero(container) {
    if (!container || activeInstance) return activeInstance;

    const visual = container.querySelector("[data-event-horizon-visual]");
    const status = container.querySelector("[data-event-horizon-status]");
    const source = container.dataset.effectSrc;
    if (!visual || !source) return null;

    const iframe = document.createElement("iframe");
    iframe.className = "event-horizon-frame";
    iframe.title = "Event Horizon WebGL visual";
    iframe.tabIndex = -1;
    iframe.setAttribute("aria-hidden", "true");
    iframe.setAttribute("loading", "eager");

    let destroyed = false;
    let visible = true;
    let initialized = false;
    let readyTimer = 0;

    const post = (payload) => {
      if (!destroyed && iframe.contentWindow) iframe.contentWindow.postMessage(payload, window.location.origin);
    };

    const applyComposition = () => {
      const mobile = window.matchMedia("(max-width: 760px)").matches;
      post({ type: "param", name: "BH_CENTER_X", value: mobile ? 0.5 : 0.7 });
      post({ type: "param", name: "BH_CENTER_Y", value: mobile ? 0.3 : 0.5 });
      post({ type: "param", name: "BH_SCALE", value: mobile ? 0.72 : 0.76 });
    };

    const pause = () => post({ type: "event-horizon:pause" });
    const resume = () => {
      if (visible && !document.hidden) post({ type: "event-horizon:resume" });
    };

    const fail = (reason) => {
      window.clearTimeout(readyTimer);
      container.classList.add("is-webgl-fallback");
      container.classList.remove("is-webgl-ready");
      container.dataset.webglState = "fallback";
      container.dataset.webglReason = reason;
      if (status) status.textContent = "";
    };

    const onMessage = (event) => {
      if (event.origin !== window.location.origin || event.source !== iframe.contentWindow) return;
      const message = event.data;
      if (!message || message.source !== "casino-event-horizon") return;

      if (message.type === "initialized") {
        initialized = true;
        container.dataset.webglInitMs = String(message.detail.initMs || 0);
        applyComposition();
        if (!visible || document.hidden) pause();
      } else if (message.type === "ready") {
        window.clearTimeout(readyTimer);
        container.classList.add("is-webgl-ready");
        container.classList.remove("is-webgl-fallback");
        container.dataset.webglState = "ready";
        container.dataset.webglFirstFrameMs = String(message.detail.firstFrameMs || 0);
        container.dataset.webglDpr = String(message.detail.dpr || 1);
      } else if (message.type === "performance") {
        container.dataset.webglFps = String(message.detail.fps || 0);
      } else if (message.type === "error") {
        fail(message.detail.reason || "renderer-error");
      } else if (message.type === "context-lost") {
        container.dataset.webglState = "context-lost";
      }
    };

    const onVisibility = () => document.hidden ? pause() : resume();
    const onResize = () => {
      if (initialized) applyComposition();
    };

    const observer = "IntersectionObserver" in window
      ? new IntersectionObserver((entries) => {
          visible = entries[0]?.isIntersecting === true;
          visible ? resume() : pause();
        }, { threshold: 0.02 })
      : null;

    const destroy = () => {
      if (destroyed) return;
      window.clearTimeout(readyTimer);
      observer?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("message", onMessage);
      post({ type: "event-horizon:destroy" });
      destroyed = true;
      iframe.remove();
      activeInstance = null;
    };

    window.addEventListener("message", onMessage);
    window.addEventListener("resize", onResize, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    observer?.observe(container);
    iframe.addEventListener("error", () => fail("asset-load"), { once: true });
    visual.appendChild(iframe);

    requestAnimationFrame(() => {
      if (destroyed) return;
      iframe.src = source;
      readyTimer = window.setTimeout(() => fail("ready-timeout"), 20000);
    });

    activeInstance = { destroy, pause, resume, element: container };
    return activeInstance;
  }

  function destroyEventHorizonHero() {
    activeInstance?.destroy();
  }

  namespace.eventHorizon = {
    init: initEventHorizonHero,
    destroy: destroyEventHorizonHero,
  };

  const hero = document.getElementById("event-horizon-hero");
  if (hero) initEventHorizonHero(hero);
})();
