/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from "react";
import PositionCard from "../../components/PositionCard/PositionCard.jsx";
import ReactionWheelsCard from "../../components/ReactionWheelsCard/ReactionWheelsCard.jsx";
import MagnetorquersCard from "../../components/MagnetorquersCard/MagnetorquersCard.jsx";
import AngularAccelerationCard from "../../components/AngularAccelerationCard/AngularAccelerationCard.jsx";
import PointingControls from "../../components/PointingControls/PointingControls.jsx";
import AttitudeTargetCard from "../../components/AttitudeTargetCard/AttitudeTargetCard.jsx";
import ActuatorCard from "../../components/ActuatorCard/ActuatorCard.jsx";
import DisturbanceCard from "../../components/DisturbanceCard/DisturbanceCard.jsx";
import "./PointingPage.css";
export default memo(function PointingPage({
  active,
  visible = active,
  departing = false,
  data,
  derived,
  samples,
  configuration
}) {
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <section className="mission-page" id="mission-page-pointing" role="tabpanel" aria-labelledby="mission-tab-pointing" hidden={!visible} data-departing={departing} aria-hidden={departing || !visible}>
    <div className="mission-rail rail-left">
      <PositionCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <ReactionWheelsCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <MagnetorquersCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <AngularAccelerationCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
    <div className="mission-rail rail-right">
      <PointingControls data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <AttitudeTargetCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <ActuatorCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <DisturbanceCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
  </section>;
});
