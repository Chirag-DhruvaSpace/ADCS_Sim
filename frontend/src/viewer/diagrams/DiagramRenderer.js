/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { TEXTURES } from '../../assets/assetUrls.js';
import * as THREE from 'three';
import { createLifecycle } from '../../services/lifecycle.js';
export function startDiagramRenderer() {
  const lifecycle = createLifecycle();
  const {
    listen,
    setTimeout,
    clearTimeout,
    requestAnimationFrame
  } = lifecycle;
  /* Telemetry diagrams reuse the main GPU context and CAD buffers. */

  const finite = Number.isFinite;
  const valid = v => Array.isArray(v) && v.length === 3 && v.every(x => typeof x === 'number' && finite(x));
  const R = 6378137;
  let renderer;
  let releaseTarget = () => {};
  try {
    renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance'
    });
  } catch (error) {
    console.warn('Telemetry globe renderer unavailable:', error);
  }
  if (renderer) {
    renderer.setPixelRatio(1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, .01, 100);
    camera.up.set(0, 0, 1);
    const light = new THREE.DirectionalLight(0xfff3d9, 2.5);
    scene.add(light);
    // Cartographic fill keeps night-side geography legible in a small diagram.
    scene.add(new THREE.AmbientLight(0xa2bed5, .35));
    const globe = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 32), new THREE.MeshPhongMaterial({
      color: 0xffffff,
      emissive: 0xb8cfe2,
      emissiveIntensity: .12,
      shininess: 24
    }));
    globe.rotation.x = Math.PI / 2;
    globe.scale.y = Math.sqrt(1 - .00669437999014);
    scene.add(globe);
    const texture = new THREE.TextureLoader().load(TEXTURES.day, () => schedule());
    texture.colorSpace = THREE.SRGBColorSpace;
    globe.material.map = texture;
    const earthImage = new Image();
    earthImage.onload = () => schedule();
    earthImage.src = TEXTURES.day;
    // A modest map emissive term keeps oceans and terrain visible at diagram size.
    globe.material.emissiveMap = texture;
    globe.material.needsUpdate = true;
    const orbit = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({
      color: 0x73caff,
      transparent: true,
      opacity: .65
    }));
    scene.add(orbit);
    const equator = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({
      length: 96
    }, (_, i) => new THREE.Vector3(1.16 * Math.cos(i * Math.PI / 48), 1.16 * Math.sin(i * Math.PI / 48), 0))), new THREE.LineBasicMaterial({
      color: 0x7cbce1,
      transparent: true,
      opacity: .24
    }));
    scene.add(equator);
    const satellite = new THREE.Mesh(new THREE.OctahedronGeometry(.045), new THREE.MeshBasicMaterial({
      color: 0xf0fbff
    }));
    scene.add(satellite);
    const sun = new THREE.Mesh(new THREE.SphereGeometry(.13, 16, 12), new THREE.MeshBasicMaterial({
      color: 0xffd768
    }));
    scene.add(sun);
    const moon = new THREE.Mesh(new THREE.SphereGeometry(.07, 16, 12), new THREE.MeshLambertMaterial({
      color: 0xc3cedb
    }));
    scene.add(moon);
    const moonMap = new THREE.TextureLoader().load(TEXTURES.moon, () => schedule());
    moonMap.colorSpace = THREE.SRGBColorSpace;
    moon.material.map = moonMap;
    const sunArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, 0xffcd57, .1, .05);
    scene.add(sunArrow);
    const reconArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 1, 0x66d9ff, .1, .05);
    scene.add(reconArrow);
    const attitude = new THREE.Group();
    scene.add(attitude);
    const modelMount = new THREE.Group();
    attitude.add(modelMount);
    let modelRevision = 0,
      modelWarmup = false;
    function useModel({
      scene: source,
      com = [0, 0, 0]
    }) {
      modelMount.clear();
      // Share decoded CAD geometry and reuse its uploaded buffers in the main context.
      const model = source.clone(true);
      modelRevision++;
      model.updateMatrixWorld(true);
      const bounds = new THREE.Box3().setFromObject(model),
        size = bounds.getSize(new THREE.Vector3());
      const span = Math.max(size.x, size.y, size.z);
      if (span > 0) model.scale.setScalar(2.1 / span);
      model.updateMatrixWorld(true);
      model.position.set(...com.map(x => -x * 2.1 / span));
      modelMount.quaternion.identity();
      modelMount.add(model);
      // Compile shared CAD and globe programs before the first tab interaction.
      const warm = window.renderer || renderer;
      modelWarmup = true;
      Promise.resolve().then(() => {
        const previousTone = warm.toneMapping,
          previousTarget = warm.getRenderTarget();
        try {
          warm.toneMapping = THREE.NoToneMapping;
          warm.setRenderTarget(target);
          return warm.compileAsync?.(scene, camera);
        } finally {
          warm.setRenderTarget(previousTarget);
          warm.toneMapping = previousTone;
        }
      }).then(() => { if (!lifecycle.disposed) warmBuffers(warm); }).catch(error => {
        if (!lifecycle.disposed) console.warn('Diagram warmup:', error);
      }).finally(() => {
        modelWarmup = false;
        schedule();
      });
    }
    listen(window, 'spacecraft-model-ready', e => useModel(e.detail));
    if (window.spacecraftRenderAsset) useModel(window.spacecraftRenderAsset);
    for (const [axis, color] of [[[1, 0, 0], 0xff797d], [[0, 1, 0], 0x4de2a5], [[0, 0, 1], 0x67b9ff]]) attitude.add(new THREE.ArrowHelper(new THREE.Vector3(...axis), new THREE.Vector3(), 1.42, color, .20, .085));
    const gnss = new THREE.Group();
    scene.add(gnss);
    const markerGeo = new THREE.SphereGeometry(.045, 8, 6),
      markerMat = new THREE.MeshBasicMaterial({
        color: 0x57e5a8
      }),
      hiddenMat = new THREE.MeshBasicMaterial({
        color: 0x6f8496
      });
    const linkMat = new THREE.LineBasicMaterial({
      color: 0x5fe6aa,
      transparent: true,
      opacity: .6
    });
    const candidateMat = new THREE.MeshBasicMaterial({
      color: 0x58e8a3,
      transparent: true,
      opacity: 1
    });
    const candidateGeo = new THREE.SphereGeometry(.032, 8, 6);
    // Nominal 24-spacecraft Walker geometry for visual line-of-sight context.
    // This is deliberately not labeled as observed PRNs or receiver locks.
    function gpsCandidates(d, sat) {
      const stamp = Date.parse(d.timestamp);
      if (!Number.isFinite(stamp)) return [];
      const t = stamp / 1000,
        incl = 55 * Math.PI / 180,
        n = 2 * Math.PI / (11 * 3600 + 58 * 60);
      const sidereal = 2 * Math.PI * (t / 86164.0905);
      const out = [];
      for (let plane = 0; plane < 6; plane++) for (let slot = 0; slot < 4; slot++) {
        const phase = n * t + slot * Math.PI / 2 + plane * Math.PI / 12,
          raan = plane * Math.PI / 3;
        const x = Math.cos(raan) * Math.cos(phase) - Math.sin(raan) * Math.sin(phase) * Math.cos(incl);
        const y = Math.sin(raan) * Math.cos(phase) + Math.cos(raan) * Math.sin(phase) * Math.cos(incl);
        const z = Math.sin(phase) * Math.sin(incl);
        const pos = new THREE.Vector3(x, y, z).applyAxisAngle(new THREE.Vector3(0, 0, 1), -sidereal);
        const actual = pos.clone().multiplyScalar(4.2),
          toSV = actual.sub(sat);
        if (toSV.dot(sat.clone().normalize()) > 0) out.push({
          id: plane * 4 + slot,
          pos: pos.multiplyScalar(1.45),
          bearing: Math.atan2(y, x)
        });
      }
      return out;
    }
    function simulatedLinks(d, sat) {
      const candidates = gpsCandidates(d, sat).sort((a, b) => a.bearing - b.bearing);
      const count = Math.max(0, Math.min(4, candidates.length, Math.round(d.gps_num_sv || 0)));
      if (!count) return [];
      // Spread the illustrative links according to reported PDOP; no PRN is implied.
      const spread = THREE.MathUtils.clamp(3 / Math.max(1, d.gps_pdop || 2), .45, 1);
      const span = Math.max(count, Math.round(candidates.length * spread));
      return Array.from({
        length: count
      }, (_, i) => candidates[Math.min(span - 1, Math.floor((i + .5) * span / count))]);
    }
    function earthDisc(ctx, x, y, r) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.clip();
      if (earthImage.complete && earthImage.naturalWidth) ctx.drawImage(earthImage, x - r, y - r, 2 * r, 2 * r);else {
        ctx.fillStyle = '#1a649a';
        ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
      }
      const shade = ctx.createLinearGradient(x - r, y, x + r, y);
      shade.addColorStop(0, 'rgba(1,12,34,.84)');
      shade.addColorStop(.5, 'rgba(1,17,39,.28)');
      shade.addColorStop(1, 'rgba(170,215,255,.06)');
      ctx.fillStyle = shade;
      ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
      ctx.restore();
      ctx.save();
      ctx.shadowColor = '#70bfff';
      ctx.shadowBlur = 12;
      ctx.strokeStyle = '#8fd0ff';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
    function drawGpsLinks(ctx, w, h, d, sat, canvas) {
      const candidates = gpsCandidates(d, sat).sort((a, b) => a.bearing - b.bearing);
      const links = simulatedLinks(d, sat);
      canvas.dataset.simulatedLinks = String(links.length);
      canvas.dataset.candidateSatellites = String(candidates.length);
      if (!candidates.length) return;
      const x = w * .5,
        y = h * .5,
        orbit = Math.min(h * .44, w * .34);
      const point = sv => {
        const a = Math.atan2(sv.pos.y, sv.pos.x),
          r = orbit * (.79 + .16 * Math.abs(sv.pos.z) / 1.45);
        return [x + Math.cos(a) * r, y + Math.sin(a) * r];
      };
      ctx.save();
      ctx.lineWidth = 1.1;
      for (const sv of candidates) {
        const [px, py] = point(sv);
        ctx.fillStyle = '#b7c6d4';
        ctx.strokeStyle = '#dfebf6';
        ctx.lineWidth = .8;
        ctx.beginPath();
        ctx.arc(px, py, 3.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
      for (const sv of links) {
        const [px, py] = point(sv);
        ctx.strokeStyle = 'rgba(95,241,174,.8)';
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(px, py);
        ctx.stroke();
        ctx.fillStyle = '#4cf0a2';
        ctx.shadowColor = '#4cf0a2';
        ctx.shadowBlur = 11;
        ctx.beginPath();
        ctx.arc(px, py, 4.1, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
      ctx.fillStyle = '#f3fbff';
      ctx.beginPath();
      ctx.arc(x, y, 3.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '10px system-ui';
      ctx.textAlign = 'center';
      ctx.fillText('SAT', x, y - 8);
      ctx.restore();
    }
    function drawSunDiagram(ctx, w, h, d, sat) {
      const r = Math.min(h * .29, w * .16),
        earthX = w * .36,
        earthY = h * .56,
        sunX = w * .88,
        sunY = earthY;
      const sunPos = valid(d.sun_position_ecef_m) ? new THREE.Vector3(...d.sun_position_ecef_m) : null;
      const direction = sunPos ? sunPos.sub(sat.clone().multiplyScalar(R)).normalize() : null;
      const facing = direction ? THREE.MathUtils.clamp(sat.clone().normalize().dot(direction), -1, 1) : 0;
      const side = direction && sat.clone().cross(direction).z < 0 ? -1 : 1;
      const satX = earthX + facing * r * 1.5,
        satY = earthY - side * Math.sqrt(Math.max(0, 1 - facing * facing)) * r * 1.5;
      const light = Number.isFinite(d.sun_arr_eclipse_factor) ? d.sun_arr_eclipse_factor : Number.isFinite(d.eclipse_fraction) ? d.eclipse_fraction : null;
      ctx.save();
      ctx.fillStyle = 'rgba(10,24,42,.42)';
      ctx.beginPath();
      ctx.moveTo(earthX - r * .7, earthY - r * .75);
      ctx.lineTo(3, earthY - r * 1.15);
      ctx.lineTo(3, earthY + r * 1.15);
      ctx.lineTo(earthX - r * .7, earthY + r * .75);
      ctx.fill();
      earthDisc(ctx, earthX, earthY, r);
      ctx.strokeStyle = '#a8cee064';
      ctx.setLineDash([3, 5]);
      ctx.beginPath();
      ctx.arc(earthX, earthY, r * 1.5, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.strokeStyle = light !== null && light < .1 ? '#d09d66' : '#ffd15a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(sunX - 10, sunY);
      ctx.lineTo(earthX + r + 5, sunY);
      ctx.stroke();
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(satX, satY);
      ctx.lineTo(sunX - 8, sunY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ffdc71';
      ctx.shadowColor = '#ffbd36';
      ctx.shadowBlur = 15;
      ctx.beginPath();
      ctx.arc(sunX, sunY, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#f7fbff';
      ctx.beginPath();
      ctx.arc(satX, satY, 4.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = '11px system-ui';
      ctx.textAlign = 'center';
      ctx.fillStyle = '#eef8ff';
      ctx.fillText('Earth', earthX, Math.max(12, earthY - r - 8));
      ctx.fillText('SAT', satX, Math.max(12, satY - 10));
      ctx.fillText('Sun', sunX, Math.max(12, sunY - 17));
      ctx.restore();
    }
    let pending = false,
      lastRender = 0,
      timer = null,
      rendering = false,
      rerender = false;
    function schedule() {
      if (rendering) {
        rerender = true;
        return;
      }
      if (pending) return;
      pending = true;
      timer = setTimeout(() => requestAnimationFrame(() => render().catch(error => {
        if (!lifecycle.disposed) console.warn('Diagram draw failed:', error);
      })), Math.max(0, 200 - (performance.now() - lastRender)));
    }
    function position(d) {
      if (valid(d.satellite_position_ecef_m)) return new THREE.Vector3(...d.satellite_position_ecef_m).divideScalar(R);
      if (![d.latitude_deg, d.longitude_deg, d.altitude_m].every(x => typeof x === 'number' && finite(x))) return null;
      const lat = d.latitude_deg * Math.PI / 180,
        lon = d.longitude_deg * Math.PI / 180;
      const n = R / Math.sqrt(1 - .00669437999014 * Math.sin(lat) ** 2),
        h = d.altitude_m;
      return new THREE.Vector3((n + h) * Math.cos(lat) * Math.cos(lon), (n + h) * Math.cos(lat) * Math.sin(lon), (n * (1 - .00669437999014) + h) * Math.sin(lat)).divideScalar(R);
    }
    function frame(d, estimate = false) {
      const a = estimate ? d.estimated_body_to_ecef_matrix : d.body_to_ecef_matrix;
      if (!Array.isArray(a) || a.length !== 3 || !a.every(valid)) return null;
      return new THREE.Matrix4().set(...a[0], 0, ...a[1], 0, ...a[2], 0, 0, 0, 0, 1);
    }
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    function drawLabel(ctx, text, v, w, h, color = '#dfedfa') {
      const p = v.clone().project(camera);
      if (p.z > 1 || p.z < -1 || Math.abs(p.x) > 1 || Math.abs(p.y) > 1) return;
      ctx.font = '11px system-ui';
      ctx.fillStyle = color;
      ctx.shadowColor = '#000';
      ctx.shadowBlur = 4;
      const x = Math.max(5, Math.min(w - ctx.measureText(text).width - 4, (p.x * .5 + .5) * w + 6));
      ctx.fillText(text, x, Math.max(13, Math.min(h - 4, (-p.y * .5 + .5) * h - 5)));
      ctx.shadowBlur = 0;
    }
    function drawAxisLabel(ctx, text, v, w, h, color) {
      const p = v.clone().project(camera);
      if (p.z > 1 || p.z < -1 || Math.abs(p.x) > 1 || Math.abs(p.y) > 1) return;
      const x = Math.max(5, Math.min(w - 25, (p.x * .5 + .5) * w + 5)),
        y = Math.max(15, Math.min(h - 4, (-p.y * .5 + .5) * h));
      ctx.font = 'bold 13px system-ui';
      ctx.textAlign = 'left';
      ctx.lineWidth = 3;
      ctx.strokeStyle = '#04111c';
      ctx.strokeText(text, x, y);
      ctx.fillStyle = color;
      ctx.fillText(text, x, y);
    }
    function updateOrbit(d) {
      const points = d.orbit_path_ecef_m;
      orbit.visible = Array.isArray(points) && points.length > 1 && points.every(valid);
      if (!orbit.visible) return;
      const size = points.length * 3;
      let attr = orbit.geometry.getAttribute('position');
      if (!attr || attr.array.length !== size) {
        attr = new THREE.BufferAttribute(new Float32Array(size), 3);
        orbit.geometry.setAttribute('position', attr);
      }
      points.forEach((p, i) => attr.setXYZ(i, p[0] / R, p[1] / R, p[2] / R));
      attr.needsUpdate = true;
      orbit.geometry.computeBoundingSphere();
    }
    const rendered = new WeakMap(),
      stagingCanvases = new WeakMap(),
      target = new THREE.WebGLRenderTarget(1, 1, {
        samples: 4
      });
    target.texture.colorSpace = THREE.SRGBColorSpace;
    releaseTarget = () => { target.dispose(); texture.dispose(); moonMap.dispose(); };
    let pixels = new Uint8Array(4);
    const oldClear = new THREE.Color();
    async function readPixelsAsync(draw, w, h, output) {
      const gl = draw.getContext();
      if (!gl.fenceSync) {
        draw.readRenderTargetPixels(target, 0, 0, w, h, output);
        return;
      }
      const pack = gl.getParameter(gl.PIXEL_PACK_BUFFER_BINDING),
        read = gl.getParameter(gl.READ_FRAMEBUFFER_BINDING),
        buffer = gl.createBuffer();
      let fence;
      try {
        // The bundled Three.js r160 keeps the resolved 2D framebuffer here.
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, draw.properties.get(target).__webglFramebuffer);
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, buffer);
        gl.bufferData(gl.PIXEL_PACK_BUFFER, output.byteLength, gl.STREAM_READ);
        gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, 0);
        fence = gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE, 0);
      } finally {
        gl.bindBuffer(gl.PIXEL_PACK_BUFFER, pack);
        gl.bindFramebuffer(gl.READ_FRAMEBUFFER, read);
      }
      gl.flush();
      try {
        await new Promise((resolve, reject) => {
          const started = performance.now();
          const poll = () => {
            if (lifecycle.disposed || gl.isContextLost() || performance.now() - started > 5000) {
              reject(new Error('Diagram GPU readback unavailable'));
              return;
            }
            const status = gl.clientWaitSync(fence, 0, 0);
            if (status === gl.WAIT_FAILED) {
              reject(new Error('Diagram GPU fence failed'));
              return;
            }
            if (status === gl.TIMEOUT_EXPIRED) {
              window.setTimeout(poll, 4);
              return;
            }
            resolve();
          };
          window.setTimeout(poll, 0);
        });
        const current = gl.getParameter(gl.PIXEL_PACK_BUFFER_BINDING);
        try {
          gl.bindBuffer(gl.PIXEL_PACK_BUFFER, buffer);
          gl.getBufferSubData(gl.PIXEL_PACK_BUFFER, 0, output);
        } finally {
          gl.bindBuffer(gl.PIXEL_PACK_BUFFER, current);
        }
      } finally {
        gl.deleteSync(fence);
        gl.deleteBuffer(buffer);
      }
    }
    function warmBuffers(draw) {
      // Pay the one-time full CAD buffer upload during model loading, not a tab flight.
      const objects = scene.children.map(object => [object, object.visible]),
        position = camera.position.clone(),
        quaternion = camera.quaternion.clone(),
        aspect = camera.aspect;
      const previousTarget = draw.getRenderTarget(),
        previousTone = draw.toneMapping,
        alpha = draw.getClearAlpha(),
        clear = draw.getClearColor(new THREE.Color());
      try {
        scene.children.forEach(object => {
          object.visible = object.isLight || object === attitude || object === globe;
        });
        camera.position.set(1.8, -2.8, 1.6).normalize().multiplyScalar(3.5);
        camera.lookAt(0, 0, 0);
        camera.aspect = 1;
        camera.updateProjectionMatrix();
        draw.toneMapping = THREE.NoToneMapping;
        draw.setRenderTarget(target);
        draw.setClearColor(0, 0);
        draw.render(scene, camera);
      } finally {
        objects.forEach(([object, visible]) => {
          object.visible = visible;
        });
        camera.position.copy(position);
        camera.quaternion.copy(quaternion);
        camera.aspect = aspect;
        camera.updateProjectionMatrix();
        draw.setRenderTarget(previousTarget);
        draw.setClearColor(clear, alpha);
        draw.toneMapping = previousTone;
      }
    }
    async function render() {
      pending = false;
      lastRender = performance.now();
      // Keep the last diagram image while the main camera flies, then draw the latest receipt.
      if (modelWarmup || window.missionCameraState?.().transitioning) {
        schedule();
        return;
      }
      if (document.hidden || window.cosmicExplorer?.enabled) return;
      if (rendering) {
        rerender = true;
        return;
      }
      rendering = true;
      try {
        const d = window.MissionDashboard?.latest;
        for (const canvas of document.querySelectorAll('.mission-page:not([hidden]) [data-globe]')) {
          const rect = canvas.getBoundingClientRect();
          if (!rect.width || !rect.height) continue;
          // Skip diagrams scrolled out of their rail to avoid wasted GPU work.
          const rail = canvas.closest('.mission-rail');
          const rr = rail?.getBoundingClientRect();
          if (rr && (rect.bottom < rr.top || rect.top > rr.bottom)) continue;
          const ratio = Math.min(devicePixelRatio || 1, document.body.dataset.quality === 'low' ? 1 : 1.25),
            w = Math.round(rect.width * ratio),
            h = Math.round(rect.height * ratio);
          const cached = rendered.get(canvas);
          if (cached?.data === d && cached.width === w && cached.height === h && cached.modelRevision === modelRevision && cached.textureReady === texture.image?.complete) continue;
          let staging = stagingCanvases.get(canvas);
          if (!staging) {
            staging = document.createElement('canvas');
            stagingCanvases.set(canvas, staging);
          }
          if (staging.width !== w || staging.height !== h) {
            staging.width = w;
            staging.height = h;
          }
          const ctx = staging.getContext('2d');
          ctx.clearRect(0, 0, w, h);
          const commit = () => {
            if (canvas.width !== w || canvas.height !== h) {
              canvas.width = w;
              canvas.height = h;
            }
            const visible = canvas.getContext('2d');
            visible.save();
            visible.setTransform(1, 0, 0, 1, 0, 0);
            visible.globalCompositeOperation = 'copy';
            visible.drawImage(staging, 0, 0);
            visible.restore();
            canvas.dataset.telemetrySequence = String(d?.telemetry_sequence ?? d?.timestamp ?? '');
            rendered.set(canvas, {
              data: d,
              width: w,
              height: h,
              modelRevision,
              textureReady: texture.image?.complete
            });
          };
          const sat = d ? position(d) : null;
          if (!sat) {
            ctx.fillStyle = '#a6bfd0';
            ctx.font = '12px system-ui';
            ctx.fillText('Awaiting position telemetry', 10, h / 2);
            commit();
            continue;
          }
          const kind = canvas.dataset.globe,
            isAttitude = kind === 'attitude' || kind === 'estimate';
          if (kind === 'sun') {
            ctx.save();
            ctx.scale(ratio, ratio);
            drawSunDiagram(ctx, rect.width, rect.height, d, sat);
            ctx.restore();
            commit();
            continue;
          }
          globe.visible = !isAttitude;
          satellite.visible = !isAttitude && kind !== 'system';
          attitude.visible = isAttitude;
          equator.visible = !isAttitude && kind !== 'system';
          satellite.position.copy(sat);
          sun.visible = false;
          moon.visible = false;
          sunArrow.visible = false;
          reconArrow.visible = false;
          const bodyFrame = frame(d, kind === 'estimate');
          if (isAttitude && !bodyFrame) {
            ctx.fillStyle = '#a6bfd0';
            ctx.font = '12px system-ui';
            ctx.fillText('Awaiting attitude frame', 10, h / 2);
            commit();
            continue;
          }
          if (bodyFrame) attitude.quaternion.setFromRotationMatrix(bodyFrame);
          const sunPos = valid(d.sun_position_ecef_m) ? new THREE.Vector3(...d.sun_position_ecef_m) : null;
          const sunDir = sunPos ? sunPos.clone().sub(sat.clone().multiplyScalar(R)).normalize() : [d.sun_ecef_x, d.sun_ecef_y, d.sun_ecef_z].every(x => typeof x === 'number' && finite(x)) ? new THREE.Vector3(d.sun_ecef_x, d.sun_ecef_y, d.sun_ecef_z).normalize() : null;
          if (sunDir) light.position.copy(sunDir).multiplyScalar(10);else light.position.set(0, 0, 0);
          updateOrbit(d);
          if (isAttitude || kind === 'system') orbit.visible = false;
          for (const child of [...gnss.children]) {
            gnss.remove(child);
            if (child.isLine) child.geometry.dispose();
          }
          if (kind === 'gps' && d.gps_links_available === true) {
            for (const sv of d.gps_satellites || []) {
              if (!valid(sv.position_ecef_m)) continue;
              const pos = new THREE.Vector3(...sv.position_ecef_m).divideScalar(R);
              const m = new THREE.Mesh(markerGeo, sv.used ? markerMat : hiddenMat);
              m.position.copy(pos);
              gnss.add(m);
              if (sv.used) {
                const g = new THREE.BufferGeometry().setFromPoints([sat, pos]);
                gnss.add(new THREE.Line(g, linkMat));
              }
            }
          }
          if (kind === 'system') {
            if (sunPos) {
              sun.visible = true;
              sun.position.copy(sunPos).normalize().multiplyScalar(2.4);
              sun.scale.setScalar(1);
            }
            if (valid(d.moon_position_ecef_m)) {
              moon.visible = true;
              moon.position.set(...d.moon_position_ecef_m).normalize().multiplyScalar(1.85);
            }
          }
          const focus = new THREE.Vector3();
          const distance = isAttitude ? 3.5 : kind === 'system' ? 5 : kind === 'sun' ? 5.8 : gnss.children.length ? d.gps_links_available === true ? 15 : 4.3 : 3.15;
          let view = sat.clone().normalize().multiplyScalar(distance).add(new THREE.Vector3(0, 0, .6));
          camera.position.copy(isAttitude ? new THREE.Vector3(1.8, -2.8, 1.6).normalize().multiplyScalar(distance) : view);
          camera.up.set(0, 0, 1);
          camera.lookAt(focus);
          camera.aspect = w / h;
          camera.fov = kind === 'sun' ? 48 : 38;
          camera.updateProjectionMatrix();
          camera.updateMatrixWorld();
          // Reuse the main context's uploaded CAD buffers rather than uploading
          // millions of triangles again in a second context on the first tab switch.
          const draw = window.renderer;
          if (draw) {
            if (target.width !== w || target.height !== h) {
              target.setSize(w, h);
              pixels = new Uint8Array(w * h * 4);
            }
            const previousTarget = draw.getRenderTarget(),
              previousTone = draw.toneMapping,
              previousAlpha = draw.getClearAlpha();
            draw.getClearColor(oldClear);
            let readback;
            try {
              draw.toneMapping = THREE.NoToneMapping;
              draw.setRenderTarget(target);
              draw.setClearColor(0, 0);
              draw.render(scene, camera);
              readback = readPixelsAsync(draw, w, h, pixels);
            } finally {
              draw.setRenderTarget(previousTarget);
              draw.setClearColor(oldClear, previousAlpha);
              draw.toneMapping = previousTone;
            }
            await readback;
            const image = ctx.createImageData(w, h),
              stride = w * 4;
            for (let row = 0; row < h; row++) image.data.set(pixels.subarray((h - 1 - row) * stride, (h - row) * stride), row * stride);
            ctx.putImageData(image, 0, 0);
          } else {
            renderer.setSize(w, h, false);
            renderer.render(scene, camera);
            ctx.drawImage(renderer.domElement, 0, 0, w, h);
          }
          ctx.save();
          ctx.scale(ratio, ratio);
          if (kind === 'gps' && d.gps_links_available !== true) drawGpsLinks(ctx, rect.width, rect.height, d, sat, canvas);
          if (!isAttitude && kind !== 'system' && kind !== 'gps') drawLabel(ctx, 'SAT', sat, rect.width, rect.height);
          if (sun.visible) drawLabel(ctx, 'Sun', sun.position, rect.width, rect.height, '#ffda6d');
          if (moon.visible) drawLabel(ctx, 'Moon', moon.position, rect.width, rect.height);
          if (isAttitude) for (const [axis, label, color] of [[[1.44, 0, 0], '+X', '#ff797d'], [[0, 1.44, 0], '+Y', '#4de2a5'], [[0, 0, 1.44], '+Z', '#67b9ff']]) drawAxisLabel(ctx, label, new THREE.Vector3(...axis).applyQuaternion(attitude.quaternion), rect.width, rect.height, color);
          if (kind === 'gps' && d.gps_links_available === true) for (const sv of d.gps_satellites || []) if (valid(sv.position_ecef_m)) drawLabel(ctx, String(sv.prn ?? sv.id ?? ''), new THREE.Vector3(...sv.position_ecef_m).divideScalar(R), rect.width, rect.height);
          ctx.restore();
          commit();
        }
      } finally {
        rendering = false;
        if (rerender) {
          rerender = false;
          schedule();
        }
      }
    }
    listen(window, 'dashboard-render', schedule);
    listen(window, 'dashboard-tab', schedule);
    listen(window, 'resize', schedule);
    listen(document, 'scroll', schedule, true);
    listen(document, 'visibilitychange', () => {
      if (!document.hidden) schedule();
    });
    listen(window, 'pagehide', () => {
      clearTimeout(timer);
      renderer.dispose();
    });
    schedule();
  } else {
    for (const c of document.querySelectorAll('[data-globe]')) c.parentElement.append(document.createTextNode('3D context unavailable'));
  }
  return () => {
    lifecycle.dispose();
    releaseTarget();
    renderer?.dispose();
    renderer?.forceContextLoss();
  };
}
