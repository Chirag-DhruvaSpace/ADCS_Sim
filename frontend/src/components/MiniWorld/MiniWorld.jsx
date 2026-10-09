/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from 'react';
import './MiniWorld.css';
export default memo(function MiniWorld({
  kind,
  caption
}) {
  // The shared WebGL diagram service commits complete frames to this canvas.
  return <figure className="mini-world">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }<canvas data-globe={kind} aria-label={caption} role="img" /><figcaption>{caption}</figcaption></figure>;
});
