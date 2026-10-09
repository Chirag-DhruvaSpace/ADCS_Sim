"""
r1_short_pause_desat.py

Latest iteration in the MTR-assisted-desaturation exploration. Prior attempts:
  - Concurrent, full aggressive PD + desat: backfires (RW fights MTR).
  - True zero-torque pause, 20min cap: doesn't destabilize, but the body
    drifts uncontrolled the whole pause (Newton's first law, nothing holding
    it) -- 4-hop test wandered 100-160deg instead of converging.
  - Concurrent, GENTLE rate-only hold + desat: verified UNSTABLE -- wheels
    seeded at an identical 5500rpm diverged apart within 40s regardless of
    DesatGain's sign, so it's a real feedback instability, not a sign bug.

This test: true zero-torque pause (the only variant that doesn't actively
destabilize), but SHORT -- 90s instead of 20min -- so drift stays bounded
(drift scales with pause duration x residual rate). Triggered repeatedly
(pause, resume, pause again) rather than attempted once, targeting the REAL
final Q_TARGET continuously (no intermediate hops -- that added its own
confound last time).

Real wedge geometry, real DEG_TO_RAD-fixed law + gyroscopic feedforward
(kept per instruction), CAD-verified deployed inertia, realistic per-wheel
6000rpm accelerate-only cap, real checkDesat()/desaturationCalcTorq()
hysteresis and B-cross MTR allocation.
"""
import ctypes
import numpy as np
import handoff_sweep_v2 as hs
import r1_realistic_wheel_cap as rc
import run_real_c_sunpointing_r1 as r1_mod

r1_mod.fw.fw_desat_step_raw.argtypes = [ctypes.POINTER(ctypes.c_double)]*3 + [ctypes.POINTER(ctypes.c_int)]
r1_mod.fw.fw_desat_step_raw.restype = None
r1_mod.fw.fw_rw_torque_dist_raw.argtypes = [ctypes.POINTER(ctypes.c_double)]*2
r1_mod.fw.fw_rw_torque_dist_raw.restype = None

I_DEPLOYED = r1_mod.PLATFORM_MOI
KP = np.array(r1_mod.R1_GAIN_KP)
KD = np.array(r1_mod.R1_GAIN_KD)
B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])
RW_MOI = rc.RW_MOI

WHEEL_CAUTION_RPM = 5500.0
PAUSE_DURATION_S = 90.0
MAX_TOTAL_S = 10800.0   # 3hr safety cap
MAX_CYCLES = 300


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
    A = r1_mod.A_WHEELS
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


def step_active(q, omega, h):
    qerr = calc_qerr(r1_mod.Q_TARGET_qwxyz, q)
    torque_body = -KP*qerr[1:4] - KD*omega + np.cross(omega, I_DEPLOYED*omega)
    wtorque_out = r1_mod.c_arr([0.0]*4)
    r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr(list(torque_body)), wtorque_out)
    u_wheel = rc.clamp_wheel_torque(np.array(wtorque_out), h)
    return rk4_combined(q, omega, h, u_wheel, np.zeros(3), r1_mod.DT)


def step_pause(q, omega, h):
    """True zero RW torque; MTR desaturates if desatFlag is active."""
    Cbi = r1_mod.base.C_bi(q)
    B_body = Cbi.T @ B_ECI
    wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
    dipole_out = r1_mod.c_arr([0.0, 0.0, 0.0])
    desat_flag = ctypes.c_int(0)
    r1_mod.fw.fw_desat_step_raw(r1_mod.c_arr(list(B_body*1e6)), r1_mod.c_arr(list(wheel_rpm)),
                                 dipole_out, ctypes.byref(desat_flag))
    wtorque_out = r1_mod.c_arr([0.0]*4)
    r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr([0.0, 0.0, 0.0]), wtorque_out)
    u_wheel = rc.clamp_wheel_torque(np.array(wtorque_out), h)
    dipole = np.array(dipole_out)
    tau_mtr = np.cross(dipole, B_body) if desat_flag.value == 1 else np.zeros(3)
    return rk4_combined(q, omega, h, u_wheel, tau_mtr, r1_mod.DT)


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min)\n")

    r1_mod.fw.fw_init_config()
    q, sun_dir = r1_mod.base.build_initial_attitude()
    omega = omega_mag * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)

    t_total = 0.0
    n_pauses = 0
    converged = False

    for cycle in range(MAX_CYCLES):
        # active phase, until wheel caution or convergence
        n_steps = int((MAX_TOTAL_S - t_total) / r1_mod.DT)
        for k in range(n_steps + 1):
            p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
            wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
            if p_err < 5.0:
                converged = True
                break
            if np.max(np.abs(wheel_rpm)) >= WHEEL_CAUTION_RPM or t_total >= MAX_TOTAL_S:
                break
            q, omega, h = step_active(q, omega, h)
            t_total += r1_mod.DT
        if converged or t_total >= MAX_TOTAL_S:
            break

        # short zero-torque pause
        n_pauses += 1
        wheel_rpm_before = (h/RW_MOI)*60.0/(2*np.pi)
        n_pause_steps = int(PAUSE_DURATION_S / r1_mod.DT)
        for k in range(n_pause_steps + 1):
            if t_total >= MAX_TOTAL_S:
                break
            q, omega, h = step_pause(q, omega, h)
            t_total += r1_mod.DT
        wheel_rpm_after = (h/RW_MOI)*60.0/(2*np.pi)
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        if n_pauses <= 20 or n_pauses % 10 == 0:
            print(f"  pause #{n_pauses:3d} @ t={t_total:7.1f}s ({t_total/60:6.1f}min): p_err={p_err:6.1f}deg, "
                  f"wheel_rpm before={np.round(wheel_rpm_before).astype(int)} -> after={np.round(wheel_rpm_after).astype(int)}")

    p_err_final = r1_mod.base.pointing_error_deg(q, sun_dir)
    wheel_rpm_final = (h/RW_MOI)*60.0/(2*np.pi)
    print(f"\n{'CONVERGED' if converged else 'DID NOT CONVERGE'} after {n_pauses} pauses, t_total={t_total:.1f}s ({t_total/60:.2f}min R1)")
    if converged:
        print(f"Total (MTR+R1): {(t_mm+t_total)/60:.2f}min")
    print(f"Final pointing error: {p_err_final:.2f}deg, final wheel rpm: {np.round(wheel_rpm_final).astype(int)}")
