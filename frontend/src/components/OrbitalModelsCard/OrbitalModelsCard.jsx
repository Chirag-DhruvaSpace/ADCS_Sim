/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { ModelRows } from '../TelemetryRows/TelemetryRows.jsx';
import "./OrbitalModelsCard.css";
export default memo(function OrbitalModelsCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass ">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="6">
            </circle>
            <ellipse cx="12" cy="12" rx="11" ry="4" transform="rotate(-35 12 12)">
            </ellipse>
          </svg>
          {"Orbital models"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <dl className="metric-list model-list" id="mission-models">
        <ModelRows data={data} />
      </dl>
    </MissionCard>;
});
