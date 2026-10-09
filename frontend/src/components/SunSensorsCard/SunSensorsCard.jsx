/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import { SunCellRows } from '../TelemetryRows/TelemetryRows.jsx';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./SunSensorsCard.css";
export default memo(function SunSensorsCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass sun-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="5">
            </circle>
            <path d="M12 1v3m0 16v3M1 12h3m16 0h3M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2">
            </path>
          </svg>
          {"Sun sensor array"}
        </h2>
        <span className="card-label">
        </span>
        <div className="card-state" data-state="sun_arr_valid" data-valid={String(data["sun_arr_valid"] === true)}>
          {formatTelemetry(data, derived, {
          "class": "card-state",
          "data-state": "sun_arr_valid"
        }, "")}
        </div>
      </header>
      <div className="sun-meta">
        <span>
          {"Eclipse "}
          <b data-value="sun_arr_eclipse_factor" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "sun_arr_eclipse_factor",
            "data-digits": "3"
          }, "")}
          </b>
        </span>
        <span data-text="sun_arr_method">{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }
          {formatTelemetry(data, derived, {
          "data-text": "sun_arr_method"
        }, "")}
        </span>
      </div>
      <div className="table-scroll">
        <table className="sensor-table">
          <thead>
            <tr>
              <th>
                {"Cell"}
              </th>
              <th>
                {"Out %"}
              </th>
              <th>
                {"ADC"}
              </th>
              <th>
                {"Cone °"}
              </th>
              <th>
                {"Status"}
              </th>
            </tr>
          </thead>
          <tbody id="mission-sun-cells">
            <SunCellRows data={data} />
          </tbody>
        </table>
      </div>
      <div className="vector-pair">
        <span>
          {"Reconstructed · body "}
          <b id="mission-sun-recon">
            {formatTelemetry(data, derived, {
            "id": "mission-sun-recon"
          }, "mission-sun-recon")}
          </b>
        </span>
        <span>
          {"Truth · body "}
          <b id="mission-sun-truth">
            {formatTelemetry(data, derived, {
            "id": "mission-sun-truth"
          }, "mission-sun-truth")}
          </b>
        </span>
      </div>
      <p className="metric-highlight">
        {"Angular error "}
        <b data-value="sun_arr_error_deg" data-unit="°" data-digits="3">
          {formatTelemetry(data, derived, {
          "data-value": "sun_arr_error_deg",
          "data-unit": "°",
          "data-digits": "3"
        }, "")}
        </b>
      </p>
      <MiniWorld kind="sun" caption="Sun-aligned view · Earth shadow and live spacecraft" />
    </MissionCard>;
});
