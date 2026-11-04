import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import {createSensorMarkers} from '../src/viewer/spacecraft/SensorMarkers.js';

test('Torquer markers use CAD positions, energized levels, disabled state and independent visibility', () => {
  const previous = globalThis.document;
  globalThis.document = {createElement: () => ({getContext: () => ({
    measureText: text => ({width: text.length * 20}), strokeText() {}, fillText() {}
  })})};
  try {
    const settings = {showMTR: true, showMag: true, sensorGlow: true};
    const model = new THREE.Group(); model.scale.setScalar(2);
    const markers = createSensorMarkers({CONFIG: {MODEL_COM: [0, 0, 0]}, SETTINGS: settings,
      modelHolder: model, satGroup: new THREE.Group()});
    const data = {center_of_mass_body_m: [.01, .02, .03],
      imu_mounts: [{name: 'coil', kind: 'Mag', position: [0, 0, .2]}], imu_mag_valid: true,
      mtr_units: [{name: 'coil', kind: 'MTR', position: [.1, .2, -.3], enabled: true, level: 0}]};
    markers.updateSensorMarkers(data); markers.paintSensorMarkers();
    const coil = markers.sensorMarkers.get('MTR:coil');
    assert.equal(markers.sensorMarkers.size, 2);
    assert.ok(coil.position.distanceTo(new THREE.Vector3(.18, .36, -.66)) < 1e-12);
    assert.equal(coil.material.color.getHex(), 0x303947);
    data.mtr_units[0].level = 1;
    markers.updateSensorMarkers(data); markers.paintSensorMarkers();
    assert.equal(coil.material.color.getHex(), 0xff8a3d);
    settings.showMTR = false; markers.paintSensorMarkers();
    assert.equal(coil.visible, false);
    assert.equal(markers.sensorMarkers.get('coil').visible, true);
    settings.showMTR = true; data.mtr_units[0].enabled = false;
    markers.updateSensorMarkers(data); markers.paintSensorMarkers();
    assert.equal(coil.visible, true);
    assert.equal(coil.material.color.getHex(), 0x303947);
    assert.equal(coil.userData.active, false);
    data.mtr_units[0].enabled = true; settings.sensorGlow = false;
    markers.updateSensorMarkers(data); markers.paintSensorMarkers();
    assert.equal(coil.material.color.getHex(), 0x303947);
    markers.updateSensorMarkers({});
    assert.equal(markers.sensorMarkers.size, 0);
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  }
});
