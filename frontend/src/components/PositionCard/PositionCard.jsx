/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./PositionCard.css";
export default memo(function PositionCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass position-card">
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="6">
            </circle>
            <ellipse cx="12" cy="12" rx="11" ry="4" transform="rotate(-35 12 12)">
            </ellipse>
          </svg>
          {"Orbit & position"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="position-body">
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
          <div>
            <dt>{
              /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
            }
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
        </dl>
        <MiniWorld kind="sun" caption="Sun-aligned view · Earth shadow and live spacecraft" />
      </div>
      <div className="position-vectors">
        <span>
          {"Position · ECI · metres"}
        </span>
        <div>
          {"Truth "}
          <b id="mission-pos-truth">
            {formatTelemetry(data, derived, {
            "id": "mission-pos-truth"
          }, "mission-pos-truth")}
          </b>
        </div>
        <div>
          {"GPS belief "}
          <b id="mission-pos-gps">
            {formatTelemetry(data, derived, {
            "id": "mission-pos-gps"
          }, "mission-pos-gps")}
          </b>
        </div>
      </div>
      <p className="metric-highlight">
        {"Position belief error "}
        <b data-derived="gpsError" data-unit=" m">
          {formatTelemetry(data, derived, {
          "data-derived": "gpsError",
          "data-unit": " m"
        }, "")}
        </b>
      </p>
    </MissionCard>;
});
