/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./AttitudeCard.css";
export default memo(function AttitudeCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass ">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="8">
            </circle>
            <circle cx="12" cy="12" r="4">
            </circle>
            <path d="M12 1v6m0 10v6M1 12h6m10 0h6">
            </path>
          </svg>
          {"Attitude · current"}
        </h2>
        <span className="card-label">{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }
        </span>
      </header>
      <dl className="metric-list">
        <div>
          <dt>
            {"Yaw"}
          </dt>
          <dd data-value="yaw_deg" data-unit="°" data-digits="2">
            {formatTelemetry(data, derived, {
            "data-value": "yaw_deg",
            "data-unit": "°",
            "data-digits": "2"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Pitch"}
          </dt>
          <dd data-value="pitch_deg" data-unit="°" data-digits="2">
            {formatTelemetry(data, derived, {
            "data-value": "pitch_deg",
            "data-unit": "°",
            "data-digits": "2"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Roll"}
          </dt>
          <dd data-value="roll_deg" data-unit="°" data-digits="2">
            {formatTelemetry(data, derived, {
            "data-value": "roll_deg",
            "data-unit": "°",
            "data-digits": "2"
          }, "")}
          </dd>
        </div>
      </dl>
      <MiniWorld kind="attitude" caption="Body axes in Earth-fixed frame" />
    </MissionCard>;
});
