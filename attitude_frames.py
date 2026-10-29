"""Attitude contract shared by the plant, sensors, navigation and viewer.

Scalar-first Hamilton q maps body to ECI: v_eci = R(q) @ v_body.
Body angular velocity is in rad/s; q_dot = 0.5 * q * [0, omega_body].
Configured sensor mounting quaternions retain their historical passive
encoding; mount_to_body converts those explicitly, independently of attitude.
"""
import numpy as np


def body_to_eci(quaternion):
    q = np.asarray(quaternion, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
        [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
        [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)],
    ])


def mount_to_body(quaternion):
    """Sensor-to-body DCM from an existing YAML mounting quaternion."""
    return body_to_eci(quaternion).T
