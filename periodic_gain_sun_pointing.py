"""Historical periodic magnetic-pointing controller with a paced governor.

The target is deliberately fixed to the epoch Sun in EME2000.
"""
import os
import numpy as np
import satellite_parameters as config
from datetime import datetime, timezone
import MTR_allocator as mtr
from adcs_target_frame import build_target_frame

_here = os.path.dirname(os.path.abspath(__file__))
K_seq = np.load(os.path.join(_here, "K_seq.npy"))     # (N,3,6)
t_grid = np.load(os.path.join(_here, "t_grid.npy"))   # (N,)
_N = len(t_grid)
_dt_grid = t_grid[1] - t_grid[0]
_T_orb = _N * _dt_grid
if (K_seq.shape != (_N, 3, 6) or _N < 2 or not np.all(np.isfinite(K_seq))
        or not np.all(np.isfinite(t_grid)) or abs(t_grid[0]) > 1e-12
        or _dt_grid <= 0 or not np.allclose(np.diff(t_grid), _dt_grid)):
    raise ValueError('Invalid magnetic gain/grid artifacts')


def K_of_t(t):
    phase = t % _T_orb
    k = int(phase // _dt_grid) % _N
    return K_seq[k]


def quat_mult(q1, q2):
    w1, x1, y1, z1 = q1; w2, x2, y2, z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ])


def quat_conj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def slerp(q0, q1, s):
    q0 = np.asarray(q0, dtype=float); q0 = q0 / np.linalg.norm(q0)
    q1 = np.asarray(q1, dtype=float); q1 = q1 / np.linalg.norm(q1)
    d = np.dot(q0, q1)
    if d < 0:
        q1 = -q1; d = -d
    d = np.clip(d, -1.0, 1.0)
    if d > 0.9995:
        out = q0 + s * (q1 - q0)
        return out / np.linalg.norm(out)
    theta0 = np.arccos(d)
    sin_theta0 = np.sin(theta0)
    a0 = np.sin((1 - s) * theta0) / sin_theta0
    a1 = np.sin(s * theta0) / sin_theta0
    out = a0 * q0 + a1 * q1
    return out / np.linalg.norm(out)


# --- Fixed sun-pointing target, built ONCE at import time -------------------
# EPOCH_UTC must match the epoch periodic_lqr_design.py used to build K_seq (it imports
# EPOCH_UTC from there internally via build_target_frame(), so this stays in sync automatically).
_C_target, _sun0 = build_target_frame()
from quat2eul import rotmat_to_quaternion
Q_TARGET = rotmat_to_quaternion(_C_target)


# --- Achievability-gated reference governor state (persists across calls) --------------
BASE_RATE_DEG_S = config.CONTROL.sun_pointing_base_rate_deg_s
RATE_CAP_DEGS = config.CONTROL.sun_pointing_rate_cap_deg_s

_gov = {
    "q_ref_start": None,   # attitude the vehicle was at when sun-pointing was last (re-)entered
    "s": 0.0,              # progress 0..1 from q_ref_start toward Q_TARGET
    "total_angle_deg": 1e-6,
    "was_active": False,   # was the SUN_POINTING branch the one that ran last call?
    "last_gate": 1.0,      # most recent achievability*rate_slack, used by step_governor()
}


def reset_governor(q_current):
    """Start a fresh paced approach from the CURRENT attitude toward Q_TARGET. Call this
    whenever sun-pointing control is (re-)entered, e.g. after DETUMBLE or RW mode releases
    control back -- using a stale q_ref_start from long ago (or from a different attitude
    entirely) is exactly what caused the see-saw before this fix."""
    q_current = np.asarray(q_current, dtype=float)
    q_err = quat_mult(quat_conj(q_current), Q_TARGET)
    if q_err[0] < 0:
        q_err = -q_err
    total_angle = 2 * np.degrees(np.arccos(np.clip(q_err[0], -1, 1)))
    _gov["q_ref_start"] = q_current.copy()
    _gov["s"] = 0.0
    _gov["total_angle_deg"] = max(total_angle, 1e-6)


def mark_inactive():
    """Call this from the DETUMBLE and RW branches (i.e. whenever control_torque() is NOT
    the torque law in effect this step), so the next time sun-pointing control resumes,
    reset_governor() fires and re-anchors to wherever the vehicle actually is by then."""
    _gov["was_active"] = False


def step_governor(dt_seconds):
    """Advance the paced reference by dt_seconds of wall-clock time, using the achievability
    gate computed during the most recent control_torque() call. Call this ONCE per OUTER
    simulation time step (e.g. once per satellite_flight_visualisation.py loop iteration),
    not from inside the ODE right-hand-side -- see module docstring point 3."""
    if _gov["q_ref_start"] is None or not _gov["was_active"] or _gov["s"] >= 1.0:
        return
    _gov["s"] = float(np.clip(
        _gov["s"] + (BASE_RATE_DEG_S * _gov["last_gate"] * dt_seconds) / _gov["total_angle_deg"],
        0.0, 1.0
    ))


def control_torque(q, omega, B_body, t):
    """
    q: current attitude quaternion [q0,q1,q2,q3] (scalar-first)
    omega: current body rates (rad/s)
    B_body: magnetic field in body frame (Tesla)
    t: simulation time (s), same clock periodic_lqr_design.py's orbit propagation used
       (t=0 at the same orbital phase as orbit_parameters.py's a,e,i,Omega,omega,nu)
    Returns: tau_actual (Nm), M (dipole moment, A*m^2)
    """
    if not _gov["was_active"]:
        reset_governor(q)
    _gov["was_active"] = True
    if _gov["q_ref_start"] is None:
        reset_governor(q)

    q_ref = slerp(_gov["q_ref_start"], Q_TARGET, _gov["s"])

    q_err = quat_mult(quat_conj(q_ref), q)
    if q_err[0] < 0:
        q_err = -q_err
    e = q_err[1:4]

    x_state = np.concatenate([e, omega])
    Kt = K_of_t(t)
    u = -Kt @ x_state

    M, tau_actual = mtr.torque_to_dipole(u, B_body)

    u_norm = np.linalg.norm(u)
    achievability = np.linalg.norm(tau_actual) / u_norm if u_norm > 1e-12 else 1.0
    w_deg = np.degrees(np.linalg.norm(omega))
    rate_slack = np.clip(1.0 - w_deg / RATE_CAP_DEGS, 0.0, 1.0)
    _gov["last_gate"] = achievability * rate_slack

    return tau_actual, M
