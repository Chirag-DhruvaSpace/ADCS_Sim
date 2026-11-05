"""Check the supplied formula, our +X frame, and the real C control path."""
import ast
import ctypes
import importlib.util
import json
import socket
import struct
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

import yaw_steering as yaw
from nadir_pointing import nadir_pointing_quaternion
from quat2eul import quaternion_multiply

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def firmware():
    spec = importlib.util.spec_from_file_location('sitl_build', ROOT / 'validation/tools/build_firmware_sitl.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    dll = ROOT / '.cache/yaw_steering/yaw_test.dll'
    builder.build(dll, shared=True, extra_sources=[str(ROOT / 'validation/yaw_steering_driver.c')])
    fw = ctypes.CDLL(str(dll))
    fw.yaw_test_step.argtypes = [ctypes.POINTER(ctypes.c_double)] * 5
    fw.yaw_test_mode.argtypes = [ctypes.c_int] * 3
    fw.yaw_test_init()
    return fw


def c_step(fw, r, v, q=(1, 0, 0, 0), w=(0, 0, 0)):
    inputs = [(ctypes.c_double * len(x))(*x) for x in (r, v, q, w)]
    out = (ctypes.c_double * 16)()
    fw.yaw_test_step(*inputs, out)
    return np.array(out)


def samples():
    random = np.random.default_rng(30)
    for _ in range(150):
        r = random.normal(size=3)
        r *= 6.9e6 / np.linalg.norm(r)
        v = random.normal(size=3)
        v -= np.dot(v, r) / np.dot(r, r) * r
        v *= 7600 / np.linalg.norm(v)
        yield r, v


def test_matches_original_supplied_function(firmware):
    source = Path('C:/Users/chirag.m_dhruvaspace/Downloads/yaw-steering files/yaw_steering.py')
    if not source.exists():
        pytest.skip('Original reference files are not present on this machine')
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'calculate_desired_yaw_angle')
    namespace = {'np': np, 'Omega_Earth': np.array([0, 0, 7.2921159e-5])}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    for r, v in samples():
        expected = namespace['calculate_desired_yaw_angle'](r, v)
        assert yaw.calculate_desired_yaw_angle(r, v) == pytest.approx(expected, abs=1e-12)
        assert c_step(firmware, r, v)[0] == pytest.approx(expected, abs=1e-10)


def test_c_and_python_targets_keep_firmware_axes(firmware):
    for r, v in samples():
        q = yaw.yaw_steering_quaternion(r, v)
        actual = c_step(firmware, r, v)
        assert actual[11] == 1
        assert abs(np.dot(q, actual[1:5])) == pytest.approx(1, abs=1e-12)
        matrix = Rotation.from_quat([*q[1:], q[0]]).as_matrix()
        np.testing.assert_allclose(matrix[:, 0], -r / np.linalg.norm(r), atol=1e-12)
        q_base = nadir_pointing_quaternion(r, v)
        relative = quaternion_multiply([q_base[0], *(-q_base[1:])], q)
        if relative[0] < 0:
            relative = -relative
        assert relative[2:] == pytest.approx([0, 0], abs=1e-12)
        assert 2*np.degrees(np.arctan2(relative[1], relative[0])) == pytest.approx(actual[0], abs=1e-10)
        np.testing.assert_allclose(actual[5:8], yaw.yaw_steering_target_rate(r, v), atol=1e-11)


def test_invalid_orbit_is_not_actuated(firmware):
    result = c_step(firmware, [0, 0, 0], [0, 0, 0])
    assert result[11] == 0
    np.testing.assert_array_equal(result[8:11], [0, 0, 0])
    with pytest.raises(ValueError):
        yaw.calculate_desired_yaw_angle([1, 0, 0], [1, 0, 0])


def test_mode_entry_exit_and_missing_navigation(firmware):
    c_step(firmware, [6.9e6, 0, 0], [0, 7000, 3000])
    assert firmware.yaw_test_event_number() == 49
    assert firmware.yaw_test_mode(0, 1, 1) == 12
    assert firmware.yaw_test_mode(1, 1, 1) != 12
    assert firmware.yaw_test_mode(2, 1, 1) == 2
    assert firmware.yaw_test_mode(0, 0, 1) != 12
    assert firmware.yaw_test_mode(0, 1, 0) != 12


def test_cosmos_tcp_mode_command_and_variables_packet(firmware):
    r, v = np.array([6.9e6, 0, 0]), np.array([0, 7000, 3000])
    expected = c_step(firmware, r, v)
    port = firmware.yaw_test_command_open()
    assert port > 0
    client = socket.create_connection(('127.0.0.1', port), timeout=2)
    try:
        assert firmware.yaw_test_command_accept() == 0
        def command(opcode, payload=b''):
            # Existing COSMOS packet, including its accepted CRC sentinel.
            client.sendall(struct.pack('<BBBH', 0x23, 1, opcode, len(payload))
                           + payload + b'\xff\xff\x3b')
            mode = firmware.yaw_test_command_poll()
            header = client.recv(5)
            assert len(header) == 5
            size = struct.unpack_from('<H', header, 3)[0]
            body = b''
            while len(body) < size+3:
                body += client.recv(size+3-len(body))
            return mode, header, body[:size]
        mode, _, _ = command(70, b'\x0c')
        assert mode == 12
        _, header, payload = command(250)
        assert header[2] == 250
        assert len(payload) == 121
        values = struct.unpack('<15dB', payload)
        assert values[0] == pytest.approx(expected[0], abs=1e-12)
        assert values[-1] == 1
        mode, _, _ = command(70, b'\x01')
        assert mode != 12
    finally:
        client.close()
        firmware.yaw_test_command_close()


def test_real_wheel_controller_tracks_a_moving_orbit(firmware):
    inertia = np.array([1.98095531, 0.93082278, 1.89464174])
    angle = np.radians(35)
    c, s = np.cos(angle), np.sin(angle)
    axes = np.array([[c, 0, -c, 0], [0, -c, 0, c], [-s, -s, -s, -s]])
    radius = 6.9e6
    orbit_rate = np.sqrt(3.986004418e14 / radius**3)
    tilt = Rotation.from_euler('xz', [97, 32], degrees=True).as_matrix()
    def orbit(t):
        a = orbit_rate*t
        return (tilt @ (radius*np.array([np.cos(a), np.sin(a), 0])),
                tilt @ (radius*orbit_rate*np.array([-np.sin(a), np.cos(a), 0])))
    r, v = orbit(0)
    target = yaw.yaw_steering_quaternion(r, v)
    offset = Rotation.from_euler('xyz', [8, -6, 5], degrees=True).as_quat()
    q = quaternion_multiply(target, [offset[3], *offset[:3]])
    w = np.zeros(3)
    momentum = np.zeros(4)
    firmware.yaw_test_init()
    errors = []
    dt = 0.2
    peak_rpm = 0.0
    for index in range(30000):
        r, v = orbit(index*dt)
        out = c_step(firmware, r, v, q, np.degrees(w))
        torque = axes @ out[12:16]
        # Integrate bus and wheel momentum together; use small attitude steps.
        for _ in range(4):
            sub = dt/4
            w += sub*(torque-np.cross(w, inertia*w + axes@momentum))/inertia
            rotation = Rotation.from_rotvec(w*sub).as_quat()
            q = quaternion_multiply(q, [rotation[3], *rotation[:3]])
            q /= np.linalg.norm(q)
            momentum -= sub*out[12:16]
        peak_rpm = max(peak_rpm, float(np.max(np.abs(momentum))/5.4e-5*60/(2*np.pi)))
        error = 2*np.degrees(np.arccos(np.clip(abs(np.dot(out[1:5], q)), 0, 1)))
        errors.append(error)
    report = {'duration_s': 6000, 'initial_error_deg': errors[0],
              'final_error_deg': errors[-1], 'max_error_after_400s_deg': max(errors[2000:]),
              'peak_wheel_rpm': peak_rpm,
              'conditions': 'Real C guidance/controller/allocation; ideal attitude, no disturbances'}
    (ROOT / '.cache/yaw_steering/tracking_result.json').write_text(json.dumps(report, indent=2))
    assert max(errors[2000:]) < 1.0, report
