/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { createImageryTiles } from './imagery/ImageryTiles.js';
import { createSensorMarkers } from './spacecraft/SensorMarkers.js';
import { createSpacecraftLoader } from './spacecraft/SpacecraftLoader.js';
import { createEarthScene } from './earth/EarthScene.js';
import { createSpaceBackground } from './cosmos/SpaceBackground.js';
import * as THREE from 'three';
import { TEXTURES } from '../assets/assetUrls.js';
import { CosmicExplorer } from './cosmos/CosmicExplorer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { createViewerConfig } from './config.js';
import { DEG, clamp, sstep, WGS84_A, WGS84_E2, EARTH_R_MEAN, EARTH_CIRC, latLonToECEF, interpolateOrbitalPosition, tile2lat, lat2tileY, raySphereHit, wrap180, parseUTCDate } from './coordinates.js';
import { TelemetryFeed } from '../services/TelemetryFeed.js';
import { reportLoading } from '../services/loadingProgress.js';
import { createLifecycle } from '../services/lifecycle.js';
export async function startSimulationEngine(configuration) {
  const lifecycle = createLifecycle();
  const {
    setInterval,
    setTimeout,
    requestAnimationFrame,
    listen,
    fetch
  } = lifecycle;

  /* Optional decoders — loaded defensively in case the GLB needs them */
  let DRACOLoader, KTX2Loader, MeshoptDecoder;
  try {
    DRACOLoader = (await import('three/addons/loaders/DRACOLoader.js')).DRACOLoader;
  } catch (e) {}
  try {
    KTX2Loader = (await import('three/addons/loaders/KTX2Loader.js')).KTX2Loader;
  } catch (e) {}
  try {
    MeshoptDecoder = (await import('three/addons/libs/meshopt_decoder.module.js')).MeshoptDecoder;
  } catch (e) {}

  /* =====================================================================
     CONFIG — everything tweakable for coders. End-users: ⚙ Settings panel.
     ===================================================================== */
  const CONFIG = createViewerConfig(configuration);
  reportLoading(20, 'Loading spacecraft and Earth imagery');
  /* Esri World Imagery (satellite). For OSM map style use:
     (z,x,y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`  (note x/y order!) */
  const TILE_URL = (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
  const TEX_DAY = TEXTURES.day;
  const TEX_WATER = TEXTURES.water;
  const TEX_MOON = TEXTURES.moon;
  const TEX_CLOUDS_HIGH = TEXTURES.cloudsHigh;
  const TEX_CLOUDS_2K = TEXTURES.cloudsLow;
  const MODEL_EXTRA_ROTATION = new THREE.Euler(0, 0, 0);

  /* =====================================================================
     User settings (live, persisted) — bound to the ⚙ panel
     ===================================================================== */
  const SETTINGS = {
    preset: 'ultra',
    fps: true,
    simFeed: true,
    attLock: false,
    chaseSens: 1.0,
    exposure: 1.8,
    night: 2.5,
    city: 1.0,
    atmo: 1.6,
    cloudsOn: true,
    clouds: 0.15,
    stars: 0.75,
    sunSize: 3.0,
    moonSize: 3.0,
    modelSun: 2.0,
    modelEnv: 0.65,
    sharp: 170,
    smoothAttitude: true,
    showSun: true,
    showGyro: true,
    showMag: true,
    sensorGlow: true,
    streamOn: false,
    streamQ: 0.4,
    streamW: 640,
    streamH: 480
  };
  try {
    const s = JSON.parse(localStorage.getItem('sat3d-settings-v2'));
    if (s) Object.assign(SETTINGS, s);
  } catch (e) {}
  if (!SETTINGS.defaultsRevision3) {
    // Superseded by defaultsRevision4 below; mark done without overwriting.
    SETTINGS.defaultsRevision3 = 1;
  }
  if (!SETTINGS.smoothingRevision) {
    SETTINGS.smoothAttitude = true;
    SETTINGS.smoothingRevision = 1;
  }
  // The former default cloud density hid the high-resolution surface imagery.
  if (!SETTINGS.cloudClarityRevision) {
    SETTINGS.cloudClarityRevision = 1;
  }
  if (!SETTINGS.cloudClarityRevision2) {
    SETTINGS.cloudClarityRevision2 = 1;
  }
  if (!SETTINGS.defaultsRevision4) {
    // Screenshot-approved first-run defaults (fresh installs + one-time
    // migration for existing users; later user tweaks persist via saveSettings).
    Object.assign(SETTINGS, {
      preset: 'ultra',
      fps: true,
      simFeed: true,
      attLock: false,
      chaseSens: 1.0,
      exposure: 1.8,
      night: 2.5,
      city: 1.0,
      atmo: 1.6,
      cloudsOn: true,
      clouds: 0.15,
      stars: 0.75,
      sunSize: 3.0,
      moonSize: 3.0,
      modelSun: 2.0,
      modelEnv: 0.65,
      sharp: 170,
      smoothAttitude: true,
      showSun: true,
      showGyro: true,
      showMag: true,
      sensorGlow: true,
      streamOn: false,
      streamQ: 0.4,
      streamW: 640,
      streamH: 480,
      defaultsRevision4: 1
    });
    saveSettings();
  }
  for (const key of ['showSun', 'showGyro', 'showMag', 'sensorGlow', 'smoothAttitude']) {
    if (SETTINGS[key] === undefined) SETTINGS[key] = true;
    document.getElementById('set-' + key).checked = SETTINGS[key];
    listen(document.getElementById('set-' + key), 'change', e => {
      SETTINGS[key] = e.target.checked;
      saveSettings();
    });
  }
  function saveSettings() {
    try {
      localStorage.setItem('sat3d-settings-v2', JSON.stringify(SETTINGS));
    } catch (e) {}
  }

  /* =====================================================================
     Constants / helpers
     ===================================================================== */
  const FOV = CONFIG.FOV_DEG * DEG;
  const $ = id => document.getElementById(id);
  const updateInterval = 250;
  /* =====================================================================
     Renderer / scene / cameras
     ===================================================================== */
  const container = $('threeContainer');
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    powerPreference: 'high-performance',
    logarithmicDepthBuffer: true
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
  } catch (e) {
    console.warn('Environment map unavailable:', e);
  }
  const texLoader = new THREE.TextureLoader();
  let earthImageryReady = false;
  function solidTex(r, g, b) {
    const c = document.createElement('canvas');
    c.width = c.height = 1;
    const x = c.getContext('2d');
    x.fillStyle = `rgb(${r},${g},${b})`;
    x.fillRect(0, 0, 1, 1);
    return new THREE.CanvasTexture(c);
  }
  function loadTex(url, srgb, onOK, onErr) {
    texLoader.load(url, t => {
      if (srgb) t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = MAX_ANISO;
      onOK(t);
      if (/earth[_-]day/.test(url)) { earthImageryReady = true; reportLoading(55, 'Earth imagery ready'); }
    }, undefined, () => {
      if (onErr) onErr();
    });
  }

  /* =====================================================================
     EARTH — imagery colors shown directly (Cesium-like), no tonemap
     ===================================================================== */
  const {
    moonlightBase,
    moonTintVec,
    buildEllipsoidGeometry,
    COLOR_FIX_GLSL,
    NIGHT_SURFACE_GLSL,
    baseMat,
    earthMesh,
    auroraMesh,
    atmoMat,
    atmoMesh,
    cloudsMat,
    cloudsMesh,
    upperCloudsMat,
    upperCloudsMesh,
    textureTier,
    textureGeneration,
    applyTextureQuality,
    getCloudsReady
  } = createEarthScene({
    CONFIG,
    DEG,
    EARTH_R_MEAN,
    TEX_CLOUDS_2K,
    TEX_CLOUDS_HIGH,
    TEX_DAY,
    TEX_WATER,
    WGS84_A,
    WGS84_E2,
    configuration,
    getHazeMaterial: () => hazeMat,
    loadTex,
    renderer,
    scene,
    solidTex,
    sunDirVec
  });
  /* =====================================================================
       STARS — round soft sprites + magnitude distribution + milky-way band
       ===================================================================== */
  let skyAligned = false;
  const {
    starAnchors,
    starMats,
    makeStarTexture,
    starTex,
    STAR_BAND_N,
    makeStarLayer,
    hazeMat,
    hazeSphere
  } = createSpaceBackground({
    CONFIG,
    scene
  });
  /* =====================================================================
       SUN + MOON (anchored "at infinity" along telemetry directions)
       ===================================================================== */
  const sunLogical = new THREE.Vector3();
  let sunSprite;
  {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0.00, 'rgba(255,255,255,1)');
    grad.addColorStop(0.06, 'rgba(255,252,240,0.98)');
    grad.addColorStop(0.16, 'rgba(255,244,214,0.75)');
    grad.addColorStop(0.32, 'rgba(255,232,180,0.30)');
    grad.addColorStop(0.60, 'rgba(255,215,140,0.10)');
    grad.addColorStop(1.00, 'rgba(255,200,120,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 128, 128);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    sunSprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: t,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false
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
  const moonMesh = new THREE.Mesh(new THREE.SphereGeometry(CONFIG.MOON_RADIUS, 48, 32), new THREE.MeshLambertMaterial({
    color: 0xbfbfbf
  }));
  moonMesh.visible = false;
  scene.add(moonMesh);
  loadTex(TEX_MOON, true, t => {
    moonMesh.material.map = t;
    moonMesh.material.needsUpdate = true;
  });

  /* =====================================================================
     SATELLITE — same frame chain as the Cesium version
     ===================================================================== */
  const satLogical = latLonToECEF(0, 0, 500000);
  const satLogicalTarget = satLogical.clone();
  const satQuatTarget = new THREE.Quaternion();
  let hasBodyQuat = false,
    quatPrimed = false,
    telemetryPrimed = false;
  const satGroup = new THREE.Group();
  scene.add(satGroup);
  const modelHolder = new THREE.Group();
  modelHolder.quaternion.identity(); // Imported STEP and physics share CAD axes.
  if (MODEL_EXTRA_ROTATION.x || MODEL_EXTRA_ROTATION.y || MODEL_EXTRA_ROTATION.z) {
    modelHolder.quaternion.multiply(new THREE.Quaternion().setFromEuler(MODEL_EXTRA_ROTATION));
  }
  satGroup.add(modelHolder);
  const {
    sensorMarkers,
    updateSensorMarkers,
    paintSensorMarkers
  } = createSensorMarkers({
    CONFIG,
    SETTINGS,
    modelHolder,
    satGroup
  });
  const {
    modelMats,
    loadSpacecraftModel,
    disposeModelLoader
  } = createSpacecraftLoader({
    CONFIG,
    DRACOLoader,
    KTX2Loader,
    MeshoptDecoder,
    applySettings,
    modelHolder,
    renderer
  });
  /* =====================================================================
       Simple 1px lines + HTML labels
       ===================================================================== */
  const ZERO = new THREE.Vector3();
  const SCRATCH = new THREE.Vector3();
  class DirLine {
    constructor(colorHex) {
      this.geo = new THREE.BufferGeometry();
      this.geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
      this.mat = new THREE.LineBasicMaterial({
        color: colorHex,
        toneMapped: false
      });
      this.line = new THREE.Line(this.geo, this.mat);
      this.line.frustumCulled = false;
      this.line.visible = false;
    }
    setEndpoints(a, b) {
      const p = this.geo.attributes.position.array;
      p[0] = a.x;
      p[1] = a.y;
      p[2] = a.z;
      p[3] = b.x;
      p[4] = b.y;
      p[5] = b.z;
      this.geo.attributes.position.needsUpdate = true;
    }
  }
  const labelsRoot = $('labels');
  const labels = [];
  function addLabel(text, cssColor, getPos, isVisible) {
    const el = document.createElement('div');
    el.className = 'glabel';
    el.textContent = text;
    el.style.color = cssColor;
    el.style.display = 'none';
    labelsRoot.appendChild(el);
    labels.push({
      el,
      getPos,
      isVisible
    });
    return labels[labels.length - 1];
  }
  const homeLocation = latLonToECEF(17.4355, 78.4579, 150);
  const homeNormal = homeLocation.clone().normalize();
  const homeView = new THREE.Vector3();
  addLabel('We are here \u00b7 Begumpet, Hyderabad', '#a9e9ff', out => out.copy(homeLocation), () => homeView.copy(camLogical).sub(homeLocation).dot(homeNormal) > 0 && camLogical.distanceTo(homeLocation) < 2.0e7);
  const satelliteNameLabel = addLabel('Spacecraft', '#9fe5ff', out => out.copy(satLogical), () => overviewView);
  const bodyDirPos = (dir, len) => out => out.copy(dir).multiplyScalar(len).applyQuaternion(satGroup.quaternion).add(satLogical);
  const worldDirPos = (dirGetter, len) => out => {
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
  let moonDirEcef = null,
    nadirDirEcef = null,
    sweepDirEcef = null;
  const sunLine = new DirLine(0xffd400);
  scene.add(sunLine.line);
  const moonLine = new DirLine(0x00e5ff);
  scene.add(moonLine.line);
  const nadirLine = new DirLine(0xffffff);
  scene.add(nadirLine.line);
  const sweepLine = new DirLine(0xff77ff);
  scene.add(sweepLine.line);
  const PN_LOCAL = new THREE.Vector3(0, 0, -1);
  const MPN_LOCAL = new THREE.Vector3(0, -1, 0);
  const panelNormalLine = new DirLine(0xff8c1a);
  panelNormalLine.setEndpoints(ZERO, SCRATCH.copy(PN_LOCAL).multiplyScalar(CONFIG.DIRLINE_LEN * 0.8));
  satGroup.add(panelNormalLine.line);
  const moonPanelLine = new DirLine(0xff8c1a);
  moonPanelLine.setEndpoints(ZERO, SCRATCH.copy(MPN_LOCAL).multiplyScalar(CONFIG.DIRLINE_LEN * 0.8));
  satGroup.add(moonPanelLine.line);
  addLabel('To Sun', '#ffd400', worldDirPos(() => sunDirEcef, CONFIG.DIRLINE_LEN), () => sunLine.line.visible);
  addLabel('Panel Normal (-Z)', '#ff8c1a', bodyDirPos(PN_LOCAL, CONFIG.DIRLINE_LEN * 0.8), () => panelNormalLine.line.visible);
  addLabel('To Moon', '#00e5ff', worldDirPos(() => moonDirEcef, CONFIG.DIRLINE_LEN), () => moonLine.line.visible);
  addLabel('Moon Panel Normal(-Y)', '#ff8c1a', bodyDirPos(MPN_LOCAL, CONFIG.DIRLINE_LEN * 0.8), () => moonPanelLine.line.visible);
  addLabel('To Nadir', '#ffffff', worldDirPos(() => nadirDirEcef, CONFIG.DIRLINE_LEN), () => nadirLine.line.visible);
  addLabel('Sun Sweep', '#ff77ff', worldDirPos(() => sweepDirEcef, CONFIG.DIRLINE_LEN), () => sweepLine.line.visible);

  /* =====================================================================
     Camera-relative placement (floating origin)
     ===================================================================== */
  const ORIGIN_LOGICAL = new THREE.Vector3(0, 0, 0);
  const statics = [];
  function trackOrigin(obj, posVec) {
    statics.push({
      obj,
      pos: posVec
    });
  }
  trackOrigin(earthMesh, ORIGIN_LOGICAL);
  trackOrigin(auroraMesh, ORIGIN_LOGICAL);
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
  const orbitPath = new THREE.Line(orbitGeometry, new THREE.LineBasicMaterial({
    color: 0x66ccff
  }));
  orbitPath.visible = false;
  orbitPath.name = 'osculating-orbit';
  scene.add(orbitPath);
  trackOrigin(orbitPath, ORIGIN_LOGICAL);
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
  let lastTileUpdate = 0;
  const {
    tiles,
    updateTiles,
    updateTileFades,
    disposeTile
  } = createImageryTiles({
    COLOR_FIX_GLSL,
    CONFIG,
    DEG,
    EARTH_CIRC,
    EARTH_R_MEAN,
    FOV,
    MAX_ANISO,
    NIGHT_SURFACE_GLSL,
    SETTINGS,
    TILE_URL,
    WGS84_A,
    WGS84_E2,
    baseMat,
    camera,
    clamp,
    computePayloadPose,
    configuration,
    getCamLogical: () => camLogical,
    getCameraMode: () => cameraMode,
    getVideoSocket: () => videoSocket,
    lat2tileY,
    latLonToECEF,
    moonTintVec,
    payloadCamera,
    raySphereHit,
    renderer,
    scene,
    sunDirVec,
    texLoader,
    tile2lat,
    wrap180
  });
  /* =====================================================================
       Camera modes — free / chase / payload (inertially-stabilized chase)
       ===================================================================== */
  let cameraMode = 'chase';
  const camLogical = new THREE.Vector3();
  window.missionCameraState = () => ({
    distanceFromEarthM: camLogical.length(),
    distanceFromSatelliteM: camLogical.distanceTo(satLogical),
    overview: overviewView,
    transitioning: cameraTransition,
    chaseDistanceM: chaseOffsetWorld.length()
  });
  const freePos = new THREE.Vector3(),
    freeQuat = new THREE.Quaternion();
  const chaseOffsetWorld = new THREE.Vector3(...CONFIG.CHASE_VIEW_FROM);
  const chaseQuatWorld = new THREE.Quaternion();
  let lastBodyQuat = null;
  let nightViewBrightness = 1;
  let overviewView = false,
    cameraTransition = false,
    cameraTransitionElapsed = 0;
  let overviewDistance = 2.1e7,
    overviewAzimuth = 0,
    overviewElevation = 0;
  const cosmicExplorer = new CosmicExplorer(renderer);
  cosmicExplorer.nativeAssets = {
    earth: earthMesh,
    atmosphere: atmoMesh,
    clouds: [cloudsMesh, upperCloudsMesh],
    sky: hazeSphere,
    stars: starAnchors,
    orbit: orbitPath,
    aurora: auroraMesh,
    sunlight: sunLight,
    sun: sunSprite,
    sunDistance: CONFIG.SUN_RENDER_DIST
  };
  scene.add(cosmicExplorer.background);
  scene.add(cosmicExplorer.departure);
  cosmicExplorer.referenceSky.scale.setScalar(1e6);
  scene.add(cosmicExplorer.referenceSky);
  const transitionStartPos = new THREE.Vector3(),
    transitionStartQuat = new THREE.Quaternion();
  const displayCamLogical = new THREE.Vector3(),
    displayCamQuat = new THREE.Quaternion();
  const flightStartOffset = new THREE.Vector3(),
    flightEndOffset = new THREE.Vector3(),
    flightDirection = new THREE.Vector3();
  const flightRotation = new THREE.Quaternion(),
    flightStep = new THREE.Quaternion(),
    flightEndQuat = new THREE.Quaternion();
  let flightStartRadius = 1,
    flightEndRadius = 1,
    flightTargetReady = false,
    flightScaleStart = 1,
    flightScaleEnd = 1,
    flightDisplayScale = 1;
  const desiredCamLogical = new THREE.Vector3(),
    desiredCamQuat = new THREE.Quaternion();
  const overviewCamLogical = new THREE.Vector3(),
    overviewRadial = new THREE.Vector3(),
    overviewTangent = new THREE.Vector3(),
    overviewUp = new THREE.Vector3();
  const Z_AXIS = new THREE.Vector3(0, 0, 1);
  let lastCameraTransitionEndMs = -Infinity;
  listen(window, 'dashboard-tab', e => {
    const next = e.detail === 'overview';
    if (overviewView !== next) {
      if (!next && overviewDistance > 8e7) {
        camLogical.normalize().multiplyScalar(2.1e7);
        overviewDistance = 2.1e7;
      }
      if (next && cosmicExplorer.distance > 8e7) cosmicExplorer.setDistance(overviewDistance);
      transitionStartPos.copy(camLogical);
      transitionStartQuat.copy(camera.quaternion);
      flightStartOffset.copy(camLogical).sub(satLogical);
      flightStartRadius = Math.max(.1, flightStartOffset.length());
      flightStartOffset.divideScalar(flightStartRadius);
      flightTargetReady = false;
      flightScaleStart = Math.max(1, modelHolder.scale.x);
      if (!next) {
        const destinationCamera = camera.clone();
        const destination = new THREE.Vector3();
        if (cameraMode === 'payload') computePayloadPose(destination, destinationCamera);
        else { destination.copy(satLogical).add(chaseOffsetWorld); destinationCamera.quaternion.copy(chaseQuatWorld); }
        updateTiles(performance.now(), destination, destinationCamera);
      }
      overviewView = next;
      cameraTransition = true;
      cameraTransitionElapsed = 0;
    }
  });
  // dashboard.js may dispatch its initial tab before this module has loaded.
  overviewView = document.querySelector('.mission-dashboard')?.dataset.tab === 'overview';
  cameraTransition = false;
  transitionStartPos.copy(camLogical);
  transitionStartQuat.copy(camera.quaternion);
  const DQ = new THREE.Quaternion(),
    QINV2 = new THREE.Quaternion();
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
  const TMPA = new THREE.Vector3(),
    TMPB = new THREE.Vector3(),
    TMPC = new THREE.Vector3();
  function computePayloadPose(outLogical, outCam) {
    const q = satGroup.quaternion;
    TMPA.set(CONFIG.PAYLOAD_OFFSET[0], CONFIG.PAYLOAD_OFFSET[1], CONFIG.PAYLOAD_OFFSET[2]).applyQuaternion(q);
    outLogical.copy(satLogical).add(TMPA);
    TMPB.fromArray(CONFIG.PAYLOAD_BORESIGHT).applyQuaternion(q);
    TMPC.fromArray(CONFIG.PAYLOAD_UP).applyQuaternion(q);
    outCam.position.set(0, 0, 0);
    outCam.up.copy(TMPC);
    outCam.lookAt(TMPB);
  }
  function computeFixedPose(outLogical, outCam) {
    latLonToECEF(13, 77, 10000000, outLogical);
    const lat = 13 * DEG,
      lon = 77 * DEG;
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
    let dragging = false,
      dragBtn = 0,
      lastX = 0,
      lastY = 0;
    const RLOC = new THREE.Quaternion(),
      M = new THREE.Quaternion(),
      QINV = new THREE.Quaternion();
    const ROTQ = new THREE.Quaternion(),
      EUL = new THREE.Euler();
    listen(el, 'contextmenu', e => e.preventDefault());
    listen(el, 'pointerdown', e => {
      if (overviewView && cosmicExplorer.referenceTime >= 95) return;
      if (cameraMode === 'payload' && !overviewView) return;
      dragging = true;
      dragBtn = e.button;
      lastX = e.clientX;
      lastY = e.clientY;
      try {
        el.setPointerCapture(e.pointerId);
      } catch (err) {}
      e.preventDefault();
    });
    listen(el, 'pointermove', e => {
      if (!dragging) return;
      const dx = e.clientX - lastX,
        dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      if (overviewView) {
        if (cosmicExplorer.referenceTime >= 95) return;
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
        const tilt = dragBtn === 2 || dragBtn === 1 || e.ctrlKey || e.metaKey;
        if (!tilt) chaseOffsetWorld.applyQuaternion(M);
        chaseQuatWorld.premultiply(M).normalize();
      } else if (cameraMode === 'free') {
        freeQuat.multiply(ROTQ.setFromEuler(EUL.set(-dy * 0.0022, -dx * 0.0022, 0, 'YXZ')));
      }
    });
    listen(window, 'pointerup', () => {
      dragging = false;
    });
    listen(el, 'wheel', e => {
      e.preventDefault();
      if (overviewView) {
        cosmicExplorer.zoom(e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? window.innerHeight : 1));
        return;
      }
      if (cameraMode === 'chase') {
        const len = chaseOffsetWorld.length();
        if (len > 1e-9) {
          const nl = clamp(len * Math.exp(e.deltaY * CONFIG.CHASE_ZOOM_SENS), CONFIG.CHASE_MIN_DIST, CONFIG.CHASE_MAX_DIST);
          chaseOffsetWorld.multiplyScalar(nl / len);
        }
      } else if (cameraMode === 'free') {
        const alt = Math.max(freePos.length() - EARTH_R_MEAN, 10);
        const step = clamp(alt * 0.12, 1, 3e5) * (-e.deltaY / 100);
        freePos.addScaledVector(TMPA.set(0, 0, -1).applyQuaternion(freeQuat), step);
      }
    }, {
      passive: false
    });
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
        if (chaseOffsetWorld.length() < 1e-3) resetChaseView();else chaseQuatWorld.copy(camera.quaternion);
      } else {
        resetChaseView();
      }
    }
    cameraMode = m;
  }
  listen($('cameraSelect'), 'change', e => setCameraMode(e.target.value));

  /* =====================================================================
     Telemetry — ported 1:1 from the Cesium version (+ clock sync + feed)
     ===================================================================== */
  let latestTimestamp = 0,
    latestLat = 0,
    latestLon = 0,
    latestAlt = 500000;
  let latestYaw = 0.0,
    latestPitch = 0.0,
    latestRoll = 0.0;
  let latestBRX = 0,
    latestBRY = 0,
    latestBRZ = 0;
  let latestAX = 0,
    latestAY = 0,
    latestAZ = 0;
  let latestMode = "";
  let telemetryRequestInFlight = false,
    rwTelemetryRequestInFlight = false,
    mtrTelemetryRequestInFlight = false;
  const clockTimeEl = $('clock-time');
  let simulationTimeMs = null;
  function updateClock() {
    if (window.MissionDashboard) return;
    if (CONFIG.CLOCK_SOURCE === 'telemetry' && simulationTimeMs === null) {
      clockTimeEl.textContent = 'Waiting for simulation time';
      return;
    }
    const t = new Date(CONFIG.CLOCK_SOURCE === 'telemetry' ? simulationTimeMs : Date.now());
    const p2 = n => String(n).padStart(2, '0');
    clockTimeEl.textContent = t.getUTCFullYear() + '-' + p2(t.getUTCMonth() + 1) + '-' + p2(t.getUTCDate()) + ' ' + p2(t.getUTCHours()) + ':' + p2(t.getUTCMinutes()) + ':' + p2(t.getUTCSeconds());
  }

  /* =====================================================================
     Sim feed meter — updates/s, real-time factor, estimated steps/s
     ===================================================================== */
  const feedEl = $('feed-meter');
  const FEED = new TelemetryFeed();
  function feedOnTelemetry(data) {
    FEED.processed(data);
  }
  function updateFeedMeter(now) {
    if (window.MissionDashboard) return;
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
    const f = (v, d) => v === undefined || v === null ? "--" : Number(v).toFixed(d);
    return `<div class="sens-row"><span>${m}</span><span>${t}</span>` + `<span>${e}${unit ? " " + unit : ""}</span></div>`;
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
          posErr = (Math.sqrt(dx * dx + dy * dy + dz * dz) / 1000).toFixed(3) + " km";
        }
        gps.innerHTML = `<div>fix: <span class="${data.gps_fix ? "sens-ok" : "sens-bad"}">${data.gps_fix ? "YES" : "NO"}</span>` + ` &nbsp; SVs: ${data.gps_num_sv ?? "--"} &nbsp; PDOP: ${data.gps_pdop?.toFixed(2) ?? "--"}</div>` + `<div>acc h/v: ${data.gps_h_acc_m?.toFixed(2) ?? "--"} / ${data.gps_v_acc_m?.toFixed(2) ?? "--"} m` + ` &nbsp; latency: ${data.gps_latency_s != null ? (data.gps_latency_s * 1000).toFixed(0) + " ms" : "--"}</div>` + `<div>fix pos: lat ${data.gps_lat_deg?.toFixed(4) ?? "--"}°, lon ${data.gps_lon_deg?.toFixed(4) ?? "--"}°, alt ${data.gps_alt_m?.toFixed(0) ?? "--"} m</div>` + `<div>belief-vs-truth position error: <b>${posErr}</b></div>`;
      } else gps.textContent = "-- (GPS off)";
    }
    // ---- Gyroscope ----
    const gyro = $("sen-gyro-body");
    if (gyro) {
      if (data.imu_gyro_x_rad_s !== undefined && data.imu_gyro_x_rad_s !== null) {
        const dg = r => r * 180 / Math.PI;
        gyro.innerHTML = _sensRow(dg(data.imu_gyro_x_rad_s).toFixed(4), data.body_rate_x?.toFixed(4) ?? "--", (dg(data.imu_gyro_x_rad_s) - (data.body_rate_x ?? 0)).toFixed(4)) + _sensRow(dg(data.imu_gyro_y_rad_s).toFixed(4), data.body_rate_y?.toFixed(4) ?? "--", (dg(data.imu_gyro_y_rad_s) - (data.body_rate_y ?? 0)).toFixed(4)) + _sensRow(dg(data.imu_gyro_z_rad_s).toFixed(4), data.body_rate_z?.toFixed(4) ?? "--", (dg(data.imu_gyro_z_rad_s) - (data.body_rate_z ?? 0)).toFixed(4));
        const gf = $("sen-gyro-flags");
        if (gf) gf.innerHTML = `valid: <span class="${data.imu_gyro_valid ? "sens-ok" : "sens-bad"}">${data.imu_gyro_valid}</span>` + ` &nbsp; saturated: ${data.imu_gyro_saturated ? "<span class='sens-warn'>YES</span>" : "no"}`;
      } else {
        gyro.innerHTML = "-- (IMU off)";
        const gf = $("sen-gyro-flags");
        if (gf) gf.textContent = "";
      }
    }
    // ---- Magnetometer ----
    const mag = $("sen-mag-body");
    if (mag) {
      if (data.imu_mag_x_nT !== undefined && data.imu_mag_x_nT !== null) {
        mag.innerHTML = _sensRow(data.imu_mag_x_nT.toFixed(1), data.truth_mag_body_x_nT?.toFixed(1) ?? "--", (data.imu_mag_x_nT - (data.truth_mag_body_x_nT ?? 0)).toFixed(1)) + _sensRow(data.imu_mag_y_nT.toFixed(1), data.truth_mag_body_y_nT?.toFixed(1) ?? "--", (data.imu_mag_y_nT - (data.truth_mag_body_y_nT ?? 0)).toFixed(1)) + _sensRow(data.imu_mag_z_nT.toFixed(1), data.truth_mag_body_z_nT?.toFixed(1) ?? "--", (data.imu_mag_z_nT - (data.truth_mag_body_z_nT ?? 0)).toFixed(1));
        const mf = $("sen-mag-flags");
        if (mf) mf.innerHTML = `valid: <span class="${data.imu_mag_valid ? "sens-ok" : "sens-bad"}">${data.imu_mag_valid}</span>` + ` &nbsp; saturated: ${data.imu_mag_saturated ? "<span class='sens-warn'>YES</span>" : "no"}`;
      } else {
        mag.innerHTML = "-- (IMU off)";
        const mf = $("sen-mag-flags");
        if (mf) mf.textContent = "";
      }
    }
    // ---- Sun sensor array ----
    const sunStatus = $("sen-sun-status");
    if (sunStatus) {
      if (data.sun_arr_valid !== undefined && data.sun_arr_valid !== null && data.sun_arr_cells) {
        const ec = data.sun_arr_eclipse_factor;
        sunStatus.innerHTML = `receipt valid: <span class="${data.sun_arr_valid ? "sens-ok" : "sens-bad"}">${data.sun_arr_valid}</span>` + ` &nbsp; cells used: ${data.sun_arr_cells_used ?? "--"}/${data.sun_arr_cells_total ?? "--"}` + ` &nbsp; eclipse F: ${ec != null ? ec.toFixed(2) : "--"}` + ` &nbsp; method: ${data.sun_arr_method ?? "--"}`;
        const tbl = $("sen-sun-cells");
        if (tbl) {
          let rows = "<tr><th>cell</th><th>out %</th><th>ADC</th><th>cone°</th><th>status</th></tr>";
          for (const c of data.sun_arr_cells) {
            const st = c.shadowed ? "<span class=sens-bad>SHADOW</span>" : !c.in_fov ? "out-FOV" : c.eclipse_factor < 1 ? "<span class=sens-warn>ECLIPSE</span>" : c.used ? "<span class=sens-ok>used</span>" : "in-FOV";
            rows += `<tr><td>${c.name}</td><td>${c.output_pct.toFixed(1)}</td>` + `<td>${c.adc_counts}</td><td>${c.angle_deg != null ? c.angle_deg.toFixed(1) : "--"}</td>` + `<td>${st}</td></tr>`;
          }
          tbl.innerHTML = rows;
        }
        const recon = $("sen-sun-recon");
        if (recon) {
          if (data.sun_arr_recon_valid) {
            const v = [data.sun_arr_recon_x, data.sun_arr_recon_y, data.sun_arr_recon_z];
            const w = [data.sun_arr_truth_x, data.sun_arr_truth_y, data.sun_arr_truth_z];
            recon.innerHTML = `recon: [${v.map(x => x.toFixed(3)).join(", ")}] vs truth: ` + `[${w.map(x => x.toFixed(3)).join(", ")}] -- error ` + `<span class="${data.sun_arr_error_deg < 2 ? "sens-ok" : "sens-warn"}">` + `${data.sun_arr_error_deg?.toFixed(3)}°</span>`;
          } else recon.innerHTML = "reconstruction FAILED (eclipse/geometry) -- coasting on gyro+mag";
        }
      } else {
        sunStatus.textContent = "-- (IMU off)";
        const tbl = $("sen-sun-cells");
        if (tbl) tbl.innerHTML = "";
        const recon = $("sen-sun-recon");
        if (recon) recon.textContent = "";
      }
    }
    // ---- Attitude estimator ----
    const est = $("sen-est");
    if (est) {
      if (data.att_est_quat_w !== undefined && data.att_est_quat_w !== null) {
        const q = [data.att_est_quat_x, data.att_est_quat_y, data.att_est_quat_z, data.att_est_quat_w];
        const qt = [data.truth_att_quat_x, data.truth_att_quat_y, data.truth_att_quat_z, data.truth_att_quat_w];
        est.innerHTML = `<div>belief quat: [${q.map(x => x.toFixed(4)).join(", ")}]</div>` + `<div>truth quat: [${qt.map(x => x == null ? "--" : x.toFixed(4)).join(", ")}]</div>` + `<div>estimation error: <span class="${data.att_est_error_deg < 2 ? "sens-ok" : data.att_est_error_deg < 15 ? "sens-warn" : "sens-bad"}">` + `${data.att_est_error_deg?.toFixed(3)}°</span>` + ` &nbsp; corrections: ${data.att_est_corrections ?? "--"}` + ` &nbsp; propagations: ${data.att_est_propagations ?? "--"}</div>` + `<div>sun correction in use: <span class="${data.att_est_sun_used ? "sens-ok" : "sens-warn"}">` + `${data.att_est_sun_used ? "YES" : "NO (coasting)"}</span></div>`;
      } else est.textContent = "-- (IMU off)";
    }
  }
  let bundledActuators = false;
  let telemetryETag = null;
  let lastTelemetryFetch = -Infinity;
  listen(window, 'telemetry-visibility', event => { if (event.detail) { lastTelemetryFetch = -Infinity; fetchTelemetry(); } });
  function fetchTelemetry() {
    const clearView = document.body.classList.contains('mission-clear-active');
    const now = performance.now();
    if (clearView && now - lastTelemetryFetch < 1000) return;
    if (telemetryRequestInFlight) return;
    telemetryRequestInFlight = true;
    lastTelemetryFetch = now;
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    fetch('/api/latest', {
      cache: 'no-store',
      headers: telemetryETag ? {
        'If-None-Match': telemetryETag
      } : {},
      signal: AbortSignal.timeout(3000)
    }).then(response => {
      if (response.status === 304) return null;
      telemetryETag = response.headers.get('ETag');
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      return response.json();
    }).then(data => {
      if (data && data.latitude_deg !== undefined) {
        if (!FEED.isNew(data)) return;
        if (data.actuator_telemetry) {
          bundledActuators = true;
          fetchRWTorques(data.actuator_telemetry);
          fetchMTRTelemetry(data.actuator_telemetry);
        }
        if (typeof data.satellite_name === 'string' && data.satellite_name.trim()) satelliteNameLabel.el.textContent = data.satellite_name.trim();
        updateSensorMarkers(data);
        updateOrbitPath(data);
        latestTimestamp = data.timestamp;
        latestLat = data.latitude_deg;
        latestLon = data.longitude_deg;
        latestAlt = data.altitude_m;
        latestYaw = data.yaw_deg;
        latestPitch = data.pitch_deg;
        latestRoll = data.roll_deg;
        latestBRX = data.body_rate_x;
        latestBRY = data.body_rate_y;
        latestBRZ = data.body_rate_z;
        latestAX = data.alpha_x;
        latestAY = data.alpha_y;
        latestAZ = data.alpha_z;
        latLonToECEF(latestLat, latestLon, latestAlt, satLogicalTarget);
        if (data.quat_x !== undefined) {
          satQuatTarget.set(data.quat_x, data.quat_y, data.quat_z, data.quat_w);
          hasBodyQuat = true;
          if (!quatPrimed) {
            satGroup.quaternion.copy(satQuatTarget);
            quatPrimed = true;
          }
        }
        if (data.sun_ecef_x !== undefined) setSunDir(TMPA.set(data.sun_ecef_x, data.sun_ecef_y, data.sun_ecef_z));
        if (data.moon_position_ecef_m) moonPositionEcef = new THREE.Vector3(...data.moon_position_ecef_m);
        if (data.moon_ecef_x !== undefined) {
          moonDirEcef = new THREE.Vector3(data.moon_ecef_x, data.moon_ecef_y, data.moon_ecef_z).normalize();
          moonMesh.visible = true;
        }
        if (data.nadir_ecef_x !== undefined) nadirDirEcef = new THREE.Vector3(data.nadir_ecef_x, data.nadir_ecef_y, data.nadir_ecef_z).normalize();
        if (data.sun_sweep_ecef_x !== undefined) sweepDirEcef = new THREE.Vector3(data.sun_sweep_ecef_x, data.sun_sweep_ecef_y, data.sun_sweep_ecef_z).normalize();
        if (data.mode !== undefined) latestMode = data.mode === 'FIRMWARE_SITL' ? ({ NadirPoint: 'NADIR', Sunpoint: 'SUN_POINTING', MoonSweep: 'MOON', SunSweep: 'SUN_SWEEP', NominalInOrbit: 'NOMINAL_IN_ORBIT', KinematicRobustness: 'KINEMATIC_ROBUSTNESS' }[data.ads_mode] || 'FIRMWARE_SITL') : data.mode;
        if (CONFIG.CLOCK_SOURCE === 'telemetry') {
          const td = parseUTCDate(data.timestamp);
          if (td) simulationTimeMs = td.getTime();
          if (data.eci_to_ecef_matrix) {
            const a = data.eci_to_ecef_matrix;
            const rotation = new THREE.Matrix4().set(a[0][0], a[0][1], a[0][2], 0, a[1][0], a[1][1], a[1][2], 0, a[2][0], a[2][1], a[2][2], 0, 0, 0, 0, 1);
            for (const o of starAnchors) if (o.isPoints) o.quaternion.setFromRotationMatrix(rotation);
          }
        }
        if (!window.MissionDashboard) {
          updateSensorsPanel(data);
          /* ---- pointing-error rows (identical logic) ---- */
          if (data.sun_pointing_error_deg !== undefined) {
            const errEl = $("sun-ptg-err");
            if (errEl) {
              if (latestMode === "POINTING") {
                const err = data.sun_pointing_error_deg;
                errEl.textContent = err.toFixed(3) + "°";
                errEl.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                errEl.textContent = "-- (not in sun-pointing mode)";
                errEl.style.color = "#9aa4b2";
              }
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
            const stale = data.imu_mag_valid === false;
            for (const id of ["rw-ptg-err-own", "mtr-ptg-err-own"]) {
              const el = $(id);
              if (!el) continue;
              el.textContent = ownErr.toFixed(3) + "°" + (stale ? " (STALE)" : "");
              el.style.color = ownErr < 2 ? "#7fff7f" : ownErr < 15 ? "#ffd27f" : "#ff7f7f";
            }
          }
          if (data.moon_pointing_error_deg !== undefined) {
            const el = $("moon-ptg-err");
            if (el) {
              if (latestMode === "MOON") {
                const err = data.moon_pointing_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in moon-pointing mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }
          if (data.nadir_pointing_error_deg !== undefined) {
            const el = $("nadir-ptg-err");
            if (el) {
              if (latestMode === "NADIR") {
                const err = data.nadir_pointing_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in nadir-pointing mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }
          if (data.kinematic_robustness_error_deg !== undefined) {
            const el = $("kinrob-ptg-err");
            if (el) {
              if (latestMode === "KINEMATIC_ROBUSTNESS") {
                const err = data.kinematic_robustness_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in kinematic-robustness mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }
          if (data.nominal_in_orbit_error_deg !== undefined) {
            const el = $("nominal-ptg-err");
            if (el) {
              if (latestMode === "NOMINAL_IN_ORBIT") {
                const err = data.nominal_in_orbit_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in nominal-in-orbit mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }
          if (data.sun_pointing_rw_error_deg !== undefined) {
            const el = $("sun-ptg-rw-err");
            if (el) {
              if (latestMode === "SUN_POINTING_RW") {
                const err = data.sun_pointing_rw_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in sun-pointing-RW mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }
          if (data.sun_sweep_error_deg !== undefined) {
            const el = $("sunsweep-ptg-err");
            if (el) {
              if (latestMode === "SUN_SWEEP") {
                const err = data.sun_sweep_error_deg;
                el.textContent = err.toFixed(3) + "°";
                el.style.color = err < 2 ? "#7fff7f" : err < 15 ? "#ffd27f" : "#ff7f7f";
              } else {
                el.textContent = "-- (not in sun-sweep mode)";
                el.style.color = "#9aa4b2";
              }
            }
          }

          /* ---- telemetry box ---- */
          $("timestamp").textContent = "Timestamp: " + latestTimestamp;
          $("lat").textContent = "Lat: " + latestLat.toFixed(6) + "°";
          $("lon").textContent = "Lon: " + latestLon.toFixed(6) + "°";
          $("alt").textContent = "Alt: " + latestAlt.toFixed(1) + " m";
          $("yaw").textContent = "Yaw: " + latestYaw.toFixed(2) + "°";
          $("pitch").textContent = "Pitch: " + latestPitch.toFixed(2) + "°";
          $("roll").textContent = "Roll: " + latestRoll.toFixed(2) + "°";
          const targetFieldsByMode = {
            "POINTING": {
              prefix: "target",
              label: "sun pointing"
            },
            "NADIR": {
              prefix: "nadir_target",
              label: "nadir pointing"
            },
            "MOON": {
              prefix: "moon_target",
              label: "moon pointing"
            },
            "SUN_SWEEP": {
              prefix: "sun_sweep_target",
              label: "sun sweep"
            },
            "SUN_POINTING_RW": {
              prefix: "sun_pointing_rw_target",
              label: "sun pointing (RW)"
            },
            "NOMINAL_IN_ORBIT": {
              prefix: "nominal_in_orbit_target",
              label: "nominal in-orbit"
            },
            "KINEMATIC_ROBUSTNESS": {
              prefix: "kinematic_robustness_target",
              label: "kinematic robustness"
            }
          };
          const targetInfo = targetFieldsByMode[latestMode];
          if (targetInfo && data[targetInfo.prefix + "_yaw_deg"] !== undefined) {
            $("target_yaw").textContent = "Required Yaw (" + targetInfo.label + "): " + data[targetInfo.prefix + "_yaw_deg"].toFixed(2) + "°";
            $("target_pitch").textContent = "Required Pitch (" + targetInfo.label + "): " + data[targetInfo.prefix + "_pitch_deg"].toFixed(2) + "°";
            $("target_roll").textContent = "Required Roll (" + targetInfo.label + "): " + data[targetInfo.prefix + "_roll_deg"].toFixed(2) + "°";
          } else {
            $("target_yaw").textContent = "Required Yaw: -- (mode has no target attitude)";
            $("target_pitch").textContent = "Required Pitch: --";
            $("target_roll").textContent = "Required Roll: --";
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
        }
        if (!telemetryPrimed) {
          satLogical.copy(satLogicalTarget);
          telemetryPrimed = true;
        }
        feedOnTelemetry(data);
        window.dispatchEvent(new CustomEvent('simulation-telemetry', {
          detail: data
        }));
      } else {
        $("status").textContent = "Waiting for data... run the propagator script.";
      }
    }).catch(error => {
      if (lifecycle.disposed) return;
      console.error('Error fetching telemetry:', error);
      $("lat").textContent = "Error: See console";
    }).finally(() => {
      telemetryRequestInFlight = false;
    });
  }
  async function fetchRWTorques(snapshot) {
    if (rwTelemetryRequestInFlight) return;
    rwTelemetryRequestInFlight = true;
    try {
      const data = snapshot;
      if (!data) return;
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
  async function fetchMTRTelemetry(snapshot) {
    if (mtrTelemetryRequestInFlight) return;
    mtrTelemetryRequestInFlight = true;
    try {
      const data = snapshot;
      if (!data) return;
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
    const rwPanel = $("rw-panel"),
      mtrPanel = $("mtr-panel");
    const sliders = document.querySelector(".control-panel");
    const usesReactionWheels = mode === "CUSTOM" || mode === "RW" || mode === "MOON" || mode === "NADIR" || mode === "SUN_SWEEP" || mode === "SUN_POINTING_RW" || mode === "NOMINAL_IN_ORBIT" || mode === "KINEMATIC_ROBUSTNESS";
    if (rwPanel) rwPanel.style.display = usesReactionWheels ? "block" : "none";
    if (mtrPanel) mtrPanel.style.display = usesReactionWheels ? "none" : "block";
    if (sliders) sliders.style.display = mode === "RW" ? "flex" : "none";
    const rowVisibility = {
      "moon-ptg-err": "MOON",
      "nadir-ptg-err": "NADIR",
      "sunsweep-ptg-err": "SUN_SWEEP",
      "sun-ptg-rw-err": "SUN_POINTING_RW",
      "nominal-ptg-err": "NOMINAL_IN_ORBIT",
      "kinrob-ptg-err": "KINEMATIC_ROBUSTNESS"
    };
    for (const [id, m] of Object.entries(rowVisibility)) {
      const el = $(id);
      if (el && el.parentElement) el.parentElement.style.display = mode === m ? "flex" : "none";
    }
  }
  setInterval(() => {
    const m = latestMode;
    const sunOn = m === "POINTING" || m === "SUN_POINTING" || m === "SUN_POINTING_RW";
    sunLine.line.visible = sunOn;
    panelNormalLine.line.visible = sunOn;
    const moonOn = m === "MOON";
    moonLine.line.visible = moonOn && !!moonDirEcef;
    moonPanelLine.line.visible = moonOn;
    nadirLine.line.visible = (m === "NADIR" || m === "NOMINAL_IN_ORBIT" || m === "KINEMATIC_ROBUSTNESS") && !!nadirDirEcef;
    sweepLine.line.visible = m === "SUN_SWEEP" && !!sweepDirEcef;
  }, updateInterval);
  setInterval(fetchTelemetry, updateInterval);
  fetchTelemetry();

  /* =====================================================================
     Controls UI — same endpoints
     ===================================================================== */
  function sendData(label, value) {
    $(label + '-label').textContent = value;
    fetch('/update/control/inputs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        label: label,
        value: parseFloat(value)
      })
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
  if ($('modeSelect')) listen($('modeSelect'), 'change', async e => {
    const response = await fetch('/update/mode', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        mode: e.target.value
      })
    });
    if (!response.ok) console.error('Legacy mode command failed', await response.text());
  });
  listen($("axis-toggle"), 'click', () => {
    axesVisible = !axesVisible;
    const tickEl = $("tick");
    tickEl.textContent = axesVisible ? '✓' : '';
    tickEl.style.background = axesVisible ? '#4CAF50' : '#333';
    $("axis-toggle").classList.toggle('on', axesVisible);
    for (const a of axes) a.line.visible = axesVisible;
  });
  listen(window, 'resize', () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });
  window.scene = scene;
  window.camera = camera;
  window.renderer = renderer;
  window.satelliteGroup = satGroup;

  /* =====================================================================
     Payload video stream → ws://localhost:8765
     ===================================================================== */
  const capCanvas = document.createElement('canvas');
  capCanvas.width = SETTINGS.streamW;
  capCanvas.height = SETTINGS.streamH;
  const capCtx = capCanvas.getContext('2d');
  const capLogical = new THREE.Vector3();
  const SIZE2 = new THREE.Vector2();
  let streamDue = false;
  let captureInFlight = false;
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
    } catch (e) {
      console.error("Send failed:", e);
    }
  }
  function doStreamCapture() {
    if (!videoSocket || videoSocket.readyState !== 1 || videoSocket.bufferedAmount > 0 || captureInFlight) return;
    captureInFlight = true;
    try {
      if (CONFIG.STREAM_SOURCE === 'payload') computePayloadPose(capLogical, payloadCamera);else computeFixedPose(capLogical, payloadCamera);
      placeWorld(capLogical);
      const DPR = renderer.getPixelRatio();
      const cw = renderer.domElement.width,
        ch = renderer.domElement.height;
      const devW = Math.min(SETTINGS.streamW, cw),
        devH = Math.min(SETTINGS.streamH, ch);
      renderer.setScissorTest(true);
      renderer.setScissor(0, 0, devW / DPR, devH / DPR);
      renderer.setViewport(0, 0, devW / DPR, devH / DPR);
      renderer.render(scene, payloadCamera);
      renderer.setScissorTest(false);
      renderer.getSize(SIZE2);
      renderer.setViewport(0, 0, SIZE2.x, SIZE2.y);
      capCtx.drawImage(renderer.domElement, 0, ch - devH, devW, devH, 0, 0, devW, devH);
      capCanvas.toBlob(async blob => {
        try {
          if (blob) await sendBlob(blob);
        } finally {
          captureInFlight = false;
        }
      }, 'image/jpeg', SETTINGS.streamQ);
    } catch (e) {
      captureInFlight = false;
      console.error("Capture error:", e);
      renderer.setScissorTest(false);
      renderer.getSize(SIZE2);
      renderer.setViewport(0, 0, SIZE2.x, SIZE2.y);
    }
  }
  let videoSocket = null;
  function syncVideoStream() {
    if (!SETTINGS.streamOn) { videoSocket?.close(); videoSocket = null; return; }
    if (videoSocket && videoSocket.readyState < 2) return;
    try {
    videoSocket = new WebSocket(CONFIG.STREAM_URL);
    videoSocket.binaryType = 'arraybuffer';
    videoSocket.onopen = () => {
      console.log("WebSocket connected");

    };
    videoSocket.onerror = () => console.warn("WebSocket not available:", CONFIG.STREAM_URL);
  } catch (e) {
    console.warn("WebSocket setup failed:", e);
    }
  }
  syncVideoStream();
  setInterval(() => { if (SETTINGS.streamOn) streamDue = true; }, CONFIG.STREAM_MS);

  /* =====================================================================
     Settings panel, quality presets (incl. 4K supersample), FPS + governor
     ===================================================================== */
  const fpsEl = $('fps-meter');
  const frameSamples = [];
  let fpsFrames = 0,
    fpsAccum = 0,
    fpsShown = 60;
  function dprCap() {
    return Math.min(window.devicePixelRatio || 1, CONFIG.PIXEL_RATIO_CAP);
  }
  function applyDpr() {
    const pixelCap = Math.sqrt(16000000 / Math.max(1, container.clientWidth * container.clientHeight));
    renderer.setPixelRatio(Math.min(curDpr, pixelCap));
    renderer.setSize(container.clientWidth, container.clientHeight);
  }
  const PRESETS = {
    low: {
      dpr: 0.75,
      budget: 80,
      concurrent: 5
    },
    balanced: {
      dpr: 1.0,
      budget: 140,
      concurrent: 8
    },
    high: {
      dpr: 1.5,
      budget: 190,
      concurrent: 10
    },
    ultra: {
      dpr: 0,
      budget: 250,
      concurrent: 11
    },
    /* 0 → native device resolution */
    '4k': {
      dpr: 2.0,
      budget: 300,
      concurrent: 12
    } /* supersampled 4× pixel count */
  };
  function applyPreset(name) {
    applyTextureQuality(name);
    if (name === 'auto') {
      document.body.dataset.quality = name;
      document.body.dataset.economy = String((navigator.deviceMemory || 4) <= 4);
      for (const o of starAnchors) if (o.isPoints) o.geometry.setDrawRange(0, Infinity);
      CONFIG.TILE_BUDGET = 120;
      CONFIG.MAX_CONCURRENT = 7;
      curDpr = Math.min(1.25, dprCap());
      applyDpr();
      return;
    }
    const p = PRESETS[name];
    if (!p) return;
    curDpr = p.dpr === 0 ? dprCap() : p.dpr;
    document.body.dataset.quality = name;
    document.body.dataset.economy = String(name === 'low');
    for (const o of starAnchors) if (o.isPoints) o.geometry.setDrawRange(0, name === 'low' ? Math.ceil(o.geometry.attributes.position.count * 0.3) : Infinity);
    CONFIG.TILE_BUDGET = p.budget;
    CONFIG.MAX_CONCURRENT = p.concurrent;
    applyDpr();
  }
  /* rAF follows display refresh; resolution stays fixed for consistent quality. */
  function tickFPS(dt) {
    frameSamples.push(dt * 1000);
    if (frameSamples.length > 600) frameSamples.shift();
    fpsFrames++;
    fpsAccum += dt;
    if (fpsAccum >= 0.5) {
      fpsShown = fpsFrames / fpsAccum;
      window.dispatchEvent(new CustomEvent('simulation-fps', {
        detail: fpsShown
      }));
      const sorted = [...frameSamples].sort((a, b) => b - a);
      const tail = sorted.slice(0, Math.max(1, Math.ceil(sorted.length * .01)));
      const low = 1000 / (tail.reduce((a, b) => a + b, 0) / tail.length);
      window.simulationFrameStats = {
        fps: fpsShown,
        onePercentLow: low,
        worstFrameMs: sorted[0],
        samples: sorted.length
      };
      fpsFrames = 0;
      fpsAccum = 0;
      if (SETTINGS.fps) {
        fpsEl.style.display = 'block';
        fpsEl.textContent = fpsShown.toFixed(0) + ' fps ? 1% low ' + low.toFixed(0);
        fpsEl.style.color = fpsShown >= 50 ? '#9fe08f' : fpsShown >= 30 ? '#ffd27f' : '#ff7f7f';
      } else fpsEl.style.display = 'none';
    }
  }
  function applySettings() {
    renderer.toneMappingExposure = SETTINGS.exposure;
    baseMat.uniforms.nightBoost.value = CONFIG.NIGHT_BOOST * SETTINGS.city;
    moonTintVec.copy(moonlightBase).multiplyScalar(SETTINGS.night);
    atmoMat.uniforms.uIntensity.value = SETTINGS.atmo;
    for (const m of starMats) m.color.setScalar(0.55 * SETTINGS.stars);
    hazeSphere.userData.overviewBaseOpacity = Math.min(1, 0.80 * SETTINGS.stars);
    hazeMat.opacity = hazeSphere.userData.overviewBaseOpacity * (1 - (cosmicExplorer.skyBlend || 0));
    hazeMat.color.setRGB(1.3, 1.18, 1.45);
    sunSprite.scale.set(CONFIG.SUN_GLARE_SIZE * SETTINGS.sunSize, CONFIG.SUN_GLARE_SIZE * SETTINGS.sunSize, 1);
    moonMesh.scale.setScalar(SETTINGS.moonSize);
    sunLight.intensity = CONFIG.SUN_INTENSITY * SETTINGS.modelSun;
    for (const m of modelMats) if (m.envMapIntensity !== undefined) m.envMapIntensity = CONFIG.MODEL_ENV * SETTINGS.modelEnv;
    CONFIG.TARGET_PX = SETTINGS.sharp;
  }
  listen($('settings-toggle'), 'click', () => window.setSettingsOpen(!$('settings-panel').classList.contains('open')));
  listen($('settings-close'), 'click', () => {
    window.setSettingsOpen(false);
  });
  function bindRange(id, key, fmt) {
    const el = $(id),
      val = $(id + '-val');
    el.value = SETTINGS[key];
    val.textContent = fmt(SETTINGS[key]);
    listen(el, 'input', () => {
      SETTINGS[key] = parseFloat(el.value);
      val.textContent = fmt(SETTINGS[key]);
      applySettings();
      saveSettings();
    });
  }
  const f2 = v => (+v).toFixed(2);
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
    listen(el, 'change', () => {
      SETTINGS[key] = el.checked;
      saveSettings();
      if (after) after();
    });
  }
  bindCheck('set-fps', 'fps', () => {
    if (!SETTINGS.fps) fpsEl.style.display = 'none';
  });
  bindCheck('set-simfeed', 'simFeed', () => {
    feedEl.style.display = SETTINGS.simFeed ? 'block' : 'none';
  });
  bindCheck('set-clouds-on', 'cloudsOn');
  bindCheck('set-stream-on', 'streamOn', syncVideoStream);
  bindCheck('set-attlock', 'attLock'); // toggling never jumps the view (per-frame delta)

  feedEl.style.display = SETTINGS.simFeed ? 'block' : 'none';
  {
    const el = $('set-preset');
    el.value = SETTINGS.preset;
    listen(el, 'change', () => {
      SETTINGS.preset = el.value;
      applyPreset(el.value);
      saveSettings();
    });
  }
  {
    const el = $('set-sharp');
    el.value = String(SETTINGS.sharp);
    listen(el, 'change', () => {
      SETTINGS.sharp = parseInt(el.value, 10);
      applySettings();
      saveSettings();
    });
  }
  {
    const el = $('set-streamsize');
    const cur = SETTINGS.streamW + 'x' + SETTINGS.streamH;
    for (const o of el.options) if (o.value === cur) el.value = cur;
    listen(el, 'change', () => {
      const [w, h] = el.value.split('x').map(Number);
      SETTINGS.streamW = w;
      SETTINGS.streamH = h;
      applyStreamSize();
      saveSettings();
    });
  }
  applyPreset(SETTINGS.preset);
  applySettings();

  /* =====================================================================
     Per-frame updates + render loop
     ===================================================================== */
  function smoothSatellite(dt) {
    if (CONFIG.SMOOTH <= 0) {
      satLogical.copy(satLogicalTarget);
      if (hasBodyQuat) satGroup.quaternion.copy(satQuatTarget);
      return;
    }
    const k = 1 - Math.exp(-dt * (document.body.classList.contains('mission-clear-active') ? Math.min(1.5, CONFIG.SMOOTH) : CONFIG.SMOOTH));
    // Follow the orbital arc instead of a chord that can pass through Earth.
    interpolateOrbitalPosition(satLogical, satLogicalTarget, k);
    if (hasBodyQuat) {
      if (SETTINGS.smoothAttitude) satGroup.quaternion.slerp(satQuatTarget, k);else satGroup.quaternion.copy(satQuatTarget);
    }
  }
  const LINE_END = new THREE.Vector3();
  function updateLines() {
    sunLine.setEndpoints(ZERO, LINE_END.copy(sunDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
    if (moonDirEcef) moonLine.setEndpoints(ZERO, LINE_END.copy(moonDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
    if (nadirDirEcef) nadirLine.setEndpoints(ZERO, LINE_END.copy(nadirDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
    if (sweepDirEcef) sweepLine.setEndpoints(ZERO, LINE_END.copy(sweepDirEcef).multiplyScalar(CONFIG.DIRLINE_LEN));
  }
  const LPOS = new THREE.Vector3(),
    LDIR = new THREE.Vector3();
  function updateLabels() {
    camera.updateMatrixWorld();
    camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    camera.getWorldDirection(LDIR);
    const w = window.innerWidth,
      h = window.innerHeight;
    for (const L of labels) {
      if (!L.el.textContent.includes('We are here') && L !== satelliteNameLabel && camLogical.distanceTo(satLogical) > 30000 || !L.isVisible()) {
        L.el.style.display = 'none';
        continue;
      }
      L.getPos(LPOS);
      LPOS.sub(camLogical);
      if (LPOS.dot(LDIR) <= 0) {
        L.el.style.display = 'none';
        continue;
      }
      LPOS.project(camera);
      if (LPOS.x < -1.05 || LPOS.x > 1.05 || LPOS.y < -1.05 || LPOS.y > 1.05) {
        L.el.style.display = 'none';
        continue;
      }
      L.el.style.display = 'block';
      L.el.style.left = (LPOS.x * 0.5 + 0.5) * w + 'px';
      L.el.style.top = (-LPOS.y * 0.5 + 0.5) * h + 'px';
    }
  }
  let bootFaded = false;
  let lastT = performance.now();
  let lastCloudTimeMs = null;
  function animate(now) {
    requestAnimationFrame(animate);
    const frameDt = (now - lastT) / 1000 || 0.016;
    const dt = Math.min(0.1, frameDt);
    lastT = now;
    if (document.hidden) return;
    if (overviewView) overviewDistance = cosmicExplorer.updateZoom(dt);
    smoothSatellite(dt);
    applyChaseAttitudeLock();
    trackBodyQuat();
    updateCamera();
    if (overviewView || cameraTransition) {
      if (cameraTransition) cameraTransitionElapsed += dt;
      desiredCamLogical.copy(camLogical);
      desiredCamQuat.copy(camera.quaternion);
      if (overviewView) {
        if (!cameraTransition && cosmicExplorer.referenceTime < 88) overviewAzimuth += dt * .006; // Camera-only drift; Orekit Earth/orbit time is unchanged.
        overviewRadial.copy(satLogical).normalize();
        overviewTangent.set(0, 0, 1).cross(overviewRadial).normalize();
        if (overviewTangent.lengthSq() < .01) overviewTangent.set(1, 0, 0);
        overviewCamLogical.copy(overviewRadial).applyAxisAngle(Z_AXIS, overviewAzimuth);
        overviewTangent.set(0, 0, 1).cross(overviewCamLogical);
        if (overviewTangent.lengthSq() < .0001) overviewTangent.set(1, 0, 0);
        overviewTangent.normalize();
        overviewCamLogical.applyAxisAngle(overviewTangent, overviewElevation);
        overviewUp.copy(overviewCamLogical).cross(overviewTangent).normalize();
        cosmicExplorer.cameraOrbit(overviewCamLogical, overviewUp);
        overviewCamLogical.multiplyScalar(overviewDistance).addScaledVector(overviewTangent, 2.6e6);
        camera.position.copy(overviewCamLogical);
        camera.up.copy(overviewUp);
        camera.lookAt(ZERO);
        desiredCamLogical.copy(overviewCamLogical);
        desiredCamQuat.copy(camera.quaternion);
      }
      const t = Math.min(1, cameraTransitionElapsed / 1.05);
      const easing = t * t * t * (t * (t * 6 - 15) + 10);
      if (cameraTransition) {
        if (!flightTargetReady) {
          flightEndOffset.copy(desiredCamLogical).sub(satLogical);
          flightEndRadius = Math.max(.1, flightEndOffset.length());
          flightEndOffset.divideScalar(flightEndRadius);
          flightEndQuat.copy(desiredCamQuat).normalize();
          flightRotation.setFromUnitVectors(flightStartOffset, flightEndOffset);
          flightScaleEnd = overviewView ? clamp(flightEndRadius * .012, 1, 180000) : 1;
          flightTargetReady = true;
        }
        flightStep.identity().slerp(flightRotation, easing);
        flightDirection.copy(flightStartOffset).applyQuaternion(flightStep);
        displayCamLogical.copy(satLogical).addScaledVector(flightDirection, Math.exp(Math.log(flightStartRadius) * (1 - easing) + Math.log(flightEndRadius) * easing));
        displayCamQuat.copy(transitionStartQuat).normalize().slerp(flightEndQuat, easing).normalize();
        flightDisplayScale = Math.exp(Math.log(flightScaleStart) * (1 - easing) + Math.log(flightScaleEnd) * easing);
      } else {
        displayCamLogical.copy(desiredCamLogical);
        displayCamQuat.copy(desiredCamQuat);
      }
      camLogical.copy(displayCamLogical);
      camera.quaternion.copy(displayCamQuat);
      camera.position.set(0, 0, 0);
      if (cameraTransition && t >= 1) {
        camLogical.copy(desiredCamLogical);
        camera.quaternion.copy(desiredCamQuat);
        cameraTransition = false;
        lastCameraTransitionEndMs = now;
      }
    }
    // Close satellite views retain readable terrain on the unlit hemisphere.
    nightViewBrightness += ((overviewView ? 1 : 7) - nightViewBrightness) * (1 - Math.exp(-dt * 12));
    moonTintVec.copy(moonlightBase).multiplyScalar(SETTINGS.night * nightViewBrightness);
    baseMat.uniforms.cityVisibility.value = 1;
    auroraMesh.visible = overviewView;
    auroraMesh.material.uniforms.time.value = now * .001;
    cosmicExplorer.updateSkyMix(overviewView);
    if (overviewView && cosmicExplorer.distance <= 2e8) cosmicExplorer.publishScale(now, camLogical.length(), camera.fov);
    if (overviewView && cosmicExplorer.render(dt, now, {
      position: camLogical,
      up: overviewUp,
      quaternion: camera.quaternion,
      transitioning: cameraTransition
    })) {
      tickFPS(frameDt);
      return;
    }
    if (!skyAligned && telemetryPrimed && (!overviewView || cameraTransitionElapsed > 1.1)) {
      hazeSphere.quaternion.copy(camera.quaternion).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(0.33, 0, 0)));
      skyAligned = true;
    }
    tickFPS(frameDt);
    if (streamDue) {
      streamDue = false;
      if (SETTINGS.streamOn && document.visibilityState === 'visible') doStreamCapture();
    }
    placeWorld(camLogical);
    // The physically sized model is sub-pixel from overview range; enlarge
    // only its display mesh so the same live spacecraft remains identifiable.
    modelHolder.scale.setScalar(cameraTransition ? flightDisplayScale : overviewView ? clamp(camLogical.distanceTo(satLogical) * .012, 1, 180000) : 1);
    paintSensorMarkers();
    const camAlt = camLogical.length() - EARTH_R_MEAN;
    const atmoF = sstep(85000, 150000, camAlt);
    atmoMesh.visible = atmoF > 0.01;
    atmoMat.uniforms.uFade.value = atmoF;
    const cloudTarget = getCloudsReady() && SETTINGS.cloudsOn ? sstep(100000, 160000, camAlt) * Math.min(.9, SETTINGS.clouds * (overviewView ? 3.4 : .68)) : 0;
    cloudsMat.opacity += (cloudTarget - cloudsMat.opacity) * Math.min(1, dt * 3);
    cloudsMesh.visible = cloudsMat.opacity > 0.01;
    upperCloudsMat.opacity = cloudsMat.opacity * .38;
    upperCloudsMesh.visible = upperCloudsMat.opacity > .01;
    if (simulationTimeMs !== null) {
      if (lastCloudTimeMs !== null) {
        const weatherDt = clamp((simulationTimeMs - lastCloudTimeMs) / 1000, 0, 10);
        cloudsMesh.rotation.z += weatherDt * 0.0000038;
        upperCloudsMesh.rotation.z += weatherDt * 0.000008;
      }
      lastCloudTimeMs = simulationTimeMs;
    }
    updateLines();
    updateTileFades(now, dt);
    // Avoid a burst of ray tests, tile creation, and image uploads mid-flight.
    if (!cameraTransition && now - lastTileUpdate > 250) {
      lastTileUpdate = now;
      updateTiles(now);
    }
    if (camAlt >= 2.0e6) for (const t of tiles.values()) t.mesh.visible = false;
    updateLabels();
    updateClock();
    updateFeedMeter(now);
    renderer.render(scene, camera);
    if (!bootFaded && window.spacecraftRenderAsset && earthImageryReady && telemetryPrimed && !cameraTransition) {
      bootFaded = true;
      reportLoading(100, 'Simulation ready', true);
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
      const p = document.documentElement.requestFullscreen({
        navigationUI: 'hide'
      });
      if (p && typeof p.catch === 'function') p.catch(() => {/* denied; button retry */});
    } catch (e) {/* ignored */}
  }
  /* Manual-only toggle (see note above). */
  listen($("fullscreen-toggle"), 'click', () => {
    if (document.fullscreenElement) {
      const p = document.exitFullscreen();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } else enterFullscreen();
  });
  requestAnimationFrame(animate);
  return () => {
    lifecycle.dispose();
    disposeModelLoader();
    cosmicExplorer.dispose();
    videoSocket?.close();
    for (const t of tiles.values()) disposeTile(t);
    const disposed = new Set();
    scene.traverse(object => {
      for (const resource of [object.geometry, ...(Array.isArray(object.material) ? object.material : [object.material])]) {
        if (resource && !disposed.has(resource)) {
          disposed.add(resource);
          resource.dispose?.();
        }
      }
    });
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
    labelsRoot.replaceChildren();
    window.gsap?.killTweensOf(cosmicExplorer);
    if (window.renderer === renderer) {
      for (const name of ['scene', 'camera', 'renderer', 'satelliteGroup', 'missionCameraState',
        'missionTileState', 'spacecraftRenderAsset', 'spacecraftBatchStats', 'simulationFrameStats', 'adjust', 'sendData']) delete window[name];
    }
  };
}
