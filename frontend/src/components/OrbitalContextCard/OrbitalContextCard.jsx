/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import SolarPlan from '../SolarPlan/SolarPlan.jsx';
import "./OrbitalContextCard.css";
export default memo(function OrbitalContextCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass context-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="6">{
              /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
            }
            </circle>
            <ellipse cx="12" cy="12" rx="11" ry="4" transform="rotate(-35 12 12)">
            </ellipse>
          </svg>
          {"Orbital context"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="solar-strip">
        <SolarPlan data={data} active={active} />
      </div>
      <div className="context-distances">
        <span>
          {"Sun "}
          <b id="sun-distance">
            {formatTelemetry(data, derived, {
            "id": "sun-distance"
          }, "sun-distance")}
          </b>
        </span>
        <span>
          {"Moon "}
          <b id="moon-distance">
            {formatTelemetry(data, derived, {
            "id": "moon-distance"
          }, "moon-distance")}
          </b>
        </span>
      </div>
    </MissionCard>;
});
