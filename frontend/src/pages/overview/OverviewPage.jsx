/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from "react";
import SpacecraftCard from "../../components/SpacecraftCard/SpacecraftCard.jsx";
import AttitudeCard from "../../components/AttitudeCard/AttitudeCard.jsx";
import SensorHealthCard from "../../components/SensorHealthCard/SensorHealthCard.jsx";
import OrbitalModelsCard from "../../components/OrbitalModelsCard/OrbitalModelsCard.jsx";
import OrbitalContextCard from "../../components/OrbitalContextCard/OrbitalContextCard.jsx";
import DistanceScale from "../../components/DistanceScale/DistanceScale.jsx";
import "./OverviewPage.css";
export default memo(function OverviewPage({
  active,
  visible = active,
  departing = false,
  data,
  derived,
  samples,
  configuration
}) {
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <section className="mission-page" id="mission-page-overview" role="tabpanel" aria-labelledby="mission-tab-overview" hidden={!visible} data-departing={departing} aria-hidden={departing || !visible}>
    <div className="mission-rail rail-left">
      <SpacecraftCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <AttitudeCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
    <div className="mission-rail rail-right">
      <SensorHealthCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
      <OrbitalModelsCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
    <div className="mission-bottom">
      <OrbitalContextCard data={data} derived={derived} samples={samples} active={active} configuration={configuration} />
    </div>
    <DistanceScale />
  </section>;
});
