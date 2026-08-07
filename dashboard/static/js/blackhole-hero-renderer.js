/**
 * BlackHoleHeroRenderer — vanilla-JS/raw-WebGL port of the "BlackHoleHeroSection"
 * React component. Every ray marches through curved (Schwarzschild) space; the
 * accretion disc, its halo above and below the shadow, and the thin photon ring
 * are one gas disc seen three or four times through bent light — nothing here
 * draws a ring or a halo directly. See SCENE_FRAG below for the physics.
 *
 * This file intentionally mirrors the original component's structure 1:1:
 *   useRef(container/canvas)  -> constructor(container, options) reads DOM refs
 *   useEffect(setup, [])      -> init()
 *   useEffect cleanup         -> destroy()
 *   props.current             -> this.options
 *   React state -> new props  -> updateOptions(partial)
 *
 * No React, no Three.js: same raw WebGL1/WebGL2 pipeline as the source.
 */
(() => {
  "use strict";

  const RAD = Math.PI / 180;

  /* -------------------------------------------------------------------- */
  /*  Shaders — kept as close to the original TSX source as GLSL allows.   */
  /* -------------------------------------------------------------------- */

  const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

  /**
   * The scene pass. One ray per pixel, integrated through Schwarzschild space.
   *
   * The whole of the physics is four lines long. For a photon, the shape of the
   * path obeys u'' + u = 3M·u² with u = 1/r, and in Cartesian form that is
   *
   *     a = -3/2 · h² · r⃗ / |r⃗|⁵ ,   h = |r⃗ × v⃗| , constant
   *
   * with the horizon at |r⃗| = 1. Leapfrog that with a step short enough to
   * resolve the disc and you have every arc in the picture: the halo, the ring,
   * the smeared stars, the flattened shadow. There is no trick layer on top.
   */
  const SCENE_FRAG = `
precision highp float;

#define MAX_STEPS 460

/**
 * Seconds before the wound-up gas pattern hands over to a fresh copy. What
 * matters is how far the gas winds in one of these, which is this times the
 * spin — so a slow disc can afford a long cycle, and a long cycle is what you
 * want: every handover costs a little contrast while the two copies overlap.
 */
#define WIND_CYCLE 46.0

varying vec2 vUv;

uniform vec2  uRes;
uniform float uTime;
uniform vec3  uCamPos;
uniform vec3  uRight;
uniform vec3  uUp;
uniform vec3  uFwd;
uniform float uTanHalf;
uniform vec2  uFocus;
uniform float uSteps;
uniform float uSkyR;
uniform float uDiskIn;
uniform float uDiskOut;
uniform float uThick;
uniform float uDensity;
uniform float uSpin;
uniform float uGrain;
uniform float uBright;
uniform float uDoppler;
uniform vec3  uHot;
uniform vec3  uMid;
uniform vec3  uCool;
uniform float uStars;
uniform float uEncode;
uniform vec2  uJitter;
uniform float uSeed;

/* --- noise ---------------------------------------------------------------- */

float hash13(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float vnoise(vec3 x) {
  vec3 i = floor(x);
  vec3 f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash13(i + vec3(0.0, 0.0, 0.0));
  float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
  float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
  float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
  float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
  float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
  float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
  float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
  return mix(
    mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
    mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
    f.z
  );
}

/** lod fades the finest octave out, for rays whose steps are too long to see it. */
float fbm(vec3 p, float lod) {
  float a = 0.5;
  float s = 0.0;
  for (int i = 0; i < 4; i++) {
    s += (i == 3 ? a * lod : a) * vnoise(p);
    p = p * 2.03 + vec3(11.3, 7.1, 3.7);
    a *= 0.5;
  }
  return s;
}

/* --- the gas -------------------------------------------------------------- */

/**
 * Density and colour of the disc at a point.
 *
 * The gas runs on Kepler orbits, so the inner rim laps the outer edge many
 * times over. Reading the turbulence in a frame that turns with the gas, at
 * each radius its own rate, is what shears the clouds into the trailing
 * spirals — nothing draws a spiral.
 */
void gasAt(vec3 p, float rd, float dt, out float dens, out vec3 tint, out float heat) {
  float rn = clamp((rd - uDiskIn) / max(0.001, uDiskOut - uDiskIn), 0.0, 1.0);

  // A thin sheet at the rim, flaring outward.
  float tk = uThick * (0.35 + 1.25 * rn);
  float v = p.y / tk;
  float sheet = exp(-v * v);

  // Detail the ray cannot resolve is detail it should not be asking for. A ray
  // running the length of the disc steps about a tenth of a unit at a time,
  // and the finest octave is finer than that — sampled once each, those cells
  // do not average out, they beat, and the arms come out combed with dashes.
  // So the last octave fades out as the step grows.
  float lod = clamp(1.0 - dt * uGrain * 14.0, 0.0, 1.0);

  float phi = atan(p.z, p.x);
  // Kepler: omega goes as r^-3/2, so every radius turns at its own rate and
  // the clouds are read in a frame that turns with them. That shear is what
  // draws the trailing spirals — nothing here draws a spiral.
  float omega = uSpin * pow(uDiskIn / rd, 1.5);
  // A third axis, so two radii turning at their own rates do not read the same
  // cloud, plus a slow creep inward so the gas falls as well as turns.
  float lr = log(rd) * 1.1 + uSpin * uTime * 0.05;

  // Left alone, that shear never stops winding: the pattern at one radius
  // slides past its neighbour for as long as the page is open, so the spiral
  // tightens without limit and within a minute it is finer than a pixel and
  // tears into moire. Real gas is spared this because turbulence keeps
  // rebuilding it. Here two copies of the disc run the same wind on clocks
  // half a cycle apart, and the picture crossfades from one to the other, each
  // handing over while the other is still young. Nothing ever winds past one
  // cycle's worth, and the crossfade lands where its layer is weightless.
  float u = uTime / WIND_CYCLE;
  float fA = fract(u);
  float fB = fract(u + 0.5);
  float w = abs(2.0 * fA - 1.0);

  float cloudsA = fbm(vec3(vec2(cos(phi + omega * fA * WIND_CYCLE),
                                sin(phi + omega * fA * WIND_CYCLE)) * (rd * uGrain), lr), lod);
  float cloudsB = fbm(vec3(vec2(cos(phi + omega * fB * WIND_CYCLE),
                                sin(phi + omega * fB * WIND_CYCLE)) * (rd * uGrain), lr + 40.0), lod);
  float clouds = mix(cloudsA, cloudsB, w);

  // Squared for the density only, so the gaps between the filaments go
  // properly dark instead of filling in as haze. The temperature below keeps
  // reading the smooth version: heat should not have hard edges.
  float filaments = clouds * clouds * 1.75;

  // Bright at the rim, gone by the outer edge, gone again just inside it.
  float inner = smoothstep(0.0, 0.07, rn);
  float outer = 1.0 - smoothstep(0.45, 1.0, rn);
  float prof = inner * outer * pow(uDiskIn / rd, 2.0);

  dens = max(0.0, filaments * 1.5 - 0.30) * sheet * prof * uDensity * 4.6;

  // Shakura-Sunyaev: T falls as r^-3/4. The colour ramp rides it.
  heat = pow(uDiskIn / rd, 0.8) * (0.72 + 0.55 * clouds);
  tint = mix(uCool, uMid, smoothstep(0.10, 0.52, heat));
  tint = mix(tint, uHot, smoothstep(0.52, 1.05, heat));
}

/* --- stars ---------------------------------------------------------------- */

/**
 * Stars are laid out on the six faces of a cube and read through whichever
 * face the ray leaves by. A grid in space would work too, until you notice
 * that a cube of space cut by the sphere of directions is a long thin sliver,
 * and every star comes out as a scratch.
 *
 * They are drawn small on purpose. The ray arrives here already bent, so this
 * sky is a lensed sky, and lensing stretches whatever it magnifies sideways.
 * A real star has no width to stretch and stays a point that merely brightens;
 * a fat blob drawn here would smear into a long arc halfway across the frame.
 * Keeping the blob near a pixel wide holds the smear to the ring around the
 * shadow, which is the one place it belongs.
 */
vec3 starField(vec3 d) {
  vec3 a = abs(d);
  vec2 uv;
  float face;
  if (a.x >= a.y && a.x >= a.z)      { uv = d.yz / a.x; face = d.x > 0.0 ? 0.0 : 1.0; }
  else if (a.y >= a.z)               { uv = d.xz / a.y; face = d.y > 0.0 ? 2.0 : 3.0; }
  else                               { uv = d.xy / a.z; face = d.z > 0.0 ? 4.0 : 5.0; }

  vec3 col = vec3(0.0);
  for (int k = 0; k < 3; k++) {
    float sc = 90.0 * pow(2.2, float(k));
    vec2 p = uv * sc;
    vec2 id = floor(p);
    vec2 f = fract(p) - 0.5;
    float h = hash13(vec3(id, face * 19.0));
    if (h > 0.965) {
      vec2 off = vec2(hash13(vec3(id, face + 11.0)), hash13(vec3(id, face + 23.0)));
      float dd = length(f - (off - 0.5) * 0.7);
      float s = smoothstep(0.055, 0.0, dd);
      float warm = hash13(vec3(id, face + 51.0));
      col += s * (0.6 + 4.5 * fract(h * 97.0))
           * mix(vec3(0.72, 0.82, 1.0), vec3(1.0, 0.88, 0.72), warm)
           / pow(2.2, float(k));
    }
  }
  // A breath of dust, so the sky is not flat black between the points.
  col += vec3(0.013, 0.017, 0.030) * fbm(d * 2.6, 1.0);
  return col;
}

/* --- march ---------------------------------------------------------------- */

void main() {
  // The ray leaves from somewhere else inside its pixel every frame, and the
  // frames are averaged. One ray per pixel cannot resolve what happens at the
  // shadow's rim: rays that skim the photon sphere land on wildly different
  // parts of the disc for a hair's difference in aim, so a single sample there
  // is a coin toss and the rim breaks into loose pixels. Ten-odd tosses per
  // pixel, gathered over time, is what settles it.
  vec2 uv = (gl_FragCoord.xy + uJitter - uFocus * uRes) / uRes.y;
  vec3 dir = normalize(uFwd + (uv.x * uRight + uv.y * uUp) * 2.0 * uTanHalf);

  vec3 pos = uCamPos;
  vec3 vel = dir;

  // Angular momentum. Conserved, so it is read once and carried.
  vec3 hv = cross(pos, vel);
  float h2 = dot(hv, hv);
  float h = sqrt(h2);
  /** Angle swept around the hole so far. dphi/ds = h/r^2, and h is constant. */
  float swept = 0.0;

  vec3 col = vec3(0.0);
  float transmit = 1.0;
  bool captured = false;

  // Where inside its step each ray reads the gas. Always reading the middle
  // beats the step pattern against the disc into rings — worst in the halo,
  // where lensing packs a hundred radii into a few pixels. So each pixel
  // starts somewhere else, and then walks the read on by the golden ratio at
  // every step: one fixed offset per pixel is not enough, because the steps
  // themselves shorten in a smooth pattern as the ray nears the disc and a
  // fixed offset rides that pattern instead of breaking it up.
  float jitter = fract(sin(dot(gl_FragCoord.xy + uSeed, vec2(12.9898, 78.233))) * 43758.5453);

  for (int i = 0; i < MAX_STEPS; i++) {
    if (float(i) >= uSteps) break;

    float r2 = dot(pos, pos);
    float r = sqrt(r2);

    if (r < 1.0) { captured = true; break; }          // through the horizon
    if (r > uSkyR && dot(pos, vel) > 0.0) break;      // gone, and not coming back
    if (transmit < 0.004) break;                      // nothing behind this is visible

    float dt = clamp(0.14 * (r - 1.0), 0.025, 1.1);

    // Never step more than half the way to the disc plane while the disc is
    // still in radial reach, or a grazing ray tunnels clean through it.
    if (r < uDiskOut * 1.25) {
      float rn = clamp((r - uDiskIn) / max(0.001, uDiskOut - uDiskIn), 0.0, 1.0);
      float tk = uThick * (0.35 + 1.25 * rn);
      dt = min(dt, max(tk * 0.38, abs(pos.y) * 0.5));
    }

    swept += h * dt / r2;

    // How much the deeper images are worth. A ray that skims the photon sphere
    // wraps the hole again and again, and each wrap paints another, tighter
    // copy of the disc against the shadow. Those copies are real, and they are
    // faint: every extra turn costs a factor of about e^2pi. Given full
    // brightness they instead pile into a hairline ring which no single ray
    // per pixel can resolve — past the photon sphere the arrival angle swings
    // wildly between neighbouring pixels, so the ring comes out as a broken
    // string of sparks that crawl as the gas turns. Charging each turn its
    // proper cost puts it back in its place: a soft rim, not a dotted circle.
    // Half a turn is free, which leaves the halo — that one only bends.
    float deep = exp(-1.3 * max(0.0, swept - 4.6));

    jitter = fract(jitter + 0.6180339887);
    vec3 mid = pos + vel * (dt * jitter);
    float rd = length(mid.xz);

    if (rd > uDiskIn && rd < uDiskOut && abs(mid.y) < uThick * 5.0) {
      float dens;
      float heat;
      vec3 tint;
      gasAt(mid, rd, dt, dens, tint, heat);

      if (dens > 0.001) {
        // Beaming. The gas orbits at sqrt(M/r) with M = 1/2, so 0.41c at the
        // rim. g folds in the boost and the climb out of the well; flux goes
        // as g^3, and uDoppler dials that exponent down to nothing.
        vec3 tang = normalize(cross(vec3(0.0, 1.0, 0.0), vec3(mid.x, 0.0, mid.z)));
        float beta = min(0.85, sqrt(0.5 / max(rd, 1.5)));
        float gam = inversesqrt(max(1e-4, 1.0 - beta * beta));
        vec3 toObs = -normalize(vel);
        float g = 1.0 / (gam * (1.0 - beta * dot(tang, toObs)));
        g *= sqrt(max(0.05, 1.0 - 1.0 / rd));
        float boost = pow(max(g, 0.02), 3.0 * uDoppler);

        // Coming at you it also runs blue, going away it runs red.
        vec3 shift = mix(
          vec3(1.0),
          g > 1.0 ? vec3(0.86, 0.94, 1.14) : vec3(1.15, 0.82, 0.62),
          clamp(abs(g - 1.0) * 1.6, 0.0, 1.0) * uDoppler
        );

        float emit = uBright * (0.26 + 2.0 * heat * heat);
        col += tint * shift * (emit * boost * dens * transmit * dt * deep);
        transmit *= exp(-dens * 0.30 * dt);
      }
    }

    // u'' + u = 3M u^2, in Cartesian form.
    vec3 acc = -1.5 * h2 * pos / (r2 * r2 * r);
    vel += acc * dt;
    pos += vel * dt;
  }

  if (!captured && uStars > 0.001) {
    // Lensing stretches an image sideways, and a star's flux does not grow to
    // fill it: a magnified point stays as bright, it does not become a bright
    // streak. The stretch is the ratio of the angle the ray left at to the
    // angle it ended up travelling at, both measured off the line to the hole,
    // and dividing the light by it puts the flux back where it belongs. Long
    // arcs then fade as they lengthen instead of scratching across the frame.
    vec3 toHole = normalize(-uCamPos);
    float sI = length(cross(normalize(dir), toHole));
    float sS = length(cross(normalize(vel), toHole));
    float stretch = clamp(sI / max(1e-3, sS), 1.0, 40.0);
    col += starField(normalize(vel)) * uStars * transmit / stretch;
  }

  if (uEncode > 0.5) col = col / (1.0 + col);
  gl_FragColor = vec4(col, 1.0);
}
`;

  /**
   * Folds the new frame into the running average. The camera does not move, so
   * every frame lines up with the last one and there is nothing to reproject:
   * the same pixel is the same piece of sky, frame after frame. The gas does
   * move, and `uAlpha` is the price of that — the more weight the history keeps,
   * the cleaner the still and the more the moving gas smears behind itself.
   */
  const BLEND_FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uCur;
uniform sampler2D uPrev;
uniform float uAlpha;

void main() {
  vec3 c = texture2D(uCur, vUv).rgb;
  vec3 p = texture2D(uPrev, vUv).rgb;
  gl_FragColor = vec4(mix(p, c, uAlpha), 1.0);
}
`;

  /** Pulls out what is brighter than the threshold, at a quarter of the size. */
  const BRIGHT_FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uTexel;
uniform float uDecode;
uniform float uPack;
uniform float uThreshold;

void main() {
  vec3 s = texture2D(uTex, vUv + uTexel * vec2(-1.0, -1.0)).rgb
         + texture2D(uTex, vUv + uTexel * vec2( 1.0, -1.0)).rgb
         + texture2D(uTex, vUv + uTexel * vec2(-1.0,  1.0)).rgb
         + texture2D(uTex, vUv + uTexel * vec2( 1.0,  1.0)).rgb;
  s *= 0.25;
  if (uDecode > 0.5) s = s / max(vec3(0.002), 1.0 - s);
  float l = max(s.r, max(s.g, s.b));
  s *= max(0.0, l - uThreshold) / max(0.0001, l);
  gl_FragColor = vec4(s * uPack, 1.0);
}
`;

  /** Five taps, weights from a gaussian, offsets picked so the sampler pairs them. */
  const BLUR_FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uStep;

void main() {
  vec3 s = texture2D(uTex, vUv).rgb * 0.2270270;
  s += (texture2D(uTex, vUv + uStep * 1.3846154).rgb
      + texture2D(uTex, vUv - uStep * 1.3846154).rgb) * 0.3162162;
  s += (texture2D(uTex, vUv + uStep * 3.2307692).rgb
      + texture2D(uTex, vUv - uStep * 3.2307692).rgb) * 0.0702702;
  gl_FragColor = vec4(s, 1.0);
}
`;

  const COMPOSITE_FRAG = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform vec2  uRes;
uniform float uDecode;
uniform float uPack;
uniform float uGlow;
uniform float uExposure;
uniform float uVignette;
uniform float uScrimDir;
uniform float uScrimAmt;
uniform float uSeed;

vec3 aces(vec3 x) {
  return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
  vec3 scene = texture2D(uScene, vUv).rgb;
  if (uDecode > 0.5) scene = scene / max(vec3(0.002), 1.0 - scene);
  vec3 bloom = texture2D(uBloom, vUv).rgb / uPack;

  vec3 c = scene + bloom * uGlow;
  c = aces(c * uExposure);
  c = pow(max(c, 0.0), vec3(0.4545));

  // Corners down.
  vec2 d = vUv - 0.5;
  c *= 1.0 - uVignette * dot(d, d) * 1.9;

  // The edge the copy sits on: heavy at the edge, off quickly, so the middle
  // of the frame keeps its contrast instead of going grey.
  if (uScrimDir > 0.5) {
    float x = uScrimDir < 1.5 ? vUv.x
            : uScrimDir < 2.5 ? 1.0 - vUv.x
            : uScrimDir < 3.5 ? 1.0 - vUv.y
            : vUv.y;
    c *= 1.0 - uScrimAmt * pow(1.0 - clamp(x, 0.0, 1.0), 2.4);
  }

  // A grain of dither. Without it these long dark ramps band into rings.
  float n = fract(sin(dot(gl_FragCoord.xy + uSeed, vec2(12.9898, 78.233))) * 43758.5453);
  c += (n - 0.5) / 255.0;

  gl_FragColor = vec4(c, 1.0);
}
`;

  /* -------------------------------------------------------------------- */
  /*  Small helpers                                                       */
  /* -------------------------------------------------------------------- */

  /** Hex to linear light. The shader works in linear and gamma-encodes at the end. */
  function hexToLinear(hex) {
    const h = String(hex).trim().replace("#", "");
    const full = h.length === 3 ? h[0] + h[0] + h[1] + h[1] + h[2] + h[2] : h.slice(0, 6);
    const n = parseInt(full, 16) || 0;
    const srgb = [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
    return srgb.map((v) => (v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
  }

  /**
   * Sub-pixel aim points, eight of them, from the Halton 2,3 sequence. They
   * spread across the pixel far more evenly than eight random draws would,
   * which is the whole job: the average has to cover the pixel, not clump in
   * one corner of it.
   */
  const HALTON = [
    [0.5, 0.333], [0.25, 0.667], [0.75, 0.111], [0.125, 0.444],
    [0.625, 0.778], [0.375, 0.222], [0.875, 0.556], [0.0625, 0.889],
  ];

  /** Default props, identical to BlackHoleHeroSectionProps' defaults in the source component. */
  const DEFAULTS = Object.freeze({
    distance: 24,
    elevation: -5.5,
    azimuth: 0,
    orbitSpeed: 0,
    roll: -20,
    fov: 42,
    diskInner: 3,
    diskOuter: 15,
    diskThickness: 0.26,
    diskDensity: 1,
    brightness: 1,
    spinSpeed: 0.06,
    grain: 0.48,
    doppler: 0.35,
    hotColor: "#FFF3DE",
    midColor: "#FF9838",
    coolColor: "#8E3A0B",
    starBrightness: 0,
    glow: 1,
    exposure: 0.9,
    vignette: 0.28,
    steps: 300,
    resolution: 0.7,
    maxDpr: 1.75,
    focus: [0.72, 0.46],
    scrim: "none",
    scrimStrength: 0.9,
    paused: false,
  });

  const SCRIM_VALUES = new Set(["none", "left", "right", "top", "bottom"]);

  function isFiniteNumber(value) {
    return typeof value === "number" && isFinite(value);
  }

  /**
   * Merges `incoming` onto `base`, keeping `base`'s value for anything missing,
   * malformed, or of the wrong type — options come from a Jinja/data-attribute
   * boundary, not from typed React props, so this is where "잘못된 값이 들어와도
   * 오류가 나지 않게" is enforced without changing the result for valid input.
   */
  function mergeOptions(base, incoming) {
    const next = Object.assign({}, base);
    if (!incoming || typeof incoming !== "object") return next;
    for (const key of Object.keys(base)) {
      if (!(key in incoming)) continue;
      const value = incoming[key];
      if (key === "hotColor" || key === "midColor" || key === "coolColor") {
        if (typeof value === "string" && /^#?[0-9a-fA-F]{3,6}$/.test(value.replace("#", ""))) next[key] = value;
      } else if (key === "scrim") {
        if (SCRIM_VALUES.has(value)) next[key] = value;
      } else if (key === "paused") {
        next[key] = Boolean(value);
      } else if (key === "focus") {
        if (Array.isArray(value) && value.length === 2 && isFiniteNumber(value[0]) && isFiniteNumber(value[1])) {
          next[key] = [value[0], value[1]];
        }
      } else if (isFiniteNumber(value)) {
        next[key] = value;
      }
    }
    return next;
  }

  class BlackHoleHeroRenderer {
    /**
     * @param {HTMLElement} container Host element; must contain a child
     *   matching `[data-blackhole-canvas]`, mirroring the original's
     *   `hostRef`/`canvasRef` pair.
     * @param {object} [options] See DEFAULTS above for every supported key.
     */
    constructor(container, options) {
      this.host = container || null;
      this.canvas = this.host ? this.host.querySelector("[data-blackhole-canvas]") : null;
      this.options = mergeOptions(DEFAULTS, options);
      this.gl = null;
      this._destroyed = false;
      this._running = false;
      this.init();
    }

    /** React props -> new props, without tearing down the WebGL context. */
    updateOptions(partial) {
      this.options = mergeOptions(this.options, partial);
    }

    /* --- lifecycle --------------------------------------------------- */

    init() {
      const host = this.host;
      const canvas = this.canvas;
      if (!host || !canvas) { this._giveUp("missing-dom"); return; }

      this.reduced = typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      const opts = {
        alpha: false, antialias: false, depth: false, stencil: false,
        powerPreference: "high-performance", preserveDrawingBuffer: false,
      };
      const gl = canvas.getContext("webgl2", opts) || canvas.getContext("webgl", opts);

      if (!gl) { this._giveUp("unsupported"); return; }
      this.gl = gl;

      // Software renderers - a machine with no GPU, a virtual desktop, a CI
      // runner - run this shader at seconds per frame, and the browser kills
      // the context for hanging. Spotting one and dropping to a cheap setting
      // is the difference between a picture and a dead canvas.
      const dbg = gl.getExtension("WEBGL_debug_renderer_info");
      const rendererName = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || "") : "";
      this.software = /swiftshader|llvmpipe|softpipe|software|microsoft basic/i.test(rendererName);
      this.isGL2 = typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext;

      this._setupHdr();

      this.sceneProg = null;
      this.blendProg = null;
      this.brightProg = null;
      this.blurProg = null;
      this.compProg = null;
      this.vbo = null;
      this.scene = null;
      this.histA = null;
      this.histB = null;
      this.bloomA = null;
      this.bloomB = null;
      /** Frames folded into the running average since it was last thrown away. */
      this.settled = 0;

      this.width = 0;
      this.height = 0;
      this.sceneW = 0;
      this.sceneH = 0;

      /** Simulation clock, in seconds. Advances only while the thing is running. */
      this.clock = this.reduced ? 6 : 0;
      this.lastFrame = 0;
      this.visible = true;
      this.raf = 0;

      if (!this._build()) { this._giveUp("build-failed"); return; }
      this._running = true;
      this._resize();
      this._settle(this.reduced ? 16 : 1);
      if (!this.reduced) this.raf = requestAnimationFrame(this._tick.bind(this));

      this._bindWorldEvents();
    }

    _setupHdr() {
      const gl = this.gl;
      // Half floats keep the gas bright enough to bloom properly. Where they
      // are missing the scene is packed with Reinhard into 8 bits instead and
      // unpacked on the way out - coarser, but it holds the highlights.
      let hdr = true;
      let texType = gl.UNSIGNED_BYTE;
      let internal = gl.RGBA;
      if (this.isGL2) {
        const ok = gl.getExtension("EXT_color_buffer_half_float") || gl.getExtension("EXT_color_buffer_float");
        if (ok) { texType = gl.HALF_FLOAT; internal = gl.RGBA16F; } else hdr = false;
      } else {
        const hf = gl.getExtension("OES_texture_half_float");
        const cb = gl.getExtension("EXT_color_buffer_half_float");
        if (hf && cb) texType = hf.HALF_FLOAT_OES; else hdr = false;
      }
      if (!hdr) { texType = gl.UNSIGNED_BYTE; internal = gl.RGBA; }
      const linearOK = this.isGL2 || !!gl.getExtension("OES_texture_half_float_linear") || !hdr;
      this.hdr = hdr;
      this.texType = texType;
      this.internal = internal;
      this.filter = linearOK ? gl.LINEAR : gl.NEAREST;
      /** Bloom is scaled down before it goes into 8 bits, and scaled back after. */
      this.pack = hdr ? 1 : 0.12;
    }

    /**
     * Take the canvas out of the picture and leave the black background and
     * whatever content sits on it. A canvas whose context has died does not go
     * quietly: it paints white, or the browser's broken-image mark, straight
     * over the background - which is worse than showing nothing at all.
     */
    _giveUp(why) {
      if (this.host) this.host.dataset.webgl = why;
      if (this.canvas) this.canvas.style.display = "none";
      if (!this._loggedFailure) {
        this._loggedFailure = true;
        console.error("blackhole-hero: falling back to static background —", why);
      }
    }

    /* --- shader plumbing ---------------------------------------------- */

    _compile(type, src) {
      const gl = this.gl;
      const sh = gl.createShader(type);
      if (!sh) return null;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        // Short and once per shader. When a context dies every shader fails at
        // the same moment with an empty log, and dumping five listings of GLSL
        // into the console buries whatever the real problem was.
        console.error("blackhole-hero: shader failed —", gl.getShaderInfoLog(sh) || "no log (context lost?)");
        gl.deleteShader(sh);
        return null;
      }
      return sh;
    }

    _link(fragSrc) {
      const gl = this.gl;
      const vs = this._compile(gl.VERTEX_SHADER, VERT);
      const fs = this._compile(gl.FRAGMENT_SHADER, fragSrc);
      if (!vs || !fs) return null;
      const program = gl.createProgram();
      if (!program) return null;
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.bindAttribLocation(program, 0, "aPos");
      gl.linkProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        console.error("blackhole-hero: program link failed —", gl.getProgramInfoLog(program));
        return null;
      }
      const u = {};
      const n = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS);
      for (let i = 0; i < n; i++) {
        const info = gl.getActiveUniform(program, i);
        if (info) u[info.name] = gl.getUniformLocation(program, info.name);
      }
      return { program, u };
    }

    _build() {
      const gl = this.gl;
      this.sceneProg = this._link(SCENE_FRAG);
      this.blendProg = this._link(BLEND_FRAG);
      this.brightProg = this._link(BRIGHT_FRAG);
      this.blurProg = this._link(BLUR_FRAG);
      this.compProg = this._link(COMPOSITE_FRAG);
      if (!this.sceneProg || !this.blendProg || !this.brightProg || !this.blurProg || !this.compProg) return false;

      // One triangle, big enough to cover the frame. Cheaper than two, and no
      // seam down the diagonal.
      this.vbo = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.BLEND);
      return true;
    }

    /* --- render targets ------------------------------------------------ */

    _makeTarget(w, h) {
      const gl = this.gl;
      const tex = gl.createTexture();
      const fb = gl.createFramebuffer();
      if (!tex || !fb) return null;
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, this.internal, w, h, 0, gl.RGBA, this.texType, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, this.filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, this.filter);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      if (status !== gl.FRAMEBUFFER_COMPLETE) {
        gl.deleteTexture(tex);
        gl.deleteFramebuffer(fb);
        return null;
      }
      return { fb, tex, w, h };
    }

    _dropTargets() {
      const gl = this.gl;
      for (const t of [this.scene, this.histA, this.histB, this.bloomA, this.bloomB]) {
        if (!t) continue;
        gl.deleteTexture(t.tex);
        gl.deleteFramebuffer(t.fb);
      }
      this.scene = null;
      this.histA = null;
      this.histB = null;
      this.bloomA = null;
      this.bloomB = null;
      this.settled = 0;
    }

    _resize() {
      const gl = this.gl;
      const rect = this.host.getBoundingClientRect();
      const dpr = this.software ? 1 : Math.min(window.devicePixelRatio || 1, Math.max(1, this.options.maxDpr));
      const cssW = Math.max(1, Math.round(rect.width));
      const cssH = Math.max(1, Math.round(rect.height));
      const scale = this.software ? 0.34 : Math.min(1, Math.max(0.4, this.options.resolution));
      const w = Math.max(2, Math.round(cssW * dpr));
      const h = Math.max(2, Math.round(cssH * dpr));
      const sw = Math.max(2, Math.round(w * scale));
      const sh = Math.max(2, Math.round(h * scale));
      if (w === this.width && h === this.height && sw === this.sceneW && sh === this.sceneH) return;
      this.width = w;
      this.height = h;
      this.sceneW = sw;
      this.sceneH = sh;
      this.canvas.width = w;
      this.canvas.height = h;
      this.canvas.style.width = cssW + "px";
      this.canvas.style.height = cssH + "px";
      this._dropTargets();
      this.scene = this._makeTarget(sw, sh);
      this.histA = this._makeTarget(sw, sh);
      this.histB = this._makeTarget(sw, sh);
      const bw = Math.max(2, sw >> 2);
      const bh = Math.max(2, sh >> 2);
      this.bloomA = this._makeTarget(bw, bh);
      this.bloomB = this._makeTarget(bw, bh);
      void gl; // targets already bound via _makeTarget; kept for readability
    }

    /* --- draw ------------------------------------------------------------ */

    _pass(prog, target) {
      const gl = this.gl;
      gl.useProgram(prog.program);
      gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
      gl.viewport(0, 0, target ? target.w : this.width, target ? target.h : this.height);
    }

    _draw() {
      this.gl.drawArrays(this.gl.TRIANGLES, 0, 3);
    }

    _bindTex(tex, unit) {
      const gl = this.gl;
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, tex);
    }

    _render(t) {
      const gl = this.gl;
      if (!this.sceneProg || !this.blendProg || !this.brightProg || !this.blurProg || !this.compProg) return;
      if (!this.scene || !this.histA || !this.histB || !this.bloomA || !this.bloomB) return;
      const C = this.options;

      // Camera: an orbit about the hole, at a fixed height above the disc.
      const az = (C.azimuth + C.orbitSpeed * t) * RAD;
      const el = Math.max(-88, Math.min(88, C.elevation)) * RAD;
      const dist = Math.max(2.2, C.distance);
      const ce = Math.cos(el);
      const camX = dist * ce * Math.cos(az);
      const camY = dist * Math.sin(el);
      const camZ = dist * ce * Math.sin(az);

      // Look at the hole. Then roll about the line of sight, which changes
      // nothing in space and only decides how the disc lies across the frame.
      const fx = -camX / dist, fy = -camY / dist, fz = -camZ / dist;
      let rx = fz, ry = 0, rz = -fx; // cross(fwd, worldUp), worldUp = +y
      const rl = Math.hypot(rx, ry, rz) || 1;
      rx /= rl; ry /= rl; rz /= rl;
      const ux = ry * fz - rz * fy;
      const uy = rz * fx - rx * fz;
      const uz = rx * fy - ry * fx;
      const cr = Math.cos(C.roll * RAD);
      const sr = Math.sin(C.roll * RAD);
      const RX = rx * cr + ux * sr, RY = ry * cr + uy * sr, RZ = rz * cr + uz * sr;
      const UX = -rx * sr + ux * cr, UY = -ry * sr + uy * cr, UZ = -rz * sr + uz * cr;

      const hot = hexToLinear(C.hotColor);
      const mid = hexToLinear(C.midColor);
      const cool = hexToLinear(C.coolColor);
      const outer = Math.max(C.diskInner + 0.5, C.diskOuter);

      /* scene ------------------------------------------------------------- */
      this._pass(this.sceneProg, this.scene);
      const u = this.sceneProg.u;
      gl.uniform2f(u.uRes, this.scene.w, this.scene.h);
      gl.uniform1f(u.uTime, t);
      gl.uniform3f(u.uCamPos, camX, camY, camZ);
      gl.uniform3f(u.uRight, RX, RY, RZ);
      gl.uniform3f(u.uUp, UX, UY, UZ);
      gl.uniform3f(u.uFwd, fx, fy, fz);
      gl.uniform1f(u.uTanHalf, Math.tan(Math.max(8, Math.min(110, C.fov)) * 0.5 * RAD));
      // gl_FragCoord counts up from the bottom; the option reads from the top.
      gl.uniform2f(u.uFocus, C.focus[0], 1 - C.focus[1]);
      gl.uniform1f(u.uSteps, this.software ? 130 : Math.max(60, Math.min(460, Math.round(C.steps))));
      gl.uniform1f(u.uSkyR, Math.max(dist * 1.35, outer * 2.4));
      gl.uniform1f(u.uDiskIn, Math.max(1.05, C.diskInner));
      gl.uniform1f(u.uDiskOut, outer);
      gl.uniform1f(u.uThick, Math.max(0.02, C.diskThickness));
      gl.uniform1f(u.uDensity, Math.max(0, C.diskDensity));
      gl.uniform1f(u.uSpin, C.spinSpeed * 6.2831853);
      gl.uniform1f(u.uGrain, Math.max(0.02, C.grain));
      gl.uniform1f(u.uBright, Math.max(0, C.brightness));
      gl.uniform1f(u.uDoppler, Math.max(0, Math.min(1, C.doppler)));
      gl.uniform3f(u.uHot, hot[0], hot[1], hot[2]);
      gl.uniform3f(u.uMid, mid[0], mid[1], mid[2]);
      gl.uniform3f(u.uCool, cool[0], cool[1], cool[2]);
      gl.uniform1f(u.uStars, Math.max(0, C.starBrightness));
      gl.uniform1f(u.uEncode, this.hdr ? 0 : 1);
      const h = HALTON[this.settled % HALTON.length];
      gl.uniform2f(u.uJitter, h[0] - 0.5, h[1] - 0.5);
      gl.uniform1f(u.uSeed, (this.settled % 64) * 17.13);
      this._draw();

      /* fold into the running average --------------------------------- */
      // Weight enough history to bury the noise, but not so much that the gas
      // drags a tail. The first frame after a resize takes the whole picture,
      // since there is no history worth keeping.
      const alpha = this.settled === 0 ? 1 : 0.14;
      this._pass(this.blendProg, this.histB);
      this._bindTex(this.scene.tex, 0);
      this._bindTex(this.histA.tex, 1);
      gl.uniform1i(this.blendProg.u.uCur, 0);
      gl.uniform1i(this.blendProg.u.uPrev, 1);
      gl.uniform1f(this.blendProg.u.uAlpha, alpha);
      this._draw();
      const shown = this.histB;
      const tmp = this.histA;
      this.histA = this.histB;
      this.histB = tmp;
      this.settled++;

      /* bright pass ------------------------------------------------------ */
      this._pass(this.brightProg, this.bloomA);
      this._bindTex(shown.tex, 0);
      gl.uniform1i(this.brightProg.u.uTex, 0);
      gl.uniform2f(this.brightProg.u.uTexel, 1 / shown.w, 1 / shown.h);
      gl.uniform1f(this.brightProg.u.uDecode, this.hdr ? 0 : 1);
      gl.uniform1f(this.brightProg.u.uPack, this.pack);
      gl.uniform1f(this.brightProg.u.uThreshold, 0.85);
      this._draw();

      /* two rounds of blur, the second wider ------------------------------ */
      const blurStep = (src, dst, dx, dy) => {
        this._pass(this.blurProg, dst);
        this._bindTex(src.tex, 0);
        gl.uniform1i(this.blurProg.u.uTex, 0);
        gl.uniform2f(this.blurProg.u.uStep, dx / dst.w, dy / dst.h);
        this._draw();
      };
      blurStep(this.bloomA, this.bloomB, 1, 0);
      blurStep(this.bloomB, this.bloomA, 0, 1);
      blurStep(this.bloomA, this.bloomB, 2.6, 0);
      blurStep(this.bloomB, this.bloomA, 0, 2.6);

      /* composite ---------------------------------------------------------- */
      this._pass(this.compProg, null);
      this._bindTex(shown.tex, 0);
      this._bindTex(this.bloomA.tex, 1);
      gl.uniform1i(this.compProg.u.uScene, 0);
      gl.uniform1i(this.compProg.u.uBloom, 1);
      gl.uniform2f(this.compProg.u.uRes, this.width, this.height);
      gl.uniform1f(this.compProg.u.uDecode, this.hdr ? 0 : 1);
      gl.uniform1f(this.compProg.u.uPack, this.pack);
      gl.uniform1f(this.compProg.u.uGlow, Math.max(0, C.glow) * 0.26);
      gl.uniform1f(this.compProg.u.uExposure, Math.max(0.05, C.exposure));
      gl.uniform1f(this.compProg.u.uVignette, Math.max(0, Math.min(1, C.vignette)));
      gl.uniform1f(
        this.compProg.u.uScrimDir,
        C.scrim === "left" ? 1 : C.scrim === "right" ? 2 : C.scrim === "top" ? 3 : C.scrim === "bottom" ? 4 : 0
      );
      gl.uniform1f(this.compProg.u.uScrimAmt, Math.max(0, Math.min(1, C.scrimStrength)));
      gl.uniform1f(this.compProg.u.uSeed, (t * 60) % 1000);
      this._draw();
    }

    /**
     * Draws one still, properly. Nothing is animating in these cases — a
     * resize while paused, or a reader who has asked for no motion — so the
     * frames the average would normally be given over time are taken all at
     * once instead. Each pass aims at a different point inside the pixel, so
     * what lands on screen is settled rather than speckled.
     */
    _settle(passes) {
      for (let i = 0; i < passes; i++) this._render(this.clock);
    }

    /* --- loop -------------------------------------------------------- */

    _tick(now) {
      if (!this._running) return;
      this.raf = requestAnimationFrame(this._tick.bind(this));
      if (!this.visible) { this.lastFrame = now; return; }
      const dt = this.lastFrame ? Math.min(0.05, (now - this.lastFrame) / 1000) : 0;
      this.lastFrame = now;
      if (!this.options.paused && !this.reduced) this.clock += dt;
      this._render(this.clock);
    }

    /* --- the world ------------------------------------------------------- */

    _bindWorldEvents() {
      const host = this.host;
      const canvas = this.canvas;

      this._onResize = () => {
        this._resize();
        if (this.reduced || this.options.paused) this._settle(16);
      };
      this._resizeObserver = new ResizeObserver(this._onResize);
      this._resizeObserver.observe(host);

      this._onIntersect = (entries) => { this.visible = entries[0] ? entries[0].isIntersecting : true; };
      this._intersectionObserver = new IntersectionObserver(this._onIntersect, { threshold: 0 });
      this._intersectionObserver.observe(host);

      this._onVisibility = () => { this.visible = !document.hidden; this.lastFrame = 0; };
      document.addEventListener("visibilitychange", this._onVisibility);

      this._onLost = (event) => {
        // Asking for the context back is only worth it if it comes back
        // working. Until it does, the canvas stays hidden — a dead context
        // paints white.
        event.preventDefault();
        this._running = false;
        if (this.raf) cancelAnimationFrame(this.raf);
        canvas.style.display = "none";
      };
      canvas.addEventListener("webglcontextlost", this._onLost);

      this._onRestored = () => {
        this.width = this.height = this.sceneW = this.sceneH = 0;
        if (!this._build()) { this._giveUp("lost"); return; }
        canvas.style.display = "";
        host.dataset.webgl = "";
        this._resize();
        this._running = true;
        this.lastFrame = 0;
        this._settle(this.reduced ? 16 : 1);
        if (!this.reduced) this.raf = requestAnimationFrame(this._tick.bind(this));
      };
      canvas.addEventListener("webglcontextrestored", this._onRestored);
    }

    /* --- teardown ------------------------------------------------------ */

    destroy() {
      if (this._destroyed) return;
      this._destroyed = true;
      this._running = false;
      if (this.raf) cancelAnimationFrame(this.raf);
      if (this._resizeObserver) this._resizeObserver.disconnect();
      if (this._intersectionObserver) this._intersectionObserver.disconnect();
      if (this._onVisibility) document.removeEventListener("visibilitychange", this._onVisibility);
      if (this.canvas) {
        if (this._onLost) this.canvas.removeEventListener("webglcontextlost", this._onLost);
        if (this._onRestored) this.canvas.removeEventListener("webglcontextrestored", this._onRestored);
      }
      const gl = this.gl;
      if (gl) {
        this._dropTargets();
        if (this.vbo) gl.deleteBuffer(this.vbo);
        for (const p of [this.sceneProg, this.blendProg, this.brightProg, this.blurProg, this.compProg]) {
          if (p) gl.deleteProgram(p.program);
        }
        // The context is deliberately left alive rather than forced lost:
        // this page never tears the canvas down and rebuilds it in place
        // (breakpoint changes go through updateOptions(), not a fresh
        // construct), so there is no double-init to guard against here.
        // Deleting what was allocated is enough; the context goes when the
        // canvas does.
      }
    }
  }

  window.BlackHoleHeroRenderer = BlackHoleHeroRenderer;
})();
