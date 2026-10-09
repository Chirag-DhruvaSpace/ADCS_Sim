/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./GpsCard.css";
export default memo(function GpsCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass gps-card">
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
          {"GPS receiver"}
        </h2>
        <span className="card-label">
        </span>
        <div className="card-state" data-state="gps_fix" data-valid={String(data["gps_fix"] === true)}>
          {formatTelemetry(data, derived, {
          "class": "card-state",
          "data-state": "gps_fix"
        }, "")}
        </div>
      </header>
      <div className="gps-layout">
        <dl className="metric-list">
          <div>
            <dt>
              {"Satellites reported"}
            </dt>
            <dd data-value="gps_num_sv" data-unit="" data-digits="0">
              {formatTelemetry(data, derived, {
              "data-value": "gps_num_sv",
              "data-unit": "",
              "data-digits": "0"
            }, "")}
            </dd>
          </div>
          <div>
            <dt>
              {"PDOP"}
            </dt>
            <dd data-value="gps_pdop" data-unit="" data-digits="2">
              {formatTelemetry(data, derived, {
              "data-value": "gps_pdop",
              "data-unit": "",
              "data-digits": "2"
            }, "")}
            </dd>
          </div>
          <div>
            <dt>
              {"Horizontal accuracy"}
            </dt>
            <dd data-value="gps_h_acc_m" data-unit=" m" data-digits="2">{
              /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
            }
              {formatTelemetry(data, derived, {
              "data-value": "gps_h_acc_m",
              "data-unit": " m",
              "data-digits": "2"
            }, "")}
            </dd>
          </div>
          <div>
            <dt>
              {"Vertical accuracy"}
            </dt>
            <dd data-value="gps_v_acc_m" data-unit=" m" data-digits="2">
              {formatTelemetry(data, derived, {
              "data-value": "gps_v_acc_m",
              "data-unit": " m",
              "data-digits": "2"
            }, "")}
            </dd>
          </div>
          <div>
            <dt>
              {"Latency"}
            </dt>
            <dd data-value="gps_latency_s" data-unit=" ms" data-digits="0">
              {formatTelemetry(data, derived, {
              "data-value": "gps_latency_s",
              "data-unit": " ms",
              "data-digits": "0"
            }, "")}
            </dd>
          </div>
        </dl>
        <MiniWorld kind="gps" caption="Spacecraft & orbit · ECEF" />
      </div>
      <dl className="metric-list">
        <div>
          <dt>
            {"Fix latitude"}
          </dt>
          <dd data-value="gps_lat_deg" data-unit="°" data-digits="4">
            {formatTelemetry(data, derived, {
            "data-value": "gps_lat_deg",
            "data-unit": "°",
            "data-digits": "4"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Fix longitude"}
          </dt>
          <dd data-value="gps_lon_deg" data-unit="°" data-digits="4">
            {formatTelemetry(data, derived, {
            "data-value": "gps_lon_deg",
            "data-unit": "°",
            "data-digits": "4"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Fix altitude"}
          </dt>
          <dd data-value="gps_alt_m" data-unit=" km" data-digits="3">
            {formatTelemetry(data, derived, {
            "data-value": "gps_alt_m",
            "data-unit": " km",
            "data-digits": "3"
          }, "")}
          </dd>
        </div>
      </dl>
      <p className="metric-highlight">
        {"Position belief error "}
        <b data-derived="gpsError" data-unit=" m">
          {formatTelemetry(data, derived, {
          "data-derived": "gpsError",
          "data-unit": " m"
        }, "")}
        </b>
      </p>
      <p className="quiet" id="gps-links-status">
        {formatTelemetry(data, derived, {
        "class": "quiet",
        "id": "gps-links-status"
      }, "gps-links-status")}
      </p>
    </MissionCard>;
});
