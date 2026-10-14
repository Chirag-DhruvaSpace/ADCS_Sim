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


def decode_orion_fields(raw, epoch_utc, earth_fixed_frame):
    """Convert ORION integers into metres, m/s, degrees and seconds."""
    from simulategps import absolute_date, ReceiverMeasurement, enu_frame_at
    from org.orekit.bodies import OneAxisEllipsoid
    from org.orekit.utils import Constants

    data = raw.data
    position_ecef_m = (data['ECEF_X'] * .01, data['ECEF_Y'] * .01, data['ECEF_Z'] * .01)
    velocity_ecef_m_s = (data['ECEF_VX'] * .01, data['ECEF_VY'] * .01, data['ECEF_VZ'] * .01)
    ellipsoid = OneAxisEllipsoid(Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
                                 Constants.WGS84_EARTH_FLATTENING, earth_fixed_frame)
    measurement_date = absolute_date(epoch_utc, raw.t_meas_s)
    enu_to_ecef, _, _, _ = enu_frame_at(ellipsoid, position_ecef_m, earth_fixed_frame, measurement_date)
    velocity_enu_m_s = enu_to_ecef.T @ np.asarray(velocity_ecef_m_s)
    return ReceiverMeasurement(
        week=data['GNSS_Week'], tow=data['GNSS_TOW'] * .01,
        t_meas_s=raw.t_meas_s, t_arrival_s=raw.t_arrival_s,
        fix_type=data['fix_mode'], num_sv=data['num_SV'], pdop=data['PDOP'] * .01,
        lat_deg=data['Latitude'] * 1e-7, lon_deg=data['Longitude'] * 1e-7,
        alt_ell_m=data['Ellipsoid_altitude'] * .01,
        pos_ecef_m=position_ecef_m, vel_ecef_m_s=velocity_ecef_m_s,
        vel_enu_m_s=tuple(velocity_enu_m_s), h_acc_m=raw.h_acc_m,
        v_acc_m=raw.v_acc_m, latency_s=raw.latency_s)


def decode_gps_data(raw, epoch_utc, inertial_frame, earth_fixed_frame):
    """Decode one receiver fix, then transform position and velocity to ECI."""
    from dataclasses import asdict
    from simulategps import absolute_date, ecef_to_eci_pv
    measurement = raw
    if hasattr(raw, 'data'):
        measurement = decode_orion_fields(raw, epoch_utc, earth_fixed_frame)
    measurement_date = absolute_date(epoch_utc, measurement.t_meas_s)
    # The complete position/velocity transform accounts for Earth's rotation.
    # Rotating velocity alone would create an incorrect orbital velocity.
    position_eci_m, velocity_eci_m_s = ecef_to_eci_pv(
        measurement.pos_ecef_m, measurement.vel_ecef_m_s,
        inertial_frame, earth_fixed_frame, measurement_date)
    return GpsMeasurement(**asdict(measurement), clock_error_s=0.0,
                          nav_pos_eci_m=position_eci_m, nav_vel_eci_mps=velocity_eci_m_s)



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

    def process_raw_data(self, raw, epoch_utc, inertial_frame, earth_fixed_frame):
        """Replaceable onboard input: decode and accept one raw receiver fix."""
        if raw is None:
            self.register_boundary_no_fix()
            return
        self.register_fix(decode_gps_data(raw, epoch_utc, inertial_frame, earth_fixed_frame))

    def get_processed_data(self, t_seconds):
        """Position/velocity input for the simulation, independent of producer."""
        return self.extrapolate(t_seconds)

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
