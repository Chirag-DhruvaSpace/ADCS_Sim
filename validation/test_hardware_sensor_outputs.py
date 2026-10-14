"""Device interface tests, independent of firmware execution."""
import json
import math
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from satellite_parameters import ImuSimParameters, GpsSimParameters
from simulateimu import SimulatedIMU, encode_gyro_registers, encode_magnetometer_registers
from imu_navigation import ImuNav
from simulatesunsensor import simulate_fine_sensor
from send_simulated_sensor_data import get_raw_sensor_data, SensorDataSender


class HardwareSensorOutputs(unittest.TestCase):
    def test_raw_sun_adc_matches_original_physical_model(self):
        from simulatesunsensor import SimulatedSunSensorArray
        from imu_navigation import decode_sun_sample
        configuration = ImuSimParameters.perfect().sun_array
        original = SimulatedSunSensorArray(configuration)
        raw_sensor = SimulatedSunSensorArray(configuration)
        for time_s, direction in enumerate(([1, 2, 3], [-2, 3, 1],
                                            [3, -1, -2], [-1, -2, -3])):
            expected = original.update(time_s, [1, 0, 0, 0], direction, 1)
            raw = raw_sensor.update(time_s, [1, 0, 0, 0], direction, 1, raw_output=True)
            self.assertEqual([cell.adc_counts for cell in raw.cells],
                             [cell.adc_counts for cell in expected.cells])
            decoded = decode_sun_sample(raw, configuration)
            self.assertTrue(decoded.reconstruction_valid)
            unit_direction = np.asarray(direction) / np.linalg.norm(direction)
            error_deg = np.degrees(np.arccos(np.clip(
                np.dot(decoded.reconstructed_body, unit_direction), -1, 1)))
            self.assertLess(error_deg, .05)

    def test_sun_navigation_covers_gap_between_fine_sensors(self):
        from simulatesunsensor import RawSunSample, RawSunCell, RawFineSunSensor
        from imu_navigation import decode_sun_sample
        configuration = ImuSimParameters.perfect().sun_array
        direction = np.ones(3) / math.sqrt(3)
        counts = 2**configuration.cells[0].adc_bits - 1
        cells = []
        sensors = []
        for index, cell in enumerate(configuration.cells):
            brightness = max(0, float(np.dot(cell.normal_body, direction)))
            cells.append(RawSunCell(cell.name, round(brightness * counts), False))
            # A diagonal direction is outside every 35-degree fine sensor.
            sensors.append(RawFineSunSensor(cell.name, 0x11 + index,
                {'Q1': 0, 'Q2': 0, 'Q3': 0, 'Q4': 0,
                 'Alpha': 0, 'Beta': 0, 'VecX': 0, 'VecY': 0, 'VecZ': 0}))
        raw = RawSunSample(0, 0, True, configuration.cells[0].adc_bits,
                           tuple(cells), tuple(sensors))
        decoded = decode_sun_sample(raw, configuration)
        self.assertTrue(decoded.reconstruction_valid)
        self.assertEqual(decoded.method, 'least_squares')
        np.testing.assert_allclose(decoded.reconstructed_body, direction)
        dark_cells = tuple(replace(cell, adc_counts=0) for cell in cells)
        dark = decode_sun_sample(replace(raw, cells=dark_cells), configuration)
        self.assertFalse(dark.reconstruction_valid)

    def test_adis_high_word_scales_and_negative_fraction(self):
        for hardware_range, expected_count in ((125, 160), (450, 40), (2000, 10)):
            registers = encode_gyro_registers([math.radians(1), math.radians(-1), 0], hardware_range)
            self.assertEqual(registers, {'X_axis': expected_count, 'Y_axis': -expected_count, 'Z_axis': 0})
        registers = encode_gyro_registers([math.radians(-.001), 0, 0], 125)
        self.assertEqual(registers['X_axis'], -1)

    def test_ak09916_scale_and_signed_output(self):
        registers = encode_magnetometer_registers([30e-6, -15e-6, 0])
        self.assertEqual(registers, {'X_axis': 200, 'Y_axis': -100, 'Z_axis': 0})

    def test_raw_navigation_and_hardware_saturation(self):
        config = ImuSimParameters.perfect()
        hardware = SimulatedIMU(config)
        gyro, magnetometer, sun = hardware.get_raw_data(
            0, [1,0,0,0], [math.radians(1),0,0], [30e-6,0,0], [0,0,1])
        navigation = ImuNav()
        navigation.process_raw_data(0, gyro, magnetometer, sun, config)
        np.testing.assert_allclose(navigation.omega_body(), [math.radians(1),0,0], atol=1e-12)
        np.testing.assert_allclose(navigation.B_body(), [30e-6,0,0], atol=1e-12)
        np.testing.assert_allclose(navigation.sun_body(), [0,0,1], atol=1e-12)
        saturated, _, _ = hardware.get_raw_data(.1, [1,0,0,0], [10,0,0], [30e-6,0,0])
        self.assertTrue(saturated.saturated)
        self.assertEqual(saturated.data['X_axis'], 20000)
        wide_range_config = replace(config, gyro_hardware_range_deg_s=450)
        wide_range = SimulatedIMU(wide_range_config)
        gyro, _, _ = wide_range.get_raw_data(0, [1,0,0,0], [math.radians(300),0,0], [0,0,0])
        self.assertEqual(gyro.data['X_axis'], 12000)
        self.assertFalse(gyro.saturated)

    def test_fss_boresight_darkness_and_reported_vector(self):
        config = ImuSimParameters.perfect().sun_array
        generator = np.random.default_rng(1)
        output = simulate_fine_sensor([0,0,1], 1, 298.15, config, 0, generator)
        self.assertEqual([output[name] for name in ('Q1','Q2','Q3','Q4')], [2500]*4)
        self.assertEqual(output['VecZ'], 10000)
        self.assertEqual(output['Alpha'], 0)
        tilted = simulate_fine_sensor([math.tan(math.radians(20)),0,1], 1, 298.15, config, 0, generator)
        self.assertAlmostEqual(tilted['Alpha'], 2000, delta=2)
        self.assertGreater(tilted['Q1'], tilted['Q2'])
        dark = simulate_fine_sensor([0,0,1], 0, 298.15, config, 0, generator)
        self.assertEqual(dark['Eclipse'], 1)
        self.assertEqual(dark['VecZ'], 0)

    def test_sender_calls_cached_getters_and_skips_them_when_absent(self):
        hardware = SimulatedIMU(ImuSimParameters.perfect())
        gyro, magnetometer, sun = hardware.get_raw_data(0, [1,0,0,0], [0,0,0], [30e-6,0,0], [0,0,1])
        exported = get_raw_sensor_data(0, gyro=gyro, mag=magnetometer, sun=sun)
        json.dumps(exported, allow_nan=False)
        self.assertNotIn('cells', exported['sun_sensors'])
        self.assertEqual(set(exported['gyroscope']['data']), {'X_axis','Y_axis','Z_axis'})
        gps_sensor, imu_sensor = Mock(), Mock()
        sender = SensorDataSender()
        with patch.object(sender, 'ready_to_send', return_value=False):
            sender.send_from_sensors(0, gps_sensor, imu_sensor)
        gps_sensor.get_raw_data.assert_not_called()
        imu_sensor.get_raw_data.assert_not_called()

    def test_orion_integer_fields_and_navigation(self):
        from simulategps import SimulatedGPS
        from gps_navigation import GpsNav
        from org.orekit.frames import FramesFactory
        from org.orekit.utils import IERSConventions
        provider = SimpleNamespace(epoch_utc=datetime(2022,1,1,tzinfo=timezone.utc),
            inertial_frame=FramesFactory.getEME2000(),
            earth_fixed_frame=FramesFactory.getITRF(IERSConventions.IERS_2010, True))
        hardware = SimulatedGPS(provider, GpsSimParameters.perfect())
        position_m, velocity_m_s = [6871000.,0,0], [0,7600.,0]
        hardware.get_raw_data(0, position_m, velocity_m_s)
        raw = hardware.get_raw_data(1, position_m, velocity_m_s)
        self.assertIsNotNone(raw)
        self.assertTrue(all(isinstance(value, int) for value in raw.data.values()))
        self.assertEqual(set(raw.data), {
            'fix_mode', 'num_SV', 'GNSS_Week', 'GNSS_TOW', 'Latitude', 'Longitude',
            'Ellipsoid_altitude', 'Mean_Sea_Level_Altitude', 'GDOP', 'PDOP', 'HDOP',
            'VDOP', 'TDOP', 'ECEF_X', 'ECEF_Y', 'ECEF_Z', 'ECEF_VX', 'ECEF_VY', 'ECEF_VZ'})
        self.assertNotEqual(raw.data['Mean_Sea_Level_Altitude'], raw.data['Ellipsoid_altitude'])
        horizontal = raw.data['HDOP'] * .01
        vertical = raw.data['VDOP'] * .01
        self.assertAlmostEqual(math.hypot(horizontal, vertical), raw.data['PDOP']*.01, delta=.02)
        navigation = GpsNav(position_m, velocity_m_s)
        navigation.process_raw_data(raw, provider.epoch_utc, provider.inertial_frame, provider.earth_fixed_frame)
        position, velocity = navigation.get_processed_data(1)
        np.testing.assert_allclose(position, position_m, atol=.01)
        np.testing.assert_allclose(velocity, velocity_m_s, atol=.01)


if __name__ == '__main__':
    unittest.main()
