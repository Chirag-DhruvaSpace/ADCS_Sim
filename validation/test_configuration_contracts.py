from dataclasses import replace
import numpy as np
import pytest
import satellite_parameters as config


def test_initial_attitude_is_normalized_and_shared():
    attitude = replace(config.ATTITUDE, initial_quaternion_scalar_first=(2.,-2.,2.,-2.))
    np.testing.assert_array_equal(attitude.initial_quaternion_scalar_first, [.5,-.5,.5,-.5])
    for value in [(0.,0.,0.,0.), (np.nan,0.,0.,1.)]:
        with pytest.raises(ValueError):
            replace(attitude, initial_quaternion_scalar_first=value)
    import satellite_rotational_dynamics_var_mag_field as dynamics
    np.testing.assert_array_equal(dynamics.y0[:4], config.ATTITUDE.initial_quaternion_scalar_first)
    from engine_adcs_bridge import EngineOrbitProvider
    provider = EngineOrbitProvider(config.EPOCH_UTC)
    np.testing.assert_array_equal(provider._attitude_q, dynamics.y0[:4])


def test_unsupported_sensor_rates_are_explicit(monkeypatch):
    from engine.simulation.sensor_schedule import validate_sensor_schedule
    imu = replace(config.IMU_SIM, enabled=True, enable_gyro=True, gyros=(), gyro_update_rate_hz=100.)
    with pytest.raises(ValueError, match='Gyroscope'):
        validate_sensor_schedule(.1, imu, config.GPS_SIM)
    validate_sensor_schedule(.1, imu, config.GPS_SIM, firmware=True)
    with pytest.raises(ValueError, match='Control step'):
        validate_sensor_schedule(0., imu, config.GPS_SIM)
    with pytest.raises(ValueError, match='GPS'):
        validate_sensor_schedule(.1, replace(imu,enabled=False), replace(config.GPS_SIM,enabled=True,update_rate_hz=20.))


def test_environment_selection_is_explicit(monkeypatch):
    import engine.orekit_runtime as runtime
    assert runtime.LOADED_DATA_PATH == config.MODEL_DATA.orekit_data_path
    with pytest.raises(RuntimeError, match='restart'):
        runtime.load_orekit_data(config.MODEL_DATA.orekit_data_path.parent)
    with pytest.raises(ValueError):
        replace(config.MODEL_DATA, magnetic_model='auto')
    from engine.physics.magnetic_field import OrekitIGRF
    model = OrekitIGRF(None,None,None,model_name='WMM')
    assert model.model_name == 'WMM'


def test_accelerator_load_failure_cannot_block_surface_model(monkeypatch):
    import engine.orekit_runtime
    import engine.physics.facet_visibility as accelerator
    from spacecraft_surface_physics import SurfaceForceModel
    def unavailable():
        raise TypeError('Class leap.physics.FacetVisibility is not found')
    monkeypatch.setattr(accelerator, '_visibility_class', unavailable)
    with pytest.warns(RuntimeWarning, match='using NumPy'):
        model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
    assert model._native_visibility is None
    result = model.evaluate([1.,0.,0.,0.], np.array([7e6,0.,0.]),
                           np.array([0.,7500.,0.]), np.array([1.5e11,0.,0.]),
                           1., 1e-12, np.zeros(3))
    assert np.all(np.isfinite(result.srp_torque_body_nm))


def test_java_visibility_is_exact_with_numpy_fallback():
    import engine.orekit_runtime
    from engine.physics.facet_visibility import make_visibility
    from spacecraft_surface_physics import SurfaceForceModel
    model = SurfaceForceModel(config.SPACECRAFT,config.GEOMETRY)
    native = make_visibility(model.position,model._blocker_lo,model._blocker_hi)
    assert native is not None
    rng = np.random.default_rng(91)
    model._native_visibility = None
    for direction in [np.zeros(3), *np.eye(3), *-np.eye(3), *rng.normal(size=(70,3))]:
        for active in [None, rng.random(len(model.position)) > .4]:
            np.testing.assert_array_equal(native(direction,active), model.visibility(direction,active))
