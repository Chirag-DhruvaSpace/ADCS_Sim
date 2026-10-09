/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {getLoadingProgress} from '../../services/loadingProgress.js';
import './LoadingScreen.css';
export default function LoadingScreen({error}) {
  const [state, setState] = useState(getLoadingProgress);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const update = event => setState(event.detail);
    window.addEventListener('viewer-loading', update);
    return () => window.removeEventListener('viewer-loading', update);
  }, []);
  useEffect(() => {
    if (!state.ready) return;
    const timer = setTimeout(() => setDismissed(true), 450);
    return () => clearTimeout(timer);
  }, [state.ready]);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  if (dismissed) return null;
  return createPortal(<div className={'launch-screen' + (state.ready ? ' launch-ready' : '')} role="status" aria-live="polite">
    <div className="launch-brand">
      <img src="/assets/loading/dhruva-logo.webp" alt="Dhruva Space" className="launch-logo" />
      <div className="launch-progress" role="progressbar" aria-label="Loading simulation" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(state.progress)}><span style={{width: state.progress + '%'}} /></div>
      <div className="launch-status">{error || state.message}<span>{Math.round(state.progress)}%</span></div>
    </div>
    <div className="launch-credit">made by chirag malik</div>
  </div>, document.getElementById('launch-root'));
}
