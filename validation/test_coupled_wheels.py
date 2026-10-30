"""Independent boundary and conservation checks for audit A003--A005."""
import numpy as np
import pytest
from scipy.integrate import solve_ivp
from scipy.spatial.transform import Rotation
from attitude_frames import body_to_eci


def test_rotation_conversion_at_half_turn_and_nearby():
    from quat2eul import rotmat_to_quaternion
    for axis in np.r_[np.eye(3), [[1., 2., -3.]]]:
        axis = axis / np.linalg.norm(axis)
        for angle in [np.pi, np.pi-1e-10, np.pi+1e-10]:
            matrix = Rotation.from_rotvec(axis*angle).as_matrix()
            q = rotmat_to_quaternion(matrix)
            np.testing.assert_allclose(body_to_eci(q), matrix, atol=1e-14)
            assert np.linalg.norm(q) == pytest.approx(1.)
    for matrix in [np.diag([1., 1., -1.]), np.full((3, 3), np.nan)]:
        with pytest.raises(ValueError):
            rotmat_to_quaternion(matrix)


def test_magnetic_allocator_always_returns_pair_for_unavailable_field():
    from MTR_allocator import torque_to_dipole
    for field in [[0., 0., 0.], [1e-7, 0., 0.], [np.nan, 0., 0.]]:
        moment, achieved = torque_to_dipole([1., 2., 3.], field)
        np.testing.assert_array_equal(moment, np.zeros(3))
        np.testing.assert_array_equal(achieved, np.zeros(3))
    moment, achieved = torque_to_dipole([0., 1e-8, 0.], [1e-6, 0., 0.])
    np.testing.assert_allclose(achieved, np.cross(moment, [1e-6, 0., 0.]))


@pytest.mark.parametrize('mode', ['FIRMWARE_SITL', 'CUSTOM'])
@pytest.mark.parametrize('command', [0., 0.0003])
def test_coupled_rotors_conserve_inertial_momentum(mode, command, monkeypatch):
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import torque_distribution as wheels
    import control_states as cs
    monkeypatch.setitem(cs.mode, 'value', mode)
    monkeypatch.setattr(dynamics, 'DETUMBLE_ON_DEG_S', 1e9)
    monkeypatch.setattr(dynamics, 'detumbling_complete', True)
    monkeypatch.setattr(dynamics.cd, 'DISTURBANCES_ENABLED', False)
    monkeypatch.setattr(dynamics, '_imu_adcs_enabled', [False])
    monkeypatch.setattr(dynamics, '_imu_adcs_use_attitude', [False])
    u = np.array([command, -command, command/2, 0.])
    monkeypatch.setattr(dynamics, '_firmware_wheels', u)
    monkeypatch.setattr(dynamics, '_firmware_dipole', np.zeros(3))
    monkeypatch.setattr(dynamics, '_firmware_wheel_axes', lambda: wheels.A)
    monkeypatch.setattr(wheels, 'reaction_wheel_torque_distribution', lambda *a, **k: u)
    q = Rotation.from_euler('xyz', [.3, -.4, .7]).as_quat()[[3, 0, 1, 2]]
    initial = np.r_[q, [.03, -.02, .01], [.007, -.004, .003, -.002]]
    result = solve_ivp(lambda t, y: dynamics.rotational_equations_of_motion(t, y, np.zeros(3)),
                       [0., 8.], initial, method='DOP853', rtol=1e-11, atol=1e-13)
    assert result.success
    reference = body_to_eci(q) @ (dynamics.I @ initial[4:7] + wheels.A @ initial[7:])
    for state in result.y.T:
        momentum = body_to_eci(state[:4]) @ (dynamics.I @ state[4:7] + wheels.A @ state[7:])
        np.testing.assert_allclose(momentum, reference, atol=2e-11)
    np.testing.assert_allclose(result.y[7:, -1], initial[7:]-u*8, atol=1e-12)


def test_capacity_sign_and_nullspace_desaturation():
    import torque_distribution as wheels
    cap = wheels.MAX_WHEEL_MOMENTUM
    np.testing.assert_array_equal(wheels._apply_wheel_limits([-1., 1.], [cap, -cap]), [0., 0.])
    allowed = wheels._apply_wheel_limits([1., -1.], [cap, -cap])
    assert allowed[0] > 0 and allowed[1] < 0
    h = wheels.NULL_VEC * .003
    u = wheels.reaction_wheel_torque_distribution(0., 0., 0., wheel_momentum=h, hold_period_s=.1)
    np.testing.assert_allclose(wheels.A @ u, 0., atol=1e-18)
    assert np.dot(h, -u) < 0


def test_accepted_coupled_endpoint_is_not_integrated_twice(monkeypatch):
    from types import SimpleNamespace
    from firmware_sitl_adapter import integrate_firmware_step
    import torque_distribution as wheels
    h0 = np.array([wheels.MAX_WHEEL_MOMENTUM-5e-5, 0., 0., 0.])
    commits = []
    held = np.array([-.004, 0., 0., 0.])
    class Link:
        schedule_lag_s = 0.
        def send_imu(self, *args): pass
        def poll_commands(self, dt): return held, np.zeros(3)
        def finish_tick(self, dt, publish=True, wheel_momentum=None):
            assert wheel_momentum is not None
            commits.append(wheel_momentum.copy())
    def solve(start, end, state):
        u = wheels._apply_wheel_limits(held, state[7:], end-start)
        # Exact held impulse is an independent reference for the step helper.
        endpoint = state.copy(); endpoint[7:] -= u*(end-start)
        return SimpleNamespace(success=True, t=[start,end], y=np.c_[state,endpoint])
    initial = np.r_[1., np.zeros(6), h0]
    endpoint = integrate_firmware_step(0., .1, initial, solve, Link(),
        SimpleNamespace(wait_firmware_sample=lambda *a:0.),
        lambda *a:(None,None), lambda *a:None)
    assert len(commits) == 10
    assert endpoint[7] == pytest.approx(wheels.MAX_WHEEL_MOMENTUM)
    np.testing.assert_array_equal(commits[-1], endpoint[7:])
