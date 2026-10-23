"""Run with python -m unittest validation.test_sensor_navigation."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from satellite_parameters import SunSensorArrayParameters, ImuSimParameters, VectorSensorParameters
from simulate_sunsensor import SimulatedSunSensorArray, earth_albedo_fractions
from simulate_gyroscope import SimulatedGyroscope
from simulate_magnetometer import SimulatedMagnetometer
from compute_simulated_attitude import ImuNav, AttitudeEstimator, _dcm_bi_from_q, _rotation_quaternion, quat_angle_deg
from engine.astrodynamics.orbit_display import osculating_orbit
from engine.astrodynamics.constants import EARTH_MU


class Sensors(unittest.TestCase):
    def test_multiple_calibrated_units_and_disabled_hardware(self):
        cfg = replace(ImuSimParameters.perfect(), gyros=(
            VectorSensorParameters('A', overrides=(('gyro_fixed_bias_rad_s', (.01, 0., 0.)),),
                                   calibration_bias=(.01, 0., 0.)),
            VectorSensorParameters('B'), VectorSensorParameters('Off', enabled=False)),
            magnetometers=(VectorSensorParameters('M1'), VectorSensorParameters('M2')))
        g = [(unit, SimulatedGyroscope(cfg.unit_config('gyro', unit, index)).update(0, [1,0,0,0], [.1,.2,.3]))
             for index, unit in enumerate(cfg.gyros) if unit.enabled] if cfg.gyros else SimulatedGyroscope(cfg).update(0, [1,0,0,0], [.1,.2,.3])
        m = [(unit, SimulatedMagnetometer(cfg.unit_config('mag', unit, index)).update(0, [1,0,0,0], [1e-5,2e-5,3e-5]))
             for index, unit in enumerate(cfg.magnetometers) if unit.enabled] if cfg.magnetometers else SimulatedMagnetometer(cfg).update(0, [1,0,0,0], [1e-5,2e-5,3e-5])
        self.assertEqual(len(g), 2)
        self.assertEqual(len(m), 2)
        nav = ImuNav()
        nav.update(0, g, m)
        np.testing.assert_allclose(nav.omega_body(), [.1,.2,.3], atol=1e-14)
        np.testing.assert_allclose(nav.B_body(), [1e-5,2e-5,3e-5], atol=1e-14)
        nav.update(1, [(u,None) for u,_ in g], [(u,None) for u,_ in m])
        self.assertFalse(nav._gyro_valid)
        self.assertFalse(nav._mag_valid)

    def test_saturated_unit_excluded_and_independent_noise(self):
        cfg = replace(ImuSimParameters.perfect(), gyros=(
            VectorSensorParameters('Clipped', overrides=(('gyro_range_rad_s', .01),)),
            VectorSensorParameters('Good')))
        g = [(unit, SimulatedGyroscope(cfg.unit_config('gyro', unit, index)).update(0, [1,0,0,0], [.1,0,0]))
             for index, unit in enumerate(cfg.gyros) if unit.enabled]
        m = SimulatedMagnetometer(cfg).update(0, [1,0,0,0], [2e-5,0,0])
        nav = ImuNav(); nav.update(0,g,m)
        np.testing.assert_allclose(nav.omega_body(), [.1,0,0])
        self.assertFalse(nav._unit_status['gyro'][0]['used'])
        cfg = replace(ImuSimParameters.nominal(), gyros=(VectorSensorParameters('A'),VectorSensorParameters('B')))
        g = [(unit, SimulatedGyroscope(cfg.unit_config('gyro', unit, index)).update(0, [1,0,0,0], [.1,0,0]))
             for index, unit in enumerate(cfg.gyros)]
        self.assertFalse(np.array_equal(g[0][1].omega_body_rad_s,g[1][1].omega_body_rad_s))

    def test_ekf_off_propagates_without_vector_corrections(self):
        nav = ImuNav(estimator_enabled=False)
        gyro = SimulatedGyroscope(ImuSimParameters.perfect())
        magnetic = SimulatedMagnetometer(ImuSimParameters.perfect())
        for t in np.arange(0, 1.01, .1):
            g = gyro.update(t, [1,0,0,0], [0,0,.1])
            m = magnetic.update(t, [1,0,0,0], [2e-5,0,0])
            s = None
            nav.update(t,g,m,s); nav.estimate(t,[2e-5,0,0],[1,0,0])
        self.assertEqual(nav.estimator.corrections, 0)
        np.testing.assert_allclose(nav.estimator.q_eci, _rotation_quaternion(np.array([0,0,.1])), atol=1e-12)

    def test_eclipse_with_every_error_off(self):
        cfg = replace(SunSensorArrayParameters.perfect(), enable_penumbra=False)
        m = SimulatedSunSensorArray(cfg).update(0, [1,0,0,0], [1,1,1], 0)
        self.assertTrue(all(c.output_fraction == 0 for c in m.cells))
        self.assertFalse(m.reconstruction_valid)

    def test_cosine_and_three_faces(self):
        cfg = replace(SunSensorArrayParameters.perfect(), activation_threshold=0.)
        rng = np.random.default_rng(123)
        for t in range(100):
            v = rng.normal(size=3); v /= np.linalg.norm(v)
            m = SimulatedSunSensorArray(cfg).update(0, [1,0,0,0], v, 1)
            self.assertEqual(sum(c.output_fraction > 0 for c in m.cells), 3)
            np.testing.assert_allclose(m.reconstructed_body, v, atol=1e-14)
            for cell, mount in zip(m.cells, cfg.cells):
                self.assertAlmostEqual(cell.output_fraction, max(0, np.dot(mount.normal_body, v)))

    def test_mount_rotation_preserves_perfect_measurements(self):
        q = tuple(_rotation_quaternion(np.array([.3, -.8, .5])))
        cfg = replace(ImuSimParameters.perfect(), gyro_mount_quaternion=q, mag_mount_quaternion=q)
        g = [(unit, SimulatedGyroscope(cfg.unit_config('gyro', unit, index)).update(0, [1,0,0,0], [.1,.2,.3]))
             for index, unit in enumerate(cfg.gyros) if unit.enabled] if cfg.gyros else SimulatedGyroscope(cfg).update(0, [1,0,0,0], [.1,.2,.3])
        m = [(unit, SimulatedMagnetometer(cfg.unit_config('mag', unit, index)).update(0, [1,0,0,0], [1e-5,2e-5,3e-5]))
             for index, unit in enumerate(cfg.magnetometers) if unit.enabled] if cfg.magnetometers else SimulatedMagnetometer(cfg).update(0, [1,0,0,0], [1e-5,2e-5,3e-5])
        np.testing.assert_allclose(g.omega_body_rad_s, [.1,.2,.3], atol=1e-14)
        np.testing.assert_allclose(m.magnetic_field_body_t, [1e-5,2e-5,3e-5], atol=1e-14)

    def test_position_gradient(self):
        cfg = replace(ImuSimParameters.perfect(), mag_position_body_m=(1,0,0),
                      mag_gradient_body_t_per_m=((1e-6,0,0),(0,0,0),(0,0,0)))
        m = SimulatedMagnetometer(cfg).update(0, [1,0,0,0], [2e-5,0,0])
        np.testing.assert_allclose(m.magnetic_field_body_t, [2.1e-5,0,0])

    def test_albedo_dayside_nightside(self):
        args = (np.array([1.,0,0]), np.eye(3), np.array([[-1.,0,0],[1.,0,0]]), np.array([0.,0.]), .3)
        day = earth_albedo_fractions(np.array([6871000.,0,0]), *args)
        night = earth_albedo_fractions(np.array([-6871000.,0,0]), *args)
        self.assertGreater(day[0], .01)
        self.assertEqual(day[1], 0.)
        np.testing.assert_array_equal(night, [0.,0.])

    def test_filter_convergence_and_bias(self):
        est = AttitudeEstimator(_rotation_quaternion(np.array([.12,-.08,.1])))
        B = np.array([1.,0.,0.]); sun = np.array([0.,1.,0.])
        bias = np.array([.0004,-.0003,.0002])
        for i in range(1501):
            t = i*.1
            mag = SimpleNamespace(valid=True, saturated=False, t_meas_s=t, magnetic_field_body_t=B)
            css = SimpleNamespace(valid=True, reconstruction_valid=True, t_meas_s=t, reconstructed_body=sun)
            est.update(t, bias, mag, B, css, sun)
        self.assertLess(quat_angle_deg(est.q_eci, [1,0,0,0]), .03)
        np.testing.assert_allclose(est.bias, bias, atol=1e-5)
        self.assertGreater(np.linalg.eigvalsh(est.P).min(), 0.)

    def test_gyro_propagation(self):
        est = AttitudeEstimator([1,0,0,0])
        omega = np.array([.2,-.1,.3])
        est.update(0, omega, None, None)
        est.update(2, omega, None, None)
        np.testing.assert_allclose(est.q_eci, _rotation_quaternion(omega*2), atol=1e-14)

    def test_inconsistent_vector_cannot_drive_bias(self):
        est = AttitudeEstimator([1,0,0,0])
        est.P = np.eye(6)*1e-6
        before = est.bias.copy()
        accepted = est._correct([0,1,0], [1,0,0], .015, 0, np.zeros(3))
        self.assertFalse(accepted)
        np.testing.assert_array_equal(est.bias, before)

    def test_circular_orbit(self):
        r = 6871000.
        path = osculating_orbit([r,0,0], [0,np.sqrt(EARTH_MU/r),0])
        np.testing.assert_allclose(np.linalg.norm(path, axis=1), r, atol=1e-7)
        np.testing.assert_allclose(path[0], path[-1], atol=1e-7)

    def test_hemisphere_detection_coverage(self):
        v = np.random.default_rng(4).normal(size=(100000, 3))
        v /= np.linalg.norm(v, axis=1)[:, None]
        threshold = SunSensorArrayParameters().activation_threshold
        coverage = np.mean(np.all(np.abs(v) > threshold, axis=1))
        self.assertTrue(.95 < coverage < .96, coverage)

    def test_rotating_filter(self):
        from compute_simulated_attitude import _quat_multiply
        omega = np.array([.015,-.02,.03])
        q0 = _rotation_quaternion(np.array([.3,-.2,.4]))
        est = AttitudeEstimator(_quat_multiply(_rotation_quaternion(np.array([.04,.03,-.02])), q0))
        B, sun = np.array([1.,.2,.1]), np.array([.1,1.,.2])
        bias = np.array([.0004,-.0003,.0002])
        for i in range(1001):
            t = i*.1
            # Independent reference: integrate the plant's explicit Omega matrix.
            from scipy.linalg import expm
            x,y,z = omega
            Om = np.array([[0,-x,-y,-z],[x,0,z,-y],[y,-z,0,x],[z,y,-x,0]])
            truth = expm(.5*t*Om) @ q0
            C = _dcm_bi_from_q(truth)
            mag = SimpleNamespace(valid=True, saturated=False, t_meas_s=t, magnetic_field_body_t=C.T@B)
            css = SimpleNamespace(valid=True, reconstruction_valid=True, t_meas_s=t, reconstructed_body=C.T@sun)
            est.update(t, omega+bias, mag, B, css, sun)
        self.assertLess(quat_angle_deg(est.q_eci, truth), .05)
        np.testing.assert_allclose(est.bias, bias, atol=2e-5)


    def test_mount_editing_endpoints_removed(self):
        from app import app
        client = app.test_client()
        self.assertEqual(client.get('/api/imu/mounts').status_code, 404)
        self.assertEqual(client.post('/api/imu/mounts', json={}).status_code, 404)
        self.assertEqual(client.post('/api/imu/defaults').status_code, 404)


if __name__ == '__main__':
    unittest.main()
