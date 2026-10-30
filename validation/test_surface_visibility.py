# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import unittest
from types import SimpleNamespace
import numpy as np
from spacecraft_surface_physics import SurfaceForceModel

class VisibilityTests(unittest.TestCase):
    def test_reduced_force_sums_match_individual_patch_moments(self):
        import satellite_parameters as config
        from attitude_frames import body_to_eci
        from spacecraft_surface_physics import AU_M, PRESSURE_AT_AU_PA
        model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
        rng = np.random.default_rng(39)
        for _ in range(30):
            q = rng.normal(size=4); q /= np.linalg.norm(q)
            rotation = body_to_eci(q)
            r = np.array([7e6, 0., 0.]); v = rng.normal(size=3)*7500
            sun = rng.normal(size=3)*AU_M; air = np.array([0., 450., 0.])
            actual = model.evaluate(q, r, v, sun, .73, 2e-12, air)
            distance = np.linalg.norm(sun-r)
            light = rotation.T @ ((sun-r)/distance)
            cosine = np.maximum(model.normal @ light, 0)
            cosine *= model.visibility(light)
            srp = -PRESSURE_AT_AU_PA*(AU_M/distance)**2*.73*(model.area*cosine)[:,None]*(
                (1-model.specular)[:,None]*light +
                (2*model.specular*cosine+2*model.diffuse/3)[:,None]*model.normal)
            relative = rotation.T @ (v-air); speed = np.linalg.norm(relative)
            wind = relative/speed
            projected = np.maximum(model.normal @ wind, 0)*model.visibility(wind)
            drag = (-.5*2e-12*model.cd*speed**2*model.area*projected)[:,None]*wind
            for got, expected in [(actual.srp_force_eci_n, rotation@srp.sum(axis=0)),
                                  (actual.srp_torque_body_nm, np.cross(model.arm,srp).sum(axis=0)),
                                  (actual.drag_force_eci_n, rotation@drag.sum(axis=0)),
                                  (actual.drag_torque_body_nm, np.cross(model.arm,drag).sum(axis=0))]:
                np.testing.assert_allclose(got, expected, atol=1e-18, rtol=2e-13)

    def test_vectorized_visibility_preserves_slab_intersections(self):
        rng = np.random.default_rng(42)
        model = SurfaceForceModel.__new__(SurfaceForceModel)
        model.position = rng.uniform(-2,2,(300,3))
        model.blockers = tuple(SimpleNamespace(center_body_m=rng.uniform(-1,1,3), half_extents_m=rng.uniform(.01,.5,3)) for _ in range(12))
        model._blocker_lo = np.array([box.center_body_m-box.half_extents_m for box in model.blockers])
        model._blocker_hi = np.array([box.center_body_m+box.half_extents_m for box in model.blockers])
        # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
        for direction in [np.zeros(3), *np.eye(3), *-np.eye(3), *rng.normal(size=(100,3))]:
            origins = model.position + direction*1e-6
            expected = np.ones(len(origins),bool)
            for box in model.blockers:
                lo, hi = box.center_body_m-box.half_extents_m, box.center_body_m+box.half_extents_m
                near, far = np.full(len(origins),-np.inf), np.full(len(origins),np.inf)
                intersects = np.ones(len(origins),bool)
                for axis in range(3):
                    if abs(direction[axis]) < 1e-12:
                        intersects &= (origins[:,axis]>=lo[axis]) & (origins[:,axis]<=hi[axis])
                    else:
                        a,b = (lo[axis]-origins[:,axis])/direction[axis], (hi[axis]-origins[:,axis])/direction[axis]
                        near = np.maximum(near,np.minimum(a,b)); far = np.minimum(far,np.maximum(a,b))
                expected &= ~(intersects & (far>=np.maximum(near,0)) & (far>1e-7))
            np.testing.assert_array_equal(model.visibility(direction),expected)

    def test_culled_shadow_rays_preserve_force_and_torque_exactly(self):
        from unittest.mock import patch
        from dataclasses import astuple
        import satellite_parameters as config
        model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
        visibility = model.visibility
        rng = np.random.default_rng(123)
        for _ in range(40):
            q = rng.normal(size=4); q /= np.linalg.norm(q)
            inputs = (q, np.array([7e6, 0., 0.]), np.array([0., 7500., 0.]),
                      rng.normal(size=3)*1.5e11, .7, 1e-12, np.array([0., 450., 0.]))
            actual = model.evaluate(*inputs)
            with patch.object(model, 'visibility', side_effect=lambda direction, active=None: visibility(direction)):
                expected = model.evaluate(*inputs)
            for a, b in zip(astuple(actual), astuple(expected)):
                np.testing.assert_array_equal(a, b)
