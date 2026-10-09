import numpy as np

# NEW import: integrate_wheel_momentum() (below) integrates store.rw_torques
# -- the per-wheel torque the dynamics ACTUALLY applied (written
# unconditionally on every pass of rotational_equations_of_motion, in every
# mode branch: the post-saturation command in RW modes, exact zeros in
# DETUMBLE/POINTING). store.py imports nothing but numpy, so this adds no
# import cycle.
import store
import satellite_parameters as config
import satellite_parameters as config

# Wheel-axis matrix -- hoisted to module level (was rebuilt inside the
# function on every call) so it's importable as td.A for recombining a
# clipped/null-space-corrected 4-wheel command back into the achieved body
# torque: tau_achieved = A @ rw_torques. Only depends on the fixed pyramid
# geometry below, never on any per-call input, so computing it once at
# import time is both more efficient and enables this recombination use.
wedge_angle = 55
elevation_angle = 90 - wedge_angle

beta1 = 45        #Degrees
beta2 = 135       #Degrees
beta3 = 225       #Degrees
beta4 = 315       #Degrees

_C = np.cos(np.radians(elevation_angle))
_S = np.sin(np.radians(elevation_angle))

_a1 = np.array([_C*np.cos(np.radians(beta1)), _C*np.sin(np.radians(beta1)), _S])
_a2 = np.array([_C*np.cos(np.radians(beta2)), _C*np.sin(np.radians(beta2)), _S])
_a3 = np.array([_C*np.cos(np.radians(beta3)), _C*np.sin(np.radians(beta3)), _S])
_a4 = np.array([_C*np.cos(np.radians(beta4)), _C*np.sin(np.radians(beta4)), _S])

A = np.asarray(config.REACTION_WHEELS.axis_matrix_body, dtype=float)
A_INV = np.linalg.pinv(A)
# The four fixed wheel axes have only 15 nonempty free-wheel subsets.
# Precompute identical SVD solutions once instead of in every saturated RK stage.
from itertools import combinations
_FREE_WHEEL_INVERSES = {indices: np.linalg.pinv(A[:, indices])
                        for size in range(1, A.shape[1] + 1)
                        for indices in combinations(range(A.shape[1]), size)}

# Derive the zero-body-torque redistribution direction from the active axes.
# The legacy diagonal pyramid and the CAD wheel placements have different
# null directions; using a fixed legacy vector would disturb attitude in CAD mode.
NULL_VEC = np.linalg.svd(A, full_matrices=True)[2][-1]

# Comat RW-40 real hardware specs (confirmed via SatCatalog and Satsearch,
# both citing Comat directly: 4 mN*m mean torque, 40 mN*m*s momentum
# storage) -- replaces the earlier placeholder values.
# NOTE: reaction_wheel_model.py (not imported anywhere in the runtime
# chain, and now superseded by this file) uses a DIFFERENT momentum figure
# (26.67 mN*m*s @ 4000rpm). If your datasheet says 26.67, change
# MAX_WHEEL_MOMENTUM here -- everything else adapts automatically.
MAX_WHEEL_TORQUE = config.WHEEL_MAX_TORQUE_NM
MAX_WHEEL_MOMENTUM = config.WHEEL_MAX_MOMENTUM_NMS

# Desaturation gain -- how aggressively the null-space correction pulls
# accumulated momentum back toward zero. Small and slow by design (this
# should be a gentle, continuous bleed-off, not a sudden correction that
# could itself look like unexpected wheel activity in telemetry).
# TODO(SME): this is still NOT derived from the RW-40's real dynamics --
# it's a starting point, not a validated value. A reasonable next step:
# set K_NULL_DESAT so the null-space component decays with a time constant
# that's slow relative to your attitude control bandwidth but fast enough
# to matter over a single orbit -- e.g. tau ~ 500-2000s given this wheel's
# torque authority, rather than picking a number and checking it doesn't
# blow up.
K_NULL_DESAT = config.REACTION_WHEELS.null_space_desaturation_gain

# --- Saturation allocator switches ------------------------------------------
# When a wheel's command gets cut by saturation, re-solve the body torque it
# can no longer deliver onto the still-free wheels (bounded passes) instead
# of silently accepting a distorted body torque. With 4 wheels for 3 body
# axes there is ONE redundant wheel, so a single limited wheel costs no body
# torque at all (any 3 of these 4 wheel axes span R^3 for this geometry --
# checked numerically, det != 0 for every 3-subset). Set False to recover the
# old plain per-wheel-clip behaviour (e.g. to study how saturation distorts
# the achieved torque direction).
ENABLE_SATURATION_REALLOCATION = config.REACTION_WHEELS.saturation_reallocation_enabled
MAX_REALLOCATION_PASSES = config.REACTION_WHEELS.max_reallocation_passes

# --- Persistent wheel momentum state (module-level box, matching this
# project's established "mutable list as a box" convention elsewhere) ----
_wheel_momentum = [np.zeros(4)]   # per-wheel angular momentum (N*m*s)
# Per-wheel flags from the allocator's most recent call: True where that
# wheel's command was cut by the torque limit and/or the momentum limit.
# Written on every RHS eval (harmless last-wins record -- only the momentum
# INTEGRATION needs to happen once per outer step, see below).
_last_command_limited = [np.zeros(4, dtype=bool)]


def _apply_wheel_limits(u, h):
    """Clamps a per-wheel torque command u to what the wheels can physically
    deliver RIGHT NOW given their current momenta h:

    (1) TORQUE saturation: |u_i| <= MAX_WHEEL_TORQUE (4 mN*m, RW-40). A
        clipped wheel still delivers its clamped value -- saturation CAPS a
        wheel, it doesn't switch it off.

    (2) MOMENTUM saturation: a wheel already AT +MAX_WHEEL_MOMENTUM (40
        mN*m*s, i.e. spinning at max speed) cannot accelerate FURTHER in the
        positive direction, so positive commanded torque on it is zeroed
        (mirrored at -MAX). Backing OUT of saturation (opposite-sign torque)
        is always allowed -- this is exactly what lets the null-space
        desaturation pull a saturated wheel back off its limit.

    Simplification (flagged, not hidden): a real wheel's torque authority
    degrades smoothly near max speed (back-EMF / driver voltage headroom);
    this is a hard cut at the limit, the same simplification
    reaction_wheel_model.py's _clip_against_saturation() made.
    """
    u = np.clip(u, -MAX_WHEEL_TORQUE, MAX_WHEEL_TORQUE)
    u = np.where((h >= MAX_WHEEL_MOMENTUM) & (u > 0.0), 0.0, u)
    u = np.where((h <= -MAX_WHEEL_MOMENTUM) & (u < 0.0), 0.0, u)
    return u


def _saturate_and_redistribute(u_ideal, tau_body_command):
    """Full RW-40 saturation pass over a 4-wheel command.

    Returns (u, limited): u is the physically deliverable per-wheel command,
    limited[i] is True if wheel i's command was cut by the torque and/or
    momentum limits.

    Reallocation: limited wheels stay pinned at their clamped values (still
    contributing whatever they CAN deliver), and the body torque they can no
    longer provide is re-solved onto the still-free wheels via the
    pseudo-inverse of their columns of A, in bounded passes (each pass pins
    any newly-limited free wheel and re-solves the rest). The pinned set only
    ever grows, so this always terminates. The null-space desat component is
    NOT protected during reallocation: when pointing authority and momentum
    housekeeping compete for the same saturated wheels, pointing wins.
    """
    h = _wheel_momentum[0]

    u = _apply_wheel_limits(u_ideal, h)
    limited = np.abs(u - u_ideal) > 1e-12

    if not ENABLE_SATURATION_REALLOCATION:
        return u, limited

    for _ in range(MAX_REALLOCATION_PASSES):
        free_idx = np.where(~limited)[0]
        if free_idx.size == 0 or not np.any(limited):
            break   # nothing limited, or no free wheel left to help

        # Body torque the limited wheels still contribute at their clamped values:
        tau_from_limited = A[:, limited] @ u[limited]
        # Ask the free wheels to make up the remainder of the commanded torque:
        u_free_raw = _FREE_WHEEL_INVERSES[tuple(free_idx)] @ (tau_body_command - tau_from_limited)
        u_free_lim = _apply_wheel_limits(u_free_raw, h[free_idx])

        newly_limited = np.abs(u_free_lim - u_free_raw) > 1e-12
        u[free_idx] = u_free_lim
        if not np.any(newly_limited):
            break   # free wheels absorbed the whole loss -- done
        limited[free_idx[newly_limited]] = True

    return u, limited


def reaction_wheel_torque_distribution(T_x, T_y, T_z):
    """
    4-wheel allocation of a commanded body torque under the FULL RW-40
    saturation model. Returns the per-wheel motor torques (N*m) the cluster
    can ACTUALLY deliver right now -- the dynamics recombines them
    (tau_actual = td.A @ rw_t), so the ideal, unlimited PD command never
    reaches the rigid body.

    Applied in order:
      1. baseline minimum-norm allocation (pseudo-inverse, unchanged);
      2. + null-space momentum desaturation (zero body-torque effect by
         construction while unsaturated);
      3. per-wheel torque clip at +/-MAX_WHEEL_TORQUE (4 mN*m);
      4. momentum saturation: wheels already at +/-MAX_WHEEL_MOMENTUM are
         blocked from torque that would push them further INTO saturation
         (backing out is always allowed);
      5. reallocation of whatever body torque the limited wheels lost onto
         the still-free wheels (see _saturate_and_redistribute).

    Only READS _wheel_momentum (safe from inside the ODE RHS -- reading many
    times per real step is harmless); records _last_command_limited for
    telemetry.
    """
    T_satellite = np.array([T_x, T_y, T_z])

    RW_Torques = A_INV @ T_satellite

    # --- NULL-SPACE MOMENTUM MANAGEMENT -----------------------------------
    # h_null_component below is the current wheel-momentum vector's
    # component along A's null direction -- the part of the 4 wheels'
    # combined momentum that's "invisible" to attitude control and would
    # otherwise silently accumulate forever. tau_null drives that component
    # back toward zero, added on top of the baseline RW_Torques above (which
    # is unaffected, by construction of the null space).
    h_null_component = np.dot(NULL_VEC, _wheel_momentum[0]) / np.dot(NULL_VEC, NULL_VEC)
    tau_null = -K_NULL_DESAT * h_null_component * NULL_VEC

    RW_Torques_final = RW_Torques + tau_null

    # --- SATURATION (the actual RW-40 limits) ------------------------------
    # Previously this was a bare np.clip to +/-MAX_WHEEL_TORQUE: the 4 mN*m
    # torque cap was enforced, but (a) a wheel already AT its 40 mN*m*s
    # momentum limit kept accepting commands in the saturating direction
    # (only the tracked number was clamped afterwards -- the allocator never
    # knew the wheel was full), and (b) one clipped wheel distorted the
    # achieved body torque even though the remaining 3 wheels can exactly
    # re-achieve it. Both are handled now by _saturate_and_redistribute().
    RW_Torques_final, limited = _saturate_and_redistribute(RW_Torques_final, T_satellite)
    _last_command_limited[0] = limited

    return RW_Torques_final


def integrate_wheel_momentum(dt):
    """
    Advances the persistent wheel-momentum state by dt, using the wheel
    torque the dynamics ACTUALLY applied over the step that just finished.

    Torque source: store.rw_torques -- the dynamics writes it
    unconditionally on every pass of rotational_equations_of_motion, in
    EVERY mode branch: the post-saturation command in the RW modes, and
    exact zeros in DETUMBLE and the MTR ("POINTING") mode. Reading it here
    (instead of a private "_latest_rw_torque_commanded" box written only by
    the allocator itself, which this replaces) fixes a real leak that box
    had: after switching from an RW mode to an MTR mode, the box kept
    holding the LAST RW torque command forever, so this integration kept
    adding a stale torque every step -- silently driving the (unpowered)
    wheels toward momentum saturation. It also guarantees the momentum
    state integrates exactly the torque whose reaction the body actually
    felt (the same rw_t the dynamics recombines via A @ rw_t).

    MUST still be called exactly ONCE PER OUTER SIMULATION STEP (e.g. once
    per second in satellite_flight_visualisation.py's run_simulation()
    loop) -- NEVER from inside the ODE's right-hand-side function
    (rotational_equations_of_motion), which solve_ivp calls a variable,
    integrator-dependent number of times per real step (rejected trial
    steps, internal RK stages, not necessarily in increasing time order).
    Integrating momentum from in there would double/triple-count torque
    within a single real second, exactly the same oversampling trap this
    project already hit and fixed for the DADMOD magnetometer recording
    and the MEKF's applied-torque feed -- same fix, same reasoning, applied
    here too.

    reaction_wheel_torque_distribution() itself only READS _wheel_momentum
    (for the null-space correction and the saturation limits) -- reading it
    many times per real second from inside the RHS is harmless, since it's
    not being written there.
    """
    _wheel_momentum[0] = _wheel_momentum[0] + np.asarray(store.rw_torques, dtype=float) * dt

    # Hard clip to the saturation limit -- prevents the tracked state itself
    # from reporting an unphysical value beyond what a real wheel could ever
    # reach. Euler integration can overshoot the limit by up to
    # MAX_WHEEL_TORQUE*dt in one step; the allocator's momentum blocking
    # then keeps it pinned at the limit rather than pushing further. This
    # does NOT model realistic saturation dynamics (a real wheel's torque
    # authority drops smoothly as it approaches max speed, rather than
    # clipping sharply) -- flagged as a simplification, not a complete
    # saturation model.
    _wheel_momentum[0] = np.clip(_wheel_momentum[0], -MAX_WHEEL_MOMENTUM, MAX_WHEEL_MOMENTUM)


def get_wheel_momentum():
    """Returns the current 4-wheel momentum state (N*m*s), e.g. for
    logging/telemetry -- a copy, so callers can't accidentally mutate the
    persistent state."""
    return _wheel_momentum[0].copy()


def get_wheel_saturation_fraction():
    """Returns each wheel's |momentum| / MAX_WHEEL_MOMENTUM (0 = empty,
    1 = at the saturation limit) -- a quick way to check how close any wheel
    is to saturating, e.g. for a console warning."""
    return np.abs(_wheel_momentum[0]) / MAX_WHEEL_MOMENTUM


def get_last_command_limited():
    """Returns a 4-bool copy of the allocator's most recent per-wheel
    saturation flags: True where that wheel's torque command was cut by the
    4 mN*m torque limit and/or the momentum limit on the last call. The
    allocator runs inside the ODE RHS (many times per real step), so this is
    the last RK-stage view -- good enough for telemetry/warning purposes."""
    return _last_command_limited[0].copy()


def reset_wheel_momentum():
    """Cleares the tracked momentum state (and the saturation flags) -- call
    when resetting/restarting a simulation run, same idea as this project's
    other reset_*() functions (reset_mekf(), reset_magnetometer_history(),
    etc.)."""
    _wheel_momentum[0] = np.zeros(4)
    _last_command_limited[0] = np.zeros(4, dtype=bool)


#reaction_wheel_torque_distribution(0,0,0.01)
