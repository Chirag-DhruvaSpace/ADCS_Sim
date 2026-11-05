"""Independent coil/torque invariants and YAML/CAD/firmware integration."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

import satellite_parameters as config
from simulate_magnetorquers import MagnetorquerParameters as Rod
from simulate_magnetorquers import MagnetorquerArrayParameters as Array
from simulate_magnetorquers import SimulatedMagnetorquers, load_parameters
from validation.test_audit_physics import firmware_plant


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('advanced,deployed', [(False, True), (True, True), (True, False)])
def test_selected_rods_match_actual_cad_placements(advanced, deployed):
    craft = config._load_configuration(use_advanced_satellite_model=advanced, panels_deployed=deployed)[0]
    mode = 'deployed' if deployed else 'stowed'
    inventory = json.loads((ROOT/f'frontend/assets/models/P-30XL-{mode}-inventory.json').read_text())
    parts = [p for p in inventory['parts'] if p['name'] == 'SPPE113_003']
    assert len(craft.magnetorquers.units) == len(parts) == 3
    for rod in craft.magnetorquers.units:
        axis = int(np.argmax(np.abs(rod.axis_body)))
        part = next(p for p in parts if int(np.argmax(np.diff(p['bounds_body_m'], axis=0)[0])) == axis)
        np.testing.assert_allclose(rod.position_body_m, part['center_body_m'], atol=1e-12)
        if advanced:
            assert rod.cad_node == part['node']


def test_position_changes_markers_but_uniform_field_torque_has_no_moment_arm():
    rod = Rod('coil', (0, 0, 1), max_current_A=10., dipole_per_amp_Am2_per_A=2., resistance_ohm=4.)
    field = [2e-5, 0, 0]
    plant = SimulatedMagnetorquers(Array(units=(rod,)))
    state = plant.apply_currents([.5], field)
    np.testing.assert_allclose(state.body_dipole_Am2, [0, 0, 1])
    np.testing.assert_allclose(state.torque_body_Nm, [0, 2e-5, 0])
    assert state.power_W == pytest.approx(1.)
    moved = SimulatedMagnetorquers(Array(units=(replace(rod, position_body_m=(10, 5, -3)),)))
    moved_state = moved.apply_currents([.5], field)
    np.testing.assert_array_equal(moved_state.torque_body_Nm, state.torque_body_Nm)
    assert moved.telemetry(moved_state)[0]['position'] == [10, 5, -3]
    assert moved.telemetry(moved_state)[0]['active']


def test_redundant_rotated_and_disabled_coils_distribute_reachable_dipole():
    rods = (Rod('x1', (1, 0, 0), max_current_A=10., max_dipole_Am2=.2),
            Rod('x2', (1, 0, 0), max_current_A=10.),
            Rod('diagonal', (0, 1, 1), max_current_A=10.),
            Rod('disabled', (0, 0, 1), enabled=False))
    plant = SimulatedMagnetorquers(Array(units=rods))
    state = plant.apply_dipole([1.5, .4, .4], [0, 0, 3e-5])
    np.testing.assert_allclose(state.body_dipole_Am2, [1.5, .4, .4], atol=1e-12)
    assert state.dipoles_Am2[0] == pytest.approx(.2)
    assert state.dipoles_Am2[-1] == 0.
    np.testing.assert_allclose(state.torque_body_Nm, [1.2e-5, -4.5e-5, 0], atol=1e-16)
    off = SimulatedMagnetorquers(replace(plant.cfg, enabled=False))
    np.testing.assert_array_equal(off.apply_dipole([1, 2, 3]).body_dipole_Am2, 0)
    np.testing.assert_array_equal(off.apply_currents([1, 2, 3, 4]).currents_A, 0)


def test_current_limit_and_quantization_never_exceed_coil_authority():
    rod = Rod('limited', (1, 0, 0), dipole_per_amp_Am2_per_A=1., max_current_A=.26,
              max_dipole_Am2=2., dipole_step_Am2=.1)
    plant = SimulatedMagnetorquers(Array(units=(rod,)))
    for sign in (-1, 1):
        state = plant.apply_currents([sign * 100])
        assert state.dipoles_Am2[0] == pytest.approx(sign * .2)
        assert abs(state.currents_A[0]) <= rod.max_current_A
    # Continuous legacy command path remains unquantized by default.
    assert plant.apply_dipole([.123, 0, 0]).dipoles_Am2[0] == pytest.approx(.123)


def test_yaml_only_can_replace_rods_and_add_magnetometers(tmp_path):
    data = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    data['use_advanced_satellite_model'] = False
    data['sensor_profiles']['magnetometer'] = 'perfect'
    data['magnetorquers']['units'] = [dict(name='payload-coil', axis_body=[0, 1, 0],
                                          position_body_m=[.4, -.2, .1], max_current_A=.2,
                                          dipole_per_amp_Am2_per_A=3.)]
    data['magnetometer'].update(mount_quaternion=[1, 0, 0, 0],
        gradient_body_t_per_m=[[1e-6, 0, 0], [0, 0, 0], [0, 0, 0]],
        units=[dict(name='Mag-A', position_body_m=[1, 0, 0], seed=1, fusion_weight=1.),
               dict(name='Mag-B', position_body_m=[-1, 0, 0], seed=2, fusion_weight=3.)])
    source = tmp_path/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(data), encoding='utf-8')
    loaded = config._load_configuration(source)
    craft, imu = loaded[0], loaded[10]
    assert len(craft.magnetorquers.units) == 1
    rod = craft.magnetorquers.units[0]
    assert rod.name == 'payload-coil' and rod.max_current_A == .2
    from simulate_magnetometer import SimulatedMagnetometer
    from compute_simulated_attitude import ImuNav
    readings = [(u, SimulatedMagnetometer(imu.unit_config('mag', u, i)).get_raw_data(0, [1, 0, 0, 0], [30e-6, 0, 0]))
                for i, u in enumerate(imu.magnetometers)]
    assert readings[0][1].data['X_axis'] > readings[1][1].data['X_axis']
    nav = ImuNav(estimator_enabled=False)
    nav.process_raw_data(0, None, readings, None, imu)
    # Raw hardware resolution is 150 nT; weighted local fields remain distinct.
    expected = np.average([r.data['X_axis'] * 150e-9 for _, r in readings], weights=[1, 3])
    assert nav.B_body()[0] == pytest.approx(expected)


def test_advanced_magnetometer_mount_list_can_override_basic(tmp_path):
    basic = yaml.safe_load((ROOT/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    advanced = yaml.safe_load((ROOT/'advanced_satellite_parameters.yaml').read_text(encoding='utf-8'))
    basic['use_advanced_satellite_model'] = True
    for mode in advanced['configurations'].values():
        mode['magnetometer'] = dict(units=[dict(name='CAD-Mag', position_body_m=[.2, .1, -.3])])
    (tmp_path/'advanced_satellite_parameters.yaml').write_text(yaml.safe_dump(advanced), encoding='utf-8')
    source = tmp_path/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(basic), encoding='utf-8')
    # Supplied GLB paths are relative to the real repo; resolve only those paths.
    for mode in advanced['configurations'].values():
        if mode['spacecraft'].get('model_file'):
            mode['spacecraft']['model_file'] = str(ROOT/mode['spacecraft']['model_file'])
    (tmp_path/'advanced_satellite_parameters.yaml').write_text(yaml.safe_dump(advanced), encoding='utf-8')
    imu = config._load_configuration(source)[10]
    assert len(imu.magnetometers) == 1
    assert imu.magnetometers[0].name == 'CAD-Mag'


def test_firmware_extra_rod_currents_reach_rotated_plant_and_expire(firmware_plant, monkeypatch):
    link = firmware_plant
    rods = tuple(Rod(f'coil-{i}', tuple(axis), max_current_A=1., dipole_per_amp_Am2_per_A=2.)
                 for i, axis in enumerate([[0, 1, 0], [-1, 0, 0], [0, 0, 1], [1, 0, 0]]))
    monkeypatch.setattr(config, 'SPACECRAFT', replace(config.SPACECRAFT, magnetorquers=Array(units=rods)))
    from firmware_sitl_adapter import _valid_actuator_command
    assert _valid_actuator_command((3., 2., 100.))
    assert not _valid_actuator_command((4., 2., 100.))
    assert not _valid_actuator_command((3.5, 2., 100.))
    monkeypatch.setattr(link.time, 'monotonic', lambda: 10.)
    monkeypatch.setattr(link, '_mtr_received_at', [9.9, 9.9, 0., 9.9])
    monkeypatch.setattr(link, '_latest_mtr_current_mA', [100., 200., 500., -300.])
    _, moment = link.apply_actuator_limits(.01)
    np.testing.assert_allclose(moment, [-1., .2, 0.], atol=1e-15)
    state = link.get_magnetorquer_state()
    np.testing.assert_allclose(state.currents_A, [.1, .2, 0, -.3], atol=1e-15)
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import control_states as cs
    import store
    monkeypatch.setitem(cs.mode, 'value', 'FIRMWARE_SITL')
    monkeypatch.setattr(dynamics.cd, 'DISTURBANCES_ENABLED', False)
    monkeypatch.setattr(dynamics, '_firmware_wheel_axes', lambda: np.zeros((3, 4)))
    monkeypatch.setattr(dynamics, '_firmware_magnetorquer_state', state)
    monkeypatch.setattr(dynamics, '_firmware_dipole', moment)
    field = np.array([0, 0, 2e-5])
    derivative = dynamics.rotational_equations_of_motion(0, [1, 0, 0, 0, 0, 0, 0], field)
    np.testing.assert_allclose(dynamics.I @ derivative[4:], [4e-6, 2e-5, 0], atol=1e-16)
    np.testing.assert_allclose([u['current_A'] for u in store.mtr_units], state.currents_A, atol=1e-15)
    monkeypatch.setattr(link.time, 'monotonic', lambda: 20.)
    _, expired = link.apply_actuator_limits(.01)
    np.testing.assert_array_equal(expired, 0.)


@pytest.mark.parametrize('advanced', [False, True])
@pytest.mark.parametrize('mode', ['SUN_POINTING', 'RW', 'CUSTOM', 'NADIR', 'MOON',
    'SUN_SWEEP', 'SUN_POINTING_RW', 'NOMINAL_IN_ORBIT', 'KINEMATIC_ROBUSTNESS', 'FIRMWARE_SITL'])
def test_every_pointing_mode_uses_consistent_plant_and_telemetry(advanced, mode, monkeypatch):
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import control_states as cs
    import torque_distribution as wheels
    import store
    craft = config._load_configuration(use_advanced_satellite_model=advanced)[0]
    monkeypatch.setattr(config, 'SPACECRAFT', craft)
    monkeypatch.setattr(dynamics, 'I', craft.inertia_matrix)
    monkeypatch.setattr(dynamics, 'I_inv', np.linalg.inv(craft.inertia_matrix))
    monkeypatch.setitem(cs.mode, 'value', mode)
    monkeypatch.setattr(dynamics, 'detumbling_complete', True)
    monkeypatch.setattr(dynamics, '_imu_adcs_enabled', [False])
    monkeypatch.setattr(dynamics, '_imu_adcs_use_attitude', [False])
    monkeypatch.setattr(dynamics, '_firmware_magnetorquer_state', None)
    monkeypatch.setattr(dynamics, '_firmware_dipole', np.array([.1, -.2, .3]))
    monkeypatch.setattr(dynamics, '_firmware_wheels', np.zeros(4))
    monkeypatch.setattr(dynamics, '_firmware_wheel_axes', lambda: wheels.A)
    monkeypatch.setattr(dynamics.cd, 'DISTURBANCES_ENABLED', False)
    field = np.array([2e-5, -1e-5, 3e-5])
    derivative = dynamics.rotational_equations_of_motion(0., [1, 0, 0, 0, 0, 0, 0], field,
                                                        [7e6, 0, 0], [0, 7500, 0])
    assert np.all(np.isfinite(derivative))
    np.testing.assert_allclose(craft.inertia_matrix @ derivative[4:],
                              wheels.A @ store.rw_torques + store.mtr_torques, atol=1e-15)
    np.testing.assert_allclose(store.mtr_torques, np.cross(store.mtr_dipole, field), atol=1e-16)
    assert len(store.mtr_units) == 3
    if mode not in ('SUN_POINTING', 'FIRMWARE_SITL'):
        np.testing.assert_array_equal(store.mtr_dipole, 0.)


@pytest.mark.parametrize('key,value', [('axis_body', [0, 0, 0]), ('max_current_A', -1),
                                      ('dipole_per_amp_Am2_per_A', 0), ('position_body_m', [0, np.nan, 0])])
def test_invalid_coil_definitions_fail_at_configuration_load(key, value):
    record = dict(name='bad', axis_body=[1, 0, 0])
    record[key] = value
    with pytest.raises(ValueError):
        load_parameters(dict(units=[record]))
