"""Physical invariants for CAD configuration selection and force/moment coupling."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import satellite_parameters as config
from spacecraft_surface_physics import SurfaceForceModel, AU_M, PRESSURE_AT_AU_PA, body_to_eci


def plate(absorption=1., diffuse=0., specular=0., com=(0,0,0)):
    face = config.SurfaceParameters('plate', 2., (1,0,0), (0,1,0), absorption,diffuse,specular)
    geometry = config.GeometryParameters((face,),com)
    spacecraft = SimpleNamespace(mass_kg=10.,drag_coefficient=2.)
    return SurfaceForceModel(spacecraft,geometry)


def evaluate(model, sun=(AU_M,0,0), illumination=1., velocity=(100,0,0), q=(1,0,0,0)):
    return model.evaluate(q,np.zeros(3),np.array(velocity),np.array(sun),illumination,1e-9,np.zeros(3))


@pytest.mark.parametrize('reflection,multiplier',[(0.,1.),(1.,2.)])
def test_flat_plate_photon_momentum_and_lever_arm(reflection,multiplier):
    r = evaluate(plate(absorption=1-reflection,specular=reflection))
    expected = -2*PRESSURE_AT_AU_PA*multiplier
    np.testing.assert_allclose(r.srp_force_eci_n,[expected,0,0],atol=1e-20)
    np.testing.assert_allclose(r.srp_torque_body_nm,[0,0,-expected],atol=1e-20)
    # Cd=2, area=2, speed=100: force opposes atmospheric relative velocity.
    np.testing.assert_allclose(r.drag_force_eci_n,[-2e-5,0,0],atol=1e-20)
    np.testing.assert_allclose(r.drag_torque_body_nm,[0,0,2e-5],atol=1e-20)


def test_eclipse_penumbra_distance_and_back_face():
    model = plate()
    full = evaluate(model)
    dark = evaluate(model,illumination=0)
    np.testing.assert_array_equal(dark.srp_force_eci_n,0)
    np.testing.assert_array_equal(dark.srp_torque_body_nm,0)
    np.testing.assert_allclose(evaluate(model,illumination=.3).srp_torque_body_nm,full.srp_torque_body_nm*.3)
    np.testing.assert_allclose(evaluate(model,sun=(2*AU_M,0,0)).srp_force_eci_n,full.srp_force_eci_n/4)
    np.testing.assert_array_equal(evaluate(model,sun=(-AU_M,0,0)).srp_force_eci_n,0)


def test_com_shift_changes_moment_but_not_force():
    first = evaluate(plate())
    shifted = evaluate(plate(com=(0,.5,0)))
    np.testing.assert_allclose(shifted.srp_force_eci_n,first.srp_force_eci_n)
    np.testing.assert_allclose(shifted.srp_torque_body_nm,first.srp_torque_body_nm/2)


def test_rotation_preserves_body_physics():
    model = plate()
    q = (np.sqrt(.5),0,0,np.sqrt(.5))
    rotation = body_to_eci(q)
    baseline = evaluate(model)
    rotated = evaluate(model,sun=rotation@np.array([AU_M,0,0]),velocity=rotation@np.array([100,0,0]),q=q)
    np.testing.assert_allclose(rotated.srp_force_eci_n,rotation@baseline.srp_force_eci_n,atol=1e-18)
    np.testing.assert_allclose(rotated.srp_torque_body_nm,baseline.srp_torque_body_nm,atol=1e-18)


@pytest.mark.parametrize('deployed,mass,com',[(True,27.29,(-.01855,-.01489,-.16821)),(False,30.40,(-.01682,-.01421,-.12967))])
def test_selected_report_and_geometry(deployed,mass,com):
    spacecraft,_,attitude,_,_,_,geometry,_,_,_,imu,_ = config._load_configuration(panels_deployed=deployed, use_advanced_satellite_model=True)
    assert spacecraft.mass_kg == mass
    assert spacecraft.panels_deployed is deployed
    assert spacecraft.configuration == ('deployed' if deployed else 'stowed')
    np.testing.assert_allclose(geometry.center_of_mass_body_m,com)
    assert not attitude.inertia_is_principal_axes
    assert np.all(np.linalg.eigvalsh(spacecraft.inertia_matrix)>0)
    expected = [.89085808,1.82933196,1.92247211] if deployed else [.96448009,1.08726972,1.22225207]
    np.testing.assert_allclose(np.linalg.eigvalsh(spacecraft.inertia_matrix),expected,atol=2e-8)
    assert np.count_nonzero(spacecraft.inertia_matrix-np.diag(np.diag(spacecraft.inertia_matrix)))==6
    assert len(imu.sun_array.cells)==6
    assert len(imu.sun_array.blockers)>1
    assert imu.gyro_position_body_m[2]<-.3


def test_deployment_changes_incidence_and_shadow_geometry():
    results=[]
    for mode in (True,False):
        cfg=config._load_configuration(panels_deployed=mode, use_advanced_satellite_model=True)
        model=SurfaceForceModel(cfg[0],cfg[6])
        results.append(evaluate(model,sun=(0,0,-AU_M),velocity=(0,0,-100)))
    assert np.linalg.norm(results[0].srp_force_eci_n)>np.linalg.norm(results[1].srp_force_eci_n)
    assert not np.allclose(results[0].srp_torque_body_nm,results[1].srp_torque_body_nm,atol=1e-12)


def test_basic_model_never_requires_advanced_file(tmp_path):
    from pathlib import Path
    source = tmp_path / 'satellite_parameters.yaml'
    source.write_text(Path(config.__file__).with_suffix('.yaml').read_text(encoding='utf-8'), encoding='utf-8')
    cfg = config._load_configuration(source, use_advanced_satellite_model=False)
    assert cfg[0].configuration == 'legacy'
    assert cfg[0].mass_kg == 6.0
    np.testing.assert_allclose(cfg[0].inertia_matrix, np.diag([1.465,1.176,1.244]))
    assert cfg[0].model_url == '/assets/models/P-30XL.glb'
    assert cfg[2].inertia_is_principal_axes
    assert len(cfg[6].surfaces) == 6
    assert cfg[6].center_of_mass_body_m == (0.,0.,0.)
    assert cfg[10].gyro_position_body_m == (0.,0.,0.)


def test_advanced_flag_and_mode_are_independent(tmp_path):
    from pathlib import Path
    import yaml
    basic = yaml.safe_load(Path(config.__file__).with_suffix('.yaml').read_text(encoding='utf-8'))
    advanced = yaml.safe_load(Path(config.__file__).with_name('advanced_satellite_parameters.yaml').read_text(encoding='utf-8'))
    basic['use_advanced_satellite_model'] = True
    basic['spacecraft']['panels_deployed'] = True
    advanced['panels_deployed'] = False
    source = tmp_path / 'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(basic), encoding='utf-8')
    (tmp_path/'advanced_satellite_parameters.yaml').write_text(yaml.safe_dump(advanced), encoding='utf-8')
    cfg = config._load_configuration(source)
    assert cfg[0].configuration == 'stowed'
    assert cfg[0].mass_kg == 30.4
    assert cfg[10].sun_array.blockers == cfg[6].blockers


def test_wheel_momentum_redistribution_preserves_body_torque(monkeypatch):
    import torque_distribution as allocator
    # A nonzero stored null momentum must be redistributed without producing
    # a spurious spacecraft torque for the currently selected CAD wheel axes.
    monkeypatch.setattr(allocator, '_wheel_momentum', [allocator.NULL_VEC * .01])
    command = np.array([1e-4, -2e-4, 3e-4])
    wheel_torque = allocator.reaction_wheel_torque_distribution(*command)
    np.testing.assert_allclose(allocator.A @ wheel_torque, command, atol=1e-15)
