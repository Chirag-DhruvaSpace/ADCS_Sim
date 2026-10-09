"""Optical surface data used by the Simulator SRP model.

The values in this module are deliberately simple validation geometry, not a
CAD-derived optical model. Facet normals and lever arms are spacecraft body
coordinates; area is m^2 and lever arm is m.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class OpticalFacet:
    area_m2: float
    normal_body: np.ndarray
    lever_arm_body_m: np.ndarray
    absorptivity: float
    diffuse_reflectivity: float
    specular_reflectivity: float

    def __post_init__(self):
        area = float(self.area_m2)
        normal = np.asarray(self.normal_body, dtype=float).reshape(3)
        lever_arm = np.asarray(self.lever_arm_body_m, dtype=float).reshape(3)
        coefficients = (
            float(self.absorptivity),
            float(self.diffuse_reflectivity),
            float(self.specular_reflectivity),
        )
        if not np.isfinite(area) or area <= 0.0:
            raise ValueError("Facet area must be finite and > 0 m^2.")
        norm = np.linalg.norm(normal)
        if not np.isfinite(norm) or norm == 0.0:
            raise ValueError("Facet normal must be nonzero.")
        if not np.isclose(norm, 1.0, rtol=0.0, atol=1.0e-9):
            raise ValueError("Facet normal must be a unit vector.")
        if not np.all(np.isfinite(lever_arm)):
            raise ValueError("Facet lever arm must be finite.")
        if any(not np.isfinite(value) or value < 0.0 for value in coefficients):
            raise ValueError("Optical coefficients must be finite and nonnegative.")
        if sum(coefficients) > 1.0 + 1.0e-12:
            raise ValueError("Absorptivity + diffuse + specular must be <= 1.")
        object.__setattr__(self, "area_m2", area)
        object.__setattr__(self, "normal_body", normal)
        object.__setattr__(self, "lever_arm_body_m", lever_arm)
        object.__setattr__(self, "absorptivity", coefficients[0])
        object.__setattr__(self, "diffuse_reflectivity", coefficients[1])
        object.__setattr__(self, "specular_reflectivity", coefficients[2])


@dataclass(frozen=True)
class FacetGeometry:
    facets: tuple[OpticalFacet, ...]

    def __post_init__(self):
        if not self.facets:
            raise ValueError("FacetGeometry requires at least one facet.")


@dataclass(frozen=True)
class LegacyReferenceArea:
    reference_area_m2: float
    reflectivity_coefficient: float

    def __post_init__(self):
        if not np.isfinite(self.reference_area_m2) or self.reference_area_m2 <= 0.0:
            raise ValueError("Reference area must be finite and > 0 m^2.")
        if not np.isfinite(self.reflectivity_coefficient) or self.reflectivity_coefficient < 0.0:
            raise ValueError("Reflectivity coefficient must be finite and >= 0.")


def default_validation_geometry(area_m2: float):
    """Return the initial placeholder P-30XL facet used by live SRP config."""
    return FacetGeometry((OpticalFacet(
        area_m2=area_m2,
        normal_body=np.array([0.0, 0.0, -1.0]),
        lever_arm_body_m=np.array([0.0, 0.15, 0.0]),
        absorptivity=0.88,
        diffuse_reflectivity=0.08,
        specular_reflectivity=0.04,
    ),))
