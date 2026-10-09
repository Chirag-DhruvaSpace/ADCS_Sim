"""
r1_realistic_wheel_cap.py

Re-test of SunPointing_R1 (RW alone, no MTR) from the full 7deg/s tumble +
180deg pointing error, correcting a modeling mistake from earlier this
session: I was treating "a wheel crosses 5000/6000rpm" as an automatic
Safe-Mode abort, reasoning rwSaturated() would trip. Verified against the
real source (state_machine.c) that's wrong -- rwSaturated() is ONLY called
inside state_Detumbling_RG's onTick; state_SunPointing_R1 has no wheel-speed
check at all (only gpsUsable/rwUsable/eclipse/success/timeout gate it).

Physically correct model instead: a wheel motor has a real max mechanical
speed (WHEEL_MAX_RPM = 6000, the datasheet rating). Once a wheel reaches
that speed, it cannot be commanded to accelerate FURTHER in the same
direction (motor authority saturates), but it can ALWAYS be decelerated --
exactly the point raised: as the body approaches the target, the PD law
naturally commands the opposite (braking) torque, which remains available
even from a maxed-out wheel. So the correct clamp is per-wheel,
direction-aware, not a blanket sim-stops-here cutoff.

dh[i]/dt = -wheel_torque_out[i] (real sign convention, verified this
session: A_WHEELS @ TorqDistMat == I_3, so body torque is direct, wheel
reaction is the Newton's-third-law opposite). A wheel is ACCELERATING
further (|h[i]| growing) when sign(dh[i]/dt) == sign(h[i]), i.e. when
sign(wheel_torque_out[i]) != sign(h[i]). Clamp exactly that case to zero;
everything else (deceleration, or any wheel not yet at cap) passes through
unchanged.
"""
import numpy as np
import run_real_c_sunpointing_r1 as r1_mod

RW_MOI = 5.4e-5
WHEEL_MAX_RPM = 6000.0
H_MAX = RW_MOI * (WHEEL_MAX_RPM * 2 * np.pi / 60.0)


def clamp_wheel_torque(wheel_torque_out, h):
    wt = wheel_torque_out.copy()
    for i in range(4):
        if abs(h[i]) >= H_MAX:
            accelerating_further = (np.sign(wt[i]) != np.sign(h[i])) and wt[i] != 0.0
            if accelerating_further:
                wt[i] = 0.0
    return wt


def run(t_final=3000.0, verbose_checkpoints=None):
    r1_mod.fw.fw_init_config()
    r1_mod.fw.fw_set_r1_gains(r1_mod.c_arr(r1_mod.R1_GAIN_KP), r1_mod.c_arr(r1_mod.R1_GAIN_KD))
    q0, sun_dir = r1_mod.base.build_initial_attitude()
    q = q0.copy()
    omega = np.radians(r1_mod.TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / r1_mod.DT)

    t_detumbled = None
    t_pointed = None
    peak_rpm = 0.0
    n_clamped_events = 0
    checkpoints = verbose_checkpoints or []
    ci = 0

    for k in range(n_steps + 1):
        t = k * r1_mod.DT
        w_deg = np.degrees(omega)
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h / RW_MOI) * 60.0 / (2 * np.pi)
        peak_rpm = max(peak_rpm, np.max(np.abs(wheel_rpm)))

        if t_detumbled is None and np.all(np.abs(w_deg) < 2.0):
            t_detumbled = t
        if t_pointed is None and p_err < 5.0:
            t_pointed = t

        if ci < len(checkpoints) and t >= checkpoints[ci]:
            print(f"  t={t:7.1f}s  p_err={p_err:7.2f}deg  w=({w_deg[0]:7.3f},{w_deg[1]:7.3f},{w_deg[2]:7.3f})deg/s  "
                  f"wheel_rpm=({wheel_rpm[0]:8.0f},{wheel_rpm[1]:8.0f},{wheel_rpm[2]:8.0f},{wheel_rpm[3]:8.0f})")
            ci += 1

        if t_pointed is not None and t_detumbled is not None:
            break
        if k == n_steps:
            break

        wtorque_out = r1_mod.c_arr([0.0, 0.0, 0.0, 0.0])
        r1_mod.fw.fw_r1_step(r1_mod.c_arr(list(np.degrees(omega))), r1_mod.c_arr(list(r1_mod.Q_TARGET_qwxyz)),
                              r1_mod.c_arr(list(q)), wtorque_out)
        u_wheel_raw = np.array(wtorque_out)
        u_wheel = clamp_wheel_torque(u_wheel_raw, h)
        if not np.array_equal(u_wheel, u_wheel_raw):
            n_clamped_events += 1

        q, omega, h = r1_mod.rk4_gyrostat(q, omega, h, u_wheel, r1_mod.DT)

    return {
        "t_detumbled": t_detumbled, "t_pointed": t_pointed, "peak_rpm": peak_rpm,
        "n_clamped_steps": n_clamped_events, "final_p_err": p_err, "final_w_deg": w_deg,
        "final_wheel_rpm": wheel_rpm,
    }


if __name__ == "__main__":
    print(f"Real wheel max speed (hardware rating): {WHEEL_MAX_RPM:.0f} rpm (H_MAX={H_MAX*1e3:.2f} mN*m*s)")
    print("SunPointing_R1, RW alone, from full 7deg/s tumble + 180deg error, realistic wheel-speed clamp:")
    print(f"{'t(s)':>8} {'p_err':>8} {'wx,wy,wz (deg/s)':>26}   {'wheel rpm (1,2,3,4)':>40}")
    r = run(t_final=3000.0, verbose_checkpoints=[0, 30, 60, 90, 120, 150, 200, 300, 450, 600, 800, 1000])
    print()
    td = r["t_detumbled"]; tp = r["t_pointed"]
    print(f"Detumbled (<2deg/s all axes): {'never' if td is None else f'{td:.1f}s ({td/60:.2f}min)'}")
    print(f"Sun-pointing achieved (<5deg): {'never' if tp is None else f'{tp:.1f}s ({tp/60:.2f}min)'}")
    print(f"Peak wheel speed reached: {r['peak_rpm']:.0f} rpm (cap: {WHEEL_MAX_RPM:.0f} rpm)")
    print(f"Steps where torque was clamped (a wheel at cap, would've accelerated further): {r['n_clamped_steps']}")
    print(f"Final pointing error: {r['final_p_err']:.2f} deg, final body rate: {r['final_w_deg']} deg/s")
    print(f"Final wheel rpm: {r['final_wheel_rpm']}")
