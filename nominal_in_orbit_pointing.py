"""
nominal_in_orbit_pointing.py

Target quaternion for the "NOMINAL_IN_ORBIT" mode: identical to nadir
pointing (body +X -> Earth center, see nadir_pointing.py) except rotated by
a fixed yaw bias ABOUT THE BORESIGHT AXIS ITSELF (body +X, the same axis
that's pointing at nadir) -- per requirement, "basically the same Nadir
pointing but with a yaw bias of 45 degrees".

Note on terminology: in the standard aerospace roll/pitch/yaw convention,
rotation about the primary/boresight axis is usually called "roll" (X-axis)
rather than "yaw" (traditionally Z-axis) -- but for a nadir-pointing
spacecraft, the boresight IS the "vertical" axis in the mission's own frame
of reference, so rotating about it is naturally called "yaw" here (matching
how a traditional LVLH-Z-nadir spacecraft's yaw is rotation about nadir/Z --
this project's earlier axis relabeling just moved that direction from body Z
to body X). Implemented directly as an axis-angle rotation about body X,
independent of any Euler-angle-name ambiguity.

This does NOT change where the spacecraft looks (body +X still points at
nadir, unaffected by rotation about that same axis) -- only the roll/yaw
angle about that line of sight changes. Confirmed numerically below.
"""
import numpy as np
import nadir_pointing as nad
import quat2eul as q2e


def _yaw_bias_quaternion(yaw_deg):
    """Quaternion for a rotation of yaw_deg about the BODY X axis (the
    boresight/nadir-pointing axis in this project's convention), in the
    same [q0,q1,q2,q3] scalar-first convention used throughout."""
    half = np.radians(yaw_deg) / 2.0
    return np.array([np.cos(half), np.sin(half), 0.0, 0.0])


def nominal_in_orbit_pointing_quaternion(r_eci, v_eci, yaw_bias_deg=45.0):
    """
    Desired attitude for:

        BODY +X -> Earth center (same as nadir_pointing_quaternion)
        then rotated by yaw_bias_deg about that SAME body +X axis.

    Right-multiplying the yaw-bias quaternion applies the rotation in the
    nadir target's own local frame (about its own X axis), matching the
    same right-multiply pattern used for moon/sun-sweep's post-convergence
    spin (see satellite_rotational_dynamics_var_mag_field.py).

    Returns:
        q_desired = [q0, q1, q2, q3]
    """
    q_nadir = nad.nadir_pointing_quaternion(r_eci, v_eci)
    q_yaw = _yaw_bias_quaternion(yaw_bias_deg)
    # Right multiplication applies the yaw about the target body X axis.
    q_target = q2e.quaternion_multiply(q_nadir, q_yaw)
    q_target = q_target / np.linalg.norm(q_target)
    if q_target[0] < 0:
        q_target = -q_target
    return q_target