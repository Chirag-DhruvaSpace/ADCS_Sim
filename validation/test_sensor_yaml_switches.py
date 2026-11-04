"""YAML power switches, per-head disables and editable register calibration."""
from dataclasses import replace
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

import satellite_parameters as config
from simulate_gyroscope import SimulatedGyroscope
from simulate_magnetometer import SimulatedMagnetometer
from simulate_sunsensor import SimulatedSunSensorArray
from simulate_startracker import SimulatedStarTracker
from simulate_magnetorquers import SimulatedMagnetorquers
from compute_simulated_attitude import ImuNav, decode_vector_sample, decode_sun_sample


ROOT = Path(__file__).resolve().parents[1]
SENSORS = ('gps', 'gyroscope', 'magnetometer', 'sun_sensor', 'star_tracker', 'magnetorquers')


@pytest.mark.parametrize('switches', list(product((False, True), repeat=len(SENSORS))))
def test_every_combination_of_yaml_master_switches_is_safe(tmp_path, switches):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['use_advanced_satellite_model'] = False
    for name, enabled in zip(SENSORS, switches):
        data[name]['enabled'] = enabled
    data['sensor_profiles'] = dict.fromkeys(data['sensor_profiles'], 'perfect')
    source = tmp_path/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(data), encoding='utf-8')
    loaded = config._load_configuration(source)
    craft, gps, imu = loaded[0], loaded[9], loaded[10]
    assert gps.enabled == switches[0]
    assert imu.enabled == any(switches[1:5])
    gyro = SimulatedGyroscope(imu).get_raw_data(0, [1, 0, 0, 0], [.1, .2, .3])
    mag = SimulatedMagnetometer(imu).get_raw_data(0, [1, 0, 0, 0], [3e-5, 0, 0])
    sun = SimulatedSunSensorArray(imu.sun_array).get_raw_data(0, [1, 0, 0, 0], [1, 1, 1], 1)
    star = SimulatedStarTracker(config=imu.star_tracker).get_raw_data(0, [1, 0, 0, 0],
                                                    [7e6, 0, 0], [1, 1, 1], [0, 0, 0])
    for reading, enabled in zip((gyro, mag, sun, star), switches[1:5]):
        assert (reading is not None) == enabled
    nav = ImuNav()
    nav.process_raw_data(0, gyro, mag, sun, imu, star_tracker=star)
    assert np.all(np.isfinite(nav.B_body()))
    assert np.all(np.isfinite(nav.omega_body()))
    plant = SimulatedMagnetorquers(craft.magnetorquers)
    state = plant.apply_dipole([.1, .2, .3], [0, 0, 3e-5])
    if not switches[5]:
        np.testing.assert_array_equal(state.torque_body_Nm, 0.)


@pytest.mark.parametrize('profile', ['custom', 'perfect', 'nominal', 'degraded', 'stress'])
def test_per_head_switch_survives_profiles_and_preserves_firmware_addresses(tmp_path, profile):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['use_advanced_satellite_model'] = False
    data['sensor_profiles']['sun_sensor'] = profile
    data['sun_sensor']['cells'][1]['enabled'] = False
    source = tmp_path/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(data), encoding='utf-8')
    sun_cfg = config._load_configuration(source)[10].sun_array
    assert not sun_cfg.cells[1].enabled
    # Disable array dropouts to test the per-head electrical switch in isolation.
    sun_cfg = replace(sun_cfg, dropout_probability=0.)
    array = SimulatedSunSensorArray(sun_cfg)
    raw = array.get_raw_data(0, [1, 0, 0, 0], [-1, 0, 0], 1)
    assert raw.cells[1].adc_counts == 0
    assert not raw.sensors[1].enabled
    assert [s.slave_id for s in raw.sensors] == list(range(0x11, 0x17))
    decoded = decode_sun_sample(raw, sun_cfg)
    assert not decoded.cells[1].used
    assert decoded.cells[1].output_fraction == 0.
    import sensor_link
    packets = []
    sensor_link.send_fss(SimpleNamespace(sendto=lambda packet, addr: packets.append(packet)), raw, sun_cfg.cells)
    assert [packet[1] for packet in packets] == [0x11, 0x13, 0x14, 0x15, 0x16]
    assert SimulatedSunSensorArray(replace(sun_cfg, cells=tuple(replace(c, enabled=False)
                                                             for c in sun_cfg.cells))).get_raw_data(
        0, [1, 0, 0, 0], [1, 0, 0], 1) is None


def test_magnetometer_hardware_scale_and_range_round_trip_through_yaml(tmp_path):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['use_advanced_satellite_model'] = False
    data['sensor_profiles']['magnetometer'] = 'perfect'
    data['magnetometer'].update(hardware_scale_t_per_count=1e-8, hardware_range_t=4e-5,
                                mount_quaternion=[1, 0, 0, 0])
    source = tmp_path/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(data), encoding='utf-8')
    cfg = config._load_configuration(source)[10]
    raw = SimulatedMagnetometer(cfg).get_raw_data(0, [1, 0, 0, 0], [3e-5, -2e-5, 1e-5])
    assert raw.counts == (3000, -2000, 1000)
    decoded = decode_vector_sample(raw, 'mag', cfg)
    np.testing.assert_allclose(decoded.magnetic_field_body_t, [3e-5, -2e-5, 1e-5])
    clipped = SimulatedMagnetometer(cfg).get_raw_data(0, [1, 0, 0, 0], [1e-4, 0, 0])
    assert clipped.saturated
    assert clipped.counts[0] == 4000


def test_individual_vector_units_respect_their_own_and_parent_power_switches():
    unit = config.VectorSensorParameters('off', enabled=False)
    for kind, model in [('gyro', SimulatedGyroscope), ('mag', SimulatedMagnetometer)]:
        base = config.ImuSimParameters.perfect()
        assert model(base.unit_config(kind, unit)).get_raw_data(0, None, None) is None
        parent_off = replace(base, **{'enable_gyro' if kind == 'gyro' else 'enable_magnetometer': False})
        on_unit = replace(unit, enabled=True)
        assert model(parent_off.unit_config(kind, on_unit)).get_raw_data(0, None, None) is None


def test_single_fine_sun_head_can_supply_direction_without_coarse_rank():
    base = config.SunSensorArrayParameters.perfect()
    cfg = replace(base, cells=(replace(base.cells[0], normal_body=(0, 0, 1)),))
    raw = SimulatedSunSensorArray(cfg).get_raw_data(0, [1, 0, 0, 0], [0, 0, 1], 1)
    decoded = decode_sun_sample(raw, cfg)
    assert decoded.method == 'fine_sensor_vectors' and decoded.reconstruction_valid
    np.testing.assert_allclose(decoded.reconstructed_body, [0, 0, 1])
