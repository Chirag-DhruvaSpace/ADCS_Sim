/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import MissionCard from '../MissionCard/MissionCard.jsx';
import { memo } from 'react';
import GlassSelect from '../GlassSelect/GlassSelect.jsx';
import './PointingControls.css';
const modes = [['SUN_POINTING', 'Sun Pointing (MTR)'], ['RW', 'Reaction Wheels (manual sliders)'], ['MOON', 'Moon Pointing (RW)'], ['NADIR', 'Nadir Pointing (RW)'], ['SUN_SWEEP', 'Sun Sweep (RW)'], ['SUN_POINTING_RW', 'Sun Pointing (RW)'], ['NOMINAL_IN_ORBIT', 'Nominal In-Orbit (+45? yaw)'], ['KINEMATIC_ROBUSTNESS', 'Kinematic Robustness (+Z spin)']].map(([value, label]) => ({
  value,
  label
}));
const cameras = [['free', 'Free Camera'], ['chase', 'Chase Camera'], ['payload', 'Satellite Payload']].map(([value, label]) => ({
  value,
  label
}));
export default memo(function PointingControls({
  data,
  configuration
}) {
  return <MissionCard className="mission-card glass pointing-controls"><header className="card-heading">{
        /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      }<h2><svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" /><path d="M12 1v6m0 10v6M1 12h6m10 0h6" /></svg>Pointing control</h2><span className="card-label">{configuration.pointing_strategy !== 'legacy' && <span className="quaternion-lights" role="status" aria-label={(configuration.pointing_strategy === 'firmware_sitl' ? "Firmware link: " : "Quaternion command: ") + (data.custom_pointing_status || "red")}>{["red", "green", "blue", "yellow"].map(color => <i key={color} data-color={color} className={(data.custom_pointing_status || "red") === color ? "lit" : ""} />)}</span>}</span></header><div id="mission-control-slot">{configuration.pointing_strategy === 'legacy' ? <><label>Legacy pointing mode</label><GlassSelect id="modeSelect" label="Legacy pointing mode" options={modes} initialValue={configuration.legacy_mode} telemetryValue={data.mode === 'POINTING' ? 'SUN_POINTING' : data.mode} /></> : <p className="quiet custom-pointing">{configuration.pointing_strategy === 'firmware_sitl' ? `Firmware SITL: ${data.ads_mode || 'awaiting ADS'} | UDP wheel torques and magnetic dipole` : 'Custom pointing: send a desired quaternion or quaternion error through the Python client or API.'}</p>}</div><label className="camera-field">Camera view <span id="mission-camera-slot"><GlassSelect id="cameraSelect" label="Camera view" options={cameras} initialValue="chase" /></span></label><p className="quiet">{configuration.pointing_strategy === 'firmware_sitl' ? 'Pointing is controlled by the external firmware.' : 'Legacy pointing uses the mode selector. Custom pointing uses quaternion input.'}</p></MissionCard>;
});
