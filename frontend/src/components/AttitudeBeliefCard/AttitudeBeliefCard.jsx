/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import { formatTelemetry } from '../../services/formatTelemetry.js';
import MiniWorld from '../MiniWorld/MiniWorld.jsx';
import "./AttitudeBeliefCard.css";
export default memo(function AttitudeBeliefCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass belief-card">
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
          {"Attitude belief"}
        </h2>
        <span className="card-label">
        </span>
      </header>
      <div className="vector-pair">
        <span>{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }
          {"Belief quaternion · w, x, y, z"}
          <b id="mission-q-belief">
            {formatTelemetry(data, derived, {
            "id": "mission-q-belief"
          }, "mission-q-belief")}
          </b>
        </span>
        <span>
          {"Truth quaternion · w, x, y, z"}
          <b id="mission-q-truth">
            {formatTelemetry(data, derived, {
            "id": "mission-q-truth"
          }, "mission-q-truth")}
          </b>
        </span>
      </div>
      <dl className="metric-list">
        <div>
          <dt>
            {"Corrections"}
          </dt>
          <dd data-value="att_est_corrections" data-unit="" data-digits="0">
            {formatTelemetry(data, derived, {
            "data-value": "att_est_corrections",
            "data-unit": "",
            "data-digits": "0"
          }, "")}
          </dd>
        </div>
        <div>
          <dt>
            {"Propagations"}
          </dt>
          <dd data-value="att_est_propagations" data-unit="" data-digits="0">
            {formatTelemetry(data, derived, {
            "data-value": "att_est_propagations",
            "data-unit": "",
            "data-digits": "0"
          }, "")}
          </dd>
        </div>
      </dl>
      <MiniWorld kind="estimate" caption="Estimated body axes · ECEF" />
    </MissionCard>;
});
