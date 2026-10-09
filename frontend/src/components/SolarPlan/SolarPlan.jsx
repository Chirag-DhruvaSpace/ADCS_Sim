/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo, useLayoutEffect, useRef } from 'react';
import { drawSolarPlan } from './drawSolarPlan.js';
import './SolarPlan.css';
export default memo(function SolarPlan({
  data,
  active
}) {
  const canvas = useRef(null);
  const latestData = useRef(data);
  latestData.current = data;
  useLayoutEffect(() => {
    if (!active) return;
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    const draw = () => drawSolarPlan(canvas.current, latestData.current);
    const observer = new ResizeObserver(draw);
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, [active]);
  useLayoutEffect(() => {
    if (active) drawSolarPlan(canvas.current, data);
  }, [data, active]);
  return <canvas ref={canvas} id="solar-plan" role="img" aria-label="Schematic Sun, Earth, Moon and live spacecraft orbital phase; distances are not to scale" />;
});
