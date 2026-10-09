"""
rg_mtr_best_strategy.py

Tests three candidate fixes for combining RW (Detumbling_RG) + MTR
desaturation, given the naive "just wire in desaturationCalcTorq()"
approach was found to backfire (fights the RW rate-damping loop, wheel
speed grows without bound instead of stabilizing):

  A) SEQUENCED   -- MTR desaturation only activates once body rate is
                    already below a threshold (so the RW loop's gain isn't
                    reacting to MTR-induced disturbances during the fast,
                    high-gain part of the maneuver).
  B) WEAK_GAIN    -- MTR desaturation runs concurrently (same as before),
                    but with AdsStat_DesatGain reduced well below the
                    default 10.0, so it perturbs the body gently enough
                    that the RW loop doesn't fight it.
  C) CURRENT      -- baseline, no MTR at all (for reference).

User's criteria:
  1) "Detumbled" = ALL 3 axes < 2 deg/s (already the threshold used
     throughout this analysis).
  2) After detumbling, chain the surviving wheel momentum state into a
     SunPointing_R1 run (180deg maneuver, using the already-fixed R1 gains)
     to confirm the wheels have enough remaining torque/momentum margin to
     actually complete sun-pointing afterward -- not just that detumbling
     itself "succeeds" on paper.
"""
import ctypes
import numpy as np

import run_real_c_rg_with_desat as rg
import run_real_c_sunpointing_r1 as r1_mod
import reaction_wheel_model as rwm

rg.fw.fw_set_desat_gain.argtypes = [ctypes.c_double]
rg.fw.fw_set_desat_gain.restype = None

DESAT_START_RPM = 5000.0
SEQUENCE_RATE_THRESH_DEG_S = 2.0   # gate: only desaturate once body rate is already this low


def run_detumble(strategy, t_final=6000.0, desat_gain=10.0):
    rg.fw.fw_init_config()
    if strategy == "weak_gain":
        rg.fw.fw_set_desat_gain(desat_gain)

    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(rg.TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / rg.DT)

    t_detumbled_axis = None
    max_rpm_seen = 0.0
    first_wheel_sat_time = None   # first time any wheel crosses the real 5000rpm FSM trigger

    for k in range(n_steps + 1):
        t = k * rg.DT
        w_deg = np.degrees(omega)
        wheel_rpm = (h / rg.RW_MOI) * 60.0 / (2 * np.pi)
        max_rpm_seen = max(max_rpm_seen, np.max(np.abs(wheel_rpm)))

        if t_detumbled_axis is None and np.all(np.abs(w_deg) < 2.0):
            t_detumbled_axis = t
        if first_wheel_sat_time is None and np.any(np.abs(wheel_rpm) >= DESAT_START_RPM):
            first_wheel_sat_time = t

        if k == n_steps:
            break

        if strategy == "current":
            wtorque_out = rg.c_arr([0.0] * 4)
            rg.fw.fw_rg_step(rg.c_arr(list(omega)), wtorque_out)
            wt = np.array(wtorque_out)
            tau_mtr = np.zeros(3)
        else:
            Cbi = rg.C_bi(q)
            B_body = Cbi.T @ rg.B_ECI
            wtorque_out = rg.c_arr([0.0] * 4)
            dipole_out = rg.c_arr([0.0, 0.0, 0.0])
            desat_flag = ctypes.c_int(0)

            gate_ok = True
            if strategy == "sequenced":
                gate_ok = np.all(np.abs(w_deg) < SEQUENCE_RATE_THRESH_DEG_S)

            if gate_ok:
                rg.fw.fw_rg_step_with_desat(rg.c_arr(list(omega)), rg.c_arr(list(B_body * 1e6)),
                                             rg.c_arr(list(wheel_rpm)), wtorque_out, dipole_out,
                                             ctypes.byref(desat_flag))
                wt = np.array(wtorque_out)
                dipole = np.array(dipole_out)
                tau_mtr = np.cross(dipole, B_body)
            else:
                rg.fw.fw_rg_step(rg.c_arr(list(omega)), wtorque_out)
                wt = np.array(wtorque_out)
                tau_mtr = np.zeros(3)

        q, omega, h = rg.rk4(q, omega, h, wt, tau_mtr, rg.DT)

    return {"t_detumbled_axis": t_detumbled_axis, "w_final": np.degrees(omega),
            "max_rpm_seen": max_rpm_seen, "first_wheel_sat_time": first_wheel_sat_time,
            "q_final": q, "h_final": h,
            "wheel_rpm_final": (h / rg.RW_MOI) * 60.0 / (2 * np.pi)}


def run_sunpoint_followon(q0, h0, t_final=6000.0):
    """Chain detumbling's final (q, h) state into a 180deg SunPointing_R1
    maneuver, using the already-fixed R1 gains, to check the wheels have
    enough remaining margin to actually complete it."""
    r1_mod.fw.fw_init_config()
    q0_target, sun_dir = r1_mod.base.build_initial_attitude()
    # Reuse the same 180deg-from-target starting orientation for the sun-pointing
    # axis check (q0 here is detumbling's own final attitude, which is arbitrary/
    # uncontrolled -- for a clean "does R1 have enough wheel margin" test, start
    # R1 fresh at the standard 180deg condition, but inherit the wheel state h0
    # detumbling left behind).
    q = q0_target.copy()
    omega = np.zeros(3)
    h = h0.copy()
    n_steps = int(t_final / r1_mod.DT)
    t_pointed = None
    first_sat = {i: None for i in range(4)}
    for k in range(n_steps + 1):
        t = k * r1_mod.DT
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        if t_pointed is None and p_err < 5.0:
            t_pointed = t
        sat = np.abs(h) >= rwm.WHEEL_MOMENTUM_MAX_NMS - 1e-9
        for i in range(4):
            if sat[i] and first_sat[i] is None:
                first_sat[i] = t
        if k == n_steps:
            return {"t_pointed": t_pointed, "p_final": p_err, "first_sat": first_sat,
                    "w_final": np.degrees(omega)}
        wtorque_out = r1_mod.c_arr([0.0, 0.0, 0.0, 0.0])
        r1_mod.fw.fw_r1_step(r1_mod.c_arr(list(omega)), r1_mod.c_arr(list(r1_mod.Q_TARGET_qwxyz)),
                              r1_mod.c_arr(list(q)), wtorque_out)
        wt = np.array(wtorque_out)
        q, omega, h = r1_mod.rk4_gyrostat(q, omega, h, wt, r1_mod.DT)


if __name__ == "__main__":
    strategies = [
        ("current", "C) CURRENT: RW only, MTR off", {}),
        ("sequenced", "A) SEQUENCED: MTR desat gated on rate already <2deg/s", {}),
        ("weak_gain", "B) WEAK_GAIN: concurrent, DesatGain=1.0 (vs default 10.0)", {"desat_gain": 1.0}),
        ("weak_gain", "B) WEAK_GAIN: concurrent, DesatGain=0.1", {"desat_gain": 0.1}),
    ]

    results = {}
    for strat, label, kwargs in strategies:
        r = run_detumble(strat, **kwargs)
        results[label] = r
        print(f"\n=== {label} ===")
        det_str = "never" if r["t_detumbled_axis"] is None else f"{r['t_detumbled_axis']:.1f}s ({r['t_detumbled_axis']/60:.2f}min)"
        print(f"  Detumbled (<2deg/s all axes): {det_str}")
        sat_str = "never" if r["first_wheel_sat_time"] is None else f"{r['first_wheel_sat_time']:.1f}s"
        print(f"  First wheel crosses real 5000rpm FSM trigger: {sat_str}")
        print(f"  Max wheel speed reached (6000s): {r['max_rpm_seen']:.0f} rpm")
        print(f"  Final wheel speeds: {r['wheel_rpm_final']} rpm")
        print(f"  Final body rate: {r['w_final']} deg/s")

        # Sun-pointing follow-on check
        sp = run_sunpoint_followon(r["q_final"], r["h_final"])
        sp_str = "never" if sp["t_pointed"] is None else f"{sp['t_pointed']:.1f}s ({sp['t_pointed']/60:.2f}min)"
        n_sat = sum(1 for v in sp["first_sat"].values() if v is not None)
        print(f"  --> Follow-on 180deg sun-point (inheriting this wheel state):")
        print(f"      Achieves <5deg pointing: {sp_str}, wheels saturated: {n_sat}/4, "
              f"final error: {sp['p_final']:.2f}deg")
