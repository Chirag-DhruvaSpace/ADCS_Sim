"""Extended Earth irradiance must be resolved through the fine aperture."""
import numpy as np
from simulate_sunsensor import (earth_albedo_rays, fine_albedo_quadrants,
    quadrant_signal, sensor_to_body_matrix, simulate_fine_sensor)
import satellite_parameters as config


def test_extended_disk_matches_independent_sum_of_optical_rays():
    cfg = config.IMU_SIM.sun_array
    rays, weights = earth_albedo_rays(np.array([6871000.,0.,0.]),
                                    np.array([1.,0.,0.]), .15, patches=512)
    for normal in [-np.eye(3)[0],np.eye(3)[2],np.array([-1.,1.,.5])]:
        axes = sensor_to_body_matrix(normal)
        expected = np.zeros(4)
        for ray, weight in zip(rays, weights):
            local = axes.T @ ray
            expected += quadrant_signal(local,weight*max(0.,local[2]),cfg)
        np.testing.assert_allclose(fine_albedo_quadrants(rays,weights,axes,cfg),expected,atol=1e-12)


def test_diffuse_earth_does_not_become_a_concentrated_coarse_cell_spot():
    cfg = config.IMU_SIM.sun_array
    rays, weights = earth_albedo_rays(np.array([6871000.,0.,0.]),np.array([1.,0.,0.]),.15)
    axes = sensor_to_body_matrix([-1.,0.,0.])
    fine = fine_albedo_quadrants(rays,weights,axes,cfg)
    coarse_total = sum(weights*np.maximum(0.,rays @ [-1.,0.,0.]))*cfg.fine_total_signal_counts
    assert 0 < sum(fine) < .6*coarse_total
    output = simulate_fine_sensor([0.,0.,-1.],0.,298.,cfg,0.,np.random.default_rng(4),albedo_quadrants=fine)
    assert sum(output[k] for k in ['Q1','Q2','Q3','Q4']) == sum(np.rint(fine))
    np.testing.assert_array_equal(fine_albedo_quadrants(rays,weights,sensor_to_body_matrix([1.,0.,0.]),cfg),np.zeros(4))


def test_display_noise_floor_does_not_modify_hardware_packets():
    from dataclasses import replace
    from types import SimpleNamespace
    from simulate_sunsensor import SimulatedSunSensorArray
    import sensor_link
    cfg = config.IMU_SIM.sun_array
    cells = tuple(replace(cell,white_noise_sigma=.003) for cell in cfg.cells)
    sampler = SimulatedSunSensorArray(replace(cfg,cells=cells,enabled=True,enable_white_noise=True))
    raw = sampler.get_raw_data(0.,[1.,0.,0.,0.],[1.,0.,0.],0.)
    packets = []
    socket = SimpleNamespace(sendto=lambda packet,address:packets.append(packet))
    heads = sensor_link.send_fss(socket,raw,cells,white_noise_enabled=True)
    assert all(head['display_noise_floor_counts'] == 39 for head in heads)
    reference = packets.copy(); packets.clear()
    heads = sensor_link.send_fss(socket,raw,cells,white_noise_enabled=False)
    assert all(head['display_noise_floor_counts'] == 0 for head in heads)
    assert packets == reference


def test_perfect_profile_dark_heads_have_zero_counts():
    from simulate_sunsensor import SimulatedSunSensorArray
    cfg = config._apply_sensor_profile(config.IMU_SIM.sun_array,'perfect')
    sensor = SimulatedSunSensorArray(cfg)
    receipt = sensor.get_raw_data(0.,[1.,0.,0.,0.],[-1.,0.,0.],1.,[-6871000.,0.,0.])
    sums = {head.name:sum(head.data[k] for k in ['Q1','Q2','Q3','Q4']) for head in receipt.sensors}
    assert sums['-X'] == cfg.fine_total_signal_counts
    assert all(value == 0 for name,value in sums.items() if name != '-X')


def test_perfect_sun_receipts_remain_current_on_accumulated_clock():
    from simulate_sunsensor import SimulatedSunSensorArray
    cfg = config._apply_sensor_profile(config.IMU_SIM.sun_array, 'perfect')
    sensor = SimulatedSunSensorArray(cfg, record_history=False)
    t = 0.
    for _ in range(1500):
        receipt = sensor.get_raw_data(t, [1.,0.,0.,0.], [-1.,0.,0.], 1.)
        assert receipt is not None and receipt.valid
        assert 0 <= t - receipt.t_meas_s <= config.IMU_SIM.fusion_max_age_s
        assert receipt.t_meas_s <= receipt.t_arrival_s <= t
        lit = next(head for head in receipt.sensors if head.name == '-X')
        assert sum(lit.data[key] for key in ('Q1','Q2','Q3','Q4')) > 400
        t += .1
