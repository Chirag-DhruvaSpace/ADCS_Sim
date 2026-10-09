/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from "three";
export function createImageryTiles({
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
  getCamLogical,
  getCameraMode,
  getVideoSocket,
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
}) {
  const tiles = new Map();
  window.missionTileState = () => ({
    total: tiles.size,
    loaded: [...tiles.values()].filter(t => t.loaded).length,
    failed: [...tiles.values()].filter(t => t.failed).length
  });
  const needed = new Set();
  const extraVisible = new Set(); // 404-fallback parents
  // 404-fallback parents
  const pending = [];
  let loadingCount = 0;

  /* children sit slightly above parents so a sharper tile crossfades over
     the blurrier one instead of being hidden behind it */
  /* children sit slightly above parents so a sharper tile crossfades over
     the blurrier one instead of being hidden behind it */
  const tileLift = z => 1.0 + Math.max(0, z - CONFIG.MIN_TILED_Z) * 2.0;
  class TileMaterial extends THREE.ShaderMaterial {
    constructor() {
      super({
        uniforms: {
          map: {
            value: null
          },
          waterMap: baseMat.uniforms.waterMap,
          nightBoost: baseMat.uniforms.nightBoost,
          sunDir: {
            value: sunDirVec
          },
          moonTint: {
            value: moonTintVec
          },
          uOpacity: {
            value: 0
          }
        },
        /* Ordered imagery layers never write depth, including at full opacity. */
        transparent: true,
        depthWrite: false,
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
          vec3 col = mix(nativeNight(tex,water,nightBoost), tex * (${configuration.viewer_lighting.earth_day_ambient ?? 0.12} + ${configuration.viewer_lighting.earth_day_diffuse ?? 0.78} * max(ndl, 0.0)), dayW);
          vec3 H = normalize(sunDir + V);
          col += vec3(1.0, 0.93, 0.82) * pow(max(dot(N, H), 0.0), 90.0) * water * dayW * 0.5;
          float fr = pow(1.0 - max(dot(N, V), 0.0), 3.0);
          col += vec3(0.07, 0.16, 0.35) * fr * (0.25 + 0.75 * dayW);
          ${COLOR_FIX_GLSL}
          gl_FragColor = vec4(col, uOpacity);
          #include <colorspace_fragment>
        }`
      });
    }
  }
  class Tile {
    constructor(z, x, y) {
      this.z = z;
      this.x = x;
      this.y = y;
      this.key = `${z}/${x}/${y}`;
      const n = 1 << z;
      const west = x / n * 360 - 180,
        east = (x + 1) / n * 360 - 180;
      const north = tile2lat(y, z),
        south = tile2lat(y + 1, z);
      const lift = tileLift(z);
      const cx = latLonToECEF((north + south) / 2, (west + east) / 2, lift);
      this.center = cx;
      const segs = z < 5 ? 32 : z < 8 ? 10 : z < 12 ? 8 : 6;
      const S1 = segs + 1;

      /* skirt depth: covers chord-vs-arc sag + LOD-boundary T-junction steps */
      const latSpanM = Math.abs(north - south) * 111320;
      const sag = Math.pow(latSpanM / segs, 2) / (2 * EARTH_R_MEAN);
      const skirt = clamp(sag * 4 + 2, 2, 500);
      const pos = [],
        nor = [],
        uv = [],
        idx = [];
      for (let j = 0; j <= segs; j++) {
        const lat = north + (south - north) * j / segs;
        const cl = Math.cos(lat * DEG),
          sl = Math.sin(lat * DEG);
        for (let i = 0; i <= segs; i++) {
          const lon = west + (east - west) * i / segs;
          const co = Math.cos(lon * DEG),
            so = Math.sin(lon * DEG);
          const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
          pos.push((N + lift) * cl * co - cx.x, (N + lift) * cl * so - cx.y, (N * (1 - WGS84_E2) + lift) * sl - cx.z);
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
        pos.push(pos[p] - nor[p] * skirt, pos[p + 1] - nor[p + 1] * skirt, pos[p + 2] - nor[p + 2] * skirt);
        nor.push(nor[p], nor[p + 1], nor[p + 2]);
        uv.push(uv[vi * 2], uv[vi * 2 + 1]);
        skirtOf[vi] = nextIdx++;
        return skirtOf[vi];
      };
      for (let i = 0; i <= segs; i++) {
        addSkirtVert(0, i);
        addSkirtVert(segs, i);
      }
      for (let j = 1; j < segs; j++) {
        addSkirtVert(j, 0);
        addSkirtVert(j, segs);
      }
      for (let j = 0; j < segs; j++) for (let i = 0; i < segs; i++) {
        const a = vMain(j, i),
          b = a + 1,
          c = a + S1,
          d = c + 1;
        idx.push(a, c, b, b, c, d);
      }
      const skirtQuad = (a, b, c, d) => idx.push(a, b, c, a, c, d, c, b, a, d, c, a);
      for (let i = 0; i < segs; i++) {
        skirtQuad(vMain(0, i), vMain(0, i + 1), addSkirtVert(0, i + 1), addSkirtVert(0, i));
        skirtQuad(vMain(segs, i), vMain(segs, i + 1), addSkirtVert(segs, i + 1), addSkirtVert(segs, i));
      }
      for (let j = 0; j < segs; j++) {
        skirtQuad(vMain(j, 0), vMain(j + 1, 0), addSkirtVert(j + 1, 0), addSkirtVert(j, 0));
        skirtQuad(vMain(j, segs), vMain(j + 1, segs), addSkirtVert(j + 1, segs), addSkirtVert(j, segs));
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
      g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
      g.setIndex(idx);
      this.mat = new TileMaterial();
      this.mesh = new THREE.Mesh(g, this.mat);
      this.mesh.renderOrder = 100 + z; // parents render before children — crossfades layer correctly
      this.mesh.visible = false;
      this.loaded = false;
      this.failed = false;
      this.requested = false;
      this.disposed = false;
      this.cullHidden = false; // set when all 4 children fully cover this parent
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
      t.requested = true;
      loadingCount++;
      texLoader.load(TILE_URL(t.z, t.x, t.y), tex => {
        loadingCount--;
        if (t.disposed) {
          tex.dispose();
          pump();
          return;
        }
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = MAX_ANISO;
        t.mat.uniforms.map.value = tex;
        t.mat.uniforms.uOpacity.value = 0;
        t.loaded = true; // fade-in handled per frame
        pump();
      }, undefined, () => {
        loadingCount--;
        if (t.disposed) {
          pump();
          return;
        }
        t.failed = true;
        if (t.z > CONFIG.MIN_TILED_Z) {
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
          // fall back to the parent tile
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
  /* evict ONLY fully-faded, unneeded tiles — a tile is never popped off
     the screen: visible sharp tiles always have a fallback beneath them */
  function evict(now) {
    let excess = tiles.size - CONFIG.CACHE_MAX;
    if (excess <= 0) return;
    const arr = [];
    for (const t of tiles.values()) {
      if (needed.has(t.key) || extraVisible.has(t.key)) continue;
      if (t.loaded && t.mat.uniforms.uOpacity.value > 0.004) continue; // still fading out
      arr.push(t);
    }
    arr.sort((a, b) => a.neededAt - b.neededAt);
    for (const t of arr) {
      if (excess <= 0) break;
      disposeTile(t);
      excess--;
    }
  }

  /* ---- per-cell footprint LOD selection (corner rays → exact coverage) ---- */
  /* ---- per-cell footprint LOD selection (corner rays → exact coverage) ---- */
  function pickLevel(pxPerMeter, latDeg) {
    const cosLat = Math.max(0.05, Math.cos(latDeg * DEG));
    for (let zz = CONFIG.MAX_Z; zz >= 2; zz--) {
      if (EARTH_CIRC * cosLat / (1 << zz) * pxPerMeter >= CONFIG.TARGET_PX) return zz;
    }
    return 2;
  }
  const DIRV = new THREE.Vector3(),
    HIT = new THREE.Vector3(),
    HITN = new THREE.Vector3();
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
        if (allowCreate <= 0) return; // retried on the next update
        t = ensureTile(z, tx, ty, HIT);
        allowCreate--;
      }
      needed.add(key);
      t.neededAt = now;
      if (count) marked++;
    };
    for (let cy = 0; cy < gridN && marked < budget; cy++) {
      for (let cx = 0; cx < gridN && marked < budget; cx++) {
        const i00 = cy * NP + cx,
          i10 = i00 + 1,
          i01 = i00 + NP,
          i11 = i01 + 1;
        let sx = 0,
          sy = 0,
          sz = 0,
          cn = 0;
        let latMin = 90,
          latMax = -90;
        let lonC = 0,
          relMin = 1e9,
          relMax = -1e9,
          first = true;
        for (const idx of [i00, i10, i01, i11]) {
          const h = hits[idx];
          if (!h) continue;
          HITN.copy(h).normalize();
          const la = Math.asin(clamp(HITN.z, -1, 1)) / DEG;
          const lo = Math.atan2(HITN.y, HITN.x) / DEG;
          if (first) {
            lonC = lo;
            first = false;
          }
          const rel = wrap180(lo - lonC);
          if (rel < relMin) relMin = rel;
          if (rel > relMax) relMax = rel;
          if (la < latMin) latMin = la;
          if (la > latMax) latMax = la;
          sx += h.x;
          sy += h.y;
          sz += h.z;
          cn++;
        }
        if (!cn) continue;
        CTR.set(sx / cn, sy / cn, sz / cn);
        HITN.copy(CTR).normalize();
        DIRV.copy(CTR).sub(originLogical).normalize();
        const cosI = Math.max(0.25, -DIRV.dot(HITN)); // obliquity
        const effDist = originLogical.distanceTo(CTR) / cosI;
        const pxPerMeter = screenH * 0.5 / (effDist * tanHalf);
        const latC = Math.asin(clamp(HITN.z, -1, 1)) / DEG;
        let z = Math.max(pickLevel(pxPerMeter, latC), CONFIG.MIN_TILED_Z);
        const n = 1 << z;
        const lonMin = lonC + relMin,
          lonMax = lonC + relMax;
        let x0 = Math.floor((lonMin + 180) / 360 * n);
        let x1 = Math.floor((lonMax + 180) / 360 * n);
        if (x1 - x0 >= n) {
          x0 = 0;
          x1 = n - 1;
        } // full-circle safety
        const y0 = lat2tileY(latMax, z),
          y1 = lat2tileY(latMin, z);
        for (let ty = y0; ty <= y1 && marked < budget; ty++) {
          if (ty < 0 || ty >= n) continue;
          for (let tx = x0; tx <= x1 && marked < budget; tx++) {
            needTile(z, (tx % n + n) % n, ty, true);
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
      let tx = +rest.slice(0, comma),
        ty = +rest.slice(comma + 1);
      tx >>= 1;
      ty >>= 1;
      for (let pz = z - 1; pz >= CONFIG.MIN_TILED_Z; pz--) {
        needTile(pz, tx, ty, false);
        tx >>= 1;
        ty >>= 1;
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
      if (t.mat.uniforms.uOpacity.value < 1) continue; // a fading child doesn't count
      const pk = `${t.z - 1}/${t.x >> 1}/${t.y >> 1}`;
      const rec = childCover.get(pk);
      if (rec) rec.n++;else childCover.set(pk, {
        n: 1
      });
    }
    for (const [pk, rec] of childCover) {
      if (rec.n >= 4) {
        // all 4 children opaque → parent fully covered → skip drawing it
        const p = tiles.get(pk);
        if (p) p.cullHidden = true;
      }
    }
  }
  function updateTiles(now, view = getCamLogical(), viewCamera = camera) {
    needed.clear();
    if (view.length() - EARTH_R_MEAN < 2.0e6) addViewTiles(view, viewCamera, renderer.domElement.height, 9, CONFIG.TILE_BUDGET, CONFIG.CREATE_BUDGET, now);
    if (SETTINGS.streamOn && CONFIG.STREAM_SOURCE === 'payload' && getCameraMode() !== 'payload' && getVideoSocket() && getVideoSocket().readyState === 1) {
      computePayloadPose(streamTileLogical, payloadCamera);
      addViewTiles(streamTileLogical, payloadCamera, SETTINGS.streamH, 5, CONFIG.STREAM_TILE_BUDGET, CONFIG.CREATE_STREAM_BUDGET, now);
    }
    updateParentCulling();
    pump();
    evict(now);
  }

  /* fade IN and OUT — always a crossfade over the layer beneath (parent /
     base globe), depth-write disabled on imagery layers */
  /* fade IN and OUT — always a crossfade over the layer beneath (parent /
     base globe), depth-write disabled on imagery layers */
  function updateTileFades(now, dt) {
    const step = dt * 1000 / CONFIG.TILE_FADE_MS;
    for (const t of tiles.values()) {
      if (!t.loaded) {
        t.mesh.visible = false;
        continue;
      }
      const active = needed.has(t.key) || extraVisible.has(t.key);
      const target = active ? 1 : 0;
      let op = t.mat.uniforms.uOpacity.value;
      if (op < target) op = Math.min(target, op + step);else if (op > target) {
        op = Math.max(target, op - step);
        if (t.z > CONFIG.MIN_TILED_Z) {
          // reveal the parent while fading out
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
  return {
    tiles,
    updateTiles,
    updateTileFades,
    disposeTile
  };
}
