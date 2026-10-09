/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
const finite = v => typeof v === 'number' && Number.isFinite(v);
const vector = (d, prefix, suffix = '') => {
  const v = ['x', 'y', 'z'].map(a => d[prefix + a + suffix]);
  return v.every(finite) ? v : null;
};
const norm = v => v && v.every(finite) ? Math.hypot(...v) : null;
const difference = (a, b) => a && b ? a.map((v, i) => v - b[i]) : null;
const fmt = (v, digits = 2) => finite(v) ? v.toLocaleString('en-US', {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits
}) : '—';
const modes = {
  POINTING: ['target', 'sun_pointing_error_deg'],
  SUN_POINTING: ['target', 'sun_pointing_error_deg'],
  SUN_POINTING_RW: ['sun_pointing_rw_target', 'sun_pointing_rw_error_deg'],
  MOON: ['moon_target', 'moon_pointing_error_deg'],
  NADIR: ['nadir_target', 'nadir_pointing_error_deg'],
  SUN_SWEEP: ['sun_sweep_target', 'sun_sweep_error_deg'],
  NOMINAL_IN_ORBIT: ['nominal_in_orbit_target', 'nominal_in_orbit_error_deg'],
  KINEMATIC_ROBUSTNESS: ['kinematic_robustness_target', 'kinematic_robustness_error_deg'],
  CUSTOM: ['custom_target', 'custom_pointing_error_deg']
};
function derive(d) {
  const gyroRaw = vector(d, 'imu_gyro_', '_rad_s');
  const gyro = d.imu_gyro_valid === true && gyroRaw ? gyroRaw.map(v => v * 180 / Math.PI) : null;
  const rates = vector(d, 'body_rate_');
  const mag = d.imu_mag_valid === true ? vector(d, 'imu_mag_', '_nT') : null;
  const magTruth = vector(d, 'truth_mag_body_', '_nT');
  const target = d.mode === 'FIRMWARE_SITL' ? ['firmware_target', 'firmware_pointing_error_deg'] : Array.isArray(d.custom_target_quaternion) ? modes.CUSTOM : modes[d.mode];
  const angles = ['yaw', 'pitch', 'roll'].map(a => d[a + '_deg']);
  const targets = target ? ['yaw', 'pitch', 'roll'].map(a => d[target[0] + '_' + a + '_deg']) : [null, null, null];
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const estAngles = Array.isArray(d.att_est_euler_deg) ? d.att_est_euler_deg : [null, null, null];
  return {
    gyro,
    rates,
    mag,
    magTruth,
    gyroError: difference(gyro, rates),
    magError: difference(mag, magTruth),
    estAngles,
    estAngleError: angles.map((v, i) => finite(v) && finite(estAngles[i]) ? (estAngles[i] - v + 540) % 360 - 180 : null),
    reactionWheels: Array.isArray(d.rw_torques_mnm) && d.rw_torques_mnm.length === 4 && d.rw_torques_mnm.every(finite) ? [...d.rw_torques_mnm] : null,
    magnetorquers: Array.isArray(d.mtr_torque_nm) && d.mtr_torque_nm.length === 3 && d.mtr_torque_nm.every(finite) ? d.mtr_torque_nm.map(v => v * 1e6) : null,
    acceleration: vector(d, 'alpha_'),
    angles,
    targets,
    angleError: angles.map((v, i) => finite(v) && finite(targets[i]) ? (v - targets[i] + 540) % 360 - 180 : null),
    pointingError: target && finite(d[target[1]]) ? d[target[1]] : null,
    gpsError: norm(difference(vector(d, 'gps_pos_eci_'), vector(d, 'truth_pos_eci_')))
  };
}
class History {
  constructor(limit = 240, windowMs = 30000) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.samples = [];
    this.session = null;
    this.key = null;
  }
  add(d) {
    const t = Date.parse(d.timestamp);
    if (!Number.isFinite(t)) return false;
    const session = d.telemetry_session_id || '';
    const key = `${session}:${d.telemetry_sequence ?? d.timestamp}`;
    if (key === this.key) return false;
    const last = this.samples.at(-1);
    if (session !== this.session || last && t < last.t) this.samples = [];
    this.session = session;
    this.key = key;
    const sample = {
      t,
      d,
      ...derive(d)
    };
    if (this.samples.at(-1)?.t === t) this.samples[this.samples.length - 1] = sample;else this.samples.push(sample);
    while (this.samples.length > this.limit || this.samples.length > 1 && t - this.samples[0].t > this.windowMs) this.samples.shift();
    return true;
  }
}
export { finite, vector, norm, difference, fmt, derive, History };
