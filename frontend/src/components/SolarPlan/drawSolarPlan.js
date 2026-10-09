/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { finite } from '../../services/dashboardData.js';
export function drawSolarPlan(c, d) {
  if (document.body.classList.contains('cosmic-range')) return;
  const rect = c.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(devicePixelRatio || 1, 2),
    w = rect.width,
    h = rect.height;
  c.width = Math.round(w * ratio);
  c.height = Math.round(h * ratio);
  const ctx = c.getContext('2d');
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, w, h);
  const sunAt = [w * .13, h * .5],
    earth = [w * .52, h * .5],
    moonAt = [w * .86, h * .5],
    satOrbit = h * .28;
  const sat = Array.isArray(d.satellite_position_ecef_m) ? d.satellite_position_ecef_m : null;
  const ms = Date.parse(d.timestamp),
    jd = Number.isFinite(ms) ? ms / 86400000 + 2440587.5 : null;
  const T = jd == null ? 0 : (jd - 2451545) / 36525;
  const gmst = jd == null ? 0 : (280.46061837 + 360.98564736629 * (jd - 2451545) + .000387933 * T * T) * Math.PI / 180;
  ctx.lineWidth = 1;
  ctx.strokeStyle = '#bcdaf474';
  ctx.setLineDash([4, 5]);
  ctx.beginPath();
  ctx.moveTo(sunAt[0] + 14, sunAt[1]);
  ctx.lineTo(earth[0] - satOrbit - 5, earth[1]);
  ctx.stroke();
  ctx.beginPath();
  ctx.ellipse(earth[0], earth[1], moonAt[0] - earth[0], h * .22, 0, 0, Math.PI * 2);
  ctx.stroke();
  ctx.strokeStyle = '#50c7ffba';
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  ctx.beginPath();
  ctx.arc(earth[0], earth[1], satOrbit, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  const body = (x, y, r, color, label) => {
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = r * 2;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#eef7ff';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(label, x, Math.max(12, y - r - 8));
  };
  body(...sunAt, 9, '#ffd261', 'Sun');
  body(...earth, 12, '#4ba7ff', 'Earth');
  const moonVector = Array.isArray(d.moon_position_ecef_m) && d.moon_position_ecef_m.every(finite) ? d.moon_position_ecef_m : null;
  const moonPhase = moonVector ? Math.atan2(moonVector[1], moonVector[0]) + gmst : jd == null ? 0 : 2 * Math.PI * ((jd - 2451545.0) / 27.321661);
  const moon = [earth[0] + Math.cos(moonPhase) * (moonAt[0] - earth[0]), earth[1] - Math.sin(moonPhase) * h * .22];
  body(...moon, 7, '#e9eef2', 'Moon');
  if (Array.isArray(sat) && sat.length === 3 && sat.every(finite)) {
    const a = Math.atan2(sat[1], sat[0]) + gmst;
    body(earth[0] + Math.cos(a) * satOrbit, earth[1] - Math.sin(a) * satOrbit, 4, '#49d9ff', 'SAT');
  }
  ctx.shadowBlur = 0;
  ctx.fillStyle = '#8faec4';
  ctx.font = '10px system-ui';
  ctx.textAlign = 'right';
  ctx.fillText('schematic · not to scale', w - 4, h - 4);
}
