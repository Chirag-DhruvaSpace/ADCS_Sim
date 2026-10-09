/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { finite } from '../../services/dashboardData.js';
export const chartDefs = {
  wheels: ['reactionWheels', ['RW 1', 'RW 2', 'RW 3', 'RW 4']],
  torquers: ['magnetorquers', ['X', 'Y', 'Z']],
  gyro: ['gyroError', ['X', 'Y', 'Z']],
  mag: ['magError', ['X', 'Y', 'Z']],
  pointing: ['pointing', ['Axis error', 'Δ yaw', 'Δ pitch', 'Δ roll']],
  rates: ['rates', ['X', 'Y', 'Z']],
  acceleration: ['acceleration', ['X', 'Y', 'Z']],
  estimator: ['estimator', ['Estimate error']]
};
export const colours = ['#ff797d', '#4de2a5', '#67b9ff'];
export function averageChartSamples(samples, periodMs = 1000) {
  const buckets = new Map();
  for (const sample of samples) {
    const bucket = Math.floor(sample.t / periodMs);
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket).push(sample);
  }
  const average = values => {
    const valid = values.filter(finite);
    return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
  };
  return [...buckets.values()].map(group => {
    const result = { ...group.at(-1), d: { ...group.at(-1).d } };
    for (const key of ['gyroError', 'magError', 'reactionWheels', 'magnetorquers', 'rates', 'acceleration', 'angleError']) {
      const channels = group.find(sample => Array.isArray(sample[key]))?.[key].length;
      result[key] = channels ? Array.from({ length: channels }, (_, i) => average(group.map(sample => sample[key]?.[i]))) : null;
    }
    result.pointingError = average(group.map(sample => sample.pointingError));
    result.d.att_est_error_deg = average(group.map(sample => sample.d.att_est_error_deg));
    return result;
  });
}
export function drawChart(canvas, rawSamples) {
  const samples = averageChartSamples(rawSamples);
  const rect = canvas.getBoundingClientRect();
  if (!rect.width) return;
  const ratio = Math.min(devicePixelRatio || 1, 2);
  const width = Math.round(rect.width * ratio),
    height = Math.round(rect.height * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.scale(ratio, ratio);
  const w = rect.width,
    h = rect.height,
    compact = h < 75,
    left = compact ? 43 : 49,
    right = w - 8,
    top = compact ? 5 : 10,
    bottom = h - (compact ? 14 : 22);
  ctx.font = (compact ? '10px' : '11px') + ' system-ui';
  ctx.fillStyle = '#9bb0c3';
  ctx.strokeStyle = '#bedfff20';
  ctx.lineWidth = 1;
  const type = canvas.dataset.chart,
    [key, names] = chartDefs[type];
  const values = samples.map(s => key === 'pointing' ? [s.pointingError, ...s.angleError] : key === 'estimator' ? [s.d.att_est_error_deg] : Array.isArray(s[key]) ? s[key] : [s[key]]);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const all = values.flat().filter(finite);
  let lo = all.length ? Math.min(...all) : 0,
    hi = all.length ? Math.max(...all) : 1;
  if (hi === lo) {
    const pad = Math.max(Math.abs(hi) * .1, .001);
    lo -= pad;
    hi += pad;
  }
  if (type === 'torquers' || type === 'acceleration') {
    const amplitude = Math.max(Math.abs(lo), Math.abs(hi), type === 'torquers' ? .1 : .0001);
    lo = -amplitude; hi = amplitude;
  }
  const margin = (hi - lo) * .1;
  lo -= margin;
  hi += margin;
  for (let i = 0; i < 3; i++) {
    const y = top + (bottom - top) * i / 2;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    const v = hi - (hi - lo) * i / 2;
    ctx.fillText(Math.abs(v) >= 10000 || Math.abs(v) < .01 && v !== 0 ? v.toExponential(1) : v.toFixed(2), 0, y + 3);
  }
  if (samples.length < 2 || !all.length) {
    ctx.fillText('Waiting for live samples', left + 8, (top + bottom) / 2);
    return;
  }
  const end = samples.at(-1).t,
    span = 30000,
    start = end - span;
  ctx.fillText('−' + (span / 1000).toFixed(0) + ' s', left, h - 5);
  ctx.fillText('now', right - 23, h - 5);
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, right - left, bottom - top);
  ctx.clip();
  const palette = (type === 'pointing' || type === 'wheels') ? ['#e8f3fb', ...colours] : colours;
  names.forEach((_, j) => {
    ctx.strokeStyle = palette[j];
    ctx.lineWidth = 1.35;
    ctx.beginPath();
    let open = false;
    values.forEach((v, i) => {
      if (!finite(v[j])) {
        open = false;
        return;
      }
      if (i && samples[i].t - samples[i - 1].t > 5000) open = false;
      const x = left + (right - left) * (samples[i].t - start) / span,
        y = bottom - (v[j] - lo) / (hi - lo) * (bottom - top);
      if (open) ctx.lineTo(x, y);else ctx.moveTo(x, y);
      open = true;
    });
    ctx.stroke();
  });
  ctx.restore();
  canvas.dataset.samples = String(samples.length);
}
