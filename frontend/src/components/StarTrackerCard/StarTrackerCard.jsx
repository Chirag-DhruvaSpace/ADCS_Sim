import { memo } from 'react';
import MissionCard from '../MissionCard/MissionCard.jsx';
import './StarTrackerCard.css';

const number = (value, digits = 1, unit = '') => Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : '—';
const vector = (values, length, digits) => Array.isArray(values) && values.length === length && values.every(Number.isFinite)
  ? `[${values.map(value => value.toFixed(digits)).join(', ')}]` : '—';

// These diagrams show the intended optical view, not a simulated star catalog.
// Keep them static until camera/catalog and exclusion models are implemented.
function OpticalPreview() {
  const stars = [[22, 25], [51, 49], [81, 22], [90, 63], [77, 84], [35, 78]];
  return <figure className="star-tracker-optics">
    <div className="star-tracker-views" aria-label="Concept previews of the camera field">
      <svg className="star-tracker-fov" viewBox="0 0 104 104" role="img" aria-label="Illustrative star camera field of view; catalog matching is not simulated">
        <rect x="1" y="1" width="102" height="102" rx="7" />
        <path className="tracker-grid" d="M35 1v102M69 1v102M1 35h102M1 69h102" />
        <path className="tracker-reticle" d="M45 52h14M52 45v14" />
        {stars.map(([x, y], index) => <g key={index}>
          <circle className="tracker-star" cx={x} cy={y} r={index % 2 ? 1.6 : 2.1} />
          {index % 2 === 0 && <circle className="tracker-match" cx={x} cy={y} r="5.2" />}
        </g>)}
        <text x="8" y="15">FOV PREVIEW</text>
      </svg>
    </div>
    <figcaption>Illustrative FOV</figcaption>
  </figure>;
}

export default memo(function StarTrackerCard({ data, derived }) {
  const valid = data.star_tracker_valid === true;
  const slew = derived.gyro ? Math.hypot(...derived.gyro) : null;
  return <MissionCard className="mission-card glass star-tracker-card">
    <header className="card-heading">
      <h2><svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 7h5l2-3h4l2 3h5v13H3Z" /><circle cx="12" cy="13" r="4" />
        <path d="m19 1 .6 1.5L21 3l-1.4.5L19 5l-.6-1.5L17 3l1.4-.5Z" />
      </svg>Star tracker</h2>
      <span className="card-label tracker-model">IDEAL · {data.star_tracker_mode || 'STANDBY'}</span>
      <span className="card-state" data-valid={String(valid)}>{valid ? 'VALID' : 'NO DATA'}</span>
    </header>
    <div className="star-tracker-body">
      <dl className="metric-list tracker-metrics">
        <div><dt>Matched / detected</dt><dd title="Star catalog matching is not modeled yet">— / —</dd></div>
        <div><dt>Slew / limit</dt><dd>{number(slew, 2, '°/s')} / —</dd></div>
        <div><dt>Update / latency</dt><dd>{number(data.star_tracker_update_rate_hz, 0, ' Hz')} / {number(data.star_tracker_latency_ms, 0, ' ms')}</dd></div>
        <div><dt>Sun angle / min</dt><dd title="Sun exclusion and hardware limit are not modeled yet">— / —</dd></div>
        <div><dt>Earth angle / min</dt><dd title="Earth exclusion and hardware limit are not modeled yet">— / —</dd></div>
      </dl>
      <OpticalPreview />
    </div>
    <div className="tracker-output"><span>Quaternion · w, x, y, z</span><b>{vector(data.star_tracker_quaternion_eci, 4, 4)}</b></div>
  </MissionCard>;
});
