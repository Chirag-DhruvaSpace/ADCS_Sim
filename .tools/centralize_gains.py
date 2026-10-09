from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=root/'satellite_rotational_dynamics_var_mag_field.py'; t=p.read_text(encoding='utf-8')
t=t.replace('w_n = 0.05','w_n = config.CONTROL.pointing_natural_frequency_rad_s').replace('zeta = 1.0','zeta = config.CONTROL.pointing_damping_ratio')
t=t.replace('dt=0.2','dt=config.CONTROL.target_rate_difference_step_s')
t=t.replace('KINEMATIC_ROBUSTNESS_SPIN_RATE_DEG_S = 1.0   # adjustable parameter, default per requirement','KINEMATIC_ROBUSTNESS_SPIN_RATE_DEG_S = config.CONTROL.kinematic_spin_rate_deg_s')
p.write_text(t,encoding='utf-8')
for filename,prefix in [('cross_b_torque.py','magnetic_pd'),('calculate_satellite_body_torques.py','manual_rw')]:
    p=root/filename;t=p.read_text(encoding='utf-8')
    t='import satellite_parameters as config\n'+t
    import re
    t=re.sub(r'    w_n = (0\.1|0\.018) .*',f'    w_n = config.CONTROL.{prefix}_natural_frequency_rad_s',t)
    t=re.sub(r'    zeta = (1\.5|1\.0) .*',f'    zeta = config.CONTROL.{prefix}_damping_ratio',t,count=1)
    p.write_text(t,encoding='utf-8')
p=root/'kinematic_robustness_pointing.py';t=p.read_text(encoding='utf-8')
# Keep the module docstring first.
t=t.replace('DEFAULT_SPIN_RATE_DEG_S = 1.0   # adjustable parameter, default per requirement',
    'from satellite_parameters import CONTROL\nDEFAULT_SPIN_RATE_DEG_S = CONTROL.kinematic_spin_rate_deg_s')
p.write_text(t,encoding='utf-8')
p=root/'satellite_parameters.yaml';t=p.read_text(encoding='utf-8')
t=t.replace('  sun_pointing_base_rate_deg_s: 0.2  # Nominal MTR governor slew rate', '''  # PD tuning. Natural frequency [rad/s], dimensionless damping ratio.
  # These preserve existing active gains; they are not newly tuned for CAD inertia.
  pointing_natural_frequency_rad_s: 0.05 # Automatic RW target modes
  pointing_damping_ratio: 1.0
  manual_rw_natural_frequency_rad_s: 0.018 # Manual Euler target controller
  manual_rw_damping_ratio: 1.0
  magnetic_pd_natural_frequency_rad_s: 0.1 # Manual magnetic B-cross controller
  magnetic_pd_damping_ratio: 1.5
  kinematic_spin_rate_deg_s: 1.0        # Continuous body-axis rotation
  target_rate_difference_step_s: 0.2   # Finite-difference step for moving targets
  sun_pointing_base_rate_deg_s: 0.2    # Nominal MTR governor slew rate''')
p.write_text(t,encoding='utf-8')
