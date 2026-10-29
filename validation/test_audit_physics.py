"""Independent physical references for A001/A002/A006/A011 regressions."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from attitude_frames import body_to_eci


@pytest.fixture
def firmware_plant():
    # Plant arithmetic must not bind the live firmware ports or share socket
    # state with the separate real-UDP integration test.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('audit_firmware_plant',
        Path(__file__).resolve().parents[1] / 'firmware_sitl_link.py')
    module = importlib.util.module_from_spec(spec)
    dummy_socket = lambda *a, **k: SimpleNamespace(bind=lambda *a: None, setblocking=lambda *a: None)
    with patch('socket.socket', dummy_socket):
        spec.loader.exec_module(module)
    return module


def test_positive_body_rotation_and_vector_derivative():
    # A positive quarter turn takes body +X to inertial +Y, so a fixed
    # inertial +X vector is seen along body -Y. No project DCM as reference.
    q = np.array([np.sqrt(.5), 0., 0., np.sqrt(.5)])
    np.testing.assert_allclose(body_to_eci(q) @ [1., 0., 0.], [0., 1., 0.], atol=1e-15)
    np.testing.assert_allclose(body_to_eci(q).T @ [1., 0., 0.], [0., -1., 0.], atol=1e-15)
    rng = np.random.default_rng(72)
    for _ in range(20):
        q = rng.normal(size=4); q /= np.linalg.norm(q)
        omega = rng.normal(size=3)
        reference = Rotation.from_quat(q[[1, 2, 3, 0]])
        np.testing.assert_allclose(body_to_eci(q), reference.as_matrix(), atol=1e-15)
        vector = rng.normal(size=3)
        dt = 1e-7
        later = reference * Rotation.from_rotvec(omega*dt)
        derivative = (later.inv().apply(vector)-reference.inv().apply(vector))/dt
        np.testing.assert_allclose(derivative, -np.cross(omega, reference.inv().apply(vector)), atol=2e-6)


def test_magnetic_field_passes_height_in_metres():
    import engine.orekit_runtime
    from engine.physics.magnetic_field import OrekitIGRF
    from org.orekit.models.earth import GeoMagneticFieldFactory
    model = GeoMagneticFieldFactory.getWMM(2026.)
    captured = []
    class RecordingModel:
        def calculateField(self, latitude, longitude, height):
            captured.append((latitude, longitude, height))
            return model.calculateField(latitude, longitude, height)
    geodetic = SimpleNamespace(getLatitude=lambda: .5, getLongitude=lambda: 1., getAltitude=lambda: 500000.)
    earth = SimpleNamespace(transform=lambda *args: geodetic)
    identity = SimpleNamespace(transformVector=lambda vector: vector)
    fixed = SimpleNamespace(getTransformTo=lambda *args: identity)
    field = OrekitIGRF(earth, object(), fixed)
    field._models[2026] = RecordingModel()
    actual = field.field_eci(np.array([7e6, 0., 0.]), datetime(2026, 1, 1, tzinfo=timezone.utc), None)
    assert captured == [(.5, 1., 500000.)]
    expected = model.calculateField(.5, 1., 500000.).getFieldVector().getNorm()
    assert np.linalg.norm([actual.x, actual.y, actual.z]) == pytest.approx(expected, rel=1e-14)


@pytest.mark.parametrize('mode', ['FIRMWARE_SITL', 'SUN_POINTING'])
def test_nonidentity_magnetic_plant_and_telemetry_agree(mode, monkeypatch):
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import control_states as cs
    import store
    q = np.array([np.sqrt(.5), 0., 0., np.sqrt(.5)])
    field = np.array([2e-5, 0., 0.])
    dipole = np.array([0., 0., 1.])
    expected_torque = np.cross(dipole, [0., -2e-5, 0.])
    monkeypatch.setitem(cs.mode, 'value', mode)
    monkeypatch.setattr(dynamics, 'detumbling_complete', True)
    monkeypatch.setattr(dynamics, '_firmware_wheels', np.zeros(4))
    monkeypatch.setattr(dynamics, '_firmware_dipole', dipole)
    monkeypatch.setattr(dynamics, '_firmware_wheel_axes', lambda: np.zeros((3, 4)))
    monkeypatch.setattr(dynamics.cd, 'DISTURBANCES_ENABLED', False)
    monkeypatch.setattr(dynamics, '_imu_adcs_enabled', [False])
    monkeypatch.setattr(dynamics, '_imu_adcs_use_attitude', [False])
    monkeypatch.setattr(dynamics.sun_pointing, 'control_torque', lambda q, w, b, t: (np.cross(dipole, b), dipole))
    derivative = dynamics.rotational_equations_of_motion(0., np.r_[q, np.zeros(3)], field)
    np.testing.assert_allclose(dynamics.I @ derivative[4:], expected_torque, atol=1e-18)
    np.testing.assert_allclose(store.mtr_torques, expected_torque, atol=1e-18)


def test_pointing_targets_preserve_physical_boresights():
    from nadir_pointing import nadir_pointing_quaternion
    from nominal_in_orbit_pointing import nominal_in_orbit_pointing_quaternion
    from kinematic_robustness_pointing import kinematic_robustness_pointing_quaternion
    from sun_pointing_rw_z import sun_pointing_rw_z_quaternion
    from sun_pointing_rw import sun_pointing_quaternion
    from sun_vector_eci import sun_vector_eci
    from periodic_gain_sun_pointing import Q_TARGET, _sun0
    epoch = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    r = np.array([3e6, -5e6, 4e6]); v = np.array([6500., 3900., 0.])
    nadir = -r / np.linalg.norm(r)
    for yaw in [-45., 0., 90.]:
        q = nominal_in_orbit_pointing_quaternion(r, v, yaw_bias_deg=yaw)
        np.testing.assert_allclose(body_to_eci(q)[:, 0], nadir, atol=1e-14)
    np.testing.assert_allclose(body_to_eci(nadir_pointing_quaternion(r, v))[:, 0], nadir, atol=1e-14)
    for t in [0., 37., 180.]:
        q = kinematic_robustness_pointing_quaternion(r, v, t)
        np.testing.assert_allclose(body_to_eci(q)[:, 2], nadir, atol=1e-14)
    np.testing.assert_allclose(-body_to_eci(sun_pointing_rw_z_quaternion(epoch))[:, 2], sun_vector_eci(epoch), atol=1e-14)
    np.testing.assert_allclose(-body_to_eci(sun_pointing_quaternion(epoch))[:, 0], sun_vector_eci(epoch), atol=1e-14)
    np.testing.assert_allclose(-body_to_eci(Q_TARGET)[:, 2], _sun0, atol=1e-14)


def test_surface_and_disturbance_frames_are_rotation_covariant():
    from spacecraft_surface_physics import SurfaceForceModel, AU_M
    import calculate_disturbances as disturbances
    import satellite_parameters as config
    model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
    q = np.array([.5, -.5, .5, .5])
    rotation = Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix()
    r = np.array([7e6, 0., 0.]); v = np.array([0., 7500., 300.])
    sun = np.array([AU_M, AU_M*.4, AU_M*.2]); air = np.array([0., 450., 0.])
    original = model.evaluate([1., 0., 0., 0.], r, v, sun, .8, 1e-12, air)
    rotated = model.evaluate(q, rotation@r, rotation@v, rotation@sun, .8, 1e-12, rotation@air)
    for name in ['srp_torque_body_nm', 'drag_torque_body_nm']:
        np.testing.assert_allclose(getattr(rotated, name), getattr(original, name), atol=1e-18)
    for name in ['srp_force_eci_n', 'drag_force_eci_n']:
        np.testing.assert_allclose(getattr(rotated, name), rotation@getattr(original, name), atol=1e-18)
    field = np.array([1e-5, -2e-5, 3e-5])
    for function, vector in [(disturbances.gravity_gradient_torque_body, r),
                             (disturbances.residual_dipole_torque_body, field)]:
        np.testing.assert_allclose(function(q, rotation@vector), function([1., 0., 0., 0.], vector), atol=1e-18)


def test_nonidentity_custom_pointing_converges_with_existing_controller(monkeypatch):
    from scipy.integrate import solve_ivp
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import control_states as cs
    import torque_distribution as wheels
    target = Rotation.from_euler('xyz', [35., -20., 80.], degrees=True)
    initial = target * Rotation.from_rotvec([.04, -.03, .02])
    target_q = target.as_quat()[[3, 0, 1, 2]]
    monkeypatch.setitem(cs.mode, 'value', 'CUSTOM')
    monkeypatch.setattr(dynamics, '_custom_tick_target', target_q)
    monkeypatch.setattr(dynamics, 'detumbling_complete', True)
    monkeypatch.setattr(dynamics, '_imu_adcs_enabled', [False])
    monkeypatch.setattr(dynamics, '_imu_adcs_use_attitude', [False])
    monkeypatch.setattr(dynamics.cd, 'DISTURBANCES_ENABLED', False)
    monkeypatch.setattr(wheels, '_wheel_momentum', [np.zeros(4)])
    result = solve_ivp(lambda t, y: dynamics.rotational_equations_of_motion(t, y, [0., 0., 3e-5]),
                       [0., 360.], np.r_[initial.as_quat()[[3, 0, 1, 2]], np.zeros(3)],
                       rtol=1e-8, atol=1e-10, max_step=.5)
    assert result.success
    final = Rotation.from_quat(result.y[:4, -1][[1, 2, 3, 0]])
    assert np.degrees((target.inv()*final).magnitude()) < .05
    assert np.linalg.norm(result.y[4:, -1]) < 1e-4


def test_firmware_limits_impulse_reversal_and_achieved_telemetry(monkeypatch, firmware_plant):
    link = firmware_plant
    import satellite_parameters as config
    hmax = config.WHEEL_MAX_MOMENTUM_NMS
    initial = np.array([hmax-5e-5, -hmax+5e-5, hmax, -hmax])
    monkeypatch.setattr(link, '_wheel_momentum', initial.tolist())
    monkeypatch.setattr(link, '_latest_torque_mNm', [-400., 400., 400., -400.])
    monkeypatch.setattr(link, '_latest_mtr_dipole_Am2', [1e6, -1e6, .34])
    monkeypatch.setattr(link, '_applied_torque_Nm', np.zeros(4))
    wheels, dipole = link.apply_actuator_limits(.1)
    np.testing.assert_allclose(wheels, [-.0005, .0005, .004, -.004], atol=1e-15)
    assert np.all(np.abs(dipole) <= config.MTR_MAX_DIPOLE_AM2)
    assert dipole[2] == pytest.approx(.3)
    link.step_wheel_momentum(.1)
    np.testing.assert_allclose(link._wheel_momentum, initial-wheels*.1, atol=1e-15)
    assert np.all(np.abs(link._wheel_momentum) <= hmax+1e-15)
    # Positive body torque and negative rotor impulse cancel about each spin axis.
    np.testing.assert_allclose(link.FLIGHT_WHEEL_AXES_BODY @ (np.asarray(link._wheel_momentum)-initial+wheels*.1), 0., atol=1e-17)
    packets = []
    monkeypatch.setattr(link, '_tlm_sock', SimpleNamespace(sendto=lambda packet, address: packets.append(packet)))
    link.send_rw_telemetry()
    import struct
    torques = [struct.unpack(link.TLM_FORMAT, packet)[2]*1e-3 for packet in packets]
    np.testing.assert_allclose(torques, wheels)
    # Once at the boundary, further outward commands are blocked; inward works.
    wheels, _ = link.apply_actuator_limits(.1)
    np.testing.assert_allclose(wheels[:2], 0., atol=1e-15)
    monkeypatch.setattr(link, '_latest_torque_mNm', [4., -4., 0., 0.])
    wheels, _ = link.apply_actuator_limits(.1)
    np.testing.assert_allclose(wheels[:2], [.004, -.004])
    with pytest.raises(ValueError):
        link.apply_actuator_limits(0.)


def test_magnetorquer_current_bound(monkeypatch, firmware_plant):
    link = firmware_plant
    import satellite_parameters as config
    from dataclasses import replace
    from satellite_rotational_dynamics_var_mag_field import compute_MTR_power
    monkeypatch.setattr(link, '_latest_mtr_dipole_Am2', [100., -100., 100.])
    monkeypatch.setattr(config, 'SPACECRAFT', replace(config.SPACECRAFT, mtr_max_current_A=(.001, .002, .003)))
    _, dipole = link.apply_actuator_limits(.1)
    assert np.all(np.asarray(compute_MTR_power(dipole)[1:]) <= np.array([.001, .002, .003])+1e-15)
