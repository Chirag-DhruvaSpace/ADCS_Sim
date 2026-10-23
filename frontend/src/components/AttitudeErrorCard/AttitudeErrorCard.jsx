import { memo } from 'react';
import MissionCard from '../MissionCard/MissionCard.jsx';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import './AttitudeErrorCard.css';

export default memo(function AttitudeErrorCard({ data, derived }) {
  const error = data.att_est_error_deg;
  const severity = !Number.isFinite(error) ? 'unknown' : error < 2 ? 'good' : error < 10 ? 'warn' : 'bad';
  return <MissionCard className="mission-card glass attitude-error-card">
    <header className="card-heading">
      <div className="attitude-error-title"><h2><svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" />
        <path d="M12 1v6m0 10v6M1 12h6m10 0h6" />
      </svg>Attitude error</h2>
        <p className="quiet">Sun correction: <span data-bool="att_est_sun_used">
          {formatTelemetry(data, derived, { 'data-bool': 'att_est_sun_used' }, '')}
        </span></p>
      </div>
      <div className="estimator-metric" data-severity={severity}>
        <b data-value="att_est_error_deg" data-unit="°" data-digits="3">
          {formatTelemetry(data, derived, { 'data-value': 'att_est_error_deg', 'data-unit': '°', 'data-digits': '3' }, '')}
        </b>
      </div>
    </header>
  </MissionCard>;
});
