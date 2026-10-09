/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./AttitudeTargetCard.css";
export default memo(function AttitudeTargetCard({
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
          {"Attitude & target"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="attitude-layout">
        <table className="sensor-table">
          <thead>
            <tr>
              <th>
                {"°"}
              </th>
              <th>
                {"Current"}
              </th>
              <th>
                {"Target"}
              </th>
              <th>
                {"Δ Euler"}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>
                {"Yaw"}
              </th>
              <td data-calc="angles.0">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.0"
              }, "")}
              </td>
              <td data-calc="targets.0">{
                /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
              }
                {formatTelemetry(data, derived, {
                "data-calc": "targets.0"
              }, "")}
              </td>
              <td data-calc="angleError.0">
                {formatTelemetry(data, derived, {
                "data-calc": "angleError.0"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Pitch"}
              </th>
              <td data-calc="angles.1">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.1"
              }, "")}
              </td>
              <td data-calc="targets.1">
                {formatTelemetry(data, derived, {
                "data-calc": "targets.1"
              }, "")}
              </td>
              <td data-calc="angleError.1">
                {formatTelemetry(data, derived, {
                "data-calc": "angleError.1"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Roll"}
              </th>
              <td data-calc="angles.2">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.2"
              }, "")}
              </td>
              <td data-calc="targets.2">
                {formatTelemetry(data, derived, {
                "data-calc": "targets.2"
              }, "")}
              </td>
              <td data-calc="angleError.2">
                {formatTelemetry(data, derived, {
                "data-calc": "angleError.2"
              }, "")}
              </td>
            </tr>
          </tbody>
        </table>
        <MiniWorld kind="attitude" caption="Body axes · ECEF" />
      </div>
      <p className="metric-highlight">
        {"Mode-specific pointing error "}
        <b data-derived="pointingError" data-unit="°">
          {formatTelemetry(data, derived, {
          "data-derived": "pointingError",
          "data-unit": "°"
        }, "")}
        </b>
      </p>
      <p className="quiet">
        {"Euler deltas are wrapped component differences, not a total rotation angle."}
      </p>
    </MissionCard>;
});
