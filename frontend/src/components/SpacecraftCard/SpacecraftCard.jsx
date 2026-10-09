/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import "./SpacecraftCard.css";
export default memo(function SpacecraftCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass ">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="m12 2 9 5v10l-9 5-9-5V7Zm0 0v10m9-5-9 5-9-5m9 5v10">
            </path>
          </svg>
          {"Spacecraft"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <dl className="metric-list">
        <div>
          <dt>
            {"Latitude"}
          </dt>
          <dd data-value="latitude_deg" data-unit="°" data-digits="4">
            {formatTelemetry(data, derived, {
            "data-value": "latitude_deg",
            "data-unit": "°",
            "data-digits": "4"
          }, "")}
          </dd>
        </div>
        <div>{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }
          <dt>
            {"Longitude"}
          </dt>
          <dd data-value="longitude_deg" data-unit="°" data-digits="4">
            {formatTelemetry(data, derived, {
            "data-value": "longitude_deg",
            "data-unit": "°",
            "data-digits": "4"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Altitude"}
          </dt>
          <dd data-value="altitude_m" data-unit=" km" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "altitude_m",
            "data-unit": " km",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Speed · ECI"}
          </dt>
          <dd data-value="satellite_speed_m_s" data-unit=" km/s" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "satellite_speed_m_s",
            "data-unit": " km/s",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
      </dl>
      <div className="card-foot">
        <span data-text="spacecraft_configuration">
          {formatTelemetry(data, derived, {
          "data-text": "spacecraft_configuration"
        }, "")}
        </span>
        {" · "}
        <span data-text="mode">
          {formatTelemetry(data, derived, {
          "data-text": "mode"
        }, "")}
        </span>
      </div>
    </MissionCard>;
});
