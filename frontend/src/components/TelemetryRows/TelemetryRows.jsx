/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { finite, fmt } from '../../services/dashboardData.js';
import './TelemetryRows.css';
export function HealthRows({
  data
}) {
  return ['GPS receiver', 'Gyroscope', 'Magnetometer', 'Sun sensor array'].map(label => {
    const enabled = data.sensor_activation?.[label];
    return <div className="health-row" key={label}><i className="health-dot" data-valid={String(enabled === true)} /><span>{label}</span><b>{typeof enabled === 'boolean' ? enabled ? 'Enabled' : 'Off' : 'Unavailable'}</b></div>;
  });
}
export function ModelRows({
  data
}) {
  return Object.entries(data.orbital_models || {
    Configuration: 'Not published'
  }).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{Array.isArray(value) ? value.join(', ') : String(value)}</dd></div>);
}
export function SunCellRows({
  data
}) {
  if (!data.sun_arr_cells?.length) return <tr><td colSpan={5}>Sun array unavailable</td></tr>;
  return data.sun_arr_cells.map((cell, index) => <tr key={cell.name || index}>{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }<td>{cell.name}</td><td>{fmt(cell.output_pct, 1)}</td><td>{fmt(cell.adc_counts, 0)}</td><td>{fmt(cell.angle_deg, 1)}</td><td data-used={String(cell.used)}>{cell.shadowed ? 'Shadowed' : cell.saturated ? 'Saturated' : cell.used ? 'Used' : cell.in_fov ? 'In FOV' : 'Out of FOV'}</td></tr>);
}
const small = value => finite(value) ? Math.abs(value) < .001 && value !== 0 ? value.toExponential(2) : fmt(value, 3) : '—';
export function ActuatorRows({
  data
}) {
  return <>{[0, 1, 2].map(index => <div className="actuator-line" key={'mtr' + index}><span>MTR {'XYZ'[index]}</span><b>{small(data.mtr_torque_nm?.[index])} N·m</b><b>{small(data.mtr_dipole_am2?.[index])} A·m²</b><b>{small(data.mtr_current_a?.[index])} A</b></div>)}{!['POINTING', 'SUN_POINTING', 'DETUMBLE'].includes(data.mode) && [0, 1, 2, 3].map(index => <div className="actuator-line" key={'rw' + index}><span>Wheel {index + 1}</span><b>{small(data.rw_torques_mnm?.[index])} mN·m</b><b>{small(data.rw_momentum_mnms?.[index])} mN·m·s</b></div>)}</>;
}
