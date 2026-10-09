"""
handoff_sweep_v2.py

Re-run of the MTR-detumbling -> SunPointing_R1(RW) handoff-threshold sweep,
using the fw_control.dll rebuilt 2026-08-07 with the real firmware's new
DEG_TO_RAD fix in sun_pointing_r1_control.c baked in, and feeding bodyRate
in DEGREES/s at every call site (matching the real ADIS16545 gyro driver
convention) -- both changes verified against the actual source this session.

Methodology (same as the earlier 55.25min/0.7deg-s result this session):
  1. Run Detumbling_MM (bdotCalcTorq, MTR only) from the 7deg/s tumble until
     ALL 3 axes drop below a handoff threshold.
  2. Seed SunPointing_R1 with that residual rate MAGNITUDE (not vector, since
     MM's final rate is expressed in MM's own uncontrolled final attitude --
     using only the magnitude, applied along the same (1,1,1)/sqrt(3) axis
     convention used for the initial tumble, avoids grafting inconsistent
     attitude/rate state -- same fix applied earlier this session), starting
     from the standard 180deg initial sun-pointing-error attitude.
  3. Run R1 (fw_r1_step, current real gains via fw_set_r1_gains) until
     pointing < 5deg, tracking peak wheel rpm throughout.
  4. Report total time and peak rpm per threshold; the answer is the LARGEST
     threshold (= fastest total time) that keeps peak rpm under 5000.
"""
import ctypes
import numpy as np

import run_real_c_detumbling as mm
import run_real_c_sunpointing_r1 as r1_mod
import sun_pointing_rw_saturation_analysis as base

RW_MOI = 5.4e-5


def run_mm_to_threshold(threshold_deg_s, t_final=6000.0):
    mm.fw.fw_init_config()
    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(mm.TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / mm.DT)

    for k in range(n_steps + 1):
        w_deg = np.degrees(omega)
        if np.all(np.abs(w_deg) < threshold_deg_s):
            return k * mm.DT, np.linalg.norm(omega)
        if k == n_steps:
            return None, None

        Cbi = mm.C_bi(q)
        B_body = Cbi.T @ mm.B_ECI
        omega_deg_s = np.degrees(omega)
        dipole_out = mm.c_arr([0.0, 0.0, 0.0])
        mm.fw.fw_mm_step(mm.c_arr(list(omega_deg_s)), mm.c_arr(list(B_body * 1e6)), dipole_out)
        dipole = np.array(dipole_out)
        tau_ext = np.cross(dipole, B_body)
        u_wheel = np.zeros(4)
        q, omega, h = mm.rk4_gyrostat(q, omega, h, tau_ext, u_wheel, mm.DT)


def run_r1_from_seed(omega_mag_rad_s, t_final=6000.0):
    r1_mod.fw.fw_init_config()
    r1_mod.fw.fw_set_r1_gains(r1_mod.c_arr(r1_mod.R1_GAIN_KP), r1_mod.c_arr(r1_mod.R1_GAIN_KD))
    q0, sun_dir = base.build_initial_attitude()
    q = q0.copy()
    omega = omega_mag_rad_s * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / r1_mod.DT)
    peak_rpm = 0.0

    for k in range(n_steps + 1):
        p_err = base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h / RW_MOI) * 60.0 / (2 * np.pi)
        peak_rpm = max(peak_rpm, np.max(np.abs(wheel_rpm)))
        if p_err < 5.0:
            return k * r1_mod.DT, peak_rpm
        if k == n_steps:
            return None, peak_rpm

        wtorque_out = r1_mod.c_arr([0.0, 0.0, 0.0, 0.0])
        r1_mod.fw.fw_r1_step(r1_mod.c_arr(list(np.degrees(omega))),
                              r1_mod.c_arr(list(r1_mod.Q_TARGET_qwxyz)),
                              r1_mod.c_arr(list(q)), wtorque_out)
        u_wheel = np.array(wtorque_out)
        q, omega, h = r1_mod.rk4_gyrostat(q, omega, h, u_wheel, r1_mod.DT)


if __name__ == "__main__":
    print(f"{'Threshold':>10} | {'MM time':>10} | {'R1 time':>10} | {'Total':>10} | {'Peak rpm':>10}")
    for thresh in [0.3, 0.5, 0.7, 1.0, 1.5, 2.0]:
        t_mm, omega_mag = run_mm_to_threshold(thresh)
        if t_mm is None:
            print(f"{thresh:>10.1f} | MM never reached this threshold")
            continue
        t_r1, peak_rpm = run_r1_from_seed(omega_mag)
        if t_r1 is None:
            print(f"{thresh:>10.1f} | {t_mm:>10.1f} | R1 never converged | peak_rpm={peak_rpm:.0f}")
            continue
        total = t_mm + t_r1
        flag = "OK" if peak_rpm < 5000 else "OVER 5000rpm LIMIT"
        print(f"{thresh:>10.1f} | {t_mm/60:>9.2f}m | {t_r1/60:>9.2f}m | {total/60:>9.2f}m | {peak_rpm:>9.0f} rpm  {flag}")
