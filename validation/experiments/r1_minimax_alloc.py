"""
r1_minimax_alloc.py

Variant #2 on wheel-load balancing: MINIMAX allocation instead of the
weighted-least-squares approach (r1_load_balanced_alloc.py). Rather than a
smooth quartic penalty that discourages loading a near-saturated wheel,
this directly minimizes, every control cycle, the WORST wheel's predicted
proximity to its speed cap -- solved as a small linear program:

    minimize t
    subject to  A @ u == tau_body                 (deliver the exact required torque)
                -RW_MAX_TORQUE <= u_i <= RW_MAX_TORQUE   (real per-wheel torque limit)
                |h_i + u_i*dt| <= t * H_MAX        (each wheel's predicted post-step
                                                     momentum, normalized to its cap,
                                                     bounded by the SAME t -- so t is
                                                     literally "how close the closest-
                                                     to-saturating wheel gets", and the
                                                     LP finds the u that minimizes it)

This is a genuinely different objective than the least-squares version:
least-squares minimizes total squared "effort" (weighted by proximity);
minimax directly minimizes the worst-case wheel, which is the more natural
objective for "avoid anyone saturating" specifically.

Same real Kp/Kd/feedforward law, CAD-verified deployed inertia, real
RW_MAX_TORQUE clip (now an explicit LP bound rather than a post-hoc clip),
same realistic per-wheel 6000rpm accelerate-only cap on top (for whatever
the LP still can't avoid).
"""
import numpy as np
from scipy.optimize import linprog
import handoff_sweep_v2 as hs
import r1_realistic_wheel_cap as rc
import r1_load_balanced_alloc as lb
import run_real_c_sunpointing_r1 as r1_mod

I_DEPLOYED = r1_mod.PLATFORM_MOI
KP = np.array(r1_mod.R1_GAIN_KP)
KD = np.array(r1_mod.R1_GAIN_KD)
RW_MOI = rc.RW_MOI
RW_MAX_TORQUE = lb.RW_MAX_TORQUE
H_MAX = lb.H_MAX
A = lb.A
DT = r1_mod.DT


def minimax_allocate(tau_body, h, dt=DT):
    """x = [u1,u2,u3,u4,t]. Minimize t s.t. A@u=tau_body, |u_i|<=RW_MAX_TORQUE,
    |h_i+u_i*dt| <= t*H_MAX for each wheel."""
    c = np.array([0, 0, 0, 0, 1.0])
    A_eq = np.hstack([A, np.zeros((3, 1))])
    b_eq = tau_body

    A_ub = []
    b_ub = []
    for i in range(4):
        row_pos = np.zeros(5); row_pos[i] = dt; row_pos[4] = -H_MAX
        A_ub.append(row_pos); b_ub.append(-h[i])
        row_neg = np.zeros(5); row_neg[i] = -dt; row_neg[4] = -H_MAX
        A_ub.append(row_neg); b_ub.append(h[i])
    A_ub = np.array(A_ub); b_ub = np.array(b_ub)

    bounds = [(-RW_MAX_TORQUE, RW_MAX_TORQUE)]*4 + [(0, None)]
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if res.success:
        return res.x[:4], False
    # infeasible (rare -- required torque exceeds total 4-wheel authority): fall back
    # to the least-squares weighted allocation for this single step rather than crash.
    return lb.weighted_allocate(tau_body, h), True


def run(omega_mag, t_final=10800.0, checkpoints=None):
    q, sun_dir = r1_mod.base.build_initial_attitude()
    omega = omega_mag * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / DT)
    cps = checkpoints or []
    ci = 0
    n_infeasible = 0
    peak_rpm = 0.0
    for k in range(n_steps + 1):
        t = k * DT
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
        peak_rpm = max(peak_rpm, np.max(np.abs(wheel_rpm)))
        if ci < len(cps) and t >= cps[ci]:
            print(f"  t={t:7.1f}s ({t/60:6.1f}min) p_err={p_err:7.2f}deg wheel_rpm={np.round(wheel_rpm).astype(int)}")
            ci += 1
        if p_err < 5.0:
            return t, peak_rpm, n_infeasible
        if k == n_steps:
            return None, peak_rpm, n_infeasible
        qerr = lb.calc_qerr(r1_mod.Q_TARGET_qwxyz, q)
        torque_body = -KP*qerr[1:4] - KD*omega + np.cross(omega, I_DEPLOYED*omega)
        u_raw, was_infeasible = minimax_allocate(torque_body, h)
        if was_infeasible:
            n_infeasible += 1
        u_wheel = rc.clamp_wheel_torque(u_raw, h)
        q, omega, h = lb.rk4_combined(q, omega, h, u_wheel, np.zeros(3), DT)


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min)\n")
    cps = [0, 60, 300, 600, 1200, 1800, 2700, 3600, 5400, 7200, 9000, 10800]
    tp, peak, n_infeasible = run(omega_mag, t_final=10800.0, checkpoints=cps)
    print()
    if tp:
        print(f"CONVERGED: R1={tp:.1f}s ({tp/60:.2f}min), total(MTR+R1)={(t_mm+tp)/60:.2f}min")
    else:
        print(f"NOT converged in 3hr")
    print(f"Peak wheel rpm used: {peak:.0f}, LP-infeasible steps (fell back to least-squares): {n_infeasible}")
