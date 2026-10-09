"""
sun_pointing_rw_saturation_analysis.py

Pure-Python simulation of the real SunPointing_R1 (RW-based sun-pointing)
control law under REAL finite wheel resources, superseding an earlier
version of this file that predated several corrections made against the
actual flight firmware:

  - SIGN CONVENTION: the old version applied wheel reaction torque as
    -A@u (a "motor torque on wheel" gyrostat convention) with dh/dt=+u.
    Verified against the real firmware (A_WHEELS @ TorqDistMat == I_3
    exactly) that this is backwards for how rwTorqueDist() actually
    works: the body feels +A_WHEELS@wheelTorque_out DIRECTLY, so by
    Newton's third law the wheels' own momentum moves as
    dh/dt = -wheelTorque_out. Fixed here.
  - INERTIA: the old version used satellite_params.py's design-stage
    ESTIMATE. Replaced with the CAD-verified (real mass-properties
    output) deployed (panels-open) inertia, since SunPointing_R1 only
    ever runs post-deployment: Ixx=1.13972318, Iyy=0.85062737,
    Izz=1.11385774 kg*m^2 (off-diagonal terms <1.2% of diagonal,
    treated as negligible, consistent with the rest of this analysis).
  - GAINS: the old version used a from-scratch Kp/Kd design. Replaced
    with the actual gains now shipped in the real firmware
    (control_defaults.h DEFAULT_SUNPT_R1_GAIN_KP/KD_X/Y/Z), derived via
    Kp=I*wn^2, Kd=2*zeta*wn*I with wn=0.05, zeta=1.0 against the
    CAD-verified inertia above.
  - UNITS: the real control law reads AdsMdl.bodyRate in DEGREES/s (the
    real gyro driver's units) and explicitly converts via DEG_TO_RAD
    before multiplying by Kd (a real firmware bug found and fixed this
    session -- Kd was sized for rad/s). Reproduced here.
  - WHEEL GEOMETRY: TorqDistMat/A_WHEELS now use the real 55deg wedge
    angle and real 0/90/180/270deg wheel azimuths, matching
    control_defaults.h/task_defs.c exactly (not a generic tetrahedral
    approximation).
  - WHEEL-SPEED CAP: the old version tracked wheel momentum against an
    ad hoc "cluster storage budget" with no per-wheel speed limit at
    all. Real wheels have a physical maximum speed (6000rpm, datasheet
    rating) -- modeled here as a per-wheel, direction-aware clamp: once
    a wheel reaches that speed, commanded torque that would accelerate
    it FURTHER in the same direction is blocked (a real motor can't
    exceed its rated speed), but deceleration is always available. This
    is NOT itself checked anywhere in the real SunPointing_R1 firmware
    code (only Detumbling_RG's rwSaturated() checks wheel speed, and
    that's a Safe-Mode trip, not a torque limiter) -- it's a physical
    reality of the actuator that any correct simulation must still
    respect.

Findings reproduced by this corrected model (see this session's full
analysis for the complete picture): DEFAULT_DETUMBLING_EXIT_THRESH is
2.0deg/s (control_defaults.h), gating state_machine.c's
stillTumbling = (AdsMdl.Wmag >= threshold) -- Wmag = utilsMod(bodyRate),
the VECTOR MAGNITUDE of body rate, NOT each axis checked separately. An
earlier pass of this analysis mistakenly tested "each axis < threshold"
in the Python harness, which is a strictly EASIER condition to satisfy
than the real Wmag check (Wmag < X implies every axis < X, not the
reverse) and left ~3.0deg/s of residual momentum at handoff instead of
the ~2.0deg/s the real firmware actually produces -- that mismatch is
what made a full ~180deg correction from this handoff look marginal
earlier. Re-verified against the REAL Wmag-based condition: handoff to
SunPointing_R1 at Wmag=2.0deg/s converges in 15/15 tested tumble
directions, ~29-36min total (MTR+R1) -- see this file's __main__ block.
Peak wheel speed sits right at the real 6000rpm rating in most of those
(not a comfortable margin below it), so this works but is worth
re-checking against tighter torque/gain tolerances before calling it
final flight config.
"""
import numpy as np
from datetime import datetime, timezone

import sun_pointing_rw_z as sprz

EPOCH_UTC = datetime(2026, 10, 1, 15, 0, 0, tzinfo=timezone.utc)

# ---- CAD-verified deployed (panels-open) inertia, kg*m^2 ----
PLATFORM_MOI = np.array([1.13972318, 0.85062737, 1.11385774])
I = np.diag(PLATFORM_MOI)
I_INV = np.linalg.inv(I)

# ---- Real firmware gains (control_defaults.h DEFAULT_SUNPT_R1_GAIN_KP/KD) ----
KP = np.array([0.002849, 0.002127, 0.002785])
KD = np.array([0.113972, 0.085063, 0.111386])
DEG_TO_RAD = 0.01745329251

# ---- Real wheel/actuator constants (control_defaults.h / control_laws.c) ----
RW_MOI = 5.4e-5              # kg*m^2, per-wheel rotor inertia
RW_MAX_TORQUE = 0.0025       # N*m, per-wheel real hardware/firmware limit
RW_WEDGE_ANGLE_DEG = 55.0    # real wheel-cant angle
WHEEL_MAX_RPM = 6000.0       # real hardware max mechanical speed (datasheet rating)
_H_MAX = RW_MOI * (WHEEL_MAX_RPM * 2 * np.pi / 60.0)

_c = np.cos(np.radians(RW_WEDGE_ANGLE_DEG))
_s = np.sin(np.radians(RW_WEDGE_ANGLE_DEG))
# Wheel torque -> body torque (real geometry, verified A_WHEELS @ TorqDistMat == I_3)
A_WHEELS = np.array([
    [_c, 0.0, -_c, 0.0],
    [0.0, _c, 0.0, -_c],
    [_s, _s, _s, _s],
])
# Body torque -> wheel torque (real TorqDistMat, task_defs.c Pars_init())
TORQ_DIST_MAT = np.array([
    [1.0/(2*_c), 0.0, 1.0/(4*_s)],
    [0.0, 1.0/(2*_c), 1.0/(4*_s)],
    [-1.0/(2*_c), 0.0, 1.0/(4*_s)],
    [0.0, -1.0/(2*_c), 1.0/(4*_s)],
])

TUMBLE_RATE_DEG_S = 7.0
DT = 0.2          # s, matches the real 5Hz TIM6 control loop
T_FINAL = 6000.0  # s

Q_TARGET = np.asarray(sprz.sun_pointing_rw_z_quaternion(EPOCH_UTC), dtype=float)
Q_TARGET /= np.linalg.norm(Q_TARGET)


def C_bi(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2 + q3**2), 2*(q1*q2 + q0*q3), 2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3), 1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2), 2*(q2*q3 - q0*q1), 1 - 2*(q1**2 + q2**2)],
    ])


def calc_quat_err(q_des, q_cur):
    """qerr = conj(q_des)/|q_des|^2 (x) q_cur -- real calcQuatErr() convention."""
    qmag = np.dot(q_des, q_des)
    qd_inv = np.array([q_des[0], -q_des[1], -q_des[2], -q_des[3]]) / max(qmag, 1e-12)
    w0, x0, y0, z0 = qd_inv
    w1, x1, y1, z1 = q_cur
    return np.array([
        w0*w1 - x0*x1 - y0*y1 - z0*z1,
        w0*x1 + x0*w1 + y0*z1 - z0*y1,
        w0*y1 - x0*z1 + y0*w1 + z0*x1,
        w0*z1 + x0*y1 - y0*x1 + z0*w1,
    ])


def build_initial_attitude():
    """Body -Z starts out pointed directly AWAY from the Sun (180deg worst case)."""
    Cbi_target = C_bi(Q_TARGET)
    sun_eci_dir = Cbi_target @ np.array([0.0, 0.0, -1.0])

    R_180x = np.diag([1.0, -1.0, -1.0])
    Cbi_init = Cbi_target @ R_180x

    from scipy.spatial.transform import Rotation
    q_xyzw = Rotation.from_matrix(Cbi_init.T).as_quat()
    q_init = np.array([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]])
    q_init /= np.linalg.norm(q_init)

    body_minus_z_eci = C_bi(q_init) @ np.array([0.0, 0.0, -1.0])
    err_deg = np.degrees(np.arccos(np.clip(np.dot(body_minus_z_eci, sun_eci_dir), -1, 1)))
    assert abs(err_deg - 180.0) < 1e-6, f"initial pointing error is {err_deg} deg, expected 180"
    return q_init, sun_eci_dir


def pointing_error_deg(q, sun_eci_dir):
    Cbi = C_bi(q)
    body_minus_z_eci = Cbi @ np.array([0.0, 0.0, -1.0])
    return np.degrees(np.arccos(np.clip(np.dot(body_minus_z_eci, sun_eci_dir), -1, 1)))


def r1_control_torque(q, omega_body_rad_s):
    """Real SunPointing_R1 law: -Kp*qerr - Kd*(bodyRate_deg_s * DEG_TO_RAD).
    bodyRate is real-hardware degrees/s; Kd was sized for rad/s (the
    DEG_TO_RAD fix applied to the real firmware this session)."""
    qerr = calc_quat_err(Q_TARGET, q)
    bodyrate_deg_s = np.degrees(omega_body_rad_s)
    return -KP*qerr[1:4] - KD*(bodyrate_deg_s * DEG_TO_RAD)


def allocate_wheel_torque(tau_body, prev_wheel_cmd, alpha=0.7):
    """Real rwTorqueDist(): fixed-geometry allocation, per-wheel RW_MAX_TORQUE
    clip, then the real ALPHA=0.7 low-pass filter on the commanded torque."""
    u_raw = TORQ_DIST_MAT @ tau_body
    u_clipped = np.clip(u_raw, -RW_MAX_TORQUE, RW_MAX_TORQUE)
    return alpha*u_clipped + (1-alpha)*prev_wheel_cmd


def clamp_wheel_speed_cap(wheel_torque, h):
    """Physical reality not itself checked in the real SunPointing_R1 code:
    a wheel motor can't be commanded to accelerate further once at its real
    max speed, but can always decelerate. Per-wheel, direction-aware."""
    wt = wheel_torque.copy()
    for i in range(4):
        if abs(h[i]) >= _H_MAX:
            accelerating_further = (np.sign(wt[i]) != np.sign(h[i])) and wt[i] != 0.0
            if accelerating_further:
                wt[i] = 0.0
    return wt


def rk4_step(q, omega, h, wheel_torque, dt):
    def deriv(q, omega, h):
        H_w = A_WHEELS @ h
        tau_body = A_WHEELS @ wheel_torque   # real convention: body feels +A@u directly
        domega = I_INV @ (-np.cross(omega, I @ omega + H_w) + tau_body)
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = -wheel_torque.copy()            # Newton's third law reaction on the wheels themselves
        return dq, domega, dh
    k1 = deriv(q, omega, h)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1], h + 0.5*dt*k1[2])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1], h + 0.5*dt*k2[2])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1], h + dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    omega_new = omega + (dt/6.0)*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    h_new = h + (dt/6.0)*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
    return q_new/np.linalg.norm(q_new), omega_new, h_new


def run(q0, sun_eci_dir, omega0_rad_s, t_final=T_FINAL, pointing_done_deg=5.0):
    q = q0.copy()
    omega = omega0_rad_s.copy()
    h = np.zeros(4)
    prev_wheel_cmd = np.zeros(4)

    n_steps = int(t_final/DT)
    t_hist = np.zeros(n_steps+1)
    w_hist = np.zeros((n_steps+1, 3))
    p_hist = np.zeros(n_steps+1)
    wheel_rpm_hist = np.zeros((n_steps+1, 4))
    wheel_torque_hist = np.zeros((n_steps+1, 4))
    qerr_hist = np.zeros((n_steps+1, 4))
    t_pointed = None

    for k in range(n_steps+1):
        t_hist[k] = k*DT
        w_hist[k, :] = np.degrees(omega)
        p_hist[k] = pointing_error_deg(q, sun_eci_dir)
        wheel_rpm_hist[k, :] = (h/RW_MOI)*60.0/(2*np.pi)
        qerr_hist[k, :] = calc_quat_err(Q_TARGET, q)

        if t_pointed is None and p_hist[k] < pointing_done_deg:
            t_pointed = t_hist[k]
            t_hist, w_hist, p_hist, wheel_rpm_hist, wheel_torque_hist, qerr_hist = (
                t_hist[:k+1], w_hist[:k+1], p_hist[:k+1], wheel_rpm_hist[:k+1], wheel_torque_hist[:k+1], qerr_hist[:k+1])
            break
        if k == n_steps:
            break

        tau_body = r1_control_torque(q, omega)
        prev_wheel_cmd = allocate_wheel_torque(tau_body, prev_wheel_cmd)
        u_wheel = clamp_wheel_speed_cap(prev_wheel_cmd, h)
        wheel_torque_hist[k, :] = u_wheel
        q, omega, h = rk4_step(q, omega, h, u_wheel, DT)

    return {
        "t": t_hist, "w_deg_s": w_hist, "p_err_deg": p_hist, "wheel_rpm": wheel_rpm_hist,
        "wheel_torque": wheel_torque_hist, "qerr": qerr_hist, "t_pointed": t_pointed,
    }


def print_table(result, checkpoints_s, t_mtr_offset_s=0.0, title=None):
    """Prints the per-axis-body-rate table format used throughout this
    session's analysis: R1-elapsed / total-elapsed / pointing error / wx,wy,wz.
    t_mtr_offset_s is the separate MTR-detumbling phase's duration (computed
    elsewhere, e.g. bdot_realistic_detumbling.py or handoff_sweep_v2.py's
    run_mm_to_threshold()) -- this file only simulates the RW/R1 phase, so the
    "total" column needs that number supplied by the caller; it defaults to 0
    (R1-only elapsed time) if not given."""
    if title:
        print(f"\n{title}")
    if t_mtr_offset_s:
        print(f"(MTR phase assumed: {t_mtr_offset_s:.1f}s / {t_mtr_offset_s/60:.2f}min, from a separate detumbling run)")
    print(f"{'R1(min)':>8} | {'Total(min)':>10} | {'p_err(deg)':>10} | {'wx(deg/s)':>10} | {'wy(deg/s)':>10} | {'wz(deg/s)':>10}")

    t_hist = result["t"]

    def print_row(idx, suffix=""):
        t = t_hist[idx]
        p = result["p_err_deg"][idx]
        w = result["w_deg_s"][idx]
        print(f"{t/60:>8.2f} | {(t_mtr_offset_s+t)/60:>10.2f} | {p:>10.2f} | {w[0]:>10.4f} | {w[1]:>10.4f} | {w[2]:>10.4f}{suffix}")

    idx = 0
    last_idx_printed = None
    for target_t in checkpoints_s:
        while idx < len(t_hist) - 1 and t_hist[idx] < target_t:
            idx += 1
        if t_hist[idx] < target_t - DT:
            break   # checkpoint is past the end of a run that already stopped
        print_row(idx)
        last_idx_printed = idx

    if result["t_pointed"] is not None and last_idx_printed != len(t_hist) - 1:
        print_row(len(t_hist) - 1, suffix="  <-- converged")


def summarize(name, result):
    tp = result["t_pointed"]
    print(f"\n=== {name} ===")
    if tp is not None:
        print(f"  Sun-pointing achieved (<5deg): {tp:.1f}s ({tp/60:.2f}min)")
    else:
        print(f"  NOT achieved within {result['t'][-1]:.0f}s (final error {result['p_err_deg'][-1]:.2f}deg)")
    print(f"  Peak wheel speed: {np.max(np.abs(result['wheel_rpm'])):.0f} rpm (real cap: {WHEEL_MAX_RPM:.0f} rpm)")
    print(f"  Final body rate: {result['w_deg_s'][-1]} deg/s")


if __name__ == "__main__":
    print(f"Deployed (panels-open) inertia, CAD-verified: {PLATFORM_MOI} kg*m^2")
    print(f"Real R1 gains: Kp={KP}, Kd={KD}")
    print(f"Real wheel limits: {RW_MAX_TORQUE*1e3:.1f}mN*m/wheel, {WHEEL_MAX_RPM:.0f}rpm max speed\n")

    q0, sun_eci_dir = build_initial_attitude()

    # Scenario A: CURRENT SHIPPED VALUE -- DEFAULT_DETUMBLING_EXIT_THRESH =
    # 2.0deg/s (control_defaults.h), gating the REAL condition
    # (state_machine.c: stillTumbling = AdsMdl.Wmag >= threshold, where Wmag
    # is the VECTOR MAGNITUDE of body rate, not each axis separately). The
    # residual magnitude below (2.0deg/s exactly) is what that real Wmag<2.0
    # condition actually produces -- confirmed against 15 different tumble
    # directions via the real B-dot MTR simulation (run_real_c_detumbling.py),
    # all converging; this symmetric-axis case is one representative example,
    # MTR phase duration 30.21min for this specific direction (varies
    # ~22.6-30.7min across the 15 tested; residual direction isn't something
    # a passive B-dot detumble controls).
    omega0_A = np.radians(2.0) * np.array([1, 1, 1]) / np.sqrt(3)
    result_A = run(q0.copy(), sun_eci_dir, omega0_A, t_final=10800.0)
    summarize("Scenario A: 2.0deg/s Wmag handoff (current shipped value)", result_A)
    print_table(result_A, checkpoints_s=[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330],
                t_mtr_offset_s=1812.8, title="Per-axis body rate table, Scenario A:")

    # Scenario B: 0.7deg/s -- briefly the shipped value earlier the same day
    # this was investigated, before the Wmag-vs-each-axis methodology error
    # was found and corrected. Kept here as a slower-but-still-safe reference
    # point, not the current default.
    omega0_B = np.radians(0.7) * np.array([1, 1, 1]) / np.sqrt(3)
    result_B = run(q0.copy(), sun_eci_dir, omega0_B, t_final=10800.0)
    summarize("Scenario B: 0.7deg/s Wmag handoff (prior value, kept as reference)", result_B)
    print_table(result_B, checkpoints_s=[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300],
                t_mtr_offset_s=2145.0, title="Per-axis body rate table, Scenario B:")
