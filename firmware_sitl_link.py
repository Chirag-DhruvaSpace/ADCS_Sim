"""
firmware_sitl_link.py

Receives the 4 reaction-wheel torque commands from the real firmware
(via ACS SITL's acs_sim_link.c) and makes them available to
satellite_rotational_dynamics_var_mag_field.py's new "FIRMWARE_SITL" mode.

Mirrors telemetry.py's role/style exactly, but for the reverse direction --
same UDP, non-blocking, module-level-state pattern.

The plant latches bounded wheel and magnetic commands once per physics step.
Wheel momentum uses the achieved torque (dh/dt = -T_body_axis); returned
wheel telemetry reports that same torque. Live simulation integrates rotor
momentum with bus attitude, including the wheel-cluster gyroscopic term.
"""

import math
import socket
import struct
import threading
import time

import numpy as np

CMD_LISTEN_PORT = 5104     # matches ACS SITL's PYTHON_CMD_PORT (where it actually sends RW commands) --
                            # CORRECTED this session: was 5102, a leftover/wrong value; ACS SITL
                            # never sends to that port at all, only from it.
TLM_SEND_PORT = 5103        # matches ACS SITL's ACS_SIM_TLM_PORT (it listens HERE)
ACS_SITL_HOST = "127.0.0.1"

MODE_LISTEN_PORT = 5105     # matches ADS SITL's PYTHON_MODE_PORT -- new this session,
                            # carries the REAL ADS AdsMode (distinct from store.mode,
                            # which is always "FIRMWARE_SITL" regardless of the real mode)

CMD_FORMAT = "<3d"   # rwNo, mode, value -- matches acs_sim_link.h's AcsRwCmdPacket exactly
# AcsRwCmdPacket.mode values (acs_sim_link.h ACS_SIM_CMD_*).
CMD_MODE_RW_TORQUE = 0      # rwNo = wheel 0..3, value = torque, mNm
CMD_MODE_RW_SPEED = 1       # rwNo = wheel 0..3, value = raw speed command
CMD_MODE_MTR_CURRENT = 2    # rwNo = torquer rod 0..2 (body X/Y/Z), value = signed current, mA
TLM_FORMAT = "<3d"   # rwNo, currspeed_rpm, actual_torque_mNm -- matches acs_sim_link.h exactly

# Compatibility name retained for callers; geometry is configured in YAML.
from satellite_parameters import REACTION_WHEELS
RW_MOI = REACTION_WHEELS.rotor_inertia_kg_m2
if REACTION_WHEELS.firmware_axis_matrix_body:
    FLIGHT_WHEEL_AXES_BODY = np.asarray(REACTION_WHEELS.firmware_axis_matrix_body, dtype=float)
elif REACTION_WHEELS.axis_matrix_body:
    FLIGHT_WHEEL_AXES_BODY = np.asarray(REACTION_WHEELS.axis_matrix_body, dtype=float)
else:
    from torque_distribution import A
    FLIGHT_WHEEL_AXES_BODY = A.copy()
FLIGHT_WHEEL_AXES_BODY.setflags(write=False)

_lock = threading.Lock()
_latest_torque_mNm = [0.0, 0.0, 0.0, 0.0]
_wheel_momentum = [0.0, 0.0, 0.0, 0.0]   # kg*m^2*rad/s, separate bookkeeping only -- see module docstring
_applied_torque_Nm = np.zeros(4)
_wheel_received_at = [None]*4
_mtr_received_at = [None]*3

_cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_cmd_sock.bind(("0.0.0.0", CMD_LISTEN_PORT))
_cmd_sock.setblocking(False)

_mode_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_mode_sock.bind(("0.0.0.0", MODE_LISTEN_PORT))
_mode_sock.setblocking(False)
_latest_ads_mode = [0]   # raw AdsMode byte value, 0 = AdcsMode_Safe

# Mode packet (mode_link.c's ModeLinkPacket, #pragma pack(1)): AdsHk.AdcsMode
# (uint8), the firmware's attitude estimate AdsMdl.fusedquat (w, x, y, z,
# body->ECI, 4 float32) and fuseAttDiag.source (uint8: 0 none, 1 star tracker,
# 2 TRIAD, 3 Sun-2DOF) -- 18 bytes. No actuator commands: those come from the
# ACS SITL on the command port, as they reach the actuators through the ACS
# board in flight.
MODE_STATUS_FORMAT = "<B4fB"

# Magnetorquer rod currents in mA, signed (+ve = dipole along +body axis), as
# the ACS last commanded them: the firmware's mtrCurrDist() via flight acs.c
# AcsSetMtrCurrAll() -> ACS SITL.
_latest_mtr_current_mA = [0.0, 0.0, 0.0]
_latest_fused_quaternion = [None]
_latest_fuse_source = [0]
_latest_fuse_received_at = [None]
FUSE_SOURCE_NAMES = {0: "Gyro only", 1: "Star tracker", 2: "TRIAD", 3: "Sun 2-DOF"}

# Human-readable names, matching base_shared.h's AdsMode enum exactly --
# only Safe/NadirPoint are meaningful in this build (the only two modes
# actually reachable: default Safe, or NadirPoint once commanded), but
# the full table is included for completeness/future modes.
_ADS_MODE_NAMES = {
    0: "Safe", 1: "Sunpoint", 2: "NadirPoint", 3: "TargetPoint",
    4: "Desaturation", 5: "Detumbling", 6: "SpinInduction",
    7: "RateControl", 8: "MoonSweep", 9: "SunSweep",
    10: "NominalInOrbit", 11: "KinematicRobustness", 20: "Maneuver",
}

_tlm_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def poll_rw_torques():
    """Non-blocking -- drains ALL pending torque-command packets this
    call (not just one), so a burst of 4 wheel updates from ACS SITL
    doesn't lag behind by multiple outer-loop iterations. Call once per
    outer loop iteration, BEFORE the rotation solve_ivp() call, so the
    latest command is actually used by that same step's integration."""
    for _ in range(256):
        try:
            data, _ = _cmd_sock.recvfrom(1024)
        except BlockingIOError:
            break

        if len(data) != struct.calcsize(CMD_FORMAT):
            print(f"firmware_sitl_link: got {len(data)} bytes, expected "
                  f"{struct.calcsize(CMD_FORMAT)} -- discarding")
            continue

        rwNo_f, mode_f, value = struct.unpack(CMD_FORMAT, data)
        if (not all(math.isfinite(v) for v in (rwNo_f, mode_f, value))
                or rwNo_f != round(rwNo_f) or mode_f not in (0, 2)):
            continue
        rwNo = int(round(rwNo_f))
        mode = int(round(mode_f))

        if not (0 <= rwNo <= (2 if mode == CMD_MODE_MTR_CURRENT else 3)):
            print(f"firmware_sitl_link: actuator {rwNo} out of range for mode {mode}, discarding")
            continue

        with _lock:
            if mode == CMD_MODE_RW_TORQUE:
                _latest_torque_mNm[rwNo] = value
                _wheel_received_at[rwNo] = time.monotonic()
            elif mode == CMD_MODE_MTR_CURRENT:
                _latest_mtr_current_mA[rwNo] = value
                _mtr_received_at[rwNo] = time.monotonic()
            else:
                print(f"firmware_sitl_link: mode={mode} (speed command) "
                      f"not yet supported, ignoring")


def get_latest_rw_torques_mNm():
    """Returns the 4 wheel torques (mNm) most recently commanded by the
    real firmware -- what satellite_rotational_dynamics_var_mag_field.py's
    new FIRMWARE_SITL mode branch feeds through torque_distribution's
    forward matrix to recover tau_actual."""
    with _lock:
        return list(_latest_torque_mNm)


def poll_mode():
    """Non-blocking, same pattern as poll_rw_torques() -- drains ALL
    pending mode-update packets this call. Call once per outer loop
    iteration, same cadence as poll_rw_torques()."""
    expected_len = struct.calcsize(MODE_STATUS_FORMAT)
    for _ in range(256):
        try:
            data, _ = _mode_sock.recvfrom(1024)
        except BlockingIOError:
            break

        if len(data) != expected_len:
            print(f"firmware_sitl_link: mode packet got {len(data)} bytes, "
                  f"expected {expected_len} -- discarding")
            continue

        mode, qw, qx, qy, qz, source = struct.unpack(MODE_STATUS_FORMAT, data)

        with _lock:
            if _latest_ads_mode[0] != mode:
                print(f"[DEBUG] mode_link: received mode byte {mode} "
                      f"(was {_latest_ads_mode[0]})")
            _latest_ads_mode[0] = mode
            _latest_fused_quaternion[0] = (qw, qx, qy, qz)
            _latest_fuse_source[0] = source
            _latest_fuse_received_at[0] = time.monotonic()


def get_latest_fuse_source_age_s():
    with _lock:
        stamp = _latest_fuse_received_at[0]
    return None if stamp is None else max(0., time.monotonic()-stamp)


def get_latest_fused_quaternion():
    """The firmware's latest attitude estimate (AdsMdl.fusedquat, w-x-y-z,
    body->ECI), or None before the first mode packet."""
    with _lock:
        return _latest_fused_quaternion[0]


def get_latest_fuse_source_name():
    """Which reference fuseAttitude() corrected toward on its last pass."""
    with _lock:
        return FUSE_SOURCE_NAMES.get(_latest_fuse_source[0], str(_latest_fuse_source[0]))


def get_latest_ads_mode_name():
    """Returns the real ADS mode's human-readable name (e.g. 'Safe',
    'NadirPoint') -- distinct from store.mode, which is always
    'FIRMWARE_SITL' regardless of which ADS mode is actually active.
    Falls back to the raw numeric value (as a string) for any mode not
    in the table above, rather than failing."""
    with _lock:
        raw = _latest_ads_mode[0]
    return _ADS_MODE_NAMES.get(raw, f"Unknown({raw})")


def mtr_dipole_per_amp():
    """Magnetorquer rod dipole per ampere, A*m^2/A -- the same dipole/current
    relation as compute_MTR_power()."""
    import MTR_parameters_P30xl as coil
    return (1+coil.gain_ratio)*np.pi*coil.r**2*coil.N*1e-6


def command_freshness(now=None):
    """Independent receive ages on wall time; status traffic cannot refresh commands."""
    import satellite_parameters as config
    now = time.monotonic() if now is None else now
    timeout = config.SIMULATION.firmware_command_timeout_s
    with _lock:
        wheel_ages = [None if t is None else max(0., now-t) for t in _wheel_received_at]
        rod_ages = [None if t is None else max(0., now-t) for t in _mtr_received_at]
    return dict(wheel_age_s=wheel_ages, rod_age_s=rod_ages,
                wheel_fresh=[age is not None and age < timeout for age in wheel_ages],
                rod_fresh=[age is not None and age < timeout for age in rod_ages],
                timeout_s=timeout)


def apply_actuator_limits(dt):
    """Latch achieved commands for one held physics step, in SI units.

    Positive wheel command produces positive body torque along its axis and
    negative rotor acceleration. Limit its impulse using the same dt used
    by the plant, so a nearly full wheel cannot overshoot its capacity.
    The magnetorquer dipole is the ACS-commanded rod current through the
    plant's coil model (the firmware's own coil constant, MTR_COIL_NA, is
    its model of the same rods), then bounded by the plant's current and
    dipole limits.
    """
    import satellite_parameters as config
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError('Actuator hold period must be finite and positive')
    freshness = command_freshness()
    with _lock:
        h = np.asarray(_wheel_momentum)
        limit = config.WHEEL_MAX_MOMENTUM_NMS
        lower = np.maximum(-config.WHEEL_MAX_TORQUE_NM, (h-limit)/dt)
        upper = np.minimum(config.WHEEL_MAX_TORQUE_NM, (h+limit)/dt)
        wheel_command = np.where(freshness['wheel_fresh'], _latest_torque_mNm, 0.)
        _applied_torque_Nm[:] = np.clip(wheel_command*1e-3, lower, upper)
        dipole_per_amp = mtr_dipole_per_amp()
        dipole_limit = np.minimum(config.MTR_MAX_DIPOLE_AM2,
                                 np.asarray(config.SPACECRAFT.mtr_max_current_A)*dipole_per_amp)
        rod_command = np.where(freshness['rod_fresh'], _latest_mtr_current_mA, 0.)
        dipole = np.clip(rod_command*1e-3*dipole_per_amp, -dipole_limit, dipole_limit)
        step = config.MTR_DIPOLE_STEP_AM2
        if step > 0:
            dipole_limit = np.floor(dipole_limit/step)*step
            dipole = np.round(dipole/step)*step
        dipole = np.clip(dipole, -dipole_limit, dipole_limit)
        return _applied_torque_Nm.copy(), dipole


def step_wheel_momentum(dt):
    """Advances the separate wheel-momentum bookkeeping estimate --
    dh/dt = -T_wheel, matching the firmware's own confirmed sign
    convention (control_laws.c's DEFAULT_DESATURATION_DIRECT_GAIN
    comment). Call once per outer loop iteration, same cadence as the
    main dynamics step."""
    with _lock:
        for i in range(4):
            torque_Nm = _applied_torque_Nm[i]
            _wheel_momentum[i] += -torque_Nm * dt


def get_wheel_momentum():
    with _lock:
        return np.asarray(_wheel_momentum, dtype=float).copy()


def set_wheel_momentum(momentum):
    import satellite_parameters as config
    h = np.asarray(momentum, dtype=float).reshape(4)
    if not np.all(np.isfinite(h)) or np.any(np.abs(h) > config.WHEEL_MAX_MOMENTUM_NMS+1e-8):
        raise ValueError('Invalid integrated wheel momentum')
    with _lock:
        _wheel_momentum[:] = np.clip(h, -config.WHEEL_MAX_MOMENTUM_NMS, config.WHEEL_MAX_MOMENTUM_NMS).tolist()


def send_rw_telemetry():
    """Sends each wheel's current speed/torque back to ACS SITL, for
    AcsHk.RWTlm[] -- same call cadence as telemetry.py's send_state()."""
    with _lock:
        momentum_snapshot = list(_wheel_momentum)
        torque_snapshot = list(_applied_torque_Nm * 1e3)

    for rwNo in range(4):
        omega_rad_s = momentum_snapshot[rwNo] / RW_MOI
        speed_rpm = omega_rad_s * 60.0 / (2.0 * 3.14159265358979323846)

        payload = struct.pack(TLM_FORMAT, float(rwNo), speed_rpm, torque_snapshot[rwNo])
        _tlm_sock.sendto(payload, (ACS_SITL_HOST, TLM_SEND_PORT))
