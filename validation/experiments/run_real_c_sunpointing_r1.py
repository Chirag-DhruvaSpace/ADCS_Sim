"""
run_real_c_sunpointing_r1.py

Drives the REAL compiled SunPointing_R1 control law (calculate_sun_pt_r1_torque()
+ actuate_sun_pt_r1_torque(), sun_pointing_r1_control.c, copied verbatim into
fw_driver.c) through the same 7deg/s tumble / 180deg initial sun-pointing-error
rigid-body scenario used throughout this analysis.

qdes (the target quaternion) is computed here in Python, reusing the same
body -Z -> Sun target (sun_pointing_rw_z.py's Q_TARGET) already validated
elsewhere in this analysis, rather than porting calcSunPtR1Frame()'s
Guidance-layer target-selection geometry into C -- that function only
builds the target frame (pure geometry, not a control law), and produces
the SAME body -Z -> Sun target this repo already uses. calcQuatErr() and
calculate_sun_pt_r1_torque()/actuate_sun_pt_r1_torque() (the actual control
law under test) run through the REAL compiled C code unchanged.

Real gains used (task_defs.c Pars_init() defaults, confirmed via source
read): Kp=0.0023, Kd=0.0001 per axis (DEFAULT_FINE_HOLD_GAIN_KP/KD -- R1 has
no dedicated gain default of its own, it reuses the fine-hold-mode ones).
Real wheel torque/geometry limits apply (RW_MAX_TORQUE=2.5mN*m/wheel, real
wedge=55deg TorqDistMat geometry) via rwTorqueDist(), same as the other real-C
tests in this analysis. rwTorqueCheckSlew() -- a real anti-windup guard that
zeroes the commanded torque entirely whenever Wmag>=2deg/s (DEFAULT_
DETUMBLING_EXIT_THRESH, since SUN_POINTING_R1 runs under AdcsMode_Sunpoint)
AND the commanded torque would accelerate the body further -- is included
via the real compiled function, unlike this repo's own Python SUN_POINTING_RW
controller.
"""
import ctypes
import numpy as np

import sun_pointing_rw_saturation_analysis as base
import reaction_wheel_model as rwm

DLL_PATH = (r"C:\Users\KRISHN~1\AppData\Local\Temp\claude\D--Dhruva-Space-firmware-"
            r"ADCS-Leap-2-ADCS-Firmware-V1\20d143a1-89d7-4d48-a9e3-9013248b6914"
            r"\scratchpad\c_harness\fw_control.dll")
fw = ctypes.CDLL(DLL_PATH)
fw.fw_init_config.argtypes = []; fw.fw_init_config.restype = None
fw.fw_r1_step.argtypes = [ctypes.POINTER(ctypes.c_double)] * 4; fw.fw_r1_step.restype = None
fw.fw_wheel_axis_matrix.argtypes = [ctypes.POINTER(ctypes.c_double)]; fw.fw_wheel_axis_matrix.restype = None
fw.fw_set_r1_gains.argtypes = [ctypes.POINTER(ctypes.c_double)] * 2; fw.fw_set_r1_gains.restype = None

# Dedicated R1 gains shipped in task_defs.c Pars_init() / control_defaults.h
# (DEFAULT_SUNPT_R1_GAIN_KP/KD_X/Y/Z), replacing the old flat fine-hold
# placeholder (Kp=0.0023/Kd=0.0001) the harness's fw_init_config() still
# hardcodes. Must override here or this test silently uses stale gains.
# UPDATED 2026-08-07: re-derived from CAD-verified deployed inertia.
R1_GAIN_KP = [0.002849, 0.002127, 0.002785]
R1_GAIN_KD = [0.113972, 0.085063, 0.111386]


def c_arr(vals):
    return (ctypes.c_double * len(vals))(*vals)


# FIXED 2026-08-07: was incorrectly using panels-CLOSED MOI here (copy-paste
# carryover from the detumbling driver) even though SunPointing_R1 runs
# POST-deployment. Now panels-OPEN (deployed), from real CAD mass-properties
# output (COM-aligned inertia tensor, diagonal terms only -- off-diagonals
# are <1.2% of the diagonal, i.e. near-principal-axis-aligned already):
# Lxx=1139723.18, Lyy=850627.37, Lzz=1113857.74 kg*mm^2 -> /1e6 -> kg*m^2.
PLATFORM_MOI = np.array([1.13972318, 0.85062737, 1.11385774])   # real panels-OPEN (deployed) MOI, CAD-verified
I = np.diag(PLATFORM_MOI)
I_inv = np.linalg.inv(I)

_A_flat = c_arr([0.0] * 12)
fw.fw_wheel_axis_matrix(_A_flat)
A_WHEELS = np.array(_A_flat).reshape(3, 4)

DT = 0.2
T_FINAL = 6000.0
TUMBLE_RATE_DEG_S = 7.0
DETUMBLE_PERAXIS_DEG_S = 2.0
POINTING_DONE_DEG = 5.0

Q_TARGET_qwxyz = base.Q_TARGET   # [q0,q1,q2,q3] scalar-first, same convention as Adsquat[qw,qx,qy,qz]


def rk4_gyrostat(q, omega, h, wheel_torque_out, dt):
    """wheel_torque_out is rwTorqueDist()'s per-wheel OUTPUT (distTorque, decoded from
    cmdActValues.RwTorque), NOT a "motor torque on wheel" -- verified numerically that
    A_WHEELS @ TorqDistMat == I_3 exactly, i.e. A_WHEELS @ wheel_torque_out reconstructs
    the ORIGINAL commanded body torque DIRECTLY (no extra negation), matching this
    project's own established convention ("A @ RW = tau_body", satellite_rotational_
    dynamics_var_mag_field.py's comment). So the body feels +A_WHEELS@wheel_torque_out
    directly; by Newton's third law the wheels' OWN spin momentum then moves as
    dh/dt = -wheel_torque_out (opposite sign from the body-torque term), NOT
    dh/dt = +wheel_torque_out as an earlier version of this function assumed (that
    convention is correct for a "motor torque on wheel" formulation, which this is not)."""
    def deriv(q, omega, h):
        H_w = A_WHEELS @ h
        tau_body = A_WHEELS @ wheel_torque_out
        domega = I_inv @ (-np.cross(omega, I @ omega + H_w) + tau_body)
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = -wheel_torque_out.copy()
        return dq, domega, dh

    k1 = deriv(q, omega, h)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1], h + 0.5*dt*k1[2])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1], h + 0.5*dt*k2[2])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1], h + dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    omega_new = omega + (dt/6.0)*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    h_new = h + (dt/6.0)*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
    q_new = q_new/np.linalg.norm(q_new)
    return q_new, omega_new, h_new


def run(t_final=T_FINAL):
    fw.fw_init_config()
    fw.fw_set_r1_gains(c_arr(R1_GAIN_KP), c_arr(R1_GAIN_KD))
    q0, sun_dir = base.build_initial_attitude()
    q = q0.copy()
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)

    n_steps = int(t_final/DT)
    t_hist = np.zeros(n_steps+1)
    w_axes_hist = np.zeros((n_steps+1, 3))
    p_hist = np.zeros(n_steps+1)
    wheel_rpm_hist = np.zeros((n_steps+1, 4))
    t_detumbled_axis = None
    t_pointed = None
    first_sat_time = {i: None for i in range(4)}

    RW_MOI = 5.4e-5
    for k in range(n_steps+1):
        t_hist[k] = k*DT
        w_axes_hist[k, :] = np.degrees(omega)
        p_hist[k] = base.pointing_error_deg(q, sun_dir)
        wheel_rpm_hist[k, :] = (h/RW_MOI) * 60.0/(2*np.pi)

        if t_detumbled_axis is None and np.all(np.abs(w_axes_hist[k, :]) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = k*DT
        if t_pointed is None and t_detumbled_axis is not None and p_hist[k] < POINTING_DONE_DEG:
            t_pointed = k*DT
        sat = np.abs(h) >= rwm.WHEEL_MOMENTUM_MAX_NMS - 1e-9
        for i in range(4):
            if sat[i] and first_sat_time[i] is None:
                first_sat_time[i] = k*DT

        if k == n_steps:
            break

        # Real gyro driver feeds AdsMdl.bodyRate in DEGREES/s (ADIS16545.c) --
        # sun_pointing_r1_control.c now converts internally (* DEG_TO_RAD)
        # before multiplying by Kd, same as the real firmware boundary
        # convention used in run_real_c_detumbling.py. Must feed degrees here.
        wtorque_out = c_arr([0.0, 0.0, 0.0, 0.0])
        fw.fw_r1_step(c_arr(list(np.degrees(omega))), c_arr(list(Q_TARGET_qwxyz)), c_arr(list(q)), wtorque_out)
        u_wheel = np.array(wtorque_out)

        q, omega, h = rk4_gyrostat(q, omega, h, u_wheel, DT)

    return {"t": t_hist, "w_axes_deg_s": w_axes_hist, "p_err_deg": p_hist,
            "t_detumbled_axis": t_detumbled_axis, "t_pointed": t_pointed,
            "first_sat_time": first_sat_time, "wheel_rpm": wheel_rpm_hist}


if __name__ == "__main__":
    r = run()
    print(f"=== Real C: SunPointing_R1 (RW PD, gains Kp={R1_GAIN_KP}/Kd={R1_GAIN_KD}, real wheel geometry) ===")
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
    for i in range(4):
        tsat = r["first_sat_time"][i]
        print(f"  Wheel {i+1} saturation time: {'never' if tsat is None else f'{tsat:.1f} s'}")
    print(f"  Peak wheel rpm (any wheel): {np.max(np.abs(r['wheel_rpm'])):.0f} rpm")
    print(f"  Final wheel rpm (all 4): {r['wheel_rpm'][-1]}")
    print(f"  Final body rate per axis: {r['w_axes_deg_s'][-1]} deg/s")
    print(f"  Final pointing error: {r['p_err_deg'][-1]:.2f} deg")
