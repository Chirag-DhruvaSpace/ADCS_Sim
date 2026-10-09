"""
mtr_only_sunpointing_accuracy.py

"Sunpointing with MTR alone" -- time to reach 20deg and 10deg pointing
accuracy, from the same 7deg/s tumble / 180deg initial error scenario used
throughout this analysis. Two sources:

  "python" -- the EXISTING, already-validated periodic_gain_sun_pointing.py
              controller (Floquet-verified periodic-LQR + achievability-
              gated reference governor, K_seq.npy/t_grid.npy), the actual
              MTR-only "SUN_POINTING" mode in this repo's own
              satellite_rotational_dynamics_var_mag_field.py.
  "mine"    -- a new MTR-only PD + B-cross controller of my own design
              (same PD structure used throughout this analysis: tau_cmd =
              -Kp*qerr - Kd*omega, allocated via the standard B-cross law
              dipole = cross(B,tau_cmd)/|B|^2, clipped to +/-2 A*m^2 per
              axis on a 0.1 A*m^2 grid -- same MTR hardware spec used
              throughout this thread). No detumbling-specific machinery --
              pure attitude PD, to isolate pointing-accuracy behavior.
"""
import sys, types
_pyigrf_stub = types.ModuleType("pyIGRF")
_pyigrf_stub.igrf_value = lambda *a, **k: (0, 0, 0, 0, 0, 0, 0)
sys.modules["pyIGRF"] = _pyigrf_stub

import numpy as np
import satellite_params as sp
import sun_pointing_rw_saturation_analysis as base
import periodic_gain_sun_pointing as pgsp
import MTR_allocator as mtr

I = np.diag([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])
I_inv = np.linalg.inv(I)

DT = 0.2
T_FINAL = 6000.0
TUMBLE_RATE_DEG_S = 7.0
B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])

M_MAX = 2.0
M_STEP = 0.1

# My own MTR-only PD gains -- same style/order-of-magnitude reasoning as the
# RW PD controllers in this analysis, but sized for MTR's much smaller torque
# budget (kp*I ~ tau_max/theta_max, same principle periodic_gain_sun_pointing's
# own docstring uses to explain why a naively-large w_n saturates permanently).
W_N = 0.02
ZETA = 1.0
KP = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (W_N ** 2)
KD = 2.0 * ZETA * W_N * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])


def quantize(m):
    return np.clip(np.round(m / M_STEP) * M_STEP, -M_MAX, M_MAX)


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
    return q_new/np.linalg.norm(q_new), omega_new


def run(mode, t_final=T_FINAL):
    q0, sun_dir = base.build_initial_attitude()
    q = q0.copy()
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    n_steps = int(t_final/DT)

    t20 = None
    t10 = None
    p_final = None
    w_final = None

    if mode == "python":
        pgsp.reset_governor(q)
        pgsp._gov["was_active"] = True

    for k in range(n_steps+1):
        t = k*DT
        p_err = base.pointing_error_deg(q, sun_dir)
        if t20 is None and p_err < 20.0:
            t20 = t
        if t10 is None and p_err < 10.0:
            t10 = t
        if k == n_steps:
            p_final = p_err; w_final = np.degrees(omega); break

        Cbi = base.C_bi(q)
        B_body = Cbi.T @ B_ECI

        if mode == "python":
            def tau_fn(q, omega, t=t, B_body=B_body):
                tau, M = pgsp.control_torque(q, omega, B_body, t)
                return tau
            q, omega = rk4(q, omega, tau_fn, DT)
            pgsp.step_governor(DT)
        elif mode == "mine":
            def tau_fn(q, omega, B_body=B_body):
                q_err = base.calc_quat_err(base.Q_TARGET, q)
                e = q_err[1:4]
                tau_cmd = -KP*e - KD*omega
                bmagsq = np.dot(B_body, B_body)
                m_raw = np.cross(B_body, tau_cmd)/bmagsq if bmagsq > 1e-20 else np.zeros(3)
                m_cmd = quantize(m_raw)
                return np.cross(m_cmd, B_body)
            q, omega = rk4(q, omega, tau_fn, DT)
        else:
            raise ValueError(mode)

    return {"t20": t20, "t10": t10, "p_final": p_final, "w_final": w_final}


if __name__ == "__main__":
    for mode, label in [("python", "Python sim folder (periodic_gain_sun_pointing.py, existing/validated)"),
                         ("mine", "My own MTR-only PD + B-cross (new)")]:
        r = run(mode)
        t20_str = "never" if r["t20"] is None else f"{r['t20']:.1f}s ({r['t20']/60:.2f}min)"
        t10_str = "never" if r["t10"] is None else f"{r['t10']:.1f}s ({r['t10']/60:.2f}min)"
        print(f"\n=== {label} ===")
        print(f"  Time to <20deg pointing error: {t20_str}")
        print(f"  Time to <10deg pointing error: {t10_str}")
        print(f"  Final pointing error: {r['p_final']:.2f} deg, final body rate: {r['w_final']} deg/s")
