import satellite_params as sp
import numpy as np
from attitude_frames import cross3


def torque_to_dipole(tau, B_body):
    """Return (dipole, achieved torque); unavailable/low fields produce no actuation."""
    tau = np.asarray(tau, dtype=float).reshape(3)
    field = np.asarray(B_body, dtype=float).reshape(3)
    if not np.all(np.isfinite(tau)):
        raise ValueError('Requested magnetic torque must be finite')
    B2 = np.dot(field, field)
    if not np.isfinite(B2) or B2 < 1e-12:
        return np.zeros(3), np.zeros(3)
    moment = np.clip(cross3(field, tau)/B2, -sp.M_max, sp.M_max)
    return moment, cross3(moment, field)
