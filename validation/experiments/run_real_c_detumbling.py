"""
run_real_c_detumbling.py

Drives the ACTUAL compiled firmware control-law code (fw_control.dll, built
from verbatim copies of detumbling_MM.c / detumbling_RG.c / control_laws.c /
utils.c -- see fw_driver.c/fw_shim.h) through a rigid-body simulation, for
the same 7deg/s tumble scenario used throughout this analysis, using the
REAL firmware constants (RW_MAX_TORQUE=2.5mN*m, RW_MOI=5.4e-5 kg*m^2,
PLATFORM_MOI = panels-CLOSED inertia, RW wedge=55deg wheel geometry,
MTR_MAX_CURR/MTR_COIL_NA -> 2A*m^2 max dipole) instead of this repo's
existing Python control laws/specs.

Three cases, all using the real compiled functions:
  MM_ONLY  -- state_Detumbling_MM(): bdotCalcTorq() + actuate_detumbling_torque(),
              MTR only, RW commanded to zero torque (matches real code).
  RG_ONLY  -- state_Detumbling_RG(): bdot_RW_CalcTorq() + actuate_detumbling_RG_torque(),
              RW only, MTR commanded to zero (matches real code).
  MM_RW    -- HYPOTHETICAL: both real torques (MM's dipole AND RG's per-wheel
              command) computed and applied to the SAME body simultaneously.
              NOTE: the real FSM never runs these two states at once --
              Detumbling_MM and Detumbling_RG are mutually exclusive states
              (MM primary, RG a priority-2 fallback if MTR/magnetometer
              fail). This case answers "what if both actuators fired
              together" using the real per-actuator control laws, not a
              real firmware mode.

Body dynamics: full rigid body, Euler's equation with the wheel reaction
torque folded in as I*domega/dt = tau_ext - omega x (I*omega) - A@u_wheel
(A = the wheel-axis matrix implied by AdsConfigStruct.TorqDistMat, read back
from the DLL itself via fw_wheel_axis_matrix -- not re-derived by hand).
Wheel state (speed, rpm) is tracked in Python from the REAL per-wheel torque
the DLL actually delivers (post RW_MAX_TORQUE saturation and the real
ALPHA=0.7 low-pass filter, which persists correctly across calls because
cmdActValues.RwTorque is a DLL-side global, not reset between steps).

B-field: same fixed-direction representative field as
mtr_rw_detumble_comparison.py (magnitude 3e-5T) -- see that file's own
docstring for why a fixed direction is an acceptable simplification for a
detumbling-DURATION question specifically (real IGRF blocked by a broken
pyIGRF package data file in this environment).
"""
import ctypes
import numpy as np

DLL_PATH = (r"C:\Users\KRISHN~1\AppData\Local\Temp\claude\D--Dhruva-Space-firmware-"
            r"ADCS-Leap-2-ADCS-Firmware-V1\20d143a1-89d7-4d48-a9e3-9013248b6914"
            r"\scratchpad\c_harness\fw_control.dll")

fw = ctypes.CDLL(DLL_PATH)

fw.fw_init_config.argtypes = []
fw.fw_init_config.restype = None

fw.fw_mm_step.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
fw.fw_mm_step.restype = None

fw.fw_rg_step.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
fw.fw_rg_step.restype = None

fw.fw_wheel_axis_matrix.argtypes = [ctypes.POINTER(ctypes.c_double)]
fw.fw_wheel_axis_matrix.restype = None


def c_arr(vals):
    arr = (ctypes.c_double * len(vals))(*vals)
    return arr


# ---- real firmware constants (verbatim, see fw_shim.h) ----
# CAD-verified 2026-08-07, panels-CLOSED (stowed) mass-properties output,
# COM-aligned inertia tensor, diagonal terms only (off-diagonals <1.1% of
# diagonal): Lxx=1465325073.19, Lyy=1175712369.70, Lzz=1243704962.67 g*mm^2
# -> /1e9 -> kg*m^2.
PLATFORM_MOI = np.array([1.46532507, 1.17571237, 1.24370496])   # panels-CLOSED (stowed), CAD-verified
RW_MOI = 0.000054       # kg*m^2, per wheel
RW_MAX_TORQUE = 0.0025  # Nm, per wheel (2.5 mN*m -- NOT the 4mN*m hardware spec quoted earlier)
DESAT_START_RPM = 5000  # AdsStat_DesatStartThresh default -- firmware's own "wheel out of capacity" trigger

I = np.diag(PLATFORM_MOI)
I_inv = np.linalg.inv(I)

# Wheel axis matrix, read back from the DLL (not re-derived) -- 3x4, wheel->body
_A_flat = c_arr([0.0] * 12)
fw.fw_wheel_axis_matrix(_A_flat)
A_WHEELS = np.array(_A_flat).reshape(3, 4)

B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])

DT = 0.2          # s, 5Hz -- matches the real TIM6 control-loop rate AND detumbling_MM.c's TIME_STEP=500ms... note:
                  # detumbling_MM.c's finite-difference Bdot branch hardcodes TIME_STEP=500ms regardless of our DT;
                  # the default AdsStat_BdotMethod is BdotCtrl_CrossProduct (not the finite-difference branch), so
                  # this mismatch doesn't affect the default-config runs below.
T_FINAL = 6000.0
TUMBLE_RATE_DEG_S = 7.0
DETUMBLE_PERAXIS_DEG_S = 2.0   # user's own criterion


def C_bi(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2+q3**2), 2*(q1*q2+q0*q3), 2*(q1*q3-q0*q2)],
        [2*(q1*q2-q0*q3), 1 - 2*(q1**2+q3**2), 2*(q2*q3+q0*q1)],
        [2*(q1*q3+q0*q2), 2*(q2*q3-q0*q1), 1 - 2*(q1**2+q2**2)],
    ])


def rk4_gyrostat(q, omega, h, tau_ext, u_wheel, dt):
    def deriv(q, omega, h):
        H_w = A_WHEELS @ h
        tau_wheel_reaction = A_WHEELS @ u_wheel
        domega = I_inv @ (tau_ext - np.cross(omega, I @ omega + H_w) - tau_wheel_reaction)
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = u_wheel.copy()
        return dq, domega, dh

    k1 = deriv(q, omega, h)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1], h + 0.5*dt*k1[2])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1], h + 0.5*dt*k2[2])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1], h + dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    omega_new = omega + (dt/6.0)*(k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    h_new = h + (dt/6.0)*(k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    q_new = q_new / np.linalg.norm(q_new)
    return q_new, omega_new, h_new


def run(case, t_final=T_FINAL):
    fw.fw_init_config()

    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)   # wheel angular momentum, kg*m^2/s (= RW_MOI * wheel_speed_rad_s)

    n_steps = int(t_final / DT)
    t_hist = np.zeros(n_steps + 1)
    w_axes_hist = np.zeros((n_steps + 1, 3))
    wheel_rpm_hist = np.zeros((n_steps + 1, 4))

    t_detumbled_axis = None
    t_wheel_hit_desat_thresh = None
    w_at_desat_thresh = None

    for k in range(n_steps + 1):
        t_hist[k] = k * DT
        w_axes_hist[k, :] = np.degrees(omega)
        wheel_speed_rad_s = h / RW_MOI
        wheel_rpm_hist[k, :] = wheel_speed_rad_s * 60.0 / (2*np.pi)

        if t_detumbled_axis is None and np.all(np.abs(w_axes_hist[k, :]) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = k * DT
        if t_wheel_hit_desat_thresh is None and np.any(np.abs(wheel_rpm_hist[k, :]) >= DESAT_START_RPM):
            t_wheel_hit_desat_thresh = k * DT
            w_at_desat_thresh = w_axes_hist[k, :].copy()
            if case in ("RG_ONLY", "MM_RW"):
                # The REAL FSM (rwSaturated(), state_machine.c) would trigger
                # Event_RwAndGyroSaturate -> Safe Mode right here. Neither
                # bdot_RW_CalcTorq() nor rwTorqueDist() has any internal
                # momentum-based cutoff of their own -- that external FSM
                # transition is the ONLY thing that stops the real system
                # from commanding torque forever regardless of wheel speed.
                # Stop here rather than let this standalone harness (which
                # has no FSM around it) run the wheel into an unbounded,
                # physically-meaningless spin that the real flight software
                # would already have aborted out of.
                t_hist = t_hist[:k+1]; w_axes_hist = w_axes_hist[:k+1]; wheel_rpm_hist = wheel_rpm_hist[:k+1]
                break

        if k == n_steps:
            break

        Cbi = C_bi(q)
        B_body = Cbi.T @ B_ECI

        tau_ext = np.zeros(3)
        u_wheel = np.zeros(4)

        # The real sensor drivers feed AdsMdl.bodyRate in DEGREES/second
        # (ADIS16545.c's gyroScaleFactor path, e.g. "case 0x03: /* +/-125deg/sec */")
        # and AdsMdl.magVectorB in MICROTESLA (ICM20948_MAG_SCALE = 0.15 uT/LSB) --
        # NOT the SI rad/s and Tesla this simulation's own physics state uses
        # internally. Convert at the boundary so the real control-law code sees
        # exactly what its real sensors would.
        omega_deg_s = np.degrees(omega)
        B_body_uT = B_body * 1e6

        if case in ("MM_ONLY", "MM_RW"):
            dipole_out = c_arr([0.0, 0.0, 0.0])
            fw.fw_mm_step(c_arr(list(omega_deg_s)), c_arr(list(B_body_uT)), dipole_out)
            dipole = np.array(dipole_out)   # A*m^2, per mtrCurrDist's own current->dipole convention
            tau_ext = tau_ext + np.cross(dipole, B_body)   # true physical torque needs true Tesla B

        if case in ("RG_ONLY", "MM_RW"):
            wtorque_out = c_arr([0.0, 0.0, 0.0, 0.0])
            fw.fw_rg_step(c_arr(list(omega_deg_s)), wtorque_out)
            u_wheel = np.array(wtorque_out)

        q, omega, h = rk4_gyrostat(q, omega, h, tau_ext, u_wheel, DT)

    return {
        "t": t_hist, "w_axes_deg_s": w_axes_hist, "wheel_rpm": wheel_rpm_hist,
        "t_detumbled_axis": t_detumbled_axis,
        "t_wheel_hit_desat_thresh": t_wheel_hit_desat_thresh,
        "w_at_desat_thresh": w_at_desat_thresh,
    }


def report(label, r):
    print(f"\n=== {label} (REAL compiled firmware control law) ===")
    if r["t_detumbled_axis"] is not None:
        print(f"  Detumbled (EACH axis < {DETUMBLE_PERAXIS_DEG_S} deg/s) at t = "
              f"{r['t_detumbled_axis']:.1f} s ({r['t_detumbled_axis']/60:.2f} min)")
    else:
        wa = r["w_axes_deg_s"][-1]
        print(f"  NOT per-axis-detumbled within {r['t'][-1]:.0f}s "
              f"(final |wx|,|wy|,|wz| = {abs(wa[0]):.2f}, {abs(wa[1]):.2f}, {abs(wa[2]):.2f} deg/s)")
    if r["t_wheel_hit_desat_thresh"] is not None:
        wa = r["w_at_desat_thresh"]
        print(f"  A wheel crossed the firmware's own {DESAT_START_RPM} rpm DesatStartThresh at t = "
              f"{r['t_wheel_hit_desat_thresh']:.1f} s -- the REAL FSM (rwSaturated() check, "
              f"state_machine.c) would trigger Event_RwAndGyroSaturate -> Safe Mode here, so this "
              f"run stops at this point rather than simulating past what the real flight software "
              f"would already have aborted out of.")
        print(f"  Body rate at that moment: |wx|,|wy|,|wz| = {abs(wa[0]):.2f}, {abs(wa[1]):.2f}, {abs(wa[2]):.2f} deg/s")
    else:
        print(f"  No wheel reached {DESAT_START_RPM} rpm within {r['t'][-1]:.0f}s "
              f"(final wheel speeds: {r['wheel_rpm'][-1]} rpm)")
    print(f"  Final body rate per axis: {r['w_axes_deg_s'][-1]} deg/s")


if __name__ == "__main__":
    print(f"Real PLATFORM_MOI (panels-closed, SAT build): {PLATFORM_MOI}")
    print(f"Real RW_MAX_TORQUE: {RW_MAX_TORQUE*1e3} mN*m/wheel, RW_MOI: {RW_MOI} kg*m^2")
    print(f"Real wheel-axis matrix (from AdsConfigStruct.TorqDistMat's pseudo-inverse):\n{A_WHEELS}")
    print(f"B field used (fixed): magnitude {np.linalg.norm(B_ECI)*1e6:.1f} uT")
    print(f"Detumble criterion (user-specified): EACH axis < {DETUMBLE_PERAXIS_DEG_S} deg/s\n")

    for case in ("MM_ONLY", "RG_ONLY", "MM_RW"):
        r = run(case)
        report(case, r)
