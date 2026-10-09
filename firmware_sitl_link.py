"""
firmware_sitl_link.py

Receives the 4 reaction-wheel torque commands from the real firmware
(via ACS SITL's acs_sim_link.c) and makes them available to
satellite_rotational_dynamics_var_mag_field.py's new "FIRMWARE_SITL" mode.

Mirrors telemetry.py's role/style exactly, but for the reverse direction --
same UDP, non-blocking, module-level-state pattern.

IMPORTANT SIMPLIFICATION, stated explicitly: this simulator's rotational
dynamics has NO wheel-speed/momentum state at all -- reaction_wheel_torque_
distribution()'s output (rw_t) is used only for display (confirmed
directly in satellite_rotational_dynamics_var_mag_field.py's own comment:
"we apply tau_body to the body and display the individual wheel torques").
So the wheel momentum tracked HERE is a separate, simple bookkeeping
estimate (dh/dt = -T_wheel, matching the firmware's own confirmed sign
convention), NOT fed back into the main body dynamics -- it exists only to
give the firmware's own wheelsNeedDesat()/gyroscopic-decoupling terms
something physically reasonable to read back as "wheel speed" telemetry.
"""

import socket
import struct
import threading

CMD_LISTEN_PORT = 5104     # matches ACS SITL's PYTHON_CMD_PORT (where it actually sends RW commands) --
                            # CORRECTED this session: was 5102, a leftover/wrong value; ACS SITL
                            # never sends to that port at all, only from it.
TLM_SEND_PORT = 5103        # matches ACS SITL's ACS_SIM_TLM_PORT (it listens HERE)
ACS_SITL_HOST = "127.0.0.1"

MODE_LISTEN_PORT = 5105     # matches ADS SITL's PYTHON_MODE_PORT -- new this session,
                            # carries the REAL ADS AdsMode (distinct from store.mode,
                            # which is always "FIRMWARE_SITL" regardless of the real mode)

CMD_FORMAT = "<3d"   # rwNo, mode(0=torque mNm, 1=speed), value -- matches acs_sim_link.h exactly
TLM_FORMAT = "<3d"   # rwNo, currspeed_rpm, actual_torque_mNm -- matches acs_sim_link.h exactly

RW_MOI = 5.4e-5   # kg*m^2 -- matches acs.h's confirmed value, reused here for the momentum estimate

_lock = threading.Lock()
_latest_torque_mNm = [0.0, 0.0, 0.0, 0.0]
_wheel_momentum = [0.0, 0.0, 0.0, 0.0]   # kg*m^2*rad/s, separate bookkeeping only -- see module docstring

_cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_cmd_sock.bind(("0.0.0.0", CMD_LISTEN_PORT))
_cmd_sock.setblocking(False)

_mode_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_mode_sock.bind(("0.0.0.0", MODE_LISTEN_PORT))
_mode_sock.setblocking(False)
_latest_ads_mode = [0]   # raw AdsMode byte value, 0 = AdcsMode_Safe

# EXTENDED this session: the mode packet now also carries
# bdotVars.controlMoment directly (mode_link.c's ModeLinkPacket, #pragma
# pack(1) -- 1 uint8 + 3 float32 = 13 bytes, matching this format string
# exactly). This is the ONLY channel carrying any MTR command to Python's
# physics at all -- satellite_rotational_dynamics_var_mag_field.py's own
# M = np.zeros(3) was a leftover "no MTR mode exists" assumption from when
# only Nadir/Sun-pointing (both RW-only) existed.
#
# SIMPLIFIED (this session): carries the physical dipole moment (Am^2)
# directly, PRE-mtrCurrDist() -- not the post-saturation, sign-magnitude-
# encoded current that function actually commands the hardware. By
# explicit request, trading testing mtrCurrDist()'s own saturation/
# encoding logic for a simpler pipeline.
MODE_STATUS_FORMAT = "<B3f"
_latest_mtr_dipole_Am2 = [0.0, 0.0, 0.0]

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
    while True:
        try:
            data, _ = _cmd_sock.recvfrom(1024)
        except BlockingIOError:
            break

        if len(data) != struct.calcsize(CMD_FORMAT):
            print(f"firmware_sitl_link: got {len(data)} bytes, expected "
                  f"{struct.calcsize(CMD_FORMAT)} -- discarding")
            continue

        rwNo_f, mode_f, value = struct.unpack(CMD_FORMAT, data)
        rwNo = int(round(rwNo_f))
        mode = int(round(mode_f))

        if not (0 <= rwNo <= 3):
            print(f"firmware_sitl_link: rwNo={rwNo} out of range, discarding")
            continue

        with _lock:
            if mode == 0:   # torque command, mNm
                _latest_torque_mNm[rwNo] = value
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
    while True:
        try:
            data, _ = _mode_sock.recvfrom(1024)
        except BlockingIOError:
            break

        if len(data) != expected_len:
            print(f"firmware_sitl_link: mode packet got {len(data)} bytes, "
                  f"expected {expected_len} -- discarding")
            continue

        mode, mx, my, mz = struct.unpack(MODE_STATUS_FORMAT, data)

        with _lock:
            if _latest_ads_mode[0] != mode:
                print(f"[DEBUG] mode_link: received mode byte {mode} "
                      f"(was {_latest_ads_mode[0]})")
            _latest_ads_mode[0] = mode
            _latest_mtr_dipole_Am2[0] = mx
            _latest_mtr_dipole_Am2[1] = my
            _latest_mtr_dipole_Am2[2] = mz


def get_latest_mtr_dipole_Am2():
    """Returns the real MTR dipole moment (A*m^2, body frame) the firmware
    actually commanded this cycle (detumbling_MM.c's bdotCalcTorq(), via
    bdotVars.controlMoment) -- sent directly, pre-mtrCurrDist(), so this is
    the control law's own output rather than the post-saturation encoded
    current."""
    with _lock:
        print(f"######################################################################{_latest_mtr_dipole_Am2}")
        return list(_latest_mtr_dipole_Am2)


def get_latest_ads_mode_name():
    """Returns the real ADS mode's human-readable name (e.g. 'Safe',
    'NadirPoint') -- distinct from store.mode, which is always
    'FIRMWARE_SITL' regardless of which ADS mode is actually active.
    Falls back to the raw numeric value (as a string) for any mode not
    in the table above, rather than failing."""
    with _lock:
        raw = _latest_ads_mode[0]
    return _ADS_MODE_NAMES.get(raw, f"Unknown({raw})")


def step_wheel_momentum(dt):
    """Advances the separate wheel-momentum bookkeeping estimate --
    dh/dt = -T_wheel, matching the firmware's own confirmed sign
    convention (control_laws.c's DEFAULT_DESATURATION_DIRECT_GAIN
    comment). Call once per outer loop iteration, same cadence as the
    main dynamics step."""
    with _lock:
        for i in range(4):
            torque_Nm = _latest_torque_mNm[i] * 1e-3
            _wheel_momentum[i] += -torque_Nm * dt


def send_rw_telemetry():
    """Sends each wheel's current speed/torque back to ACS SITL, for
    AcsHk.RWTlm[] -- same call cadence as telemetry.py's send_state()."""
    with _lock:
        momentum_snapshot = list(_wheel_momentum)
        torque_snapshot = list(_latest_torque_mNm)

    for rwNo in range(4):
        omega_rad_s = momentum_snapshot[rwNo] / RW_MOI
        speed_rpm = omega_rad_s * 60.0 / (2.0 * 3.14159265358979323846)

        payload = struct.pack(TLM_FORMAT, float(rwNo), speed_rpm, torque_snapshot[rwNo])
        _tlm_sock.sendto(payload, (ACS_SITL_HOST, TLM_SEND_PORT))