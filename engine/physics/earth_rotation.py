from engine.astrodynamics.constants import EARTH_ROTATION_RATE_RAD_PER_SEC
from engine.math.vector3 import Vector3


class EarthRotation:
    """
    Rigid Earth-rotation utility for atmosphere kinematics.

    WHY this abstraction exists:
    - Environment providers and force plugins need one shared, stable source for
      atmosphere corotation velocity.
    - Keeping it separate avoids duplicating frame-kinematics logic across
      atmosphere models.

    Scientific scope:
    - Current implementation is the rigid Earth-rotation approximation.
    - TODO: Replace with IAU 2006 / 2000A Earth Orientation chain (precession,
      nutation, Earth rotation angle, polar motion, EOP) in a future upgrade.
    """

    EARTH_ROTATION_RATE_RAD_PER_SEC = EARTH_ROTATION_RATE_RAD_PER_SEC

    @staticmethod
    def atmospheric_velocity(position_m: Vector3) -> Vector3:
        """
        Return local atmospheric velocity from rigid rotation: v_atm = omega x r.

        Rotation axis is +Z in the simulation frame.
        """
        omega_vector = Vector3(
            0.0,
            0.0,
            EarthRotation.EARTH_ROTATION_RATE_RAD_PER_SEC,
        )
        return omega_vector.cross(position_m)