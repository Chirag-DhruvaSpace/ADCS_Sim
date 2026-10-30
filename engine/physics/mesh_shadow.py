"""Static CAD triangle occlusion for sun heads, with a prebuilt bounding tree.

The facet force model retains its documented envelope geometry. This narrow
phase is for sensor rays through a non-solid panel envelope (holes/cutouts).
"""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = ROOT / '.cache' / 'model-occlusion'


def build_tree(vertices, triangles):
    """Build once during model preparation; runtime rays only traverse the tree."""
    points = vertices[triangles]
    centers, triangle_lo, triangle_hi = points.mean(axis=1), points.min(axis=1), points.max(axis=1)
    del points
    order, bounds, children, leaves = [], [], [], []
    def partition(ids):
        index = len(bounds)
        lo, hi = triangle_lo[ids].min(axis=0), triangle_hi[ids].max(axis=0)
        bounds.append((lo-1e-9, hi+1e-9)); children.append((-1, -1)); leaves.append((0, 0))
        if len(ids) <= 32:
            leaves[index] = (len(order), len(ids)); order.extend(ids)
        else:
            axis = int(np.argmax(hi-lo)); middle = len(ids)//2
            ids = ids[np.argpartition(centers[ids, axis], middle)]
            children[index] = (partition(ids[:middle]), partition(ids[middle:]))
        return index
    if len(triangles) == 0:
        raise ValueError('Selected CAD node has no triangles')
    partition(np.arange(len(triangles)))
    bounds = np.asarray(bounds)
    return dict(vertices=vertices, triangles=triangles[order], lo=bounds[:, 0], hi=bounds[:, 1],
                children=np.asarray(children, dtype=np.int32), leaves=np.asarray(leaves, dtype=np.int32))


@lru_cache(maxsize=32)
def _source_digest(path, size, modified_ns):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_cache_path(model_file, node, scale=1.):
    path = Path(model_file).resolve()
    stat = path.stat()
    digest = _source_digest(str(path), stat.st_size, stat.st_mtime_ns)
    signature = json.dumps([1, digest, node, float(scale)], separators=(',', ':'))
    key = hashlib.sha256(signature.encode()).hexdigest()
    return CACHE_ROOT / f'{key}.npz', digest


def load_model_occluder(model_file, node, scale=1.):
    """Prepare a cache from YAML-selected geometry; no satellite names in code."""
    cache, digest = model_cache_path(model_file, node, scale)
    if not cache.is_file():
        decoder = ROOT / 'frontend' / 'scripts' / 'decodeModelGeometry.mjs'
        try:
            decoded = subprocess.check_output(['node', str(decoder), str(model_file), node], cwd=ROOT,
                stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.CalledProcessError) as error:
            details = getattr(error, 'stderr', b'').decode(errors='replace')
            raise ValueError(f'Could not prepare CAD node {node!r} from {model_file}: {details or error}') from error
        count, indices = struct.unpack_from('<II', decoded)
        vertices = np.frombuffer(decoded, dtype='<f8', count=count*3, offset=8).reshape(-1, 3)*scale
        triangles = np.frombuffer(decoded, dtype='<u4', count=indices, offset=8+count*24).reshape(-1, 3)
        arrays = build_tree(vertices, triangles)
        cache.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache.parent, suffix='.npz', delete=False) as temporary:
            name = temporary.name
        try:
            np.savez_compressed(name, **arrays, source_sha256=digest, source_node=node)
            os.replace(name, cache)
        finally:
            Path(name).unlink(missing_ok=True)
    return load_occluder(str(cache))


def ray_hits_triangles(origin, direction, vertices, triangles):
    """Two-sided Moller-Trumbore test; only intersections ahead of the sensor."""
    points = vertices[triangles]
    a = points[:, 0]
    e1, e2 = points[:, 1]-a, points[:, 2]-a
    h = np.cross(direction, e2)
    determinant = np.einsum('ij,ij->i', e1, h)
    valid = np.abs(determinant) > 1e-15
    if not np.any(valid):
        return False
    a, e1, e2, h, determinant = a[valid], e1[valid], e2[valid], h[valid], determinant[valid]
    delta = origin-a
    u = np.einsum('ij,ij->i', delta, h)/determinant
    q = np.cross(delta, e1)
    v = q @ direction/determinant
    t = np.einsum('ij,ij->i', e2, q)/determinant
    return bool(np.any((u >= -1e-9) & (v >= -1e-9) & (u+v <= 1+1e-9) & (t > 1e-7)))


class MeshOccluder:
    def __init__(self, path):
        with np.load(path, allow_pickle=False) as data:
            self.vertices = data['vertices']
            self.triangles = data['triangles']
            self.lo, self.hi = data['lo'], data['hi']
            self.children, self.leaves = data['children'], data['leaves']

    def intersects(self, origin, direction):
        origin, direction = np.asarray(origin), np.asarray(direction)
        parallel = np.abs(direction) < 1e-15
        stack = [0]
        while stack:
            index = stack.pop()
            near, far = 0., np.inf
            for axis in range(3):
                lo, hi = self.lo[index, axis], self.hi[index, axis]
                if parallel[axis]:
                    if not lo <= origin[axis] <= hi:
                        break
                else:
                    a, b = (lo-origin[axis])/direction[axis], (hi-origin[axis])/direction[axis]
                    near, far = max(near, min(a, b)), min(far, max(a, b))
                    if far < near:
                        break
            else:
                if far <= 1e-7:
                    continue
                left, right = self.children[index]
                if left >= 0:
                    stack.extend((int(left), int(right)))
                else:
                    start, count = self.leaves[index]
                    if ray_hits_triangles(origin, direction, self.vertices, self.triangles[start:start+count]):
                        return True
        return False


@lru_cache(maxsize=8)
def load_occluder(relative_path):
    path = Path(relative_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return MeshOccluder(path)
