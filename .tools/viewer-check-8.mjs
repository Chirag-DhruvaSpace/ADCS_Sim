
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
/* Optional decoders — loaded defensively in case the GLB needs them */
let DRACOLoader, KTX2Loader, MeshoptDecoder;
try { DRACOLoader   = (await import('three/addons/loaders/DRACOLoader.js')).DRACOLoader; } catch(e) {}
try { KTX2Loader    = (await import('three/addons/loaders/KTX2Loader.js')).KTX2Loader; } catch(e) {}
try { MeshoptDecoder = (await import('three/addons/libs/meshopt_decoder.module.js')).MeshoptDecoder; } catch(e) {}

/* =====================================================================
   CONFIG — everything tweakable for coders. End-users: ⚙ Settings panel.
   ===================================================================== */
const CONFIG = {
  MODEL_URL:      "/static/models/P-30XL-deployed.glb",
  MODEL_COM:      [-0.01855, -0.01489, -0.16821],
  MODEL_SCALE:    1.0,                           // CAD export uses SI metres
  AXIS_LEN:       1500.0,                        // was axisLength in Cesium code
  DIRLINE_LEN:    3000.0,                        // was sunLineLength
  CHASE_VIEW_FROM:[-4.8, 0.0, 1.8],              // close enough to read the spacecraft against Earth
  PAYLOAD_OFFSET: [0.0, 15.0, 0.0],              // was camOffsetBody
  FOV_DEG:        60,

  /* performance (the ⚙ preset overrides budget/concurrent; sharpness in SETTINGS) */
  PIXEL_RATIO_CAP: 2.0,
  TILE_BUDGET:    160,      // max visible tiles (main view)
  STREAM_TILE_BUDGET: 48,   // max visible tiles for the payload stream view
  CREATE_BUDGET:  40,       // new tiles created per 250ms update (main view)
  CREATE_STREAM_BUDGET: 12, // new tiles created per update for the payload stream
  CACHE_MAX:      320,      // tiles kept in memory
  TARGET_PX:      170,      // tile screen-px threshold (overridden by SETTINGS.sharp)
  MAX_Z:          19,
  MIN_TILED_Z:    3,        // tiles always cover the globe down to this level
  MAX_CONCURRENT: 10,
  SMOOTH:         5,

  /* night side */
  NIGHT_BOOST:    3.2,
  MOONLIGHT:      [0.045, 0.055, 0.075],

  /* sun / moon ("at infinity", camera-anchored) */
  CAMERA_FAR:       2.0e8,
  SUN_RENDER_DIST:  1.3e8,
  SUN_GLARE_SIZE:   6.5e6,
  MOON_RENDER_DIST: 6.0e7,
  MOON_RADIUS:      2.71e5,
  STAR_RADIUS:      1.4e8,
  HAZE_RADIUS:      1.3e8,

  /* chase camera */
  CHASE_ROT_SENS:  0.004,
  CHASE_ZOOM_SENS: 0.0012,
  CHASE_MIN_DIST:  0.05,
  CHASE_MAX_DIST:  5.0e7,
  FREE_MAX_DIST:   8.0e7,

  /* model look */
  SUN_INTENSITY:  2.8,
  MODEL_ENV:      0.45,
  MODEL_COLORIZE: true,

  CLOCK_SOURCE:   'telemetry',
  STREAM_URL:     'ws://localhost:8765',
  STREAM_MS:      1000,
  STREAM_SOURCE:  'payload', // 'payload' | 'fixed' (legacy static 77E/13N view)

  /* tile crossfade — fades happen OVER the parent layer, never into black */
  TILE_FADE_MS:   300,
};
/* Esri World Imagery (satellite). For OSM map style use:
   (z,x,y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`  (note x/y order!) */
const TILE_URL = (z, x, y) =>
  `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;

const TEX_DAY = '/static/textures/earth-day.jpg';
const TEX_WATER = '/static/textures/earth-water.png';
const TEX_MOON = '/static/textures/moon.jpg';
const TEX_CLOUDS_HIGH = '/static/textures/8k_earth_clouds.jpg';
const TEX_CLOUDS_2K = '/static/textures/2k_earth_clouds.jpg';

const MODEL_EXTRA_ROTATION = new THREE.Euler(0, 0, 0);

/* =====================================================================
   User settings (live, persisted) — bound to the ⚙ panel
   ===================================================================== */
const SETTINGS = {
  preset: 'auto', fps: false, simFeed: true,
  attLock: false, chaseSens: 1.0,
  exposure: 1.0, night: 1.0, city: 1.0, atmo: 1.0,
  cloudsOn: true, clouds: 0.22,
  stars: 1.0, sunSize: 1.0, moonSize: 1.0,
  modelSun: 1.0, modelEnv: 1.0,
  sharp: 170,
  smoothAttitude: true,
  streamOn: true, streamQ: 0.9, streamW: 800, streamH: 600,
};
try { const s = JSON.parse(localStorage.getItem('sat3d-settings-v2')); if (s) Object.assign(SETTINGS, s); } catch (e) {}
if (!SETTINGS.smoothingRevision) { SETTINGS.smoothAttitude = true; SETTINGS.smoothingRevision = 1; }
// The former default cloud density hid the high-resolution surface imagery.
if (!SETTINGS.cloudClarityRevision) { if (SETTINGS.clouds === 0.85) SETTINGS.clouds = 0.38; SETTINGS.cloudClarityRevision = 1; }
if (!SETTINGS.cloudClarityRevision2) { if (SETTINGS.clouds === 0.38) SETTINGS.clouds = 0.22; SETTINGS.cloudClarityRevision2 = 1; }
for (const key of ['showSun', 'showGyro', 'showMag', 'sensorGlow', 'smoothAttitude']) {
  if (SETTINGS[key] === undefined) SETTINGS[key] = true;
  document.getElementById('set-' + key).checked = SETTINGS[key];
  document.getElementById('set-' + key).addEventListener('change', e => {
    SETTINGS[key] = e.target.checked; saveSettings();
  });
}
function saveSettings() { try { localStorage.setItem('sat3d-settings-v2', JSON.stringify(SETTINGS)); } catch (e) {} }

/* =====================================================================
   Constants / helpers
   ===================================================================== */
const DEG = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sstep = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
const WGS84_A  = 6378137.0;
const WGS84_E2 = 0.00669437999014;
const EARTH_R_MEAN = 6371000.0;
const EARTH_CIRC   = 40075016.686;
const FOV = CONFIG.FOV_DEG * DEG;
const $ = (id) => document.getElementById(id);
const updateInterval = 250;

function latLonToECEF(latDeg, lonDeg, h, out = new THREE.Vector3()) {
  const lat = latDeg * DEG, lon = lonDeg * DEG;
  const sl = Math.sin(lat), cl = Math.cos(lat);
  const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
  return out.set((N + h) * cl * Math.cos(lon),
                 (N + h) * cl * Math.sin(lon),
                 (N * (1 - WGS84_E2) + h) * sl);
}
function tile2lat(y, z) {
  const n = Math.PI - 2 * Math.PI * y / (1 << z);
  return Math.atan(Math.sinh(n)) / DEG;
}
function lat2tileY(latDeg, z) {
  const c = clamp(latDeg, -85.05112878, 85.05112878) * DEG;
  const y = 0.5 - Math.log(Math.tan(c) + 1 / Math.cos(c)) / (2 * Math.PI);
  return clamp(Math.floor(y * (1 << z)), 0, (1 << z) - 1);
}
function raySphereHit(origin, dir, radius, out) {
  if (!out) return null;
  const b = 2 * origin.dot(dir);
  const c = origin.lengthSq() - radius * radius;
  const disc = b * b - 4 * c;
  if (disc < 0) return null;
  let t = (-b - Math.sqrt(disc)) / 2;
  if (t < 0) t = (-b + Math.sqrt(disc)) / 2;
  if (t < 0) return null;
  return out.copy(dir).multiplyScalar(t).add(origin);
}
function wrap180(d) { d %= 360; if (d > 180) d -= 360; else if (d < -180) d += 360; return d; }
function parseUTCDate(ts) {
  if (!ts || typeof ts !== 'string') return null;
  let iso = ts.trim();
  if (iso.includes(' ') && !iso.includes('T')) iso = iso.replace(' ', 'T') + 'Z';
  if (iso.includes('+') && iso.endsWith('Z')) iso = iso.slice(0, -1);
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

/* =====================================================================
   Renderer / scene / cameras
   ===================================================================== */
const container = $('threeContainer');
const renderer = new THREE.WebGLRenderer({
  antialias: true, powerPreference: 'high-performance', logarithmicDepthBuffer: true
});
let curDpr = Math.min(window.devicePixelRatio || 1, CONFIG.PIXEL_RATIO_CAP);
renderer.setPixelRatio(curDpr);
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
container.appendChild(renderer.domElement);
const MAX_ANISO = Math.min(16, renderer.capabilities.getMaxAnisotropy());

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000000);

const camera = new THREE.PerspectiveCamera(CONFIG.FOV_DEG, container.clientWidth / container.clientHeight, 0.02, CONFIG.CAMERA_FAR);
new ResizeObserver(() => {
  if (!container.clientWidth || !container.clientHeight) return;
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
}).observe(container);
camera.position.set(0, 0, 0);
const payloadCamera = new THREE.PerspectiveCamera(CONFIG.FOV_DEG, SETTINGS.streamW / SETTINGS.streamH, 1.0, CONFIG.CAMERA_FAR);
payloadCamera.position.set(0, 0, 0);

const sunDirVec = new THREE.Vector3(1, 0.2, 0.35).normalize();
const sunLight = new THREE.DirectionalLight(0xffffff, CONFIG.SUN_INTENSITY);
sunLight.position.copy(sunDirVec).multiplyScalar(1e6);
scene.add(sunLight, sunLight.target);
scene.add(new THREE.AmbientLight(0xffffff, 0.16));
scene.add(new THREE.HemisphereLight(0x30405a, 0x090909, 0.20));

try {
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  pmrem.dispose();
} catch (e) { console.warn('Environment map unavailable:', e); }

const texLoader = new THREE.TextureLoader();
function solidTex(r, g, b) {
  const c = document.createElement('canvas'); c.width = c.height = 1;
  const x = c.getContext('2d'); x.fillStyle = `rgb(${r},${g},${b})`; x.fillRect(0, 0, 1, 1);
  return new THREE.CanvasTexture(c);
}
function loadTex(url, srgb, onOK, onErr) {
  texLoader.load(url, t => {
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = MAX_ANISO;
    onOK(t);
  }, undefined, () => { if (onErr) onErr(); });
}

/* =====================================================================
   EARTH — imagery colors shown directly (Cesium-like), no tonemap
   ===================================================================== */
const moonlightBase = new THREE.Vector3(...CONFIG.MOONLIGHT);
const moonTintVec = moonlightBase.clone();

function buildEllipsoidGeometry(segLat, segLon, scaleMult, liftM, withUV) {
  const pos = [], nor = [], uv = [], idx = [];
  for (let i = 0; i <= segLat; i++) {
    const lat = 90 - 180 * i / segLat;
    const cl = Math.cos(lat * DEG), sl = Math.sin(lat * DEG);
    for (let j = 0; j <= segLon; j++) {
      const lon = -180 + 360 * j / segLon;
      const co = Math.cos(lon * DEG), so = Math.sin(lon * DEG);
      const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
      pos.push((N + liftM) * cl * co * scaleMult,
               (N + liftM) * cl * so * scaleMult,
               (N * (1 - WGS84_E2) + liftM) * sl * scaleMult);
      nor.push(cl * co, cl * so, sl);
      if (withUV) uv.push((lon + 180) / 360, (lat + 90) / 180);
    }
  }
  const S1 = segLon + 1;
  for (let i = 0; i < segLat; i++) for (let j = 0; j < segLon; j++) {
    const a = i * S1 + j, b = a + 1, c = a + S1, d = c + 1;
    idx.push(a, c, b, b, c, d);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal',   new THREE.Float32BufferAttribute(nor, 3));
  if (withUV) g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

/* direct, saturated color output shared by earth shaders */
const COLOR_FIX_GLSL = `
  float lum = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(vec3(lum), col, 1.05);                 /* saturation punch */
  col = col / (1.0 + max(vec3(0.0), col - 1.0));   /* soft highlight shoulder */
`;
// Night terrain remains visible under weak moonlight. No synthetic city dots.
const NIGHT_SURFACE_GLSL = `
  vec3 nativeNight(vec3 surface, float water, float boost) {
    vec3 moonlit = surface * max(moonTint * (0.8 + 0.2 * boost), vec3(.13));
    return moonlit;
  }
`;

const baseMat = new THREE.ShaderMaterial({
  uniforms: {
    dayMap:   { value: solidTex(20, 45, 90) },
    cityMap:  { value: solidTex(0, 0, 0) },
    cityVisibility: { value: 0 },
    waterMap: { value: solidTex(0, 0, 0) },
    sunDir:   { value: sunDirVec },
    nightBoost: { value: CONFIG.NIGHT_BOOST },
    moonTint:   { value: moonTintVec },
  },
  vertexShader: `
    #include <common>
    #include <logdepthbuf_pars_vertex>
    varying vec2 vUv; varying vec3 vN; varying vec3 vP;
    void main(){
      vUv = uv; vN = normalize(normal);
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vP = wp.xyz;
      gl_Position = projectionMatrix * viewMatrix * wp;
      #include <logdepthbuf_vertex>
    }`,
  fragmentShader: `
    #include <common>
    #include <logdepthbuf_pars_fragment>
    uniform sampler2D dayMap, waterMap, cityMap;
    uniform vec3 sunDir, moonTint;
    uniform float nightBoost, cityVisibility;
    varying vec2 vUv; varying vec3 vN; varying vec3 vP;
    ${NIGHT_SURFACE_GLSL}
    void main(){
      #include <logdepthbuf_fragment>
      vec3 N = normalize(vN);
      vec3 V = normalize(-vP);
      float ndl = dot(N, sunDir);
      float dayW = smoothstep(-0.08, 0.18, ndl);
      vec3 day = texture2D(dayMap, vUv).rgb;
      float water = texture2D(waterMap, vUv).r;
      vec3 dayCol = day * (0.32 + 1.15 * max(ndl, 0.0));
      vec3 nightCol = nativeNight(day,water,nightBoost)
        + texture2D(cityMap,vUv).rgb * vec3(1.5,1.22,.93) * nightBoost * cityVisibility;
      vec3 col = mix(nightCol, dayCol, dayW);
      vec3 H = normalize(sunDir + V);
      float spec = pow(max(dot(N, H), 0.0), 90.0) * water * dayW;
      col += vec3(1.0, 0.93, 0.82) * spec * 0.5;
      float fr = pow(1.0 - max(dot(N, V), 0.0), 3.0);
      col += vec3(0.07, 0.16, 0.35) * fr * (0.25 + 0.75 * dayW);
      ${COLOR_FIX_GLSL}
      gl_FragColor = vec4(col, 1.0);
      #include <colorspace_fragment>
    }`,
});
const earthMesh = new THREE.Mesh(buildEllipsoidGeometry(192, 384, 1.0, -4000, true), baseMat);
earthMesh.name = 'earth-surface';
scene.add(earthMesh);
// Day and cloud maps are loaded together by the quality preset.
loadTex(TEX_WATER, false, t => baseMat.uniforms.waterMap.value = t);

const atmoMat = new THREE.ShaderMaterial({
  uniforms: { sunDir: { value: sunDirVec }, uFade: { value: 1 }, uIntensity: { value: 1 } },
  side: THREE.BackSide, transparent: true, depthWrite: false,
  blending: THREE.AdditiveBlending,
  vertexShader: `
    #include <common>
    #include <logdepthbuf_pars_vertex>
    varying vec3 vN; varying vec3 vP;
    void main(){
      vN = normalize(normal);
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vP = wp.xyz;
      gl_Position = projectionMatrix * viewMatrix * wp;
      #include <logdepthbuf_vertex>
    }`,
  fragmentShader: `
    #include <common>
    #include <logdepthbuf_pars_fragment>
    uniform vec3 sunDir;
    uniform float uFade, uIntensity;
    varying vec3 vN; varying vec3 vP;
    void main(){
      #include <logdepthbuf_fragment>
      vec3 N = normalize(vN);
      vec3 V = normalize(-vP);
      float d = dot(N, V);
      float rim = clamp(-d * 5.5, 0.0, 1.0);
      float i = pow(rim, 1.7);
      float hot = pow(rim, 7.0);
      float sunlight = smoothstep(-0.24, 0.18, dot(N, sunDir));
      float twilight = exp(-pow(dot(N, sunDir) / 0.16, 2.0));
      vec3 rayleigh = vec3(0.13, 0.36, 0.95) * i * (0.12 + 0.88 * sunlight);
      vec3 mie = vec3(1.0, 0.43, 0.16) * hot * twilight * 0.52;
      vec3 col = rayleigh + mie;
      gl_FragColor = vec4(col * 0.82 * uFade * uIntensity, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`,
});
const atmoMesh = new THREE.Mesh(buildEllipsoidGeometry(96, 192, 1.012, 0, false), atmoMat);
atmoMesh.renderOrder = 300;   // after tiles & clouds (additive limb glow)
scene.add(atmoMesh);

/* Cloud density maps: 2K for economy, 8K for high-detail presets. */
const cloudsMat = new THREE.MeshLambertMaterial({ color: 0xf1f5fb, emissive:0x1b2939, emissiveIntensity:.26, transparent: true, opacity: 0, alphaTest: 0.055, depthWrite: false });
const cloudsMesh = new THREE.Mesh(buildEllipsoidGeometry(128, 256, 1.0014, 0, true), cloudsMat);
cloudsMesh.renderOrder = 200; // above tiles (100+z), below atmosphere
cloudsMesh.visible = false;
cloudsMesh.name = 'earth-clouds';
scene.add(cloudsMesh);
const upperCloudsMat = cloudsMat.clone();
const upperCloudsMesh = new THREE.Mesh(buildEllipsoidGeometry(96, 192, 1.0028, 0, true), upperCloudsMat);
upperCloudsMesh.renderOrder = 201;
upperCloudsMesh.visible = false;
scene.add(upperCloudsMesh);
let cloudsReady = false;
let textureTier = null, textureGeneration = 0;
function applyTextureQuality(name) {
  const high = ['high', 'ultra', '4k'].includes(name) && renderer.capabilities.maxTextureSize >= 8192;
  const medium = !high && name !== 'low' && renderer.capabilities.maxTextureSize >= 4096 &&
    (name !== 'auto' || (navigator.deviceMemory || 4) >= 8);
  const tier = high ? 'high' : medium ? 'medium' : 'low';
  if (textureTier === tier) return;
  textureTier = tier;
  const generation = ++textureGeneration;
  loadTex(high ? '/static/textures/8k_earth_daymap.jpg' : medium ? '/static/textures/4k_earth_daymap.jpg' : TEX_DAY, true, t => {
    if (generation !== textureGeneration) { t.dispose(); return; }
    const old = baseMat.uniforms.dayMap.value;
    baseMat.uniforms.dayMap.value = t; old.dispose();
  });
  loadTex(high ? '/static/textures/nasa_black_marble_2016_8192.jpg' : medium ? '/static/textures/nasa_black_marble_2016_4096.jpg' : '/static/textures/earth-night.jpg', true, t => {
    if (generation !== textureGeneration) { t.dispose(); return; }
    const old = baseMat.uniforms.cityMap.value;
    baseMat.uniforms.cityMap.value = t; old.dispose();
  });
  loadTex(high ? TEX_CLOUDS_HIGH : medium ? '/static/textures/4k_earth_clouds.jpg' : TEX_CLOUDS_2K, false, t => {
    if (generation !== textureGeneration) { t.dispose(); return; }
    t.wrapS = THREE.RepeatWrapping;
    const old = cloudsMat.alphaMap;
    cloudsMat.alphaMap = t; cloudsMat.needsUpdate = true;
    upperCloudsMat.alphaMap = t; upperCloudsMat.needsUpdate = true; cloudsReady = true;
    if (old) old.dispose();
  });
  loadTex(high ? '/static/textures/8k_stars_visible.jpg' : medium ? '/static/textures/4k_stars_visible.jpg' : '/static/textures/2k_stars_visible.jpg', true, t => {
    if (generation !== textureGeneration) { t.dispose(); return; }
    const old = hazeMat.map; hazeMat.map = t; hazeMat.needsUpdate = true;
    if (old) old.dispose();
  });
}

/* =====================================================================
   STARS — round soft sprites + magnitude distribution + milky-way band
   ===================================================================== */
const starAnchors = [];
const starMats = [];
function makeStarTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0.00, 'rgba(255,255,255,1)');
  grad.addColorStop(0.28, 'rgba(255,255,255,0.75)');
  grad.addColorStop(0.60, 'rgba(255,255,255,0.18)');
  grad.addColorStop(1.00, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}
const starTex = makeStarTexture();
const STAR_BAND_N = new THREE.Vector3(0.3, 0.9, 0.2).normalize();
function makeStarLayer(count, size, bandFraction) {
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const v = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    const z = Math.random() * 2 - 1, phi = Math.random() * Math.PI * 2;
    const radial = Math.sqrt(1 - z * z);
    v.set(radial * Math.cos(phi), radial * Math.sin(phi), z);
    if (v.lengthSq() < 1e-6) v.set(1, 0, 0);
    v.normalize();
    if (Math.random() < bandFraction) {
      const d = v.dot(STAR_BAND_N);
      v.addScaledVector(STAR_BAND_N, -d * 0.86).normalize();
    }
    v.multiplyScalar(CONFIG.STAR_RADIUS * (0.94 + Math.random() * 0.06));
    pos.set([v.x, v.y, v.z], i * 3);
    const b = 0.24 + 0.76 * Math.pow(Math.random(), 2.2);
    const t = Math.random();
    let r = 1, g = 1, bl = 1;
    if (t < 0.20)      { r = 0.70; g = 0.81; bl = 1.00; }
    else if (t < 0.32) { r = 1.00; g = 0.83; bl = 0.66; }
    else if (t < 0.40) { r = 1.00; g = 0.93; bl = 0.86; }
    col.set([r * b, g * b, bl * b], i * 3);
  }
  const g2 = new THREE.BufferGeometry();
  g2.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g2.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const mat = new THREE.PointsMaterial({
    map: starTex, size, sizeAttenuation: false, vertexColors: true,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending
  });
  const p = new THREE.Points(g2, mat);
  p.frustumCulled = false;
  scene.add(p);
  starAnchors.push(p);
  starMats.push(mat);
}
makeStarLayer(700, 0.8, 0.25);   // restrained points over the photographic sky
makeStarLayer(220, 1.2, 0.25);
makeStarLayer(40, 1.9, 0.25);

/* Milky-way haze band */
let hazeMat, hazeSphere, skyAligned = false;
{
  const c = document.createElement('canvas'); c.width = 1024; c.height = 512;
  const g = c.getContext('2d');
  const gauss = () => { let s = 0; for (let i = 0; i < 4; i++) s += Math.random(); return (s - 2) / 2; };
  for (let i = 0; i < 3600; i++) {
    const x = Math.random() * 1024;
    const y = 256 + gauss() * 46;
    const r = 0.6 + Math.random() * 2.6;
    const a = 0.014 + Math.random() * 0.05;
    const warm = Math.random() < 0.3;
    g.fillStyle = warm ? `rgba(255,236,205,${a})` : `rgba(198,214,255,${a})`;
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  }
  for (let i = 0; i < 30; i++) {
    const x = Math.random() * 1024, y = 256 + gauss() * 30;
    const r = 6 + Math.random() * 16;
    g.fillStyle = 'rgba(210,225,255,0.05)';
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  hazeMat = new THREE.MeshBasicMaterial({
    map: t, side: THREE.BackSide, transparent: true, opacity: 0.55,
    blending: THREE.AdditiveBlending, depthWrite: false
  });
  const sphere = new THREE.Mesh(new THREE.SphereGeometry(CONFIG.HAZE_RADIUS, 48, 24), hazeMat);
  hazeSphere = sphere;
  sphere.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), STAR_BAND_N);
  sphere.frustumCulled = false;
  scene.add(sphere);
  starAnchors.push(sphere);
}

/* =====================================================================
   SUN + MOON (anchored "at infinity" along telemetry directions)
   ===================================================================== */
const sunLogical = new THREE.Vector3();
let sunSprite;
{
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0.00, 'rgba(255,255,255,1)');
  grad.addColorStop(0.06, 'rgba(255,252,240,0.98)');
  grad.addColorStop(0.16, 'rgba(255,244,214,0.75)');
  grad.addColorStop(0.32, 'rgba(255,232,180,0.30)');
  grad.addColorStop(0.60, 'rgba(255,215,140,0.10)');
  grad.addColorStop(1.00, 'rgba(255,200,120,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  sunSprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: t, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false
  }));
  sunSprite.scale.set(CONFIG.SUN_GLARE_SIZE, CONFIG.SUN_GLARE_SIZE, 1);
  sunSprite.renderOrder = 1;
  scene.add(sunSprite);
}
const moonLogical = new THREE.Vector3();
let moonPositionEcef = null;
const moonView = new THREE.Vector3();
const moonFacing = new THREE.Vector3();
const moonForward = new THREE.Vector3(0, 0, 1);
const moonMesh = new THREE.Mesh(
  new THREE.SphereGeometry(CONFIG.MOON_RADIUS, 48, 32),
  new THREE.MeshLambertMaterial({ color: 0xbfbfbf }));
moonMesh.visible = false;
scene.add(moonMesh);
loadTex(TEX_MOON, true, t => { moonMesh.material.map = t; moonMesh.material.needsUpdate = true; });

/* =====================================================================
   SATELLITE — same frame chain as the Cesium version
   ===================================================================== */
const satLogical = latLonToECEF(0, 0, 500000);
const satLogicalTarget = satLogical.clone();
const satQuatTarget = new THREE.Quaternion();
let hasBodyQuat = false, quatPrimed = false, telemetryPrimed = false;

const satGroup = new THREE.Group();
scene.add(satGroup);
const modelHolder = new THREE.Group();
modelHolder.quaternion.identity(); // Imported STEP and physics share CAD axes.
if (MODEL_EXTRA_ROTATION.x || MODEL_EXTRA_ROTATION.y || MODEL_EXTRA_ROTATION.z) {
  modelHolder.quaternion.multiply(new THREE.Quaternion().setFromEuler(MODEL_EXTRA_ROTATION));
}
satGroup.add(modelHolder);

const sensorMarkers = new Map();
function updateSensorMarkers(data) {
  const layout = data.imu_mounts || [];
  const alive = new Set();
  for (const item of layout) {
    alive.add(item.name);
    let mesh = sensorMarkers.get(item.name);
    if (!mesh) {
      mesh = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8),
        new THREE.MeshStandardMaterial({color: 0x777777, emissive: 0x000000, depthTest: false, depthWrite: false}));
      mesh.renderOrder = 500; satGroup.add(mesh); sensorMarkers.set(item.name, mesh);
    }
    const [x,y,z] = item.position;
    const com = data.center_of_mass_body_m || CONFIG.MODEL_COM;
    mesh.position.set(x-com[0], y-com[1], z-com[2]);
    mesh.userData.kind = item.kind;
    const cell = (data.sun_arr_cells || []).find(c => c.name === item.name);
      const unit = (data.imu_units?.[item.kind === 'Gyro' ? 'gyro' : 'mag'] || []).find(u => u.name === item.name);
      const level = item.kind === 'Sun' ? ((cell?.output_pct || 0) / 100) :
        Number(unit ? unit.used : (item.kind === 'Gyro' ? data.imu_gyro_valid : data.imu_mag_valid));
    mesh.userData.level = Number.isFinite(level) ? level : 0;
    mesh.userData.active = item.kind === 'Sun' ? !!cell?.used : level > 0;
    mesh.userData.color = item.kind === 'Sun' ? 0xc65b12 : item.kind === 'Gyro' ? 0x25c76f : 0x9b59e8;
  }
  for (const [name, mesh] of sensorMarkers) if (!alive.has(name)) {
    satGroup.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); sensorMarkers.delete(name);
  }
}
function paintSensorMarkers() {
  for (const mesh of sensorMarkers.values()) {
    mesh.visible = SETTINGS['show' + mesh.userData.kind];
    mesh.material.color.setHex(mesh.userData.active ? mesh.userData.color : 0x303947);
    mesh.material.emissive.setHex(mesh.userData.color);
    mesh.material.emissiveIntensity = SETTINGS.sensorGlow && mesh.userData.active ? 0.15 + mesh.userData.level * 0.35 : 0;
  }
}
const gltfLoader = new GLTFLoader();
try { if (DRACOLoader) {
  const d = new DRACOLoader();
  d.setDecoderPath('/static/vendor/three/examples/jsm/libs/draco/gltf/');
  gltfLoader.setDRACOLoader(d);
} } catch (e) { console.warn('DRACO unavailable', e); }
try { if (KTX2Loader) {
  const k = new KTX2Loader();
  k.setTranscoderPath('/static/vendor/three/examples/jsm/libs/basis/');
  k.detectSupport(renderer);
  gltfLoader.setKTX2Loader(k);
} } catch (e) { console.warn('KTX2 unavailable', e); }
try { if (MeshoptDecoder) gltfLoader.setMeshoptDecoder(MeshoptDecoder); } catch (e) {}

const modelMats = [];
function enhanceModelColors(root) {
  const isWhite = (c) => c.r > 0.8 && c.g > 0.8 && c.b > 0.8;
  root.traverse(o => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (!m) continue;
      if (!modelMats.includes(m)) modelMats.push(m);
      if (m.envMapIntensity !== undefined) m.envMapIntensity = CONFIG.MODEL_ENV;
      if (CONFIG.MODEL_COLORIZE && m.isMeshStandardMaterial && !m.map && m.color && isWhite(m.color)) {
        const name = ((o.name || '') + ' ' + (m.name || '')).toLowerCase();
        if (/panel|solar|cell|wing|array/.test(name)) {
          m.color.setHex(0x153a8c); m.metalness = 0.35; m.roughness = 0.55;
        } else if (/foil|gold|mli|blanket|kapton|wrap|tape|isolat/.test(name)) {
          m.color.setHex(0xc08a2e); m.metalness = 0.75; m.roughness = 0.38;
        } else if (/antenna|dish|boom|rod|mast|probe/.test(name)) {
          m.color.setHex(0x9aa0a6); m.metalness = 0.6; m.roughness = 0.45;
        } else {
          m.color.setHex(0x8d939b); m.metalness = 0.35; m.roughness = 0.6;
        }
      }
    }
  });
}
function buildPlaceholderSat() {
  const g = new THREE.Group();
  const gold  = new THREE.MeshStandardMaterial({ color: 0xc8a24a, metalness: 0.85, roughness: 0.35, envMapIntensity: 0.6 });
  const blue  = new THREE.MeshStandardMaterial({ color: 0x1c3a8c, metalness: 0.4, roughness: 0.45, envMapIntensity: 0.6 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.6, 0.35), gold); g.add(body);
  const p1 = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.5, 0.02), blue); p1.position.y = 0.85; g.add(p1);
  const p2 = p1.clone(); p2.position.y = -0.85; g.add(p2);
  modelMats.push(gold, blue);
  return g;
}
let loadedModelUrl = null;
let modelLoadVersion = 0;
function loadSpacecraftModel(url, com = CONFIG.MODEL_COM) {
  if (!url || url === loadedModelUrl) return;
  loadedModelUrl = url;
  const version = ++modelLoadVersion;
  gltfLoader.load(url,
  gltf => {
    if (version !== modelLoadVersion) return;
    modelHolder.clear();
    modelMats.length = 0;
    gltf.scene.scale.setScalar(CONFIG.MODEL_SCALE);
    gltf.scene.position.set(-com[0], -com[1], -com[2]);
    // Exported component materials already distinguish structure and hardware.
    gltf.scene.traverse(o => { if (o.isMesh) {
      const materials = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of materials) { m.envMapIntensity = CONFIG.MODEL_ENV; modelMats.push(m); }
    }});
    modelHolder.add(gltf.scene);
    console.log('[debug] satellite model loaded:', CONFIG.MODEL_URL);
    applySettings();
  },
  undefined,
  err => { console.warn('CAD GLB failed:', url, err); loadedModelUrl = null; });
}
loadSpacecraftModel(CONFIG.MODEL_URL);

/* =====================================================================
   Simple 1px lines + HTML labels
   ===================================================================== */
const ZERO = new THREE.Vector3();
const SCRATCH = new THREE.Vector3();
class DirLine {
  constructor(colorHex) {
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
    this.mat = new THREE.LineBasicMaterial({ color: colorHex, toneMapped: false });
    this.line = new THREE.Line(this.geo, this.mat);
    this.line.frustumCulled = false;
    this.line.visible = false;
  }
  setEndpoints(a, b) {
    const p = this.geo.attributes.position.array;
    p[0] = a.x; p[1] = a.y; p[2] = a.z;
    p[3] = b.x; p[4] = b.y; p[5] = b.z;
    this.geo.attributes.position.needsUpdate = true;
  }
}

const labelsRoot = $('labels');
const labels = [];
function addLabel(text, cssColor, getPos, isVisible) {
  const el = document.createElement('div');
  el.className = 'glabel'; el.textContent = text; el.style.color = cssColor;
  el.style.display = 'none';
  labelsRoot.appendChild(el);
  labels.push({ el, getPos, isVisible });
  return labels[labels.length - 1];
}
const homeLocation = latLonToECEF(17.4355, 78.4579, 150);
const homeNormal = homeLocation.clone().normalize();
const homeView = new THREE.Vector3();
addLabel('We are here \u00b7 Begumpet, Hyderabad', '#a9e9ff', out => out.copy(homeLocation),
  () => homeView.copy(camLogical).sub(homeLocation).dot(homeNormal) > 0 && camLogical.distanceTo(homeLocation) < 2.0e7);
const satelliteNameLabel = addLabel('Spacecraft', '#9fe5ff', out => out.copy(satLogical), () => overviewView);
const bodyDirPos = (dir, len) => (out) =>
  out.copy(dir).multiplyScalar(len).applyQuaternion(satGroup.quaternion).add(satLogical);
const worldDirPos = (dirGetter, len) => (out) => {
  const d = dirGetter();
  if (!d) return out.set(0, 0, 0);
  return out.copy(d).normalize().multiplyScalar(len).add(satLogical);
};

const axes = [];
let axesVisible = false;
function addBodyAxis(dir, labelText, colorHex, cssColor) {
  const L = new DirLine(colorHex);
  L.setEndpoints(ZERO, SCRATCH.copy(dir).multiplyScalar(CONFIG.AXIS_LEN));
  satGroup.add(L.line);
  axes.push(L);
  addLabel(labelText, cssColor, bodyDirPos(dir, CONFIG.AXIS_LEN), () => axesVisible);
}
addBodyAxis(new THREE.Vector3(-1, 0, 0), '+Y', 0x00c800, '#7fff7f');
addBodyAxis(new THREE.Vector3(0, 1, 0), '+X', 0xd00000, '#ff7f7f');
addBodyAxis(new THREE.Vector3(0, 0, 1), '+Z', 0x0066ff, '#7fb7ff');

const sunDirEcef = sunDirVec.clone();
let moonDirEcef = null, nadirDirEcef = null, sweepDirEcef = null;

const sunLine   = new DirLine(0xffd400); scene.add(sunLine.line);
const moonLine  = new DirLine(0x00e5ff); scene.add(moonLine.line);
const nadirLine = new DirLine(0xffffff); scene.add(nadirLine.line);
const sweepLine = new DirLine(0xff77ff); scene.add(sweepLine.line);
const PN_LOCAL  = new THREE.Vector3(0, 0, -1);
const MPN_LOCAL = new THREE.Vector3(0, -1, 0);
const panelNormalLine = new DirLine(0xff8c1a);
panelNormalLine.setEndpoints(ZERO, SCRATCH.copy(PN_LOCAL).multiplyScalar(CONFIG.DIRLINE_LEN * 0.8));
satGroup.add(panelNormalLine.line);
const moonPanelLine = new DirLine(0xff8c1a);
moonPanelLine.setEndpoints(ZERO, SCRATCH.copy(MPN_LOCAL).multiplyScalar(CONFIG.DIRLINE_LEN * 0.8));
satGroup.add(moonPanelLine.line);

addLabel('To Sun',              '#ffd400', worldDirPos(() => sunDirEcef, CONFIG.DIRLINE_LEN), () => sunLine.line.visible);
addLabel('Panel Normal (-Z)',   '#ff8c1a', bodyDirPos(PN_LOCAL, CONFIG.DIRLINE_LEN * 0.8), () => panelNormalLine.line.visible);
addLabel('To Moon',             '#00e5ff', worldDirPos(() => moonDirEcef, CONFIG.DIRLINE_LEN), () => moonLine.line.visible);
addLabel('Moon Panel Normal(-Y)','#ff8c1a', bodyDirPos(MPN_LOCAL, CONFIG.DIRLINE_LEN * 0.8), () => moonPanelLine.line.visible);
addLabel('To Nadir',            '#ffffff', worldDirPos(() => nadirDirEcef, CONFIG.DIRLINE_LEN), () => nadirLine.line.visible);
addLabel('Sun Sweep',           '#ff77ff', worldDirPos(() => sweepDirEcef, CONFIG.DIRLINE_LEN), () => sweepLine.line.visible);

/* =====================================================================
   Camera-relative placement (floating origin)
   ===================================================================== */
const ORIGIN_LOGICAL = new THREE.Vector3(0, 0, 0);
const statics = [];
function trackOrigin(obj, posVec) { statics.push({ obj, pos: posVec }); }
trackOrigin(earthMesh, ORIGIN_LOGICAL);
trackOrigin(atmoMesh, ORIGIN_LOGICAL);
trackOrigin(cloudsMesh, ORIGIN_LOGICAL);
trackOrigin(upperCloudsMesh, ORIGIN_LOGICAL);
trackOrigin(satGroup, satLogical);
trackOrigin(sunLine.line, satLogical);
trackOrigin(moonLine.line, satLogical);
trackOrigin(nadirLine.line, satLogical);
trackOrigin(sweepLine.line, satLogical);
trackOrigin(moonMesh, moonLogical);
trackOrigin(sunSprite, sunLogical);

const orbitGeometry = new THREE.BufferGeometry();
const orbitPath = new THREE.Line(orbitGeometry, new THREE.LineBasicMaterial({color: 0x66ccff}));
orbitPath.visible = false;
orbitPath.name = 'osculating-orbit';
scene.add(orbitPath); trackOrigin(orbitPath, ORIGIN_LOGICAL);
function updateOrbitPath(data) {
  if (!data.orbit_path_ecef_m) return;
  const points = data.orbit_path_ecef_m;
  let positions = orbitGeometry.getAttribute('position');
  if (!positions || positions.count !== points.length) {
    positions = new THREE.Float32BufferAttribute(new Float32Array(points.length * 3), 3);
    orbitGeometry.setAttribute('position', positions);
  }
  for (let i = 0; i < points.length; i++) positions.setXYZ(i, ...points[i]);
  positions.needsUpdate = true;
  orbitGeometry.computeBoundingSphere();
}
function placeWorld(camPos) {
  orbitPath.visible = camPos.distanceTo(satLogical) > 1.2e5;
  sunLogical.copy(camPos).addScaledVector(sunDirEcef, CONFIG.SUN_RENDER_DIST);
  if (moonPositionEcef) {
    moonView.copy(moonPositionEcef).sub(camPos);
    const distance = moonView.length();
    moonLogical.copy(camPos).addScaledVector(moonView, CONFIG.MOON_RENDER_DIST / distance);
    moonMesh.scale.setScalar(SETTINGS.moonSize * (1737400 / CONFIG.MOON_RADIUS) * CONFIG.MOON_RENDER_DIST / distance);
    moonMesh.quaternion.setFromUnitVectors(moonForward, moonFacing.copy(moonPositionEcef).negate().normalize());
  } else if (moonDirEcef) moonLogical.copy(camPos).addScaledVector(moonDirEcef, CONFIG.MOON_RENDER_DIST);
  for (const s of statics) s.obj.position.copy(s.pos).sub(camPos);
  for (const t of tiles.values()) t.mesh.position.copy(t.center).sub(camPos);
  for (const o of starAnchors) o.position.set(0, 0, 0);
}

/* =====================================================================
   IMAGERY TILE STREAMING — artifact-free crossfades

   THE BUG THAT MADE "DIAMONDS" AND BRIGHT/DIM SQUARES:
   1) Fading tiles wrote DEPTH while semi-transparent, which hid the
      coarser tile beneath them → they blended against the dark base
      globe instead of their parent (every load = dim→bright pulse).
   2) LOD marking used cell-center rays only, so partially-visible
      boundary tiles were never marked → holes shaped like tile quads.

   THE FIX (this whole section):
   - renderOrder = 100 + z → parents ALWAYS render before children.
   - depthWrite disabled on imagery layers → fades are true crossfades over
     the parent layer, never over the globe.
   - Exact per-cell coverage: each screen cell's 4 corner rays define
     its earth footprint; every tile in that footprint is marked.
   - Tiles cover the globe down to MIN_TILED_Z (base level everywhere).
   - Every visible tile pins its full ancestor chain → there is always
     a loaded fallback layer underneath (and zoom-outs are instant).
   - Fully-covered parents are depth-culled → the pinning costs ~nothing.
   ===================================================================== */
const tiles = new Map();
window.missionTileState = () => ({ total: tiles.size, loaded: [...tiles.values()].filter(t => t.loaded).length, failed: [...tiles.values()].filter(t => t.failed).length });
const needed = new Set();
const extraVisible = new Set();   // 404-fallback parents
const pending = [];
let loadingCount = 0, lastTileUpdate = 0;

/* children sit slightly above parents so a sharper tile crossfades over
   the blurrier one instead of being hidden behind it */
const tileLift = (z) => 1.0 + Math.max(0, z - CONFIG.MIN_TILED_Z) * 2.0;

class TileMaterial extends THREE.ShaderMaterial {
  constructor() {
    super({
      uniforms: {
        map:     { value: null },
        waterMap: baseMat.uniforms.waterMap,
        nightBoost: baseMat.uniforms.nightBoost,
        sunDir:  { value: sunDirVec },
        moonTint:{ value: moonTintVec },
        uOpacity:{ value: 0 },
      },
      /* Ordered imagery layers never write depth, including at full opacity. */
      transparent: true, depthWrite: false,
      vertexShader: `
        #include <common>
        #include <logdepthbuf_pars_vertex>
        varying vec2 vUv; varying vec3 vN; varying vec3 vP;
        void main(){
          vUv = uv; vN = normalize(normal);
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vP = wp.xyz;
          gl_Position = projectionMatrix * viewMatrix * wp;
          #include <logdepthbuf_vertex>
        }`,
      fragmentShader: `
        #include <common>
        #include <logdepthbuf_pars_fragment>
        uniform sampler2D map, waterMap;
        uniform float nightBoost;
        uniform vec3 sunDir, moonTint;
        uniform float uOpacity;
        varying vec2 vUv; varying vec3 vN; varying vec3 vP;
        ${NIGHT_SURFACE_GLSL}
        void main(){
          #include <logdepthbuf_fragment>
          vec3 N = normalize(vN);
          vec3 V = normalize(-vP);
          float ndl = dot(N, sunDir);
          vec2 globeUV = vec2(atan(N.y, N.x) / (2.0 * PI) + 0.5, asin(clamp(N.z, -1.0, 1.0)) / PI + 0.5);
          float water = smoothstep(0.95, 1.0, texture2D(waterMap, globeUV).r);
          // Continuous deep-water shading removes offshore mosaic/tile colour blocks.
          vec3 tex = mix(texture2D(map, vUv).rgb, vec3(0.004, 0.018, 0.032), water);
          float dayW = smoothstep(-0.08, 0.18, ndl);
          if (dot(N, V) <= 0.0) discard;
          vec3 col = mix(nativeNight(tex,water,nightBoost), tex * (0.14 + 1.35 * max(ndl, 0.0)), dayW);
          vec3 H = normalize(sunDir + V);
          col += vec3(1.0, 0.93, 0.82) * pow(max(dot(N, H), 0.0), 90.0) * water * dayW * 0.5;
          float fr = pow(1.0 - max(dot(N, V), 0.0), 3.0);
          col += vec3(0.07, 0.16, 0.35) * fr * (0.25 + 0.75 * dayW);
          ${COLOR_FIX_GLSL}
          gl_FragColor = vec4(col, uOpacity);
          #include <colorspace_fragment>
        }`,
    });
  }
}

class Tile {
  constructor(z, x, y) {
    this.z = z; this.x = x; this.y = y;
    this.key = `${z}/${x}/${y}`;
    const n = 1 << z;
    const west = x / n * 360 - 180, east = (x + 1) / n * 360 - 180;
    const north = tile2lat(y, z), south = tile2lat(y + 1, z);
    const lift = tileLift(z);
    const cx = latLonToECEF((north + south) / 2, (west + east) / 2, lift);
    this.center = cx;
    const segs = z < 5 ? 32 : (z < 8 ? 10 : (z < 12 ? 8 : 6));
    const S1 = segs + 1;

    /* skirt depth: covers chord-vs-arc sag + LOD-boundary T-junction steps */
    const latSpanM = Math.abs(north - south) * 111320;
    const sag = Math.pow(latSpanM / segs, 2) / (2 * EARTH_R_MEAN);
    const skirt = clamp(sag * 4 + 2, 2, 500);

    const pos = [], nor = [], uv = [], idx = [];
    for (let j = 0; j <= segs; j++) {
      const lat = north + (south - north) * j / segs;
      const cl = Math.cos(lat * DEG), sl = Math.sin(lat * DEG);
      for (let i = 0; i <= segs; i++) {
        const lon = west + (east - west) * i / segs;
        const co = Math.cos(lon * DEG), so = Math.sin(lon * DEG);
        const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
        pos.push((N + lift) * cl * co - cx.x,
                 (N + lift) * cl * so - cx.y,
                 (N * (1 - WGS84_E2) + lift) * sl - cx.z);
        nor.push(cl * co, cl * so, sl);
        uv.push(i / segs, 1 - j / segs);
      }
    }

    /* ---- skirt vertices: border verts duplicated, pushed radially in ---- */
    const vMain = (j, i) => j * S1 + i;
    const skirtOf = new Array(S1 * S1).fill(-1);
    let nextIdx = S1 * S1;
    const addSkirtVert = (j, i) => {
      const vi = vMain(j, i);
      if (skirtOf[vi] >= 0) return skirtOf[vi];
      const p = vi * 3;
      pos.push(pos[p]     - nor[p]     * skirt,
               pos[p + 1] - nor[p + 1] * skirt,
               pos[p + 2] - nor[p + 2] * skirt);
      nor.push(nor[p], nor[p + 1], nor[p + 2]);
      uv.push(uv[vi * 2], uv[vi * 2 + 1]);
      skirtOf[vi] = nextIdx++;
      return skirtOf[vi];
    };
    for (let i = 0; i <= segs; i++) { addSkirtVert(0, i); addSkirtVert(segs, i); }
    for (let j = 1; j < segs; j++)  { addSkirtVert(j, 0); addSkirtVert(j, segs); }

    for (let j = 0; j < segs; j++) for (let i = 0; i < segs; i++) {
      const a = vMain(j, i), b = a + 1, c = a + S1, d = c + 1;
      idx.push(a, c, b, b, c, d);
    }
    const skirtQuad = (a, b, c, d) => idx.push(a, b, c, a, c, d, c, b, a, d, c, a);
    for (let i = 0; i < segs; i++) {
      skirtQuad(vMain(0, i),     vMain(0, i + 1),     addSkirtVert(0, i + 1),     addSkirtVert(0, i));
      skirtQuad(vMain(segs, i),  vMain(segs, i + 1),  addSkirtVert(segs, i + 1),  addSkirtVert(segs, i));
    }
    for (let j = 0; j < segs; j++) {
      skirtQuad(vMain(j, 0),     vMain(j + 1, 0),     addSkirtVert(j + 1, 0),     addSkirtVert(j, 0));
      skirtQuad(vMain(j, segs),  vMain(j + 1, segs),  addSkirtVert(j + 1, segs),  addSkirtVert(j, segs));
    }

    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal',   new THREE.Float32BufferAttribute(nor, 3));
    g.setAttribute('uv',       new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    this.mat = new TileMaterial();
    this.mesh = new THREE.Mesh(g, this.mat);
    this.mesh.renderOrder = 100 + z;   // parents render before children — crossfades layer correctly
    this.mesh.visible = false;
    this.loaded = false; this.failed = false; this.requested = false; this.disposed = false;
    this.cullHidden = false;            // set when all 4 children fully cover this parent
    this.neededAt = performance.now();
    scene.add(this.mesh);
  }
}
function ensureTile(z, x, y, focus) {
  const key = `${z}/${x}/${y}`;
  let t = tiles.get(key);
  if (!t) {
    t = new Tile(z, x, y);
    tiles.set(key, t);
    t.priority = t.center.distanceTo(focus);
    pending.push(t);
  }
  return t;
}
function pump() {
  pending.sort((a, b) => a.priority - b.priority);
  while (loadingCount < CONFIG.MAX_CONCURRENT && pending.length) {
    const t = pending.shift();
    if (t.disposed || t.loaded || t.failed || t.requested) continue;
    t.requested = true; loadingCount++;
    texLoader.load(TILE_URL(t.z, t.x, t.y), tex => {
      loadingCount--;
      if (t.disposed) { tex.dispose(); pump(); return; }
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = MAX_ANISO;
      t.mat.uniforms.map.value = tex;
      t.mat.uniforms.uOpacity.value = 0;
      t.loaded = true;                  // fade-in handled per frame
      pump();
    }, undefined, () => {
      loadingCount--;
      if (t.disposed) { pump(); return; }
      t.failed = true;
      if (t.z > CONFIG.MIN_TILED_Z) {   // fall back to the parent tile
        const p = ensureTile(t.z - 1, t.x >> 1, t.y >> 1, t.center);
        extraVisible.add(p.key);
        if (extraVisible.size > 40) extraVisible.delete(extraVisible.keys().next().value);
      }
      pump();
    });
  }
}
function disposeTile(t) {
  scene.remove(t.mesh);
  t.mesh.geometry.dispose();
  if (t.mat.uniforms.map.value) t.mat.uniforms.map.value.dispose();
  t.mat.dispose();
  t.disposed = true;
  tiles.delete(t.key);
}
/* evict ONLY fully-faded, unneeded tiles — a tile is never popped off
   the screen: visible sharp tiles always have a fallback beneath them */
function evict(now) {
  let excess = tiles.size - CONFIG.CACHE_MAX;
  if (excess <= 0) return;
  const arr = [];
  for (const t of tiles.values()) {
    if (needed.has(t.key) || extraVisible.has(t.key)) continue;
    if (t.loaded && t.mat.uniforms.uOpacity.value > 0.004) continue;  // still fading out
    arr.push(t);
  }
  arr.sort((a, b) => a.neededAt - b.neededAt);
  for (const t of arr) { if (excess <= 0) break; disposeTile(t); excess--; }
}

/* ---- per-cell footprint LOD selection (corner rays → exact coverage) ---- */
function pickLevel(pxPerMeter, latDeg) {
  const cosLat = Math.max(0.05, Math.cos(latDeg * DEG));
  for (let zz = CONFIG.MAX_Z; zz >= 2; zz--) {
    if ((EARTH_CIRC * cosLat / (1 << zz)) * pxPerMeter >= CONFIG.TARGET_PX) return zz;
  }
  return 2;
}

const DIRV = new THREE.Vector3(), HIT = new THREE.Vector3(), HITN = new THREE.Vector3();
const CTR = new THREE.Vector3();
const hitPool = [];
function addViewTiles(originLogical, cam, screenH, gridN, budget, allowCreateIn, now) {
  const tanHalf = Math.tan(FOV / 2);
  const aspect = cam.aspect;
  const q = cam.quaternion;
  const NP = gridN + 1;
  while (hitPool.length < NP * NP) hitPool.push(new THREE.Vector3());
  const hits = hitPool;

  /* corner rays for every grid cell — a cell's earth footprint is the
     lat/lon box spanned by its corner hits, so the tiles we mark cover
     the cell EXACTLY (no holes, no diamonds at LOD boundaries) */
  let anyHit = false;
  for (let gy = 0; gy < NP; gy++) {
    const fy = (1 - 2 * gy / gridN) * tanHalf;
    for (let gx = 0; gx < NP; gx++) {
      const fx = (2 * gx / gridN - 1) * tanHalf * aspect;
      DIRV.set(fx, fy, -1).normalize().applyQuaternion(q);
      const i = gy * NP + gx;
      hits[i] = raySphereHit(originLogical, DIRV, EARTH_R_MEAN + 2000, hits[i] || new THREE.Vector3());
      if (hits[i]) anyHit = true;
    }
  }
  if (!anyHit) return;

  let marked = 0;
  let allowCreate = allowCreateIn;
  const needTile = (z, tx, ty, count) => {
    const key = `${z}/${tx}/${ty}`;
    if (needed.has(key)) return;
    let t = tiles.get(key);
    if (!t) {
      if (allowCreate <= 0) return;    // retried on the next update
      t = ensureTile(z, tx, ty, HIT);
      allowCreate--;
    }
    needed.add(key);
    t.neededAt = now;
    if (count) marked++;
  };

  for (let cy = 0; cy < gridN && marked < budget; cy++) {
    for (let cx = 0; cx < gridN && marked < budget; cx++) {
      const i00 = cy * NP + cx, i10 = i00 + 1, i01 = i00 + NP, i11 = i01 + 1;
      let sx = 0, sy = 0, sz = 0, cn = 0;
      let latMin = 90, latMax = -90;
      let lonC = 0, relMin = 1e9, relMax = -1e9, first = true;
      for (const idx of [i00, i10, i01, i11]) {
        const h = hits[idx];
        if (!h) continue;
        HITN.copy(h).normalize();
        const la = Math.asin(clamp(HITN.z, -1, 1)) / DEG;
        const lo = Math.atan2(HITN.y, HITN.x) / DEG;
        if (first) { lonC = lo; first = false; }
        const rel = wrap180(lo - lonC);
        if (rel < relMin) relMin = rel;
        if (rel > relMax) relMax = rel;
        if (la < latMin) latMin = la;
        if (la > latMax) latMax = la;
        sx += h.x; sy += h.y; sz += h.z; cn++;
      }
      if (!cn) continue;

      CTR.set(sx / cn, sy / cn, sz / cn);
      HITN.copy(CTR).normalize();
      DIRV.copy(CTR).sub(originLogical).normalize();
      const cosI = Math.max(0.25, -DIRV.dot(HITN));    // obliquity
      const effDist = originLogical.distanceTo(CTR) / cosI;
      const pxPerMeter = (screenH * 0.5) / (effDist * tanHalf);
      const latC = Math.asin(clamp(HITN.z, -1, 1)) / DEG;

      let z = Math.max(pickLevel(pxPerMeter, latC), CONFIG.MIN_TILED_Z);
      const n = 1 << z;
      const lonMin = lonC + relMin, lonMax = lonC + relMax;
      let x0 = Math.floor(((lonMin + 180) / 360) * n);
      let x1 = Math.floor(((lonMax + 180) / 360) * n);
      if (x1 - x0 >= n) { x0 = 0; x1 = n - 1; }        // full-circle safety
      const y0 = lat2tileY(latMax, z), y1 = lat2tileY(latMin, z);
      for (let ty = y0; ty <= y1 && marked < budget; ty++) {
        if (ty < 0 || ty >= n) continue;
        for (let tx = x0; tx <= x1 && marked < budget; tx++) {
          needTile(z, ((tx % n) + n) % n, ty, true);
        }
      }
    }
  }

  /* pass 2: pin ancestor chains of every marked tile → there is always a
     loaded fallback layer beneath, and zoom-outs already have imagery */
  for (const key of [...needed]) {
    const slash = key.indexOf('/');
    const z = +key.slice(0, slash);
    if (z <= CONFIG.MIN_TILED_Z) continue;
    const rest = key.slice(slash + 1);
    const comma = rest.indexOf('/');
    let tx = +rest.slice(0, comma), ty = +rest.slice(comma + 1);
    tx >>= 1; ty >>= 1;
    for (let pz = z - 1; pz >= CONFIG.MIN_TILED_Z; pz--) {
      needTile(pz, tx, ty, false);
      tx >>= 1; ty >>= 1;
    }
  }
}

const streamTileLogical = new THREE.Vector3();
const childCover = new Map();
function updateParentCulling() {
  for (const t of tiles.values()) t.cullHidden = false;
  childCover.clear();
  for (const key of needed) {
    const t = tiles.get(key);
    if (!t || !t.loaded || t.z <= CONFIG.MIN_TILED_Z) continue;
    if (t.mat.uniforms.uOpacity.value < 1) continue;   // a fading child doesn't count
    const pk = `${t.z - 1}/${t.x >> 1}/${t.y >> 1}`;
    const rec = childCover.get(pk);
    if (rec) rec.n++;
    else childCover.set(pk, { n: 1 });
  }
  for (const [pk, rec] of childCover) {
    if (rec.n >= 4) {   // all 4 children opaque → parent fully covered → skip drawing it
      const p = tiles.get(pk);
      if (p) p.cullHidden = true;
    }
  }
}

function updateTiles(now) {
  needed.clear();
  if (camLogical.length() - EARTH_R_MEAN < 2.0e6) addViewTiles(camLogical, camera, renderer.domElement.height, 9,
               CONFIG.TILE_BUDGET, CONFIG.CREATE_BUDGET, now);
  if (SETTINGS.streamOn && CONFIG.STREAM_SOURCE === 'payload' && cameraMode !== 'payload' &&
      videoSocket && videoSocket.readyState === 1) {
    computePayloadPose(streamTileLogical, payloadCamera);
    addViewTiles(streamTileLogical, payloadCamera, SETTINGS.streamH, 5,
                 CONFIG.STREAM_TILE_BUDGET, CONFIG.CREATE_STREAM_BUDGET, now);
  }
  updateParentCulling();
  pump();
  evict(now);
}

/* fade IN and OUT — always a crossfade over the layer beneath (parent /
   base globe), depth-write disabled on imagery layers */
function updateTileFades(now, dt) {
  const step = (dt * 1000) / CONFIG.TILE_FADE_MS;
  for (const t of tiles.values()) {
    if (!t.loaded) { t.mesh.visible = false; continue; }
    const active = needed.has(t.key) || extraVisible.has(t.key);
    const target = active ? 1 : 0;
    let op = t.mat.uniforms.uOpacity.value;
    if (op < target) op = Math.min(target, op + step);
    else if (op > target) {
      op = Math.max(target, op - step);
      if (t.z > CONFIG.MIN_TILED_Z) {   // reveal the parent while fading out
        const p = tiles.get(`${t.z - 1}/${t.x >> 1}/${t.y >> 1}`);
        if (p) p.cullHidden = false;
      }
    }
    t.mat.uniforms.uOpacity.value = op;
    // Intersecting curved LOD meshes must not clip one another.
    t.mat.depthWrite = false;
    t.mesh.visible = op > 0.004 && !t.cullHidden;
  }
}

/* =====================================================================
   Camera modes — free / chase / payload (inertially-stabilized chase)
   ===================================================================== */
let cameraMode = 'chase';
const camLogical = new THREE.Vector3();
window.missionCameraState = () => ({ distanceFromEarthM: camLogical.length(), distanceFromSatelliteM: camLogical.distanceTo(satLogical), overview: overviewView, transitioning: cameraTransition, chaseDistanceM: chaseOffsetWorld.length() });
const freePos = new THREE.Vector3(), freeQuat = new THREE.Quaternion();

const chaseOffsetWorld = new THREE.Vector3(...CONFIG.CHASE_VIEW_FROM);
const chaseQuatWorld = new THREE.Quaternion();
let lastBodyQuat = null;
let overviewView = false, cameraTransition = false, cameraTransitionElapsed = 0;
let overviewDistance = 2.1e7, overviewAzimuth = 0, overviewElevation = 0;
const transitionStartPos = new THREE.Vector3(), transitionStartQuat = new THREE.Quaternion();
const displayCamLogical = new THREE.Vector3(), displayCamQuat = new THREE.Quaternion();
const desiredCamLogical = new THREE.Vector3(), desiredCamQuat = new THREE.Quaternion();
const overviewCamLogical = new THREE.Vector3(), overviewRadial = new THREE.Vector3(), overviewTangent = new THREE.Vector3(), overviewUp = new THREE.Vector3();
const Z_AXIS = new THREE.Vector3(0,0,1);
let lastCameraTransitionEndMs = -Infinity;
window.addEventListener('dashboard-tab', e => {
  const next = e.detail === 'overview';
  if (overviewView !== next) {
    transitionStartPos.copy(camLogical); transitionStartQuat.copy(camera.quaternion);
    overviewView = next; cameraTransition = true; cameraTransitionElapsed = 0;
  }
});
// dashboard.js may dispatch its initial tab before this module has loaded.
overviewView = document.querySelector('.mission-dashboard')?.dataset.tab === 'overview';
cameraTransition = false;
transitionStartPos.copy(camLogical); transitionStartQuat.copy(camera.quaternion);
const DQ = new THREE.Quaternion(), QINV2 = new THREE.Quaternion();

function resetChaseView() {
  const q = satGroup.quaternion;
  chaseOffsetWorld.set(...CONFIG.CHASE_VIEW_FROM).applyQuaternion(q);
  const up = new THREE.Vector3(0, 0, 1).applyQuaternion(q);
  const dir = new THREE.Vector3().copy(chaseOffsetWorld).normalize();
  if (Math.abs(up.dot(dir)) > 0.98) up.set(0, 1, 0);
  const m = new THREE.Matrix4().lookAt(chaseOffsetWorld, ZERO, up);
  chaseQuatWorld.setFromRotationMatrix(m);
}
resetChaseView();

const TMPA = new THREE.Vector3(), TMPB = new THREE.Vector3(), TMPC = new THREE.Vector3();

function computePayloadPose(outLogical, outCam) {
  const q = satGroup.quaternion;
  TMPA.set(CONFIG.PAYLOAD_OFFSET[0], CONFIG.PAYLOAD_OFFSET[1], CONFIG.PAYLOAD_OFFSET[2])
      .applyQuaternion(q);
  outLogical.copy(satLogical).add(TMPA);
  TMPB.set(0, 1, 0).applyQuaternion(q);
  TMPC.set(0, 0, 1).applyQuaternion(q);
  outCam.position.set(0, 0, 0);
  outCam.up.copy(TMPC);
  outCam.lookAt(TMPB);
}
function computeFixedPose(outLogical, outCam) {
  latLonToECEF(13, 77, 10000000, outLogical);
  const lat = 13 * DEG, lon = 77 * DEG;
  TMPA.set(Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat));
  outCam.position.set(0, 0, 0);
  outCam.up.copy(TMPA);
  outCam.lookAt(TMPC.copy(outLogical).negate());
}

function updateCamera() {
  if (cameraMode === 'chase') {
    camLogical.copy(satLogical).add(chaseOffsetWorld);
    camera.position.set(0, 0, 0);
    camera.quaternion.copy(chaseQuatWorld);
  } else if (cameraMode === 'payload') {
    computePayloadPose(camLogical, camera);
  } else {
    let r = freePos.length();
    if (r < EARTH_R_MEAN + 50) freePos.multiplyScalar((EARTH_R_MEAN + 50) / r);
    r = freePos.length();
    if (r > CONFIG.FREE_MAX_DIST) freePos.multiplyScalar(CONFIG.FREE_MAX_DIST / r);
    camLogical.copy(freePos);
    camera.quaternion.copy(freeQuat);
  }
}

function applyChaseAttitudeLock() {
  if (cameraMode !== 'chase' || !SETTINGS.attLock || !lastBodyQuat) return;
  DQ.copy(satGroup.quaternion).multiply(QINV2.copy(lastBodyQuat).invert()).normalize();
  chaseOffsetWorld.applyQuaternion(DQ);
  chaseQuatWorld.premultiply(DQ).normalize();
}
function trackBodyQuat() {
  if (!lastBodyQuat) lastBodyQuat = new THREE.Quaternion();
  lastBodyQuat.copy(satGroup.quaternion);
}

/* Pointer controls */
{
  const el = renderer.domElement;
  let dragging = false, dragBtn = 0, lastX = 0, lastY = 0;
  const RLOC = new THREE.Quaternion(), M = new THREE.Quaternion(), QINV = new THREE.Quaternion();
  const ROTQ = new THREE.Quaternion(), EUL = new THREE.Euler();

  el.addEventListener('contextmenu', e => e.preventDefault());
  el.addEventListener('pointerdown', e => {
    if (cameraMode === 'payload' && !overviewView) return;
    dragging = true; dragBtn = e.button;
    lastX = e.clientX; lastY = e.clientY;
    try { el.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  });
  el.addEventListener('pointermove', e => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    if (overviewView) {
      overviewAzimuth = (overviewAzimuth - dx * 0.003) % (2 * Math.PI);
      overviewElevation = (overviewElevation - dy * 0.003) % (2 * Math.PI);
      return;
    }
    if (cameraMode === 'chase') {
      const s = CONFIG.CHASE_ROT_SENS * SETTINGS.chaseSens;
      EUL.set(-dy * s, -dx * s, 0, 'YXZ');
      RLOC.setFromEuler(EUL);
      QINV.copy(chaseQuatWorld).invert();
      M.copy(chaseQuatWorld).multiply(RLOC).multiply(QINV);
      const tilt = (dragBtn === 2 || dragBtn === 1 || e.ctrlKey || e.metaKey);
      if (!tilt) chaseOffsetWorld.applyQuaternion(M);
      chaseQuatWorld.premultiply(M).normalize();
    } else if (cameraMode === 'free') {
      freeQuat.multiply(ROTQ.setFromEuler(EUL.set(-dy * 0.0022, -dx * 0.0022, 0, 'YXZ')));
    }
  });
  window.addEventListener('pointerup', () => { dragging = false; });
  el.addEventListener('wheel', e => {
    e.preventDefault();
    if (overviewView) {
      overviewDistance = clamp(overviewDistance * Math.exp(e.deltaY * 0.001), 8.0e6, 8.0e7);
      return;
    }
    if (cameraMode === 'chase') {
      const len = chaseOffsetWorld.length();
      if (len > 1e-9) {
        const nl = clamp(len * Math.exp(e.deltaY * CONFIG.CHASE_ZOOM_SENS),
                         CONFIG.CHASE_MIN_DIST, CONFIG.CHASE_MAX_DIST);
        chaseOffsetWorld.multiplyScalar(nl / len);
      }
    } else if (cameraMode === 'free') {
      const alt = Math.max(freePos.length() - EARTH_R_MEAN, 10);
      const step = clamp(alt * 0.12, 1, 3e5) * (-e.deltaY / 100);
      freePos.addScaledVector(TMPA.set(0, 0, -1).applyQuaternion(freeQuat), step);
    }
  }, { passive: false });
}
function setCameraMode(m) {
  if (m === cameraMode) return;
  if (m === 'free') {
    freePos.copy(camLogical);
    freeQuat.copy(camera.quaternion);
  } else if (m === 'chase') {
    let adopt = false;
    if (cameraMode === 'free') {
      TMPA.copy(satLogical).sub(camLogical).normalize();
      camera.getWorldDirection(TMPB);
      adopt = TMPA.dot(TMPB) > 0.25;
    }
    if (adopt) {
      chaseOffsetWorld.copy(camLogical).sub(satLogical);
      if (chaseOffsetWorld.length() < 1e-3) resetChaseView();
      else chaseQuatWorld.copy(camera.quaternion);
    } else {
      resetChaseView();
    }
  }
  cameraMode = m;
}
 $('cameraSelect').addEventListener('change', e => setCameraMode(e.target.value));

/* =====================================================================
   Telemetry — ported 1:1 from the Cesium version (+ clock sync + feed)
   ===================================================================== */
let latestTimestamp = 0, latestLat = 0, latestLon = 0, latestAlt = 500000;
let latestYaw = 0.0, latestPitch = 0.0, latestRoll = 0.0;
let latestBRX = 0, latestBRY = 0, latestBRZ = 0;
let latestAX = 0, latestAY = 0, latestAZ = 0;
let latestMode = "";
let telemetryRequestInFlight = false, rwTelemetryRequestInFlight = false, mtrTelemetryRequestInFlight = false;

const clockTimeEl = $('clock-time');
let simulationTimeMs = null;
function updateClock() {
  if (CONFIG.CLOCK_SOURCE === 'telemetry' && simulationTimeMs === null) { clockTimeEl.textContent = 'Waiting for simulation time'; return; }
  const t = new Date(CONFIG.CLOCK_SOURCE === 'telemetry' ? simulationTimeMs : Date.now());
  const p2 = (n) => String(n).padStart(2, '0');
  clockTimeEl.textContent = t.getUTCFullYear() + '-' + p2(t.getUTCMonth() + 1) + '-' + p2(t.getUTCDate())
    + ' ' + p2(t.getUTCHours()) + ':' + p2(t.getUTCMinutes()) + ':' + p2(t.getUTCSeconds());
}

/* =====================================================================
   Sim feed meter — updates/s, real-time factor, estimated steps/s
   ===================================================================== */
const feedEl = $('feed-meter');
const FEED = new TelemetryFeed();
function feedOnTelemetry(data) { FEED.processed(data); }
function updateFeedMeter(now) {
  if (!SETTINGS.simFeed) return;
  feedEl.textContent = 'Processed ' + FEED.rate(now).toFixed(0) + ' updates/s · ' + FEED.total + ' total';
  feedEl.style.color = '#a9bdd0';
}

function setSunDir(v) {
  sunDirVec.copy(v).normalize();
  sunDirEcef.copy(sunDirVec);
  sunLight.position.copy(sunDirVec).multiplyScalar(1e6);
}

/* =====================================================================
   Sensors panel -- MEASURED | TRUTH | ERROR for every sensor suite.
   All keys are optional (each suite gates its own telemetry), so every
   block checks for presence first and stays "--" when the suite is off.
   ===================================================================== */
function _sensRow(m, t, e, unit) {
  const f = (v, d) => (v === undefined || v === null) ? "--" : Number(v).toFixed(d);
  return `<div class="sens-row"><span>${m}</span><span>${t}</span>` +
         `<span>${e}${unit ? " " + unit : ""}</span></div>`;
}
function updateSensorsPanel(data) {
  // ---- GPS receiver ----
  const gps = $("sen-gps-body");
  if (gps) {
    if (data.gps_fix !== undefined && data.gps_fix !== null) {
      let posErr = "--";
      if (data.gps_pos_eci_x !== undefined && data.truth_pos_eci_x !== undefined) {
        const dx = data.gps_pos_eci_x - data.truth_pos_eci_x;
        const dy = data.gps_pos_eci_y - data.truth_pos_eci_y;
        const dz = data.gps_pos_eci_z - data.truth_pos_eci_z;
        posErr = (Math.sqrt(dx*dx + dy*dy + dz*dz) / 1000).toFixed(3) + " km";
      }
      gps.innerHTML =
        `<div>fix: <span class="${data.gps_fix ? "sens-ok" : "sens-bad"}">${data.gps_fix ? "YES" : "NO"}</span>` +
        ` &nbsp; SVs: ${data.gps_num_sv ?? "--"} &nbsp; PDOP: ${data.gps_pdop?.toFixed(2) ?? "--"}</div>` +
        `<div>acc h/v: ${data.gps_h_acc_m?.toFixed(2) ?? "--"} / ${data.gps_v_acc_m?.toFixed(2) ?? "--"} m` +
        ` &nbsp; latency: ${data.gps_latency_s != null ? (data.gps_latency_s * 1000).toFixed(0) + " ms" : "--"}</div>` +
        `<div>fix pos: lat ${data.gps_lat_deg?.toFixed(4) ?? "--"}°, lon ${data.gps_lon_deg?.toFixed(4) ?? "--"}°, alt ${data.gps_alt_m?.toFixed(0) ?? "--"} m</div>` +
        `<div>belief-vs-truth position error: <b>${posErr}</b></div>`;
    } else gps.textContent = "-- (GPS off)";
  }
  // ---- Gyroscope ----
  const gyro = $("sen-gyro-body");
  if (gyro) {
    if (data.imu_gyro_x_rad_s !== undefined && data.imu_gyro_x_rad_s !== null) {
      const dg = (r) => r * 180 / Math.PI;
      gyro.innerHTML =
        _sensRow(dg(data.imu_gyro_x_rad_s).toFixed(4), data.body_rate_x?.toFixed(4) ?? "--",
                 (dg(data.imu_gyro_x_rad_s) - (data.body_rate_x ?? 0)).toFixed(4)) +
        _sensRow(dg(data.imu_gyro_y_rad_s).toFixed(4), data.body_rate_y?.toFixed(4) ?? "--",
                 (dg(data.imu_gyro_y_rad_s) - (data.body_rate_y ?? 0)).toFixed(4)) +
        _sensRow(dg(data.imu_gyro_z_rad_s).toFixed(4), data.body_rate_z?.toFixed(4) ?? "--",
                 (dg(data.imu_gyro_z_rad_s) - (data.body_rate_z ?? 0)).toFixed(4));
      const gf = $("sen-gyro-flags");
      if (gf) gf.innerHTML = `valid: <span class="${data.imu_gyro_valid ? "sens-ok" : "sens-bad"}">${data.imu_gyro_valid}</span>` +
        ` &nbsp; saturated: ${data.imu_gyro_saturated ? "<span class='sens-warn'>YES</span>" : "no"}`;
    } else { gyro.innerHTML = "-- (IMU off)"; const gf = $("sen-gyro-flags"); if (gf) gf.textContent = ""; }
  }
  // ---- Magnetometer ----
  const mag = $("sen-mag-body");
  if (mag) {
    if (data.imu_mag_x_nT !== undefined && data.imu_mag_x_nT !== null) {
      mag.innerHTML =
        _sensRow(data.imu_mag_x_nT.toFixed(1), data.truth_mag_body_x_nT?.toFixed(1) ?? "--",
                 (data.imu_mag_x_nT - (data.truth_mag_body_x_nT ?? 0)).toFixed(1)) +
        _sensRow(data.imu_mag_y_nT.toFixed(1), data.truth_mag_body_y_nT?.toFixed(1) ?? "--",
                 (data.imu_mag_y_nT - (data.truth_mag_body_y_nT ?? 0)).toFixed(1)) +
        _sensRow(data.imu_mag_z_nT.toFixed(1), data.truth_mag_body_z_nT?.toFixed(1) ?? "--",
                 (data.imu_mag_z_nT - (data.truth_mag_body_z_nT ?? 0)).toFixed(1));
      const mf = $("sen-mag-flags");
      if (mf) mf.innerHTML = `valid: <span class="${data.imu_mag_valid ? "sens-ok" : "sens-bad"}">${data.imu_mag_valid}</span>` +
        ` &nbsp; saturated: ${data.imu_mag_saturated ? "<span class='sens-warn'>YES</span>" : "no"}`;
    } else { mag.innerHTML = "-- (IMU off)"; const mf = $("sen-mag-flags"); if (mf) mf.textContent = ""; }
  }
  // ---- Sun sensor array ----
  const sunStatus = $("sen-sun-status");
  if (sunStatus) {
    if (data.sun_arr_valid !== undefined && data.sun_arr_valid !== null && data.sun_arr_cells) {
      const ec = data.sun_arr_eclipse_factor;
      sunStatus.innerHTML = `receipt valid: <span class="${data.sun_arr_valid ? "sens-ok" : "sens-bad"}">${data.sun_arr_valid}</span>` +
        ` &nbsp; cells used: ${data.sun_arr_cells_used ?? "--"}/${data.sun_arr_cells_total ?? "--"}` +
        ` &nbsp; eclipse F: ${ec != null ? ec.toFixed(2) : "--"}` +
        ` &nbsp; method: ${data.sun_arr_method ?? "--"}`;
      const tbl = $("sen-sun-cells");
      if (tbl) {
        let rows = "<tr><th>cell</th><th>out %</th><th>ADC</th><th>cone°</th><th>status</th></tr>";
        for (const c of data.sun_arr_cells) {
          const st = c.shadowed ? "<span class=sens-bad>SHADOW</span>"
            : (!c.in_fov ? "out-FOV"
            : (c.eclipse_factor < 1 ? "<span class=sens-warn>ECLIPSE</span>"
            : (c.used ? "<span class=sens-ok>used</span>" : "in-FOV")));
          rows += `<tr><td>${c.name}</td><td>${c.output_pct.toFixed(1)}</td>` +
                  `<td>${c.adc_counts}</td><td>${c.angle_deg != null ? c.angle_deg.toFixed(1) : "--"}</td>` +
                  `<td>${st}</td></tr>`;
        }
        tbl.innerHTML = rows;
      }
      const recon = $("sen-sun-recon");
      if (recon) {
        if (data.sun_arr_recon_valid) {
          const v = [data.sun_arr_recon_x, data.sun_arr_recon_y, data.sun_arr_recon_z];
          const w = [data.sun_arr_truth_x, data.sun_arr_truth_y, data.sun_arr_truth_z];
          recon.innerHTML = `recon: [${v.map(x => x.toFixed(3)).join(", ")}] vs truth: ` +
            `[${w.map(x => x.toFixed(3)).join(", ")}] -- error ` +
            `<span class="${data.sun_arr_error_deg < 2 ? "sens-ok" : "sens-warn"}">` +
            `${data.sun_arr_error_deg?.toFixed(3)}°</span>`;
        } else recon.innerHTML = "reconstruction FAILED (eclipse/geometry) -- coasting on gyro+mag";
      }
    } else {
      sunStatus.textContent = "-- (IMU off)";
      const tbl = $("sen-sun-cells"); if (tbl) tbl.innerHTML = "";
      const recon = $("sen-sun-recon"); if (recon) recon.textContent = "";
    }
  }
  // ---- Attitude estimator ----
  const est = $("sen-est");
  if (est) {
    if (data.att_est_quat_w !== undefined && data.att_est_quat_w !== null) {
      const q = [data.att_est_quat_x, data.att_est_quat_y, data.att_est_quat_z, data.att_est_quat_w];
      const qt = [data.truth_att_quat_x, data.truth_att_quat_y, data.truth_att_quat_z, data.truth_att_quat_w];
      est.innerHTML =
        `<div>belief quat: [${q.map(x => x.toFixed(4)).join(", ")}]</div>` +
        `<div>truth quat: [${qt.map(x => x == null ? "--" : x.toFixed(4)).join(", ")}]</div>` +
        `<div>estimation error: <span class="${data.att_est_error_deg < 2 ? "sens-ok" : (data.att_est_error_deg < 15 ? "sens-warn" : "sens-bad")}">` +
        `${data.att_est_error_deg?.toFixed(3)}°</span>` +
        ` &nbsp; corrections: ${data.att_est_corrections ?? "--"}` +
        ` &nbsp; propagations: ${data.att_est_propagations ?? "--"}</div>` +
        `<div>sun correction in use: <span class="${data.att_est_sun_used ? "sens-ok" : "sens-warn"}">` +
        `${data.att_est_sun_used ? "YES" : "NO (coasting)"}</span></div>`;
    } else est.textContent = "-- (IMU off)";
  }
}

function fetchTelemetry() {
  if (telemetryRequestInFlight) return;
  telemetryRequestInFlight = true;
  fetch('/api/latest')
    .then(response => {
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      return response.json();
    })
    .then(data => {
      if (data && data.latitude_deg !== undefined) {
        if (!FEED.isNew(data)) return;
        if (typeof data.satellite_name === 'string' && data.satellite_name.trim())
          satelliteNameLabel.el.textContent = data.satellite_name.trim();
        updateSensorMarkers(data);
        updateOrbitPath(data);
        latestTimestamp = data.timestamp;
        latestLat = data.latitude_deg;
        latestLon = data.longitude_deg;
        latestAlt = data.altitude_m;
        latestYaw = data.yaw_deg;
        latestPitch = data.pitch_deg;
        latestRoll = data.roll_deg;
        latestBRX = data.body_rate_x; latestBRY = data.body_rate_y; latestBRZ = data.body_rate_z;
        latestAX = data.alpha_x; latestAY = data.alpha_y; latestAZ = data.alpha_z;

        latLonToECEF(latestLat, latestLon, latestAlt, satLogicalTarget);

        if (data.quat_x !== undefined) {
          satQuatTarget.set(data.quat_x, data.quat_y, data.quat_z, data.quat_w);
          hasBodyQuat = true;
          if (!quatPrimed) { satGroup.quaternion.copy(satQuatTarget); quatPrimed = true; }
        }
        if (data.sun_ecef_x !== undefined) setSunDir(TMPA.set(data.sun_ecef_x, data.sun_ecef_y, data.sun_ecef_z));
        if (data.moon_position_ecef_m) moonPositionEcef = new THREE.Vector3(...data.moon_position_ecef_m);
        if (data.moon_ecef_x !== undefined) {
          moonDirEcef = new THREE.Vector3(data.moon_ecef_x, data.moon_ecef_y, data.moon_ecef_z).normalize();
          moonMesh.visible = true;
        }
        if (data.nadir_ecef_x !== undefined)
          nadirDirEcef = new THREE.Vector3(data.nadir_ecef_x, data.nadir_ecef_y, data.nadir_ecef_z).normalize();
        if (data.sun_sweep_ecef_x !== undefined)
          sweepDirEcef = new THREE.Vector3(data.sun_sweep_ecef_x, data.sun_sweep_ecef_y, data.sun_sweep_ecef_z).normalize();
        if (data.mode !== undefined) latestMode = data.mode;

        if (CONFIG.CLOCK_SOURCE === 'telemetry') {
          const td = parseUTCDate(data.timestamp);
          if (td) simulationTimeMs = td.getTime();
          if (data.eci_to_ecef_matrix) {
            const a = data.eci_to_ecef_matrix;
            const rotation = new THREE.Matrix4().set(a[0][0],a[0][1],a[0][2],0,a[1][0],a[1][1],a[1][2],0,a[2][0],a[2][1],a[2][2],0,0,0,0,1);
            for (const o of starAnchors) if (o.isPoints) o.quaternion.setFromRotationMatrix(rotation);
          }
        }

        updateSensorsPanel(data);
        /* ---- pointing-error rows (identical logic) ---- */
        if (data.sun_pointing_error_deg !== undefined) {
          const errEl = $("sun-ptg-err");
          if (errEl) {
            if (latestMode === "POINTING") {
              const err = data.sun_pointing_error_deg;
              errEl.textContent = err.toFixed(3) + "°";
              errEl.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { errEl.textContent = "-- (not in sun-pointing mode)"; errEl.style.color = "#9aa4b2"; }
          }
        }
        /* ---- satellite's OWN-data pointing error (IMU estimate) ----
           Backend sends ONE comparable row: imu_own_axis_error_deg = the SAME
           mode-specific boresight metric as the truth rows, but computed from
           the onboard estimate q_est (nadir axis error for NADIR, sun axis
           for POINTING, ...). Same number, same mode axis as truth -- so own
           8-9 deg vs truth 2 deg is impossible; own must sit ~+/-1 deg
           around truth. The full-quaternion imu_att_* fields are NOT drawn
           (they also penalise twist about the boresight, which is why they
           read larger for the same true attitude). */
        if (data.imu_own_axis_error_deg !== undefined && data.imu_own_axis_error_deg !== null) {
          const ownErr = data.imu_own_axis_error_deg;
          const stale = (data.imu_mag_valid === false);
          for (const id of ["rw-ptg-err-own", "mtr-ptg-err-own"]) {
            const el = $(id);
            if (!el) continue;
            el.textContent = ownErr.toFixed(3) + "°" + (stale ? " (STALE)" : "");
            el.style.color = ownErr < 2 ? "#7fff7f" : (ownErr < 15 ? "#ffd27f" : "#ff7f7f");
          }
        }
        if (data.moon_pointing_error_deg !== undefined) {
          const el = $("moon-ptg-err");
          if (el) {
            if (latestMode === "MOON") {
              const err = data.moon_pointing_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in moon-pointing mode)"; el.style.color = "#9aa4b2"; }
          }
        }
        if (data.nadir_pointing_error_deg !== undefined) {
          const el = $("nadir-ptg-err");
          if (el) {
            if (latestMode === "NADIR") {
              const err = data.nadir_pointing_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in nadir-pointing mode)"; el.style.color = "#9aa4b2"; }
          }
        }
        if (data.kinematic_robustness_error_deg !== undefined) {
          const el = $("kinrob-ptg-err");
          if (el) {
            if (latestMode === "KINEMATIC_ROBUSTNESS") {
              const err = data.kinematic_robustness_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in kinematic-robustness mode)"; el.style.color = "#9aa4b2"; }
          }
        }
        if (data.nominal_in_orbit_error_deg !== undefined) {
          const el = $("nominal-ptg-err");
          if (el) {
            if (latestMode === "NOMINAL_IN_ORBIT") {
              const err = data.nominal_in_orbit_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in nominal-in-orbit mode)"; el.style.color = "#9aa4b2"; }
          }
        }
        if (data.sun_pointing_rw_error_deg !== undefined) {
          const el = $("sun-ptg-rw-err");
          if (el) {
            if (latestMode === "SUN_POINTING_RW") {
              const err = data.sun_pointing_rw_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in sun-pointing-RW mode)"; el.style.color = "#9aa4b2"; }
          }
        }
        if (data.sun_sweep_error_deg !== undefined) {
          const el = $("sunsweep-ptg-err");
          if (el) {
            if (latestMode === "SUN_SWEEP") {
              const err = data.sun_sweep_error_deg;
              el.textContent = err.toFixed(3) + "°";
              el.style.color = err < 2 ? "#7fff7f" : (err < 15 ? "#ffd27f" : "#ff7f7f");
            } else { el.textContent = "-- (not in sun-sweep mode)"; el.style.color = "#9aa4b2"; }
          }
        }

        /* ---- telemetry box ---- */
        $("timestamp").textContent = "Timestamp: " + latestTimestamp;
        $("lat").textContent    = "Lat: "   + latestLat.toFixed(6) + "°";
        $("lon").textContent    = "Lon: "   + latestLon.toFixed(6) + "°";
        $("alt").textContent    = "Alt: "   + latestAlt.toFixed(1) + " m";
        $("yaw").textContent    = "Yaw: "   + latestYaw.toFixed(2) + "°";
        $("pitch").textContent  = "Pitch: " + latestPitch.toFixed(2) + "°";
        $("roll").textContent   = "Roll: "  + latestRoll.toFixed(2) + "°";

        const targetFieldsByMode = {
          "POINTING":             { prefix: "target",                      label: "sun pointing" },
          "NADIR":                { prefix: "nadir_target",                label: "nadir pointing" },
          "MOON":                 { prefix: "moon_target",                 label: "moon pointing" },
          "SUN_SWEEP":            { prefix: "sun_sweep_target",            label: "sun sweep" },
          "SUN_POINTING_RW":      { prefix: "sun_pointing_rw_target",      label: "sun pointing (RW)" },
          "NOMINAL_IN_ORBIT":     { prefix: "nominal_in_orbit_target",     label: "nominal in-orbit" },
          "KINEMATIC_ROBUSTNESS": { prefix: "kinematic_robustness_target", label: "kinematic robustness" },
        };
        const targetInfo = targetFieldsByMode[latestMode];
        if (targetInfo && data[targetInfo.prefix + "_yaw_deg"] !== undefined) {
          $("target_yaw").textContent   = "Required Yaw ("   + targetInfo.label + "): " + data[targetInfo.prefix + "_yaw_deg"].toFixed(2)   + "°";
          $("target_pitch").textContent = "Required Pitch (" + targetInfo.label + "): " + data[targetInfo.prefix + "_pitch_deg"].toFixed(2) + "°";
          $("target_roll").textContent  = "Required Roll ("  + targetInfo.label + "): " + data[targetInfo.prefix + "_roll_deg"].toFixed(2)  + "°";
        } else {
          $("target_yaw").textContent   = "Required Yaw: -- (mode has no target attitude)";
          $("target_pitch").textContent = "Required Pitch: --";
          $("target_roll").textContent  = "Required Roll: --";
        }
        $("body_rate_x").textContent = "X body rate: " + latestBRX.toFixed(2) + "°/s";
        $("body_rate_y").textContent = "Y body rate: " + latestBRY.toFixed(2) + "°/s";
        $("body_rate_z").textContent = "Z body rate: " + latestBRZ.toFixed(2) + "°/s";
        $("alpha_x").textContent = "X acceleration rate: " + latestAX.toFixed(6) + "°/s2";
        $("alpha_y").textContent = "Y acceleration rate: " + latestAY.toFixed(6) + "°/s2";
        $("alpha_z").textContent = "Z acceleration rate: " + latestAZ.toFixed(6) + "°/s2";
        if (data.srp_acceleration_eci_x !== undefined) {
          loadSpacecraftModel(data.spacecraft_model_url, data.center_of_mass_body_m);
          if (data.spacecraft_configuration) $("spacecraft-configuration").textContent = `Configuration: ${data.spacecraft_configuration} · ${data.spacecraft_mass_kg} kg`;
          if (data.disturbance_srp_unm !== undefined) $("srp_torque").textContent = `SRP torque: ${data.disturbance_srp_unm.toFixed(3)} µN·m`;
          $("srp_acceleration").textContent = "SRP acceleration (ECI): [" + data.srp_acceleration_eci_x.toExponential(3) + ", " + data.srp_acceleration_eci_y.toExponential(3) + ", " + data.srp_acceleration_eci_z.toExponential(3) + "] m/s²";
        }
        if (data.eclipse_fraction !== undefined) {
          $("eclipse_fraction").textContent = "Eclipse illumination: " + data.eclipse_fraction.toFixed(3);
        }
        if (data.drag_acceleration_eci_x !== undefined) {
          $("drag_acceleration").textContent = "Drag acceleration (ECI): [" + data.drag_acceleration_eci_x.toExponential(3) + ", " + data.drag_acceleration_eci_y.toExponential(3) + ", " + data.drag_acceleration_eci_z.toExponential(3) + "] m/s²";
        }
        if (data.disturbance_net_unm !== undefined) {
          $("dist_gg").textContent = "Gravity-gradient torque: " + data.disturbance_gravity_gradient_unm.toFixed(3) + " µN·m";
          $("dist_dipole").textContent = "Residual-dipole torque: " + data.disturbance_residual_dipole_unm.toFixed(3) + " µN·m";
          $("dist_drag").textContent = "Atmospheric-drag torque: " + data.disturbance_atmospheric_drag_unm.toFixed(3) + " µN·m";
          $("dist_net").textContent = "Net disturbance torque: " + data.disturbance_net_unm.toFixed(3) + " µN·m";
        }
        if (data.truth_pos_eci_x !== undefined) {
          $("truth_pos_eci").textContent = "Real pos (ECI): [" + data.truth_pos_eci_x.toFixed(1) + ", " + data.truth_pos_eci_y.toFixed(1) + ", " + data.truth_pos_eci_z.toFixed(1) + "] m";
        }
        if (data.gps_pos_eci_x !== undefined) {
          $("gps_pos_eci").textContent = "GPS pos (ECI): [" + data.gps_pos_eci_x.toFixed(1) + ", " + data.gps_pos_eci_y.toFixed(1) + ", " + data.gps_pos_eci_z.toFixed(1) + "] m";
        }
        if (data.imu_gyro_x_rad_s !== undefined && data.imu_gyro_x_rad_s !== null) {
          $("imu_gyro").textContent = "IMU gyro (rad/s): [" + data.imu_gyro_x_rad_s.toExponential(3) + ", " + data.imu_gyro_y_rad_s.toExponential(3) + ", " + data.imu_gyro_z_rad_s.toExponential(3) + "]" + (data.imu_gyro_valid ? "" : " (STALE)");
        }
        if (data.imu_mag_x_nT !== undefined && data.imu_mag_x_nT !== null) {
          $("imu_mag").textContent = "IMU mag (nT): [" + data.imu_mag_x_nT.toFixed(1) + ", " + data.imu_mag_y_nT.toFixed(1) + ", " + data.imu_mag_z_nT.toFixed(1) + "]" + (data.imu_mag_valid ? "" : " (STALE)");
        }
        $("status").textContent = "";
        if (!telemetryPrimed) { satLogical.copy(satLogicalTarget); telemetryPrimed = true; }
        feedOnTelemetry(data);
        window.dispatchEvent(new CustomEvent('simulation-telemetry', {detail:data}));
      } else {
        $("status").textContent = "Waiting for data... run the propagator script.";
      }
    })
    .catch(error => {
      console.error('Error fetching telemetry:', error);
      $("lat").textContent = "Error: See console";
    })
    .finally(() => { telemetryRequestInFlight = false; });
}

async function fetchRWTorques() {
  if (rwTelemetryRequestInFlight) return;
  rwTelemetryRequestInFlight = true;
  try {
    const res = await fetch("/rw_telemetry");
    const data = await res.json();
    $("rw-time").textContent = data.time.toFixed(2) + " s";
    $("rw-mode").textContent = data.mode;
    $("rw1").textContent = (data.rw_torques[0] * 1000).toFixed(3);
    $("rw2").textContent = (data.rw_torques[1] * 1000).toFixed(3);
    $("rw3").textContent = (data.rw_torques[2] * 1000).toFixed(3);
    $("rw4").textContent = (data.rw_torques[3] * 1000).toFixed(3);
    applyPanelVisibility(data.mode);
  } catch (err) {
    console.warn("RW telemetry unavailable:", err);
  } finally {
    rwTelemetryRequestInFlight = false;
  }
}

async function fetchMTRTelemetry() {
  if (mtrTelemetryRequestInFlight) return;
  mtrTelemetryRequestInFlight = true;
  try {
    const res = await fetch("/mtr_telemetry");
    const data = await res.json();
    $("mtr-time").textContent = data.time.toFixed(2) + " s";
    $("mtr-mode").textContent = data.mode;
    $("tau-x").textContent = data.mtr_torques[0].toExponential(3);
    $("tau-y").textContent = data.mtr_torques[1].toExponential(3);
    $("tau-z").textContent = data.mtr_torques[2].toExponential(3);
    $("dipole-x").textContent = data.mtr_dipole[0].toFixed(3);
    $("dipole-y").textContent = data.mtr_dipole[1].toFixed(3);
    $("dipole-z").textContent = data.mtr_dipole[2].toFixed(3);
    $("current-x").textContent = data.mtr_currents[0].toFixed(3);
    $("current-y").textContent = data.mtr_currents[1].toFixed(3);
    $("current-z").textContent = data.mtr_currents[2].toFixed(3);
    applyPanelVisibility(data.mode);
  } catch (err) {
    console.warn("MTR telemetry unavailable:", err);
  } finally {
    mtrTelemetryRequestInFlight = false;
  }
}

function applyPanelVisibility(mode) {
  const rwPanel = $("rw-panel"), mtrPanel = $("mtr-panel");
  const sliders = document.querySelector(".control-panel");
  const usesReactionWheels = (mode === "RW" || mode === "MOON" || mode === "NADIR" ||
    mode === "SUN_SWEEP" || mode === "SUN_POINTING_RW" || mode === "NOMINAL_IN_ORBIT" ||
    mode === "KINEMATIC_ROBUSTNESS");
  if (rwPanel)  rwPanel.style.display  = usesReactionWheels ? "block" : "none";
  if (mtrPanel) mtrPanel.style.display = usesReactionWheels ? "none"  : "block";
  if (sliders)  sliders.style.display  = (mode === "RW") ? "flex" : "none";
  const rowVisibility = { "moon-ptg-err": "MOON", "nadir-ptg-err": "NADIR", "sunsweep-ptg-err": "SUN_SWEEP",
    "sun-ptg-rw-err": "SUN_POINTING_RW", "nominal-ptg-err": "NOMINAL_IN_ORBIT", "kinrob-ptg-err": "KINEMATIC_ROBUSTNESS" };
  for (const [id, m] of Object.entries(rowVisibility)) {
    const el = $(id);
    if (el && el.parentElement) el.parentElement.style.display = (mode === m) ? "flex" : "none";
  }
}

setInterval(() => {
  const m = latestMode;
  const sunOn = (m === "POINTING" || m === "SUN_POINTING" || m === "SUN_POINTING_RW");
  sunLine.line.visible = sunOn;
  panelNormalLine.line.visible = sunOn;
  const moonOn = (m === "MOON");
  moonLine.line.visible = moonOn && !!moonDirEcef;
  moonPanelLine.line.visible = moonOn;
  nadirLine.line.visible = (m === "NADIR" || m === "NOMINAL_IN_ORBIT" || m === "KINEMATIC_ROBUSTNESS") && !!nadirDirEcef;
  sweepLine.line.visible = (m === "SUN_SWEEP") && !!sweepDirEcef;
}, updateInterval);

setInterval(fetchRWTorques, updateInterval);
setInterval(fetchMTRTelemetry, updateInterval);
setInterval(fetchTelemetry, updateInterval);
fetchTelemetry();

/* =====================================================================
   Controls UI — same endpoints
   ===================================================================== */
function sendData(label, value) {
  $(label + '-label').textContent = value;
  fetch('/update/control/inputs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: label, value: parseFloat(value) })
  });
}
function adjust(label, delta) {
  const slider = $(label + '-slider');
  let v = parseFloat(slider.value) + delta;
  v = Math.max(-180, Math.min(180, v));
  slider.value = v;
  sendData(label, v);
}
window.adjust = adjust;
window.sendData = sendData;

 $("modeSelect").addEventListener('change', e => {
  fetch('/update/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: e.target.value })
  });
});

 $("axis-toggle").addEventListener('click', () => {
  axesVisible = !axesVisible;
  const tickEl = $("tick");
  tickEl.textContent = axesVisible ? '✓' : '';
  tickEl.style.background = axesVisible ? '#4CAF50' : '#333';
  $("axis-toggle").classList.toggle('on', axesVisible);
  for (const a of axes) a.line.visible = axesVisible;
});

window.addEventListener('resize', () => {
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
});

window.scene = scene; window.camera = camera;
window.renderer = renderer; window.satelliteGroup = satGroup;

/* =====================================================================
   Payload video stream → ws://localhost:8765
   ===================================================================== */
const capCanvas = document.createElement('canvas');
capCanvas.width = SETTINGS.streamW; capCanvas.height = SETTINGS.streamH;
const capCtx = capCanvas.getContext('2d');
const capLogical = new THREE.Vector3();
const SIZE2 = new THREE.Vector2();
let streamDue = false;

function applyStreamSize() {
  capCanvas.width = SETTINGS.streamW;
  capCanvas.height = SETTINGS.streamH;
  payloadCamera.aspect = SETTINGS.streamW / SETTINGS.streamH;
  payloadCamera.updateProjectionMatrix();
}
applyStreamSize();

async function sendBlob(blob) {
  try {
    const ab = blob.arrayBuffer ? await blob.arrayBuffer() : await new Response(blob).arrayBuffer();
    if (videoSocket && videoSocket.readyState === 1) {
      console.log("Sending frame, size:", ab.byteLength);
      videoSocket.send(ab);
    }
  } catch (e) { console.error("Send failed:", e); }
}

function doStreamCapture() {
  if (!videoSocket || videoSocket.readyState !== 1) return;
  try {
    if (CONFIG.STREAM_SOURCE === 'payload') computePayloadPose(capLogical, payloadCamera);
    else computeFixedPose(capLogical, payloadCamera);

    placeWorld(capLogical);
    const DPR = renderer.getPixelRatio();
    const cw = renderer.domElement.width, ch = renderer.domElement.height;
    const devW = Math.min(SETTINGS.streamW, cw), devH = Math.min(SETTINGS.streamH, ch);
    renderer.setScissorTest(true);
    renderer.setScissor(0, 0, devW / DPR, devH / DPR);
    renderer.setViewport(0, 0, devW / DPR, devH / DPR);
    renderer.render(scene, payloadCamera);
    renderer.setScissorTest(false);
    renderer.getSize(SIZE2);
    renderer.setViewport(0, 0, SIZE2.x, SIZE2.y);
    capCtx.drawImage(renderer.domElement, 0, ch - devH, devW, devH, 0, 0, devW, devH);

    capCanvas.toBlob(blob => { if (blob) sendBlob(blob); }, 'image/jpeg', SETTINGS.streamQ);
  } catch (e) {
    console.error("Capture error:", e);
    renderer.setScissorTest(false);
    renderer.getSize(SIZE2);
    renderer.setViewport(0, 0, SIZE2.x, SIZE2.y);
  }
}
let videoSocket = null;
try {
  videoSocket = new WebSocket(CONFIG.STREAM_URL);
  videoSocket.binaryType = 'arraybuffer';
  videoSocket.onopen = () => {
    console.log("WebSocket connected");
    setInterval(() => { streamDue = true; }, CONFIG.STREAM_MS);
  };
  videoSocket.onerror = () => console.warn("WebSocket not available:", CONFIG.STREAM_URL);
} catch (e) { console.warn("WebSocket setup failed:", e); }

/* =====================================================================
   Settings panel, quality presets (incl. 4K supersample), FPS + governor
   ===================================================================== */
const fpsEl = $('fps-meter');
let fpsFrames = 0, fpsAccum = 0, fpsShown = 60, govAccum = 0;
function dprCap() { return Math.min(window.devicePixelRatio || 1, CONFIG.PIXEL_RATIO_CAP); }
function applyDpr() {
  const pixelCap = Math.sqrt(16000000 / Math.max(1, container.clientWidth * container.clientHeight));
  renderer.setPixelRatio(Math.min(curDpr, pixelCap));
  renderer.setSize(container.clientWidth, container.clientHeight);
}
const PRESETS = {
  low:      { dpr: 0.75, budget: 80,  concurrent: 5 },
  balanced: { dpr: 1.0,  budget: 140, concurrent: 8 },
  high:     { dpr: 1.5,  budget: 190, concurrent: 10 },
  ultra:    { dpr: 0,    budget: 250, concurrent: 11 },  /* 0 → native device resolution */
  '4k':     { dpr: 2.0,  budget: 300, concurrent: 12 },  /* supersampled 4× pixel count */
};
function applyPreset(name) {
  applyTextureQuality(name);
  if (name === 'auto') { document.body.dataset.quality = name; document.body.dataset.economy = String((navigator.deviceMemory || 4) <= 4); for (const o of starAnchors) if (o.isPoints) o.geometry.setDrawRange(0, Infinity); CONFIG.TILE_BUDGET = 120; CONFIG.MAX_CONCURRENT = 7; curDpr = Math.min(1.25, dprCap()); applyDpr(); return; }
  const p = PRESETS[name]; if (!p) return;
  curDpr = (p.dpr === 0) ? dprCap() : p.dpr;
  document.body.dataset.quality = name;
  document.body.dataset.economy = String(name === 'low');
  for (const o of starAnchors) if (o.isPoints) o.geometry.setDrawRange(0, name === 'low' ? Math.ceil(o.geometry.attributes.position.count * 0.3) : Infinity);
  CONFIG.TILE_BUDGET = p.budget;
  CONFIG.MAX_CONCURRENT = p.concurrent;
  applyDpr();
}
/* No fps cap exists: rAF runs at display refresh. Auto only intervenes
   when fps drops below ~45, and climbs back above ~57. */
function tickFPS(dt) {
  fpsFrames++; fpsAccum += dt; govAccum += dt;
  if (fpsAccum >= 0.5) {
    fpsShown = fpsFrames / fpsAccum;
    window.dispatchEvent(new CustomEvent('simulation-fps', {detail:fpsShown}));
    fpsFrames = 0; fpsAccum = 0;
    if (SETTINGS.fps) {
      fpsEl.style.display = 'block';
      fpsEl.textContent = fpsShown.toFixed(0) + ' fps';
      fpsEl.style.color = fpsShown >= 50 ? '#9fe08f' : (fpsShown >= 30 ? '#ffd27f' : '#ff7f7f');
    } else fpsEl.style.display = 'none';
  }
  if (SETTINGS.preset === 'auto' && govAccum >= 2.5) {
    govAccum = 0;
    if (fpsShown < 45 && curDpr > 0.75) { curDpr = Math.max(0.75, curDpr - 0.2); applyDpr(); }
    else if (fpsShown > 57 && curDpr < Math.min(1.5, dprCap())) { curDpr = Math.min(1.5, dprCap(), curDpr + 0.1); applyDpr(); }
  }
}

function applySettings() {
  renderer.toneMappingExposure = SETTINGS.exposure;
  baseMat.uniforms.nightBoost.value = CONFIG.NIGHT_BOOST * SETTINGS.city;
  moonTintVec.copy(moonlightBase).multiplyScalar(SETTINGS.night);
  atmoMat.uniforms.uIntensity.value = SETTINGS.atmo;
  for (const m of starMats) m.color.setScalar(0.55 * SETTINGS.stars);
  hazeMat.opacity = Math.min(1, 0.80 * SETTINGS.stars);
  hazeMat.color.setRGB(1.3, 1.18, 1.45);
  sunSprite.scale.set(CONFIG.SUN_GLARE_SIZE * SETTINGS.sunSize, CONFIG.SUN_GLARE_SIZE * SETTINGS.sunSize, 1);
  moonMesh.scale.setScalar(SETTINGS.moonSize);
  sunLight.intensity = CONFIG.SUN_INTENSITY * SETTINGS.modelSun;
  for (const m of modelMats) if (m.envMapIntensity !== undefined)
    m.envMapIntensity = CONFIG.MODEL_ENV * SETTINGS.modelEnv;
  CONFIG.TARGET_PX = SETTINGS.sharp;
}

 $('settings-toggle').addEventListener('click', () => window.setSettingsOpen(!$('settings-panel').classList.contains('open')));
 $('settings-close').addEventListener('click', () => {
  window.setSettingsOpen(false);
});

function bindRange(id, key, fmt) {
  const el = $(id), val = $(id + '-val');
  el.value = SETTINGS[key];
  val.textContent = fmt(SETTINGS[key]);
  el.addEventListener('input', () => {
    SETTINGS[key] = parseFloat(el.value);
    val.textContent = fmt(SETTINGS[key]);
    applySettings(); saveSettings();
  });
}
const f2 = (v) => (+v).toFixed(2);
bindRange('set-exposure', 'exposure', f2);
bindRange('set-night', 'night', f2);
bindRange('set-city', 'city', f2);
bindRange('set-atmo', 'atmo', f2);
bindRange('set-clouds', 'clouds', f2);
bindRange('set-stars', 'stars', f2);
bindRange('set-sunsize', 'sunSize', f2);
bindRange('set-moonsize', 'moonSize', f2);
bindRange('set-modelsun', 'modelSun', f2);
bindRange('set-modelenv', 'modelEnv', f2);
bindRange('set-streamq', 'streamQ', f2);
bindRange('set-chasesens', 'chaseSens', f2);

function bindCheck(id, key, after) {
  const el = $(id);
  el.checked = !!SETTINGS[key];
  el.addEventListener('change', () => { SETTINGS[key] = el.checked; saveSettings(); if (after) after(); });
}
bindCheck('set-fps', 'fps', () => { if (!SETTINGS.fps) fpsEl.style.display = 'none'; });
bindCheck('set-simfeed', 'simFeed', () => { feedEl.style.display = SETTINGS.simFeed ? 'block' : 'none'; });
bindCheck('set-clouds-on', 'cloudsOn');
bindCheck('set-stream-on', 'streamOn');
bindCheck('set-attlock', 'attLock');   // toggling never jumps the view (per-frame delta)

feedEl.style.display = SETTINGS.simFeed ? 'block' : 'none';

{ const el = $('set-preset'); el.value = SETTINGS.preset;
  el.addEventListener('change', () => { SETTINGS.preset = el.value; applyPreset(el.value); saveSettings(); }); }
{ const el = $('set-sharp'); el.value = String(SETTINGS.sharp);
  el.addEventListener('change', () => { SETTINGS.sharp = parseInt(el.value, 10); applySettings(); saveSettings(); }); }
{ const el = $('set-streamsize');
  const cur = SETTINGS.streamW + 'x' + SETTINGS.streamH;
  for (const o of el.options) if (o.value === cur) el.value = cur;
  el.addEventListener('change', () => {
    const [w, h] = el.value.split('x').map(Number);
    SETTINGS.streamW = w; SETTINGS.streamH = h;
    applyStreamSize(); saveSettings();
  }); }

applyPreset(SETTINGS.preset);
applySettings();

/* =====================================================================
   Per-frame updates + render loop
   ===================================================================== */
function smoothSatellite(dt) {
  if (CONFIG.SMOOTH <= 0) { satLogical.copy(satLogicalTarget); if (hasBodyQuat) satGroup.quaternion.copy(satQuatTarget); return; }
  const k = 1 - Math.exp(-dt * CONFIG.SMOOTH);
  satLogical.lerp(satLogicalTarget, k);
  if (hasBodyQuat) {
    if (SETTINGS.smoothAttitude) satGroup.quaternion.slerp(satQuatTarget, k);
    else satGroup.quaternion.copy(satQuatTarget);
  }
}

const LINE_END = new THREE.Vector3();
function updateLines() {
  sunLine.setEndpoints(ZERO, LINE_END.copy(sunDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
  if (moonDirEcef)  moonLine.setEndpoints(ZERO, LINE_END.copy(moonDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
  if (nadirDirEcef) nadirLine.setEndpoints(ZERO, LINE_END.copy(nadirDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
  if (sweepDirEcef) sweepLine.setEndpoints(ZERO, LINE_END.copy(sweepDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
}

const LPOS = new THREE.Vector3(), LDIR = new THREE.Vector3();
function updateLabels() {
  camera.updateMatrixWorld();
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
  camera.getWorldDirection(LDIR);
  const rect = container.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  for (const L of labels) {
    if ((!L.el.textContent.includes('We are here') && L !== satelliteNameLabel && camLogical.distanceTo(satLogical) > 30000) || !L.isVisible()) { L.el.style.display = 'none'; continue; }
    L.getPos(LPOS);
    LPOS.sub(camLogical);
    if (LPOS.dot(LDIR) <= 0) { L.el.style.display = 'none'; continue; }
    LPOS.project(camera);
    if (LPOS.x < -1.05 || LPOS.x > 1.05 || LPOS.y < -1.05 || LPOS.y > 1.05) { L.el.style.display = 'none'; continue; }
    L.el.style.display = 'block';
    L.el.style.left = (rect.left + (LPOS.x * 0.5 + 0.5) * w) + 'px';
    L.el.style.top  = (rect.top + (-LPOS.y * 0.5 + 0.5) * h) + 'px';
  }
}

let bootFaded = false;
let lastT = performance.now();
let lastCloudTimeMs = null;
function animate(now) {
  requestAnimationFrame(animate);
  const dt = Math.min(0.1, (now - lastT) / 1000) || 0.016;
  lastT = now;

  if (document.hidden) return;
  paintSensorMarkers();
  smoothSatellite(dt);
  applyChaseAttitudeLock();
  trackBodyQuat();
  updateCamera();
  if (overviewView || cameraTransition) {
    if (cameraTransition) cameraTransitionElapsed += dt;
    desiredCamLogical.copy(camLogical); desiredCamQuat.copy(camera.quaternion);
    if (overviewView) {
      overviewRadial.copy(satLogical).normalize();
      overviewTangent.set(0, 0, 1).cross(overviewRadial).normalize();
      if (overviewTangent.lengthSq() < .01) overviewTangent.set(1, 0, 0);
      overviewCamLogical.copy(overviewRadial).applyAxisAngle(Z_AXIS,overviewAzimuth);
      overviewTangent.set(0,0,1).cross(overviewCamLogical);
      if (overviewTangent.lengthSq() < .0001) overviewTangent.set(1,0,0);
      overviewTangent.normalize();
      overviewCamLogical.applyAxisAngle(overviewTangent,overviewElevation);
      overviewUp.copy(overviewCamLogical).cross(overviewTangent).normalize();
      overviewCamLogical.multiplyScalar(overviewDistance).addScaledVector(overviewTangent,2.6e6);
      camera.position.copy(overviewCamLogical); camera.up.copy(overviewUp); camera.lookAt(ZERO);
      desiredCamLogical.copy(overviewCamLogical); desiredCamQuat.copy(camera.quaternion);
    }
    const t = Math.min(1,cameraTransitionElapsed / 0.7);
    const easing = t*t*(3-2*t);
    if (cameraTransition) {
      displayCamLogical.copy(transitionStartPos).lerp(desiredCamLogical,easing);
      displayCamQuat.copy(transitionStartQuat).slerp(desiredCamQuat,easing);
    } else {
      displayCamLogical.copy(desiredCamLogical);
      displayCamQuat.copy(desiredCamQuat);
    }
    camLogical.copy(displayCamLogical); camera.quaternion.copy(displayCamQuat); camera.position.set(0, 0, 0);
    if (cameraTransition && t >= 1) {
      camLogical.copy(desiredCamLogical); camera.quaternion.copy(desiredCamQuat);
      cameraTransition = false;
      lastCameraTransitionEndMs = now;
    }
  }
  baseMat.uniforms.cityVisibility.value = overviewView ? 1 : 0;
  if (!skyAligned && telemetryPrimed && (!overviewView || cameraTransitionElapsed > 1.1)) {
    hazeSphere.quaternion.copy(camera.quaternion).multiply(
      new THREE.Quaternion().setFromEuler(new THREE.Euler(0.33, 0, 0)));
    skyAligned = true;
  }
  tickFPS(dt);

  if (streamDue) {
    streamDue = false;
    if (SETTINGS.streamOn && document.visibilityState === 'visible') doStreamCapture();
  }

  placeWorld(camLogical);
  // The physically sized model is sub-pixel from overview range; enlarge
  // only its display mesh so the same live spacecraft remains identifiable.
  modelHolder.scale.setScalar(overviewView || cameraTransition
    ? clamp(camLogical.distanceTo(satLogical) * .012, 1, 180000) : 1);

  const camAlt = camLogical.length() - EARTH_R_MEAN;
  const atmoF = sstep(85000, 150000, camAlt);
  atmoMesh.visible = atmoF > 0.01;
  atmoMat.uniforms.uFade.value = atmoF;
  const cloudTarget = (cloudsReady && SETTINGS.cloudsOn) ? sstep(100000, 160000, camAlt) * SETTINGS.clouds * .68 : 0;
  cloudsMat.opacity += (cloudTarget - cloudsMat.opacity) * Math.min(1, dt * 3);
  cloudsMesh.visible = cloudsMat.opacity > 0.01;
  upperCloudsMat.opacity = cloudsMat.opacity * .38;
  upperCloudsMesh.visible = upperCloudsMat.opacity > .01;
  if (simulationTimeMs !== null) {
    if (lastCloudTimeMs !== null) {
      const weatherDt = clamp((simulationTimeMs-lastCloudTimeMs)/1000,0,10);
      cloudsMesh.rotation.z += weatherDt * 0.0000038;
      upperCloudsMesh.rotation.z += weatherDt * 0.000008;
    }
    lastCloudTimeMs = simulationTimeMs;
  }

  updateLines();
  updateTileFades(now, dt);
  // Avoid a burst of ray tests, tile creation, and image uploads mid-flight.
  if (!cameraTransition && now - lastCameraTransitionEndMs > 400 && now - lastTileUpdate > 250) { lastTileUpdate = now; updateTiles(now); }
  if (camAlt >= 2.0e6) for (const t of tiles.values()) t.mesh.visible = false;
  updateLabels();
  updateClock();
  updateFeedMeter(now);

  renderer.render(scene, camera);

  if (!bootFaded) {
    bootFaded = true;
    const b = $('boot');
    if (b) { b.style.opacity = '0'; setTimeout(() => b.remove(), 600); }
  }
}
/* =====================================================================
   Fullscreen is MANUAL ONLY (button in the top-left bar).
   Rationale 2026-09-18: browsers block programmatic fullscreen before ANY
   user click, and this page's heavy first paint (3D scene + tile fetch)
   means an auto-request fired at load either fails silently or pops late
   over the operator's click -- both looked like "weird UI". A user click
   on ⛶ always works, so auto-request on load + gesture-retry were removed.
   ===================================================================== */
function enterFullscreen() {
  if (document.fullscreenElement) return;
  try {
    const p = document.documentElement.requestFullscreen({ navigationUI: 'hide' });
    if (p && typeof p.catch === 'function') p.catch(() => { /* denied; button retry */ });
  } catch (e) { /* ignored */ }
}
/* Manual-only toggle (see note above). */
$("fullscreen-toggle").addEventListener('click', () => {
  if (document.fullscreenElement) {
    const p = document.exitFullscreen();
    if (p && typeof p.catch === 'function') p.catch(() => {});
  } else enterFullscreen();
});

requestAnimationFrame(animate);
