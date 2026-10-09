"""
max_absorbable_tumble_rate.py

Answers: "what's the largest tumble rate this 4-wheel cluster can FULLY
absorb using reaction wheels alone (no MTR)?"

Two complementary calculations:

1. ANALYTICAL (steady-state momentum budget): if the body is to end at rest
   (omega=0) with MTR unavailable, total system angular momentum is
   conserved, so the wheels alone must end up storing exactly the body's
   ENTIRE initial momentum vector L0 = I*omega0. This is a straight linear
   scaling (h(omega0) = omega0 * [pinv(A) @ (I @ axis)]) -- no need to
   simulate the transient to find this bound, and it also naturally reveals
   the anisotropy the user's own torque-authority table already showed
   (some tumble axes store more cheaply than others).

2. SIMULATED (closed-loop, nonlinear): confirms the analytical bound is
   actually reachable by the real feedback control law (same PD as
   SUN_POINTING_RW, 4-wheel pseudo-inverse allocation, hard torque+momentum
   limits) starting from the same worst-case 180deg initial sun-pointing
   error used in the previous test -- the linear argument only proves a
   final state COULD exist within budget, not that the transient trajectory
   getting there stays within budget too.
"""
import numpy as np
import reaction_wheel_model as rwm
import sun_pointing_rw_saturation_analysis as base

I = base.I

# ---------------------------------------------------------------------
# 1. Analytical: max omega0 (deg/s) along a given axis before any single
#    wheel's REQUIRED steady-state momentum exceeds its 26.67 mN*m*s limit.
# ---------------------------------------------------------------------
def max_rate_analytical(axis_unit):
    axis_unit = np.asarray(axis_unit, dtype=float)
    axis_unit = axis_unit / np.linalg.norm(axis_unit)
    L_per_rad_s = I @ axis_unit                      # L0 direction/scale per rad/s of omega0
    h_per_rad_s = rwm._A_PINV @ L_per_rad_s           # required wheel momenta per rad/s of omega0
    max_h_per_rad_s = np.max(np.abs(h_per_rad_s))
    omega0_max_rad_s = rwm.WHEEL_MOMENTUM_MAX_NMS / max_h_per_rad_s
    return np.degrees(omega0_max_rad_s)


axes_of_interest = {
    "even (1,1,1)/sqrt3  -- same axis as the previous 7deg/s test": np.array([1, 1, 1]),
    "body +X":  np.array([1, 0, 0]),
    "body +Y":  np.array([0, 1, 0]),
    "body +Z":  np.array([0, 0, 1]),
}

print("=== Analytical max fully-absorbable tumble rate (steady-state momentum budget) ===")
best, worst = None, None
# also scan many random directions to find the true worst/best case axis, matching
# the anisotropy the user's own torque-authority numbers already implied.
rng_dirs = []
for theta in np.linspace(0, np.pi, 19):
    for phi in np.linspace(0, 2 * np.pi, 37):
        rng_dirs.append([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)])
rng_dirs = np.array(rng_dirs)

for label, axis in axes_of_interest.items():
    rate = max_rate_analytical(axis)
    print(f"  {label:60s}: {rate:6.2f} deg/s")
    if best is None or rate > best[1]:
        best = (label, rate)
    if worst is None or rate < worst[1]:
        worst = (label, rate)

scan_rates = np.array([max_rate_analytical(a) for a in rng_dirs])
worst_idx, best_idx = np.argmin(scan_rates), np.argmax(scan_rates)
print(f"\n  Scanned {len(rng_dirs)} directions on the unit sphere:")
print(f"    WORST-case axis {rng_dirs[worst_idx]}: {scan_rates[worst_idx]:.2f} deg/s")
print(f"    BEST-case  axis {rng_dirs[best_idx]}: {scan_rates[best_idx]:.2f} deg/s")

even_axis = np.array([1, 1, 1]) / np.sqrt(3)
even_rate = max_rate_analytical(even_axis)

# ---------------------------------------------------------------------
# 2. Simulated confirmation, same axis/initial-error as the earlier 7deg/s
#    test, sweeping rate to find where the closed-loop trajectory actually
#    stops saturating AND actually converges to ~0 body rate + sun-pointing.
# ---------------------------------------------------------------------
print("\n=== Closed-loop simulation sweep (4-wheel, 180deg initial pointing error) ===")
q0, sun_eci_dir = base.build_initial_attitude()

test_rates = sorted(set(
    list(np.round(np.arange(0.2, even_rate + 0.4, 0.2), 2))
))

sweep_results = []
for rate in test_rates:
    omega0 = np.radians(rate) * even_axis
    res = base.run(q0.copy(), sun_eci_dir, omega0, t_final=1200.0)
    ever_saturated = np.any(np.abs(res["wheel_rpm"]) >= base.WHEEL_MAX_RPM - 1e-6)
    final_w = np.linalg.norm(res["w_deg_s"][-1])
    final_p = res["p_err_deg"][-1]
    converged = (final_w < 0.5) and (final_p < 5.0)
    sweep_results.append((rate, ever_saturated, final_w, final_p, converged))
    print(f"  omega0={rate:5.2f} deg/s  |  any wheel saturated: {str(ever_saturated):5s}  |  "
          f"final rate={final_w:6.3f} deg/s  final pointing err={final_p:6.2f} deg  |  "
          f"{'CONVERGED' if converged else 'did not converge'}")

# Largest rate that both never saturates and converges
ok_rates = [r for r, sat, fw, fp, conv in sweep_results if (not sat) and conv]
max_simulated_ok = max(ok_rates) if ok_rates else None

print(f"\nAnalytical bound for this axis (1,1,1)/sqrt3: {even_rate:.2f} deg/s")
print(f"Largest simulated rate that never saturates AND converges to sun-pointing: "
      f"{'none tested converged' if max_simulated_ok is None else f'{max_simulated_ok:.2f} deg/s'}")
