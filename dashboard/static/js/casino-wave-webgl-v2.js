const THREE = window.THREE;

const canvas = document.querySelector("[data-casino-wave]");
const page = document.body;

if (canvas && page.classList.contains("cinematic-home") && THREE) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const mobileQuery = window.matchMedia("(max-width: 700px)");
  let renderer;
  let geometry;
  let material;
  let scene;
  let camera;
  let points;
  let themeObserver;
  let animationFrame = 0;
  let resizeFrame = 0;
  let disposed = false;
  let lastTime = 0;
  let currentTime = 0;
  let themeIsLight = document.documentElement.dataset.theme === "light";

  const vertexShader = `
    uniform float uTime;
    uniform float uAspect;
    uniform float uPointSize;
    uniform float uDpr;
    uniform float uMobile;
    varying float vHeight;
    varying float vFade;
    varying float vCenter;

    vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
    vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

    float snoise(vec2 v) {
      const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
      vec2 i = floor(v + dot(v, C.yy));
      vec2 x0 = v - i + dot(i, C.xx);
      vec2 i1 = x0.x > x0.y ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
      vec4 x12 = x0.xyxy + C.xxzz;
      x12.xy -= i1;
      i = mod289(i);
      vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
      vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
      m = m * m;
      m = m * m;
      vec3 x = 2.0 * fract(p * C.www) - 1.0;
      vec3 h = abs(x) - 0.5;
      vec3 ox = floor(x + 0.5);
      vec3 a0 = x - ox;
      m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
      vec3 g;
      g.x = a0.x * x0.x + h.x * x0.y;
      g.yz = a0.yz * x12.xz + h.yz * x12.yw;
      return 130.0 * dot(m, g);
    }

    void main() {
      vec2 base = position.xy;
      vec2 field = vec2(base.x * uAspect, base.y);
      float n1 = snoise(field * 1.15 + vec2(uTime * 0.115, -uTime * 0.072));
      float n2 = snoise(field * 2.35 + vec2(-uTime * 0.067, uTime * 0.104));
      float n3 = snoise(field * 4.6 + vec2(uTime * 0.041, uTime * 0.058));
      float wave = n1 * 0.56 + n2 * 0.30 + n3 * 0.14;

      vec2 displaced = base;
      displaced.x += (n2 * 0.010 + n3 * 0.004) * mix(1.0, 0.82, uMobile);
      displaced.y += wave * mix(0.036, 0.045, uMobile);

      float edgeX = 1.0 - smoothstep(0.74, 1.17, abs(base.x));
      float edgeY = 1.0 - smoothstep(0.72, 1.12, abs(base.y));
      float headerFade = 1.0 - smoothstep(0.62, 1.05, base.y);
      float center = exp(-dot(base / vec2(0.78, 0.62), base / vec2(0.78, 0.62)) * 1.35);

      vHeight = wave * 0.5 + 0.5;
      vFade = edgeX * edgeY * headerFade;
      vCenter = clamp(center + (n1 * 0.5 + 0.5) * 0.08, 0.0, 1.0);
      gl_Position = vec4(displaced, 0.0, 1.0);
      gl_PointSize = uPointSize * uDpr * (0.72 + vHeight * 0.82 + vCenter * 0.36);
    }
  `;

  const fragmentShader = `
    precision highp float;
    uniform float uMobile;
    varying float vHeight;
    varying float vFade;
    varying float vCenter;

    void main() {
      float distanceToCenter = length(gl_PointCoord - vec2(0.5));
      float particle = 1.0 - smoothstep(0.12, 0.5, distanceToCenter);
      vec3 outer = vec3(0.325, 0.349, 0.376);
      vec3 middle = vec3(0.784, 0.804, 0.824);
      vec3 white = vec3(1.0);
      float lightness = clamp(vHeight * 0.72 + vCenter * 0.48, 0.0, 1.0);
      vec3 color = mix(outer, middle, lightness);
      color = mix(color, white, vCenter * vHeight * 0.46);
      float alpha = particle * vFade * (0.20 + vHeight * 0.36 + vCenter * 0.32);
      alpha *= mix(1.0, 1.5, uMobile);
      if (alpha < 0.008) discard;
      gl_FragColor = vec4(color, alpha);
    }
  `;

  function makeGeometry() {
    const mobile = mobileQuery.matches;
    const columns = mobile ? 84 : 154;
    const rows = mobile ? 58 : 102;
    const values = new Float32Array(columns * rows * 3);
    let offset = 0;
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const seed = Math.sin((column + 1) * 12.9898 + (row + 1) * 78.233) * 43758.5453;
        const jitter = (seed - Math.floor(seed) - 0.5) * 0.004;
        values[offset] = -1.18 + (column / (columns - 1)) * 2.36 + jitter;
        values[offset + 1] = -1.12 + (row / (rows - 1)) * 2.24 + jitter;
        values[offset + 2] = seed - Math.floor(seed);
        offset += 3;
      }
    }
    const nextGeometry = new THREE.BufferGeometry();
    nextGeometry.setAttribute("position", new THREE.BufferAttribute(values, 3));
    return nextGeometry;
  }

  function resize() {
    if (!renderer || disposed) return;
    const mobile = mobileQuery.matches;
    const dpr = Math.min(window.devicePixelRatio || 1, mobile ? 1 : 1.5);
    renderer.setPixelRatio(dpr);
    renderer.setSize(window.innerWidth, window.innerHeight, false);
    material.uniforms.uAspect.value = window.innerWidth / Math.max(window.innerHeight, 1);
    material.uniforms.uDpr.value = dpr;
    material.uniforms.uMobile.value = mobile ? 1 : 0;
    material.uniforms.uPointSize.value = mobile ? 3.15 : 2.05;
  }

  function scheduleResize() {
    if (resizeFrame) cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0;
      const previousMobile = material.uniforms.uMobile.value > 0.5;
      const nextMobile = mobileQuery.matches;
      if (previousMobile !== nextMobile) {
        geometry.dispose();
        geometry = makeGeometry();
        points.geometry = geometry;
      }
      resize();
      if (reduceMotion.matches) renderer.render(scene, camera);
    });
  }

  function render(timestamp) {
    animationFrame = 0;
    if (disposed || document.hidden) return;
    const elapsed = Math.min((timestamp - lastTime) / 1000 || 0, 0.05);
    lastTime = timestamp;
    if (!reduceMotion.matches) currentTime += elapsed;
    material.uniforms.uTime.value = reduceMotion.matches ? 0.8 : currentTime;
    renderer.render(scene, camera);
    if (!reduceMotion.matches) animationFrame = requestAnimationFrame(render);
  }

  function start() {
    if (!animationFrame && !disposed && !document.hidden) {
      lastTime = 0;
      animationFrame = requestAnimationFrame(render);
    }
  }

  function handleVisibility() {
    if (document.hidden && animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = 0;
    } else {
      start();
    }
  }

  function handleThemeChange() {
    themeIsLight = document.documentElement.dataset.theme === "light";
    start();
  }

  function cleanup() {
    if (disposed) return;
    disposed = true;
    if (animationFrame) cancelAnimationFrame(animationFrame);
    if (resizeFrame) cancelAnimationFrame(resizeFrame);
    window.removeEventListener("resize", scheduleResize);
    document.removeEventListener("visibilitychange", handleVisibility);
    if (themeObserver) themeObserver.disconnect();
    geometry.dispose();
    material.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  }

  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "high-performance" });
    renderer.setClearColor(0x050607, 0);
    scene = new THREE.Scene();
    camera = new THREE.Camera();
    geometry = makeGeometry();
    material = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uAspect: { value: 1 },
        uPointSize: { value: 2.05 },
        uDpr: { value: 1 },
        uMobile: { value: mobileQuery.matches ? 1 : 0 }
      },
      vertexShader,
      fragmentShader,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    points = new THREE.Points(geometry, material);
    points.frustumCulled = false;
    scene.add(points);
    resize();

    window.addEventListener("resize", scheduleResize, { passive: true });
    document.addEventListener("visibilitychange", handleVisibility);
    themeObserver = new MutationObserver(handleThemeChange);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    window.addEventListener("pagehide", cleanup, { once: true });
    page.classList.add("webgl-wave-ready");
    document.documentElement.dataset.webglWave = "ready";
    start();
  } catch (error) {
    page.classList.add("webgl-wave-fallback");
    document.documentElement.dataset.webglWave = "fallback";
    console.warn("CASINO IN WebGL background fallback enabled.", error);
  }
} else if (canvas && page.classList.contains("cinematic-home")) {
  page.classList.add("webgl-wave-fallback");
  document.documentElement.dataset.webglWave = "fallback";
}
