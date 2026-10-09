"""
r1_staged_hops.py

Test #2 from the "what else can we try" list: split the 180deg correction
into four ~45deg hops along the known eigenaxis (the same body-X axis
build_initial_attitude() uses to construct the 180deg start), with a
pause-and-desaturate break between each hop -- instead of one continuous
180deg push that exhausts the whole wheel momentum budget in one go.

Per hop: run the existing PD law (+ gyroscopic feedforward, kept per
instruction) targeting the hop's intermediate quaternion, using the real
Kp/Kd gains, until EITHER the hop's own attitude error is small OR any
wheel gets close to its real cap -- whichever comes first. Then pause RW
(hold near-zero torque) and run the REAL desaturationCalcTorq() for up to
a capped duration, using the REAL checkDesat()/rwTorqueDist() functions via
the fw_pause_and_desat_raw wrapper built for the previous (single-pause)
test. Move to the next hop regardless of how much the pause actually
achieved (the null-space blindness found in that test means it may not
fully clear wheels -- tracked and reported, not hidden).

Real wedge/torque-distribution geometry, real DEG_TO_RAD-fixed law, CAD-
verified deployed inertia, and the same realistic per-wheel 6000rpm
accelerate-only cap used throughout this session.
"""
import ctypes
import numpy as np
import handoff_sweep_v2 as hs
import r1_realistic_wheel_cap as rc
import run_real_c_sunpointing_r1 as r1_mod

r1_mod.fw.fw_pause_and_desat_raw.argtypes = [ctypes.POINTER(ctypes.c_double)]*5 + [ctypes.POINTER(ctypes.c_int)]
r1_mod.fw.fw_pause_and_desat_raw.restype = None
r1_mod.fw.fw_desat_step_raw.argtypes = [ctypes.POINTER(ctypes.c_double)]*3 + [ctypes.POINTER(ctypes.c_int)]
r1_mod.fw.fw_desat_step_raw.restype = None
r1_mod.fw.fw_rw_torque_dist_raw.argtypes = [ctypes.POINTER(ctypes.c_double)]*2
r1_mod.fw.fw_rw_torque_dist_raw.restype = None

I_DEPLOYED = r1_mod.PLATFORM_MOI
KP = np.array(r1_mod.R1_GAIN_KP)
KD = np.array(r1_mod.R1_GAIN_KD)
B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])
RW_MOI = rc.RW_MOI

WHEEL_CAUTION_RPM = 5500.0   # pause the hop and desat if any wheel gets this close to the real 6000rpm cap
DESAT_MAX_DURATION_S = 1200.0   # cap each desat pause at 20min so a null-space-blind stall doesn't loop forever
HOP_ANGLE_DEG = 45.0
N_HOPS = 4


def rx(theta_rad):
    c, s = np.cos(theta_rad), np.sin(theta_rad)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def build_hop_targets():
    from scipy.spatial.transform import Rotation
    Cbi_target = r1_mod.base.C_bi(r1_mod.Q_TARGET_qwxyz)
    targets = []
    for remaining_deg in [180 - HOP_ANGLE_DEG * k for k in range(1, N_HOPS + 1)]:
        Cbi_stage = Cbi_target @ rx(np.radians(remaining_deg))
        q_xyzw = Rotation.from_matrix(Cbi_stage.T).as_quat()
        q_stage = np.array([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]])
        q_stage /= np.linalg.norm(q_stage)
        targets.append(q_stage)
    return targets


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


def quat_angle_deg(qerr):
    q0 = np.clip(qerr[0], -1.0, 1.0)
    return np.degrees(2.0 * np.arccos(abs(q0)))


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


RATE_HOLD_KD = KD   # same Kd used for the gentle rate-only hold during pauses -- no Kp term at all


def step_active(q, omega, h):
    """One 5Hz tick, pure RW PD+feedforward toward the CURRENT stage target. No MTR at all --
    matches the original (non-hop) approach used everywhere else this session."""
    qerr = calc_qerr(current_target[0], q)
    torque_body = -KP*qerr[1:4] - KD*omega + np.cross(omega, I_DEPLOYED*omega)
    wtorque_out = r1_mod.c_arr([0.0]*4)
    r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr(list(torque_body)), wtorque_out)
    u_wheel = rc.clamp_wheel_torque(np.array(wtorque_out), h)
    return rk4_combined(q, omega, h, u_wheel, np.zeros(3), r1_mod.DT)


def step_desat(q, omega, h):
    """One 5Hz tick: RW runs a GENTLE rate-damping-ONLY hold (no Kp/attitude term -- just
    -Kd*omega + gyro feedforward, so it doesn't fight MTR's disturbance the way the full
    aggressive PD did) CONCURRENTLY with the real MTR desaturation. The active reaction to
    MTR's push is what actually unloads wheel momentum -- a true zero-torque pause can't,
    since nothing but a wheel's own motor torque changes its speed."""
    Cbi = r1_mod.base.C_bi(q)
    B_body = Cbi.T @ B_ECI
    wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)

    dipole_out = r1_mod.c_arr([0.0, 0.0, 0.0])
    desat_flag = ctypes.c_int(0)
    r1_mod.fw.fw_desat_step_raw(r1_mod.c_arr(list(B_body*1e6)), r1_mod.c_arr(list(wheel_rpm)),
                                 dipole_out, ctypes.byref(desat_flag))

    torque_body = -RATE_HOLD_KD*omega + np.cross(omega, I_DEPLOYED*omega)
    wtorque_out = r1_mod.c_arr([0.0]*4)
    r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr(list(torque_body)), wtorque_out)
    u_wheel = rc.clamp_wheel_torque(np.array(wtorque_out), h)

    dipole = np.array(dipole_out)
    tau_mtr = np.cross(dipole, B_body) if desat_flag.value == 1 else np.zeros(3)
    return rk4_combined(q, omega, h, u_wheel, tau_mtr, r1_mod.DT), desat_flag.value


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min)\n")

    r1_mod.fw.fw_init_config()
    q0, sun_dir = r1_mod.base.build_initial_attitude()
    q = q0.copy()
    omega = omega_mag * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)

    hop_targets = build_hop_targets()
    t_total = 0.0
    log = []

    for hop_idx, target in enumerate(hop_targets, start=1):
        current_target = (target,)
        t_hop_start = t_total
        stage_done = False
        wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
        print(f"--- Hop {hop_idx}/{N_HOPS}: target = {180 - HOP_ANGLE_DEG*hop_idx:.0f}deg remaining from original ---")
        n_steps = int(3600.0 / r1_mod.DT)   # cap each active phase at 1hr
        for k in range(n_steps + 1):
            qerr = calc_qerr(target, q)
            stage_err_deg = quat_angle_deg(qerr)
            wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
            p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
            if k % int(60/r1_mod.DT) == 0:
                log.append((t_total, f"hop{hop_idx}-active", stage_err_deg, p_err, wheel_rpm.copy()))
            if stage_err_deg < 3.0 or np.max(np.abs(wheel_rpm)) >= WHEEL_CAUTION_RPM:
                reason = "reached stage target" if stage_err_deg < 3.0 else "wheel caution threshold"
                print(f"  active phase ended at t={t_total:.1f}s ({reason}), stage_err={stage_err_deg:.2f}deg, "
                      f"p_err={p_err:.2f}deg, wheel_rpm={np.round(wheel_rpm).astype(int)}")
                break
            q, omega, h = step_active(q, omega, h)
            t_total += r1_mod.DT
        else:
            print(f"  active phase TIMED OUT (1hr) at t={t_total:.1f}s, stage_err={stage_err_deg:.2f}deg")

        # desat pause
        t_desat_start = t_total
        n_desat_steps = int(DESAT_MAX_DURATION_S / r1_mod.DT)
        for k in range(n_desat_steps + 1):
            wheel_rpm = (h/RW_MOI)*60.0/(2*np.pi)
            if k % int(60/r1_mod.DT) == 0:
                p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
                log.append((t_total, f"hop{hop_idx}-desat", None, p_err, wheel_rpm.copy()))
            if np.max(np.abs(wheel_rpm)) < 1000.0 or k == n_desat_steps:
                print(f"  desat pause ended at t={t_total:.1f}s ({'all wheels <1000rpm' if k<n_desat_steps else 'timed out'}), "
                      f"wheel_rpm={np.round(wheel_rpm).astype(int)}")
                break
            (q, omega, h), _ = step_desat(q, omega, h)
            t_total += r1_mod.DT

    p_err_final = r1_mod.base.pointing_error_deg(q, sun_dir)
    wheel_rpm_final = (h/RW_MOI)*60.0/(2*np.pi)
    print(f"\nAfter all {N_HOPS} hops: t_total={t_total:.1f}s ({t_total/60:.2f}min R1), "
          f"total(MTR+R1)={(t_mm+t_total)/60:.2f}min")
    print(f"Final pointing error: {p_err_final:.2f}deg, final wheel rpm: {np.round(wheel_rpm_final).astype(int)}")
