"""Modular Earth eclipse models for the Simulator SRP subsystem."""
from abc import ABC, abstractmethod
import math
import numpy as np


class EclipseModel(ABC):
    @abstractmethod
    def illumination_fraction(self, spacecraft_position_eci, sun_position_eci):
        """Return direct solar flux fraction in [0, 1]."""
        raise NotImplementedError


class CylindricalUmbraModel(EclipseModel):
    """Binary infinite-cylinder umbra approximation.

    This ignores finite Sun radius and penumbra. It remains available as a
    transparent baseline while ConicalEclipseModel is the preferred default.
    """
    def __init__(self, earth_radius_m):
        if not np.isfinite(earth_radius_m) or earth_radius_m <= 0.0:
            raise ValueError("Earth radius must be finite and > 0 m.")
        self.earth_radius_m = float(earth_radius_m)

    def illumination_fraction(self, spacecraft_position_eci, sun_position_eci):
        r_sc = np.asarray(spacecraft_position_eci, dtype=float)
        r_sun = np.asarray(sun_position_eci, dtype=float)
        sun_norm = np.linalg.norm(r_sun)
        if sun_norm == 0.0:
            raise ValueError("Sun position must be nonzero for eclipse geometry.")
        s_hat = r_sun / sun_norm
        axial = np.dot(r_sc, s_hat)
        if axial > 0.0:
            return 1.0
        cross_track = r_sc - axial * s_hat
        return 0.0 if np.linalg.norm(cross_track) < self.earth_radius_m else 1.0


class ConicalEclipseModel(EclipseModel):
    """Finite-disc Sun/Earth occultation with continuous penumbra.

    Apparent-disc overlap is the geometric finite-radius equivalent of a
    conical shadow for spherical bodies. Atmosphere, limb irregularity,
    refraction, and solar limb darkening are not modeled.
    """
    def __init__(self, earth_radius_m, sun_radius_m):
        if earth_radius_m <= 0.0 or sun_radius_m <= 0.0:
            raise ValueError("Earth and Sun radii must be > 0 m.")
        self.earth_radius_m = float(earth_radius_m)
        self.sun_radius_m = float(sun_radius_m)

    def illumination_fraction(self, spacecraft_position_eci, sun_position_eci):
        r_sc = np.asarray(spacecraft_position_eci, dtype=float)
        r_sun = np.asarray(sun_position_eci, dtype=float)
        earth_distance = np.linalg.norm(r_sc)
        sun_vector = r_sun - r_sc
        sun_distance = np.linalg.norm(sun_vector)
        if earth_distance <= self.earth_radius_m:
            raise ValueError("Spacecraft must be outside the Earth surface.")
        if sun_distance <= self.sun_radius_m:
            raise ValueError("Spacecraft must be outside the Sun surface.")

        earth_radius = math.asin(min(1.0, self.earth_radius_m / earth_distance))
        sun_radius = math.asin(min(1.0, self.sun_radius_m / sun_distance))
        separation = math.acos(np.clip(np.dot(-r_sc, sun_vector) / (earth_distance * sun_distance), -1.0, 1.0))
        if separation >= earth_radius + sun_radius:
            return 1.0
        if earth_radius >= separation + sun_radius:
            return 0.0
        if sun_radius >= separation + earth_radius:
            return 1.0
        overlap = self._overlap(sun_radius, earth_radius, separation)
        return float(np.clip(1.0 - overlap / (math.pi * sun_radius**2), 0.0, 1.0))

    @staticmethod
    def _overlap(radius_a, radius_b, separation):
        a = math.acos(np.clip((separation**2 + radius_a**2 - radius_b**2) / (2 * separation * radius_a), -1.0, 1.0))
        b = math.acos(np.clip((separation**2 + radius_b**2 - radius_a**2) / (2 * separation * radius_b), -1.0, 1.0))
        radical = math.sqrt(max(0.0, (-separation + radius_a + radius_b) * (separation + radius_a - radius_b) * (separation - radius_a + radius_b) * (separation + radius_a + radius_b)))
        return radius_a**2 * a + radius_b**2 * b - 0.5 * radical
