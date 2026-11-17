"""Exact ECI fault injection through the real GPS frame and ORION/SITL paths."""
from dataclasses import replace
from pathlib import Path
import math
import struct
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

import satellite_parameters as config
from simulate_gps import SimulatedGPS, absolute_date, ecef_to_eci_pv
from compute_simulated_position import decode_gps_data


ROOT = Path(__file__).resolve().parents[1]
POSITION = 'fixed_position_offset_eci_m'
VELOCITY = 'fixed_velocity_offset_eci_m_s'


@pytest.fixture(scope='module')
def frames():
    # Importing simulate_gps has initialized the existing JVM/data context.
    from org.orekit.frames import FramesFactory
    from org.orekit.utils import IERSConventions
    return SimpleNamespace(epoch_utc=config.EPOCH_UTC,
                           inertial_frame=FramesFactory.getEME2000(),
                           earth_fixed_frame=FramesFactory.getITRF(IERSConventions.IERS_2010, True))


def truth(time_s):
    # Non-equatorial orbit so tests cannot accidentally pass on an aligned axis.
    radius = 7e6
    rate = math.sqrt(3.986004418e14 / radius**3)
    phase = .31 + rate * time_s
    tilt = .73
    position = radius * np.array([math.cos(phase), math.sin(phase)*math.cos(tilt),
                                  math.sin(phase)*math.sin(tilt)])
    velocity = radius * rate * np.array([-math.sin(phase), math.cos(phase)*math.cos(tilt),
                                         math.cos(phase)*math.sin(tilt)])
    return position, velocity


AXIS_CASES = []
for kind, amplitude in [(POSITION, 100.0), (VELOCITY, .25)]:
    for axis in range(3):
        for sign in (-1, 1):
            vector = [0., 0., 0.]
            vector[axis] = sign * amplitude
            AXIS_CASES.append(pytest.param({kind: vector}, id=f'{kind}-{axis}-{sign:+}'))
AXIS_CASES += [
    pytest.param({POSITION: (10., -20., 30.), VELOCITY: (.1, -.2, .3)}, id='combined'),
    pytest.param({POSITION: (10000., -20000., 30000.)}, id='position-only-earth-rotation'),
    pytest.param({}, id='zero-defaults'),
]


@pytest.mark.parametrize('settings', AXIS_CASES)
def test_exact_eci_axes_through_real_rotating_frames(frames, settings):
    cfg = replace(config.GpsSimParameters.perfect(), **settings)
    gps = SimulatedGPS(frames, cfg)
    expected_position = np.asarray(cfg.fixed_position_offset_eci_m)
    expected_velocity = np.asarray(cfg.fixed_velocity_offset_eci_m_s)
    for time_s in [0., 1., 30., 900., 3600.]:
        position, velocity = truth(time_s)
        saved_position, saved_velocity = position.copy(), velocity.copy()
        measurement = gps.update(time_s, position, velocity)
        np.testing.assert_array_equal(position, saved_position)
        np.testing.assert_array_equal(velocity, saved_velocity)
        if time_s == 0.:
            assert measurement is None
            continue
        np.testing.assert_allclose(measurement.nav_pos_eci_m - position, expected_position,
                                   rtol=0, atol=1e-7)
        np.testing.assert_allclose(measurement.nav_vel_eci_mps - velocity, expected_velocity,
                                   rtol=0, atol=1e-10)
        # The receiver's history and validation truth retain unmodified orbit data.
        np.testing.assert_array_equal(gps._history[-1][1], position)
        np.testing.assert_array_equal(gps._history[-1][2], velocity)
        np.testing.assert_allclose(gps.records[-1]['truth_pos_eci'], position, rtol=0, atol=1e-8)
        np.testing.assert_allclose(gps.records[-1]['truth_vel_eci'], velocity, rtol=0, atol=1e-11)


@pytest.mark.parametrize('settings', AXIS_CASES)
def test_orion_and_firmware_sensor_packet_keep_offsets(frames, settings):
    import sensor_link
    cfg = replace(config.GpsSimParameters.perfect(), **settings)
    gps = SimulatedGPS(frames, cfg)
    assert gps.get_raw_data(0., *truth(0.)) is None
    position, velocity = truth(1.)
    raw = gps.get_raw_data(1., position, velocity)
    assert raw is not None
    assert gps.get_raw_data() is raw
    assert gps.get_raw_data(1.) is raw  # cached reads never inject twice
    decoded = decode_gps_data(raw, frames.epoch_utc, frames.inertial_frame, frames.earth_fixed_frame)
    # ORION encodes ECEF components at 1 cm and 1 cm/s even with model
    # quantization disabled. A rotation of the three rounding errors can be
    # sqrt(3)*0.005 along an ECI axis; do not promise exact wire-level offsets.
    np.testing.assert_allclose(decoded.nav_pos_eci_m - position, cfg.fixed_position_offset_eci_m,
                               rtol=0, atol=.009)
    np.testing.assert_allclose(decoded.nav_vel_eci_mps - velocity, cfg.fixed_velocity_offset_eci_m_s,
                               rtol=0, atol=.009)
    packets = []
    sensor_link.send_gps(SimpleNamespace(sendto=lambda packet, address: packets.append(packet)), raw)
    assert len(packets) == 1 and len(packets[0]) == 135
    fields = struct.unpack(sensor_link.GPS_PACKET_FORMAT, packets[0])
    assert fields[0] == sensor_link.SENSOR_ID_GPS
    packet_position, packet_velocity = fields[-6:-3], fields[-3:]
    date = absolute_date(frames.epoch_utc, raw.t_meas_s)
    recovered_position, recovered_velocity = ecef_to_eci_pv(
        packet_position, packet_velocity, frames.inertial_frame, frames.earth_fixed_frame, date)
    np.testing.assert_array_equal(recovered_position, decoded.nav_pos_eci_m)
    np.testing.assert_array_equal(recovered_velocity, decoded.nav_vel_eci_mps)


@pytest.mark.parametrize('field', [POSITION, VELOCITY])
@pytest.mark.parametrize('bad', [None, 1., [], [1., 2.], [1., 2., 3., 4.],
                                 [[1., 2., 3.]], [0., np.nan, 0.], [np.inf, 0., 0.],
                                 [0., 0., -np.inf], ['bad', 0., 0.]])
def test_offset_validation_rejects_bad_vectors(field, bad):
    with pytest.raises(ValueError, match=field):
        replace(config.GpsSimParameters.perfect(), **{field: bad})


@pytest.mark.parametrize('field', [POSITION, VELOCITY])
def test_direct_vector_config_is_immutable(field):
    vector = [-1., 2., 3.]
    cfg = replace(config.GpsSimParameters.perfect(), **{field: vector})
    vector[0] = 500.
    assert getattr(cfg, field) == (-1., 2., 3.)


@pytest.mark.parametrize('profile', ['custom', 'off', 'perfect', 'nominal', 'degraded', 'stress'])
def test_offsets_round_trip_yaml_and_respect_profiles(tmp_path, profile):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['sensor_profiles']['gps'] = profile
    data['gps'][POSITION] = [12., -34., 56.]
    data['gps'][VELOCITY] = [-.1, .2, -.3]
    data['gps']['enable_bias'] = False
    path = tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    cfg = config._load_configuration(path, use_advanced_satellite_model=False)[9]
    assert cfg.fixed_position_offset_eci_m == ((12., -34., 56.) if profile == 'custom' else (0., 0., 0.))
    assert cfg.fixed_velocity_offset_eci_m_s == ((-.1, .2, -.3) if profile == 'custom' else (0., 0., 0.))


def test_old_yaml_without_offset_keys_still_loads(tmp_path):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['gps'].pop(POSITION, None)
    data['gps'].pop(VELOCITY, None)
    data['sensor_profiles']['gps'] = 'custom'
    path = tmp_path/'old.yaml'
    path.write_text(yaml.safe_dump(data), encoding='utf-8')
    cfg = config._load_configuration(path, use_advanced_satellite_model=False)[9]
    assert cfg.fixed_position_offset_eci_m == cfg.fixed_velocity_offset_eci_m_s == (0., 0., 0.)


def test_master_disabled_gps_still_sends_nothing(frames):
    cfg = replace(config.GpsSimParameters.perfect(), enabled=False,
                  fixed_position_offset_eci_m=(10., 20., 30.))
    gps = SimulatedGPS(frames, cfg)
    assert gps.get_raw_data(0., *truth(0.)) is None
    assert gps.get_raw_data(1., *truth(1.)) is None
    assert not gps.records


def test_offsets_add_to_random_errors_without_changing_rng_or_latency(frames):
    cfg = replace(config.GpsSimParameters.nominal(), enable_dropout=False, enable_clock_error=False)
    baseline = SimulatedGPS(frames, cfg)
    delta_position = np.array([10., -20., 30.])
    delta_velocity = np.array([.1, -.2, .3])
    shifted = SimulatedGPS(frames, replace(cfg, fixed_position_offset_eci_m=delta_position,
                                         fixed_velocity_offset_eci_m_s=delta_velocity))
    received = 0
    for step in range(61):
        time_s = step * .1
        first = baseline.update(time_s, *truth(time_s))
        second = shifted.update(time_s, *truth(time_s))
        assert (first is None) == (second is None)
        assert baseline.rng.bit_generator.state == shifted.rng.bit_generator.state
        if first is None:
            continue
        received += 1
        assert first.t_meas_s == second.t_meas_s
        np.testing.assert_allclose(second.nav_pos_eci_m-first.nav_pos_eci_m, delta_position,
                                   rtol=0, atol=1e-7)
        np.testing.assert_allclose(second.nav_vel_eci_mps-first.nav_vel_eci_mps, delta_velocity,
                                   rtol=0, atol=1e-10)
    assert received >= 5
