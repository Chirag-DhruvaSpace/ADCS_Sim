"""Print a hand-checkable SRP calculation for the configured validation facet."""
import numpy as np

from .eclipse_model import ConicalEclipseModel
from .solar_radiation_pressure import AU_M, SolarRadiationPressure
from .solar_surface_properties import FacetGeometry, OpticalFacet
import environment_parameters as ep


def main():
    sun_position = np.array([-AU_M, 0.0, 0.0])
    spacecraft_position = np.array([0.0, 0.0, 0.0])
    geometry = FacetGeometry((OpticalFacet(
        area_m2=0.3 * 0.3,
        normal_body=np.array([-1.0, 0.0, 0.0]),
        lever_arm_body_m=np.array([0.0, 0.15, 0.0]),
        absorptivity=0.88,
        diffuse_reflectivity=0.08,
        specular_reflectivity=0.04,
    ),))
    calculator = SolarRadiationPressure(
        geometry,
        ConicalEclipseModel(ep.Re, ep.sun_radius_m),
    )
    # The demo uses an Earth-free analytical point to isolate SRP. Use a fixed
    # full-light model through the public eclipse interface in validation tests.
    class FullSun:
        def illumination_fraction(self, spacecraft_position_eci, sun_position_eci):
            return 1.0

    calculator = SolarRadiationPressure(geometry, FullSun())
    result = calculator.compute(
        spacecraft_position, np.array([1.0, 0.0, 0.0, 0.0]), 6.0, sun_position
    )
    print("Earth-to-Sun direction:", sun_position / np.linalg.norm(sun_position))
    print("Sun-to-spacecraft direction:", (spacecraft_position - sun_position) / result.sun_distance_m)
    print("Sun-spacecraft distance (m):", result.sun_distance_m)
    print("Solar pressure (Pa):", result.solar_pressure_pa)
    print("Effective solar pressure (Pa):", result.effective_pressure_pa)
    print("Eclipse illumination fraction:", result.eclipse_fraction)
    print("Facet incidence cosines:", result.incidence_cosines)
    print("Total SRP force ECI (N):", result.force_eci_n)
    print("SRP acceleration ECI (m/s^2):", result.acceleration_eci_m_s2)
    print("SRP torque body (N m):", result.torque_body_nm)


if __name__ == "__main__":
    main()
