/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import {memo, useEffect, useState} from 'react';
import './DistanceScale.css';
export default memo(function DistanceScale() {
  const [scale, setScale] = useState(null);
  useEffect(() => {
    const update = event => setScale(event.detail);
    window.addEventListener('overview-scale', update);
    return () => window.removeEventListener('overview-scale', update);
  }, []);
  if (!scale?.metersPerPixel) return null;
  const target = scale.metersPerPixel * 160;
  const power = 10 ** Math.floor(Math.log10(target));
  const meters = [1, 2, 5].filter(v => v * power <= target).at(-1) * power;
  const unit = meters >= 9.4607e15 ? [9.4607e15, 'ly'] : meters >= 1.495978707e11 ? [1.495978707e11, 'AU'] : meters >= 1000 ? [1000, 'km'] : [1, 'm'];
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return <div className="distance-scale" aria-label="View distance scale">
    <span>{scale.approximate ? 'Approx. ' : ''}{(meters / unit[0]).toLocaleString('en-US', {maximumSignificantDigits: 3})} {unit[1]}</span>
    <div className="distance-scale-line" style={{width: meters / scale.metersPerPixel}} />
  </div>;
});
