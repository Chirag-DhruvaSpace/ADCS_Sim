/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';
export function createSpaceBackground({
  CONFIG,
  scene
}) {
  const starAnchors = [];
  const starMats = [];
  function makeStarTexture() {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0.00, 'rgba(255,255,255,1)');
    grad.addColorStop(0.28, 'rgba(255,255,255,0.75)');
    grad.addColorStop(0.60, 'rgba(255,255,255,0.18)');
    grad.addColorStop(1.00, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  }
  const starTex = makeStarTexture();
  const STAR_BAND_N = new THREE.Vector3(0.3, 0.9, 0.2).normalize();
  function makeStarLayer(count, size, bandFraction) {
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const v = new THREE.Vector3();
    for (let i = 0; i < count; i++) {
      const z = Math.random() * 2 - 1,
        phi = Math.random() * Math.PI * 2;
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
      let r = 1,
        g = 1,
        bl = 1;
      if (t < 0.20) {
        r = 0.70;
        g = 0.81;
        bl = 1.00;
      } else if (t < 0.32) {
        r = 1.00;
        g = 0.83;
        bl = 0.66;
      } else if (t < 0.40) {
        r = 1.00;
        g = 0.93;
        bl = 0.86;
      }
      col.set([r * b, g * b, bl * b], i * 3);
    }
    const g2 = new THREE.BufferGeometry();
    g2.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g2.setAttribute('color', new THREE.BufferAttribute(col, 3));
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    const mat = new THREE.PointsMaterial({
      map: starTex,
      size,
      sizeAttenuation: false,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    const p = new THREE.Points(g2, mat);
    p.frustumCulled = false;
    scene.add(p);
    starAnchors.push(p);
    starMats.push(mat);
  }
  makeStarLayer(700, 0.8, 0.25); // restrained points over the photographic sky
  makeStarLayer(220, 1.2, 0.25);
  makeStarLayer(40, 1.9, 0.25);

  /* Milky-way haze band */
  let hazeMat, hazeSphere;
  {
    const c = document.createElement('canvas');
    c.width = 1024;
    c.height = 512;
    const g = c.getContext('2d');
    const gauss = () => {
      let s = 0;
      for (let i = 0; i < 4; i++) s += Math.random();
      return (s - 2) / 2;
    };
    for (let i = 0; i < 3600; i++) {
      const x = Math.random() * 1024;
      const y = 256 + gauss() * 46;
      const r = 0.6 + Math.random() * 2.6;
      const a = 0.014 + Math.random() * 0.05;
      const warm = Math.random() < 0.3;
      g.fillStyle = warm ? `rgba(255,236,205,${a})` : `rgba(198,214,255,${a})`;
      g.beginPath();
      g.arc(x, y, r, 0, Math.PI * 2);
      g.fill();
    }
    for (let i = 0; i < 30; i++) {
      const x = Math.random() * 1024,
        y = 256 + gauss() * 30;
      const r = 6 + Math.random() * 16;
      g.fillStyle = 'rgba(210,225,255,0.05)';
      g.beginPath();
      g.arc(x, y, r, 0, Math.PI * 2);
      g.fill();
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    hazeMat = new THREE.MeshBasicMaterial({
      map: t,
      side: THREE.BackSide,
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false
    });
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(CONFIG.HAZE_RADIUS, 48, 24), hazeMat);
    hazeSphere = sphere;
    sphere.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), STAR_BAND_N);
    sphere.frustumCulled = false;
    scene.add(sphere);
    starAnchors.push(sphere);
  }
  return {
    starAnchors,
    starMats,
    makeStarTexture,
    starTex,
    STAR_BAND_N,
    makeStarLayer,
    hazeMat,
    hazeSphere
  };
}
