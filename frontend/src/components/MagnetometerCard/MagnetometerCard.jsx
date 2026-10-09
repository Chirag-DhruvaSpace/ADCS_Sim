/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import LiveChart from '../LiveChart/LiveChart.jsx';
import "./MagnetometerCard.css";
export default memo(function MagnetometerCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass vector-sensor-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M8 3v9a4 4 0 0 0 8 0V3M5 8v6a7 7 0 0 0 14 0V8M12 21v2M8 3h3v5H8m8-5h-3v5h3">
            </path>
          </svg>
          {"Magnetometer"}
        </h2>
        <span className="card-label">
          <p className="quiet">
            {"Saturated: "}
            <span data-bool="imu_mag_saturated">
              {formatTelemetry(data, derived, {
              "data-bool": "imu_mag_saturated"
            }, "")}
            </span>
          </p>
        </span>
        <div className="card-state" data-state="imu_mag_valid" data-valid={String(data["imu_mag_valid"] === true)}>
          {formatTelemetry(data, derived, {
          "class": "card-state",
          "data-state": "imu_mag_valid"
        }, "")}
        </div>
      </header>
      <div className="sensor-split">
        <table className="sensor-table">
          <thead>
            <tr>
              <th>
                {"nT"}
              </th>
              <th>
                {"Measured"}
              </th>
              <th>
                {"Truth"}
              </th>
              <th>{
                /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
              }
                {"Error"}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>
                {"X"}
              </th>
              <td data-calc="mag.0">
                {formatTelemetry(data, derived, {
                "data-calc": "mag.0"
              }, "")}
              </td>
              <td data-calc="magTruth.0">
                {formatTelemetry(data, derived, {
                "data-calc": "magTruth.0"
              }, "")}
              </td>
              <td data-calc="magError.0">
                {formatTelemetry(data, derived, {
                "data-calc": "magError.0"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Y"}
              </th>
              <td data-calc="mag.1">
                {formatTelemetry(data, derived, {
                "data-calc": "mag.1"
              }, "")}
              </td>
              <td data-calc="magTruth.1">
                {formatTelemetry(data, derived, {
                "data-calc": "magTruth.1"
              }, "")}
              </td>
              <td data-calc="magError.1">
                {formatTelemetry(data, derived, {
                "data-calc": "magError.1"
              }, "")}
              </td>
            </tr>
            <tr>
              <th>
                {"Z"}
              </th>
              <td data-calc="mag.2">
                {formatTelemetry(data, derived, {
                "data-calc": "mag.2"
              }, "")}
              </td>
              <td data-calc="magTruth.2">
                {formatTelemetry(data, derived, {
                "data-calc": "magTruth.2"
              }, "")}
              </td>
              <td data-calc="magError.2">
                {formatTelemetry(data, derived, {
                "data-calc": "magError.2"
              }, "")}
              </td>
            </tr>
          </tbody>
        </table>
        <LiveChart type="mag" label="Magnetic measurement error · nT" samples={samples} active={active} />
      </div>
    </MissionCard>;
});
