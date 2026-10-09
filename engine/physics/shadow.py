from engine.math.vector3 import Vector3


class CylindricalShadowModel:
    """
    Classical cylindrical Earth-shadow approximation.

    WHY this abstraction exists:
    - Keep eclipse geometry separate from SRP force computation.
    - Preserve a stable shadow API so SRP can consume illumination state without
      embedding geometric model details.

    Scientific scope:
    - This validation model uses an infinite cylindrical umbra aligned with the
      Earth-Sun direction.
    - It intentionally ignores penumbra, finite Sun radius, and atmospheric
      refraction.
    - TODO: Replace with conical umbra/penumbra eclipse geometry in a future
      scientific upgrade without changing force-plugin APIs.
    """

    def __init__(self, earth_radius_m: float) -> None:
        if earth_radius_m <= 0.0:
            raise ValueError(
                "CylindricalShadowModel.earth_radius_m must be > 0."
            )
        self.earth_radius_m = earth_radius_m

    def is_illuminated(
        self,
        spacecraft_position_m: Vector3,
        sun_position_m: Vector3,
    ) -> bool:
        """
        Return sunlight state for a spacecraft position in an Earth-centered frame.

        Returns:
            True if illuminated by the Sun.
            False if inside Earth's cylindrical umbral shadow.
        """
        if sun_position_m.magnitude() == 0.0:
            raise ValueError(
                "sun_position_m must be a non-zero vector to define Sun direction."
            )

        s_hat = sun_position_m.normalize()
        parallel_distance = spacecraft_position_m.dot(s_hat)

        # Sun-facing side of Earth cannot be in umbra.
        if parallel_distance > 0.0:
            return True

        perpendicular_vector = spacecraft_position_m - (s_hat * parallel_distance)
        perpendicular_distance = perpendicular_vector.magnitude()

        if perpendicular_distance < self.earth_radius_m:
            return False

        return True