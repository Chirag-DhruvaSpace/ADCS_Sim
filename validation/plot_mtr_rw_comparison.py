import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = np.load("mtr_rw_detumble_comparison_results.npz")

fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

ax = axes[0]
ax.plot(d["mtr_t"] / 60, d["mtr_w"], label="MTR only", color="#8e44ad")
ax.plot(d["combo_t"] / 60, d["combo_w"], label="MTR + RW", color="#27ae60")
ax.axhline(0.5, color="gray", ls="--", lw=1, label="detumble threshold (0.5 deg/s)")
ax.set_ylabel("body rate (deg/s)")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)
ax.set_title("Detumbling from 7deg/s / 180deg initial sun-pointing error")

ax = axes[1]
ax.plot(d["mtr_t"] / 60, d["mtr_p"], label="MTR only", color="#8e44ad")
ax.plot(d["combo_t"] / 60, d["combo_p"], label="MTR + RW", color="#27ae60")
ax.axhline(5.0, color="gray", ls="--", lw=1, label="sun-pointing threshold (5 deg)")
ax.set_ylabel("sun-pointing error (deg)")
ax.set_xlabel("time (minutes)")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

fig.tight_layout()
fig.savefig("mtr_rw_detumble_comparison.png", dpi=140)
print("saved mtr_rw_detumble_comparison.png")
