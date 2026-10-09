"""
sun_pointing_rw.py

Target quaternion for the NEW reaction-wheel-based "sun sweep" mode.

This is deliberately separate from periodic_gain_sun_pointing.py, which is
the EXISTING magnetorquer-based sun-pointing controller (body -Z convention,
Floquet-verified robust K_seq). That controller is untouched by this file.
This one is for the new RW-based mode specifically, using body -X (matching
the moon-pointing mode's convention, per explicit confirmation) rather than
the MTR controller's -Z.

Reuses sun_vector_eci() for the actual Sun direction -- geocentric, no
spacecraft-position dependence needed (the Sun is ~1 AU away; per that
module's own docstring, the topocentric/geocentric difference is ~0.0007deg,
utterly negligible for attitude pointing purposes).
"""
import numpy as np
from sun_vector_eci import sun_vector_eci


def sun_pointing_quaternion(timestamp_utc):
    """
    Desired attitude for:

        BODY -X -> SUN

    Roll constraint:
        +Z is kept as close as possible to ECI +Z.

    Returns:
        q_desired = [q0, q1, q2, q3]
    """
    sun_los = sun_vector_eci(timestamp_utc)   # already a unit vector, Earth->Sun

    # -X body points toward Sun, so +X body points away from it.
    x_body_eci = -sun_los

    # Roll reference: ECI +Z
    z_ref = np.array([0.0, 0.0, 1.0])

    # Avoid singularity when Sun is near ECI Z (same threshold as moon_pointing.py)
    if abs(np.dot(x_body_eci, z_ref)) > 0.95:
        z_ref = np.array([0.0, 1.0, 0.0])

    # Remove X component from reference vector
    z_body_eci = (
        z_ref
        - np.dot(z_ref, x_body_eci) * x_body_eci
    )
    z_body_eci /= np.linalg.norm(z_body_eci)

    # Complete right-handed frame
    y_body_eci = np.cross(z_body_eci, x_body_eci)
    y_body_eci /= np.linalg.norm(y_body_eci)

    # Re-orthogonalize
    z_body_eci = np.cross(x_body_eci, y_body_eci)

    # Body axes expressed in ECI
    C_IB = np.column_stack([
        x_body_eci,
        y_body_eci,
        z_body_eci
    ])

    # ECI -> Body
    C_BI = C_IB.T

    from scipy.spatial.transform import Rotation
    q_xyzw = Rotation.from_matrix(C_BI).as_quat()

    # Convert to project convention [q0,q1,q2,q3]
    q0 = q_xyzw[3]
    q1 = q_xyzw[0]
    q2 = q_xyzw[1]
    q3 = q_xyzw[2]

    return np.array([q0, q1, q2, q3])