/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from "react";
import "./InstrumentBindings.css";
export default memo(function InstrumentBindings() {
  return <aside id="instrument-dock" hidden={true}>
    <div id="rw-panel">
      <h2>
        {"Reaction Wheel Torques (mN·m)"}
      </h2>
      <div className="rw-row">
        <span className="rw-label">
          {"Sim Time"}
        </span>
        <span className="rw-value" id="rw-time">
          {"0.00 s"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Mode"}
        </span>
        <span className="rw-value" id="rw-mode">
          {"DETUMBLE"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Moon Pointing Error"}
        </span>
        <span className="rw-value" id="moon-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Nadir Pointing Error"}
        </span>
        <span className="rw-value" id="nadir-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Sun Sweep Error"}
        </span>
        <span className="rw-value" id="sunsweep-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Sun Pointing (RW) Error"}
        </span>
        <span className="rw-value" id="sun-ptg-rw-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Nominal In-Orbit Error"}
        </span>
        <span className="rw-value" id="nominal-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Kinematic Robustness Error"}
        </span>
        <span className="rw-value" id="kinrob-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"RW1"}
        </span>
        <span className="rw-value" id="rw1">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"RW2"}
        </span>
        <span className="rw-value" id="rw2">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"RW3"}
        </span>
        <span className="rw-value" id="rw3">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">{
            /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
          }
          {"RW4"}
        </span>
        <span className="rw-value" id="rw4">
          {"0.000"}
        </span>
      </div>
    </div>
    <div id="mtr-panel">
      <h2>
        {"Magnetorquer Telemetry"}
      </h2>
      <div className="rw-row">
        <span className="rw-label">
          {"Sim Time"}
        </span>
        <span className="rw-value" id="mtr-time">
          {"0.00 s"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Mode"}
        </span>
        <span className="rw-value" id="mtr-mode">
          {"DETUMBLE"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Sun Pointing Error"}
        </span>
        <span className="rw-value" id="sun-ptg-err" style={{
          "color": "#7fff7f"
        }}>
          {"--"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Torque X (N·m)"}
        </span>
        <span className="rw-value" id="tau-x">
          {"0.000e+0"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Torque Y (N·m)"}
        </span>
        <span className="rw-value" id="tau-y">
          {"0.000e+0"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Torque Z (N·m)"}
        </span>
        <span className="rw-value" id="tau-z">
          {"0.000e+0"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Dipole X (A·m²)"}
        </span>
        <span className="rw-value" id="dipole-x">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Dipole Y (A·m²)"}
        </span>
        <span className="rw-value" id="dipole-y">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Dipole Z (A·m²)"}
        </span>
        <span className="rw-value" id="dipole-z">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Current X (A)"}
        </span>
        <span className="rw-value" id="current-x">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Current Y (A)"}
        </span>
        <span className="rw-value" id="current-y">
          {"0.000"}
        </span>
      </div>
      <div className="rw-row">
        <span className="rw-label">
          {"Current Z (A)"}
        </span>
        <span className="rw-value" id="current-z">
          {"0.000"}
        </span>
      </div>
    </div>
  </aside>;
});
