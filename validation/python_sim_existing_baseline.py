"""
python_sim_existing_baseline.py

Runs the PRE-EXISTING control laws already committed in this simulation repo
(not anything I added this session) under the SAME 7deg/s tumble / 180deg
initial sun-pointing-error scenario used throughout this analysis, for a
fair three-way table against the real C firmware and my own added code:

  "Detumbling with MTR"  -> satellite_rotational_dynamics_var_mag_field.
                             detumbling_torque() -- the existing bang-bang
                             B-dot MTR law already in this repo, ideal (no
                             MTR current/dipole saturation modeling beyond
                             its own sign-based M_max clip).
  "Sunpointing with RW"  -> satellite_rotational_dynamics_var_mag_field.
                             _sun_pointing_rw_control_torque() -- the
                             existing SUN_POINTING_RW PD law, ideal (no
                             wheel torque/momentum saturation -- this is the
                             "infinite resources" assumption flagged at the
                             very start of this analysis).

Same fixed B-field, same rigid-body dynamics, same panels-deployed inertia
(satellite_params.py's sat_Ixx/Iyy/Izz) used throughout the "my own code"
runs in this repo, so this baseline is directly comparable to those.
"""
import sys
import types

# satellite_rotational_dynamics_var_mag_field.py transitively imports
# periodic_gain_sun_pointing -> periodic_lqr_design -> satellite_states_visualisation
# -> calculate_eci_position_and_velocity -> pyIGRF, whose PyPI package is missing its
# coefficient data file in this environment (see earlier analysis in this session).
# Neither detumbling_torque() nor _sun_pointing_rw_control_torque() (the two functions
# actually under test here) call into IGRF at all, so a stub satisfies the import
# without needing that file.
_pyigrf_stub = types.ModuleType("pyIGRF")
_pyigrf_stub.igrf_value = lambda *a, **k: (0, 0, 0, 0, 0, 0, 0)
sys.modules["pyIGRF"] = _pyigrf_stub

import numpy as np
import satellite_rotational_dynamics_var_mag_field as srd
import satellite_params as sp
import sun_pointing_rw_saturation_analysis as base

I = np.diag([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])
I_inv = np.linalg.inv(I)

DT = 0.2
T_FINAL = 6000.0
TUMBLE_RATE_DEG_S = 7.0
DETUMBLE_PERAXIS_DEG_S = 2.0
POINTING_DONE_DEG = 5.0

B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])


def rk4(q, omega, tau_fn, dt):
    def deriv(q, omega):
        tau = tau_fn(q, omega)
        domega = I_inv @ (tau - np.cross(omega, I @ omega))
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        return dq, domega

    k1 = deriv(q, omega)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1])
    q_new = q + (dt/6.0)*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    omega_new = omega + (dt/6.0)*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    q_new = q_new/np.linalg.norm(q_new)
    return q_new, omega_new


def run(mode, t_final=T_FINAL):
    q0, sun_dir = base.build_initial_attitude()
    q = q0.copy()
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    n_steps = int(t_final/DT)

    t_hist = np.zeros(n_steps+1)
    w_axes_hist = np.zeros((n_steps+1, 3))
    p_hist = np.zeros(n_steps+1)
    t_detumbled_axis = None
    t_pointed = None

    for k in range(n_steps+1):
        t_hist[k] = k*DT
        w_axes_hist[k, :] = np.degrees(omega)
        p_hist[k] = base.pointing_error_deg(q, sun_dir)

        if t_detumbled_axis is None and np.all(np.abs(w_axes_hist[k, :]) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = k*DT
        if t_pointed is None and t_detumbled_axis is not None and p_hist[k] < POINTING_DONE_DEG:
            t_pointed = k*DT

        if k == n_steps:
            break

        if mode == "MTR_DETUMBLE":
            # detumbling_torque() takes B in ECI and rotates to body internally.
            def tau_fn(q, omega):
                tau, M, _ = srd.detumbling_torque(q, omega, 2.0, B_ECI)
                return tau
        elif mode == "RW_SUNPOINT":
            def tau_fn(q, omega, t=k*DT):
                tau, _ = srd._sun_pointing_rw_control_torque(q, omega, t)
                return tau
        else:
            raise ValueError(mode)

        q, omega = rk4(q, omega, tau_fn, DT)

    return {"t": t_hist, "w_axes_deg_s": w_axes_hist, "p_err_deg": p_hist,
            "t_detumbled_axis": t_detumbled_axis, "t_pointed": t_pointed}


def report(label, r):
    print(f"\n=== {label} (existing Python sim-folder code, ideal/no-saturation actuators) ===")
    if r["t_detumbled_axis"] is not None:
        print(f"  Detumbled (EACH axis < {DETUMBLE_PERAXIS_DEG_S} deg/s) at t = {r['t_detumbled_axis']:.1f} s "
              f"({r['t_detumbled_axis']/60:.2f} min)")
    else:
        print(f"  NOT per-axis-detumbled within {r['t'][-1]:.0f}s")
    if r["t_pointed"] is not None:
        print(f"  Also achieved sun-pointing (<{POINTING_DONE_DEG} deg) at t = {r['t_pointed']:.1f} s "
              f"({r['t_pointed']/60:.2f} min)")
    else:
        print(f"  Sun-pointing NOT achieved within {r['t'][-1]:.0f}s (final pointing error {r['p_err_deg'][-1]:.1f} deg)")
    print(f"  Final body rate per axis: {r['w_axes_deg_s'][-1]} deg/s")
    print(f"  Final pointing error: {r['p_err_deg'][-1]:.2f} deg")


if __name__ == "__main__":
    r1 = run("MTR_DETUMBLE")
    report("Detumbling with MTR", r1)

    r2 = run("RW_SUNPOINT")
    report("Sunpointing with RW", r2)
