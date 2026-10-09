/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import LiveChart from '../LiveChart/LiveChart.jsx';
import "./AttitudeErrorCard.css";
export default memo(function AttitudeErrorCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass attitude-error-card">
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
          {"Attitude error"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="estimator-metric" data-severity={!Number.isFinite(data.att_est_error_deg) ? "unknown" : data.att_est_error_deg < 2 ? "good" : data.att_est_error_deg < 10 ? "warn" : "bad"}>
        <b data-value="att_est_error_deg" data-unit="°" data-digits="3">
          {formatTelemetry(data, derived, {
          "data-value": "att_est_error_deg",
          "data-unit": "°",
          "data-digits": "3"
        }, "")}
        </b>
        <span>
          {"Attitude error"}
        </span>
      </div>
      <p className="quiet">
        {"Sun correction: "}
        <span data-bool="att_est_sun_used">
          {formatTelemetry(data, derived, {
          "data-bool": "att_est_sun_used"
        }, "")}
        </span>
      </p>
      <div className="attitude-trend-card">
        <h3>
          {"Attitude trend & Euler"}
        </h3>
        <LiveChart type="estimator" label="Estimate error · °" samples={samples} active={active} />
        <table className="sensor-table">
          <thead>{
            /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
          }
            <tr>
              <th>
                {"Euler °"}
              </th>
              <th>
                {"Belief"}
              </th>
              <th>
                {"Truth"}
              </th>
              <th>
                {"Error"}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>
                {"Yaw"}
              </th>
              <td data-calc="estAngles.0">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngles.0"
              }, "")}
              </td>
              <td data-calc="angles.0">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.0"
              }, "")}
              </td>
              <td data-calc="estAngleError.0">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngleError.0"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Pitch"}
              </th>
              <td data-calc="estAngles.1">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngles.1"
              }, "")}
              </td>
              <td data-calc="angles.1">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.1"
              }, "")}
              </td>
              <td data-calc="estAngleError.1">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngleError.1"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Roll"}
              </th>
              <td data-calc="estAngles.2">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngles.2"
              }, "")}
              </td>
              <td data-calc="angles.2">
                {formatTelemetry(data, derived, {
                "data-calc": "angles.2"
              }, "")}
              </td>
              <td data-calc="estAngleError.2">
                {formatTelemetry(data, derived, {
                "data-calc": "estAngleError.2"
              }, "")}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </MissionCard>;
});
