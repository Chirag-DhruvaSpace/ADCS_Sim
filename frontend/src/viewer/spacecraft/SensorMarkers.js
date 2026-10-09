/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';
export function createSensorMarkers({
  CONFIG,
  SETTINGS,
  modelHolder,
  satGroup
}) {
  const sensorMarkers = new Map();
  function updateSensorMarkers(data) {
    const layout = data.imu_mounts || [];
    const alive = new Set();
    for (const item of layout) {
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
        satGroup.add(mesh);
        sensorMarkers.set(item.name, mesh);
      }
      const [x, y, z] = item.position;
      const com = data.center_of_mass_body_m || CONFIG.MODEL_COM;
      mesh.userData.bodyPosition = new THREE.Vector3(x - com[0], y - com[1], z - com[2]);
      mesh.position.copy(mesh.userData.bodyPosition);
      mesh.userData.kind = item.kind;
      const cell = (data.sun_arr_cells || []).find(c => c.name === item.name);
      const unit = (data.imu_units?.[item.kind === 'Gyro' ? 'gyro' : 'mag'] || []).find(u => u.name === item.name);
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      const level = item.kind === 'Sun' ? (cell?.output_pct || 0) / 100 : Number(unit ? unit.used : item.kind === 'Gyro' ? data.imu_gyro_valid : data.imu_mag_valid);
      mesh.userData.level = Number.isFinite(level) ? level : 0;
      mesh.userData.active = item.kind === 'Sun' ? !!cell?.used : level > 0;
      mesh.userData.color = item.kind === 'Sun' ? 0xc65b12 : item.kind === 'Gyro' ? 0x25c76f : 0x9b59e8;
    }
    for (const [name, mesh] of sensorMarkers) if (!alive.has(name)) {
      satGroup.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      sensorMarkers.delete(name);
    }
  }
  function paintSensorMarkers() {
    for (const mesh of sensorMarkers.values()) {
      mesh.visible = SETTINGS['show' + mesh.userData.kind];
      mesh.material.color.setHex(mesh.userData.active ? mesh.userData.color : 0x303947);
      mesh.material.opacity = SETTINGS.sensorGlow && mesh.userData.active ? 1 : 0.85;
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
