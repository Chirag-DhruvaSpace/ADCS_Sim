import numpy as np

rw_torques = np.zeros(4)      # 4 reaction-wheel torques (Nm)
mtr_torques = np.zeros(3)
mtr_dipole = np.zeros(3)
tau_body = np.zeros(3)
mode = "DETUMBLE"
mtr_currents = np.zeros(3)
angular_acceleration = np.zeros(3)
time = 0.0
moon_target_quat = np.array([1.0, 0.0, 0.0, 0.0])   # last computed moon-pointing target quaternion, for telemetry
nadir_target_quat = np.array([1.0, 0.0, 0.0, 0.0])  # last computed nadir-pointing target quaternion, for telemetry
sun_sweep_target_quat = np.array([1.0, 0.0, 0.0, 0.0])  # last computed sun-sweep target quaternion, for telemetry
sun_pointing_rw_target_quat = np.array([1.0, 0.0, 0.0, 0.0])  # last computed RW sun-pointing (body -Z) target quaternion, for telemetry
nominal_in_orbit_target_quat = np.array([1.0, 0.0, 0.0, 0.0])  # last computed nadir+45deg-yaw target quaternion, for telemetry
kinematic_robustness_target_quat = np.array([1.0, 0.0, 0.0, 0.0])  # last computed nadir(+Z)+spin target quaternion, for telemetry

# --- Live environmental disturbance torques (calculate_disturbances.py) -----
# Written on every RHS pass of rotational_equations_of_motion (last RK stage
# wins -- same convention as every other store record); read once per outer
# step by the telemetry in satellite_flight_visualisation.py. All body-frame,
# N*m. SRP is NOT included here -- it rides the existing srp_torque_body_*
# telemetry from solar_radiation_pressure.py, and keeping it separate avoids
# double-counting.
disturbance_torque = np.zeros(3)                    # net GG + residual dipole + drag
disturbance_torque_gravity_gradient = np.zeros(3)   # 3*mu/r^3 * (u x I u), live
disturbance_torque_residual_dipole = np.zeros(3)    # m x B with the real IGRF B
disturbance_torque_atmospheric_drag = np.zeros(3)   # r_cp x F_drag, live