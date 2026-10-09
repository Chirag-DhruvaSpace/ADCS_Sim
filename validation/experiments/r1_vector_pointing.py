"""
r1_vector_pointing.py

Second-iteration prototype. The first rate-governed attempt (r1_rate_governed.py)
still stalled -- traced to two compounding issues:

  1. The shipped R1 law (and my first rewrite) tracks a FULL 3-axis attitude
     match against Q_TARGET. But sun-pointing is a 2-DOF constraint: only
     body -Z needs to align with the sun direction. The 3rd DOF (roll about
     that boresight) is completely free for the mission -- tracking a
     specific roll wastes wheel momentum for zero mission benefit.
  2. The test scenario starts EXACTLY at the 180deg antipodal point (body -Z
     exactly opposite the sun). At exactly 180deg, the quaternion vector-part
     axis is mathematically well-defined, but nothing forces the controller
     to commit decisively to it -- a known "unwinding" instability in
     quaternion feedback control near the antipode. My rate-governed law
     wobbled near 180deg for hundreds of seconds instead of committing.

Fix for both: switch to a 2-DOF VECTOR-POINTING error (b_hat x s_hat, the
standard cross-product alignment error -- ignores roll entirely) instead of
a full quaternion error, and resolve the antipodal degeneracy (cross product
-> 0 right at 180deg) by rotating about whatever axis the body ALREADY has
residual rate on (from the MTR handoff) rather than an arbitrary fixed axis.
This is also momentum-minimizing: it "coasts" the existing residual rate
into the correction instead of fighting it to impose an unrelated axis.

Rate-governed reference (same idea as before) + gyroscopic feedforward,
driven through the REAL rwTorqueDist() (fw_rw_torque_dist_raw) and the
realistic per-wheel 6000rpm accelerate-only cap.
"""
import ctypes
import numpy as np
import run_real_c_sunpointing_r1 as r1_mod
import r1_realistic_wheel_cap as rc
import handoff_sweep_v2 as hs

I_DEPLOYED = r1_mod.PLATFORM_MOI
RW_MOI = rc.RW_MOI


def vector_pointing_error(q, sun_eci_dir, omega_body_for_degenerate_axis):
    Cbi = r1_mod.base.C_bi(q)
    b_hat = Cbi @ np.array([0.0, 0.0, -1.0])   # body -Z in ECI
    cross = np.cross(b_hat, sun_eci_dir)
    sin_angle = np.linalg.norm(cross)
    cos_angle = np.clip(np.dot(b_hat, sun_eci_dir), -1.0, 1.0)
    angle = np.arctan2(sin_angle, cos_angle)   # 0..pi, robust near both 0 and pi

    if sin_angle > 1e-6:
        axis_eci = cross / sin_angle
    else:
        # Degenerate (aligned or antipodal): pick an axis from whatever rate
        # the body already has (in ECI), so the correction coasts along
        # existing momentum instead of fighting to impose an arbitrary one.
        w_norm = np.linalg.norm(omega_body_for_degenerate_axis)
        if w_norm > 1e-6:
            axis_eci = Cbi @ (omega_body_for_degenerate_axis / w_norm)
        else:
            axis_eci = np.array([1.0, 0.0, 0.0])
        if cos_angle < 0:   # antipodal: rotating either way about this axis works
            pass
        else:
            axis_eci = np.zeros(3)   # already aligned, no rotation needed

    axis_body = Cbi.T @ axis_eci   # error axis expressed in body frame (matches bodyRate convention)
    return angle, axis_body


def run(omega_mag_seed, omega_max_deg_s, k_rate, kd_track, t_final=6000.0, checkpoints=None):
    r1_mod.fw.fw_init_config()
    q0, sun_dir = r1_mod.base.build_initial_attitude()
    q = q0.copy()
    omega = omega_mag_seed * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / r1_mod.DT)
    t_pointed = None
    peak_rpm = 0.0
    rows = []
    ci = 0
    cps = checkpoints or []

    for k in range(n_steps + 1):
        t = k * r1_mod.DT
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h / RW_MOI) * 60.0 / (2 * np.pi)
        peak_rpm = max(peak_rpm, np.max(np.abs(wheel_rpm)))

        if ci < len(cps) and t >= cps[ci]:
            rows.append((t, p_err, np.degrees(omega).copy(), wheel_rpm.copy()))
            ci += 1

        if p_err < 5.0:
            t_pointed = t
            break
        if k == n_steps:
            break

        angle, axis_body = vector_pointing_error(q, sun_dir, omega)
        angle_deg = np.degrees(angle)
        omega_ref_mag = min(omega_max_deg_s, k_rate * angle_deg)
        omega_ref_deg_s = omega_ref_mag * axis_body

        rate_err_rad_s = omega - np.radians(omega_ref_deg_s)
        gyro_ff = np.cross(omega, I_DEPLOYED * omega)
        torque_body = gyro_ff - kd_track * rate_err_rad_s

        wtorque_out = r1_mod.c_arr([0.0, 0.0, 0.0, 0.0])
        r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr(list(torque_body)), wtorque_out)
        u_raw = np.array(wtorque_out)
        u_wheel = rc.clamp_wheel_torque(u_raw, h)

        q, omega, h = r1_mod.rk4_gyrostat(q, omega, h, u_wheel, r1_mod.DT)

    return {"t_pointed": t_pointed, "peak_rpm": peak_rpm, "trace": rows}


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min), residual = {np.degrees(omega_mag):.3f} deg/s\n")

    KD_TRACK = I_DEPLOYED * 0.2
    for omega_max, k_rate in [(0.5, 0.02), (0.7, 0.02), (1.0, 0.02), (0.3, 0.02), (0.7, 0.05)]:
        r = run(omega_mag, omega_max, k_rate, KD_TRACK, t_final=6000.0)
        tp = r["t_pointed"]
        status = f"{tp:.1f}s ({tp/60:.2f}min)" if tp else "NOT converged in 6000s"
        total = f"{(t_mm+tp)/60:.2f}min" if tp else "n/a"
        print(f"omega_max={omega_max:.1f}deg/s, k_rate={k_rate:.3f}: R1={status}, total={total}, peak_rpm={r['peak_rpm']:.0f}")
