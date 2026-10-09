/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { reportLoading } from '../../services/loadingProgress.js';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { batchStaticCADAsync } from './cadBatches.js';
export function createSpacecraftLoader({
  CONFIG,
  DRACOLoader,
  KTX2Loader,
  MeshoptDecoder,
  applySettings,
  modelHolder,
  renderer
}) {
  const gltfLoader = new GLTFLoader();
  try {
    if (DRACOLoader) {
      const d = new DRACOLoader();
      d.setDecoderPath('/assets/decoders/draco/gltf/');
      gltfLoader.setDRACOLoader(d);
    }
  } catch (e) {
    console.warn('DRACO unavailable', e);
  }
  try {
    if (KTX2Loader) {
      const k = new KTX2Loader();
      k.setTranscoderPath('/assets/decoders/basis/');
      k.detectSupport(renderer);
      gltfLoader.setKTX2Loader(k);
    }
  } catch (e) {
    console.warn('KTX2 unavailable', e);
  }
  try {
    if (MeshoptDecoder) gltfLoader.setMeshoptDecoder(MeshoptDecoder);
  } catch (e) {}
  const modelMats = [];
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  let loadedModelUrl = null;
  let modelLoadVersion = 0;
  function loadSpacecraftModel(url, com = CONFIG.MODEL_COM) {
    if (!url || url === loadedModelUrl) return;
    loadedModelUrl = url;
    const version = ++modelLoadVersion;
    gltfLoader.load(url, async gltf => {
      if (version !== modelLoadVersion) return;
      reportLoading(65, 'Preparing spacecraft geometry');
      window.spacecraftBatchStats = await batchStaticCADAsync(gltf.scene);
      if (version !== modelLoadVersion) return;
      modelHolder.clear();
      modelMats.length = 0;
      const legacy = /\/P-30XL(?:_orignal)?\.glb(?:$|[?#])/.test(url);
      gltf.scene.scale.setScalar(CONFIG.MODEL_SCALE * (legacy ? .001 : 1));
      if (legacy) {
        // The original model is millimetres and has an offset export origin.
        gltf.scene.updateMatrixWorld(true);
        const center = new THREE.Box3().setFromObject(gltf.scene).getCenter(new THREE.Vector3());
        gltf.scene.position.sub(center);
      }
      gltf.scene.position.sub(new THREE.Vector3(...com));
      // Exported component materials already distinguish structure and hardware.
      gltf.scene.traverse(o => {
        if (o.isMesh) {
          const materials = Array.isArray(o.material) ? o.material : [o.material];
          for (const m of materials) {
            m.envMapIntensity = CONFIG.MODEL_ENV;
            modelMats.push(m);
          }
        }
      });
      modelHolder.add(gltf.scene);
      window.spacecraftRenderAsset = {
        scene: gltf.scene,
        com: [...com]
      };
      window.dispatchEvent(new CustomEvent('spacecraft-model-ready', {
        detail: window.spacecraftRenderAsset
      }));
      reportLoading(80, 'Spacecraft ready');
      applySettings();
    }, event => {
      if (event.total > 0) reportLoading(20 + 42 * event.loaded / event.total, 'Loading spacecraft');
    }, err => {
      window.dispatchEvent(new CustomEvent('viewer-load-error', {detail: 'Spacecraft model could not load. Reload to retry.'}));
      console.warn('CAD GLB failed:', url, err);
      loadedModelUrl = null;
    });
  }
  loadSpacecraftModel(CONFIG.MODEL_URL);
  return {
    modelMats,
    loadSpacecraftModel,
    disposeModelLoader: () => {
      modelLoadVersion++;
      gltfLoader.dracoLoader?.dispose();
      gltfLoader.ktx2Loader?.dispose();
    }
  };
}
