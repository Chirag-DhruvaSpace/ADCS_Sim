"""Ideal star tracker interface and absolute-attitude/fallback integration."""
import unittest
from dataclasses import replace

import numpy as np

from compute_simulated_attitude import AttitudeEstimator, ImuNav, _rotation_quaternion
from satellite_parameters import ImuSimParameters
from simulate_startracker import SimulatedStarTracker, StarTrackerMeasurement


class StarTrackerTests(unittest.TestCase):
    def test_yaml_switch_survives_sensor_profile_selection(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import yaml
        import satellite_parameters as configuration

        data = yaml.safe_load(Path(configuration.__file__).with_suffix('.yaml').read_text(encoding='utf-8'))
        data['star_tracker']['enabled'] = False
        data['use_advanced_satellite_model'] = False
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'satellite_parameters.yaml'
            for profile in ('custom', 'nominal', 'perfect', 'degraded', 'stress', 'off'):
                with self.subTest(profile=profile):
                    data['sensor_profiles']['gyroscope'] = profile
                    source.write_text(yaml.safe_dump(data), encoding='utf-8')
                    self.assertFalse(configuration._load_configuration(source)[10].enable_star_tracker)

    def test_disabled_tracker_produces_no_receipts(self):
        tracker = SimulatedStarTracker(enabled=False)
        self.assertIsNone(tracker.get_raw_data(0, [1, 0, 0, 0]))
        self.assertIsNone(tracker.get_raw_data())

    def test_disabled_configuration_discards_cached_and_injected_tracker(self):
        navigation = ImuNav()
        sample = SimulatedStarTracker().get_raw_data(0, [1, 0, 0, 0])
        navigation.process_raw_data(0, None, None, None,
                                    ImuSimParameters.perfect(), star_tracker=sample)
        self.assertIsNotNone(navigation._star_tracker)
        disabled = replace(ImuSimParameters.perfect(), enable_star_tracker=False)
        navigation.process_raw_data(.1, None, None, None, disabled, star_tracker=sample)
        self.assertIsNone(navigation._star_tracker)

    def test_passes_every_quaternion_component_unchanged(self):
        tracker = SimulatedStarTracker()
        truth = np.array([.5, -.5, .5, -.5])
        sample = tracker.get_raw_data(0, truth)
        np.testing.assert_array_equal(sample.quaternion_eci, truth)
        truth[:] = 0
        np.testing.assert_array_equal(sample.quaternion_eci, [.5, -.5, .5, -.5])
        self.assertEqual(sample.t_meas_s, sample.t_arrival_s)
        self.assertTrue(sample.valid)

    def test_cached_reads_do_not_resample(self):
        tracker = SimulatedStarTracker()
        self.assertIsNone(tracker.get_raw_data())
        first = tracker.get_raw_data(0, [1, 0, 0, 0])
        self.assertIs(tracker.get_raw_data(), first)
        self.assertIs(tracker.get_raw_data(0), first)
        tracker.get_raw_data(.1, [.5, .5, .5, .5])
        self.assertAlmostEqual(tracker.update_rate_hz, 10)
        with self.assertRaises(ValueError):
            tracker.get_raw_data(0, [1, 0, 0, 0])

    def test_invalid_sensor_inputs_are_rejected(self):
        for quaternion in ([0, 0, 0, 0], [float('nan'), 0, 0, 1], [1, 0, 0]):
            with self.subTest(quaternion=quaternion), self.assertRaises(ValueError):
                SimulatedStarTracker().get_raw_data(0, quaternion)

    def test_absolute_attitude_wins_over_a_large_initial_error(self):
        tracker = SimulatedStarTracker()
        navigation = ImuNav(initial_quaternion=(0, 1, 0, 0))
        configuration = ImuSimParameters.perfect()
        for index in range(100):
            time_s = index * .1
            truth = _rotation_quaternion(np.array([.1, -.2, .3]) * time_s)
            sample = tracker.get_raw_data(time_s, truth)
            navigation.process_raw_data(time_s, None, None, None, configuration,
                                        star_tracker=sample)
            navigation.estimate(time_s, [1, 0, 0], [0, 1, 0])
            np.testing.assert_allclose(navigation.get_processed_data()['quaternion_eci'], truth,
                                       atol=1e-14)
            self.assertTrue(navigation.telemetry()['star_tracker_used'])
            self.assertEqual(navigation.telemetry()['imu_navigation_mode'], 'star_tracker')
        self.assertEqual(navigation.estimator.corrections, 100)
        self.assertEqual(navigation.estimator.propagations, 0)

    def test_invalid_and_stale_tracker_fall_back_to_gyro(self):
        for mode in ('invalid', 'stale', 'future'):
            with self.subTest(mode=mode):
                estimator = AttitudeEstimator([1, 0, 0, 0])
                sample = StarTrackerMeasurement(0, 0, np.array([1., 0, 0, 0]))
                estimator.update(0, [0, 0, .1], None, None, star_tracker=sample)
                if mode == 'invalid':
                    sample = replace(sample, valid=False)
                elif mode == 'future':
                    sample = replace(sample, t_meas_s=2, t_arrival_s=2)
                estimator.update(1, [0, 0, .1], None, None, star_tracker=sample)
                np.testing.assert_allclose(estimator.q_eci, _rotation_quaternion(np.array([0, 0, .1])))
                self.assertFalse(estimator.star_tracker_used_last)

    def test_repeated_receipt_predicts_instead_of_freezing_attitude(self):
        estimator = AttitudeEstimator([1, 0, 0, 0])
        sample = StarTrackerMeasurement(0, 0, np.array([1., 0, 0, 0]))
        estimator.update(0, [0, 0, .1], None, None, star_tracker=sample)
        estimator.update(.1, [0, 0, .1], None, None, star_tracker=sample)
        np.testing.assert_allclose(estimator.q_eci, _rotation_quaternion(np.array([0, 0, .01])))
        self.assertEqual(estimator.corrections, 1)

    def test_disabled_estimator_does_not_use_tracker(self):
        navigation = ImuNav(estimator_enabled=False)
        sample = StarTrackerMeasurement(0, 0, np.array([0., 1, 0, 0]))
        navigation.update(0, None, None, star_tracker=sample)
        navigation.estimate(0, None, None)
        np.testing.assert_array_equal(navigation.estimator.q_eci, [1, 0, 0, 0])
        self.assertFalse(navigation.telemetry()['star_tracker_used'])


if __name__ == '__main__':
    unittest.main()
