/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { finite, fmt, vector, norm } from './dashboardData.js';
const vectorText = value => value ? '[' + value.map(x => fmt(x, 3)).join(', ') + ']' : '—';
const modeNames = {
  POINTING: 'Sun pointing',
  SUN_POINTING: 'Sun pointing',
  SUN_POINTING_RW: 'Sun pointing · wheels',
  MOON: 'Moon pointing',
  NADIR: 'Nadir pointing',
  SUN_SWEEP: 'Sun sweep',
  NOMINAL_IN_ORBIT: 'Nominal orbit',
  KINEMATIC_ROBUSTNESS: 'Kinematic robustness',
  FIRMWARE_SITL: 'Firmware SITL',
  CUSTOM: 'Custom quaternion'
};
export function formatTelemetry(data, derived, attributes, id) {
  const key = attributes['data-value'];
  if (key) {
    let value = data[key];
    if (['altitude_m', 'gps_alt_m', 'satellite_speed_m_s'].includes(key) && finite(value)) value /= 1000;
    if (key === 'gps_latency_s' && finite(value)) value *= 1000;
    return fmt(value, Number(attributes['data-digits'] ?? 2)) + (finite(value) ? attributes['data-unit'] || '' : '');
  }
  if (attributes['data-text']) return data[attributes['data-text']] ?? '—';
  if (attributes['data-bool']) {
    const value = data[attributes['data-bool']];
    return typeof value === 'boolean' ? value ? 'Yes' : 'No' : '—';
  }
  if (attributes['data-state']) {
    const value = data[attributes['data-state']];
    return value === true ? 'Valid' : value === false ? 'No valid measurement' : 'Unavailable';
  }
  if (attributes['data-derived']) {
    const value = derived[attributes['data-derived']];
    return fmt(value, 3) + (finite(value) ? attributes['data-unit'] || '' : '');
  }
  if (attributes['data-calc']) {
    const [key, index] = attributes['data-calc'].split('.');
    return fmt(derived[key]?.[index], key.startsWith('mag') ? 1 : 3);
  }
  if (id === 'sun-distance') /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    return fmt(norm(data.sun_position_ecef_m) ? norm(data.sun_position_ecef_m) / 1e9 : null, 2) + ' million km';
  if (id === 'moon-distance') return fmt(norm(data.moon_position_ecef_m) ? norm(data.moon_position_ecef_m) / 1000 : null, 0) + ' km';
  if (id === 'gps-links-status') return data.gps_links_available === true ? `${(data.gps_satellites || []).filter(s => s.used).length} tracked links from backend` : `Grey: nearby · green: illustrative links (${finite(data.gps_num_sv) ? data.gps_num_sv : '—'} SVs reported) · PRNs unavailable`;
  if (id === 'mission-sun-recon') return data.sun_arr_recon_valid === true ? vectorText(vector(data, 'sun_arr_recon_')) : 'Unavailable';
  if (id === 'mission-sun-truth') return vectorText(vector(data, 'sun_arr_truth_'));
  if (id === 'mission-q-belief' || id === 'mission-q-truth') {
    const prefix = id === 'mission-q-belief' ? 'att_est_quat_' : 'truth_att_quat_';
    const value = ['w', 'x', 'y', 'z'].map(a => data[prefix + a]);
    return value.every(finite) ? vectorText(value) : '—';
  }
  if (id === 'mission-pos-truth' || id === 'mission-pos-gps') {
    const value = vector(data, id === 'mission-pos-truth' ? 'truth_pos_eci_' : 'gps_pos_eci_');
    return value ? '[' + value.map(x => x.toFixed(1)).join(', ') + ']' : 'Unavailable';
  }
  if (id === 'mission-mode-error') return finite(derived.pointingError) ? `${Array.isArray(data.custom_target_quaternion) ? modeNames.CUSTOM : modeNames[data.mode] || 'Pointing'} error ${fmt(derived.pointingError, 3)}°` : 'Pointing error unavailable';
  if (id === 'mission-configuration') return data.spacecraft_configuration ? `${data.spacecraft_configuration} · ${data.spacecraft_mass_kg} kg` : '';
  if (id === 'mission-srp' || id === 'mission-drag') {
    const value = vector(data, id === 'mission-srp' ? 'srp_acceleration_eci_' : 'drag_acceleration_eci_');
    return value ? '[' + value.map(x => x.toExponential(3)).join(', ') + ']' : '—';
  }
  return '—';
}
