import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sunSignalLevel} from '../src/viewer/spacecraft/sunSignal.js';
import {disposeModel} from '../src/viewer/spacecraft/disposeModel.js';
import {createSensorMarkers} from '../src/viewer/spacecraft/SensorMarkers.js';
import * as THREE from 'three';
import {sunCellLabel} from '../src/services/sensorLabels.js';

test('Telemetry sensor labels include stable FSS numbers and configured names', () => {
  assert.equal(sunCellLabel({name:'-Z'},0),'FSS1 (-Z)');
  assert.equal(sunCellLabel({name:'Payload head',fss_id:'FSS6'},5),'FSS6 (Payload head)');
  assert.equal(sunCellLabel({},2),'FSS3');
});

test('Sun marker brightness follows received fine-head light regardless of eligibility', () => {
  const data={sun_arr_valid:true, fss_heads:[{cell:'head-A',q_sum:2000,full_scale_counts:10000,used:true}],
    sun_arr_cells:[{name:'head-A',output_pct:80,used:true}]};
  assert.equal(sunSignalLevel(data,'head-A'),.2);
  data.fss_heads[0].used=false;
  assert.equal(sunSignalLevel(data,'head-A'),.2);
  data.fss_heads[0].q_sum=500;
  data.fss_heads[0].full_scale_counts=2000;
  assert.equal(sunSignalLevel(data,'head-A'),.25);
  data.fss_heads[0].q_sum=0;
  assert.equal(sunSignalLevel(data,'head-A'),0);
});

test('Dark, missing, invalid and disabled heads do not glow; coarse fallback is bounded', () => {
  const data={sun_arr_valid:true,sun_arr_cells:[{name:'head-B',output_pct:50}]};
  assert.equal(sunSignalLevel(data,'head-B'),.5);
  assert.equal(sunSignalLevel(data,'head-B',false),0);
  assert.equal(sunSignalLevel({...data,sun_arr_valid:false},'head-B'),0);
  assert.equal(sunSignalLevel(data,'absent'),0);
  data.sun_arr_cells[0].output_pct=1000;
  assert.equal(sunSignalLevel(data,'head-B'),1);
  data.sun_arr_cells[0].output_pct=NaN;
  assert.equal(sunSignalLevel(data,'head-B'),0);
});

test('Model cleanup disposes shared asset resources once and retains scene environment', () => {
  const count={geometry:0,material:0,texture:0,environment:0};
  const geometry={dispose:()=>count.geometry++};
  const texture={isTexture:true,dispose:()=>count.texture++};
  const envMap={isTexture:true,dispose:()=>count.environment++};
  const material={map:texture,normalMap:texture,envMap,dispose:()=>count.material++};
  const objects=[{geometry,material},{geometry,material:[material]}];
  disposeModel({traverse:callback=>objects.forEach(callback)});
  assert.deepEqual(count,{geometry:1,material:1,texture:1,environment:0});
});

test('Rendered Sun markers dim in yellow even when a head is eligible', () => {
  const previous=globalThis.document;
  globalThis.document={createElement:()=>({getContext:()=>({measureText:text=>({width:text.length*20}),strokeText(){},fillText(){}})})};
  try {
    const markers=createSensorMarkers({CONFIG:{MODEL_COM:[0,0,0]},
      SETTINGS:{showSun:true,sensorGlow:true},modelHolder:new THREE.Group(),satGroup:new THREE.Group()});
    const data={imu_mounts:[{name:'head-A',kind:'Sun',position:[0,0,0]}],sun_arr_valid:true,
      fss_heads:[{cell:'head-A',q_sum:0,full_scale_counts:10000,used:true}]};
    const brightness=[];
    for(const signal of [0,1000,5000,10000]) {
      data.fss_heads[0].q_sum=signal;
      markers.updateSensorMarkers(data);markers.paintSensorMarkers();
      const color=markers.sensorMarkers.get('head-A').material.color;
      brightness.push(color.r+color.g+color.b);
      if(signal===0) assert.equal(color.getHex(),0x303947);
      if(signal===10000) assert.equal(color.getHex(),0xffe600);
    }
    assert.ok(brightness.every((value,index)=>index===0 || value>brightness[index-1]));
    markers.updateSensorMarkers({imu_mounts:[]});
  } finally {
    if(previous===undefined) delete globalThis.document;else globalThis.document=previous;
  }
});
