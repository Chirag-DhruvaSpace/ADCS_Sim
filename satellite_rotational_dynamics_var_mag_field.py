# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import satellite_params as sp 
import satellite_parameters as config
import numpy as np 
#import calculate_eci_position_and_velocity as eci
#import matplotlib.pyplot as plt 
#import calculate_satellite_body_torques as sat_torques
import control_states as cs 
import torque_distribution as td 
import calculate_disturbances as cd   # NEW: live environmental disturbance torques (gravity gradient / residual dipole / drag)
import store 
#import spin_stabilisation_torque as sst
import MTR_allocator as mtr 
import MTR_parameters_P30xl as mtr_P30 
import time 
import cross_b_torque as sat_torques 
import periodic_gain_sun_pointing as sun_pointing
import calculate_satellite_body_torques as rw_torques_ctrl
import quat2eul as q2e

import moon_pointing as mpt
import nadir_pointing as nad
import sun_pointing_rw as spr
import sun_pointing_rw_z as sprz
import nominal_in_orbit_pointing as niop
import kinematic_robustness_pointing as krp
from datetime import datetime, timezone, timedelta

I = sp.INERTIA_MATRIX.copy()
I_inv = np.linalg.inv(I)
#get_lat_lon_alt = None  
detumbling_complete = False 

# --- Post-convergence spin config (moon-pointing mode) ----------------------
# Once the spacecraft has actually converged on the moon-pointing target
# (checked against the PURE moon-pointing quaternion, not a moving one), it
# continuously spins about its own body Y or Z axis at a fixed rate rather
# than holding still. This is layered on top of moon-pointing, not a
# replacement for it -- the boresight (-X) keeps tracking the Moon while the
# spacecraft rolls about that Y/Z axis underneath it.
MOON_SPIN_AXIS = config.CONTROL.moon_spin_axis
MOON_SPIN_RATE_DEG_S = config.CONTROL.moon_spin_rate_deg_s
MOON_SPIN_AMPLITUDE_DEG = config.CONTROL.moon_spin_amplitude_deg
MOON_SPIN_ACHIEVE_THRESHOLD_DEG = config.CONTROL.moon_spin_achieve_threshold_deg
                                          # which convergence is considered "achieved"
                                          # and spin-up begins (residual floor measured
                                          # in testing was ~0.25-0.4deg, so 2deg gives
                                          # margin without waiting on transient noise)

# Mutable single-element box (same pattern as _latest_r_eci below) holding the
# sim time at which convergence was first detected, so the spin angle is
# t - t_achieved rather than t itself. None means "not yet achieved".
_moon_spin_achieved_time = [None]


def reset_moon_spin():
    """Clears the achieved-convergence timestamp so the spin restarts cleanly
    the next time MOON mode is (re-)entered, instead of jumping to whatever
    angle a stale timestamp would imply. Call this from every dispatch branch
    that ISN'T the MOON branch, same idea as mark_inactive() in the C
    governor port."""
    _moon_spin_achieved_time[0] = None


# --- Sun sweep (RW-based) config ---------------------------------------------
# Same requirement as moon-pointing's post-convergence spin, but for the Sun
# instead of the Moon, and using reaction wheels (this is a NEW mode, separate
# from periodic_gain_sun_pointing.py's existing MTR-based sun-pointing
# controller -- that one is untouched). Body -X -> Sun (matching the
# moon-pointing convention, per explicit confirmation), then oscillates
# between -64deg and +64deg about body Y or Z once converged -- NOTE: this
# is a DIFFERENT range from MOON's own +/-12deg (confirmed explicitly; the
# two sweeps are not meant to share the same amplitude).
SUN_SWEEP_AXIS = config.CONTROL.sun_sweep_axis
SUN_SWEEP_RATE_DEG_S = config.CONTROL.sun_sweep_rate_deg_s
SUN_SWEEP_AMPLITUDE_DEG = config.CONTROL.sun_sweep_amplitude_deg
SUN_SWEEP_ACHIEVE_THRESHOLD_DEG = config.CONTROL.sun_sweep_achieve_threshold_deg

_sun_sweep_achieved_time = [None]


def reset_sun_sweep():
    """Same idea as reset_moon_spin() -- clears the achieved-convergence
    timestamp so the oscillation restarts cleanly the next time SUN_SWEEP
    mode is (re-)entered. Call this from every dispatch branch that ISN'T the
    SUN_SWEEP branch."""
    _sun_sweep_achieved_time[0] = None


def _triangle_wave_angle_deg(elapsed_s, amplitude_deg, rate_deg_s):
    """Symmetric triangle wave: starts at 0, ramps up to +amplitude_deg, back
    down through 0 to -amplitude_deg, and back to 0, with constant slope
    magnitude rate_deg_s throughout (not a full rotation -- oscillates
    between -amplitude_deg and +amplitude_deg only)."""
    period_s = 4.0 * amplitude_deg / rate_deg_s
    t_mod = elapsed_s % period_s
    quarter = period_s / 4.0
    if t_mod < quarter:                       # 0 -> +A
        return rate_deg_s * t_mod
    elif t_mod < 3.0 * quarter:                # +A -> -A
        return amplitude_deg - rate_deg_s * (t_mod - quarter)
    else:                                      # -A -> 0
        return -amplitude_deg + rate_deg_s * (t_mod - 3.0 * quarter)


def _build_spin_quaternion(theta_deg, axis):
    """Quaternion for a rotation of theta_deg about the local 'y' or 'z' axis,
    in the same [q0,q1,q2,q3] scalar-first convention used throughout this
    project (verified against periodic_gain_sun_pointing.quat_mult)."""
    theta_rad = np.radians(theta_deg)
    half = theta_rad / 2.0
    if axis == 'y':
        axis_vec = np.array([0.0, 1.0, 0.0])
    elif axis == 'z':
        axis_vec = np.array([0.0, 0.0, 1.0])
    else:
        raise ValueError(f"MOON_SPIN_AXIS must be 'y' or 'z', got {axis!r}")
    return np.array([np.cos(half),
                      axis_vec[0]*np.sin(half),
                      axis_vec[1]*np.sin(half),
                      axis_vec[2]*np.sin(half)])

get_spacecraft_location = None

# All orbit and target dates use the same configured UTC epoch.
EPOCH_UTC = config.ORBIT.epoch_utc

def _dcm_bi_from_q(q):
    """body->ECI rotation matrix from a scalar-first quaternion [q0,q1,q2,q3].

    This is the EXACT same formula the rotational equations inline everywhere
    (detumbling_torque, the MTR sun-pointing branch, the Omega/q_dot step) --
    hoisted into one named helper so other modules (the visualisation's
    magnetometer-sensor ECI conversion) can reuse it instead of duplicating
    or guessing. Normalises defensively: between RK stages the ODE
    quaternion can drift slightly off unit.
    """
    q = np.asarray(q, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
    ])   # v_eci = C_bi @ v_body ; v_body = C_bi.T @ v_eci

def detumbling_torque(q, w, threshold_deg_s, B_eci):

    # CONTROL-INPUT TAP: the B-dot detumble law steers from the SENSOR belief
    # (noisy gyro rate + noisy body field) when the visualisation loop has
    # the IMU tap switched on; physics truth (q/y integration below) is
    # untouched -- only these controller inputs are swapped.
    q, w, _B_body_sensed = _imu_adcs_state(np.asarray(q, dtype=float),
                                           np.asarray(w, dtype=float),
                                           np.zeros(3))
    if _imu_adcs_enabled[0]:
        # Recompute the body field from the propagated quaternion and the
        # SENSED ECI field (the RHS passes B_sensor_eci in as B_eci), so w
        # and B stay in the same body frame inside this law.
        q0, q1, q2, q3 = q
        _C = np.array([
            [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
            [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
            [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
        ])
        B_body = _C.T @ np.asarray(B_eci, dtype=float)
        B_body_dot = -np.cross(w, B_body)
        B_body_dot_sign = np.array([np.sign(B_body_dot[0]), np.sign(B_body_dot[1]), np.sign(B_body_dot[2])])
        M_max_vector = np.array([sp.M_max, sp.M_max, sp.M_max])
        M = -M_max_vector * B_body_dot_sign
        Torque = np.cross(M, B_body)
        return Torque, M, B_body

    q0, q1, q2, q3 = q
    w_net_deg = np.linalg.norm(w) * 180 / np.pi
    
    C_bi = np.array([
        [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
    ])

    B_body = C_bi.T @ B_eci 
    #B_body = C_bi @ B_eci

    B_body_dot = -np.cross(w, B_body)
    B_body_dot_sign = np.array([np.sign(B_body_dot[0]), np.sign(B_body_dot[1]), np.sign(B_body_dot[2])])
    M_max_vector = np.array([sp.M_max, sp.M_max, sp.M_max])
    M = -M_max_vector * B_body_dot_sign

    Torque = np.cross(M, B_body)  

    return Torque, M, B_body 

'''
def detumbling_torque_decoupled(q, w, threshold_deg_s):

    # Ensure proper shapes
    q = np.asarray(q).reshape(4,)
    w = np.asarray(w).reshape(3,)

    q0, q1, q2, q3 = q

    # Angular velocity magnitude in deg/s
    w_net_deg = np.linalg.norm(w) * 180.0 / np.pi

    # Magnetic field in ECI frame (Tesla)
    B_n = 3.75e-5
    B_e = 3.75e-5
    B_d = 3.75e-5

    B_eci = np.array([B_n, B_e, B_d]).reshape(3,)

    # Direction cosine matrix (Body ← ECI)
    C_bi = np.array([
        [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
    ])

    # Magnetic field in body frame
    B_body = (C_bi.T @ B_eci).reshape(3,)

    # If below threshold → no torque
    if w_net_deg < threshold_deg_s:

        Torque = np.zeros(3)
        M = np.zeros(3)

    else:
           
        # --- DECOUPLED MODE (independent axis torque) ---
        tau_max = sp.M_max * np.linalg.norm(B_body)

        Torque = np.array([
            -tau_max * np.sign(w[0]),
            -tau_max * np.sign(w[1]),
            -tau_max * np.sign(w[2])
        ])

        # Magnetic moment not physically meaningful here
        M = np.zeros(3)


    # Force correct shapes before returning
    return Torque.reshape(3,), M.reshape(3,)
'''

def compute_MTR_power(m):

    m_X = m[0]
    m_Y = m[1]
    m_Z = m[2]

    I_X = m_X/(1 + mtr_P30.gain_ratio) * 1/(np.pi*mtr_P30.r**2 * mtr_P30.N) * 10**6
    I_Y = m_Y/(1 + mtr_P30.gain_ratio) * 1/(np.pi*mtr_P30.r**2 * mtr_P30.N) * 10**6
    I_Z = m_Z/(1 + mtr_P30.gain_ratio) * 1/(np.pi*mtr_P30.r**2 * mtr_P30.N) * 10**6 

    Power_X = (I_X ** 2) * mtr_P30.R
    Power_Y = (I_Y ** 2) * mtr_P30.R 
    Power_Z = (I_Z ** 2) * mtr_P30.R

    power_consumed = Power_X + Power_Y + Power_Z
    return power_consumed, np.abs(I_X), np.abs(I_Y), np.abs(I_Z) 


DETUMBLE_ON_DEG_S = config.CONTROL.detumble_on_rate_deg_s
DETUMBLE_OFF_DEG_S = config.CONTROL.detumble_off_rate_deg_s

# Reaction-wheel target reference. The slider (yaw,pitch,roll) command is interpreted
# relative to the spacecraft's INITIAL orientation at the start of the sim (i.e. an
# ECI-fixed target measured from q_initial), which is the configuration that was
# verified to converge cleanly. It is NOT LVLH/orbit-relative: an orbit-relative
# target requires the body to continuously rotate at orbital rate, which a plain
# attitude-error PD cannot track stably.
Q_INITIAL_RW = np.array([1.0, 0.0, 0.0, 0.0])   # set from y0 at import (below)


_custom_tick_target = None

def set_custom_tick_target(target):
    """Freeze command input during one adaptive attitude integration tick."""
    global _custom_tick_target
    _custom_tick_target = None if target is None else np.asarray(target, dtype=float).copy()


def _rw_control_torque(q, omega):
    """Reaction-wheel PD body torque toward the slider target, expressed relative to
    the initial orientation (ECI-fixed). Same PD law/convention as the original
    calculate_satellite_body_torques that was verified to work."""
    yaw, pitch, roll = cs.get_controls()

    q_slider = np.array(q2e.quaternion_from_euler(yaw, pitch, roll))
    q_slider = q_slider / np.linalg.norm(q_slider)
    q_target = q2e.quaternion_multiply(Q_INITIAL_RW, q_slider)
    q_target = q_target / np.linalg.norm(q_target)
    if cs.get_mode() == 'CUSTOM':
        q_target = cs.get_pointing_target() if _custom_tick_target is None else _custom_tick_target

    q_err = q2e.get_quaternion_error(q_target, q)   # flips sign for shortest path
    e = q_err[1:4]

    # PD gains sized off the actual RW torque budget (same structure as
    # calculate_satellite_body_torques). Reaction wheels can deliver far more
    # torque than magnetorquers, so these can be more aggressive than the MTR case.
    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    # ROOT-CAUSE FIX: sign flipped on the proportional term (was +kp*e) to
    # match get_quaternion_error's corrected convention -- see that function's
    # docstring for the full Lyapunov-stability explanation. Verified this
    # combination converges correctly for target angles from identity ranging
    # 10-172deg (was previously diverging past ~90-100deg).
    tau_body = -kp * e - kd * omega
    return tau_body


def _moon_pointing_control_torque(q, omega, t):
    """Reaction-wheel PD body torque toward the moon-pointing target (body -X ->
    Moon, +Z kept close to ECI +Z -- see moon_pointing.py). Same PD structure as
    _rw_control_torque above, just targeting a genuinely time-varying quaternion
    (the Moon actually moves meaningfully over the course of a simulation,
    unlike the sun-pointing target or the RW slider target) instead of a fixed
    one, so q_target is recomputed every call rather than cached."""
    utc_time = EPOCH_UTC + timedelta(seconds=float(t))

    # moon_pointing_quaternion needs the spacecraft's ECI position; this
    # function only receives q/omega/t directly, so the caller (the mode
    # dispatch below) is responsible for making r_eci available -- see
    # rotational_equations_of_motion's MOON branch.
    r_eci = _latest_r_eci[0]
    q_target_moon = mpt.moon_pointing_quaternion(utc_time, r_eci)

    # Check convergence against the PURE moon-pointing target (not a moving
    # one) -- this is what "achieved" means. Checking against the spinning
    # target instead would never latch, since that target never stops moving.
    q_err_moon = q2e.get_quaternion_error(q_target_moon, q)
    angle_err_deg = 2.0 * np.degrees(np.arccos(np.clip(abs(q_err_moon[0]), -1.0, 1.0)))
    if _moon_spin_achieved_time[0] is None and angle_err_deg < MOON_SPIN_ACHIEVE_THRESHOLD_DEG:
        _moon_spin_achieved_time[0] = t

    if _moon_spin_achieved_time[0] is not None:
        spin_theta_deg = _triangle_wave_angle_deg(
            t - _moon_spin_achieved_time[0], MOON_SPIN_AMPLITUDE_DEG, MOON_SPIN_RATE_DEG_S)
        q_spin = _build_spin_quaternion(spin_theta_deg, MOON_SPIN_AXIS)
        # Right-multiply: applies the spin in the target's OWN (local) Y/Z
        # axis, i.e. rolls the pointing frame about its own boresight-
        # perpendicular axis rather than about a fixed ECI axis.
        # ROOT-CAUSE FIX: this project's C_bi(q) formula composes Hamilton
        # products in REVERSED order (verified directly: C_bi(qA (x) qB) =
        # C_bi(qB) @ C_bi(qA)). Right-multiplying here (quat_mult(q_target_
        # moon, q_spin), the original form) does NOT make the boresight
        # sweep by the exact commanded angle relative to the moon-centered
        # direction -- confirmed numerically: a commanded 12deg spin only
        # produced a ~10.6deg actual sweep (~88%, not exact, and not simply
        # proportional in a clean way). Left-multiplying instead (q_spin (x)
        # q_target_moon) applies the spin FIRST in the moon target's own
        # local body coordinates, THEN carries the whole thing into ECI via
        # the moon-pointing orientation -- verified to give an EXACT sweep:
        # commanded 0/5/12/-12/8deg produced actual 0/5/12/12/8deg off the
        # moon-centered direction, precisely. This matches the actual
        # requirement (confirmed): the Moon should be exactly centered in
        # the frame at the midpoint of the sweep, reaching exactly +/-12deg
        # (the sensor's half-cone FOV angle) at the extremes.
        q_target = sun_pointing.quat_mult(q_spin, q_target_moon)
    else:
        q_target = q_target_moon

    q_err = q2e.get_quaternion_error(q_target, q)   # flips sign for shortest path
    e = q_err[1:4]

    # Same gains as the RW slider mode -- same actuator, same torque budget.
    #
    # HISTORY (kept for context, since this got chased for a while): the
    # earlier "slow multi-orbit divergence" investigation that led to bumping
    # zeta up to 3.0, then higher, was chasing the wrong culprit. The real
    # cause was the get_quaternion_error/control-law sign mismatch (see that
    # function's docstring) -- not underdamping, and not (solely) wheel
    # momentum. The gyroscopic compensation term that used to be here was
    # also REMOVED: it cancels the real omega x I*omega Euler-equation term,
    # which turns out to be exactly the term the closed-loop Lyapunov proof
    # needs (via the identity w.(w x Iw)=0) to guarantee global stability.
    # With the corrected sign convention and that real physics left intact,
    # zeta=1.0 converges cleanly for target angles from identity ranging
    # 10-172deg, no re-divergence over 6000s -- no gain increase needed.
    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    tau_body = -kp * e - kd * omega
    return tau_body, q_target


def _sun_sweep_control_torque(q, omega, t):
    """Reaction-wheel PD body torque toward the sun-sweep target: body -X ->
    Sun (matching moon-pointing's convention), oscillating between -12deg and
    +12deg about body Y or Z once converged. Same structure as
    _moon_pointing_control_torque, including the gyroscopic-compensation term
    (an empirical addition, not something the real firmware's plain-PD
    pattern uses -- carried over here since the requirement was "exactly
    same as moon-pointing"). NOT yet tested for the same long-duration
    stability issues found with moon-pointing (the wheel-momentum-coupling
    divergence); the Sun moves ~4000x slower than the Moon, so whether that
    issue reproduces here is an open question worth testing fresh, not
    assumed to be the same.

    Unlike moon-pointing, no r_eci is needed at all -- sun_vector_eci() is
    purely a function of time (topocentric/geocentric difference is
    ~0.0007deg, negligible), so utc_time is the only input needed for the
    target itself.
    """
    utc_time = EPOCH_UTC + timedelta(seconds=float(t))

    q_target_sun = spr.sun_pointing_quaternion(utc_time)

    q_err_sun = q2e.get_quaternion_error(q_target_sun, q)
    angle_err_deg = 2.0 * np.degrees(np.arccos(np.clip(abs(q_err_sun[0]), -1.0, 1.0)))
    if _sun_sweep_achieved_time[0] is None and angle_err_deg < SUN_SWEEP_ACHIEVE_THRESHOLD_DEG:
        _sun_sweep_achieved_time[0] = t

    if _sun_sweep_achieved_time[0] is not None:
        spin_theta_deg = _triangle_wave_angle_deg(
            t - _sun_sweep_achieved_time[0], SUN_SWEEP_AMPLITUDE_DEG, SUN_SWEEP_RATE_DEG_S)
        q_spin = _build_spin_quaternion(spin_theta_deg, SUN_SWEEP_AXIS)
        # ROOT-CAUSE FIX: same composition-order fix as MOON's spin above --
        # left-multiply so the boresight sweeps by the EXACT commanded
        # angle off the sun-centered direction, matching the confirmed
        # requirement (Sun centered at sweep midpoint, +/-12deg at the
        # extremes, matching the sensor's half-cone FOV angle).
        q_target = sun_pointing.quat_mult(q_spin, q_target_sun)
    else:
        q_target = q_target_sun

    q_err = q2e.get_quaternion_error(q_target, q)
    e = q_err[1:4]

    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    # ROOT-CAUSE FIX (this is where the bug was actually found and diagnosed --
    # see get_quaternion_error's docstring for the full Lyapunov-stability
    # explanation): the plain kp*e-kd*w PD law, combined with the OLD
    # get_quaternion_error convention, diverged for any target attitude
    # sitting past ~90-100deg from identity -- which is exactly where the Sun
    # happens to be right now (~172deg). No amount of gain tuning fixed this
    # (tested up to zeta=100, only delayed the divergence). The gyroscopic
    # compensation term that used to be here was removed for the same reason
    # as moon-pointing's. With the corrected sign below and the real
    # omega x I*omega Euler term left intact, this converges cleanly for
    # target angles from identity ranging 10-172deg, verified over 6000s.
    tau_body = -kp * e - kd * omega
    return tau_body, q_target


def _nadir_target_angular_velocity_body(r_eci, v_eci, dt=config.CONTROL.target_rate_difference_step_s):
    """Feedforward: the nadir-pointing target ISN'T a fixed setpoint -- it
    continuously rotates at orbital rate (once per orbit). A plain PD law
    damps against the spacecraft's own ABSOLUTE body rate, not the rate
    ERROR relative to this rotating target, which produces a permanent
    steady-state tracking lag (classic Type-1-system-tracking-a-ramp
    result) -- confirmed in practice: ~4-5deg residual with no feedforward,
    at 500km altitude that's ~40+km of ground-track offset, well outside
    typical pointing budgets.

    This estimates the target's own body-frame angular velocity by a short
    pure two-body (Keplerian) forward propagation of r_eci/v_eci and finite-
    differencing the resulting target quaternion -- validated to converge
    cleanly as dt shrinks (tested 1.0/0.2/0.05s, agreeing to 4+ significant
    figures), and safer than a hand-derived closed-form (an initial attempt
    at one gave the right magnitude but the wrong axis -- this sidesteps
    that risk entirely by measuring the true rotation directly rather than
    assuming which axis it's about).

    Ignoring J2/drag for this estimate is fine: it's only a feedforward
    correction term, not a substitute for the actual position/velocity
    propagation used everywhere else, so it doesn't need to be exact --
    only close enough to cancel most of the tracking lag. Verified this
    collapses the residual from ~4-5deg to ~0.03deg over a full orbit.
    """
    mu = 3.986004418e14
    a_acc = -mu / np.linalg.norm(r_eci)**3 * r_eci
    v2 = v_eci + a_acc * dt
    r2 = r_eci + v_eci * dt
    q1 = nad.nadir_pointing_quaternion(r_eci, v_eci)
    q2 = nad.nadir_pointing_quaternion(r2, v2)
    dq = q2e.quaternion_multiply(q2e.quaternion_inverse(q1), q2)
    if dq[0] < 0:
        dq = -dq
    return 2.0 * dq[1:4] / dt, q1


def _sun_pointing_rw_control_torque(q, omega, t):
    """Reaction-wheel PD body torque toward plain sun-pointing (body -Z ->
    Sun, matching the EXISTING magnetorquer-based "SUN_POINTING" mode's own
    axis convention -- see sun_pointing_rw_z.py's docstring). No sweep/
    oscillation here, just plain tracking, analogous to the nadir/moon RW
    modes before any spin was layered on top.

    No feedforward needed the way nadir's RW mode has one: the Sun's own
    angular motion is ~1deg/day, utterly negligible compared to the ~0.05
    rad/s natural frequency of this control loop, unlike nadir's once-per-
    orbit (~95min) rotation which produced a real, measurable tracking lag.
    """
    utc_time = EPOCH_UTC + timedelta(seconds=float(t))
    q_target = sprz.sun_pointing_rw_z_quaternion(utc_time)

    q_err = q2e.get_quaternion_error(q_target, q)
    e = q_err[1:4]

    # Same gains as the other RW modes.
    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    tau_body = -kp * e - kd * omega
    return tau_body, q_target


def _nominal_in_orbit_target_angular_velocity_body(r_eci, v_eci, dt=config.CONTROL.target_rate_difference_step_s):
    """Same feedforward technique as _nadir_target_angular_velocity_body
    (finite-difference the target quaternion under a short pure two-body
    forward propagation), applied to the yaw-biased nominal-in-orbit target
    instead of the plain nadir target. Needed for the same reason: this
    target also continuously rotates at orbital rate (the yaw bias is a
    fixed offset riding on top of the same rotating nadir frame), so a plain
    PD law would show the same steady-state tracking lag nadir did without
    this feedforward."""
    mu = 3.986004418e14
    a_acc = -mu / np.linalg.norm(r_eci)**3 * r_eci
    v2 = v_eci + a_acc * dt
    r2 = r_eci + v_eci * dt
    q1 = niop.nominal_in_orbit_pointing_quaternion(r_eci, v_eci)
    q2 = niop.nominal_in_orbit_pointing_quaternion(r2, v2)
    dq = q2e.quaternion_multiply(q2e.quaternion_inverse(q1), q2)
    if dq[0] < 0:
        dq = -dq
    return 2.0 * dq[1:4] / dt, q1


def _nominal_in_orbit_control_torque(q, omega):
    """Reaction-wheel PD+feedforward body torque toward the nominal-in-orbit
    target (nadir pointing with a fixed 45deg yaw bias about the boresight
    -- see nominal_in_orbit_pointing.py). Same structure as
    _nadir_pointing_control_torque, including the feedforward fix for the
    once-per-orbit tracking lag."""
    r_eci = _latest_r_eci[0]
    v_eci = _latest_v_eci[0]
    omega_ff, q_target = _nominal_in_orbit_target_angular_velocity_body(r_eci, v_eci)

    q_err = q2e.get_quaternion_error(q_target, q)
    e = q_err[1:4]

    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    tau_body = -kp * e - kd * (omega - omega_ff)
    return tau_body, q_target


KINEMATIC_ROBUSTNESS_SPIN_RATE_DEG_S = config.CONTROL.kinematic_spin_rate_deg_s


def _kinematic_robustness_target_angular_velocity_body(r_eci, v_eci, t, dt=config.CONTROL.target_rate_difference_step_s):
    """Same finite-difference feedforward technique as nadir/nominal-in-orbit's
    own (short pure two-body forward propagation, then differencing the
    resulting target quaternion) -- naturally captures BOTH the once-per-
    orbit rotation (from nadir tracking) AND the commanded spin rate about
    body +Z combined, without needing to analytically decompose the two."""
    mu = 3.986004418e14
    a_acc = -mu / np.linalg.norm(r_eci)**3 * r_eci
    v2 = v_eci + a_acc * dt
    r2 = r_eci + v_eci * dt
    q1 = krp.kinematic_robustness_pointing_quaternion(r_eci, v_eci, t)
    q2 = krp.kinematic_robustness_pointing_quaternion(r2, v2, t + dt)
    dq = q2e.quaternion_multiply(q2e.quaternion_inverse(q1), q2)
    if dq[0] < 0:
        dq = -dq
    return 2.0 * dq[1:4] / dt, q1


def _kinematic_robustness_control_torque(q, omega, t):
    """Reaction-wheel PD+feedforward body torque toward the kinematic-
    robustness target (body +Z -> nadir, continuously spinning about that
    axis -- see kinematic_robustness_pointing.py). Same structure as
    _nadir_pointing_control_torque/_nominal_in_orbit_control_torque,
    including the feedforward fix for tracking a continuously-rotating
    target (here the target rotates both from orbital motion AND the
    commanded spin, both captured together by the feedforward function
    above)."""
    r_eci = _latest_r_eci[0]
    v_eci = _latest_v_eci[0]
    omega_ff, q_target = _kinematic_robustness_target_angular_velocity_body(r_eci, v_eci, t)

    q_err = q2e.get_quaternion_error(q_target, q)
    e = q_err[1:4]

    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    tau_body = -kp * e - kd * (omega - omega_ff)
    return tau_body, q_target


def _nadir_pointing_control_torque(q, omega):
    """Reaction-wheel PD+feedforward body torque toward the nadir-pointing
    target (body +X -> Earth center, see nadir_pointing.py -- ported from
    the C firmware's calcNadirFrame, with axes relabeled so +X carries the
    nadir direction rather than the C code's literal zdes->bodyZ mapping,
    per this mission's hardware convention).

    NOTE on the sign convention below: this is now -Kp*qerr - Kd*bodyRate,
    not the literal +Kp*qerr +Kd*bodyRate the C code (calculate_nadir_
    pointing_torque) appears to use. That's not a deviation from matching the
    real firmware for its own sake -- it's the fix for a genuine, confirmed
    Lyapunov-stability bug in THIS PYTHON PORT's get_quaternion_error
    (see its docstring). The real C firmware's own calcQuatErr may already
    pair correctly with its own +Kp/+Kd signs (I don't have that function's
    source to check) -- if so, no firmware change is needed, only this
    simulation's. Worth confirming against the real calcQuatErr before
    porting this mode to C."""
    r_eci = _latest_r_eci[0]
    v_eci = _latest_v_eci[0]
    omega_ff, q_target = _nadir_target_angular_velocity_body(r_eci, v_eci)

    q_err = q2e.get_quaternion_error(q_target, q)
    e = q_err[1:4]

    # Same gains as the other RW modes -- untested for long-duration
    # stability the way moon-pointing/sun-sweep now have been, but the
    # sign/stability fix itself is the same one validated across target
    # angles from identity ranging 10-172deg for those modes.
    w_n = config.CONTROL.pointing_natural_frequency_rad_s
    zeta = config.CONTROL.pointing_damping_ratio
    kp = np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz]) * (w_n**2)
    kd = 2.0 * zeta * w_n * np.array([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])

    # Damp against RATE ERROR (omega - omega_ff), not raw omega -- this is
    # the feedforward fix for the steady-state tracking lag described above.
    tau_body = -kp * e - kd * (omega - omega_ff)
    return tau_body, q_target


# Holds the most recent spacecraft ECI position, set by
# rotational_equations_of_motion each call (it already receives r_eci as an
# argument) so _moon_pointing_control_torque can access it without changing
# every caller's signature. A plain list used as a mutable single-element
# box, matching this file's existing style of module-level state
# (detumbling_complete, Q_INITIAL_RW).
_latest_r_eci = [np.array([0.0, 0.0, 0.0])]

# Same pattern, but for velocity -- moon-pointing never needed v_eci (the
# Moon's own ephemeris doesn't depend on the spacecraft's velocity), but
# nadir-pointing does (calcNadirFrame uses both r and v to build the frame).
_latest_v_eci = [np.array([0.0, 0.0, 0.0])]

# ---- IMU-ADCS CONTROL INPUT TAP (added for the IMU wiring question) ----
# Tells the ADCS torque functions in THIS file whether to run on TRUE state
# or on the IMU sensor belief. The visualisation loop sets ACTIVE before each
# solve_ivp step; validation/demo code leaves it OFF (truth). Module-level on
# purpose: solve_ivp's RHS callback chain carries only (t, y, B_eci, ...),
# so a tiny "latest sensor reading" mailbox is the only way to feed the
# controller noisy inputs without rewriting every controller signature.
_imu_adcs_enabled = [False]         # True: rate/field controller inputs come from IMU
_imu_adcs_use_attitude = [False]    # True: attitude error computed on the ESTIMATE
_imu_adcs_omega = [np.zeros(3)]     # latest gyro-measured body rate (rad/s)
_imu_adcs_B_body = [np.zeros(3)]    # latest magnetometer body field (Tesla)
_imu_adcs_q = [np.array([1.0, 0.0, 0.0, 0.0])]   # latest ESTIMATED attitude
                                                 # (body->ECI, scalar-first)


def set_imu_adcs_input(enabled, omega_body_rad_s=None, B_body_t=None,
                       q_belief_eci=None, use_attitude=None):
    """Point the controller-input tap at a sensor reading (or back to truth).

    enabled gates the RATE/FIELD inputs (gyro belief, magnetometer belief);
    use_attitude gates the ATTITUDE input independently: when True, the
    controllers compute their pointing error against q_belief_eci (the
    onboard attitude ESTIMATOR's belief, body->ECI, scalar-first) instead of
    the true attitude -- the satellite steers on what it BELIEVES, exactly
    like real flight software. False/None falls back to truth.
    The stored vectors are COPIED so later caller-side mutation cannot leak
    into the dynamics mid-step.
    """
    _imu_adcs_enabled[0] = bool(enabled)
    if use_attitude is not None:
        _imu_adcs_use_attitude[0] = bool(use_attitude)
    if omega_body_rad_s is not None:
        _imu_adcs_omega[0] = np.asarray(omega_body_rad_s, dtype=float).reshape(3)
    if B_body_t is not None:
        _imu_adcs_B_body[0] = np.asarray(B_body_t, dtype=float).reshape(3)
    if q_belief_eci is not None:
        q_bel = np.asarray(q_belief_eci, dtype=float).reshape(4)
        _imu_adcs_q[0] = q_bel / np.linalg.norm(q_bel)


def _imu_adcs_state(q_true, omega_true, B_body_true):
    """Pick controller inputs: sensor belief when the tap is on, else truth.

    Returns (q_for_control, omega_for_control, B_body_for_control). With the
    tap on, ALL THREE come from the satellite's own belief: the attitude
    ESTIMATOR's quaternion (gyro + magnetometer + sun sensor), the gyro-
    measured rate and the magnetometer-measured field. The PHYSICS
    integration below always uses the true state -- only the controller's
    eyes are the belief (real flight software behaves exactly this way).
    """
    q_ctrl = (np.asarray(_imu_adcs_q[0], dtype=float).reshape(4)
              if _imu_adcs_use_attitude[0] else q_true)
    if not _imu_adcs_enabled[0]:
        return q_ctrl, omega_true, B_body_true
    return q_ctrl, np.asarray(_imu_adcs_omega[0], dtype=float).reshape(3), \
        np.asarray(_imu_adcs_B_body[0], dtype=float).reshape(3)




_firmware_wheels = np.zeros(4)
_firmware_dipole = np.zeros(3)

def set_firmware_tick(wheels, dipole):
    _firmware_wheels[:] = wheels
    _firmware_dipole[:] = dipole

def rotational_equations_of_motion(t, y, B_eci, r_eci=None, v_eci=None, external_torque_body=None, truth_field_eci=None, truth_position_eci=None, truth_velocity_eci=None, aerodynamic_torque_body=None):
     
    global detumbling_complete

    q0,q1,q2,q3,w_x,w_y,w_z = y 
    q = np.array([q0,q1,q2,q3])
    omega = np.array([w_x, w_y, w_z])

    # Make the spacecraft's current ECI position (and, for nadir-pointing,
    # velocity) available to the mode-specific torque functions, which need
    # it but aren't in this function's own call chain from solve_ivp (only
    # q/omega/B_eci/t are).
    if r_eci is not None:
        _latest_r_eci[0] = np.asarray(r_eci, dtype=float)
    if v_eci is not None:
        _latest_v_eci[0] = np.asarray(v_eci, dtype=float)

    w_deg = np.degrees(np.linalg.norm(_imu_adcs_state(q, omega, np.zeros(3))[1]))

    # --- Detumble override with hysteresis: forces DETUMBLE in ANY selected mode
    #     whenever the body rate is high, and only releases below the OFF threshold. ---
    if w_deg > DETUMBLE_ON_DEG_S:
        detumbling_complete = False
    elif w_deg < DETUMBLE_OFF_DEG_S:
        detumbling_complete = True

    # Defaults so telemetry fields always exist regardless of branch
    M = np.zeros(3)
    rw_t = np.zeros(4)

    # ---- SENSOR-BELIEF CONTROL INPUTS (IMU tap) ----
    # The pointing controllers below steer from the satellite's OWN BELIEF
    # when the visualisation loop has the IMU tap switched on
    # (set_imu_adcs_input): the ESTIMATED attitude (q_ctrl, from the onboard
    # gyro+magnetometer+sun-sensor estimator) and the GYRO-MEASURED body rate.
    # The PHYSICS integration below (w_deg hysteresis, the Omega matrix,
    # q_dot/w_dot) keeps using the TRUE state -- only the controller's INPUT
    # is swapped, exactly like real flight software steering on its estimate.
    q_ctrl, omega_ctrl, _ = _imu_adcs_state(q, omega, np.zeros(3))

    firmware_mode = cs.get_mode() == 'FIRMWARE_SITL'
    if firmware_mode:
        rw_t = _firmware_wheels.copy()
        M = _firmware_dipole.copy()
        field = np.asarray(B_eci if truth_field_eci is None else truth_field_eci)
        tau_actual = td.A @ rw_t + np.cross(M, _dcm_bi_from_q(q).T @ field)
        store.mode = 'FIRMWARE_SITL'
    elif not detumbling_complete:
        # Detumble damps the MEASURED rate (omega_ctrl = gyro belief when the
        # IMU tap is on, truth otherwise) -- real flight software can only
        # damp what its gyro reports. B_eci here is ALREADY the sensor view
        # when use_mag_for_control is on (the loop swaps it before solve_ivp).
        # The w_deg hysteresis above stays on TRUE rate (mode arbitration,
        # not a control law -- avoids threshold chatter from gyro noise).
        tau_actual, M, B_body = detumbling_torque(q_ctrl, omega_ctrl, 2.0, B_eci)
        store.mode = "DETUMBLE"
        sun_pointing.mark_inactive()
        reset_moon_spin()
        reset_sun_sweep()

    else:
        mode = cs.get_mode()

        if mode in ("RW", "CUSTOM"):
            # Reaction-wheel PD control to the slider target (relative to initial
            # orientation, ECI-fixed). The net torque the body feels IS the commanded
            # PD torque; the 4-wheel distribution (torque_distribution) is an allocation
            # whose recombined effect A @ RW = tau_body, so we apply tau_body to the body
            # and display the individual wheel torques.
            tau_actual = _rw_control_torque(q_ctrl, omega_ctrl)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            # FIXED: previously tau_actual (the idealized, uncapped PD
            # torque) was what actually drove the physics below, while
            # rw_t was only ever displayed -- meaning RW-40 torque
            # saturation and null-space desaturation had ZERO effect on
            # the simulated satellite. Recombining here makes the ACHIEVED
            # body torque (after the wheel allocator's real 4 mN*m clip and
            # null-space correction) the one that actually acts on the body.
            tau_actual = td.A @ rw_t
            store.mode = mode
            sun_pointing.mark_inactive()
            reset_moon_spin()
            reset_sun_sweep()

        elif mode == "NADIR":
            # Reaction-wheel PD control to the nadir-pointing target (body Z
            # -> Earth center). Same allocation pattern as RW/MOON modes.
            tau_actual, q_nadir_target = _nadir_pointing_control_torque(q_ctrl, omega_ctrl)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "NADIR"
            store.nadir_target_quat[:] = q_nadir_target
            sun_pointing.mark_inactive()
            reset_moon_spin()
            reset_sun_sweep()

        elif mode == "MOON":
            # Reaction-wheel PD control to the moon-pointing target (body -X ->
            # Moon). Same allocation pattern as RW mode -- net body torque IS
            # the commanded PD torque, 4-wheel distribution is just the
            # allocation/display split.
            tau_actual, q_moon_target = _moon_pointing_control_torque(q_ctrl, omega_ctrl, t)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "MOON"
            store.moon_target_quat[:] = q_moon_target
            sun_pointing.mark_inactive()
            reset_sun_sweep()

        elif mode == "SUN_SWEEP":
            # Reaction-wheel PD control to the sun-sweep target (body -X ->
            # Sun, oscillating +/-64deg about Y/Z once converged -- NOTE:
            # this amplitude is different from MOON's own +/-12deg, per
            # explicit correction; the two sweeps are NOT the same range).
            # Same allocation pattern as RW/MOON/NADIR modes. NOT the same as
            # the existing "SUN_POINTING" MTR mode below -- that one is
            # untouched, this is a new, separate mode.
            tau_actual, q_sun_target = _sun_sweep_control_torque(q_ctrl, omega_ctrl, t)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "SUN_SWEEP"
            store.sun_sweep_target_quat[:] = q_sun_target
            sun_pointing.mark_inactive()
            reset_moon_spin()

        elif mode == "SUN_POINTING_RW":
            # Reaction-wheel PD control to plain sun-pointing (body -Z ->
            # Sun, SAME axis as the existing "SUN_POINTING" MTR mode below --
            # only the actuator/control law differs, per explicit
            # requirement that the satellite look at the same direction
            # either way). NOT the same as "SUN_SWEEP" (body -X, oscillates).
            # Same allocation pattern as the other RW modes.
            tau_actual, q_sun_rw_target = _sun_pointing_rw_control_torque(q_ctrl, omega_ctrl, t)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "SUN_POINTING_RW"
            store.sun_pointing_rw_target_quat[:] = q_sun_rw_target
            sun_pointing.mark_inactive()
            reset_moon_spin()
            reset_sun_sweep()

        elif mode == "NOMINAL_IN_ORBIT":
            # Reaction-wheel PD+feedforward control to nadir pointing with a
            # fixed 45deg yaw bias about the boresight (body +X). Same
            # allocation pattern as the other RW modes.
            tau_actual, q_nom_target = _nominal_in_orbit_control_torque(q_ctrl, omega_ctrl)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "NOMINAL_IN_ORBIT"
            store.nominal_in_orbit_target_quat[:] = q_nom_target
            sun_pointing.mark_inactive()
            reset_moon_spin()
            reset_sun_sweep()

        elif mode == "KINEMATIC_ROBUSTNESS":
            # Reaction-wheel PD+feedforward control to the kinematic-
            # robustness target (body +Z -> nadir, continuously spinning
            # about that axis at KINEMATIC_ROBUSTNESS_SPIN_RATE_DEG_S).
            # Same allocation pattern as the other RW modes.
            tau_actual, q_kr_target = _kinematic_robustness_control_torque(q_ctrl, omega_ctrl, t)
            rw_t = td.reaction_wheel_torque_distribution(
                tau_actual[0], tau_actual[1], tau_actual[2])
            tau_actual = td.A @ rw_t   # recombine achieved (clipped/desat) torque -- see RW branch's note
            store.mode = "KINEMATIC_ROBUSTNESS"
            store.kinematic_robustness_target_quat[:] = q_kr_target
            sun_pointing.mark_inactive()
            reset_moon_spin()
            reset_sun_sweep()

        else:
            # Magnetorquer periodic-gain sun pointing (validated). Correct B-cross
            # allocation is done inside sun_pointing.control_torque via MTR_allocator.
            # C_bi here is the satellite's BELIEVED frame (q_ctrl = estimator
            # belief when the IMU tap is on, truth otherwise) -- the controller
            # converts the field with the frame IT believes it has.
            q0c, q1c, q2c, q3c = q_ctrl
            C_bi = np.array([
            [1 - 2*(q2c**2 + q3c**2),   2*(q1c*q2c + q0c*q3c), 2*(q1c*q3c - q0c*q2c)],
            [2*(q1c*q2c - q0c*q3c),     1 - 2*(q1c**2 + q3c**2), 2*(q2c*q3c + q0c*q1c)],
            [2*(q1c*q3c + q0c*q2c),     2*(q2c*q3c - q0c*q1c), 1 - 2*(q1c**2 + q2c**2)]
            ])
            B_body = C_bi.T @ B_eci
            tau_actual, M = sun_pointing.control_torque(q_ctrl, omega_ctrl, B_body, t)
            store.mode = "POINTING"
            reset_moon_spin()
            reset_sun_sweep()

    # Actuator physics uses the real field; controller allocation uses belief.
    actual_B_body = _dcm_bi_from_q(q).T @ np.asarray(truth_field_eci if truth_field_eci is not None else B_eci)
    if truth_field_eci is not None and not firmware_mode:
        sensed_B_body = _dcm_bi_from_q(q_ctrl).T @ np.asarray(B_eci)
        tau_actual = tau_actual + np.cross(M, actual_B_body - sensed_B_body)
    store.rw_torques[:] = rw_t
    store.mtr_dipole[:] = M
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    # Magnetic telemetry excludes the achieved wheel torque; plant torque is unchanged.
    store.mtr_torques[:] = np.cross(M, actual_B_body)
    store.tau_body[:] = tau_actual
    store.time = t
    store.mtr_currents[:] = np.zeros(3) if firmware_mode else compute_MTR_power(M)[1:4] 

    Omega = np.array([
    [0,   -w_x, -w_y, -w_z],
    [w_x,  0,   w_z, -w_y],
    [w_y, -w_z,  0,   w_x],
    [w_z,  w_y, -w_x,  0]
    ])

    external_torque = (np.zeros(3) if external_torque_body is None else
                       np.asarray(external_torque_body(t, q) if callable(external_torque_body)
                                  else external_torque_body, dtype=float))

    # --- ENVIRONMENTAL DISTURBANCE TORQUES (calculate_disturbances.py) --------
    # NEW: the disturbance file is now LIVE physics, not just a budget report.
    # Gravity-gradient + residual-dipole + atmospheric-drag torques are
    # computed here as body-frame VECTORS from the current state (q, r, v, B)
    # and added to the Euler equation below, in EVERY mode -- disturbances
    # are environment physics, they don't care which actuator/controller is
    # active.
    #
    # SRP is deliberately NOT in this sum: satellite_flight_visualisation.py
    # already feeds solar_radiation_pressure.py's detailed (per-surface,
    # eclipse-aware) SRP torque in through external_torque_body above --
    # adding calculate_disturbances.py's crude worst-case SRP constant on
    # top of that would double-count SRP.
    #
    # This is a PURE function of (q, r, v, B) -- nothing is written except
    # the store.* telemetry records (last-RK-stage-wins, same as every other
    # store write in this function) -- so calling it from inside the ODE RHS
    # is safe no matter how many times solve_ivp evaluates this per real
    # step. Only the WRITE-side integrations (wheel momentum, reference
    # governor) need the once-per-outer-step rule; this is read-side physics,
    # like the attitude itself.
    #
    # Downstream effect on the wheels: the controllers must now FIGHT these
    # torques, so the commanded per-wheel torques (and hence the integrated
    # wheel momentum in torque_distribution.py) include the disturbance
    # reaction -- which is exactly what exercises the RW-40 saturation model
    # over long runs.
    tau_disturbance, tau_dist_parts = cd.disturbance_torque_body(
        q, _latest_r_eci[0] if truth_position_eci is None else truth_position_eci,
        _latest_v_eci[0] if truth_velocity_eci is None else truth_velocity_eci,
        B_eci if truth_field_eci is None else truth_field_eci,
        drag_torque_body=(aerodynamic_torque_body(t, q) if callable(aerodynamic_torque_body)
                          else np.zeros(3) if aerodynamic_torque_body is None else aerodynamic_torque_body))
    store.disturbance_torque[:] = tau_disturbance + external_torque
    store.disturbance_torque_gravity_gradient[:] = tau_dist_parts["gravity_gradient"]
    store.disturbance_torque_residual_dipole[:] = tau_dist_parts["residual_dipole"]
    store.disturbance_torque_atmospheric_drag[:] = tau_dist_parts["atmospheric_drag"]

    w_dot = I_inv @ (tau_actual + external_torque + tau_disturbance - np.cross(omega, I @ omega))       #Iω˙=τ−ω×(Iω)
    #w_dot = I_inv @ tau 
    q_dot = 0.5 * Omega @ q
    q = q / np.linalg.norm(q)

    q0_dot = q_dot[0]
    q1_dot = q_dot[1]
    q2_dot = q_dot[2]
    q3_dot = q_dot[3]
    
    #return [q0_dot, q1_dot, q2_dot, q3_dot, w_dot[0], w_dot[1], w_dot[2], E_dot]



    store.angular_acceleration[:] = w_dot
    return [q0_dot, q1_dot, q2_dot, q3_dot, w_dot[0], w_dot[1], w_dot[2]]
    
#y0 = [1.0, 0.0, 0.0, 0.0, sp.w_x*np.pi/180, sp.w_y*np.pi/180, sp.w_z*np.pi/180, 0.0]

y0 = [1.0, 0.0, 0.0, 0.0, sp.w_x*np.pi/180, sp.w_y*np.pi/180, sp.w_z*np.pi/180]

# RW slider target is measured relative to the initial orientation (see _rw_control_torque).
Q_INITIAL_RW = np.array(y0[:4], dtype=float)
Q_INITIAL_RW = Q_INITIAL_RW / np.linalg.norm(Q_INITIAL_RW)
