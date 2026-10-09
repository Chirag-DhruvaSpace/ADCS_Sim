/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { HealthRows } from '../TelemetryRows/TelemetryRows.jsx';
import "./SensorHealthCard.css";
export default memo(function SensorHealthCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass ">
      <header className="card-heading">{
        /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      }
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 3v9a4 4 0 0 0 8 0V3M5 8v6a7 7 0 0 0 14 0V8M12 21v2M8 3h3v5H8m8-5h-3v5h3">
            </path>
          </svg>
          {"Sensors activated"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="health-list" id="mission-health">
        <HealthRows data={data} />
      </div>
      <p className="quiet">
        {"Simulation enablement reported by the backend"}
      </p>
    </MissionCard>;
});
