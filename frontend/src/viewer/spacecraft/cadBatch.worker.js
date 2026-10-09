/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
/* Prepare unchanged CAD geometry off the browser's animation thread. */
import * as THREE from 'three';
function decodeAttribute(description) {
  const {
    array,
    itemSize,
    normalized,
    stride,
    offset
  } = description;
  const source = stride ? new THREE.InterleavedBufferAttribute(new THREE.InterleavedBuffer(array, stride), itemSize, offset, normalized) : new THREE.BufferAttribute(array, itemSize, normalized);
  const values = new Float32Array(source.count * itemSize);
  for (let i = 0; i < source.count; i++) {
    const j = i * itemSize;
    values[j] = source.getX(i);
    if (itemSize > 1) values[j + 1] = source.getY(i);
    if (itemSize > 2) values[j + 2] = source.getZ(i);
    if (itemSize > 3) values[j + 3] = source.getW(i);
  }
  return new THREE.BufferAttribute(values, itemSize);
}
self.onmessage = ({
  data: groups
}) => {
  try {
    const batches = [],
      transfers = [];
    for (const {
      key,
      meshes
    } of groups) {
      const geometries = meshes.map(row => {
        const geometry = new THREE.BufferGeometry();
        for (const [name, description] of Object.entries(row.attributes)) geometry.setAttribute(name, decodeAttribute(description));
        if (row.index) geometry.setIndex(new THREE.BufferAttribute(row.index.slice(), 1));
        const matrix = new THREE.Matrix4().fromArray(row.matrix);
        geometry.applyMatrix4(matrix);
        if (matrix.determinant() < 0) {
          if (geometry.index) {
            const indices = geometry.index.array;
            for (let i = 0; i < indices.length; i += 3) [indices[i + 1], indices[i + 2]] = [indices[i + 2], indices[i + 1]];
          } else for (const attribute of Object.values(geometry.attributes)) {
            for (let i = 0; i < attribute.count; i += 3) for (let j = 0; j < attribute.itemSize; j++) {
              const a = (i + 1) * attribute.itemSize + j,
                b = (i + 2) * attribute.itemSize + j;
              /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
              [attribute.array[a], attribute.array[b]] = [attribute.array[b], attribute.array[a]];
            }
          }
        }
        return geometry;
      });
      const attributes = {};
      for (const name of Object.keys(geometries[0].attributes)) {
        const length = geometries.reduce((n, g) => n + g.attributes[name].array.length, 0);
        const array = new Float32Array(length);
        let offset = 0;
        for (const geometry of geometries) {
          array.set(geometry.attributes[name].array, offset);
          offset += geometry.attributes[name].array.length;
        }
        attributes[name] = {
          array,
          itemSize: geometries[0].attributes[name].itemSize
        };
        transfers.push(array.buffer);
      }
      let index = null;
      if (geometries[0].index) {
        const count = geometries.reduce((n, g) => n + g.index.count, 0),
          vertices = geometries.reduce((n, g) => n + g.attributes.position.count, 0);
        index = vertices > 65535 ? new Uint32Array(count) : new Uint16Array(count);
        let offset = 0,
          base = 0;
        for (const g of geometries) {
          for (let i = 0; i < g.index.count; i++) index[offset++] = g.index.array[i] + base;
          base += g.attributes.position.count;
        }
        transfers.push(index.buffer);
      }
      const merged = new THREE.BufferGeometry();
      for (const [name, a] of Object.entries(attributes)) merged.setAttribute(name, new THREE.BufferAttribute(a.array, a.itemSize));
      if (index) merged.setIndex(new THREE.BufferAttribute(index, 1));
      merged.computeBoundingBox();
      merged.computeBoundingSphere();
      batches.push({
        key,
        attributes,
        index,
        box: [merged.boundingBox.min.toArray(), merged.boundingBox.max.toArray()],
        sphere: [merged.boundingSphere.center.toArray(), merged.boundingSphere.radius]
      });
    }
    self.postMessage({
      batches
    }, transfers);
  } catch (error) {
    self.postMessage({
      error: error.message
    });
  }
};
