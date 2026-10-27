"""Firmware SITL sensor link: bytes on UDP 5010 must read, through the
firmware's own decode and mounting, as the physical truth.

The firmware side is reproduced here from its sources:
  RelDCM        ADS main.c (AdsConfigStruct.RelDCM[0,1,2,6,7,8], slaves 0x11..0x16)
  sensor2body   utils/coord_transform.c: v_body = cos(RelDCM) @ v_sensor
  fssTask       sitl_task_defs.c: Q > 10000 -> 0, lit = sum(Q) >= 400,
                usable = |Alpha|, |Beta| <= 3500
  IMU           sitl_task_defs.c sitl_processHybridGyroMag (flight ADIS16545.c):
                gyro deg/s = counts / (10485760 / 65536), body = RelDCM[9];
                mag uT = counts * 0.15, magApplyCal, body = RelDCM[4]
  sagittaTask   sitl_task_defs.c (flight task_defs.c): accepted when isTrustworthy;
                absquat = RelQuat[3] (x) q_ST (sensor2bodyquat, star_tracker_absquat.c)
  fusedquat     body -> ECI, so body vectors are _dcm_bi_from_q(q) @ v_eci
"""
import math
import socket
import struct
from dataclasses import replace

import numpy as np
import pytest

import satellite_parameters as config
import sensor_link
from simulate_gps import RawGpsSample
from simulate_sunsensor import SimulatedSunSensorArray, sensor_to_body_matrix, _dcm_bi_from_q

FIRMWARE_REL_DCM_DEG = (
    ((90, 0, 90), (0, 90, 90), (90, 90, 180)),        # FSS1 -Z
    ((90, 90, 180), (0, 90, 90), (90, 180, 90)),      # FSS2 -X
    ((0, 90, 90), (90, 75, 15), (90, 165, 75)),       # FSS3 +Y, 15 deg to +Z
    ((90, 90, 0), (180, 90, 90), (90, 180, 90)),      # FSS4 +X
    ((180, 90, 90), (90, 105, 165), (90, 165, 75)),   # FSS5 -Y, 15 deg to +Z
    ((180, 90, 90), (90, 180, 90), (90, 90, 0)),      # FSS6 +Z
)
FIRMWARE_C = [np.cos(np.radians(np.array(m, dtype=float))) for m in FIRMWARE_REL_DCM_DEG]


def sun_arrays():
    """The sun array of every model variant: legacy, CAD stowed, CAD deployed."""
    return {
        'legacy': config._load_configuration(use_advanced_satellite_model=False)[10].sun_array,
        'stowed': config._load_configuration(use_advanced_satellite_model=True, panels_deployed=False)[10].sun_array,
        'deployed': config._load_configuration(use_advanced_satellite_model=True, panels_deployed=True)[10].sun_array,
    }


@pytest.fixture
def receiver(monkeypatch):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(2)
    monkeypatch.setattr(sensor_link, 'ADS_SENSOR_PORT', sock.getsockname()[1])
    yield sock
    sock.close()


@pytest.mark.parametrize('variant', ['legacy', 'stowed', 'deployed'])
def test_cell_mountings_reproduce_firmware_rel_dcm(variant):
    cells = sun_arrays()[variant].cells
    assert len(cells) == 6
    for k, (cell, expected) in enumerate(zip(cells, FIRMWARE_C)):
        mount = sensor_to_body_matrix(cell.normal_body, cell.sensor_roll_rad)
        np.testing.assert_allclose(mount, expected, atol=1e-5, err_msg=f'{variant} cell {k} ({cell.name})')


def test_gps_packet_is_obc_decoded_ads_gps_data(receiver):
    data = {'fix_mode': 3, 'num_SV': 9, 'GNSS_Week': 2386, 'GNSS_TOW': 30123456,
            'Latitude': -123456789, 'Longitude': 1234567890,
            'Ellipsoid_altitude': 50000312, 'Mean_Sea_Level_Altitude': 49998000,
            'GDOP': 250, 'PDOP': 210, 'HDOP': 120, 'VDOP': 170, 'TDOP': 130,
            'ECEF_X': 678912345, 'ECEF_Y': -12345678, 'ECEF_Z': 3456,
            'ECEF_VX': -1234, 'ECEF_VY': 765432, 'ECEF_VZ': 98}
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sensor_link.send_gps(sender, RawGpsSample(0.0, 0.0, 0.08, 1.0, 2.0, data))
    finally:
        sender.close()
    packet = receiver.recvfrom(1024)[0]
    assert len(packet) == 1 + 134 and packet[0] == sensor_link.SENSOR_ID_GPS
    fields = struct.unpack(sensor_link.GPS_PAYLOAD_FORMAT, packet[1:])
    assert fields[:3] == (3, 9, 2386)
    assert fields[3] == pytest.approx(301234.56)                     # TOW [s]
    assert fields[4:8] == (pytest.approx(-12.3456789), b'S', pytest.approx(123.456789), b'E')
    assert fields[8:10] == (pytest.approx(500003.12), pytest.approx(499980.0))
    assert fields[10:15] == pytest.approx((2.5, 2.1, 1.2, 1.7, 1.3))
    assert fields[15:21] == pytest.approx((6789123.45, -123456.78, 34.56, -12.34, 7654.32, .98))


@pytest.mark.parametrize('variant', ['legacy', 'deployed'])
def test_fss_packets_give_firmware_the_physical_sun(variant, receiver):
    """Sun model fed the SITL sensor-frame quaternion -> packets -> firmware
    decode + RelDCM must give _dcm_bi_from_q(q) @ sun_eci for every used head."""
    # Zero latency too: each tick below jumps to a random attitude, so any
    # lookback would blend in the previous trial's attitude.
    cfg = replace(sun_arrays()[variant], enable_alignment_error=False, enable_bias_drift=False,
                  enable_scale_nonlinearity=False, enable_white_noise=False,
                  enable_albedo=False, enable_self_shadowing=False, dropout_probability=0.0,
                  latency_mean_s=0.0, latency_sigma_s=0.0, latency_min_s=0.0, latency_max_s=0.0)
    array = SimulatedSunSensorArray(cfg, record_history=False)
    rng = np.random.default_rng(3)
    sun_eci = np.array([0.3, -0.8, 0.52])
    sun_eci /= np.linalg.norm(sun_eci)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    used_total = 0
    try:
        for i in range(40):
            q = rng.normal(size=4)
            q /= np.linalg.norm(q)
            q_sensor = q * np.array([1.0, -1.0, -1.0, -1.0])     # as satellite_flight_visualisation in SITL
            raw = array.get_raw_data(0.1 * i, q_sensor, sun_eci, 1.0, None)
            heads = sensor_link.send_fss(sender, raw, cfg.cells)
            expected = _dcm_bi_from_q(q) @ sun_eci
            for _ in range(6):
                packet = receiver.recvfrom(1024)[0]
                assert len(packet) == 27 and packet[0] == sensor_link.SENSOR_ID_FSS
                values = dict(zip(sensor_link.FSS_FIELDS, struct.unpack(sensor_link.FSS_PACKET_FORMAT, packet)[2:]))
                idx = packet[1] - 0x11
                q_sum = sum(v if v <= 10000 else 0 for v in (values['Q1'], values['Q2'], values['Q3'], values['Q4']))
                usable = abs(values['Alpha']) <= 3500 and abs(values['Beta']) <= 3500
                assert heads[idx]['used'] == (q_sum >= 400 and usable)
                if not heads[idx]['used']:
                    continue
                used_total += 1
                vec = np.array([values['VecX'], values['VecY'], values['VecZ']], dtype=float) / 10000.0
                body = FIRMWARE_C[idx] @ vec
                angle = math.degrees(math.acos(np.clip(body @ expected / np.linalg.norm(body), -1, 1)))
                assert angle < 0.1, f'trial {i}, FSS{idx + 1}: {angle:.3f} deg from the physical Sun'
    finally:
        sender.close()
    assert used_total >= 10   # enough attitudes put the Sun inside some head's window


# ---- IMU (ADIS16545 gyro + AK09916 magnetometer) ---------------------------
FIRMWARE_C_MAG = np.cos(np.radians(np.array(((0, 90, 90), (90, 180, 90), (90, 90, 180)), dtype=float)))   # RelDCM[4]
FIRMWARE_C_GYRO = np.cos(np.radians(np.array(((90, 0, 90), (0, 90, 90), (90, 90, 180)), dtype=float)))   # RelDCM[9]
FIRMWARE_GYRO_DEG_S_PER_COUNT = 65536.0 / 10485760.0


def firmware_imu_decode(gyro_counts, mag_counts):
    """sitl_processHybridGyroMag() without the clamps and updateEst() (a
    constant input passes through that filter unchanged): body rate in deg/s,
    body field in uT."""
    from firmware_sitl_adapter import BOARD_MAG_CAL_BIAS_UT, BOARD_MAG_CAL_MATRIX
    rate = FIRMWARE_C_GYRO @ (np.asarray(gyro_counts, dtype=float) * FIRMWARE_GYRO_DEG_S_PER_COUNT)
    mag_sensor = np.asarray(mag_counts, dtype=float) * 0.15
    mag_sensor = np.array(BOARD_MAG_CAL_MATRIX) @ (mag_sensor - np.array(BOARD_MAG_CAL_BIAS_UT))
    return rate, FIRMWARE_C_MAG @ mag_sensor


def test_imu_mountings_reproduce_firmware_rel_dcm():
    imu = config.IMU_SIM
    np.testing.assert_allclose(_dcm_bi_from_q(imu.gyro_mount_quaternion), FIRMWARE_C_GYRO, atol=1e-12)
    np.testing.assert_allclose(_dcm_bi_from_q(imu.mag_mount_quaternion), FIRMWARE_C_MAG, atol=1e-12)


def test_imu_packets_give_firmware_the_physical_rate_and_field(receiver):
    """Gyroscope/magnetometer models (the magnetometer with the board's error,
    as SITL builds it) fed the SITL sensor-frame quaternion -> packets ->
    firmware decode must give the true body rate and _dcm_bi_from_q(q) @ B_eci."""
    from simulate_gyroscope import SimulatedGyroscope
    from simulate_magnetometer import SimulatedMagnetometer
    from firmware_sitl_adapter import with_board_magnetometer
    perfect = config._apply_sensor_profile(config.IMU_SIM, 'perfect')
    gyro_cfg = perfect
    mag_cfg = with_board_magnetometer(replace(perfect, mag_disturbance_t=(0.0, 0.0, 0.0)))
    rng = np.random.default_rng(5)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for trial in range(20):
            q = rng.normal(size=4)
            q /= np.linalg.norm(q)
            omega = np.radians(rng.uniform(-10.0, 10.0, size=3))        # rad/s, body
            b_eci = rng.normal(size=3) * 25e-6                          # T
            q_sensor = q * np.array([1.0, -1.0, -1.0, -1.0])            # as satellite_flight_visualisation in SITL
            # fresh sensors each trial: latency never blends two trials
            gyro = SimulatedGyroscope(gyro_cfg, record_history=False).get_raw_data(0.0, q_sensor, omega)
            mag = SimulatedMagnetometer(mag_cfg, record_history=False).get_raw_data(0.0, q_sensor, b_eci)
            sensor_link.send_imu(sender, gyro, mag)
            packets = {}
            for _ in range(2):
                packet = receiver.recvfrom(1024)[0]
                assert len(packet) == 7
                packets[packet[0]] = struct.unpack('<3h', packet[1:])
            assert set(packets) == {sensor_link.SENSOR_ID_GYRO, sensor_link.SENSOR_ID_MAG}
            rate, field = firmware_imu_decode(packets[sensor_link.SENSOR_ID_GYRO], packets[sensor_link.SENSOR_ID_MAG])
            np.testing.assert_allclose(rate, np.degrees(omega), atol=0.007,          # one high-word count
                                       err_msg=f'trial {trial} body rate')
            np.testing.assert_allclose(field, (_dcm_bi_from_q(q) @ b_eci) * 1e6, atol=0.25,   # ~1.5 counts
                                       err_msg=f'trial {trial} body field')
    finally:
        sender.close()


def test_imu_dropout_sends_nothing(receiver):
    sample = type('Sample', (), {'valid': False, 'data': {'X_axis': 1, 'Y_axis': 2, 'Z_axis': 3}})()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sensor_link.send_imu(sender, sample, None)
        receiver.settimeout(0.2)
        with pytest.raises(socket.timeout):
            receiver.recvfrom(1024)
    finally:
        sender.close()


# ---- Star tracker (Sagitta Solution) -----------------------------------------
FIRMWARE_C_STAR_TRACKER = np.cos(np.radians(np.array(((85, 175, 90), (90, 90, 180), (5, 85, 90)), dtype=float)))   # RelDCM[3]


def hamilton(a, b):
    return sensor_link._hamilton(a, b)


def firmware_absquat(q_st):
    """sensor2bodyquat(StarTracker, q_ST) = RelQuat[3] (x) q_ST."""
    return hamilton(sensor_link.FIRMWARE_STAR_TRACKER_REL_QUAT, q_st)


def quaternion_angle_deg(a, b):
    return math.degrees(2 * math.acos(min(1.0, abs(float(np.dot(a, b))) / (np.linalg.norm(a) * np.linalg.norm(b)))))


def test_star_tracker_mount_reproduces_firmware_rel_quat():
    mount = config.IMU_SIM.star_tracker.mount_quaternion
    np.testing.assert_allclose(_dcm_bi_from_q(mount), FIRMWARE_C_STAR_TRACKER, atol=2e-6)
    np.testing.assert_allclose(np.asarray(mount) * np.array([1, -1, -1, -1]),
                               sensor_link.FIRMWARE_STAR_TRACKER_REL_QUAT, atol=1e-12)


def _unpack_solution(packet):
    fields = struct.unpack(sensor_link.STAR_TRACKER_PACKET_FORMAT, packet)
    assert fields[0] == sensor_link.SENSOR_ID_STAR_TRACKER and len(packet) == 80
    return {'q': np.array(fields[3:7]), 'trust': fields[22], 'matched': fields[14], 'tq': np.array(fields[8:12])}


@pytest.mark.parametrize('profile', ['perfect', 'nominal'])
def test_star_tracker_solution_gives_firmware_the_physical_attitude(profile, receiver):
    """Tracker model sampled with the SITL firmware-frame quaternion -> Solution
    packet -> firmware's RelQuat[3] (x) q_ST must give the true body->ECI
    attitude (to the tracker's own error)."""
    from simulate_startracker import SimulatedStarTracker
    base = getattr(config.StarTrackerParameters, profile)()
    cfg = replace(base, mount_quaternion=config.IMU_SIM.star_tracker.mount_quaternion,
                  enable_blinding=False, enable_kinematic_limits=False, enable_dropouts=False,
                  enable_outliers=False, enable_latency=False, cold_start_s=0.0, low_trust_packets=0)
    rng = np.random.default_rng(9)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    worst_chain = worst_truth = 0.0
    try:
        for trial in range(20):
            q = rng.normal(size=4)
            q /= np.linalg.norm(q)
            tracker = SimulatedStarTracker(config=cfg)
            q_sensor = q * np.array([1.0, -1.0, -1.0, -1.0])     # as satellite_flight_visualisation in SITL
            receipt = tracker.get_raw_data(0.0, q_sensor, np.array([7e6, 0, 0]), np.array([0, 1.0, 0]), np.zeros(3))
            assert receipt is not None and receipt.valid
            sensor_link.send_star_tracker(sender, receipt, 1.79e9)
            solution = _unpack_solution(receiver.recvfrom(1024)[0])
            assert solution['trust'] == 1 and solution['matched'] > 0
            np.testing.assert_allclose(solution['tq'], solution['q'])
            absquat = firmware_absquat(solution['q'])
            # the tracker's measured attitude in the firmware's convention
            measured = np.asarray(receipt.quaternion_eci) * np.array([1.0, -1.0, -1.0, -1.0])
            worst_chain = max(worst_chain, quaternion_angle_deg(absquat, measured))
            worst_truth = max(worst_truth, quaternion_angle_deg(absquat, q))
    finally:
        sender.close()
    # The link must deliver exactly what the tracker measured (float32 on the
    # wire); the tracker's own modelled error is the only difference from truth.
    assert worst_chain * 3600 < 1.0, f'{profile}: link adds {worst_chain * 3600:.3f} arcsec'
    assert worst_truth < (1e-4 if profile == 'perfect' else 0.05), f'{profile}: {worst_truth * 3600:.1f} arcsec from truth'


def test_star_tracker_invalid_receipt_sends_no_solution(receiver):
    receipt = type('Receipt', (), dict(valid=False, trusted=False, quaternion_eci=np.array([1.0, 0, 0, 0]),
                                       num_stars=0, quality=0.0, t_meas_s=1.0, mode='BLINDED'))()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sensor_link.send_star_tracker(sender, receipt, 1.79e9)
        solution = _unpack_solution(receiver.recvfrom(1024)[0])
        assert solution['trust'] == 0 and solution['matched'] == 0
        assert not np.any(solution['q'])
        sensor_link.send_star_tracker(sender, None, 1.79e9)          # no receipt yet: nothing sent
        receiver.settimeout(0.2)
        with pytest.raises(socket.timeout):
            receiver.recvfrom(1024)
    finally:
        sender.close()
