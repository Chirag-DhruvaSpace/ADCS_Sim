/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo, useEffect } from "react";
import { bindSettingsPanel } from "../../services/settingsPanel.js";
import "./SettingsPanel.css";
export default memo(function SettingsPanel() {
  useEffect(bindSettingsPanel, []);
  return <>
 <div className="mission-settings-backdrop" onClick={() => window.setSettingsOpen(false)} />
  <div id="settings-panel" className="mission-settings" role="dialog" aria-label="Viewer settings" aria-modal="true">
    <div className="sp-head">
      <span>
        {"Viewer settings"}
      </span>
      <button id="settings-close" aria-label="Close settings">
        <img src="/assets/icons/x.svg" alt="" aria-hidden="true" className="settings-glyph" />
      </button>
    </div>
    <div className="settings-tabs" role="tablist">
      <button type="button" role="tab" data-settings-tab="0" aria-selected="true">
        {"View"}
      </button>
      <button type="button" role="tab" data-settings-tab="1" aria-selected="false">
        {"Scene"}
      </button>
      <button type="button" role="tab" data-settings-tab="2" aria-selected="false">
        {"Sensors"}
      </button>
      <button type="button" role="tab" data-settings-tab="3" aria-selected="false">
        {"Performance"}
      </button>
    </div>
    <div className="settings-content" data-settings-page="0">
      <h3 className="sec" style={{
          "--acc": "#4dd0e1"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Camera"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-attlock">
          {"Chase: lock to attitude"}
        </label>
        <input type="checkbox" id="set-attlock" />
      </div>
      <div className="set-row">
        <label htmlFor="set-smoothAttitude">
          {"Smooth attitude display"}
        </label>
        <input type="checkbox" id="set-smoothAttitude" />
      </div>
      <div className="set-row">
        <label htmlFor="set-chasesens">
          {"Chase drag speed"}
        </label>
        <input type="range" id="set-chasesens" min="0.5" max="3" step="0.1" />
        <span className="val" id="set-chasesens-val">
          {"1.00"}
        </span>
      </div>
      <h3 className="sec" style={{
          "--acc": "#ffb74d"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Satellite Model"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-modelsun">
          {"Sunlight"}
        </label>
        <input type="range" id="set-modelsun" min="0.2" max="2" step="0.05" />
        <span className="val" id="set-modelsun-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-modelenv">
          {"Reflections"}
        </label>
        <input type="range" id="set-modelenv" min="0" max="2" step="0.05" />
        <span className="val" id="set-modelenv-val">
          {"1.00"}
        </span>
      </div>
    </div>
    <div className="settings-content" data-settings-page="1" hidden={true}>
      <h3 className="sec" style={{
          "--acc": "#81c784"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Imagery"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-sharp">
          {"Sharpness"}
        </label>
        <select id="set-sharp">
          <option value="256">
            {"Standard"}
          </option>
          <option value="170">
            {"Sharp"}
          </option>
          <option value="120">
            {"Ultra (most tiles)"}
          </option>
        </select>
      </div>
      <h3 className="sec" style={{
          "--acc": "#64b5f6"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Earth"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-exposure">
          {"Exposure (sat/atmo)"}
        </label>
        <input type="range" id="set-exposure" min="0.4" max="1.8" step="0.05" />
        <span className="val" id="set-exposure-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-night">
          {"Night brightness"}
        </label>
        <input type="range" id="set-night" min="0" max="2.5" step="0.05" />
        <span className="val" id="set-night-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-city">
          {"City lights"}
        </label>
        <input type="range" id="set-city" min="0.2" max="5" step="0.1" />
        <span className="val" id="set-city-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-atmo">
          {"Atmosphere"}
        </label>
        <input type="range" id="set-atmo" min="0" max="1.6" step="0.05" />
        <span className="val" id="set-atmo-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-clouds-on">
          {"Clouds"}
        </label>
        <input type="checkbox" id="set-clouds-on" />
      </div>
      <div className="set-row">
        <label htmlFor="set-clouds">
          {"Cloud opacity"}
        </label>
        <input type="range" id="set-clouds" min="0" max="1" step="0.05" />
        <span className="val" id="set-clouds-val">
          {"0.30"}
        </span>
      </div>
      <h3 className="sec" style={{
          "--acc": "#ba68c8"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Sky"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-stars">
          {"Stars"}
        </label>
        <input type="range" id="set-stars" min="0.2" max="2" step="0.05" />
        <span className="val" id="set-stars-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">{
            /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
          }
        <label htmlFor="set-sunsize">
          {"Sun glare size"}
        </label>
        <input type="range" id="set-sunsize" min="0.3" max="3" step="0.1" />
        <span className="val" id="set-sunsize-val">
          {"1.00"}
        </span>
      </div>
      <div className="set-row">
        <label htmlFor="set-moonsize">
          {"Moon size"}
        </label>
        <input type="range" id="set-moonsize" min="0.3" max="3" step="0.1" />
        <span className="val" id="set-moonsize-val">
          {"1.00"}
        </span>
      </div>
    </div>
    <div className="settings-content" data-settings-page="2" hidden={true}>
      <h3 className="sec">
        {"IMU hardware"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-showSun">
          {"Sun sensor markers"}
        </label>
        <input id="set-showSun" type="checkbox" defaultChecked={true} />
      </div>
      <div className="set-row">
        <label htmlFor="set-showGyro">
          {"Gyroscope marker"}
        </label>
        <input id="set-showGyro" type="checkbox" defaultChecked={true} />
      </div>
      <div className="set-row">
        <label htmlFor="set-showMag">
          {"Magnetometer marker"}
        </label>
        <input id="set-showMag" type="checkbox" defaultChecked={true} />
      </div>
      <div className="set-row">
        <label htmlFor="set-sensorGlow">
          {"Measurement glow"}
        </label>
        <input id="set-sensorGlow" type="checkbox" defaultChecked={true} />
      </div>
      <p>
        {"Sun glow follows measured photocurrent. Gyro and magnetometer glow indicates a valid receipt."}
      </p>
      <div className="set-row">
        <label htmlFor="mount-select">
          {"Mount"}
        </label>
        <select id="mount-select">
        </select>
      </div>
      <div className="set-row">
        <label>
          {"X / Y / Z (m)"}
        </label>
        <div id="mount-position">
          <input aria-label="Mount X" type="number" step="any" />
          <input aria-label="Mount Y" type="number" step="any" />
          <input aria-label="Mount Z" type="number" step="any" />
        </div>
      </div>
      <div className="set-row" id="mount-normal-row">
        <label>
          {"Normal X / Y / Z"}
        </label>
        <div id="mount-normal">
          <input aria-label="Normal X" type="number" step="any" />
          <input aria-label="Normal Y" type="number" step="any" />
          <input aria-label="Normal Z" type="number" step="any" />
        </div>
      </div>
      <div className="set-row" id="mount-fov-row">
        <label htmlFor="mount-fov">
          {"FOV half-angle (deg)"}
        </label>
        <input id="mount-fov" type="number" min="0.1" max="90" step="any" />
      </div>
      <button id="mount-apply" type="button">
        {"Apply mounting"}
      </button>
      <button id="mount-save" type="button">
        {"Save applied mounts as defaults"}
      </button>
      <p id="mount-status" role="status">
      </p>
      <p>
        {"Changes apply at the next simulation tick and restart sensor calibration. Permanent defaults, mount orientations, and field gradients: satellite_parameters.yaml → imu_sim."}
      </p>
    </div>
    <div className="settings-content" data-settings-page="3" hidden={true}>
      <h3 className="sec" style={{
          "--acc": "#ffd166"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Performance"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-preset">
          {"Quality preset"}
        </label>
        <select id="set-preset">
          <option value="auto">
            {"Auto (adaptive — no fps cap)"}
          </option>
          <option value="low">
            {"Low (max fps)"}
          </option>
          <option value="balanced">
            {"Balanced"}
          </option>
          <option value="high">
            {"High"}
          </option>
          <option value="ultra">
            {"Ultra (native res)"}
          </option>
          <option value="4k">
            {"4K (supersampled)"}
          </option>
        </select>
      </div>
      <div className="set-row">
        <label htmlFor="set-fps">
          {"FPS meter"}
        </label>
        <input type="checkbox" id="set-fps" />
      </div>
      <div className="set-row">
        <label htmlFor="set-simfeed">
          {"Sim feed meter"}
        </label>
        <input type="checkbox" id="set-simfeed" defaultChecked={true} />
      </div>
      <h3 className="sec" style={{
          "--acc": "#ff8a80"
        }}>
        <span className="ico" aria-hidden="true">&#9670;</span>
        {"Video Stream (ws://8765)"}
      </h3>
      <div className="set-row">
        <label htmlFor="set-stream-on">
          {"Enabled"}
        </label>
        <input type="checkbox" id="set-stream-on" />
      </div>
      <div className="set-row">
        <label htmlFor="set-streamsize">
          {"Resolution"}
        </label>
        <select id="set-streamsize">
          <option value="640x480">
            {"640×480"}
          </option>
          <option value="800x600">
            {"800×600"}
          </option>
          <option value="1024x768">
            {"1024×768"}
          </option>
          <option value="1280x960">
            {"1280×960"}
          </option>
        </select>
      </div>
      <div className="set-row">
        <label htmlFor="set-streamq">
          {"JPEG quality"}
        </label>
        <input type="range" id="set-streamq" min="0.4" max="0.95" step="0.05" />
        <span className="val" id="set-streamq-val">
          {"0.90"}
        </span>
      </div>
    </div>
  </div>
 </>;
});
