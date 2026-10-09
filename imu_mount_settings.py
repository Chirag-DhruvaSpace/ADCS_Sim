"""Thread-safe runtime mounting changes applied at tick boundaries."""
from dataclasses import replace
from threading import Lock
import numpy as np
import satellite_parameters as config

_lock = Lock()
_pending = None


def mounts(cfg):
    return ([dict(name=c.name, kind='Sun', position=list(c.position_body_m),
                  normal=list(c.normal_body), fov=c.fov_half_angle_deg) for c in cfg.sun_array.cells]
            + [dict(name=unit.name, kind=label,
                    position=list(unit.position_body_m or getattr(cfg, kind + '_position_body_m')),
                    enabled=unit.enabled)
               for kind, label in [('gyro', 'Gyro'), ('mag', 'Mag')]
               for unit in cfg.sensor_units(kind)])


def get_mounts():
    with _lock:
        return mounts(_pending if _pending is not None else config.IMU_SIM)


def request_mount(data):
    global _pending
    if not isinstance(data, dict):
        raise ValueError('Expected a mounting object')
    position = np.asarray(data.get('position'), float)
    if position.shape != (3,) or not np.all(np.isfinite(position)):
        raise ValueError('Position must contain three finite coordinates in metres')
    with _lock:
        cfg = _pending if _pending is not None else config.IMU_SIM
        name = data.get('name')
        group = next((key for key in ('gyros', 'magnetometers')
                      if any(unit.name == name for unit in getattr(cfg, key))), None)
        if group:
            candidate = replace(cfg, **{group: tuple(
                replace(unit, position_body_m=tuple(position)) if unit.name == name else unit
                for unit in getattr(cfg, group))})
        elif name in ('Gyroscope', 'Magnetometer'):
            key = 'gyro_position_body_m' if name == 'Gyroscope' else 'mag_position_body_m'
            candidate = replace(cfg, **{key: tuple(position)})
        else:
            if name not in [c.name for c in cfg.sun_array.cells]:
                raise ValueError('Unknown IMU sensor')
            normal = np.asarray(data.get('normal'), float)
            if normal.shape != (3,) or not np.all(np.isfinite(normal)) or np.linalg.norm(normal) < 1e-12:
                raise ValueError('Sun normal must be a finite nonzero 3-vector')
            cells = tuple(replace(c, position_body_m=tuple(position),
                                  normal_body=tuple(normal / np.linalg.norm(normal)),
                                  fov_half_angle_deg=float(data.get('fov', c.fov_half_angle_deg)))
                          if c.name == name else c for c in cfg.sun_array.cells)
            candidate = replace(cfg, sun_array=replace(cfg.sun_array, cells=cells))
        _pending = candidate
        return mounts(candidate)


def consume_mount_config():
    global _pending
    with _lock:
        result, _pending = _pending, None
        return result


def save_mount_defaults():
    """Persist mounting defaults in the canonical YAML configuration."""
    import os
    import tempfile
    import yaml
    from pathlib import Path
    with _lock:
        cfg = _pending if _pending is not None else config.IMU_SIM
        values = {m['name']: {k: v for k, v in m.items()
                             if k in ('position', 'normal', 'fov')} for m in mounts(cfg)}
        source = Path(config.__file__).resolve().with_suffix('.yaml')
        original = source.read_bytes()
        # utf-8-sig accepts both BOM and BOM-free files and removes the marker
        # before rebuilding the text. The saved YAML is plain UTF-8 so callers
        # receive identical behavior whether they parse bytes, a stream, or text.
        content = original.decode('utf-8-sig')
        # Locate the key itself so documentation headings above it may evolve
        # without breaking the viewer's save-defaults action.
        marker = '\nimu_mount_defaults:'
        if content.count(marker) != 1:
            raise ValueError('Canonical mounting section is missing or ambiguous')
        prefix = content[:content.index(marker) + 1]
        block = yaml.safe_dump({'imu_mount_defaults': values}, sort_keys=False,
                               allow_unicode=True, default_flow_style=False)
        updated = prefix + block
        fd, temporary = tempfile.mkstemp(prefix='.imu-defaults-', dir=source.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(updated.encode('utf-8'))
            if source.read_bytes() != original:
                raise ValueError('Parameters changed during save; retry after reviewing edits')
            os.replace(temporary, source)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return values
