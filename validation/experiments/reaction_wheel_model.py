"""
reaction_wheel_model.py

Realistic (finite-resource) reaction-wheel actuator model for the 4-wheel
skewed-pyramid cluster ("tetrahedral" configuration), to replace the
infinite-torque/infinite-momentum assumption baked into torque_distribution.py
+ satellite_rotational_dynamics_var_mag_field.py (those apply the commanded
PD body torque directly to the rigid body and only use the 4-wheel
allocation for telemetry display -- see the comment at that call site).

Wheel geometry is IDENTICAL to torque_distribution.py (elevation 35deg,
azimuths 45/135/225/315deg) -- this was cross-checked against the user's own
mission numbers: driving all 4 wheels at +/-4mN*m with signs (+,+,+,+) gives
+9.177mN*m about Z, and signs (+,-,-,+) give +9.268mN*m about X with Y/Z
exactly cancelling -- both match the user's stated cluster torque-authority
figures to 3 decimal places, so this geometry is confirmed correct.

Per-wheel limits, from the user's supplied hardware numbers:
    WHEEL_TORQUE_MAX_NM     = 4.00 mN*m   (torque per wheel)
    WHEEL_MOMENTUM_MAX_NMS  = 26.67 mN*m*s (momentum per wheel @ 4000rpm
                                            saturation speed)
"""
import numpy as np

WHEEL_TORQUE_MAX_NM = 4.00e-3        # N*m, per wheel
WHEEL_MOMENTUM_MAX_NMS = 26.67e-3    # N*m*s, per wheel (4000rpm saturation)

_ELEVATION_DEG = 35.0
_BETAS_DEG = (45.0, 135.0, 225.0, 315.0)


def wheel_axes():
    """Returns A, shape (3,4): columns are the 4 wheel spin-axis unit vectors
    in body frame. v_body_torque = A @ u, u = per-wheel motor torque (N*m)."""
    C = np.cos(np.radians(_ELEVATION_DEG))
    S = np.sin(np.radians(_ELEVATION_DEG))
    cols = []
    for beta in _BETAS_DEG:
        cols.append([C * np.cos(np.radians(beta)), C * np.sin(np.radians(beta)), S])
    return np.array(cols).T   # (3,4)


A_WHEELS = wheel_axes()             # all 4 wheels
A3_WHEELS = A_WHEELS[:, :3]         # wheels 1,2,3 only (used by the 3-wheel+dump strategy)
A4_AXIS = A_WHEELS[:, 3]            # wheel 4's own spin axis (the dedicated dump wheel)

_A_PINV = np.linalg.pinv(A_WHEELS)
_A3_INV = np.linalg.inv(A3_WHEELS)


def _clip_against_saturation(u, h):
    """Clip commanded per-wheel torque to +/-WHEEL_TORQUE_MAX_NM, AND zero out
    any torque that would drive an already-momentum-saturated wheel further
    into saturation (a wheel pinned at its speed limit physically cannot
    accelerate further in that direction)."""
    u = np.clip(u, -WHEEL_TORQUE_MAX_NM, WHEEL_TORQUE_MAX_NM)
    u = np.where((h >= WHEEL_MOMENTUM_MAX_NMS) & (u > 0), 0.0, u)
    u = np.where((h <= -WHEEL_MOMENTUM_MAX_NMS) & (u < 0), 0.0, u)
    return u


def allocate_4wheel(tau_cmd_body, h):
    """Baseline realistic allocator: minimum-norm split of the commanded body
    torque across all 4 wheels (same pseudo-inverse torque_distribution.py
    already uses), but now actually clipped to what the hardware can deliver."""
    u = _A_PINV @ tau_cmd_body
    return _clip_against_saturation(u, h)


def allocate_3wheel_plus_dump(tau_cmd_body, h, H_total_body, k_dump=5.0):
    """Fallback strategy requested when the 4-wheel allocator saturates:
    wheels 1-3 handle 3-axis pointing EXACTLY (A3 is square/invertible, so no
    pseudo-inverse residual -- unlike the 4-wheel minimum-norm split, wheels
    1-3 alone can still deliver any commanded body torque, just with less
    torque margin per axis since wheel 4 is no longer sharing the load).

    Wheel 4 is entirely dedicated to momentum management: it is NOT part of
    the pointing-torque solve at all. Instead it is driven to null the
    system's total angular momentum component along its own spin axis,
    H_total_body . A4_AXIS (H_total_body = I*omega + wheel momentum vector,
    i.e. everything the wheels+body are carrying together) -- soaking up
    whatever momentum it can along that one axis so wheels 1-3 see less
    residual momentum to fight. k_dump=5.0 [1/s] is large enough that this
    law saturates to +/-WHEEL_TORQUE_MAX_NM (bang-bang) whenever the
    projected momentum is more than ~0.8 mN*m*s from zero, i.e. it dumps as
    fast as the hardware physically allows until nearly emptied.
    """
    u123 = _A3_INV @ tau_cmd_body
    u4 = -k_dump * np.dot(H_total_body, A4_AXIS)
    u = np.array([u123[0], u123[1], u123[2], u4])
    return _clip_against_saturation(u, h)


def wheel_momentum_vector_body(h):
    """H_w in body frame: sum of each wheel's own momentum along its spin axis."""
    return A_WHEELS @ h
