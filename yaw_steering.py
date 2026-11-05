"""Supplied yaw calculation, using our firmware's +X nadir axis."""
import numpy as np

from nadir_pointing import nadir_pointing_quaternion
from quat2eul import quaternion_multiply

EARTH_RATE_RAD_S = 7.2921159e-5  # Same value as the supplied environment_parameters.py.


def calculate_desired_yaw_angle(r, v_eci):
    """Direct port of the supplied function. ECI metres and m/s; returns degrees."""
    r = np.asarray(r, dtype=float)
    v_eci = np.asarray(v_eci, dtype=float)
    if (r.shape != (3,) or v_eci.shape != (3,)
            or not np.all(np.isfinite(r)) or not np.all(np.isfinite(v_eci))
            or np.linalg.norm(r) == 0 or np.linalg.norm(v_eci) == 0):
        raise ValueError('Yaw steering needs finite, nonzero ECI position and velocity')

    v_earth = np.cross([0.0, 0.0, EARTH_RATE_RAD_S], r)
    v_rel = v_eci - v_earth
    u_v = v_eci / np.linalg.norm(v_eci)
    u_n = -r / np.linalg.norm(r)
    u_c = np.cross(u_n, u_v)
    if np.linalg.norm(u_c) < 1e-12:
        raise ValueError('Yaw steering needs a valid orbital plane')
    u_c /= np.linalg.norm(u_c)
    v_rel_cross = np.dot(v_rel, u_c)
    v_rel_along = np.dot(v_rel, u_v)
    return -np.degrees(np.arctan2(v_rel_cross, v_rel_along))


def yaw_steering_quaternion(r_eci, v_eci):
    """Apply the supplied angle about body +X, keeping our existing nadir frame."""
    half = np.radians(calculate_desired_yaw_angle(r_eci, v_eci)) / 2.0
    q_yaw = np.array([np.cos(half), np.sin(half), 0.0, 0.0])
    q = quaternion_multiply(nadir_pointing_quaternion(r_eci, v_eci), q_yaw)
    q /= np.linalg.norm(q)
    return q if q[0] >= 0 else -q


def yaw_steering_target_rate(r_eci, v_eci, dt=0.2):
    """Target's turning rate in rad/s, using the same short step as the firmware."""
    r = np.asarray(r_eci, dtype=float)
    v = np.asarray(v_eci, dtype=float)
    acceleration = -3.986004418e14 * r / np.linalg.norm(r)**3
    q_now = yaw_steering_quaternion(r, v)
    q_next = yaw_steering_quaternion(r + v*dt, v + acceleration*dt)
    difference = quaternion_multiply([q_now[0], *(-q_now[1:])], q_next)
    if difference[0] < 0:
        difference = -difference
    return 2*difference[1:]/dt
