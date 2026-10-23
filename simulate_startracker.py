"""Ideal star tracker: spacecraft truth quaternion in, sensor quaternion out.

CONFIGURATION (satellite_parameters.yaml)
---------------------------------------
star_tracker.enabled:
  true  : return the supplied truth quaternion unchanged.
  false : return no reading; navigation uses its existing sensor fallback.
Restart the simulation after changing YAML, as with other sensor settings.
This initial tracker has only ideal/on and off modes; it has no nominal,
degraded, or stress error presets.

ERRORS AND LIMITATIONS
----------------------
No added noise, bias, drift, catalog matching, missed stars, Sun/Earth exclusion,
rate limits, or delivery delay is modeled yet. The camera view in the dashboard
is an illustrative preview. Unimplemented optical metrics have no measurement.
The sensor is aligned with the body frame. Quaternions use scalar-first
[w, x, y, z], with the simulator's existing ECI attitude convention.

DATA FLOW
---------
Truth quaternion -> independent copy -> timestamped sensor reading
                 -> compute_simulated_attitude.py absolute-attitude update.
get_raw_data(t_seconds, q_truth) samples once per tick.
get_raw_data() rereads the cached sample. Sampling uses no random numbers,
so enabling the tracker cannot change the other sensors' seeded readings.
Acquisition does not normalize or filter the supplied quaternion; navigation
validates and normalizes an accepted reading. Firmware SITL does not use it.
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class StarTrackerMeasurement:
    t_meas_s: float
    t_arrival_s: float
    quaternion_eci: np.ndarray
    valid: bool = True


class SimulatedStarTracker:
    """Sample once per simulation tick; argument-free calls read the cache."""

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        self._reading = None
        self.update_rate_hz = None

    def get_raw_data(self, t_seconds=None, q_truth=None):
        if not self.enabled:
            return None
        if t_seconds is None:
            return self._reading
        time_s = float(t_seconds)
        if not np.isfinite(time_s):
            raise ValueError('Star tracker sampling time must be finite')
        if self._reading is not None:
            if time_s < self._reading.t_meas_s:
                raise ValueError('Star tracker sampling time must move forward')
            if time_s == self._reading.t_meas_s:
                return self._reading

        quaternion = np.asarray(q_truth, dtype=float).reshape(4)
        if not np.all(np.isfinite(quaternion)) or np.linalg.norm(quaternion) < 1e-12:
            raise ValueError('Star tracker quaternion must be finite and nonzero')
        if self._reading is not None:
            self.update_rate_hz = 1.0 / (time_s - self._reading.t_meas_s)

        # Copy for ownership only: preserve every supplied component exactly.
        self._reading = StarTrackerMeasurement(time_s, time_s, quaternion.copy())
        return self._reading
