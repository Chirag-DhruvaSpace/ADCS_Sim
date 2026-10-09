"""Explicit, frame-aware Solar Radiation Pressure calculator."""
from dataclasses import dataclass
import numpy as np

from .eclipse_model import EclipseModel
from .solar_surface_properties import FacetGeometry, LegacyReferenceArea

AU_M = 149597870700.0
P_1AU_PA = 4.56e-6


@dataclass(frozen=True)
class SRPResult:
    force_eci_n: np.ndarray
    acceleration_eci_m_s2: np.ndarray
    torque_body_nm: np.ndarray
    solar_pressure_pa: float
    effective_pressure_pa: float
    eclipse_fraction: float
    sun_distance_m: float
    incidence_cosines: tuple[float, ...]
    enabled: bool


class SolarRadiationPressure:
    """Compute force and torque without accessing Simulator global state.

    Quaternion convention is scalar-first [q0,q1,q2,q3]. The project's C_bi
    maps body vectors to ECI, therefore body vectors use C_bi.T and ECI forces
    use C_bi. Photon travel and SRP force both follow s_hat from Sun to craft.
    """
    def __init__(self, geometry, eclipse_model: EclipseModel,
                 pressure_1au_pa=P_1AU_PA, au_m=AU_M):
        if not np.isfinite(pressure_1au_pa) or pressure_1au_pa < 0.0:
            raise ValueError("pressure_1au_pa must be finite and >= 0.")
        if not np.isfinite(au_m) or au_m <= 0.0:
            raise ValueError("au_m must be finite and > 0 m.")
        if not isinstance(geometry, (FacetGeometry, LegacyReferenceArea)):
            raise TypeError("geometry must be FacetGeometry or LegacyReferenceArea.")
        self.geometry = geometry
        self.eclipse_model = eclipse_model
        self.pressure_1au_pa = float(pressure_1au_pa)
        self.au_m = float(au_m)

    def compute(self, spacecraft_position_eci_m, attitude_quaternion, spacecraft_mass_kg,
                sun_position_eci_m, eclipse_fraction=None, enabled=True):
        r_sc = np.asarray(spacecraft_position_eci_m, dtype=float).reshape(3)
        r_sun = np.asarray(sun_position_eci_m, dtype=float).reshape(3)
        q = np.asarray(attitude_quaternion, dtype=float).reshape(4)
        if not np.all(np.isfinite(r_sc)) or not np.all(np.isfinite(r_sun)):
            raise ValueError("Spacecraft and Sun positions must be finite.")
        if not np.all(np.isfinite(q)) or np.linalg.norm(q) == 0.0:
            raise ValueError("Attitude quaternion must be finite and nonzero.")
        if not np.isfinite(spacecraft_mass_kg) or spacecraft_mass_kg <= 0.0:
            raise ValueError("Spacecraft mass must be finite and > 0 kg.")
        sun_to_spacecraft = r_sc - r_sun
        sun_distance = np.linalg.norm(sun_to_spacecraft)
        if not np.isfinite(sun_distance) or sun_distance == 0.0:
            raise ValueError("Sun-spacecraft distance must be finite and nonzero.")
        s_eci = sun_to_spacecraft / sun_distance
        illumination = self.eclipse_model.illumination_fraction(r_sc, r_sun) if eclipse_fraction is None else float(eclipse_fraction)
        if not np.isfinite(illumination) or not 0.0 <= illumination <= 1.0:
            raise ValueError("eclipse_fraction must be in [0, 1].")
        solar_pressure = self.pressure_1au_pa * (self.au_m / sun_distance)**2
        pressure = solar_pressure * illumination
        if not enabled or pressure == 0.0:
            return SRPResult(np.zeros(3), np.zeros(3), np.zeros(3), solar_pressure, pressure, illumination, sun_distance, tuple(), bool(enabled))

        c_bi = self._body_to_eci_dcm(q)
        s_body = c_bi.T @ s_eci
        force_body = np.zeros(3)
        torque_body = np.zeros(3)
        incidence_cosines = []
        if isinstance(self.geometry, LegacyReferenceArea):
            force_eci = pressure * self.geometry.reference_area_m2 * self.geometry.reflectivity_coefficient * s_eci
            return SRPResult(force_eci, force_eci / spacecraft_mass_kg, torque_body, solar_pressure, pressure, illumination, sun_distance, tuple(), bool(enabled))

        for facet in self.geometry.facets:
            normal = facet.normal_body
            cosine = float(np.dot(normal, -s_body))
            incidence_cosines.append(cosine)
            if cosine <= 0.0:
                continue
            incident = s_body
            reflected = incident - 2.0 * np.dot(incident, normal) * normal
            diffuse_outgoing = (2.0 / 3.0) * normal
            momentum_transfer = (
                facet.absorptivity * incident
                + facet.diffuse_reflectivity * (incident - diffuse_outgoing)
                + facet.specular_reflectivity * (incident - reflected)
            )
            facet_force = pressure * facet.area_m2 * cosine * momentum_transfer
            force_body += facet_force
            torque_body += np.cross(facet.lever_arm_body_m, facet_force)
        force_eci = c_bi @ force_body
        return SRPResult(force_eci, force_eci / spacecraft_mass_kg, torque_body, solar_pressure, pressure, illumination, sun_distance, tuple(incidence_cosines), bool(enabled))

    @staticmethod
    def _body_to_eci_dcm(q):
        q0, q1, q2, q3 = q / np.linalg.norm(q)
        return np.array([
            [1 - 2*(q2**2 + q3**2), 2*(q1*q2 + q0*q3), 2*(q1*q3 - q0*q2)],
            [2*(q1*q2 - q0*q3), 1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
            [2*(q1*q3 + q0*q2), 2*(q2*q3 - q0*q1), 1 - 2*(q1**2 + q2**2)],
        ])
