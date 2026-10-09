"""
plot_mtr_detumbling_tipoff.py

Graphs (not tables) of the REAL compiled firmware Detumbling_MM (MTR-only
B-dot) control law, driven through fw_control.dll exactly like
run_real_c_detumbling.py's MM_ONLY case, but with two changes requested
for this run:

  1. B-field: real IGRF-14 (real_igrf_field.py), not the fixed-direction
     3e-5T fallback run_real_c_detumbling.py uses -- consistent with this
     session's standing decision to use real IGRF wherever the field's
     true time structure matters.
  2. Initial body rate: worst-case launcher tip-off rate from the EOS-frame
     spec table (X: nominal 5.5, max 5.8 deg/s; Y: nominal 7.4, max 7.8
     deg/s; Z axis not given on that sheet -> taken as 0). Worst case =
     max values, mapped directly onto body axes: [Wx,Wy,Wz] =
     [5.8, 7.8, 0.0] deg/s (EOS coordinate axes assumed == body axes;
     no other mapping was supplied). |w| = 9.72 deg/s -- higher than the
     7.0deg/s symmetric case tested elsewhere in this session.

Plots, all vs time:
  1. MTR commanded dipole moment, 3 axes (A*m^2) -- the real actuator
     command with a real hardware limit (+/-2 A*m^2), analogous to "wheel
     torque" in the RW plots. NOTE: the actual physical torque delivered
     is tau = dipole x B_body (Nm), which depends on the (here,
     time-varying real-IGRF) field -- the dipole moment itself is what's
     actually commanded/limited in hardware, so that's what's plotted as
     "MTR torque".
  2. Wheel speed, 4 wheels (rpm). Detumbling_MM commands the RW to ZERO
     torque (matches the real FSM: MM and RG are mutually exclusive
     states) -- this will be a flat line at 0 rpm, not a bug.
  3. Body rates Wx, Wy, Wz (deg/s).
  4. "Qerr" -- there is no attitude TARGET during pure rate-damping B-dot
     detumbling (unlike SunPointing_M1's governor), so this is the total
     rotation angle away from the INITIAL attitude (2*acos(q0) of the
     attitude quaternion, q0_init = identity), not error-to-a-target. It
     will not converge to zero -- the body keeps tumbling (just slower)
     the whole time; only its RATE decays.
"""
import ctypes
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timezone

from real_igrf_field import b_field_eci_real_igrf

DLL_PATH = (r"C:\Users\KRISHN~1\AppData\Local\Temp\claude\D--Dhruva-Space-firmware-"
            r"ADCS-Leap-2-ADCS-Firmware-V1\20d143a1-89d7-4d48-a9e3-9013248b6914"
            r"\scratchpad\c_harness\fw_control.dll")

fw = ctypes.CDLL(DLL_PATH)
fw.fw_init_config.argtypes = []
fw.fw_init_config.restype = None
fw.fw_mm_step.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
fw.fw_mm_step.restype = None
fw.fw_wheel_axis_matrix.argtypes = [ctypes.POINTER(ctypes.c_double)]
fw.fw_wheel_axis_matrix.restype = None


def c_arr(vals):
    return (ctypes.c_double * len(vals))(*vals)


EPOCH_UTC = datetime(2026, 10, 1, 15, 0, 0, tzinfo=timezone.utc)

# CAD-verified panels-CLOSED (stowed) inertia -- detumbling happens right
# after ejection, before panel deployment.
PLATFORM_MOI = np.array([1.46532507, 1.17571237, 1.24370496])
RW_MOI = 0.000054
I = np.diag(PLATFORM_MOI)
I_inv = np.linalg.inv(I)

_A_flat = c_arr([0.0] * 12)
fw.fw_wheel_axis_matrix(_A_flat)
A_WHEELS = np.array(_A_flat).reshape(3, 4)

DT = 0.2
T_FINAL = 7200.0   # 2hr -- margin above the ~7deg/s cases' 22-36min, for a higher 9.72deg/s start

# Worst-case tip-off rate, EOS coord axes taken as body axes: X=5.8, Y=7.8 max, Z not given -> 0
OMEGA0_DEG_S = np.array([5.8, 7.8, 0.0])


def C_bi(q):
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2+q3**2), 2*(q1*q2+q0*q3), 2*(q1*q3-q0*q2)],
        [2*(q1*q2-q0*q3), 1 - 2*(q1**2+q3**2), 2*(q2*q3+q0*q1)],
        [2*(q1*q3+q0*q2), 2*(q2*q3-q0*q1), 1 - 2*(q1**2+q2**2)],
    ])


def rk4_gyrostat(q, omega, h, tau_ext, dt):
    def deriv(q, omega, h):
        domega = I_inv @ (tau_ext - np.cross(omega, I @ omega))
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz], [wx, 0, wz, -wy], [wy, -wz, 0, wx], [wz, wy, -wx, 0]])
        dq = 0.5 * Omega @ q
        dh = np.zeros(4)
        return dq, domega, dh
    k1 = deriv(q, omega, h)
    k2 = deriv(q + 0.5*dt*k1[0], omega + 0.5*dt*k1[1], h + 0.5*dt*k1[2])
    k3 = deriv(q + 0.5*dt*k2[0], omega + 0.5*dt*k2[1], h + 0.5*dt*k2[2])
    k4 = deriv(q + dt*k3[0], omega + dt*k3[1], h + dt*k3[2])
    q_new = q + (dt/6.0)*(k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
    omega_new = omega + (dt/6.0)*(k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
    h_new = h + (dt/6.0)*(k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
    return q_new/np.linalg.norm(q_new), omega_new, h_new


def run():
    fw.fw_init_config()
    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(OMEGA0_DEG_S)
    h = np.zeros(4)

    n_steps = int(T_FINAL/DT)
    t_hist = np.zeros(n_steps+1)
    w_hist = np.zeros((n_steps+1, 3))
    dipole_hist = np.zeros((n_steps+1, 3))
    wheel_rpm_hist = np.zeros((n_steps+1, 4))
    qerr_deg_hist = np.zeros(n_steps+1)
    t_detumbled_wmag = None
    WMAG_THRESH_DEG_S = 2.0

    # IGRF field varies on the orbital (~90min) timescale, not the 0.2s
    # control-loop timescale -- refreshing it every 2s (10 steps) instead of
    # every step is a >10x speedup with no meaningful effect on the physics
    # (satellite moves ~15km in 2s at LEO speed, negligible vs field gradient).
    B_CACHE_STEPS = 10
    B_eci_cached = None

    for k in range(n_steps+1):
        t = k*DT
        t_hist[k] = t
        w_hist[k, :] = np.degrees(omega)
        wheel_rpm_hist[k, :] = (h/RW_MOI)*60.0/(2*np.pi)
        qerr_deg_hist[k] = 2*np.degrees(np.arccos(np.clip(abs(q[0]), -1, 1)))

        wmag = np.degrees(np.linalg.norm(omega))
        if t_detumbled_wmag is None and wmag < WMAG_THRESH_DEG_S:
            t_detumbled_wmag = t

        if k == n_steps:
            break

        if B_eci_cached is None or k % B_CACHE_STEPS == 0:
            B_eci_cached = b_field_eci_real_igrf(t, EPOCH_UTC)
        B_eci = B_eci_cached
        Cbi = C_bi(q)
        B_body = Cbi.T @ B_eci

        omega_deg_s = np.degrees(omega)
        B_body_uT = B_body * 1e6
        dipole_out = c_arr([0.0, 0.0, 0.0])
        fw.fw_mm_step(c_arr(list(omega_deg_s)), c_arr(list(B_body_uT)), dipole_out)
        dipole = np.array(dipole_out)
        dipole_hist[k, :] = dipole
        tau_ext = np.cross(dipole, B_body)

        q, omega, h = rk4_gyrostat(q, omega, h, tau_ext, DT)

    return {
        "t": t_hist, "w_deg_s": w_hist, "dipole": dipole_hist, "wheel_rpm": wheel_rpm_hist,
        "qerr_deg": qerr_deg_hist, "t_detumbled_wmag": t_detumbled_wmag,
    }


if __name__ == "__main__":
    print(f"Worst-case tip-off rate (EOS axes = body axes): {OMEGA0_DEG_S} deg/s, "
          f"|w|={np.linalg.norm(OMEGA0_DEG_S):.2f} deg/s")
    print("Using REAL IGRF-14 field, real compiled Detumbling_MM (fw_mm_step)")

    r = run()
    t_min = r["t"]/60.0

    fig, axes = plt.subplots(4, 1, figsize=(11, 13), sharex=True)

    ax = axes[0]
    for i, lbl in enumerate(["Mx", "My", "Mz"]):
        ax.plot(t_min, r["dipole"][:, i], label=lbl)
    ax.axhline(2.0, color="k", linestyle=":", linewidth=1, label="±max (2 A·m²)")
    ax.axhline(-2.0, color="k", linestyle=":", linewidth=1)
    ax.set_ylabel("MTR dipole moment (A·m²)")
    ax.set_title("Detumbling_MM (real firmware, real IGRF): worst-case tip-off rate [5.8, 7.8, 0.0] deg/s")
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[1]
    for i in range(4):
        ax.plot(t_min, r["wheel_rpm"][:, i], label=f"Wheel {i+1}")
    ax.set_ylabel("Wheel speed (rpm)")
    ax.set_ylim(-10, 10)
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    ax.text(0.02, 0.5, "RW commanded to zero in Detumbling_MM (MTR-only state) -- flat 0 expected",
            transform=ax.transAxes, fontsize=8, color="gray", va="center")
    ax.grid(alpha=0.3)

    ax = axes[2]
    ax.plot(t_min, r["w_deg_s"][:, 0], label="Wx")
    ax.plot(t_min, r["w_deg_s"][:, 1], label="Wy")
    ax.plot(t_min, r["w_deg_s"][:, 2], label="Wz")
    ax.axhline(2.0, color="k", linestyle=":", linewidth=0.8)
    ax.axhline(-2.0, color="k", linestyle=":", linewidth=0.8)
    ax.set_ylabel("Body rate (deg/s)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[3]
    ax.plot(t_min, r["qerr_deg"], color="purple")
    ax.set_ylabel("Qerr (deg,\nrel. to initial attitude)")
    ax.set_xlabel("Time (min)")
    ax.grid(alpha=0.3)

    if r["t_detumbled_wmag"] is not None:
        tp = r["t_detumbled_wmag"]/60.0
        for ax in axes:
            ax.axvline(tp, color="green", linestyle="--", linewidth=1)
        axes[0].text(tp, axes[0].get_ylim()[1]*0.8, f"  |w|<2deg/s\n  {tp:.2f} min", color="green", fontsize=8)

    fig.tight_layout()
    out_path = "mtr_detumbling_tipoff_worstcase.png"
    fig.savefig(out_path, dpi=150)
    print(f"Saved {out_path}")
    if r["t_detumbled_wmag"] is not None:
        print(f"Wmag < 2deg/s at t={r['t_detumbled_wmag']:.1f}s ({r['t_detumbled_wmag']/60:.2f} min)")
    else:
        print(f"Did NOT reach Wmag<2deg/s within {T_FINAL:.0f}s")
    print(f"Final body rate: {r['w_deg_s'][-1]} deg/s, |w|={np.linalg.norm(r['w_deg_s'][-1]):.4f} deg/s")
    print(f"Peak |dipole|: {np.max(np.abs(r['dipole'])):.4f} A*m^2")
