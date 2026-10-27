import { memo } from 'react';
import './ManualControls.css';
export default memo(function ManualControls() {
  return <div className="control-panel" role="group" aria-label="Manual attitude commands">
    {['yaw', 'pitch', 'roll'].map(axis => <div className="manual-axis" key={axis}>
      <label htmlFor={axis + '-slider'}>{axis[0].toUpperCase() + axis.slice(1)} <span><span id={axis + '-label'}>0</span>&deg;</span></label>
      <div className="manual-axis-controls">
        <button aria-label={'Decrease ' + axis + ' by 0.5 degrees'} onClick={() => window.adjust(axis, -.5)}>&minus;</button>
        <input type="range" id={axis + '-slider'} min="-180" max="180" step="0.5" defaultValue="0" onInput={event => window.sendData(axis, event.currentTarget.value)} />
        <button aria-label={'Increase ' + axis + ' by 0.5 degrees'} onClick={() => window.adjust(axis, .5)}>+</button>
      </div>
    </div>)}
  </div>;
});
