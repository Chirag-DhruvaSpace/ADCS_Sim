"""Firmware SITL sensor link: bytes on UDP 5010 must read, through the
firmware's own decode and mounting, as the physical truth.

The firmware side is reproduced here from its sources:
  RelDCM        ADS main.c (AdsConfigStruct.RelDCM[0,1,2,6,7,8], slaves 0x11..0x16)
  sensor2body   utils/coord_transform.c: v_body = cos(RelDCM) @ v_sensor
  fssTask       sitl_task_defs.c: Q > 10000 -> 0, lit = sum(Q) >= 400,
                usable = |Alpha|, |Beta| <= 3500
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
from simulategps import RawGpsSample
from simulatesunsensor import SimulatedSunSensorArray, sensor_to_body_matrix, _dcm_bi_from_q

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
    cfg = replace(sun_arrays()[variant], enable_alignment_error=False, enable_bias_drift=False,
                  enable_scale_nonlinearity=False, enable_white_noise=False,
                  enable_albedo=False, enable_self_shadowing=False, dropout_probability=0.0)
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
