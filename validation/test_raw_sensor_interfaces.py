"""Exercise hardware packets and the replaceable onboard boundary."""
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np

from sensor_packets import RawVectorSample, RawSunSample, RawGpsSample
from satellite_parameters import ImuSimParameters, VectorSensorParameters, GpsSimParameters
from simulateimu import SimulatedIMU, _dcm_bi_from_q
from imu_navigation import ImuNav, _rotation_quaternion
from simulatesunsensor import SimulatedSunSensorArray
from send_simulated_sensor_data import get_raw_sensor_data


class RawInterfaces(unittest.TestCase):
    def test_registers_sensor_axes_and_navigation_roundtrip(self):
        mount = tuple(_rotation_quaternion(np.array([.4, -.7, .2])))
        cfg = replace(ImuSimParameters.perfect(), gyro_mount_quaternion=mount,
                      mag_mount_quaternion=mount)
        hardware = SimulatedIMU(cfg)
        omega, field = np.array([.1, -.2, .3]), np.array([2e-5, -3e-5, 4e-5])
        gyro, mag, sun = hardware.get_raw_data(0, [1,0,0,0], omega, field, [1,1,1])
        for packet in (gyro, mag):
            self.assertEqual(RawVectorSample.from_bytes(packet.to_bytes()), packet)
            self.assertTrue(all(isinstance(v, int) for v in packet.counts))
            self.assertFalse(hasattr(packet, 'bias_rad_s'))
        self.assertEqual(RawSunSample.from_bytes(sun.to_bytes()), sun)
        self.assertFalse(hasattr(sun, 'reconstructed_body'))
        expected = np.rint((_dcm_bi_from_q(mount).T @ omega) / cfg.gyro_range_rad_s * 32767)
        np.testing.assert_array_equal(gyro.counts, expected)
        nav = ImuNav()
        nav.process_raw_data(0, gyro, mag, sun, cfg)
        np.testing.assert_allclose(nav.omega_body(), omega,
                                   atol=np.sqrt(3)*cfg.gyro_range_rad_s/65534)
        np.testing.assert_allclose(nav.B_body(), field,
                                   atol=np.sqrt(3)*cfg.mag_range_t/65534)
        direction = np.ones(3)/np.sqrt(3)
        np.testing.assert_allclose(nav.sun_body(), direction, atol=1e-12)
        exported = get_raw_sensor_data(0, gyro=gyro, mag=mag, sun=sun)
        self.assertNotIn('omega_body_rad_s', exported['gyroscope'])
        self.assertNotIn('reconstructed_body', exported['sun_sensors'])
        self.assertNotIn('albedo_fraction', exported['sun_sensors']['cells'][0])

    def test_no_resampling_and_off_grid(self):
        hw = SimulatedIMU(ImuSimParameters.nominal())
        args = (0, [1,0,0,0], [.1,0,0], [2e-5,0,0], [1,1,1])
        first = hw.get_raw_data(*args)
        self.assertIs(hw.get_raw_data(*args), first)
        self.assertIs(hw.get_gyroscope_raw_data(), first[0])
        self.assertIs(hw.get_magnetometer_raw_data(), first[1])
        self.assertIs(hw.get_sun_sensor_raw_data(), first[2])
        self.assertEqual(hw.gyro_samples, 1)
        self.assertEqual(hw.get_raw_data(.001, *args[1:]), (None,None,None))
        self.assertIsNone(hw._sun_array.get_raw_data())

    def test_sun_raw_does_not_reconstruct(self):
        array = SimulatedSunSensorArray(ImuSimParameters.perfect().sun_array)
        with patch.object(array, '_reconstruct', side_effect=AssertionError('Navigation inside sensor')):
            packet = array.get_raw_data(0, [1,0,0,0], [1,1,1])
        self.assertIsInstance(packet, RawSunSample)
        self.assertIs(array.get_raw_data(), packet)

    def test_multi_units_and_dropout_coasting(self):
        cfg = replace(ImuSimParameters.perfect(), gyros=(
            VectorSensorParameters('A', mount_quaternion=tuple(_rotation_quaternion(np.array([.3,.4,0])))),
            VectorSensorParameters('Off', enabled=False),
            VectorSensorParameters('B', overrides=(('gyro_adc_bits', 12),))),
            magnetometers=(VectorSensorParameters('M'),))
        hw, nav = SimulatedIMU(cfg), ImuNav()
        values = hw.get_raw_data(0, [1,0,0,0], [.1,.2,.3], [2e-5,0,0])
        nav.process_raw_data(0, *values, cfg)
        np.testing.assert_allclose(nav.omega_body(), [.1,.2,.3], atol=.002)
        previous = nav.omega_body()
        gyro, mag, sun = values
        invalid = [(unit, replace(packet, valid=False, t_arrival_s=.1)) for unit, packet in gyro]
        nav.process_raw_data(.1, invalid, None, None, cfg)
        self.assertFalse(nav._gyro_valid)
        np.testing.assert_array_equal(nav.omega_body(), previous)

    def test_resolution_saturation_and_invalid_counts(self):
        cfg = replace(ImuSimParameters.perfect(), gyro_adc_bits=12,
                      gyro_range_rad_s=.1, mag_dropout_probability=1.)
        hw = SimulatedIMU(cfg)
        gyro, mag, sun = hw.get_raw_data(0,[1,0,0,0],[.2,-.2,0],[2e-5,0,0])
        self.assertEqual(gyro.counts, (2047,-2047,0))
        self.assertTrue(gyro.saturated)
        self.assertFalse(mag.valid)
        nav = ImuNav()
        with self.assertRaises(ValueError):
            nav.process_raw_data(0, replace(gyro, counts=(2048,0,0)), mag, sun, cfg)
        with self.assertRaises(ValueError):
            replace(cfg, gyro_adc_bits=7)

    def test_gps_raw_has_no_navigation_and_navigation_owns_conversion(self):
        from types import SimpleNamespace
        from simulategps import SimulatedGPS
        from gps_navigation import GpsNav
        from org.orekit.frames import FramesFactory
        from org.orekit.utils import IERSConventions
        provider = SimpleNamespace(epoch_utc=datetime(2022,1,1,tzinfo=timezone.utc),
            inertial_frame=FramesFactory.getEME2000(),
            earth_fixed_frame=FramesFactory.getITRF(IERSConventions.IERS_2010, True))
        hw = SimulatedGPS(provider, replace(GpsSimParameters.perfect(), cold_start_s=0., outages_s=()))
        position, velocity = [6871000.,0,0], [0,7600.,0]
        with patch('simulategps.ecef_to_eci_pv', side_effect=AssertionError('Navigation inside GPS')):
            self.assertIsNone(hw.get_raw_data(0, position, velocity))
            packet = hw.get_raw_data(1, position, velocity)
        self.assertIsNotNone(packet)
        self.assertFalse(hasattr(packet, 'nav_pos_eci_m'))
        self.assertFalse(hasattr(packet, 'clock_error_s'))
        self.assertEqual(RawGpsSample.from_bytes(packet.to_bytes()), packet)
        self.assertIs(hw.get_raw_data(1, position, velocity), packet)
        nav = GpsNav(position, velocity)
        nav.process_raw_data(packet, provider.epoch_utc, provider.inertial_frame, provider.earth_fixed_frame)
        r, v = nav.get_processed_data(1)
        np.testing.assert_allclose(r, position, atol=1e-7)
        np.testing.assert_allclose(v, velocity, atol=1e-9)


if __name__ == '__main__':
    unittest.main()
