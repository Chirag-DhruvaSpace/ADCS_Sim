"""Local fixture server for browser regression checks; no flight commands."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from imu_mount_settings import get_mounts
import numpy as np
from engine.astrodynamics.orbit_display import osculating_orbit
from engine.astrodynamics.constants import EARTH_MU
from satellite_parameters import SunSensorArrayParameters
from simulatesunsensor import SimulatedSunSensorArray

m = SimulatedSunSensorArray(SunSensorArrayParameters.perfect()).update(0, [1,0,0,0], [1,1,1], 1)
app.latest_telemetry = dict(timestamp='2026-10-01T15:00:00+00:00', latitude_deg=0,
    longitude_deg=0, altitude_m=500000, yaw_deg=0, pitch_deg=0, roll_deg=0,
    body_rate_x=0, body_rate_y=0, body_rate_z=0, alpha_x=0, alpha_y=0, alpha_z=0,
    quat_w=1, quat_x=0, quat_y=0, quat_z=0, imu_mounts=get_mounts(),
    sun_arr_cells=[dict(name=c.name, output_pct=c.output_pct, adc_counts=c.adc_counts,
        angle_deg=c.angle_deg, used=c.used, in_fov=c.in_fov, shadowed=c.shadowed,
        saturated=c.saturated, eclipse_factor=1, albedo_pct=0) for c in m.cells],
    sun_arr_valid=True, sun_arr_cells_used=3, sun_arr_cells_total=6,
    sun_arr_eclipse_factor=1, sun_arr_recon_valid=True, sun_arr_recon_x=.577,
    sun_arr_recon_y=.577, sun_arr_recon_z=.577, sun_arr_error_deg=0,
    imu_gyro_valid=True, imu_mag_valid=True,
    orbit_path_ecef_m=osculating_orbit([6871000,0,0],[0,np.sqrt(EARTH_MU/6871000),0]).tolist())
from simulateimu import SimulatedIMU
from satellite_parameters import ImuSimParameters
from imu_navigation import ImuNav
nav = ImuNav(sun_config=SunSensorArrayParameters.perfect())
nav.update(0, *SimulatedIMU(ImuSimParameters.perfect()).update(0, [1,0,0,0], [0,0,0], [2e-5,0,0], [1,1,1]))
app.latest_telemetry.update(nav.telemetry())
app.latest_telemetry.update(sun_arr_truth_x=.577, sun_arr_truth_y=.577, sun_arr_truth_z=.577,
    sun_arr_method='least_squares', att_est_quat_w=1, att_est_quat_x=0,
    att_est_quat_y=0, att_est_quat_z=0, att_est_error_deg=0,
    att_est_corrections=2, att_est_propagations=1, att_est_sun_used=True,
    truth_att_quat_w=1, truth_att_quat_x=0, truth_att_quat_y=0, truth_att_quat_z=0,
    truth_mag_body_x_nT=20000, truth_mag_body_y_nT=0, truth_mag_body_z_nT=0,
    gps_fix=True, gps_num_sv=8, gps_pdop=1.3, gps_h_acc_m=1.2, gps_v_acc_m=2.1)
app.app.run(port=5057, use_reloader=False)
