/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';
const DEG = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sstep = (e0, e1, x) => {
  const t = clamp((x - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};
const WGS84_A = 6378137.0;
const WGS84_E2 = 0.00669437999014;
const EARTH_R_MEAN = 6371000.0;
const EARTH_CIRC = 40075016.686;
function latLonToECEF(latDeg, lonDeg, h, out = new THREE.Vector3()) {
  const lat = latDeg * DEG,
    lon = lonDeg * DEG;
  const sl = Math.sin(lat),
    cl = Math.cos(lat);
  const N = WGS84_A / Math.sqrt(1 - WGS84_E2 * sl * sl);
  return out.set((N + h) * cl * Math.cos(lon), (N + h) * cl * Math.sin(lon), (N * (1 - WGS84_E2) + h) * sl);
}
const orbitalFrom = new THREE.Vector3(), orbitalTo = new THREE.Vector3();
const orbitalTurn = new THREE.Quaternion(), orbitalStep = new THREE.Quaternion();
function interpolateOrbitalPosition(position, target, blend) {
  const fromRadius = position.length(), toRadius = target.length();
  if (!Number.isFinite(fromRadius) || !Number.isFinite(toRadius) || fromRadius <= 0 || toRadius <= 0) return position;
  const amount = clamp(blend, 0, 1);
  orbitalFrom.copy(position).divideScalar(fromRadius);
  orbitalTo.copy(target).divideScalar(toRadius);
  orbitalTurn.setFromUnitVectors(orbitalFrom, orbitalTo);
  orbitalStep.identity().slerp(orbitalTurn, amount);
  return position.copy(orbitalFrom).applyQuaternion(orbitalStep).multiplyScalar(fromRadius + (toRadius - fromRadius) * amount);
}
function tile2lat(y, z) {
  const n = Math.PI - 2 * Math.PI * y / (1 << z);
  return Math.atan(Math.sinh(n)) / DEG;
}
function lat2tileY(latDeg, z) {
  const c = clamp(latDeg, -85.05112878, 85.05112878) * DEG;
  const y = 0.5 - Math.log(Math.tan(c) + 1 / Math.cos(c)) / (2 * Math.PI);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
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
function wrap180(d) {
  d %= 360;
  if (d > 180) d -= 360;else if (d < -180) d += 360;
  return d;
}
function parseUTCDate(ts) {
  if (!ts || typeof ts !== 'string') return null;
  let iso = ts.trim();
  if (iso.includes(' ') && !iso.includes('T')) iso = iso.replace(' ', 'T') + 'Z';
  if (iso.includes('+') && iso.endsWith('Z')) iso = iso.slice(0, -1);
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}
export { DEG, clamp, sstep, WGS84_A, WGS84_E2, EARTH_R_MEAN, EARTH_CIRC, latLonToECEF, interpolateOrbitalPosition, tile2lat, lat2tileY, raySphereHit, wrap180, parseUTCDate };
