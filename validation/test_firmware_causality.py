"""Command loss, causal sampling, configured albedo and common Sun-frame checks."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from validation.test_audit_physics import firmware_plant
from engine.simulation.pacing import SimulationPacer


def test_each_actuator_expires_independently_of_status(firmware_plant, monkeypatch):
    link = firmware_plant
    monkeypatch.setattr(link.time, 'monotonic', lambda: 10.)
    link._wheel_received_at[:] = [9.9, 0., None, 9.9]
    link._mtr_received_at[:] = [0., 9.9, None]
    link._latest_torque_mNm[:] = [1., 2., 3., 4.]
    link._latest_mtr_current_mA[:] = [100., 100., 100.]
    # An active mode/status stream must not keep dead actuator channels alive.
    link._latest_ads_mode[:] = [1]
    wheels, dipole = link.apply_actuator_limits(.01)
    np.testing.assert_allclose(wheels, [.001, 0., 0., .004])
    assert dipole[0] == dipole[2] == 0. and dipole[1] > 0.
    link.step_wheel_momentum(.01)
    stored = np.asarray(link._wheel_momentum).copy()
    monkeypatch.setattr(link.time, 'monotonic', lambda: 20.)
    wheels, dipole = link.apply_actuator_limits(.01)
    np.testing.assert_array_equal(wheels, np.zeros(4))
    np.testing.assert_array_equal(dipole, np.zeros(3))
    link.step_wheel_momentum(.01)
    np.testing.assert_array_equal(link._wheel_momentum, stored)
    # Reconnection of one wheel cannot revive another's old command.
    link._wheel_received_at[1] = 20.
    wheels, _ = link.apply_actuator_limits(.01)
    np.testing.assert_allclose(wheels, [0., .002, 0., 0.])


@pytest.mark.parametrize('overrun', [False, True])
def test_samples_are_paced_and_commands_affect_only_future_steps(overrun):
    from firmware_sitl_adapter import integrate_firmware_step
    clock = [0.]
    pacer = SimulationPacer(1., now=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0]+dt))
    command = [1.]
    samples, intervals, finishes = [], [], []
    class Link:
        schedule_lag_s = 0.
        def send_imu(self, gyro, mag):
            samples.append((clock[0], gyro[0], gyro[1]))
        def poll_commands(self, dt):
            return np.array([2.]), np.zeros(3)
        def finish_tick(self, dt, publish=True):
            finishes.append((dt, publish))
    def acquire(t, q, w):
        return (t, w[0]), None
    def set_commands(wheels, dipole):
        command[0] = wheels[0]
    def solve(start, end, state):
        intervals.append((start, end, command[0]))
        state = state.copy()
        state[4] += command[0]*(end-start)
        if overrun and len(intervals) == 3:
            clock[0] += .05
        return SimpleNamespace(success=True, t=[start, end], y=np.c_[state, state], message='ok')
    link = Link()
    endpoint = integrate_firmware_step(0., .1, np.array([1., 0, 0, 0, 0, 0, 0]),
        solve, link, pacer, acquire, set_commands)
    assert len(samples) == 9 and len(intervals) == 10
    np.testing.assert_allclose([s[1] for s in samples], np.arange(1, 10)*.01, atol=1e-15)
    assert all(b[0]-a[0] >= .01-1e-12 for a, b in zip(samples, samples[1:]))
    assert samples[0][2] == pytest.approx(.01)  # committed first interval
    assert intervals[0][2] == 1. and all(segment[2] == 2. for segment in intervals[1:])
    assert endpoint[4] == pytest.approx(.19)
    assert sum(dt for dt, _ in finishes) == pytest.approx(.1)
    assert sum(publish for _, publish in finishes) == 1
    assert (link.schedule_lag_s > .01) == overrun


def test_preparation_uses_idle_budget_without_sending_future_packets():
    from firmware_sitl_adapter import integrate_firmware_step
    clock = [0.]
    pacer = SimulationPacer(1., now=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0]+dt))
    samples, published = [], []
    class Link:
        schedule_lag_s = 0.
        def send_imu(self, gyro, mag): samples.append((clock[0], gyro))
        def poll_commands(self, dt): return np.zeros(4), np.zeros(3)
        def finish_tick(self, dt, publish=True): published.append(publish)
    def solve(start, end, state):
        clock[0] += .002  # work fits into each 10 ms interval
        return SimpleNamespace(success=True, t=[start,end], y=np.c_[state,state])
    state = np.r_[1.,np.zeros(6)]
    for tick in range(3):
        t = tick*.1
        clock[0] += .005  # outer environment preparation
        pacer.wait_firmware_sample(t,.01)
        samples.append((clock[0],t))  # caller's first capture
        state = integrate_firmware_step(t,.1,state,solve,Link(),pacer,
            lambda stamp,*a:(stamp,None),lambda *a:None,defer_endpoint_publish=True)
        assert clock[0] < t+.1
    assert not any(published)  # endpoint telemetry belongs to the caller's deadline
    assert all(wall >= stamp-1e-12 for wall,stamp in samples)
    np.testing.assert_allclose([wall for wall,_ in samples][1:],np.arange(.01,.3,.01),atol=1e-12)


def test_tracker_usage_follows_fresh_firmware_reference(firmware_plant, monkeypatch):
    from firmware_sitl_adapter import FirmwareLink
    link = FirmwareLink.__new__(FirmwareLink)
    link.link = firmware_plant
    link.received_at = link.event_at = link.stable_since = None
    link.schedule_lag_s = 0.
    monkeypatch.setattr(firmware_plant.time,'monotonic',lambda:10.)
    firmware_plant._latest_fuse_source[0] = 1
    firmware_plant._latest_fuse_received_at[0] = 9.9
    metadata = link.metadata(0.,{},np.zeros(3))
    assert metadata['star_tracker_used']
    assert metadata['att_est_source'] == 'Star tracker'
    firmware_plant._latest_fuse_received_at[0] = 7.
    metadata = link.metadata(0.,{},np.zeros(3))
    assert not metadata['star_tracker_used']
    assert metadata['att_est_source'] == 'Awaiting fresh firmware status'


@pytest.mark.parametrize('source,used', [(0,False),(1,False),(2,True),(3,True)])
def test_sun_usage_follows_firmware_not_python_estimator(firmware_plant, monkeypatch, source, used):
    from firmware_sitl_adapter import FirmwareLink
    link = FirmwareLink.__new__(FirmwareLink)
    link.link = firmware_plant
    link.received_at = link.event_at = link.stable_since = None
    link.schedule_lag_s = 0.
    monkeypatch.setattr(firmware_plant.time, 'monotonic', lambda: 10.)
    firmware_plant._latest_fuse_source[0] = source
    firmware_plant._latest_fuse_received_at[0] = 9.9
    assert link.metadata(0., {}, np.zeros(3))['att_est_sun_used'] is used
    firmware_plant._latest_fuse_received_at[0] = 7.
    assert not link.metadata(0., {}, np.zeros(3))['att_est_sun_used']


def test_failed_segment_does_not_send_future_samples():
    from firmware_sitl_adapter import integrate_firmware_step
    link = SimpleNamespace(schedule_lag_s=0., finish_tick=lambda *a, **k: pytest.fail('advanced failed interval'))
    pacer = SimpleNamespace(wait_firmware_sample=lambda *args: 0.)
    def failed(*args):
        return SimpleNamespace(success=False, t=[0.], message='failed')
    with pytest.raises(RuntimeError, match='failed'):
        integrate_firmware_step(0., .1, np.array([1., 0, 0, 0, 0, 0, 0]), failed,
            link, pacer, lambda *a: pytest.fail('sampled future'), lambda *a: None)


def test_schedule_rebase_does_not_hide_actual_speed_or_lag():
    clock = [0.]
    pacer = SimulationPacer(1., now=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0]+dt))
    clock[0] = .5
    assert pacer.wait_firmware_sample(.01, .01) == pytest.approx(.49)
    metrics = pacer.metrics(.01)
    assert metrics['simulation_speed_actual'] == pytest.approx(.02)
    assert metrics['simulation_lag_s'] == pytest.approx(.49)
    pacer.wait_firmware_sample(.02, .01)
    assert clock[0] == pytest.approx(.51)


def test_albedo_enabled_and_sun_settings_retained():
    import satellite_parameters as config
    from firmware_sitl_adapter import with_firmware_imu_rate
    # Configuration may intentionally select perfect/off. Check that SITL
    # preserves explicit enabled albedo rather than forcing a profile on users.
    enabled = replace(config.IMU_SIM, sun_array=replace(config.IMU_SIM.sun_array,
                      enable_albedo=True,enable_fine_albedo=True))
    assert with_firmware_imu_rate(enabled).sun_array is enabled.sun_array
    from simulate_sunsensor import simulate_fine_sensor
    cfg = config.IMU_SIM.sun_array
    for level, expected in [(0., 0), (.2, 2000)]:
        data = simulate_fine_sensor(np.array([0., 0., -1.]), 0., 298., cfg,
            0., np.random.default_rng(2), np.array([0., 0., 1.]), level)
        assert sum(data[k] for k in ['Q1', 'Q2', 'Q3', 'Q4']) == expected


def test_sun_reference_matches_orekit_and_spacecraft_line_of_sight():
    import engine.orekit_runtime
    from org.orekit.bodies import CelestialBodyFactory
    from org.orekit.frames import FramesFactory
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    from sun_vector_eci import sun_vector_eci
    from sun_pointing_rw_z import sun_pointing_rw_z_quaternion
    from attitude_frames import body_to_eci
    date = AbsoluteDate(2026, 10, 1, 15, 0, 0., TimeScalesFactory.getUTC())
    vector = CelestialBodyFactory.getSun().getPosition(date, FramesFactory.getEME2000())
    position = np.array([vector.getX(), vector.getY(), vector.getZ()])
    epoch = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    utc_offset_epoch = epoch.astimezone(timezone(timedelta(hours=5, minutes=30)))
    r = np.array([3e6, -4e6, 5e6])
    expected = position-r
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(sun_vector_eci(epoch, r), expected, atol=1e-15)
    np.testing.assert_allclose(sun_vector_eci(utc_offset_epoch, r), expected, atol=1e-15)
    q = sun_pointing_rw_z_quaternion(epoch, r)
    np.testing.assert_allclose(-body_to_eci(q)[:, 2], expected, atol=1e-15)


def test_true_anomaly_half_turn_reverses_initial_position():
    import engine_adcs_bridge as bridge
    import satellite_parameters as config
    with pytest.MonkeyPatch.context() as patch:
        provider = bridge.EngineOrbitProvider.__new__(bridge.EngineOrbitProvider)
        provider.altitude_m = config.ALTITUDE_M
        provider.inclination_deg = config.INCLINATION_DEG
        patch.setattr(config, 'ORBIT', replace(config.ORBIT, true_anomaly_deg=0., eccentricity=0.))
        first_r, first_v = provider._make_initial_pv()
        patch.setattr(config, 'ORBIT', replace(config.ORBIT, true_anomaly_deg=180.))
        second_r, second_v = provider._make_initial_pv()
    np.testing.assert_allclose(second_r, -first_r, atol=1e-8)
    np.testing.assert_allclose(second_v, -first_v, atol=1e-10)
