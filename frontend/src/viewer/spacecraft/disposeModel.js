// GLTF resources owned by one loaded scene; renderer environment maps are shared.
export function disposeModel(root) {
  const geometries=new Set(), materials=new Set(), textures=new Set();
  root.traverse(object => {
    if (object.geometry) geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : object.material ? [object.material] : []) {
      materials.add(material);
      for (const [key, value] of Object.entries(material)) {
        if (key !== 'envMap' && value?.isTexture) textures.add(value);
      }
    }
  });
  for (const texture of textures) texture.dispose();
  for (const material of materials) material.dispose();
  for (const geometry of geometries) geometry.dispose();
}
