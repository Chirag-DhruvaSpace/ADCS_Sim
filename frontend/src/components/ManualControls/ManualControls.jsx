/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { memo } from 'react';
import './ManualControls.css';
export default memo(function ManualControls() {
  return <div className="control-panel">{['yaw', 'pitch', 'roll'].map(axis => <div className="card" key={axis}><h3>{axis[0].toUpperCase() + axis.slice(1)}</h3><div className="display">{
          /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
        }<span id={axis + '-label'}>0</span>°</div><div className="controls"><button onClick={() => window.adjust(axis, -.5)}>−0.5°</button><input type="range" id={axis + '-slider'} min="-180" max="180" defaultValue="0" onInput={event => window.sendData(axis, event.currentTarget.value)} /><button onClick={() => window.adjust(axis, .5)}>+0.5°</button></div></div>)}</div>;
});
