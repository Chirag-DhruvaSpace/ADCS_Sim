/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo, useEffect, useState } from 'react';
import { useTelemetry } from '../../hooks/useTelemetry.js';
import './MissionHeader.css';
const tabs = ['overview', 'sensors', 'pointing'];
function Clock() {
  const {
    data,
    receivedAt
  } = useTelemetry();
  const [fps, setFps] = useState(null),
    [now, setNow] = useState(performance.now());
  useEffect(() => {
    const update = event => setFps(Number.isFinite(event.detail) ? Math.round(event.detail) : null);
    window.addEventListener('simulation-fps', update);
    const timer = setInterval(() => setNow(performance.now()), 1000);
    return () => {
      window.removeEventListener('simulation-fps', update);
      clearInterval(timer);
    };
  }, []);
  const time = Date.parse(data.timestamp);
  const speedLimited = Number.isFinite(data.simulation_speed_actual) && Number.isFinite(data.simulation_speed_requested) && (data.simulation_speed_requested !== 1 || data.simulation_lag_s > 1);
  const speedLabel = speedLimited ? `Live telemetry | ${data.simulation_speed_actual.toFixed(2)}x / ${data.simulation_speed_requested}x requested` : 'Live telemetry';
  return <div className="mission-clock glass"><div><time id="mission-time">{Number.isFinite(time) ? new Date(time).toLocaleString('en-GB', {
          timeZone: 'UTC',
          day: '2-digit',
          month: 'short',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false
        }) + ' UTC' : 'Awaiting simulation'}</time><small id="mission-status">{!receivedAt ? 'No telemetry received' : now - receivedAt < 5000 ? speedLabel : 'Holding last sample · no new telemetry'}</small></div><span className="mission-fps"><b id="mission-fps">{fps ?? '—'}</b> FPS</span></div>;
}
export default memo(function MissionHeader({
  active,
  onTabChange,
  clear,
  onClearChange
}) {
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const update = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', update);
    return () => document.removeEventListener('fullscreenchange', update);
  }, []);
  function navigate(event, index) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
    onTabChange(tabs[next]);
    document.getElementById('mission-tab-' + tabs[next]).focus();
  }
  return <header className="mission-header">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }<Clock /><nav className="mission-tabs glass" role="tablist" aria-label="Telemetry workspace" style={{
      '--tab-index': tabs.indexOf(active)
    }}><i className="tab-indicator" />{tabs.map((tab, index) => <button className="mission-tab" id={'mission-tab-' + tab} type="button" data-tab={tab} role="tab" aria-controls={'mission-page-' + tab} aria-selected={active === tab} tabIndex={active === tab ? 0 : -1} onClick={() => onTabChange(tab)} onKeyDown={event => navigate(event, index)} key={tab}>{tab[0].toUpperCase() + tab.slice(1)}</button>)}</nav><div className="mission-actions"><button className="mission-action glass mission-clear" type="button" title="Show or hide telemetry" aria-label="Show or hide telemetry" aria-pressed={clear} onClick={() => onClearChange(!clear)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.7" /><path className="eye-slash" d="M3 21 21 3" /></svg></button><button id="fullscreen-toggle" className="glass mission-action" type="button" aria-label="Toggle fullscreen" title="Toggle fullscreen"><img className="mission-icon" src={'/assets/icons/' + (fullscreen ? 'minimize' : 'maximize') + '.svg'} alt="" aria-hidden="true" /></button><button id="axis-toggle" className="glass mission-action" type="button" aria-label="Toggle satellite axes" title="Toggle satellite axes"><span id="tick" /><img className="mission-icon" src="/assets/icons/axis-3d.svg" alt="" aria-hidden="true" /></button><button id="settings-toggle" className="glass mission-action" type="button" aria-label="Viewer settings" title="Viewer settings"><img className="mission-icon" src="/assets/icons/settings.svg" alt="" aria-hidden="true" /></button></div></header>;
});
