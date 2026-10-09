"""
plot_rw_sunpointing.py

Graphs (not tables) of the SunPointing_R1 (reaction-wheel) sun-pointing
simulation from sun_pointing_rw_saturation_analysis.py. Produces one figure,
four stacked panels vs time:
  1. All 4 reaction-wheel commanded torques (mN*m)
  2. All 4 reaction-wheel speeds (rpm)
  3. Body rates Wx, Wy, Wz (deg/s)
  4. Quaternion error components qerr (w,x,y,z) vs Q_TARGET (calc_quat_err convention)

Run standalone to produce both cases discussed this session:
  - 2.0 deg/s Wmag handoff (real DEFAULT_DETUMBLING_EXIT_THRESH value) -- converges
  - each-axis 2.0 deg/s handoff (Wmag=3.46 deg/s) -- does not converge, wheels saturate
"""
import numpy as np
import matplotlib.pyplot as plt

import sun_pointing_rw_saturation_analysis as sp


def make_plot(result, title, out_path):
    t_min = result["t"] / 60.0
    wheel_torque_mNm = result["wheel_torque"] * 1e3
    wheel_rpm = result["wheel_rpm"]
    w = result["w_deg_s"]
    qerr = result["qerr"]
    tp = result["t_pointed"]

    fig, axes = plt.subplots(4, 1, figsize=(11, 13), sharex=True)

    ax = axes[0]
    for i in range(4):
        ax.plot(t_min, wheel_torque_mNm[:, i], label=f"Wheel {i+1}")
    ax.axhline(sp.RW_MAX_TORQUE * 1e3, color="k", linestyle=":", linewidth=1, label="±max (2.5 mN·m)")
    ax.axhline(-sp.RW_MAX_TORQUE * 1e3, color="k", linestyle=":", linewidth=1)
    ax.set_ylabel("Wheel torque (mN·m)")
    ax.set_title(title)
    ax.legend(ncol=5, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[1]
    for i in range(4):
        ax.plot(t_min, wheel_rpm[:, i], label=f"Wheel {i+1}")
    ax.axhline(sp.WHEEL_MAX_RPM, color="k", linestyle=":", linewidth=1, label="±max (6000 rpm)")
    ax.axhline(-sp.WHEEL_MAX_RPM, color="k", linestyle=":", linewidth=1)
    ax.set_ylabel("Wheel speed (rpm)")
    ax.legend(ncol=5, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[2]
    ax.plot(t_min, w[:, 0], label="Wx")
    ax.plot(t_min, w[:, 1], label="Wy")
    ax.plot(t_min, w[:, 2], label="Wz")
    ax.set_ylabel("Body rate (deg/s)")
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)

    ax = axes[3]
    ax.plot(t_min, qerr[:, 0], label="qerr[0] (w)")
    ax.plot(t_min, qerr[:, 1], label="qerr[1] (x)")
    ax.plot(t_min, qerr[:, 2], label="qerr[2] (y)")
    ax.plot(t_min, qerr[:, 3], label="qerr[3] (z)")
    ax.set_ylabel("Quaternion error (vs Q_TARGET)")
    ax.set_xlabel("Time (min)")
    ax.legend(ncol=4, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)

    if tp is not None:
        for ax in axes:
            ax.axvline(tp / 60.0, color="green", linestyle="--", linewidth=1)
        axes[0].text(tp / 60.0, axes[0].get_ylim()[1] * 0.85, f"  converged\n  {tp/60:.2f} min",
                     color="green", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Saved {out_path}")
    print(f"Converged: {tp/60:.2f} min" if tp is not None else "Did NOT converge within window")
    print(f"Final p_err: {result['p_err_deg'][-1]:.2f} deg")
    print(f"Peak wheel speed: {np.max(np.abs(wheel_rpm)):.0f} rpm")
    print(f"Peak wheel torque: {np.max(np.abs(wheel_torque_mNm)):.4f} mN*m")


if __name__ == "__main__":
    q0, sun_eci_dir = sp.build_initial_attitude()

    omega0_wmag = np.radians(2.0) * np.array([1, 1, 1]) / np.sqrt(3)   # 2 deg/s vector magnitude
    result_wmag = sp.run(q0.copy(), sun_eci_dir, omega0_wmag, t_final=10800.0)
    make_plot(result_wmag,
              "SunPointing_R1: 2.0 deg/s Wmag handoff — torque, speed, body rate, qerr vs time",
              "rw_sunpointing_2degs_wmag.png")

    print()

    omega0_eachaxis = np.radians(2.0) * np.array([1.0, 1.0, 1.0])   # each axis 2 deg/s (Wmag=3.46 deg/s)
    result_eachaxis = sp.run(q0.copy(), sun_eci_dir, omega0_eachaxis, t_final=7200.0)
    make_plot(result_eachaxis,
              "SunPointing_R1: each-axis 2.0 deg/s handoff (Wmag=3.46 deg/s) — torque, speed, body rate, qerr vs time",
              "rw_sunpointing_eachaxis2degs.png")
