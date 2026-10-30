"""Sun direction in EME2000, using the same Orekit DE ephemeris as truth.

Public calls without a spacecraft position return Earth-to-Sun direction.
Pass position_eci_m for the spacecraft-to-Sun line of sight. Dates without
an offset retain the historical interpretation as UTC; aware dates are
normalized to UTC. No mean-of-date vector is presented as J2000/EME2000.
"""
from datetime import datetime, timezone
from functools import lru_cache
import numpy as np


@lru_cache(maxsize=1024)
def _sun_position(utc_dt):
    from engine.orekit_runtime import ensure_initialized
    ensure_initialized()
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    from org.orekit.bodies import CelestialBodyFactory
    from org.orekit.frames import FramesFactory
    date = AbsoluteDate(utc_dt.year, utc_dt.month, utc_dt.day, utc_dt.hour,
                        utc_dt.minute, utc_dt.second + utc_dt.microsecond/1e6,
                        TimeScalesFactory.getUTC())
    position = CelestialBodyFactory.getSun().getPosition(date, FramesFactory.getEME2000())
    return (position.getX(), position.getY(), position.getZ())


def sun_vector_eci(utc_dt: datetime, position_eci_m=None) -> np.ndarray:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    utc_dt = utc_dt.astimezone(timezone.utc)
    direction = np.array(_sun_position(utc_dt), dtype=float)
    if position_eci_m is not None:
        direction -= np.asarray(position_eci_m, dtype=float).reshape(3)
    return direction / np.linalg.norm(direction)


def sun_ra_dec_deg(utc_dt: datetime):
    direction = sun_vector_eci(utc_dt)
    return (float(np.degrees(np.arctan2(direction[1], direction[0])) % 360),
            float(np.degrees(np.arcsin(direction[2]))))


if __name__ == '__main__':
    for month, day in [(3, 20), (6, 21), (9, 22), (12, 21)]:
        epoch = datetime(2026, month, day, 12, tzinfo=timezone.utc)
        ra, dec = sun_ra_dec_deg(epoch)
        print(f'{epoch.isoformat()}  RA={ra:.3f} deg  Dec={dec:.3f} deg (EME2000)')
