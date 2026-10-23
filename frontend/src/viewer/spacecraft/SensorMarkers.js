/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';
export function createSensorMarkers({
  CONFIG,
  SETTINGS,
  modelHolder,
  satGroup
}) {
  const sensorMarkers = new Map();
  let latestData = {};
  let trackerPosition = null;
  const inactiveColor = new THREE.Color(0x303947);
  function createSensorLabel(text) {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 96;
    const context = canvas.getContext('2d');
    context.font = 'bold 48px sans-serif';
    const fontSize = Math.min(48, Math.floor(48 * 240 / context.measureText(text).width));
    context.font = `bold ${fontSize}px sans-serif`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.lineWidth = 8;
    context.strokeStyle = '#101820';
    context.strokeText(text, 128, 48);
    context.fillStyle = '#ffffff';
    context.fillText(text, 128, 48);
    const label = new THREE.Sprite(new THREE.SpriteMaterial({
      map: new THREE.CanvasTexture(canvas),
      depthTest: false,
      depthWrite: false,
      toneMapped: false
    }));
    label.position.set(0, 0.065, 0);
    label.scale.set(0.16, 0.06, 1);
    label.renderOrder = 501;
    return label;
  }
  function updateSensorMarkers(data) {
    latestData = data;
    trackerPosition = modelHolder.children[0]?.userData.starTrackerPositionBodyM;
    const layout = [...(data.imu_mounts || [])];
    if (trackerPosition) {
      layout.push({ name: 'Star tracker', kind: 'StarTracker', position: trackerPosition });
    }
    const alive = new Set();
    let sunSensorNumber = 0;
    for (const item of layout) {
      if (item.kind === 'Sun') sunSensorNumber += 1;
      alive.add(item.name);
      let mesh = sensorMarkers.get(item.name);
      if (!mesh) {
        mesh = new THREE.Mesh(new THREE.SphereGeometry(0.025, 10, 8), new THREE.MeshBasicMaterial({
          color: 0x777777,
          transparent: true,
          depthTest: false,
          depthWrite: false,
          toneMapped: false
        }));
        mesh.renderOrder = 500;
        const label = item.kind === 'Sun' ? `FSS${sunSensorNumber}`
          : item.kind === 'StarTracker' ? 'Star tracker' : item.name;
        mesh.add(createSensorLabel(label));
        satGroup.add(mesh);
        sensorMarkers.set(item.name, mesh);
      }
      const [x, y, z] = item.position;
      const com = data.center_of_mass_body_m || CONFIG.MODEL_COM;
      mesh.userData.bodyPosition = new THREE.Vector3(x - com[0], y - com[1], z - com[2]);
      mesh.position.copy(mesh.userData.bodyPosition);
      mesh.userData.kind = item.kind;
      const cell = (data.sun_arr_cells || []).find(c => c.name === item.name);
      // Firmware SITL: "used" is the firmware's verdict on this head's GETTLM
      // reply (lit and inside +/-35 deg), not the Python reconstruction's.
      const head = (data.fss_heads || []).find(h => h.cell === item.name);
      const sunUsed = head ? head.used : !!cell?.used;
      const unit = (data.imu_units?.[item.kind === 'Gyro' ? 'gyro' : 'mag'] || []).find(u => u.name === item.name);
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      const level = item.kind === 'Sun' ? (cell?.output_pct || 0) / 100
        : item.kind === 'StarTracker' ? Number(data.star_tracker_valid)
        : Number(unit ? unit.used : item.kind === 'Gyro' ? data.imu_gyro_valid : data.imu_mag_valid);
      mesh.userData.level = Number.isFinite(level) ? THREE.MathUtils.clamp(level, 0, 1) : 0;
      mesh.userData.active = item.kind === 'Sun' ? sunUsed : level > 0;
      mesh.userData.color = item.kind === 'Sun' ? (sunUsed ? 0xff8800 : 0xffe600)
        : item.kind === 'StarTracker' ? 0x2986ff : item.kind === 'Gyro' ? 0x25c76f : 0x9b59e8;
    }
    for (const [name, mesh] of sensorMarkers) if (!alive.has(name)) {
      satGroup.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      for (const label of mesh.children) {
        label.material.map.dispose();
        label.material.dispose();
      }
      sensorMarkers.delete(name);
    }
  }
  function paintSensorMarkers(visible = true) {
    // A model can finish loading after the last telemetry receipt.
    if (trackerPosition !== modelHolder.children[0]?.userData.starTrackerPositionBodyM) {
      updateSensorMarkers(latestData);
    }
    for (const mesh of sensorMarkers.values()) {
      mesh.visible = visible && SETTINGS['show' + mesh.userData.kind];
      const illuminated = mesh.userData.kind === 'Sun' && mesh.userData.level > 0;
      if (mesh.userData.kind === 'StarTracker') {
        // The tracker stays identifiable in blue even without a valid reading.
        mesh.material.color.setHex(mesh.userData.color);
      } else if (mesh.userData.kind === 'Sun' && (illuminated || mesh.userData.active)) {
        // Keep selected sensors orange; sunlight controls the other sensors' brightness.
        mesh.material.color.setHex(mesh.userData.color);
        if (!mesh.userData.active) mesh.material.color.lerp(inactiveColor, 1 - mesh.userData.level);
      } else {
        mesh.material.color.setHex(mesh.userData.active ? mesh.userData.color : 0x303947);
      }
      mesh.material.opacity = SETTINGS.sensorGlow && (mesh.userData.active || illuminated) ? 1 : 0.85;
      mesh.scale.setScalar(modelHolder.scale.x);
      mesh.position.copy(mesh.userData.bodyPosition).multiplyScalar(modelHolder.scale.x);
    }
  }
  return {
    sensorMarkers,
    updateSensorMarkers,
    paintSensorMarkers
  };
}
