"""gps_navigation.py -- turns raw GPS receiver messages into what the
satellite actually needs, and feeds it to the satellite.

PLAIN LANGUAGE: the receiver (simulategps.SimulatedGPS) speaks "floor book"
coordinates (ECEF) once per second, slightly wrong like a real chip. The
satellite's attitude controllers think in "star book" coordinates (ECI).
This file is the little onboard calculator in between:

  1. It holds the satellite's POSITION/VELOCITY BELIEF. Before the first GPS
     fix arrives, the belief is simply the launch-vehicle-provided starting
     state (that is all the satellite knows).
  2. Every accepted GPS fix replaces the belief with the fix's position and
     velocity, converted from ECEF to ECI exactly the way real flight
     software converts it.
  3. Between the once-per-second fixes it DEAD-RECKONS: last believed
     position + last believed velocity x elapsed time. (Real systems do
     exactly this between fixes; a full navigation filter is future work.)

The main simulation loop reads `extrapolate(t)` from here every tick and
gives the result to the attitude controllers INSTEAD of the perfect truth.
"""

from __future__ import annotations

import numpy as np

from simulategps import GpsMeasurement


class GpsNav:
    """The satellite's onboard POSITION/VELOCITY KNOWLEDGE holder."""

    def __init__(self, r0_eci, v0_eci) -> None:
        self._pos = np.asarray(r0_eci, dtype=float).reshape(3).copy()
        self._vel = np.asarray(v0_eci, dtype=float).reshape(3).copy()
        self._t_meas = None          # sim time of the last fix (None = none yet)
        self._last_fix = None        # last GpsMeasurement, for telemetry
        self.gps_fix = False         # did the most recent 1 Hz boundary deliver a fix?

    def register_fix(self, msg: GpsMeasurement, boundary_had_fix: bool = True) -> None:
        """Adopt a fresh fix as the current belief."""
        self._pos = np.asarray(msg.nav_pos_eci_m, dtype=float).reshape(3).copy()
        self._vel = np.asarray(msg.nav_vel_eci_mps, dtype=float).reshape(3).copy()
        self._t_meas = float(msg.t_meas_s)
        self._last_fix = msg
        self.gps_fix = bool(boundary_had_fix)

    def register_boundary_no_fix(self) -> None:
        """A 1 Hz boundary passed with no fix (dropout/cold start): the
        belief is kept, but gps_fix goes False for the telemetry."""
        self.gps_fix = False

    def extrapolate(self, t_seconds):
        """Belief at sim time t: last fix + velocity x elapsed time (never a
        negative age). Returns (r_eci, v_eci) as fresh arrays."""
        if self._t_meas is None:
            return self._pos.copy(), self._vel.copy()
        age = max(0.0, float(t_seconds) - self._t_meas)
        return self._pos + self._vel * age, self._vel.copy()

    def telemetry(self) -> dict:
        """Dashboard fields from the last fix (None values before any fix)."""
        if self._last_fix is None:
            return {"gps_fix": False, "gps_num_sv": None, "gps_pdop": None,
                    "gps_h_acc_m": None, "gps_v_acc_m": None, "gps_lat_deg": None,
                    "gps_lon_deg": None, "gps_alt_m": None, "gps_latency_s": None}
        m = self._last_fix
        return {"gps_fix": bool(self.gps_fix), "gps_num_sv": int(m.num_sv),
                "gps_pdop": float(m.pdop), "gps_h_acc_m": float(m.h_acc_m),
                "gps_v_acc_m": float(m.v_acc_m), "gps_lat_deg": float(m.lat_deg),
                "gps_lon_deg": float(m.lon_deg), "gps_alt_m": float(m.alt_ell_m),
                "gps_latency_s": float(m.latency_s)}


__all__ = ["GpsNav"]
