"""
r1_load_balanced_alloc.py

Option #3: load-aware wheel allocation. The real rwTorqueDist() always uses
a FIXED geometric matrix (TorqDistMat) to split a desired body torque across
the 4 wheels -- it has no notion of current wheel speed at all. The short-
pause-desat test just showed the direct consequence: for this maneuver,
that fixed split routes almost everything through wheels 1&2 (which then
saturate) while 3&4 sit idle with unused capacity the whole time.

Fix tested here: a WEIGHTED pseudo-inverse allocation, re-solved every
cycle from the CURRENT wheel speeds, that makes it costly to keep loading a
wheel that's already close to its cap:

    W[i,i] = 1 + (|h_i| / H_MAX)^4          (blows up as a wheel nears its cap)
    u = W^-1 A^T (A W^-1 A^T)^-1 tau_body   (still delivers tau_body EXACTLY,
                                              A@u == tau_body always -- only
                                              WHICH wheels carry it changes)

No MTR involved at all -- this is purely about spending the wheel cluster's
own redundant degree of freedom better, independent of the desaturation
exploration. Same real Kp/Kd gains + gyroscopic feedforward, CAD-verified
deployed inertia, real per-wheel RW_MAX_TORQUE clip (replicated here since
bypassing the fixed-matrix rwTorqueDist()), and the same realistic 6000rpm
accelerate-only wheel-speed cap used throughout.
"""
import numpy as np
import handoff_sweep_v2 as hs
import r1_realistic_wheel_cap as rc
import run_real_c_sunpointing_r1 as r1_mod

I_DEPLOYED = r1_mod.PLATFORM_MOI
KP = np.array(r1_mod.R1_GAIN_KP)
KD = np.array(r1_mod.R1_GAIN_KD)
RW_MOI = rc.RW_MOI
RW_MAX_TORQUE = 0.0025   # Nm/wheel, real hardware limit (control_defaults.h)
H_MAX = RW_MOI * (6000.0 * 2 * np.pi / 60.0)   # real 6000rpm cap, momentum units

A = r1_mod.A_WHEELS   # 3x4, wheel torque -> body torque (verified geometry)


def calc_qerr(qdes, qcurr):
    qd = np.array(qdes); qc = np.array(qcurr)
    qmag = np.dot(qd, qd)
    qdinv = np.array([qd[0], -qd[1], -qd[2], -qd[3]]) / max(qmag, 1e-12)
    w0, x0, y0, z0 = qdinv; w1, x1, y1, z1 = qc
    return np.array([
        w0*w1 - x0*x1 - y0*y1 - z0*z1,
        w0*x1 + x0*w1 + y0*z1 - z0*y1,
        w0*y1 - x0*z1 + y0*w1 + z0*x1,
        w0*z1 + x0*y1 - y0*x1 + z0*w1,
    ])


def rk4_combined(q, omega, h, wheel_torque, tau_mtr, dt):
    def deriv(q, omega, h):
        H_w = A @ h
        tau_body = A @ wheel_torque + tau_mtr
        domega = r1_mod.I_inv @ (-np.cross(omega, r1_mod.I @ omega + H_w) + tau_body)
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = -wheel_torque.copy()
        return dq, domega, dh
    k1 = deriv(q, omega, h)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1], h + 0.5*dt*k1[2])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1], h + 0.5*dt*k2[2])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1], h + dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    omega_new = omega + (dt/6.0)*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    h_new = h + (dt/6.0)*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
    return q_new/np.linalg.norm(q_new), omega_new, h_new


def weighted_allocate(tau_body, h):
    w = 1.0 + (np.abs(h) / H_MAX) ** 4
    Winv = np.diag(1.0 / w)
    M = A @ Winv @ A.T
    u = Winv @ A.T @ np.linalg.solve(M, tau_body)
    u = np.clip(u, -RW_MAX_TORQUE, RW_MAX_TORQUE)
    return u


def run(omega_mag, t_final=10800.0, checkpoints=None):
    q, sun_dir = r1_mod.base.build_initial_attitude()
    omega = omega_mag * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / r1_mod.DT)
    cps = checkpoints or []
    ci = 0
    for k in range(n_steps + 1):
        t = k * r1_mod.DT
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
        if ci < len(cps) and t >= cps[ci]:
            print(f"  t={t:7.1f}s ({t/60:6.1f}min) p_err={p_err:7.2f}deg wheel_rpm={np.round(wheel_rpm).astype(int)}")
            ci += 1
        if p_err < 5.0:
            return t, wheel_rpm
        if k == n_steps:
            return None, wheel_rpm
        qerr = calc_qerr(r1_mod.Q_TARGET_qwxyz, q)
        torque_body = -KP*qerr[1:4] - KD*omega + np.cross(omega, I_DEPLOYED*omega)
        u_wheel_raw = weighted_allocate(torque_body, h)
        u_wheel = rc.clamp_wheel_torque(u_wheel_raw, h)
        q, omega, h = rk4_combined(q, omega, h, u_wheel, np.zeros(3), r1_mod.DT)


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min)\n")
    cps = [0, 60, 120, 300, 600, 900, 1200, 1800, 2400, 3600, 5400, 7200, 9000, 10800]
    tp, wheel_rpm = run(omega_mag, t_final=10800.0, checkpoints=cps)
    print()
    if tp:
        print(f"CONVERGED: R1={tp:.1f}s ({tp/60:.2f}min), total(MTR+R1)={(t_mm+tp)/60:.2f}min")
    else:
        print(f"NOT converged in 10800s (3hr)")
    print(f"Final wheel rpm: {np.round(wheel_rpm).astype(int)}")
