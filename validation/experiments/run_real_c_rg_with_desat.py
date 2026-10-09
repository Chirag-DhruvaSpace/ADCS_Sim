"""
run_real_c_rg_with_desat.py

Compares the REAL compiled Detumbling_RG algorithm as currently shipped
(MTR hardcoded to zero) against the PROPOSED fix (wire in the same
desatFlag-gated desaturationCalcTorq() every other RW-based mode already
uses), from the same 7deg/s tumble scenario used throughout this analysis.

Uses the CORRECTED wheel-torque sign convention (found while testing R1):
A_WHEELS @ wheelTorque_out reconstructs the commanded body torque DIRECTLY
(verified numerically, A_WHEELS @ TorqDistMat == I_3), so the body feels
+A_WHEELS@wheelTorque_out, and by Newton's third law the wheels' own momentum
moves as dh/dt = -wheelTorque_out.

Real firmware constants throughout: PLATFORM_MOI (closed-panel, correct for
Detumbling_RG since it runs before SP deployment), RW_MAX_TORQUE=2.5mN*m/wheel,
real wedge=55deg TorqDistMat geometry, RW_MOI=5.4e-5 kg*m^2, real 5000rpm/
1000rpm desat start/stop thresholds, real MTR_MAX_CURR/MTR_COIL_NA (2 A*m^2 max).
"""
import ctypes
import numpy as np

DLL_PATH = (r"C:\Users\KRISHN~1\AppData\Local\Temp\claude\D--Dhruva-Space-firmware-"
            r"ADCS-Leap-2-ADCS-Firmware-V1\20d143a1-89d7-4d48-a9e3-9013248b6914"
            r"\scratchpad\c_harness\fw_control.dll")
fw = ctypes.CDLL(DLL_PATH)
fw.fw_init_config.argtypes = []; fw.fw_init_config.restype = None
fw.fw_rg_step.argtypes = [ctypes.POINTER(ctypes.c_double)]*2
fw.fw_rg_step.restype = None
fw.fw_rg_step_with_desat.argtypes = [ctypes.POINTER(ctypes.c_double)]*5 + [ctypes.POINTER(ctypes.c_int)]
fw.fw_rg_step_with_desat.restype = None
fw.fw_wheel_axis_matrix.argtypes = [ctypes.POINTER(ctypes.c_double)]
fw.fw_wheel_axis_matrix.restype = None


def c_arr(vals):
    return (ctypes.c_double * len(vals))(*vals)


PLATFORM_MOI = np.array([1.46532507, 1.17571237, 1.24370496])   # CAD-verified panels-CLOSED MOI, correct pre-deployment
I = np.diag(PLATFORM_MOI)
I_inv = np.linalg.inv(I)
RW_MOI = 5.4e-5   # kg*m^2, real per-wheel rotor inertia

_A_flat = c_arr([0.0]*12)
fw.fw_wheel_axis_matrix(_A_flat)
A_WHEELS = np.array(_A_flat).reshape(3, 4)

DT = 0.2
T_FINAL = 6000.0
TUMBLE_RATE_DEG_S = 7.0
DETUMBLE_PERAXIS_DEG_S = 2.0
DESAT_START_RPM = 5000.0
DESAT_STOP_RPM = 1000.0
B_ECI = 3e-5 * np.array([0.35, 0.55, 0.75]) / np.linalg.norm([0.35, 0.55, 0.75])


def C_bi(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2+q3**2), 2*(q1*q2+q0*q3), 2*(q1*q3-q0*q2)],
        [2*(q1*q2-q0*q3), 1 - 2*(q1**2+q3**2), 2*(q2*q3+q0*q1)],
        [2*(q1*q3+q0*q2), 2*(q2*q3-q0*q1), 1 - 2*(q1**2+q2**2)],
    ])


def rk4(q, omega, h, wheel_torque, tau_mtr, dt):
    def deriv(q, omega, h):
        H_w = A_WHEELS @ h
        tau_body = A_WHEELS @ wheel_torque + tau_mtr   # RW reaction (direct) + real external MTR torque
        domega = I_inv @ (-np.cross(omega, I @ omega + H_w) + tau_body)
        wx, wy, wz = omega
        Omega = np.array([[0,-wx,-wy,-wz],[wx,0,wz,-wy],[wy,-wz,0,wx],[wz,wy,-wx,0]])
        dq = 0.5*Omega@q
        dh = -wheel_torque.copy()
        return dq, domega, dh
    k1 = deriv(q, omega, h)
    k2 = deriv(q+0.5*dt*k1[0], omega+0.5*dt*k1[1], h+0.5*dt*k1[2])
    k3 = deriv(q+0.5*dt*k2[0], omega+0.5*dt*k2[1], h+0.5*dt*k2[2])
    k4 = deriv(q+dt*k3[0], omega+dt*k3[1], h+dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0]+2*k2[0]+2*k3[0]+k4[0])
    omega_new = omega + (dt/6.0)*(k1[1]+2*k2[1]+2*k3[1]+k4[1])
    h_new = h + (dt/6.0)*(k1[2]+2*k2[2]+2*k3[2]+k4[2])
    return q_new/np.linalg.norm(q_new), omega_new, h_new


def run(mode, t_final=T_FINAL):
    fw.fw_init_config()
    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)   # wheel angular momentum, kg*m^2/s

    n_steps = int(t_final/DT)
    t_detumbled_axis = None
    desat_active_time = None
    max_rpm_seen = 0.0

    for k in range(n_steps+1):
        t = k*DT
        w_deg = np.degrees(omega)
        wheel_rpm = (h/RW_MOI) * 60.0/(2*np.pi)
        max_rpm_seen = max(max_rpm_seen, np.max(np.abs(wheel_rpm)))

        if t_detumbled_axis is None and np.all(np.abs(w_deg) < DETUMBLE_PERAXIS_DEG_S):
            t_detumbled_axis = t

        if k == n_steps:
            return {"t_detumbled_axis": t_detumbled_axis, "w_final": w_deg,
                    "max_rpm_seen": max_rpm_seen, "desat_active_time": desat_active_time}

        if mode == "current":
            wtorque_out = c_arr([0.0]*4)
            fw.fw_rg_step(c_arr(list(omega)), wtorque_out)
            wt = np.array(wtorque_out)
            tau_mtr = np.zeros(3)
        elif mode == "with_desat":
            Cbi = C_bi(q)
            B_body = Cbi.T @ B_ECI
            wtorque_out = c_arr([0.0]*4)
            dipole_out = c_arr([0.0, 0.0, 0.0])
            desat_flag = ctypes.c_int(0)
            fw.fw_rg_step_with_desat(c_arr(list(omega)), c_arr(list(B_body*1e6)),
                                      c_arr(list(wheel_rpm)), wtorque_out, dipole_out,
                                      ctypes.byref(desat_flag))
            wt = np.array(wtorque_out)
            dipole = np.array(dipole_out)
            tau_mtr = np.cross(dipole, B_body)   # real Tesla B for genuine physical torque
            if desat_flag.value == 1 and desat_active_time is None:
                desat_active_time = t
        else:
            raise ValueError(mode)

        q, omega, h = rk4(q, omega, h, wt, tau_mtr, DT)


if __name__ == "__main__":
    for mode, label in [("current", "CURRENT (as-shipped): MTR held at zero during RG"),
                         ("with_desat", "PROPOSED: RG + concurrent MTR wheel desaturation")]:
        r = run(mode)
        print(f"\n=== {label} ===")
        if r["t_detumbled_axis"] is None:
            det_str = f"never within {T_FINAL:.0f}s"
        else:
            det_str = f"{r['t_detumbled_axis']:.1f}s ({r['t_detumbled_axis']/60:.2f}min)"
        print(f"  Detumbled (<{DETUMBLE_PERAXIS_DEG_S} deg/s each axis): {det_str}")
        if r["desat_active_time"] is None:
            desat_str = "never"
        else:
            desat_str = f"{r['desat_active_time']:.1f}s"
        print(f"  Desaturation first became active: {desat_str}")
        print(f"  Max wheel speed reached: {r['max_rpm_seen']:.0f} rpm "
              f"(real desat trigger: {DESAT_START_RPM:.0f} rpm)")
        print(f"  Final body rate: {r['w_final']} deg/s")
