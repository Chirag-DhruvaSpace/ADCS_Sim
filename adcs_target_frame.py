from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from engine.orekit_runtime import ensure_initialized


EPOCH_UTC = datetime(2026, 10, 1, 15, 0, 0, tzinfo=timezone.utc)


def build_target_frame(epoch_utc: datetime = EPOCH_UTC):
    """Build the body-to-EME2000 target frame with body -Z at the Sun."""
    ensure_initialized()
    from org.orekit.bodies import CelestialBodyFactory
    from org.orekit.frames import FramesFactory

    sun_pv = CelestialBodyFactory.getSun().getPVCoordinates(
        _absolute_date(epoch_utc), FramesFactory.getEME2000()
    )
    sun0 = np.array([
        sun_pv.getPosition().getX(),
        sun_pv.getPosition().getY(),
        sun_pv.getPosition().getZ(),
    ], dtype=float)
    sun0 /= np.linalg.norm(sun0)
    z_axis = -sun0
    helper = np.array([1.0, 0.0, 0.0]) if abs(z_axis[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    x_axis = np.cross(helper, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    return np.column_stack([x_axis, y_axis, z_axis]), sun0


def _absolute_date(utc_dt: datetime):
    from org.orekit.time import AbsoluteDate, TimeScalesFactory

    return AbsoluteDate(
        utc_dt.year,
        utc_dt.month,
        utc_dt.day,
        utc_dt.hour,
        utc_dt.minute,
        float(utc_dt.second) + utc_dt.microsecond / 1e6,
        TimeScalesFactory.getUTC(),
    )
