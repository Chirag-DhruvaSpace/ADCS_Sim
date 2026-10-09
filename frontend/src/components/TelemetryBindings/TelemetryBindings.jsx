/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from "react";
import "./TelemetryBindings.css";
export default memo(function TelemetryBindings() {
  return <aside id="inspector-dock" hidden={true}>
    <div id="telemetry">
      <div className="tlm-tabs">
        <button className="tlm-tab active" id="tlm-tab-tlm" type="button">
          {"Telemetry"}
        </button>
        <button className="tlm-tab" id="tlm-tab-sen" type="button">
          {"Sensors"}
        </button>
      </div>
      <div className="tlm-page" id="tlm-page-tlm">
        <span id="timestamp">
          {"Timestamp: --"}
        </span>
        <span id="lat">
          {"Lat: --"}
        </span>
        <span id="lon">
          {"Lon: --"}
        </span>
        <span id="alt">
          {"Alt: --"}
        </span>
        <span id="yaw">
          {"Yaw: --"}
        </span>
        <span id="pitch">
          {"Pitch: --"}
        </span>
        <span id="roll">
          {"Roll: --"}
        </span>
        <span id="target_yaw">
          {"Required Yaw (sun pointing): --"}
        </span>
        <span id="target_pitch">
          {"Required Pitch (sun pointing): --"}
        </span>
        <span id="target_roll">
          {"Required Roll (sun pointing): --"}
        </span>
        <span id="body_rate_x">
          {"X body rate: --"}
        </span>
        <span id="body_rate_y">
          {"Y body rate: --"}
        </span>
        <span id="body_rate_z">
          {"Z body rate: --"}
        </span>
        <span id="alpha_x">
          {"X angular acceleration: --"}
        </span>
        <span id="alpha_y">
          {"Y angular acceleration: --"}
        </span>
        <span id="alpha_z">
          {"Z angular acceleration: --"}
        </span>
        <span id="truth_pos_eci">
          {"Real pos (ECI): --"}
        </span>
        <span id="gps_pos_eci">
          {"GPS pos (ECI): off"}
        </span>
        <span id="imu_gyro">
          {"IMU gyro (rad/s): --"}
        </span>
        <span id="imu_mag">
          {"IMU mag (nT): --"}
        </span>
        <details id="disturbance-panel">
          <summary>
            {"Disturbance Torques (click to open)"}
          </summary>
          <span id="srp_acceleration">
            {"SRP acceleration (ECI): --"}
          </span>
          <span id="srp_torque">
            {"SRP torque: --"}
          </span>
          <span id="spacecraft-configuration">
            {"Configuration: --"}
          </span>
          <span id="eclipse_fraction">
            {"Eclipse illumination: --"}
          </span>
          <span id="drag_acceleration">
            {"Drag acceleration (ECI): --"}
          </span>
          <span id="dist_gg">{
              /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
            }
            {"Gravity-gradient torque: --"}
          </span>
          <span id="dist_dipole">
            {"Residual-dipole torque: --"}
          </span>
          <span id="dist_drag">
            {"Atmospheric-drag torque: --"}
          </span>
          <span id="dist_net">
            {"Net disturbance torque: --"}
          </span>
        </details>
      </div>
      <div className="tlm-page" id="tlm-page-sensors" hidden={true}>
        <div className="sens-hint">
          {"MEASURED | TRUTH | ERROR -- the flight software only ever sees MEASURED."}
        </div>
        <div className="sens-sec" id="sens-sec-gps">
          <h4>
            {"GPS receiver"}
          </h4>
          <div id="sen-gps-body">
            {"--"}
          </div>
        </div>
        <div className="sens-sec" id="sens-sec-gyro">
          <h4>
            {"IMU · Gyroscope (deg/s)"}
          </h4>
          <div className="sens-head3">
            <span>
              {"MEASURED"}
            </span>
            <span>
              {"TRUTH"}
            </span>
            <span>
              {"ERROR"}
            </span>
          </div>
          <div id="sen-gyro-body">
            {"--"}
          </div>
          <div id="sen-gyro-flags" className="sens-flags">
            {"--"}
          </div>
        </div>
        <div className="sens-sec" id="sens-sec-mag">
          <h4>
            {"IMU · Magnetometer (nT)"}
          </h4>
          <div className="sens-head3">
            <span>
              {"MEASURED"}
            </span>
            <span>
              {"TRUTH"}
            </span>
            <span>
              {"ERROR"}
            </span>
          </div>
          <div id="sen-mag-body">
            {"--"}
          </div>
          <div id="sen-mag-flags" className="sens-flags">
            {"--"}
          </div>
        </div>
        <div className="sens-sec" id="sens-sec-sun">
          <h4>
            {"IMU · Sun sensor array"}
          </h4>
          <div id="sen-sun-status">
            {"--"}
          </div>
          <table id="sen-sun-cells">
          </table>
          <div id="sen-sun-recon">
            {"--"}
          </div>
        </div>
        <div className="sens-sec" id="sens-sec-est">
          <h4>
            {"Estimator"}
          </h4>
          <div id="sen-est">
            {"--"}
          </div>
        </div>
      </div>
      <span id="status">
        {"Waiting for data... run the propagator script."}
      </span>
    </div>
  </aside>;
});
