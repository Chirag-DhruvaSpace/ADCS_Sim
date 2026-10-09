/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
/* Static CAD draw-call batching. No decimation or material substitutions. */
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
export async function batchStaticCADAsync(root) {
  if (!window.Worker) return batchStaticCAD(root);
  root.updateMatrixWorld(true);
  const inverse = root.matrixWorld.clone().invert(),
    groups = new Map();
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    const g = mesh.geometry;
    if (mesh.isSkinnedMesh || mesh.isInstancedMesh || Array.isArray(mesh.material) || mesh.material.transparent || Object.keys(g.morphAttributes).length || g.drawRange.start !== 0 || g.drawRange.count !== Infinity) return;
    const key = mesh.material.uuid + ':' + Object.keys(g.attributes).sort().join(',') + ':' + !!g.index;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(mesh);
  });
  const descriptions = [];
  for (const [key, meshes] of groups) if (meshes.length > 1) {
    descriptions.push({
      key,
      meshes: meshes.map(mesh => {
        const attributes = {};
        for (const [name, a] of Object.entries(mesh.geometry.attributes)) attributes[name] = {
          array: a.isInterleavedBufferAttribute ? a.data.array : a.array,
          itemSize: a.itemSize,
          normalized: a.normalized,
          stride: a.isInterleavedBufferAttribute ? a.data.stride : 0,
          offset: a.offset ?? 0
        };
        return {
          attributes,
          index: mesh.geometry.index?.array,
          matrix: inverse.clone().multiply(mesh.matrixWorld).elements
        };
      })
    });
  }
  if (!descriptions.length) return batchStaticCAD(root);
  const worker = new Worker(new URL('./cadBatch.worker.js', import.meta.url), {
    type: 'module'
  });
  let batches;
  try {
    batches = await new Promise((resolve, reject) => {
      worker.onmessage = ({
        data
      }) => data.error ? reject(new Error(data.error)) : resolve(data.batches);
      worker.onerror = event => reject(new Error(event.message));
      // Clone compressed source buffers; transferring them would invalidate
      // the originals needed by the fallback and other GLTF components.
      worker.postMessage(descriptions);
    });
  } catch (error) {
    console.warn('CAD worker unavailable; preparing geometry locally:', error);
    return batchStaticCAD(root);
  } finally {
    worker.terminate();
  }
  const stats = {
      before: 0,
      after: 0,
      trianglesBefore: 0,
      trianglesAfter: 0
    },
    removed = new Set();
  root.traverse(m => {
    if (m.isMesh) {
      stats.before++;
      stats.trianglesBefore += (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3;
    }
  });
  for (const row of batches) {
    const meshes = groups.get(row.key),
      g = new THREE.BufferGeometry();
    for (const [name, a] of Object.entries(row.attributes)) g.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize));
    if (row.index) g.setIndex(new THREE.BufferAttribute(row.index, 1));
    g.boundingBox = new THREE.Box3(new THREE.Vector3().fromArray(row.box[0]), new THREE.Vector3().fromArray(row.box[1]));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3().fromArray(row.sphere[0]), row.sphere[1]);
    const mesh = new THREE.Mesh(g, meshes[0].material);
    mesh.name = 'CAD batch: ' + (meshes[0].material.name || 'material');
    root.add(mesh);
    for (const original of meshes) {
      original.removeFromParent();
      removed.add(original.geometry);
    }
  }
  const used = new Set();
  root.traverse(m => {
    if (m.isMesh) {
      used.add(m.geometry);
      stats.after++;
      stats.trianglesAfter += (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3;
    }
  });
  for (const g of removed) if (!used.has(g)) g.dispose();
  function prune(group) {
    for (const child of [...group.children]) {
      prune(child);
      if (child.isGroup && !child.children.length) child.removeFromParent();
    }
  }
  prune(root);
  root.userData.renderBatchStats = stats;
  return stats;
}
export function batchStaticCAD(root) {
  root.updateMatrixWorld(true);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const inverseRoot = root.matrixWorld.clone().invert();
  const groups = new Map();
  const stats = {
    before: 0,
    after: 0,
    trianglesBefore: 0,
    trianglesAfter: 0
  };
  root.traverse(mesh => {
    if (!mesh.isMesh) return;
    stats.before++;
    const geometry = mesh.geometry;
    const count = geometry.index?.count ?? geometry.attributes.position.count;
    stats.trianglesBefore += count / 3;
    if (mesh.isSkinnedMesh || mesh.isInstancedMesh || Array.isArray(mesh.material) || mesh.material.transparent || Object.keys(geometry.morphAttributes).length || geometry.drawRange.start !== 0 || geometry.drawRange.count !== Infinity) return;
    const key = mesh.material.uuid + ':' + Object.keys(geometry.attributes).sort().join(',') + ':' + !!geometry.index;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(mesh);
  });
  const removedGeometries = new Set();
  for (const meshes of groups.values()) {
    if (meshes.length < 2) continue;
    const geometries = meshes.map(mesh => {
      // Decode quantized/interleaved attributes into floating-point buffers
      // before baking node transforms, avoiding quantization/clamping changes.
      const geometry = new THREE.BufferGeometry();
      for (const [name, attr] of Object.entries(mesh.geometry.attributes)) {
        const buffer = new Float32Array(attr.count * attr.itemSize);
        for (let i = 0; i < attr.count; i++) {
          const offset = i * attr.itemSize;
          buffer[offset] = attr.getX(i);
          if (attr.itemSize > 1) buffer[offset + 1] = attr.getY(i);
          if (attr.itemSize > 2) buffer[offset + 2] = attr.getZ(i);
          if (attr.itemSize > 3) buffer[offset + 3] = attr.getW(i);
        }
        geometry.setAttribute(name, new THREE.BufferAttribute(buffer, attr.itemSize));
      }
      if (mesh.geometry.index) geometry.setIndex(mesh.geometry.index.clone());
      geometry.applyMatrix4(inverseRoot.clone().multiply(mesh.matrixWorld));
      // Baking mirrored transforms also requires reversing face winding.
      if (inverseRoot.clone().multiply(mesh.matrixWorld).determinant() < 0) {
        if (geometry.index) {
          const indices = geometry.index.array;
          for (let i = 0; i < indices.length; i += 3) [indices[i + 1], indices[i + 2]] = [indices[i + 2], indices[i + 1]];
        } else {
          for (const attr of Object.values(geometry.attributes)) {
            for (let i = 0; i < attr.count; i += 3) for (let j = 0; j < attr.itemSize; j++) {
              const a = (i + 1) * attr.itemSize + j,
                b = (i + 2) * attr.itemSize + j;
              [attr.array[a], attr.array[b]] = [attr.array[b], attr.array[a]];
            }
          }
        }
      }
      return geometry;
    });
    const combined = mergeGeometries(geometries, false);
    geometries.forEach(g => g.dispose());
    if (!combined) continue; // Preserve originals if attributes cannot be merged.
    combined.computeBoundingBox();
    combined.computeBoundingSphere();
    const batch = new THREE.Mesh(combined, meshes[0].material);
    batch.name = 'CAD batch: ' + (meshes[0].material.name || 'material');
    root.add(batch);
    for (const mesh of meshes) {
      mesh.removeFromParent();
      removedGeometries.add(mesh.geometry);
    }
  }
  const usedGeometries = new Set();
  root.traverse(mesh => {
    if (mesh.isMesh) {
      usedGeometries.add(mesh.geometry);
      stats.after++;
      stats.trianglesAfter += (mesh.geometry.index?.count ?? mesh.geometry.attributes.position.count) / 3;
    }
  });
  for (const geometry of removedGeometries) if (!usedGeometries.has(geometry)) geometry.dispose();
  function prune(group) {
    for (const child of [...group.children]) {
      prune(child);
      if (child.isGroup && !child.children.length) child.removeFromParent();
    }
  }
  prune(root);
  root.userData.renderBatchStats = stats;
  return stats;
}
