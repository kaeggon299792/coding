const PAPER_SHADER_VERSION = "0.0.78";
const PAPER_SHADER_BASE = `https://cdn.jsdelivr.net/npm/@paper-design/shaders@${PAPER_SHADER_VERSION}/dist`;

const PRIMARY_COLORS = ["#000000", "#1a1a1a", "#2e2e2e", "#ffffff"];
const SECONDARY_COLORS = ["#000000", "#ffffff", "#2e2e2e"];
const mountsByHero = new WeakMap();

function prepareStaggeredTitle(hero) {
  let characterIndex = 0;
  hero.querySelectorAll("[data-stagger-text]").forEach((line) => {
    const text = line.textContent.trim();
    line.textContent = "";
    line.setAttribute("aria-label", text);
    Array.from(text).forEach((character) => {
      const span = document.createElement("span");
      span.className = "mesh-gradient-character";
      span.setAttribute("aria-hidden", "true");
      span.style.setProperty("--character-index", characterIndex);
      span.textContent = character === " " ? "\u00a0" : character;
      line.appendChild(span);
      characterIndex += 1;
    });
  });
}

function createUniforms(colors, modules) {
  const sizing = modules.defaultObjectSizing;
  return {
    u_colors: colors.map(modules.getShaderColorFromString),
    u_colorsCount: colors.length,
    u_distortion: 0.8,
    u_swirl: 0.1,
    u_grainMixer: 0,
    u_grainOverlay: 0,
    u_fit: modules.ShaderFitOptions[sizing.fit],
    u_rotation: sizing.rotation,
    u_scale: sizing.scale,
    u_offsetX: sizing.offsetX,
    u_offsetY: sizing.offsetY,
    u_originX: sizing.originX,
    u_originY: sizing.originY,
    u_worldWidth: sizing.worldWidth,
    u_worldHeight: sizing.worldHeight,
  };
}

async function loadPaperMeshGradient() {
  const [mountModule, meshModule, sizingModule, colorModule] = await Promise.all([
    import(`${PAPER_SHADER_BASE}/shader-mount.js`),
    import(`${PAPER_SHADER_BASE}/shaders/mesh-gradient.js`),
    import(`${PAPER_SHADER_BASE}/shader-sizing.js`),
    import(`${PAPER_SHADER_BASE}/get-shader-color-from-string.js`),
  ]);
  return {
    ShaderMount: mountModule.ShaderMount,
    meshGradientFragmentShader: meshModule.meshGradientFragmentShader,
    defaultObjectSizing: sizingModule.defaultObjectSizing,
    ShaderFitOptions: sizingModule.ShaderFitOptions,
    getShaderColorFromString: colorModule.getShaderColorFromString,
  };
}

export async function initMeshGradientHero(hero) {
  if (!hero || mountsByHero.has(hero)) return mountsByHero.get(hero) || null;

  const startedAt = performance.now();
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mobile = window.matchMedia("(max-width: 760px)").matches;
  const maxPixelCount = mobile ? 900000 : 2073600;
  const primaryHost = hero.querySelector('[data-mesh-gradient-layer="primary"]');
  const secondaryHost = hero.querySelector('[data-mesh-gradient-layer="secondary"]');
  const status = hero.querySelector("[data-mesh-gradient-status]");
  if (!primaryHost || !secondaryHost) return null;

  let disposed = false;
  let mounts = [];
  let contextLossHandlers = [];

  const destroy = () => {
    if (disposed) return;
    disposed = true;
    contextLossHandlers.forEach(([canvas, handler]) => {
      canvas.removeEventListener("webglcontextlost", handler);
    });
    contextLossHandlers = [];
    mounts.forEach((mount) => mount.dispose());
    mounts = [];
    mountsByHero.delete(hero);
  };

  const fallback = (reason) => {
    destroy();
    hero.classList.remove("is-shader-ready");
    hero.classList.add("is-shader-fallback");
    hero.dataset.shaderState = reason;
    if (status) status.textContent = "";
  };

  // Preview-only diagnostic: verifies the content-first fallback without
  // downloading or initializing the WebGL package.
  if (new URLSearchParams(window.location.search).get("webgl") === "off") {
    fallback("forced-fallback");
    return null;
  }

  try {
    const modules = await loadPaperMeshGradient();
    if (disposed) return null;
    const contextAttributes = {
      alpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
      preserveDrawingBuffer: false,
    };
    const primaryMount = new modules.ShaderMount(
      primaryHost,
      modules.meshGradientFragmentShader,
      createUniforms(PRIMARY_COLORS, modules),
      contextAttributes,
      reducedMotion ? 0 : 0.25,
      4200,
      1,
      maxPixelCount,
    );
    const secondaryMount = new modules.ShaderMount(
      secondaryHost,
      modules.meshGradientFragmentShader,
      createUniforms(SECONDARY_COLORS, modules),
      contextAttributes,
      reducedMotion ? 0 : 0.15,
      11800,
      1,
      maxPixelCount,
    );
    mounts = [primaryMount, secondaryMount];
    mounts.forEach((mount) => {
      const handler = () => fallback("context-lost");
      mount.canvasElement.addEventListener("webglcontextlost", handler, { once: true });
      contextLossHandlers.push([mount.canvasElement, handler]);
    });
    mountsByHero.set(hero, { destroy, mounts });
    hero.classList.add("is-shader-ready");
    hero.dataset.shaderState = "ready";
    hero.dataset.shaderInitMs = String(Math.round(performance.now() - startedAt));
    hero.dispatchEvent(new CustomEvent("meshgradientready", {
      detail: { initMs: Number(hero.dataset.shaderInitMs), contexts: mounts.length },
    }));
    return mountsByHero.get(hero);
  } catch (error) {
    fallback("fallback");
    console.warn("CASINO IN MeshGradient fallback enabled.", error);
    return null;
  }
}

export function destroyMeshGradientHero(hero) {
  mountsByHero.get(hero)?.destroy();
}

const hero = document.getElementById("mesh-gradient-hero");
if (hero) {
  prepareStaggeredTitle(hero);
  requestAnimationFrame(() => hero.classList.add("is-content-ready"));
  requestAnimationFrame(() => {
    requestAnimationFrame(() => initMeshGradientHero(hero));
  });
  window.addEventListener("pagehide", () => destroyMeshGradientHero(hero), { once: true });
}

window.CasinoMeshGradientHero = {
  initMeshGradientHero,
  destroyMeshGradientHero,
};
