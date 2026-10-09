/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { useEffect, useState } from 'react';
import ViewerLayout from './layouts/ViewerLayout/ViewerLayout.jsx';
import DashboardLayout from './layouts/DashboardLayout/DashboardLayout.jsx';
import SettingsPanel from './components/SettingsPanel/SettingsPanel.jsx';
import { startSimulationEngine } from './viewer/SimulationEngine.js';
import { startDiagramRenderer } from './viewer/diagrams/DiagramRenderer.js';
import './App.css';
import LoadingScreen from './components/LoadingScreen/LoadingScreen.jsx';
import {reportLoading} from './services/loadingProgress.js';
function Simulation({
  configuration
}) {
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false,
      disposeEngine,
      disposeDiagrams;
    startSimulationEngine(configuration).then(dispose => {
      if (cancelled) {
        dispose();
        return;
      }
      disposeEngine = dispose;
      disposeDiagrams = startDiagramRenderer();
      window.dispatchEvent(new CustomEvent('dashboard-tab', {
        detail: window.MissionDashboard?.active || 'overview'
      }));
    }).catch(cause => {
      console.error(cause);
      if (!cancelled)
        /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        { setError('Viewer initialization failed: ' + cause.message); window.dispatchEvent(new CustomEvent('viewer-load-error', {detail: cause.message})); }
    });
    return () => {
      cancelled = true;
      disposeDiagrams?.();
      disposeEngine?.();
    };
  }, [configuration]);
  return <><ViewerLayout /><DashboardLayout configuration={configuration} /><SettingsPanel />{error && <div className="startup-error" role="alert">{error}</div>}</>;
}
export default function App() {
  const [configuration, setConfiguration] = useState(null),
    [error, setError] = useState('');
  useEffect(() => {
    const failed = event => setError(event.detail);
    window.addEventListener('viewer-load-error', failed);
    const controller = new AbortController();
    fetch('/api/viewer/config', {
      signal: controller.signal
    }).then(response => {
      if (!response.ok) throw Error('Backend returned ' + response.status);
      return response.json();
    }).then(data => { reportLoading(10, 'Preparing 3D scene'); setConfiguration(data); }).catch(cause => {
      if (cause.name !== 'AbortError') setError(cause.message);
    });
    return () => {controller.abort(); window.removeEventListener('viewer-load-error', failed);};
  }, []);
  return <>{configuration && <Simulation configuration={configuration} />}<LoadingScreen error={error} /></>;
}
