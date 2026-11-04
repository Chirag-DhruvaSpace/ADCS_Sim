"""CAD apertures, real folded-panel shadows and firmware solver accuracy."""
from dataclasses import replace
from pathlib import Path
import hashlib

import numpy as np
import pytest
from scipy.integrate import solve_ivp

import satellite_parameters as config
from simulate_sunsensor import SimulatedSunSensorArray, _ray_hits_box
from engine.physics.mesh_shadow import load_model_occluder, model_cache_path, ray_hits_triangles


def perfect_array(deployed):
    cfg = config._load_configuration(use_advanced_satellite_model=True, panels_deployed=deployed)[10].sun_array
    return replace(cfg, enable_alignment_error=False, enable_bias_drift=False,
        enable_scale_nonlinearity=False, enable_white_noise=False, enable_albedo=False,
        enable_self_shadowing=True,
        dropout_probability=0., latency_mean_s=0., latency_sigma_s=0., latency_min_s=0., latency_max_s=0.)


@pytest.mark.parametrize('deployed', [False, True])
def test_minus_z_sees_sun_through_actual_cad_opening(deployed):
    cfg = perfect_array(deployed)
    sensor = SimulatedSunSensorArray(cfg, record_history=False)
    raw = sensor.get_raw_data(0., [1., 0., 0., 0.], [0., 0., -1.], 1., None)
    assert sum(raw.sensors[0].data[k] for k in ['Q1', 'Q2', 'Q3', 'Q4']) == 10000
    assert not sensor._last_cell_diagnostics['-Z'].shadowed
    blocker = next(b for b in cfg.blockers if b.sensor_model_node)
    # Demonstrates the false positive that motivated the CAD narrow phase.
    assert _ray_hits_box(cfg.cells[0].position_body_m, [0., 0., -1.], blocker.center_body_m, blocker.half_extents_m)


@pytest.mark.parametrize('deployed', [False, True])
@pytest.mark.parametrize('index', range(6))
def test_each_head_on_boresight_respects_real_panel_deployment(deployed, index):
    cfg = perfect_array(deployed)
    cell = cfg.cells[index]
    direction = np.asarray(cell.normal_body, dtype=float); direction /= np.linalg.norm(direction)
    sensor = SimulatedSunSensorArray(cfg, record_history=False)
    raw = sensor.get_raw_data(0., [1., 0., 0., 0.], direction, 1., None)
    covered = not deployed and cell.name in ('+Y', '-Y')
    assert sensor._last_cell_diagnostics[cell.name].shadowed == covered
    assert sum(raw.sensors[index].data[k] for k in ['Q1', 'Q2', 'Q3', 'Q4']) == (0 if covered else 10000)


@pytest.mark.parametrize('mode', ['deployed', 'stowed'])
def test_occluder_asset_matches_cad_and_tree_matches_triangle_reference(mode):
    root = Path(__file__).resolve().parents[1]
    blocker = next(b for b in perfect_array(mode == 'deployed').blockers if b.sensor_model_node)
    mesh = load_model_occluder(blocker.sensor_model_file, blocker.sensor_model_node, blocker.sensor_model_scale_to_m)
    asset, _ = model_cache_path(blocker.sensor_model_file, blocker.sensor_model_node, blocker.sensor_model_scale_to_m)
    with np.load(asset, allow_pickle=False) as data:
        assert str(data['source_sha256']) == hashlib.sha256((root/f'frontend/assets/models/P-30XL-{mode}.glb').read_bytes()).hexdigest()
    rng = np.random.default_rng(17)
    origin = np.array([-.1325, .106, -.34176])
    for direction in [np.array([0., 0., -1.]), *rng.normal(size=(8, 3))]:
        direction /= np.linalg.norm(direction)
        assert mesh.intersects(origin, direction) == ray_hits_triangles(origin, direction, mesh.vertices, mesh.triangles)
    # A ray aimed at real panel material must still be blocked.
    triangle = mesh.vertices[mesh.triangles[1000]]
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    normal /= np.linalg.norm(normal)
    assert mesh.intersects(triangle.mean(axis=0)+normal*.01, -normal)


def test_firmware_rk23_matches_high_accuracy_reference(monkeypatch):
    import satellite_rotational_dynamics_var_mag_field as dynamics
    import control_states as cs
    from spacecraft_surface_physics import SurfaceForceModel, AU_M
    monkeypatch.setitem(cs.mode, 'value', 'FIRMWARE_SITL')
    monkeypatch.setattr(dynamics, '_firmware_wheel_axes', lambda: np.array([[.8, 0., -.8, 0.], [0., -.8, 0., .8], [-.6, -.6, -.6, -.6]]))
    monkeypatch.setattr(dynamics, '_firmware_wheels', np.array([.004, -.002, .001, -.004]))
    monkeypatch.setattr(dynamics, '_firmware_dipole', np.array([2., -2., .5]))
    model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
    r, v, sun, air = np.array([7e6, 0., 0.]), np.array([0., 7500., 0.]), np.array([AU_M, .3*AU_M, .2*AU_M]), np.array([0., 450., 0.])
    field = np.array([1e-5, -2e-5, 3e-5])
    def rhs(t, y):
        facets = model.evaluate(y[:4], r, v, sun, 1., 1e-12, air)
        return dynamics.rotational_equations_of_motion(t, y, field, r, v,
            external_torque_body=facets.srp_torque_body_nm, aerodynamic_torque_body=facets.drag_torque_body_nm)
    rng = np.random.default_rng(42)
    for _ in range(8):
        q = rng.normal(size=4); q /= np.linalg.norm(q)
        initial = np.r_[q, rng.uniform(-2., 2., 3)]
        actual = initial.copy()
        for index in range(10):
            start, end = index*.01, (index+1)*.01
            result = solve_ivp(rhs, [start, end], actual, method='RK23', first_step=end-start,
                rtol=config.SIMULATION.attitude_integrator_rel_tolerance,
                atol=config.SIMULATION.attitude_integrator_abs_tolerance)
            assert result.success
            actual = result.y[:, -1]; actual[:4] /= np.linalg.norm(actual[:4])
        reference = solve_ivp(rhs, [0., .1], initial, method='DOP853', rtol=1e-12, atol=1e-14).y[:, -1]
        reference[:4] /= np.linalg.norm(reference[:4])
        angle = 4*np.arcsin(min(1., np.linalg.norm(actual[:4]-reference[:4])/2))
        assert np.degrees(angle) < .001
        np.testing.assert_allclose(actual[4:], reference[4:], rtol=1e-6, atol=1e-8)


def test_scalar_cross_product_matches_numpy_exactly():
    from attitude_frames import cross3
    rng = np.random.default_rng(39)
    for a, b in rng.normal(size=(100, 2, 3)):
        np.testing.assert_array_equal(cross3(a, b), np.cross(a, b))
