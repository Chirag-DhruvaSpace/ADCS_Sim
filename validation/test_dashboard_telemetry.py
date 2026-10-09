# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import unittest
import numpy as np
from dashboard_telemetry import enrich_dashboard


class DashboardSnapshotTests(unittest.TestCase):
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    def test_magnetorquer_endpoint_does_not_publish_total_actuator_torque(self):
        from unittest.mock import patch
        import app
        import store
        with patch.object(store, 'tau_body', np.array([.004, .003, .002])), patch.object(store, 'mtr_torques', np.array([1e-6, -2e-6, 3e-6])):
            data = app.app.test_client().get('/mtr_telemetry').json
            self.assertEqual(data['mtr_torques'], [1e-6, -2e-6, 3e-6])

    def test_wheel_mode_publishes_zero_magnetic_torque_with_nonzero_acceleration(self):
        from unittest.mock import patch
        import satellite_rotational_dynamics_var_mag_field as dynamics
        import store
        with patch.object(dynamics.cs, 'get_mode', return_value='RW'), patch.object(dynamics, '_rw_control_torque', return_value=np.array([.0001, -.0002, .0003])):
            dynamics.rotational_equations_of_motion(0, [1, 0, 0, 0, 0, 0, 0], np.array([20e-6, 0, 40e-6]))
            np.testing.assert_array_equal(store.mtr_torques, np.zeros(3))
            self.assertGreater(np.linalg.norm(store.angular_acceleration), 0)
            self.assertGreater(np.linalg.norm(store.tau_body), 0)

    def test_snapshot_uses_same_frame_and_does_not_mutate_truth(self):
        r = np.array([7e6, 0., 0.])
        v = np.array([0., 7500., 0.])
        rotation = np.array([[0., 1., 0.], [-1., 0., 0.], [0., 0., 1.]])
        snapshot = enrich_dashboard(
            {}, t=12.5, position_eci=r, velocity_eci=v,
            sun_eci_m=np.array([1.5e11, 0., 0.]), eci_to_ecef=rotation,
            body_to_eci=np.eye(3), mtr_torque=[1., 2., 3.],
            mtr_dipole=[.1, .2, .3], mtr_current=[.01, .02, .03],
            models={'Gravity': 'Test configuration'}, gps_enabled=True,
            spacecraft_name='P-30XL', sensor_activation={
                'GPS receiver': True, 'Gyroscope': False})
        np.testing.assert_array_equal(snapshot['satellite_position_ecef_m'], [0., -7e6, 0.])
        np.testing.assert_array_equal(snapshot['sun_position_ecef_m'], [0., -1.5e11, 0.])
        np.testing.assert_array_equal(snapshot['body_to_ecef_matrix'], rotation)
        np.testing.assert_array_equal(r, [7e6, 0., 0.])
        self.assertEqual(snapshot['satellite_speed_m_s'], 7500.)
        self.assertEqual(snapshot['simulation_time_s'], 12.5)
        self.assertFalse(snapshot['gps_links_available'])
        self.assertEqual(snapshot['gps_satellites'], [])
        self.assertEqual(snapshot['orbital_models']['Gravity'], 'Test configuration')
        self.assertEqual(snapshot['satellite_name'], 'P-30XL')
        self.assertEqual(snapshot['sensor_activation']['Gyroscope'], False)


if __name__ == '__main__':
    unittest.main()
