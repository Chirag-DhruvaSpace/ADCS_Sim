/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import "./DisturbanceCard.css";
export default memo(function DisturbanceCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass disturbance-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M1 12h5l2-8 4 16 3-12 2 4h6">
            </path>
          </svg>
          {"Disturbances"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <p id="mission-configuration" className="quiet">
        {formatTelemetry(data, derived, {
        "id": "mission-configuration",
        "class": "quiet"
      }, "mission-configuration")}
      </p>
      <dl className="metric-list">
        <div>
          <dt>
            {"SRP torque"}
          </dt>
          <dd data-value="disturbance_srp_unm" data-unit=" µN·m" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "disturbance_srp_unm",
            "data-unit": " µN·m",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Air density"}
          </dt>
          <dd data-value="atmospheric_density_kg_m3" data-unit=" kg/m³" data-digits="14">
            {formatTelemetry(data, derived, {
            "data-value": "atmospheric_density_kg_m3",
            "data-unit": " kg/m³",
            "data-digits": "14"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Illumination"}
          </dt>
          <dd data-value="eclipse_fraction" data-unit="" data-digits="3">{
            /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
          }
            {formatTelemetry(data, derived, {
            "data-value": "eclipse_fraction",
            "data-unit": "",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Gravity gradient"}
          </dt>
          <dd data-value="disturbance_gravity_gradient_unm" data-unit=" µN·m" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "disturbance_gravity_gradient_unm",
            "data-unit": " µN·m",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Residual dipole"}
          </dt>
          <dd data-value="disturbance_residual_dipole_unm" data-unit=" µN·m" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "disturbance_residual_dipole_unm",
            "data-unit": " µN·m",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Atmospheric drag"}
          </dt>
          <dd data-value="disturbance_atmospheric_drag_unm" data-unit=" µN·m" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "disturbance_atmospheric_drag_unm",
            "data-unit": " µN·m",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Net torque"}
          </dt>
          <dd data-value="disturbance_net_unm" data-unit=" µN·m" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "disturbance_net_unm",
            "data-unit": " µN·m",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
      </dl>
      <details>
        <summary>
          {"Acceleration vectors · ECI · m/s²"}
        </summary>
        <p className="quiet">
          {"SRP "}
          <span id="mission-srp">
            {formatTelemetry(data, derived, {
            "id": "mission-srp"
          }, "mission-srp")}
          </span>
        </p>
        <p className="quiet">
          {"Drag "}
          <span id="mission-drag">
            {formatTelemetry(data, derived, {
            "id": "mission-drag"
          }, "mission-drag")}
          </span>
        </p>
      </details>
    </MissionCard>;
});
