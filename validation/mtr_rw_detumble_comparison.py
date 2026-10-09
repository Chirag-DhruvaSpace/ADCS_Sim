"""
mtr_rw_detumble_comparison.py

Compares two detumbling strategies from the same 7deg/s tumble / 180deg
initial sun-pointing error used throughout this analysis:

  "MTR_ONLY"   -- classic B-dot bang-bang law (the SAME law already in
                  satellite_rotational_dynamics_var_mag_field.detumbling_torque),
                  no reaction wheels at all.
  "MTR_PLUS_RW"-- reaction wheels do the fast attitude+rate PD control (as in
                  sun_pointing_rw_saturation_analysis.py, corrected sign),
                  while MTR is dedicated to CONTINUOUSLY desaturating the
                  wheels in the background via a bang-bang B-cross momentum-
                  unloading law, so the wheels don't run out of margin the
                  way they did with no MTR at all.

MTR model: 3 independently-commandable dipole rods, +/-2 A*m^2 each
(sp.M_max), commanded on a 0.1 A*m^2 grid (per the user's hardware spec).
Quantization is applied to every M command; note it has literally zero
effect on the bang-bang law (its outputs already sit exactly on multiples
of 0.1) but DOES apply to the proportional-direction desaturation law used
in the combined strategy.

B-field: fixed vector, magnitude 3e-5 T -- the same order-of-magnitude value
this codebase's own MTR controller design already validated against real
IGRF (see periodic_gain_sun_pointing.py's comments: "|B|~3e-5T"). Held fixed
in direction rather than orbit-propagated: pyIGRF's PyPI package is missing
its coefficient data file in this environment (a packaging bug, not
something to work around by fetching files from an untrusted source), and a
fixed-direction field is a reasonable simplification for a detumbling-
duration question specifically -- what drives B-dot/desaturation physics
here is B as seen in the BODY frame, which sweeps through a wide range of
orientations from the vehicle's own 7deg/s tumble across all 3 axes alone,
independent of the (much slower, ~90min period) orbital rotation of B in
ECI. This would NOT be adequate for a many-orbit endurance question, but is
fine for "how long to detumble".
"""
import numpy as np

import satellite_params as sp
import reaction_wheel_model as rwm
import sun_pointing_rw_saturation_analysis as base

I = base.I
I_inv = base.I_INV

B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])

M_MAX = sp.M_max          # 2 A*m^2 per axis
M_STEP = 0.1              # A*m^2 command resolution

DT = base.DT              # 0.2s, 5Hz
T_FINAL = 6000.0          # s (up to ~100min, long enough for MTR-only to plausibly finish)
DETUMBLE_DONE_DEG_S = 0.5   # same threshold as DETUMBLE_OFF_DEG_S in the flight sim
POINTING_DONE_DEG = 5.0
DETUMBLE_PERAXIS_DEG_S = 2.0   # user's own definition: EACH axis below this, not the norm


def quantize(m):
    return np.clip(np.round(m / M_STEP) * M_STEP, -M_MAX, M_MAX)


def C_bi(q):
    return base.C_bi(q)


# ---------------------------------------------------------------------
# Strategy 1: MTR only -- classic B-dot bang-bang, no wheels.
# ---------------------------------------------------------------------
def bdot_dipole(omega, B_body):
    B_dot = -np.cross(omega, B_body)
    M = -M_MAX * np.sign(B_dot)
    return quantize(M)


def run_mtr_only(q0, sun_eci_dir, t_final=T_FINAL):
    n_steps = int(t_final / DT)
    state = np.zeros(7)
    state[0:4] = q0
    state[4:7] = np.radians(base.TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)

    t_hist = np.zeros(n_steps + 1)
    w_hist = np.zeros(n_steps + 1)
    w_axes_hist = np.zeros((n_steps + 1, 3))
    p_hist = np.zeros(n_steps + 1)

    t_detumbled = None
    t_detumbled_axis = None

    def deriv(state, M_body):
        q = state[0:4]; omega = state[4:7]
        Cbi = C_bi(q)
        B_body = Cbi.T @ B_ECI
        tau = np.cross(M_body, B_body)
        domega = I_inv @ (tau - np.cross(omega, I @ omega))
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        return np.concatenate([dq, domega])

    for k in range(n_steps + 1):
        q = state[0:4]; omega = state[4:7]
        t_hist[k] = k * DT
        w_hist[k] = np.degrees(np.linalg.norm(omega))
        w_axes_hist[k, :] = np.degrees(omega)
        p_hist[k] = base.pointing_error_deg(q, sun_eci_dir)

        if t_detumbled is None and w_hist[k] < DETUMBLE_DONE_DEG_S:
            t_detumbled = k * DT
        if t_detumbled_axis is None and np.all(np.abs(w_axes_hist[k, :]) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = k * DT

        if k == n_steps:
            break

        Cbi = C_bi(q)
        B_body = Cbi.T @ B_ECI
        M_body = bdot_dipole(omega, B_body)

        k1 = deriv(state, M_body)
        k2 = deriv(state + 0.5 * DT * k1, M_body)
        k3 = deriv(state + 0.5 * DT * k2, M_body)
        k4 = deriv(state + DT * k3, M_body)
        state = state + (DT / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        state[0:4] /= np.linalg.norm(state[0:4])

    return {"t": t_hist, "w_deg_s": w_hist, "w_axes_deg_s": w_axes_hist, "p_err_deg": p_hist,
            "t_detumbled": t_detumbled, "t_detumbled_axis": t_detumbled_axis}


# ---------------------------------------------------------------------
# Strategy 2: MTR + RW -- RW does PD pointing/detumbling, MTR continuously
# bang-bang-dumps whatever momentum the wheels are currently holding.
# ---------------------------------------------------------------------
def desat_dipole(h_wheels, B_body):
    H_w = rwm.wheel_momentum_vector_body(h_wheels)
    if np.linalg.norm(H_w) < 1e-9:
        return np.zeros(3)
    raw_dir = np.cross(H_w, B_body)
    n = np.linalg.norm(raw_dir)
    if n < 1e-12:
        return np.zeros(3)   # H_w parallel to B_body: momentarily undumpable, matches real hardware
    M = M_MAX * raw_dir / n
    return quantize(M)


def run_mtr_plus_rw(q0, sun_eci_dir, t_final=T_FINAL):
    n_steps = int(t_final / DT)
    state = np.zeros(11)
    state[0:4] = q0
    state[4:7] = np.radians(base.TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)

    t_hist = np.zeros(n_steps + 1)
    w_hist = np.zeros(n_steps + 1)
    w_axes_hist = np.zeros((n_steps + 1, 3))
    p_hist = np.zeros(n_steps + 1)
    h_hist = np.zeros((n_steps + 1, 4))

    t_detumbled = None
    t_detumbled_axis = None
    t_pointed = None
    first_sat_time = {i: None for i in range(4)}

    def deriv(state, u_wheels, M_body):
        q = state[0:4]; omega = state[4:7]; h = state[7:11]
        Cbi = C_bi(q)
        B_body = Cbi.T @ B_ECI
        tau_mtr = np.cross(M_body, B_body)
        H_w = rwm.wheel_momentum_vector_body(h)
        tau_wheel_reaction = rwm.A_WHEELS @ u_wheels
        domega = I_inv @ (-np.cross(omega, I @ omega + H_w) - tau_wheel_reaction + tau_mtr)
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = u_wheels.copy()
        return np.concatenate([dq, domega, dh])

    for k in range(n_steps + 1):
        q = state[0:4]; omega = state[4:7]; h = state[7:11]
        t_hist[k] = k * DT
        w_hist[k] = np.degrees(np.linalg.norm(omega))
        w_axes_hist[k, :] = np.degrees(omega)
        p_hist[k] = base.pointing_error_deg(q, sun_eci_dir)
        h_hist[k, :] = h * 1e3

        if t_detumbled is None and w_hist[k] < DETUMBLE_DONE_DEG_S:
            t_detumbled = k * DT
        if t_detumbled_axis is None and np.all(np.abs(w_axes_hist[k, :]) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = k * DT
        if t_pointed is None and w_hist[k] < DETUMBLE_DONE_DEG_S and p_hist[k] < POINTING_DONE_DEG:
            t_pointed = k * DT
        sat = np.abs(h) >= rwm.WHEEL_MOMENTUM_MAX_NMS - 1e-9
        for i in range(4):
            if sat[i] and first_sat_time[i] is None:
                first_sat_time[i] = k * DT

        if k == n_steps:
            break

        q_err = base.calc_quat_err(base.Q_TARGET, q)
        e = q_err[1:4]
        tau_cmd = -base.KP * e - base.KD * omega
        u_wheels = rwm.allocate_4wheel(-tau_cmd, h)

        Cbi = C_bi(q)
        B_body = Cbi.T @ B_ECI
        M_body = desat_dipole(h, B_body)

        k1 = deriv(state, u_wheels, M_body)
        k2 = deriv(state + 0.5 * DT * k1, u_wheels, M_body)
        k3 = deriv(state + 0.5 * DT * k2, u_wheels, M_body)
        k4 = deriv(state + DT * k3, u_wheels, M_body)
        state = state + (DT / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        state[0:4] /= np.linalg.norm(state[0:4])

    return {"t": t_hist, "w_deg_s": w_hist, "w_axes_deg_s": w_axes_hist, "p_err_deg": p_hist, "h_mNms": h_hist,
            "t_detumbled": t_detumbled, "t_detumbled_axis": t_detumbled_axis,
            "t_pointed": t_pointed, "first_sat_time": first_sat_time}


def _report(label, r, t_final):
    print(f"\n=== {label} ===")
    if r["t_detumbled_axis"] is not None:
        print(f"  Detumbled (EACH axis < {DETUMBLE_PERAXIS_DEG_S} deg/s) at t = {r['t_detumbled_axis']:.1f} s "
              f"({r['t_detumbled_axis']/60:.2f} min)")
    else:
        wa = r["w_axes_deg_s"][-1]
        print(f"  NOT per-axis-detumbled within {t_final:.0f}s "
              f"(final |wx|,|wy|,|wz| = {abs(wa[0]):.2f}, {abs(wa[1]):.2f}, {abs(wa[2]):.2f} deg/s)")
    if r["t_detumbled"] is not None:
        print(f"  (for reference, norm < {DETUMBLE_DONE_DEG_S} deg/s at t = {r['t_detumbled']:.1f} s)")
    if "t_pointed" in r:
        if r["t_pointed"] is not None:
            print(f"  Detumbled AND sun-pointing (<{POINTING_DONE_DEG} deg) at t = {r['t_pointed']:.1f} s "
                  f"({r['t_pointed']/60:.2f} min)")
        else:
            print(f"  Sun-pointing NOT achieved within {t_final:.0f}s (final pointing error {r['p_err_deg'][-1]:.1f} deg)")
    if "first_sat_time" in r:
        for i in range(4):
            tsat = r["first_sat_time"][i]
            print(f"  Wheel {i+1} saturation time: {'never' if tsat is None else f'{tsat:.1f} s'}")
    print(f"  Final body rate: {r['w_deg_s'][-1]:.3f} deg/s, final pointing error: {r['p_err_deg'][-1]:.1f} deg")


if __name__ == "__main__":
    q0, sun_eci_dir = base.build_initial_attitude()
    print(f"B field used (fixed, ECI): {B_ECI*1e6} uT, |B|={np.linalg.norm(B_ECI)*1e6:.1f} uT")
    print(f"MTR: +/-{M_MAX} A*m^2 per axis, {M_STEP} A*m^2 command resolution")
    print(f"Detumble criterion (user-specified): EACH axis < {DETUMBLE_PERAXIS_DEG_S} deg/s")

    r1 = run_mtr_only(q0.copy(), sun_eci_dir)
    _report("Strategy: MTR only (B-dot bang-bang, no wheels)", r1, T_FINAL)

    r2 = run_mtr_plus_rw(q0.copy(), sun_eci_dir)
    _report("Strategy: MTR + RW (RW points/detumbles, MTR continuously desaturates wheels)", r2, T_FINAL)

    np.savez("mtr_rw_detumble_comparison_results.npz",
             mtr_t=r1["t"], mtr_w=r1["w_deg_s"], mtr_p=r1["p_err_deg"],
             combo_t=r2["t"], combo_w=r2["w_deg_s"], combo_p=r2["p_err_deg"], combo_h=r2["h_mNms"])
    print("\nSaved time-series to mtr_rw_detumble_comparison_results.npz")
