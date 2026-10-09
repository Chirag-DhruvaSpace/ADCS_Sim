import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = np.load("sun_pointing_rw_saturation_results.npz")

fig, axes = plt.subplots(3, 2, figsize=(13, 10), sharex=True)
strategies = [("4wheel", "4-wheel (baseline)"), ("3wheel+dump", "3-wheel + 4th-wheel dump")]

for col, (key, title) in enumerate(strategies):
    t = d[f"{key}__t"]
    w = d[f"{key}__w_deg_s"]
    p = d[f"{key}__p_err_deg"]
    h = d[f"{key}__h_mNms"]

    ax = axes[0, col]
    ax.plot(t, w, color="#c0392b")
    ax.axhline(7.0, color="gray", ls="--", lw=1, label="initial 7 deg/s")
    ax.set_title(title)
    ax.set_ylabel("body rate (deg/s)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax = axes[1, col]
    ax.plot(t, p, color="#2980b9")
    ax.axhline(0.0, color="gray", ls="--", lw=1)
    ax.set_ylabel("sun-pointing error (deg)")
    ax.grid(alpha=0.3)

    ax = axes[2, col]
    for i in range(4):
        ax.plot(t, h[:, i], label=f"wheel {i+1}")
    ax.axhline(26.67, color="k", ls=":", lw=1, label="+/-limit")
    ax.axhline(-26.67, color="k", ls=":", lw=1)
    ax.set_ylabel("wheel momentum (mN*m*s)")
    ax.set_xlabel("time (s)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.3)

fig.suptitle("SUN_POINTING_RW from 7deg/s tumble, 180deg initial error, MTR unavailable", fontsize=12)
fig.tight_layout()
fig.savefig("sun_pointing_rw_saturation_results.png", dpi=140)
print("saved sun_pointing_rw_saturation_results.png")