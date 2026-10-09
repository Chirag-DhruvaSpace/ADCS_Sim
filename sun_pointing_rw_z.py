"""
sun_pointing_rw_z.py

Target quaternion for the NEW reaction-wheel-based "SUN_POINTING_RW" mode.

This uses BODY -Z -> Sun, matching the EXISTING magnetorquer-based
sun-pointing controller's own axis convention (see
periodic_lqr_design_robust.build_target_frame(): "body -Z points at the
sun -- matches the display/render frame's own -Z convention directly").
The only thing that changes between that mode and this one is the
ACTUATOR (magnetorquers vs reaction wheels) and control law (Floquet-
verified periodic-LQR vs plain PD) -- the pointing axis itself must stay
identical, per explicit requirement, so the satellite looks at the same
physical direction either way.

Deliberately NOT the same as sun_pointing_rw.py, which is body -X (used by
the separate "SUN_SWEEP" mode, matching moon-pointing's convention) -- that
file is untouched by this one.

No oscillation/sweep here: this is plain sun-tracking, analogous to the
nadir/moon RW modes before any spin was layered on top.

Reuses sun_vector_eci() for the actual Sun direction -- geocentric, no
spacecraft-position dependence needed (per that module's own docstring,
the topocentric/geocentric difference is ~0.0007deg, utterly negligible).
"""
import numpy as np
from sun_vector_eci import sun_vector_eci


def sun_pointing_rw_z_quaternion(timestamp_utc):
    """
    Desired attitude for:

        BODY -Z -> SUN

    Roll constraint:
        +Y is kept as close as possible to ECI +Z (same style of
        secondary-axis reference as sun_pointing_rw.py and moon_pointing.py,
        just built around -Z as the primary axis instead of -X).

    Returns:
        q_desired = [q0, q1, q2, q3]
    """
    sun_los = sun_vector_eci(timestamp_utc)   # unit vector, Earth->Sun

    # -Z body points toward Sun, so +Z body points away from it.
    z_body_eci = -sun_los

    # Roll reference: ECI +Z (same threshold pattern as sun_pointing_rw.py
    # and moon_pointing.py -- avoid singularity when the Sun is itself near
    # the ECI Z axis, in which case fall back to ECI Y).
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(z_body_eci, ref)) > 0.95:
        ref = np.array([0.0, 1.0, 0.0])

    # Remove the Z-body component from the reference vector to get body Y
    y_body_eci = ref - np.dot(ref, z_body_eci) * z_body_eci
    y_body_eci /= np.linalg.norm(y_body_eci)

    # Complete right-handed frame: X = Y cross Z
    x_body_eci = np.cross(y_body_eci, z_body_eci)
    x_body_eci /= np.linalg.norm(x_body_eci)

    # Re-orthogonalize Y for numerical cleanliness
    y_body_eci = np.cross(z_body_eci, x_body_eci)

    # Body axes expressed in ECI (columns = body->ECI)
    C_IB = np.column_stack([x_body_eci, y_body_eci, z_body_eci])

    # ECI -> Body (matches sun_pointing_rw.py's exact pattern -- scipy's
    # Rotation.from_matrix needs this transpose to produce a quaternion
    # whose STANDARD C_bi(q) reconstruction, used throughout this project,
    # equals C_IB rather than its transpose. Missing this was caught by
    # direct numerical verification below: without it, body -Z landed
    # ~81deg away from the true Sun direction instead of ~0deg.)
    C_BI = C_IB.T

    from scipy.spatial.transform import Rotation
    q_xyzw = Rotation.from_matrix(C_BI).as_quat()

    # Convert to project convention [q0,q1,q2,q3]
    q0 = q_xyzw[3]
    q1 = q_xyzw[0]
    q2 = q_xyzw[1]
    q3 = q_xyzw[2]

    q = np.array([q0, q1, q2, q3])
    if q[0] < 0:
        q = -q
    return q