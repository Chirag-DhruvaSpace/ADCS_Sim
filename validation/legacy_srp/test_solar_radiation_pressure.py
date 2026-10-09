import math
import unittest

import numpy as np

from .eclipse_model import EclipseModel
from .solar_radiation_pressure import AU_M, P_1AU_PA, SolarRadiationPressure
from .solar_surface_properties import FacetGeometry, LegacyReferenceArea, OpticalFacet


class FixedEclipse(EclipseModel):
    def __init__(self, fraction):
        self.fraction = fraction

    def illumination_fraction(self, spacecraft_position_eci, sun_position_eci):
        return self.fraction


class SolarRadiationPressureTests(unittest.TestCase):
    sun = np.array([-AU_M, 0.0, 0.0])
    position = np.zeros(3)
    identity = np.array([1.0, 0.0, 0.0, 0.0])

    def calculator(self, geometry, eclipse=1.0):
        return SolarRadiationPressure(geometry, FixedEclipse(eclipse))

    def facet(self, normal=(-1.0, 0.0, 0.0), area=1.0, **coefficients):
        defaults = dict(
            lever_arm_body_m=np.zeros(3),
            absorptivity=1.0,
            diffuse_reflectivity=0.0,
            specular_reflectivity=0.0,
        )
        defaults.update(coefficients)
        return OpticalFacet(area, np.array(normal), **defaults)

    def compute(self, geometry, mass=1.0, q=None, eclipse=1.0):
        return self.calculator(geometry, eclipse).compute(
            self.position, self.identity if q is None else q, mass, self.sun
        )

    def test_pressure_at_one_au_and_inverse_square(self):
        one_au = self.calculator(FacetGeometry((self.facet(),))).compute(
            self.position, self.identity, 1.0, self.sun
        )
        twice = SolarRadiationPressure(FacetGeometry((self.facet(),)), FixedEclipse(1.0)).compute(
            self.position, self.identity, 1.0, np.array([-2.0 * AU_M, 0.0, 0.0])
        )
        self.assertAlmostEqual(one_au.solar_pressure_pa, P_1AU_PA)
        self.assertAlmostEqual(twice.solar_pressure_pa, P_1AU_PA / 4.0)

    def test_force_points_away_from_sun(self):
        result = self.compute(FacetGeometry((self.facet(),)))
        self.assertGreater(result.force_eci_n[0], 0.0)
        self.assertAlmostEqual(result.force_eci_n[1], 0.0)

    def test_back_facing_facet_has_no_force(self):
        result = self.compute(FacetGeometry((self.facet(normal=(1.0, 0.0, 0.0)),)))
        self.assertTrue(np.allclose(result.force_eci_n, 0.0))

    def test_area_and_mass_scaling(self):
        one = self.compute(FacetGeometry((self.facet(area=1.0),)), mass=1.0)
        two_area = self.compute(FacetGeometry((self.facet(area=2.0),)), mass=1.0)
        two_mass = self.compute(FacetGeometry((self.facet(area=1.0),)), mass=2.0)
        self.assertAlmostEqual(two_area.force_eci_n[0], 2.0 * one.force_eci_n[0])
        self.assertAlmostEqual(two_mass.acceleration_eci_m_s2[0], one.acceleration_eci_m_s2[0] / 2.0)

    def test_eclipse_scaling(self):
        geometry = FacetGeometry((self.facet(),))
        dark = self.compute(geometry, eclipse=0.0)
        half = self.compute(geometry, eclipse=0.5)
        full = self.compute(geometry, eclipse=1.0)
        self.assertTrue(np.allclose(dark.force_eci_n, 0.0))
        self.assertAlmostEqual(half.force_eci_n[0], full.force_eci_n[0] / 2.0)

    def test_absorption_specular_and_diffuse_models(self):
        absorption = self.compute(FacetGeometry((self.facet(),))).force_eci_n[0]
        specular = self.compute(FacetGeometry((self.facet(absorptivity=0.0, specular_reflectivity=1.0),))).force_eci_n[0]
        diffuse = self.compute(FacetGeometry((self.facet(absorptivity=0.0, diffuse_reflectivity=1.0),))).force_eci_n[0]
        self.assertAlmostEqual(absorption, P_1AU_PA)
        self.assertAlmostEqual(specular, 2.0 * P_1AU_PA)
        self.assertAlmostEqual(diffuse, 5.0 / 3.0 * P_1AU_PA)

    def test_torque_is_lever_arm_cross_force(self):
        facet = self.facet(lever_arm_body_m=np.array([0.0, 1.0, 0.0]))
        result = self.compute(FacetGeometry((facet,)))
        self.assertAlmostEqual(result.torque_body_nm[2], -P_1AU_PA)

    def test_multiple_facets_sum(self):
        result = self.compute(FacetGeometry((self.facet(area=1.0), self.facet(area=2.0))))
        self.assertAlmostEqual(result.force_eci_n[0], 3.0 * P_1AU_PA)

    def test_quaternion_body_frame_conversion(self):
        q_z_90 = np.array([math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)])
        facet = self.facet(normal=(0.0, -1.0, 0.0))
        result = self.compute(FacetGeometry((facet,)), q=q_z_90)
        self.assertGreater(result.force_eci_n[0], 0.0)
        self.assertAlmostEqual(result.force_eci_n[1], 0.0, places=14)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            self.compute(FacetGeometry((self.facet(),)), mass=0.0)
        with self.assertRaises(ValueError):
            self.calculator(FacetGeometry((self.facet(),))).compute(
                self.sun, self.identity, 1.0, self.sun
            )
        with self.assertRaises(ValueError):
            OpticalFacet(0.0, np.array([-1.0, 0.0, 0.0]), np.zeros(3), 1.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            OpticalFacet(1.0, np.array([-2.0, 0.0, 0.0]), np.zeros(3), 1.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            OpticalFacet(1.0, np.array([-1.0, 0.0, 0.0]), np.zeros(3), 0.8, 0.3, 0.0)

    def test_legacy_reference_area_fallback(self):
        result = self.compute(LegacyReferenceArea(2.0, 1.0), mass=2.0)
        self.assertAlmostEqual(result.force_eci_n[0], 2.0 * P_1AU_PA)
        self.assertTrue(np.allclose(result.torque_body_nm, 0.0))


if __name__ == "__main__":
    unittest.main()
