"""
kinematic_robustness_pointing.py

Target quaternion for the "KINEMATIC_ROBUSTNESS" mode: body +Z aligns to the
nadir vector and continuously SPINS about that axis at a configurable rate
(default 1 deg/s) -- a test of the ADCS's ability to hold a fixed pointing
direction while sustaining nonzero body rates, rather than a bounded sweep
(unlike MOON/SUN_SWEEP's oscillation).

Axis convention: DIFFERENT from NADIR/NOMINAL_IN_ORBIT, which use body +X for
nadir. This mode uses body +Z instead, per requirement. Built via a cyclic
relabeling of nadir_pointing.py's own body-+X target (new_X=old_Y, new_Y=
old_Z, new_Z=old_X -- a proper rotation, det=+1, verified numerically), the
same style of axis relabeling nadir_pointing.py itself already uses to move
the C firmware's literal zdes->bodyZ mapping onto body +X for this project.

Targets use Hamilton body-to-ECI quaternions. Body axes are matrix columns;
right multiplication applies a spin in the target's local body frame.
"""
import numpy as np
import nadir_pointing as nad
import quat2eul as q2e

# Cyclic relabel matrix: v_old_frame = _R_RELABEL @ v_new_frame.
# new_X = old_Y, new_Y = old_Z, new_Z = old_X -- moves nadir (which
# nadir_pointing.py puts on old body +X) onto NEW body +Z.
_R_RELABEL = np.array([
    [0.0, 0.0, 1.0],
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
])

from satellite_parameters import CONTROL
DEFAULT_SPIN_RATE_DEG_S = CONTROL.kinematic_spin_rate_deg_s


def _spin_quaternion_about_z(theta_deg):
    """Quaternion for a rotation of theta_deg about BODY Z (the locked
    nadir-pointing axis in this mode), scalar-first [q0,q1,q2,q3]."""
    half = np.radians(theta_deg) / 2.0
    return np.array([np.cos(half), 0.0, 0.0, np.sin(half)])


def kinematic_robustness_pointing_quaternion(r_eci, v_eci, t, spin_rate_deg_s=DEFAULT_SPIN_RATE_DEG_S):
    """
    Desired attitude for:

        BODY +Z -> Earth center (nadir), continuously spinning about that
        same axis at spin_rate_deg_s (deg/s), unbounded (not a sweep).

    t: simulation time (s) -- spin angle = spin_rate_deg_s * t, wrapped to
       [0, 360) for numerical cleanliness (mathematically equivalent
       unwrapped, since sin/cos of the built quaternion are periodic).

    Returns:
        q_desired = [q0, q1, q2, q3]
    """
    q_nadir = nad.nadir_pointing_quaternion(r_eci, v_eci)   # body +X -> nadir
    from attitude_frames import body_to_eci
    C_old = body_to_eci(q_nadir)
    rotmat_z = C_old @ _R_RELABEL   # cyclic relabel: nadir now on body +Z

    q_z_base = nad._rotmat_to_quaternion_robust(rotmat_z)
    q_z_base = q_z_base / np.linalg.norm(q_z_base)

    theta_deg = (spin_rate_deg_s * float(t)) % 360.0
    q_spin = _spin_quaternion_about_z(theta_deg)

    # Right multiplication spins about the target body +Z boresight.
    q_target = q2e.quaternion_multiply(q_z_base, q_spin)
    q_target = q_target / np.linalg.norm(q_target)
    if q_target[0] < 0:
        q_target = -q_target
    return q_target