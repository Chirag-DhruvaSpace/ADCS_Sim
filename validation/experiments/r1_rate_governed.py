"""
r1_rate_governed.py

PROTOTYPE fix for the R1 stall found this session: the shipped control law
is -Kp*qerr - Kd*bodyRate, both terms active from t=0. Since qerr starts at
~180deg, Kp alone commands near-max torque immediately -- which pins all 4
wheels near their real 6000rpm cap within the first ~60s, LONG before the
attitude has moved appreciably (attitude can only change by integrating the
modest initial rate, which is slow). Once pinned, only whatever wheel margin
remains gets the vehicle the rest of the way -- explains the 9-12deg
permanent limit cycle found from a 2deg/s MTR handoff.

Proposed fix: don't feed the raw (huge) qerr into the torque law at all.
Instead compute a REFERENCE rate from the remaining eigenaxis angle, capped
at OMEGA_MAX and shrinking proportionally as the angle closes (a simple
version of a trapezoidal/triangular slew-rate profile), then run a pure
rate-TRACKING law against that reference:

    theta, axis  = eigenaxis angle/axis of qerr (shortest path)
    omega_ref    = min(OMEGA_MAX, K_RATE * theta) * axis      (body frame)
    torque_body  = -Kd_track * (bodyRate - omega_ref)

Rate and attitude are no longer independent: omega_ref IS how attitude
error enters the loop, but always bounded to whatever rate the wheels can
actually sustain AND later decelerate from -- so the wheels are never asked
for more momentum than the maneuver needs. As theta -> 0, omega_ref -> 0,
and the vehicle settles with (ideally) no residual torque demand pinning
any wheel.

Body torque is passed through the REAL rwTorqueDist() (fw_rw_torque_dist_raw
wrapper -- real wedge geometry, RW_MAX_TORQUE clip, real ALPHA=0.7 LPF) for
full fidelity, then through the same realistic per-wheel-speed cap used
elsewhere this session (accelerate blocked at 6000rpm, deceleration always
available).
"""
import ctypes
import numpy as np
import run_real_c_sunpointing_r1 as r1_mod
import r1_realistic_wheel_cap as rc
import handoff_sweep_v2 as hs

r1_mod.fw.fw_rw_torque_dist_raw.argtypes = [ctypes.POINTER(ctypes.c_double)] * 2
r1_mod.fw.fw_rw_torque_dist_raw.restype = None

RW_MOI = rc.RW_MOI
I_DEPLOYED = r1_mod.PLATFORM_MOI   # [1.13972318, 0.85062737, 1.11385774] kg*m^2, CAD-verified


def eigenaxis_angle(qerr_wxyz):
    q0, q1, q2, q3 = qerr_wxyz
    if q0 < 0:
        q0, q1, q2, q3 = -q0, -q1, -q2, -q3   # shortest path
    q0 = np.clip(q0, -1.0, 1.0)
    theta = 2.0 * np.arccos(q0)
    sin_half = np.sqrt(max(1.0 - q0 * q0, 0.0))
    if sin_half > 1e-8:
        axis = np.array([q1, q2, q3]) / sin_half
    else:
        axis = np.zeros(3)
    return theta, axis


def calc_qerr(qdes_wxyz, qcurr_wxyz):
    # same convention as calcQuatErr(): qerr = conj(qdes)/|qdes|^2 (x) qcurr
    qd = np.array(qdes_wxyz); qc = np.array(qcurr_wxyz)
    qmag = np.dot(qd, qd)
    qdinv = np.array([qd[0], -qd[1], -qd[2], -qd[3]]) / max(qmag, 1e-12)
    w0, x0, y0, z0 = qdinv
    w1, x1, y1, z1 = qc
    return np.array([
        w0*w1 - x0*x1 - y0*y1 - z0*z1,
        w0*x1 + x0*w1 + y0*z1 - z0*y1,
        w0*y1 - x0*z1 + y0*w1 + z0*x1,
        w0*z1 + x0*y1 - y0*x1 + z0*w1,
    ])


def run(omega_mag_seed, omega_max_deg_s, k_rate, kd_track, t_final=6000.0, verbose_every=None):
    r1_mod.fw.fw_init_config()   # resets cmdActValues.RwTorque (the LPF state) to zero
    q0, sun_dir = r1_mod.base.build_initial_attitude()
    q = q0.copy()
    omega = omega_mag_seed * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)
    n_steps = int(t_final / r1_mod.DT)
    t_pointed = None
    peak_rpm = 0.0
    rows = []

    for k in range(n_steps + 1):
        t = k * r1_mod.DT
        p_err = r1_mod.base.pointing_error_deg(q, sun_dir)
        wheel_rpm = (h / RW_MOI) * 60.0 / (2 * np.pi)
        peak_rpm = max(peak_rpm, np.max(np.abs(wheel_rpm)))

        if verbose_every and k % int(verbose_every / r1_mod.DT) == 0:
            rows.append((t, p_err, np.degrees(omega).copy(), wheel_rpm.copy()))

        if p_err < 5.0:
            t_pointed = t
            break
        if k == n_steps:
            break

        qerr = calc_qerr(r1_mod.Q_TARGET_qwxyz, q)
        theta, axis = eigenaxis_angle(qerr)
        theta_deg = np.degrees(theta)
        omega_ref_mag = min(omega_max_deg_s, k_rate * theta_deg)
        omega_ref_deg_s = omega_ref_mag * axis

        rate_err_deg_s = np.degrees(omega) - omega_ref_deg_s
        rate_err_rad_s = np.radians(rate_err_deg_s)
        # Feedforward-cancel the natural gyroscopic coupling (asymmetric I means
        # holding ANY steady body rate off-principal-axis isn't torque-free --
        # without this the wheels drain momentum during the coast phase too,
        # not just the initial slew) -- then pure rate-tracking on top.
        gyro_ff = np.cross(omega, I_DEPLOYED * omega)
        torque_body = gyro_ff - kd_track * rate_err_rad_s

        wtorque_out = r1_mod.c_arr([0.0, 0.0, 0.0, 0.0])
        r1_mod.fw.fw_rw_torque_dist_raw(r1_mod.c_arr(list(torque_body)), wtorque_out)
        u_raw = np.array(wtorque_out)
        u_wheel = rc.clamp_wheel_torque(u_raw, h)

        q, omega, h = r1_mod.rk4_gyrostat(q, omega, h, u_wheel, r1_mod.DT)

    return {"t_pointed": t_pointed, "peak_rpm": peak_rpm, "trace": rows}


if __name__ == "__main__":
    t_mm, omega_mag = hs.run_mm_to_threshold(2.0)
    print(f"MTR phase to <2deg/s: {t_mm:.1f}s ({t_mm/60:.2f}min), residual = {np.degrees(omega_mag):.3f} deg/s\n")

    KD_TRACK = I_DEPLOYED * 0.2   # rate-loop gain: Kd = I * bandwidth, faster than the original 2*zeta*wn*I=0.1*I
    for omega_max, k_rate in [(0.5, 0.02), (0.7, 0.02), (1.0, 0.02), (0.7, 0.01), (0.7, 0.05)]:
        r = run(omega_mag, omega_max, k_rate, KD_TRACK, t_final=6000.0)
        tp = r["t_pointed"]
        status = f"{tp:.1f}s ({tp/60:.2f}min)" if tp else "NOT converged in 6000s"
        print(f"omega_max={omega_max:.1f}deg/s, k_rate={k_rate:.3f}: R1={status}, peak_rpm={r['peak_rpm']:.0f}")
