/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from 'react';
import InstrumentBindings from '../../components/InstrumentBindings/InstrumentBindings.jsx';
import TelemetryBindings from '../../components/TelemetryBindings/TelemetryBindings.jsx';
import './ViewerLayout.css';
export default memo(function ViewerLayout() {
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <><main id="viewer-layout"><div id="view-controls" hidden /><InstrumentBindings /><div id="threeContainer"><div id="clock"><span id="clock-time">--</span>&nbsp;UTC</div><div id="fps-meter">-- fps</div><div id="feed-meter">Feed: waiting…</div><div id="attribution">Imagery © Esri, Maxar, Earthstar Geographics · Earth/clouds/stars: Solar System Scope (CC BY 4.0) · Overview night lights: NASA Black Marble</div></div><TelemetryBindings /></main><div id="labels" /></>;
});
