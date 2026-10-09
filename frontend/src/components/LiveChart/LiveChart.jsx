/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo, useLayoutEffect, useRef } from 'react';
import { drawChart, chartDefs, colours } from './drawChart.js';
import './LiveChart.css';
export default memo(function LiveChart({
  type,
  label,
  samples,
  active
}) {
  const canvas = useRef(null);
  const latestSamples = useRef(samples);
  latestSamples.current = samples;
  useLayoutEffect(() => {
    if (!active) return;
    // Charts show one-second averages and redraw once per second.
    let dirty = true;
    const observer = new ResizeObserver(() => { dirty = true; });
    observer.observe(canvas.current);
    let previous = null;
    const draw = () => {
      if (document.hidden || (!dirty && previous === latestSamples.current)) return;
      drawChart(canvas.current, latestSamples.current);
      previous = latestSamples.current;
      dirty = false;
    };
    draw();
    const timer = setInterval(draw, 1000);
    return () => { clearInterval(timer); observer.disconnect(); };
  }, [type, active]);
  const palette = (type === 'pointing' || type === 'wheels') ? ['#e8f3fb', ...colours] : colours;
  return <figure className="live-chart">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }<div className="chart-legend" data-legend={type}>{chartDefs[type][1].map((name, index) => <span key={name} style={{
        '--series': palette[index]
      }}>{name}</span>)}</div><canvas ref={canvas} data-chart={type} role="img" aria-label={label} /><figcaption>{label} · simulation seconds · last 30 s (1 s averages)</figcaption></figure>;
});
