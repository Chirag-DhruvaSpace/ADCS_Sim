/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import LiveChart from '../LiveChart/LiveChart.jsx';
import "./AngularAccelerationCard.css";
export default memo(function AngularAccelerationCard({
  data,
  derived,
  samples,
  active
}) {
  return <MissionCard className="mission-card glass pointing-graph-card">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }
      <header className="card-heading">
        <h2>
          <svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M1 12h5l2-8 4 16 3-12 2 4h6">
            </path>
          </svg>
          {"Angular accelerations"}
        </h2>
        <span className="card-label">{"deg/s\u00b2"}</span>
      </header>
      <LiveChart type="acceleration" label="Body accelerations · °/s²" samples={samples} active={active} />
    </MissionCard>;
});
