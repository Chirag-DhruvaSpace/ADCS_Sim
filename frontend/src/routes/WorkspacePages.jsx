/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { useLayoutEffect, useRef, useState } from 'react';
import { useTelemetry } from '../hooks/useTelemetry.js';
import OverviewPage from '../pages/overview/OverviewPage.jsx';
import SensorsPage from '../pages/sensors/SensorsPage.jsx';
import PointingPage from '../pages/pointing/PointingPage.jsx';
import './WorkspacePages.css';
function PageSubscription({
  name,
  active,
  configuration,
  Component,
  suspended,
  leaving
}) {
  const enabled = !suspended && active === name;
  const snapshot = useTelemetry(enabled);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <Component active={enabled} visible={active === name || leaving === name} departing={leaving === name && active !== name} configuration={configuration} {...snapshot} />;
}
export default function WorkspacePages({
  active,
  configuration,
  suspended = false
}) {
  const previous = useRef(active);
  const [leaving, setLeaving] = useState(null);
  useLayoutEffect(() => {
    if (previous.current === active) return;
    setLeaving(previous.current);
    previous.current = active;
    const timer = setTimeout(() => setLeaving(null), 220);
    return () => clearTimeout(timer);
  }, [active]);
  return <><PageSubscription name="overview" active={active} configuration={configuration} suspended={suspended} leaving={leaving} Component={OverviewPage} /><PageSubscription name="sensors" active={active} configuration={configuration} suspended={suspended} leaving={leaving} Component={SensorsPage} /><PageSubscription name="pointing" active={active} configuration={configuration} suspended={suspended} leaving={leaving} Component={PointingPage} /></>;
}
