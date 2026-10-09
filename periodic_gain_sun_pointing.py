"""
periodic_gain_sun_pointing.py

Sun-pointing controller using the Floquet-verified periodic gain schedule (K_seq.npy /
t_grid.npy, produced by periodic_lqr_design.py against the REAL IGRF field this project
already uses).

Two deliberate choices here, both to avoid bugs found elsewhere in this codebase:

1. Quaternion error convention is copied VERBATIM from periodic_lqr_design.py (not from
   quat2eul.py's get_quaternion_error, which uses q_target * conj(q_curr) -- the OPPOSITE
   Hamilton-product order from what K_seq.npy was designed against: conj(q_target) * q_curr).
   Mixing the two would silently feed the gain schedule a differently-signed error.

2. The B-cross actuator step calls MTR_allocator.torque_to_dipole() directly instead of
   reimplementing the cross product locally. cross_b_torque.py in this project computes
   mu = cross(tau_des, B_body)/|B|^2, which is the REVERSE argument order from the correct
   law (mu = cross(B_body, tau_des)/|B|^2, as used in MTR_allocator.py and as derived in
   periodic_lqr_design.py's docstring). The reversed order produces tau_actual = -P(t)@u,
   i.e. torque in the OPPOSITE direction of what was commanded -- an inverted-sign actuator
   that actively destabilizes a feedback loop instead of correcting it. MTR_allocator.py's
   implementation is already correct, so we reuse it here rather than risk a third copy of
   this same bug.

3. ACHIEVABILITY-GATED REFERENCE GOVERNOR (added -- this was the missing piece that caused
   the large see-saw oscillation observed in testing). K_seq/K(t) was only ever Floquet-
   verified as a SMALL-SIGNAL regulator near the target -- feeding it the FINAL target
   directly from a large initial error (e.g. the ~171deg gap between identity attitude and
   Q_TARGET at simulation start) reproduced a real, confirmed oscillation swinging the
   pointing error from ~171deg down to a few degrees, overshooting back out past 170deg, and
   only damping out after a multi-thousand-second transient. The fix (same approach validated
   in periodic_gain_governor_180.py): instead of tracking Q_TARGET directly, track a PACED
   reference q_ref that SLERPs from wherever the vehicle was when sun-pointing control was
   last (re-)entered, toward Q_TARGET, advancing only when the current geometry can actually
   deliver correction torque in roughly the needed direction (the achievability fraction) and
   only while body rate stays contained. This is intentionally NOT integrated as part of the
   ODE state vector (unlike periodic_gain_governor_180.py's single-solve_ivp-call design) --
   this codebase's live loop advances the rotation state in independent, fixed dt-second
   chunks (see satellite_flight_visualisation.py), re-evaluating mode/B_eci once per chunk,
   so the governor's progress is advanced the same way: once per OUTER time step via
   step_governor(dt), not from inside the ODE right-hand-side (which gets evaluated an
   integrator-dependent, non-physical number of times per chunk -- advancing state there
   would make the maneuver's pacing depend on solver internals instead of wall-clock time).
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
_R = _C_target.T
_tr = np.trace(_R)
_qw = np.sqrt(max(0, 1 + _tr)) / 2
_qx = (_R[2, 1] - _R[1, 2]) / (4 * _qw)
_qy = (_R[0, 2] - _R[2, 0]) / (4 * _qw)
_qz = (_R[1, 0] - _R[0, 1]) / (4 * _qw)
Q_TARGET = np.array([_qw, _qx, _qy, _qz])
Q_TARGET /= np.linalg.norm(Q_TARGET)


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
