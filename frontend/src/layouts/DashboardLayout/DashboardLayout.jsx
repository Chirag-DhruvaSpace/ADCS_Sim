/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import MissionHeader from '../header/MissionHeader.jsx';
import WorkspacePages from '../../routes/WorkspacePages.jsx';
import { telemetryStore } from '../../services/telemetryStore.js';
import { useTelemetry } from '../../hooks/useTelemetry.js';
import './DashboardLayout.css';
import './DashboardLayout.layout.css';
import './DashboardLayout.glass.css';
// Bare eye-mode mirror of the Pointing card's link dots. Identical
// .quaternion-lights markup (pixel-identical, no wrapper, no background),
// parked at the card's screen spot. Lives outside the sliding section so
// rail transforms/opacity can't touch it. Same store subscription as the
// header clock -- no extra fetch.
function ClearDots({ configuration, clear }) {
  const { data } = useTelemetry();
  if (!clear || configuration?.pointing_strategy === 'legacy') return null;
  const status = data.custom_pointing_status || 'red';
  const isSitl = data.mode === 'FIRMWARE_SITL' || data.ads_mode !== undefined;
  const label = (isSitl ? 'Firmware link: ' : 'Quaternion command: ') + status;
  return <span className="quaternion-lights clear-dots" role="status" aria-label={label}>{['red', 'green', 'blue', 'yellow'].map(color => <i key={color} data-color={color} className={status === color ? 'lit' : ''} />)}</span>;
}
export default function DashboardLayout({
  configuration
}) {
  const [active, setActive] = useState('overview'),
    [clear, setClear] = useState(false),
    [suspended, setSuspended] = useState(false);
  const currentTab = useRef(active);
  currentTab.current = active;
  useEffect(() => {
    const accept = event => telemetryStore.accept(event.detail);
    window.addEventListener('simulation-telemetry', accept);
    window.MissionDashboard = {
      get latest() {
        return telemetryStore.getSnapshot().data;
      },
      get active() {
        return currentTab.current;
      },
      get samples() {
        return telemetryStore.getSnapshot().samples;
      }
    };
    const unsubscribe = telemetryStore.subscribe(() => requestAnimationFrame(() => window.dispatchEvent(new Event('dashboard-render'))));
    return () => {
      window.removeEventListener('simulation-telemetry', accept);
      unsubscribe();
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      delete window.MissionDashboard;
    };
  }, []);
  useLayoutEffect(() => {
    const page = document.getElementById('mission-page-' + active);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) page.querySelectorAll('.mission-card').forEach((card, index) => {
      card.getAnimations().forEach(animation => animation.cancel());
      card.animate([{
        opacity: 0,
        transform: `translate3d(${card.closest('.rail-left') ? '-18px' : '18px'},8px,0)`
      }, {
        opacity: 1,
        transform: 'translate3d(0,0,0)'
      }], {
        duration: 520,
        delay: Math.min(index * 25, 100),
        easing: 'cubic-bezier(.16,1,.3,1)',
        fill: 'backwards'
      });
    });
    window.dispatchEvent(new CustomEvent('dashboard-tab', {
      detail: active
    }));
    window.dispatchEvent(new Event('dashboard-render'));
  }, [active]);
  useEffect(() => {
    document.body.classList.toggle('mission-clear-active', clear);
    window.dispatchEvent(new CustomEvent('telemetry-visibility', { detail: !clear }));
    if (!clear) setSuspended(false);
    const timer = clear ? setTimeout(() => setSuspended(true), 500) : null;
    return () => { clearTimeout(timer); document.body.classList.remove('mission-clear-active'); };
  }, [clear]);
  return <><MissionHeader active={active} onTabChange={setActive} clear={clear} onClearChange={setClear} /><ClearDots configuration={configuration} clear={clear} /><section className={'mission-dashboard' + (clear ? ' mission-clear-view' : '')} id="mission-dashboard" data-tab={active}><WorkspacePages active={active} configuration={configuration} suspended={suspended} /></section></>;
}
