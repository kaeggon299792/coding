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
  const mouseTarget = new THREE.Vector2(8, 8);
  const mouseCurrent = new THREE.Vector2(8, 8);

  const vertexShader = `
    uniform float uTime;
    uniform float uAspect;
    uniform float uPointSize;
    uniform float uDpr;
    uniform float uMobile;
    uniform vec2 uMouse;
    uniform vec2 uRipple;
    uniform float uRippleTime;
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
      float n1 = snoise(field * 1.15 + vec2(uTime * 0.055, -uTime * 0.034));
      float n2 = snoise(field * 2.35 + vec2(-uTime * 0.031, uTime * 0.047));
      float n3 = snoise(field * 4.6 + vec2(uTime * 0.018, uTime * 0.026));
      float wave = n1 * 0.56 + n2 * 0.30 + n3 * 0.14;

      vec2 mouseDelta = base - uMouse;
      float mouseDistance = length(mouseDelta * vec2(uAspect, 1.0));
      float mouseGlow = smoothstep(0.62, 0.0, mouseDistance);
      vec2 safeDirection = mouseDistance > 0.001 ? normalize(mouseDelta) : vec2(0.0);

      float rippleAge = uTime - uRippleTime;
      float rippleDistance = distance(base * vec2(uAspect, 1.0), uRipple * vec2(uAspect, 1.0));
      float rippleLife = step(0.0, rippleAge) * (1.0 - smoothstep(0.0, 1.45, rippleAge));
      float ripple = sin(rippleDistance * 32.0 - rippleAge * 7.0) * exp(-rippleAge * 2.15) * rippleLife;

      vec2 displaced = base;
      displaced += safeDirection * mouseGlow * 0.018;
      displaced.y += wave * mix(0.024, 0.036, uMobile);
      displaced += normalize(base - uRipple + vec2(0.0001)) * ripple * 0.012;

      float edgeX = 1.0 - smoothstep(0.74, 1.17, abs(base.x));
      float edgeY = 1.0 - smoothstep(0.72, 1.12, abs(base.y));
      float headerFade = 1.0 - smoothstep(0.62, 1.05, base.y);
      float center = exp(-dot(base / vec2(0.78, 0.62), base / vec2(0.78, 0.62)) * 1.35);

      vHeight = wave * 0.5 + 0.5;
      vFade = edgeX * edgeY * headerFade;
      vCenter = clamp(center + mouseGlow * 0.22 + ripple * 0.14, 0.0, 1.0);
      gl_Position = vec4(displaced, 0.0, 1.0);
      gl_PointSize = uPointSize * uDpr * (0.72 + vHeight * 0.82 + vCenter * 0.36);
    }
  `;

  const fragmentShader = `
    precision highp float;
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
    material.uniforms.uPointSize.value = mobile ? 2.55 : 2.05;
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

  function pointerToUniform(event, target) {
    target.set((event.clientX / Math.max(window.innerWidth, 1)) * 2 - 1, 1 - (event.clientY / Math.max(window.innerHeight, 1)) * 2);
  }

  function handlePointerMove(event) {
    if (mobileQuery.matches || reduceMotion.matches) return;
    pointerToUniform(event, mouseTarget);
  }

  function handlePointerLeave() {
    mouseTarget.set(8, 8);
  }

  function handlePointerDown(event) {
    if (themeIsLight || reduceMotion.matches) return;
    pointerToUniform(event, material.uniforms.uRipple.value);
    material.uniforms.uRippleTime.value = currentTime;
  }

  function render(timestamp) {
    animationFrame = 0;
    if (disposed || document.hidden || themeIsLight) return;
    const elapsed = Math.min((timestamp - lastTime) / 1000 || 0, 0.05);
    lastTime = timestamp;
    if (!reduceMotion.matches) currentTime += elapsed;
    mouseCurrent.lerp(mouseTarget, 0.035);
    material.uniforms.uTime.value = reduceMotion.matches ? 0.8 : currentTime;
    material.uniforms.uMouse.value.copy(mouseCurrent);
    renderer.render(scene, camera);
    if (!reduceMotion.matches) animationFrame = requestAnimationFrame(render);
  }

  function start() {
    if (!animationFrame && !disposed && !document.hidden && !themeIsLight) {
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
    if (themeIsLight && animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      renderer.clear();
    } else {
      start();
    }
  }

  function cleanup() {
    if (disposed) return;
    disposed = true;
    if (animationFrame) cancelAnimationFrame(animationFrame);
    if (resizeFrame) cancelAnimationFrame(resizeFrame);
    window.removeEventListener("resize", scheduleResize);
    window.removeEventListener("pointermove", handlePointerMove);
    window.removeEventListener("pointerleave", handlePointerLeave);
    window.removeEventListener("pointerdown", handlePointerDown);
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
        uMobile: { value: mobileQuery.matches ? 1 : 0 },
        uMouse: { value: mouseCurrent },
        uRipple: { value: new THREE.Vector2(8, 8) },
        uRippleTime: { value: -10 }
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
    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", handlePointerLeave, { passive: true });
    window.addEventListener("pointerdown", handlePointerDown, { passive: true });
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
