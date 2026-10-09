/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from "react";
import AttitudeBeliefCard from "../../components/AttitudeBeliefCard/AttitudeBeliefCard.jsx";
import GpsCard from "../../components/GpsCard/GpsCard.jsx";
import GyroscopeCard from "../../components/GyroscopeCard/GyroscopeCard.jsx";
import MagnetometerCard from "../../components/MagnetometerCard/MagnetometerCard.jsx";
import AttitudeErrorCard from "../../components/AttitudeErrorCard/AttitudeErrorCard.jsx";
import SunSensorsCard from "../../components/SunSensorsCard/SunSensorsCard.jsx";
import "./SensorsPage.css";
export default memo(function SensorsPage({
  active,
  visible = active,
  departing = false,
  data,
  derived,
  samples,
  configuration
}) {
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <section className="mission-page" id="mission-page-sensors" role="tabpanel" aria-labelledby="mission-tab-sensors" hidden={!visible} data-departing={departing} aria-hidden={departing || !visible}>
    <div className="mission-rail rail-left">
      <AttitudeBeliefCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <GpsCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <GyroscopeCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <MagnetometerCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
    <div className="mission-rail rail-right">
      <AttitudeErrorCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <SunSensorsCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
  </section>;
});
