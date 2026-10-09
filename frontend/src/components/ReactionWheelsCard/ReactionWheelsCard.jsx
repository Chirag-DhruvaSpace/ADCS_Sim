/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import LiveChart from '../LiveChart/LiveChart.jsx';
import "./ReactionWheelsCard.css";
export default memo(function ReactionWheelsCard({
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
            <circle cx="12" cy="12" r="8">
            </circle>
            <circle cx="12" cy="12" r="4">
            </circle>
            <path d="M12 1v6m0 10v6M1 12h6m10 0h6">
            </path>
          </svg>
          {"Reaction wheels"}
        </h2>
        <span className="card-label">{"mN\u00b7m"}</span>
      </header>
      <LiveChart type="wheels" label="Wheel torque / mN m" samples={samples} active={active} />
    </MissionCard>;
});
