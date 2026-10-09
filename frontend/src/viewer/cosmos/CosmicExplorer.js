/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { MEDIA } from '../../assets/assetUrls.js';
/* The user's footage drives the distant Overview shot. The close Earth
 * remains live 3D; the handoff occurs after its apparent diameter is subpixel. */
import * as THREE from 'three';
import { createLifecycle } from '../../services/lifecycle.js';
import { createReferenceStarfield } from './referenceStarfield.js';
import { referenceLog, referenceSeconds, SUN_TRACK, GALAXY_TRACK } from './referenceCalibration.js';
const clamp = THREE.MathUtils.clamp,
  smooth = THREE.MathUtils.smoothstep;
const sample = (track, t) => {
  let i = 0;
  while (i < track.length - 2 && t > track[i + 1][0]) i++;
  const a = track[i],
    b = track[i + 1],
    f = clamp((t - a[0]) / (b[0] - a[0]), 0, 1);
  return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
};
export class CosmicExplorer {
  constructor(renderer) {
    this.lifecycle = createLifecycle();
    const {
      listen
    } = this.lifecycle;
    this.renderer = renderer;
    this.enabled = false;
    this.built = false;
    this.ready = false;
    this.log = this.target = Math.log10(2.1e7);
    this.distance = 2.1e7;
    this.referenceTime = this.targetTime = referenceSeconds(this.log);
    this.time = this.visualDays = 0;
    this.labels = document.createElement('canvas');
    this.labels.className = 'cosmic-labels';
    this.labels.hidden = true;
    this.labels.setAttribute('aria-label', 'Celestial names and scale');
    document.body.append(this.labels);
    this.ctx = this.labels.getContext('2d');
    this.video = document.createElement('video');
    this.video.src = MEDIA.overviewReference;
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.preload = 'metadata';
    this.video.setAttribute('aria-hidden', 'true');
    this.videoTexture = new THREE.VideoTexture(this.video);
    this.videoTexture.colorSpace = THREE.SRGBColorSpace;
    this.videoTexture.generateMipmaps = false;
    this.videoTexture.minFilter = this.videoTexture.magFilter = THREE.LinearFilter;
    listen(this.video, 'seeked', () => {
      this.presentedTime = this.video.currentTime;
    });
    if (this.video.requestVideoFrameCallback) {
      const shown = (_, meta) => {
        this.presentedTime = meta.mediaTime;
        this.videoFrameId = this.video.requestVideoFrameCallback(shown);
      };
      this.videoFrameId = this.video.requestVideoFrameCallback(shown);
    }
    this.lastSeek = -Infinity;
    this.referenceSky = createReferenceStarfield();
    this.skyAligned = false;
    listen(this.video, 'error', () => console.warn('Overview reference video could not load:', this.video.error?.message));
    this.backgroundMaterial = new THREE.ShaderMaterial({
      uniforms: {
        footage: {
          value: this.videoTexture
        },
        blend: {
          value: 0
        },
        crop: {
          value: new THREE.Vector2(1, 1)
        }
      },
      vertexShader: 'varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,1.,1.);}',
      fragmentShader: `varying vec2 vUv;uniform sampler2D footage;uniform float blend;uniform vec2 crop;
    vec4 sharpFrame(vec2 uv){
      vec2 size=vec2(3840.,1664.),p=uv*size,base=floor(p-.5)+.5,f=p-base;
      vec2 w0=f*(-.5+f*(1.-.5*f)),w1=1.+f*f*(-2.5+1.5*f),w2=f*(.5+f*(2.-1.5*f)),w3=f*f*(-.5+.5*f),w12=w1+w2;
      vec2 a=(base-1.)/size,b=(base+w2/w12)/size,c=(base+2.)/size;
      vec4 color=texture2D(footage,vec2(a.x,a.y))*w0.x*w0.y;
      color+=texture2D(footage,vec2(b.x,a.y))*w12.x*w0.y;
      color+=texture2D(footage,vec2(c.x,a.y))*w3.x*w0.y;
      color+=texture2D(footage,vec2(a.x,b.y))*w0.x*w12.y;
      color+=texture2D(footage,b)*w12.x*w12.y;
      color+=texture2D(footage,vec2(c.x,b.y))*w3.x*w12.y;
      color+=texture2D(footage,vec2(a.x,c.y))*w0.x*w3.y;
      color+=texture2D(footage,vec2(b.x,c.y))*w12.x*w3.y;
      color+=texture2D(footage,c)*w3.x*w3.y;return clamp(color,0.,1.);
    }
    void main(){vec2 uv=(vUv-.5)*crop+.5;vec4 frame=sharpFrame(uv);frame.rgb=mix(frame.rgb/12.92,pow((frame.rgb+.055)/1.055,vec3(2.4)),step(vec3(.04045),frame.rgb));gl_FragColor=vec4(frame.rgb,blend);
    #include <colorspace_fragment>
    }`,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      toneMapped: false
    });
    this.background = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.backgroundMaterial);
    this.background.frustumCulled = false;
    this.background.renderOrder = 10000;
    this.background.visible = false;
    this.departure = this.background.clone();
    this.departure.material = this.backgroundMaterial.clone();
    this.departure.material.uniforms.footage.value = this.videoTexture;
    this.departure.visible = false;
    this.size = new THREE.Vector2();
    this.frame = new THREE.Quaternion();
    this.inverse = new THREE.Quaternion();
    this.tmp = new THREE.Vector3();
    this.point = new THREE.Vector3();
    this.matrix = new THREE.Matrix4();
    this.rotation = new THREE.Matrix3();
    this.eciFrame = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -(90 + 23.43928) * Math.PI / 180);
    this.turn = new THREE.Quaternion();
    this.turnTarget = new THREE.Quaternion();
    listen(window, 'dashboard-tab', e => {
      if (e.detail !== 'overview') this.exit();
    });
    listen(window, 'spacecraft-model-ready', () => this.build());
    window.cosmicExplorer = this;
  }
  dispose() {
    this.lifecycle.dispose();
    window.gsap?.killTweensOf(this);
    window.gsap?.killTweensOf(this.departure.material.uniforms.blend);
    if (this.videoFrameId !== undefined) this.video.cancelVideoFrameCallback?.(this.videoFrameId);
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.load();
    this.labels.remove();
    this.videoTexture.dispose();
    this.background.geometry.dispose();
    this.backgroundMaterial.dispose();
    this.departure.material.dispose();
    delete window.cosmicExplorer;
  }
  updateZoom(dt) {
    this.log = referenceLog(this.referenceTime);
    this.distance = 10 ** this.log;
    this.updateFrame();
    return this.distance;
  }
  zoom(delta) {
    this.targetTime = clamp(this.targetTime + clamp(delta, -300, 300) * .012, 58, 250);
    this.target = referenceLog(this.targetTime);
    // One short scrub tween, replaced by every input; no playback or velocity queue.
    if (window.gsap) window.gsap.to(this, {
      referenceTime: this.targetTime,
      duration: .18,
      ease: 'power1.out',
      overwrite: true
    });else this.referenceTime = this.targetTime;
  }
  cameraOrbit(radial, up) {
    const f = smooth(this.referenceTime, 88, 96);
    if (!f || !this.nativeAssets) return;
    // End on the sunward side of Earth: the camera looks away from the Sun.
    this.turnTarget.setFromUnitVectors(radial, this.nativeAssets.earth.material.uniforms.sunDir.value);
    const angle = 2 * Math.acos(Math.min(1, Math.abs(this.turnTarget.w)));
    const requiredTurn = Math.max(0, angle - Math.PI / 2);
    this.turn.identity().slerp(this.turnTarget, angle > 1e-6 ? f * requiredTurn / angle : 0);
    radial.applyQuaternion(this.turn);
    up.applyQuaternion(this.turn);
  }
  setDistance(m) {
    window.gsap?.killTweensOf(this);
    this.log = this.target = Math.log10(clamp(m, 8e6, 2e27));
    this.referenceTime = this.targetTime = referenceSeconds(this.log);
    this.distance = 10 ** this.log;
    this.forceSeek = true;
    this.updateFrame();
  }
  updateFrame() {
    const aspect = window.innerWidth / window.innerHeight,
      source = 3840 / 1664;
    this.backgroundMaterial.uniforms.crop.value.set(Math.min(1, aspect / source), Math.min(1, source / aspect));
    const target = clamp(this.referenceTime - 95, 0, 154.8);
    this.desiredVideoTime = target;
    this.video.pause();
    const now = performance.now();
    if (this.video.readyState >= 2 && !this.video.seeking && Math.abs(this.video.currentTime - target) > 1 / 30 && (this.forceSeek || now - this.lastSeek >= 33)) {
      this.video.currentTime = target;
      this.lastSeek = now;
      this.forceSeek = false;
    }
    // Seeking can temporarily reduce readyState even though a valid frame remains
    // on the GPU. Keep that frame and its fade; never flash back to the 3D sky.
    if (this.video.readyState >= 2) this.hasVideoFrame = true;
    this.backgroundMaterial.uniforms.blend.value = this.hasVideoFrame ? smooth(this.referenceTime, 98, 100) : 0;
  }
  exit(cancel = true) {
    this.lastRenderedFrame = null;
    if (cancel) {
      window.gsap?.killTweensOf(this);
      this.targetTime = this.referenceTime;
      if (this.backgroundMaterial.uniforms.blend.value > 0 && window.gsap) {
        this.departure.material.uniforms.crop.value.copy(this.backgroundMaterial.uniforms.crop.value);
        this.departure.material.uniforms.blend.value = this.backgroundMaterial.uniforms.blend.value;
        this.departure.visible = true;
        window.gsap.to(this.departure.material.uniforms.blend, {
          value: 0,
          duration: .4,
          ease: 'power1.out',
          overwrite: true,
          onComplete: () => {
            this.departure.visible = false;
          }
        });
      }
    }
    this.background.visible = false;
    this.enabled = false;
    this.labels.hidden = true;
    this.video.pause();
    document.body.classList.remove('cosmic-range', 'cosmic-cinema', 'overview-scale-visible');
  }
  updateSkyMix(overview) {
    const f = overview ? smooth(this.referenceTime, 88, 96) : 0;
    this.skyBlend = f;
    for (const star of this.nativeAssets?.stars || []) {
      if (star.userData.overviewBaseOpacity === undefined) star.userData.overviewBaseOpacity = star.material.opacity;
      star.material.opacity = star.userData.overviewBaseOpacity * (1 - f);
      star.visible = f < 1;
    }
    this.referenceSky.visible = overview && f > 0;
    this.referenceSky.userData.fade.value = f;
  }
  build() {
    if (this.built || !this.nativeAssets) return;
    this.built = true;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1e-6, 1000);
    this.overlay = this.background.clone();
    this.overlay.visible = false;
    this.scene.add(this.overlay);
    this.sky = this.referenceSky.clone();
    this.sky.scale.setScalar(1);
    this.scene.add(this.sky);
    this.earth = new THREE.Group();
    this.scene.add(this.earth);
    this.clones = [];
    for (const source of [this.nativeAssets.earth, this.nativeAssets.atmosphere, ...this.nativeAssets.clouds, this.nativeAssets.aurora]) {
      if (!source) continue;
      const clone = source.clone();
      clone.position.set(0, 0, 0);
      clone.material = source.material.clone();
      if (clone.material.isShaderMaterial) clone.material.vertexShader = clone.material.vertexShader.replaceAll('normalize(normal)', 'normalize(mat3(modelMatrix)*normal)').replaceAll('vP = wp.xyz;', 'vP = wp.xyz-cameraPosition;');
      this.earth.add(clone);
      this.clones.push({
        source,
        clone
      });
    }
    if (this.nativeAssets.orbit) {
      this.orbit = this.nativeAssets.orbit.clone();
      this.orbit.position.set(0, 0, 0);
      this.orbit.material = this.nativeAssets.orbit.material.clone();
      this.orbitBaseOpacity = this.orbit.material.opacity;
      this.earth.add(this.orbit);
    }
    const texture = new THREE.TextureLoader().load('/assets/textures/moon.jpg');
    texture.colorSpace = THREE.SRGBColorSpace;
    this.moon = new THREE.Mesh(new THREE.SphereGeometry(1737400, 48, 24), new THREE.MeshStandardMaterial({
      map: texture,
      roughness: 1
    }));
    this.scene.add(this.moon);
    this.scene.add(new THREE.AmbientLight(0xffffff, .16));
    this.hemisphere = new THREE.HemisphereLight(0x30405a, 0x090909, .20);
    this.scene.add(this.hemisphere);
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    this.light = new THREE.DirectionalLight(0xffffff, 2.8);
    this.scene.add(this.light);
    this.ready = true;
    if (this.nativeAssets.sun) {
      this.sun = this.nativeAssets.sun.clone();
      this.sun.material = this.nativeAssets.sun.material.clone();
      this.sun.name = 'overview-sun';
      this.scene.add(this.sun);
    }
    this.nativeSkyClones = (this.nativeAssets.stars || []).map(source => {
      const clone = source.clone();
      clone.scale.multiplyScalar(1e-6);
      clone.renderOrder = source.isPoints ? -1100 : -1200;
      this.scene.add(clone);
      return {
        source,
        clone
      };
    });
    this.renderer.compileAsync?.(this.scene, this.camera).catch(error => console.warn('Overview shader warmup:', error));
  }
  render(dt, now, state) {
    if (state.quaternion && (!this.skyAligned || state.transitioning)) {
      this.referenceSky.quaternion.copy(state.quaternion);
      this.skyAligned = true;
    }
    if (!this.skyHome || state.transitioning) this.skyHome = this.referenceSky.quaternion.clone();
    if (state.quaternion) this.referenceSky.quaternion.slerpQuaternions(this.skyHome, state.quaternion, smooth(this.referenceTime, 88, 96));
    this.background.visible = this.referenceTime >= 98;
    this.departure.visible = false;
    this.updateSkyMix(true);
    if (this.distance <= 2e8) {
      if (this.enabled) this.exit(false);
      this.background.visible = false;
      return false;
    }
    this.build();
    if (!this.ready) return false;
    this.enabled = true;
    this.labels.hidden = false;
    document.body.classList.add('cosmic-range');
    document.body.classList.toggle('overview-scale-visible', this.referenceTime >= 93);
    this.time += dt;
    this.visualDays += dt * .03;
    const w = window.innerWidth,
      h = window.innerHeight,
      D = this.distance,
      t = this.referenceTime;
    if (this.size.x !== w || this.size.y !== h) {
      this.size.set(w, h);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      const dpr = Math.min(devicePixelRatio, 2);
      this.labels.width = Math.round(w * dpr);
      this.labels.height = Math.round(h * dpr);
    }
    const data = window.MissionDashboard?.latest,
      rotation = data?.eci_to_ecef_matrix;
    if (Array.isArray(rotation)) this.rotation.set(...rotation[0], ...rotation[1], ...rotation[2]).transpose();else this.rotation.identity();
    this.frame.setFromRotationMatrix(this.matrix.setFromMatrix3(this.rotation)).premultiply(this.eciFrame);
    this.camera.position.copy(state.position).multiplyScalar(1 / D).applyQuaternion(this.frame);
    this.camera.up.copy(state.up).applyQuaternion(this.frame);
    this.camera.quaternion.copy(state.quaternion).premultiply(this.frame);
    this.camera.updateMatrixWorld();
    for (const {
      source,
      clone
    } of this.nativeSkyClones) {
      clone.visible = source.visible && this.backgroundMaterial.uniforms.blend.value < .999999;
      clone.position.copy(this.camera.position);
      clone.quaternion.copy(source.quaternion).premultiply(this.frame);
    }
    const covered = this.backgroundMaterial.uniforms.blend.value >= .999999;
    this.overlay.visible = this.background.visible;
    this.sky.visible = this.referenceSky.visible && !covered;
    this.sky.position.copy(this.camera.position);
    this.sky.quaternion.copy(this.referenceSky.quaternion).premultiply(this.frame);
    if (this.sun) {
      this.tmp.copy(this.nativeAssets.earth.material.uniforms.sunDir.value).applyQuaternion(this.frame);
      this.sun.position.copy(this.camera.position).addScaledVector(this.tmp, 60);
      this.sun.scale.copy(this.nativeAssets.sun.scale).multiplyScalar(60 / this.nativeAssets.sunDistance);
      this.sun.visible = this.nativeAssets.sun.visible && !covered;
    }
    // Match the measured footage globe centre and angular radius before fading.
    const join = smooth(t, 88, 98),
      crop = this.backgroundMaterial.uniforms.crop.value;
    const x = (.487109375 - .5) / crop.x * 2,
      y = (.5 - .501502404) / crop.y * 2;
    this.tmp.set(x * Math.tan(Math.PI / 6) * this.camera.aspect, y * Math.tan(Math.PI / 6), 0).applyQuaternion(this.camera.quaternion);
    this.earth.position.copy(this.tmp).multiplyScalar(join);
    const pixelRadius = 12.5 * Math.exp(-.18 * Math.max(0, t - 95));
    const matchedScale = pixelRadius / 1664 / crop.y * 2 * Math.tan(Math.PI / 6) / 6371000;
    this.earth.scale.setScalar(THREE.MathUtils.lerp(1 / D, matchedScale, join));
    this.earth.quaternion.copy(this.frame);
    this.earth.visible = !covered;
    if (this.orbit) {
      this.orbit.geometry = this.nativeAssets.orbit.geometry;
      this.orbit.visible = !covered;
      this.orbit.material.opacity = this.orbitBaseOpacity * (1 - this.backgroundMaterial.uniforms.blend.value);
    }
    this.clones.forEach(({
      source,
      clone
    }) => {
      clone.quaternion.copy(source.quaternion);
      clone.visible = source.visible;
      const src = source.material,
        dst = clone.material;
      if (src.uniforms) {
        for (const key of Object.keys(src.uniforms)) {
          const v = src.uniforms[key].value;
          if (v?.isTexture) dst.uniforms[key].value = v;else if (key === 'sunDir') dst.uniforms[key].value.copy(v).applyQuaternion(this.frame);else if (typeof v === 'number') dst.uniforms[key].value = v;
        }
      } else {
        dst.opacity = src.opacity;
        if (dst.map !== src.map || dst.alphaMap !== src.alphaMap) {
          dst.map = src.map;
          dst.alphaMap = src.alphaMap;
          dst.needsUpdate = true;
        }
      }
    });
    const moon = data?.moon_position_ecef_m;
    if (Array.isArray(moon)) this.tmp.set(...moon);else {
      const phase = this.time * .0000027;
      this.tmp.set(Math.cos(phase) * 3844e5, 0, Math.sin(phase) * 3844e5);
    }
    this.moon.position.copy(this.tmp).multiplyScalar(1 / D).applyQuaternion(this.frame);
    this.moon.scale.setScalar(1 / D);
    this.moon.visible = t < 95;
    this.light.position.copy(this.nativeAssets.earth.material.uniforms.sunDir.value).applyQuaternion(this.frame);
    this.light.intensity = this.nativeAssets.sunlight.intensity;
    this.hemisphere.position.set(0, 1, 0).applyQuaternion(this.frame);
    const cuts = [95, 139, 148, 174, 188, 217],
      stages = ['Earth and local space', 'Solar system', 'Heliosphere', 'Stellar neighbourhood', 'Milky Way', 'Nearby galaxies', 'Deep universe'];
    this.stage = stages[cuts.filter(c => t >= c).length];
    if (t > 145 && !document.body.classList.contains('cosmic-cinema')) window.setSettingsOpen?.(false);
    document.body.classList.toggle('cosmic-cinema', t > 145);
    this.publishScale(now, this.backgroundMaterial.uniforms.blend.value > 0 ? D : 1 / this.earth.scale.x, this.camera.fov, this.backgroundMaterial.uniforms.blend.value > 0);
    const renderedFrame = this.presentedTime ?? this.video.currentTime;
    const renderKey = `${this.renderer.domElement.width}:${this.renderer.domElement.height}:${renderedFrame}`;
    if (!covered || this.lastRenderedFrame !== renderKey || this.wasCovered !== covered) {
      this.renderer.render(this.scene, this.camera);
      this.lastRenderedFrame = renderKey;
    }
    this.wasCovered = covered;
    if (!this.lastLabelDraw || now - this.lastLabelDraw >= 50) {
      this.drawLabels(w, h, D, t);
      this.lastLabelDraw = now;
    }
    return true;
  }
  publishScale(now, distance, fov, approximate = false) {
    if (this.lastScaleUpdate && now - this.lastScaleUpdate < 100) return;
    this.lastScaleUpdate = now;
    const metersPerPixel = 2 * distance * Math.tan(fov * Math.PI / 360) / window.innerHeight;
    window.dispatchEvent(new CustomEvent('overview-scale', {detail: {metersPerPixel, approximate}}));
  }
  drawLabels(w, h, D, t) {
    const ctx = this.ctx,
      dpr = Math.min(devicePixelRatio, 2);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.font = '12px system-ui';
    ctx.fillStyle = '#e2e7ee';
    ctx.shadowColor = '#000';
    ctx.shadowBlur = 5;
    const occupied = [];
    this.drawnLabels = [];
    const label = (name, x, y, detail = '') => {
      if (x < 12 || x > w - 12 || y < 40 || y > h - 50) return;
      const width = Math.max(ctx.measureText(name).width, ctx.measureText(detail).width) + 18,
        height = detail ? 42 : 27;
      const candidates = [[x + 16, y - 18], [x + 16, y + 16], [x - width - 16, y - 18], [x - width - 16, y + 16], [x + 25, y - 75], [x - width - 25, y - 75], [x + 25, y + 65], [x - width - 25, y + 65]];
      const box = candidates.find(([bx, by]) => bx >= 12 && bx + width <= w - 12 && by >= 24 && by + height < h - 48 && !occupied.some(b => bx < b[0] + b[2] + 6 && bx + width > b[0] - 6 && by < b[1] + b[3] + 6 && by + height > b[1] - 6));
      if (!box) return;
      const [bx, by] = box;
      occupied.push([bx, by, width, height]);
      this.drawnLabels.push(name);
      ctx.shadowBlur = 0;
      ctx.fillStyle = 'rgba(3,8,15,.72)';
      ctx.fillRect(bx, by, width, height);
      ctx.strokeStyle = 'rgba(180,205,230,.6)';
      ctx.lineWidth = .8;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(bx > x ? bx : bx + width, by + height / 2);
      ctx.stroke();
      ctx.fillStyle = '#e7eff9';
      ctx.beginPath();
      ctx.arc(x, y, 1.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillText(name, bx + 9, by + 17);
      if (detail) {
        ctx.fillStyle = '#a7b8cd';
        ctx.font = '11px system-ui';
        ctx.fillText(detail, bx + 9, by + 33);
        ctx.font = '12px system-ui';
      }
    };
    const objectLabel = (name, object, detail) => {
      object.getWorldPosition(this.point);
      this.point.project(this.camera);
      if (this.point.z > -1 && this.point.z < 1) label(name, (this.point.x + 1) * w / 2, (1 - this.point.y) * h / 2, detail);
    };

    const blend = this.backgroundMaterial.uniforms.blend.value;
    if (blend < .5 && t < 99 && this.sun?.visible) objectLabel('Sun', this.sun, 'Our star');
    const shownTime = 95 + (this.presentedTime ?? this.video.currentTime);
    const footageLabel = (name, track, detail) => {
      const [x, y] = sample(track, shownTime),
        crop = this.backgroundMaterial.uniforms.crop.value;
      label(name, ((x - .5) / crop.x + .5) * w, ((y - .5) / crop.y + .5) * h, detail);
    };
    if (blend >= .5 && shownTime >= 116.4 && shownTime < 140) footageLabel('Sun', SUN_TRACK, 'Centre of the Solar System');
    if (shownTime >= 177.2 && shownTime <= 200.8) footageLabel('Milky Way', GALAXY_TRACK, 'Our barred spiral galaxy');
    if (shownTime >= 142 && shownTime < 159) {
      const crop = this.backgroundMaterial.uniforms.crop.value;
      label('Interstellar cloud', ((.82 - .5) / crop.x + .5) * w, ((.18 - .5) / crop.y + .5) * h, 'Gas and dust between the stars');
    }
    if (shownTime >= 180 && shownTime < 184) {
      const [x, y] = sample(GALAXY_TRACK, shownTime),
        f = (shownTime - 180) / 4,
        crop = this.backgroundMaterial.uniforms.crop.value;
      label('Spiral arms', ((x + .22 - f * .12 - .5) / crop.x + .5) * w, ((y + .1 - f * .055 - .5) / crop.y + .5) * h, 'Stars, gas and dark dust lanes');
    }
    const descriptions = ['Earth and our local sky', 'Our star and its surrounding space', 'The region shaped by the solar wind', 'Stars and interstellar dust', 'The galaxy that contains our Solar System', 'Galaxies beyond the Milky Way', 'The distant galaxy field'];
    const index = ['Earth and local space', 'Solar system', 'Heliosphere', 'Stellar neighbourhood', 'Milky Way', 'Nearby galaxies', 'Deep universe'].indexOf(this.stage);
    ctx.shadowColor = '#000';
    ctx.shadowBlur = 6;
    ctx.font = '600 15px system-ui';
    ctx.fillStyle = '#e7eff9';
    ctx.fillText(this.stage, 24, h - 44);
    ctx.font = '11px system-ui';
    ctx.fillStyle = '#abb8c9';
    ctx.fillText(descriptions[index] || '', 24, h - 25);
  }
}
