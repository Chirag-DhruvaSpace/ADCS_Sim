/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import { ActuatorRows } from '../TelemetryRows/TelemetryRows.jsx';
import ManualControls from '../ManualControls/ManualControls.jsx';
import "./ActuatorCard.css";
export default memo(function ActuatorCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass actuator-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 3v9a4 4 0 0 0 8 0V3M5 8v6a7 7 0 0 0 14 0V8M12 21v2M8 3h3v5H8m8-5h-3v5h3">
            </path>
          </svg>
          {"Actuator telemetry"}
        </h2>
        <span className="card-label">{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }
        </span>
      </header>
      <p className="quiet mode-status">
        {"Mode "}
        <strong data-text="mode">
          {formatTelemetry(data, derived, {
          "data-text": "mode"
        }, "")}
        </strong>
        {" · "}
        <span data-value="simulation_time_s" data-unit=" s">
          {formatTelemetry(data, derived, {
          "data-value": "simulation_time_s",
          "data-unit": " s"
        }, "")}
        </span>
        {" · "}
        <span id="mission-mode-error">
          {formatTelemetry(data, derived, {
          "id": "mission-mode-error"
        }, "mission-mode-error")}
        </span>
      </p>
      <div id="mission-actuators">
        <ActuatorRows data={data} />
      </div>
      <details id="mission-manual" hidden={data.mode !== "RW"}>
        <summary>
          {"Manual attitude commands"}
        </summary>
        <ManualControls />
      </details>
    </MissionCard>;
});
