(() => {
  "use strict";

  const SETTINGS = Object.freeze({
    animationSpeed: 0.72,
    ringThickness: 0.018,
    goldIntensity: 1.05,
    glowIntensity: 0.72,
    iridescenceIntensity: 0.34,
    refractionStrength: 0.008,
    sparkleIntensity: 0.86,
    pointerInfluence: 0.016,
    mobileQuality: 0.68,
    resolution: 256,
    maxPixelRatio: 1.5,
  });

  const VERTEX_SHADER = `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = vec4(position, 1.0);
    }
  `;

  const FRAGMENT_SHADER = `
    precision highp float;
    uniform sampler2D uTexture;
    uniform float uTime;
    uniform vec2 uPointer;
    uniform float uAnimationSpeed;
    uniform float uRingThickness;
    uniform float uGoldIntensity;
    uniform float uGlowIntensity;
    uniform float uIridescenceIntensity;
    uniform float uRefractionStrength;
    uniform float uSparkleIntensity;
    uniform float uPointerInfluence;
    uniform float uMobileQuality;
    uniform float uInnerRadius;
    varying vec2 vUv;

    float hash21(vec2 p) {
      p = fract(p * vec2(123.34, 456.21));
      p += dot(p, p + 45.32);
      return fract(p.x * p.y);
    }
    float valueNoise(vec2 p) {
      vec2 i = floor(p), f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash21(i), hash21(i + vec2(1.,0.)), f.x),
                 mix(hash21(i + vec2(0.,1.)), hash21(i + vec2(1.)), f.x), f.y);
    }
    vec3 spectrum(float x) {
      return .56 + .44 * cos(6.28318 * (x + vec3(0.00, .33, .67)));
    }
    float star(vec2 p, vec2 at, float size) {
      vec2 d = abs(p - at);
      float core = exp(-length(d) * 125.0 / size);
      float rays = exp(-min(d.x, d.y) * 165.0 / size) * exp(-length(d) * 20.0);
      return core + rays * .42;
    }

    void main() {
      vec2 p = vUv - .5;
      float t = uTime * uAnimationSpeed;
      vec2 pointerShift = uPointer * uPointerInfluence;
      float radius = length(p);
      float angle = atan(p.y, p.x);
      float aa = .0045;

      vec2 photoUv = (p - pointerShift * .34) / (uInnerRadius * 2.0) + .5;
      float arc = sin(p.x * 8.0 + t * .38) * .035 + sin(p.x * 3.0 - t * .21) * .018;
      float travel = fract(t * .055) * 1.45 - .72;
      float bandDistance = abs((p.y + arc) - travel);
      float band = exp(-bandDistance * bandDistance * 560.0) * smoothstep(uInnerRadius, uInnerRadius - .035, radius);
      float distortion = sin((p.y + p.x) * 22.0 - t * .7) * uRefractionStrength * band;
      vec2 refracted = photoUv + vec2(distortion, distortion * .35);
      vec3 photo;
      photo.r = texture2D(uTexture, refracted + vec2(uRefractionStrength * band, 0.)).r;
      photo.g = texture2D(uTexture, refracted).g;
      photo.b = texture2D(uTexture, refracted - vec2(uRefractionStrength * band, 0.)).b;
      vec3 prism = spectrum(photoUv.x * .62 + photoUv.y * .38 + t * .025);
      photo += prism * band * uIridescenceIntensity * uMobileQuality;
      float photoMask = smoothstep(uInnerRadius + aa, uInnerRadius - aa, radius);

      float ringRadius = uInnerRadius + .034;
      float ringSdf = abs(radius - ringRadius);
      float ringMask = smoothstep(uRingThickness + aa, uRingThickness - aa, ringSdf);
      float flowA = valueNoise(vec2(angle * 2.1 + t * .11, t * .09));
      float flowB = valueNoise(vec2(angle * 4.7 - t * .19, t * .045 + 7.));
      float highlight = pow(max(0., sin(angle * 2.0 - t * .34 + flowA * 3.2)), 10.0);
      highlight += pow(max(0., sin(angle * 3.0 + t * .17 + flowB * 4.0)), 18.0) * .72;
      float localWhite = pow(max(0., sin(angle - t * .23 + flowB * 5.7)), 34.0);
      vec3 darkGold = vec3(.27, .12, .018);
      vec3 warmGold = vec3(1.00, .60, .10);
      vec3 gold = mix(darkGold, warmGold, .38 + flowA * .34 + highlight * .52);
      gold = mix(gold, vec3(1.0, .94, .72), localWhite * .9) * uGoldIntensity;

      float glow = exp(-abs(radius - ringRadius) * 48.0) * uGlowIntensity;
      glow += exp(-abs(radius - ringRadius) * 17.0) * .16 * uGlowIntensity;
      vec3 color = photo * photoMask;
      color += gold * ringMask;
      color += warmGold * glow * (1.0 - photoMask) * .34;

      vec2 s1 = vec2(cos(t * .13 + .4), sin(t * .13 + .4)) * ringRadius;
      vec2 s2 = vec2(cos(-t * .09 + 2.5), sin(-t * .09 + 2.5)) * ringRadius;
      vec2 s3 = vec2(cos(t * .07 + 4.7), sin(t * .07 + 4.7)) * ringRadius;
      float gate1 = smoothstep(.72, .96, valueNoise(vec2(floor(t * .35), 11.)));
      float gate2 = smoothstep(.69, .95, valueNoise(vec2(floor(t * .27), 29.)));
      float gate3 = smoothstep(.76, .97, valueNoise(vec2(floor(t * .21), 47.)));
      float spark = star(p, s1, 1.) * gate1 + star(p, s2, .82) * gate2;
      spark += star(p, s3, .68) * gate3 * uMobileQuality;
      color += vec3(1.0, .88, .55) * spark * uSparkleIntensity;

      float outerAlpha = smoothstep(.50, .46, radius);
      float alpha = max(photoMask, max(ringMask, glow * .62));
      alpha = max(alpha, min(spark, 1.0)) * outerAlpha;
      gl_FragColor = vec4(color, clamp(alpha, 0.0, 1.0));
    }
  `;

  class ProfileAvatarWebGL {
    constructor(container, onFailure) {
      this.container = container;
      this.onFailure = onFailure;
      this.image = container.querySelector("img:not(.membership-badge-icon)");
      this.renderer = null;
      this.frame = 0;
      this.visible = true;
      this.contextAvailable = true;
      this.disposed = false;
      this.pointerTarget = {x: 0, y: 0};
      this.pointer = {x: 0, y: 0};
      this.clockStart = performance.now();
      this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.mobile = matchMedia("(max-width: 760px)").matches;
      this.initialize();
    }

    initialize() {
      if (!this.image || !window.THREE || this.reducedMotion) return this.fail();
      const source = this.image.currentSrc || this.image.src;
      if (!source) return this.fail();
      const loader = new THREE.TextureLoader();
      loader.setCrossOrigin("anonymous");
      loader.load(source, (texture) => this.build(texture), undefined, () => this.fail());
    }

    build(texture) {
      if (this.disposed) { texture.dispose(); return; }
      try {
        texture.encoding = THREE.sRGBEncoding;
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        const canvas = document.createElement("canvas");
        canvas.className = "profile-avatar-webgl-canvas";
        canvas.setAttribute("aria-hidden", "true");
        this.renderer = new THREE.WebGLRenderer({canvas, alpha: true, antialias: true, powerPreference: "low-power"});
        this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, SETTINGS.maxPixelRatio));
        this.renderer.setSize(SETTINGS.resolution, SETTINGS.resolution, false);
        this.renderer.setClearColor(0x000000, 0);
        this.scene = new THREE.Scene();
        this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
        this.camera.position.z = 1;
        this.uniforms = {
          uTexture: {value: texture}, uTime: {value: 0}, uPointer: {value: new THREE.Vector2()},
          uAnimationSpeed: {value: SETTINGS.animationSpeed}, uRingThickness: {value: SETTINGS.ringThickness},
          uGoldIntensity: {value: SETTINGS.goldIntensity}, uGlowIntensity: {value: SETTINGS.glowIntensity},
          uIridescenceIntensity: {value: SETTINGS.iridescenceIntensity}, uRefractionStrength: {value: SETTINGS.refractionStrength},
          uSparkleIntensity: {value: SETTINGS.sparkleIntensity}, uPointerInfluence: {value: SETTINGS.pointerInfluence},
          uMobileQuality: {value: this.mobile ? SETTINGS.mobileQuality : 1}, uInnerRadius: {value: this.mobile ? .365 : .385},
        };
        this.material = new THREE.ShaderMaterial({vertexShader: VERTEX_SHADER, fragmentShader: FRAGMENT_SHADER, uniforms: this.uniforms, transparent: true, depthTest: false, depthWrite: false});
        this.geometry = new THREE.PlaneGeometry(2, 2);
        this.scene.add(new THREE.Mesh(this.geometry, this.material));
        this.container.insertBefore(canvas, this.container.querySelector(".membership-badge-icon"));
        this.canvas = canvas;
        this.bindEvents();
        this.renderer.render(this.scene, this.camera);
        this.container.classList.add("is-webgl-active");
        this.animate();
      } catch (_) { this.fail(); }
    }

    bindEvents() {
      this.onPointer = (event) => {
        const point = event.touches ? event.touches[0] : event;
        const rect = this.container.getBoundingClientRect();
        this.pointerTarget.x = Math.max(-1, Math.min(1, ((point.clientX - rect.left) / rect.width) * 2 - 1));
        this.pointerTarget.y = Math.max(-1, Math.min(1, -(((point.clientY - rect.top) / rect.height) * 2 - 1)));
      };
      this.container.addEventListener("pointermove", this.onPointer, {passive: true});
      this.container.addEventListener("touchmove", this.onPointer, {passive: true});
      this.canvas.addEventListener("webglcontextlost", this.onContextLost = (event) => {
        event.preventDefault(); this.contextAvailable = false; this.stop(); this.container.classList.remove("is-webgl-active");
      });
      this.canvas.addEventListener("webglcontextrestored", this.onContextRestored = () => {
        this.contextAvailable = true; this.container.classList.add("is-webgl-active"); this.animate();
      });
      this.observer = new IntersectionObserver(([entry]) => { this.visible = entry.isIntersecting; this.visible ? this.animate() : this.stop(); }, {threshold: .05});
      this.observer.observe(this.container);
    }

    animate() {
      if (this.frame || !this.renderer || !this.visible || document.hidden || !this.contextAvailable) return;
      const draw = (now) => {
        this.frame = 0;
        if (!this.visible || document.hidden || !this.contextAvailable) return;
        this.pointer.x += (this.pointerTarget.x - this.pointer.x) * .045;
        this.pointer.y += (this.pointerTarget.y - this.pointer.y) * .045;
        this.uniforms.uPointer.value.set(this.pointer.x, this.pointer.y);
        this.uniforms.uTime.value = (now - this.clockStart) / 1000;
        this.renderer.render(this.scene, this.camera);
        this.frame = requestAnimationFrame(draw);
      };
      this.frame = requestAnimationFrame(draw);
    }

    stop() { if (this.frame) cancelAnimationFrame(this.frame); this.frame = 0; }
    fail() { this.destroy(false); if (this.onFailure) this.onFailure(); }
    destroy(removeCanvas = true) {
      this.disposed = true;
      this.stop();
      this.observer?.disconnect();
      if (this.onPointer) { this.container.removeEventListener("pointermove", this.onPointer); this.container.removeEventListener("touchmove", this.onPointer); }
      this.geometry?.dispose(); this.material?.dispose(); this.uniforms?.uTexture.value?.dispose(); this.renderer?.dispose();
      if (removeCanvas) this.canvas?.remove();
      this.container.classList.remove("is-webgl-active");
    }
  }

  let active = null;
  const candidates = () => [
    ...document.querySelectorAll(".account-avatar-wrap[data-profile-avatar-webgl='candidate']"),
    ...document.querySelectorAll(".topbar-profile-menu[open] .topbar-profile-large-avatar[data-profile-avatar-webgl='candidate']"),
    ...document.querySelectorAll(".topbar-user [data-profile-avatar-webgl='candidate']"),
  ].filter((node) => {
    const r = node.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(node).visibility !== "hidden";
  });
  const selectRepresentative = () => {
    const target = candidates()[0];
    if (!target || active?.container === target) return;
    active?.destroy();
    active = new ProfileAvatarWebGL(target, () => { if (active?.container === target) active = null; });
  };
  document.addEventListener("visibilitychange", () => { if (!active) return; document.hidden ? active.stop() : active.animate(); });
  document.querySelectorAll(".topbar-profile-menu").forEach((details) => details.addEventListener("toggle", () => requestAnimationFrame(selectRepresentative)));
  addEventListener("resize", selectRepresentative, {passive: true});
  selectRepresentative();
})();
