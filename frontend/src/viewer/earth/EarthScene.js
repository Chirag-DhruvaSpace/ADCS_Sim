/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';
import { createEarthAurora } from './aurora.js';
export function createEarthScene({
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
  getHazeMaterial,
  loadTex,
  renderer,
  scene,
  solidTex,
  sunDirVec
}) {
  const moonlightBase = new THREE.Vector3(...CONFIG.MOONLIGHT);
  const moonTintVec = moonlightBase.clone();
  function buildEllipsoidGeometry(segLat, segLon, scaleMult, liftM, withUV) {
    const pos = [],
      nor = [],
      uv = [],
      idx = [];
    for (let i = 0; i <= segLat; i++) {
      const lat = 90 - 180 * i / segLat;
      const cl = Math.cos(lat * DEG),
        sl = Math.sin(lat * DEG);
      for (let j = 0; j <= segLon; j++) {
        const lon = -180 + 360 * j / segLon;
        const co = Math.cos(lon * DEG),
          so = Math.sin(lon * DEG);
        const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
        pos.push((N + liftM) * cl * co * scaleMult, (N + liftM) * cl * so * scaleMult, (N * (1 - WGS84_E2) + liftM) * sl * scaleMult);
        nor.push(cl * co, cl * so, sl);
        if (withUV) uv.push((lon + 180) / 360, (lat + 90) / 180);
      }
    }
    const S1 = segLon + 1;
    for (let i = 0; i < segLat; i++) for (let j = 0; j < segLon; j++) {
      const a = i * S1 + j,
        b = a + 1,
        c = a + S1,
        d = c + 1;
      idx.push(a, c, b, b, c, d);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
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
    vec3 moonlit = surface * max(moonTint * (0.8 + 0.2 * boost), vec3(${configuration.viewer_lighting.earth_night_floor ?? 0.015}));
    return moonlit;
  }
`;
  const baseMat = new THREE.ShaderMaterial({
    uniforms: {
      dayMap: {
        value: solidTex(20, 45, 90)
      },
      cityMap: {
        value: solidTex(0, 0, 0)
      },
      cityVisibility: {
        value: 0
      },
      waterMap: {
        value: solidTex(0, 0, 0)
      },
      sunDir: {
        value: sunDirVec
      },
      nightBoost: {
        value: CONFIG.NIGHT_BOOST
      },
      moonTint: {
        value: moonTintVec
      }
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
      vec3 dayCol = day * (${configuration.viewer_lighting.earth_day_ambient ?? 0.12} + ${configuration.viewer_lighting.earth_day_diffuse ?? 0.78} * max(ndl, 0.0));
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
    }`
  });
  const earthMesh = new THREE.Mesh(buildEllipsoidGeometry(192, 384, 1.0, -4000, true), baseMat);
  earthMesh.name = 'earth-surface';
  scene.add(earthMesh);
  const auroraMesh = createEarthAurora(EARTH_R_MEAN, sunDirVec);
  scene.add(auroraMesh);
  // Day and cloud maps are loaded together by the quality preset.
  loadTex(TEX_WATER, false, t => baseMat.uniforms.waterMap.value = t);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const atmoMat = new THREE.ShaderMaterial({
    uniforms: {
      sunDir: {
        value: sunDirVec
      },
      uFade: {
        value: 1
      },
      uIntensity: {
        value: 1
      }
    },
    side: THREE.BackSide,
    transparent: true,
    depthWrite: false,
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
    }`
  });
  const atmoMesh = new THREE.Mesh(buildEllipsoidGeometry(96, 192, 1.012, 0, false), atmoMat);
  atmoMesh.renderOrder = 300; // after tiles & clouds (additive limb glow)
  scene.add(atmoMesh);

  /* Cloud density maps: 2K for economy, 8K for high-detail presets. */
  const cloudsMat = new THREE.MeshLambertMaterial({
    color: 0xf1f5fb,
    emissive: 0x1b2939,
    emissiveIntensity: .26,
    transparent: true,
    opacity: 0,
    alphaTest: 0.055,
    depthWrite: false
  });
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
  let textureTier = null,
    textureGeneration = 0;
  function applyTextureQuality(name) {
    const high = ['high', 'ultra', '4k'].includes(name) && renderer.capabilities.maxTextureSize >= 8192;
    const medium = !high && name !== 'low' && renderer.capabilities.maxTextureSize >= 4096 && (name !== 'auto' || (navigator.deviceMemory || 4) >= 8);
    const tier = high ? 'high' : medium ? 'medium' : 'low';
    if (textureTier === tier) return;
    textureTier = tier;
    const generation = ++textureGeneration;
    loadTex(high ? '/assets/textures/8k_earth_daymap.jpg' : medium ? '/assets/textures/4k_earth_daymap.jpg' : TEX_DAY, true, t => {
      if (generation !== textureGeneration) {
        t.dispose();
        return;
      }
      const old = baseMat.uniforms.dayMap.value;
      baseMat.uniforms.dayMap.value = t;
      old.dispose();
    });
    loadTex(high ? '/assets/textures/nasa_black_marble_2016_8192.jpg' : medium ? '/assets/textures/nasa_black_marble_2016_4096.jpg' : '/assets/textures/earth-night.jpg', true, t => {
      if (generation !== textureGeneration) {
        t.dispose();
        return;
      }
      const old = baseMat.uniforms.cityMap.value;
      baseMat.uniforms.cityMap.value = t;
      old.dispose();
    });
    loadTex(high ? TEX_CLOUDS_HIGH : medium ? '/assets/textures/4k_earth_clouds.jpg' : TEX_CLOUDS_2K, false, t => {
      if (generation !== textureGeneration) {
        t.dispose();
        return;
      }
      t.wrapS = THREE.RepeatWrapping;
      const old = cloudsMat.alphaMap;
      cloudsMat.alphaMap = t;
      cloudsMat.needsUpdate = true;
      upperCloudsMat.alphaMap = t;
      upperCloudsMat.needsUpdate = true;
      cloudsReady = true;
      if (old) old.dispose();
    });
    loadTex(high ? '/assets/textures/8k_stars_visible.jpg' : medium ? '/assets/textures/4k_stars_visible.jpg' : '/assets/textures/2k_stars_visible.jpg', true, t => {
      if (generation !== textureGeneration) {
        t.dispose();
        return;
      }
      const hazeMat = getHazeMaterial();
      const old = hazeMat.map;
      hazeMat.map = t;
      hazeMat.needsUpdate = true;
      if (old) old.dispose();
    });
  }
  return {
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
    getCloudsReady: () => cloudsReady
  };
}
