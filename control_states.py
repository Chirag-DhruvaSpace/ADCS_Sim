import threading
import time
import uuid

_lock = threading.Lock()

controls = {
    
    "yaw": 0.0,
    "pitch": 0.0,
    "roll": 0.0
}

# Control mode selected from the UI. One of:
#   "SUN_POINTING"  -> magnetorquer periodic-gain sun pointing
#   "RW"            -> reaction-wheel PD attitude control to slider (LVLH) target
#   "MOON"          -> reaction-wheel PD attitude control to moon-pointing target
#   "NADIR"         -> reaction-wheel PD attitude control to nadir-pointing target
#   "SUN_SWEEP"     -> reaction-wheel PD attitude control to sun-sweep target
#                      (NOT the same as "SUN_POINTING", which is the existing
#                      magnetorquer-based mode)
#   "SUN_POINTING_RW" -> reaction-wheel PD attitude control to plain sun
#                      pointing, SAME axis (body -Z) as "SUN_POINTING" --
#                      only the actuator/control law differs. NOT the same
#                      as "SUN_SWEEP", which uses body -X and oscillates.
#   "NOMINAL_IN_ORBIT" -> reaction-wheel PD+feedforward attitude control,
#                      same as "NADIR" but with a fixed 45deg yaw bias about
#                      the boresight (body +X). Does not change where the
#                      spacecraft looks, only the roll angle about that
#                      line of sight.
#   "KINEMATIC_ROBUSTNESS" -> reaction-wheel PD+feedforward attitude control,
#                      body +Z locked on nadir while continuously spinning
#                      about that same axis at a configurable rate (default
#                      1deg/s, see kinematic_robustness_pointing.py). Tests
#                      sustained pointing accuracy under nonzero body rates,
#                      NOT a bounded sweep like MOON/SUN_SWEEP.
# Detumbling is an automatic override handled in the dynamics when |omega| is high,
# so it is NOT a selectable mode here.
import numpy as np
import satellite_parameters as config
from quat2eul import quaternion_multiply, quaternion_inverse
MODES = ('FIRMWARE_SITL', 'CUSTOM', 'SUN_POINTING', 'RW', 'MOON', 'NADIR', 'SUN_SWEEP',
         'SUN_POINTING_RW', 'NOMINAL_IN_ORBIT', 'KINEMATIC_ROBUSTNESS')
mode = {"value": config.POINTING['legacy_mode'] if config.POINTING['strategy'] == 'legacy' else 'FIRMWARE_SITL' if config.POINTING['strategy'] == 'firmware_sitl' else 'CUSTOM'}
if mode['value'] not in MODES:
    raise ValueError('Invalid pointing.legacy_mode')

def _unit_quaternion(value):
    q = np.asarray(value, dtype=float)
    if q.shape != (4,) or not np.all(np.isfinite(q)) or np.max(np.abs(q)) < 1e-12:
        raise ValueError('Quaternion must contain four finite values and have nonzero norm')
    q = q / np.max(np.abs(q))
    return q / np.linalg.norm(q)

def _target(value, input_kind, reference):
    q = _unit_quaternion(value)
    if input_kind == 'desired_quaternion':
        return q
    if input_kind == 'quaternion_error':
        return _unit_quaternion(quaternion_multiply(_unit_quaternion(reference), quaternion_inverse(q)))
    raise ValueError('input must be desired_quaternion or quaternion_error')

_custom = config.POINTING['custom']
_custom_target = (_target(_custom['quaternion'], _custom['input'], _custom.get('reference_quaternion'))
                  if config.POINTING['strategy'] == 'custom' else np.array([1., 0., 0., 0.]))

_command_id = None
_command_received = None
_command_sequence = 0

def get_pointing_command():
    with _lock:
        return dict(command_id=_command_id, sequence=_command_sequence,
                    desired_quaternion=_custom_target.tolist(),
                    age_s=None if _command_received is None else max(0.0, time.monotonic()-_command_received))

def accept_pointing_command(command):
    global _custom_target, _command_id, _command_received, _command_sequence
    if config.POINTING['strategy'] != 'custom' or not command or not command.get('command_id'):
        return
    target = _unit_quaternion(command['desired_quaternion'])
    with _lock:
        if command['command_id'] == _command_id:
            return
        _custom_target = target
        _command_id = command['command_id']
        _command_sequence = command['sequence']
        _command_received = time.monotonic() - max(0.0, float(command.get('age_s') or 0))
        mode['value'] = 'CUSTOM'

def set_pointing_input(quaternion, *, input_kind='desired_quaternion', reference_quaternion=None):
    """Latch a CUSTOM ECI target; error = inverse(desired) * reference."""
    global _custom_target, _command_id, _command_received, _command_sequence
    if config.POINTING['strategy'] != 'custom':
        raise ValueError('Set pointing.strategy: custom in satellite_parameters.yaml and restart before sending quaternion commands')
    target = _target(quaternion, input_kind, reference_quaternion)
    with _lock:
        _custom_target = target
        _command_id = uuid.uuid4().hex
        _command_received = time.monotonic()
        _command_sequence += 1
        mode['value'] = 'CUSTOM'
    return target.tolist()

def get_pointing_target():
    with _lock:
        return _custom_target.copy()



def set_control(label, value):
    with _lock:
        if label in controls:
            controls[label] = float(value)

def get_controls():
    with _lock:
        return controls["yaw"], controls["pitch"], controls["roll"]


def set_mode(value):
    if value == 'FIRMWARE_SITL' and config.POINTING['strategy'] != 'firmware_sitl':
        raise ValueError('Firmware mode requires pointing.strategy: firmware_sitl')
    if config.POINTING['strategy'] == 'firmware_sitl' and value != 'FIRMWARE_SITL':
        raise ValueError('Firmware SITL owns actuator commands')
    if config.POINTING['strategy'] == 'custom' and value != 'CUSTOM':
        raise ValueError('Legacy mode commands require pointing.strategy: legacy')
    if config.POINTING['strategy'] == 'legacy' and value == 'CUSTOM':
        raise ValueError('Custom mode requires pointing.strategy: custom')
    with _lock:
        if value in MODES:
            mode["value"] = value

def get_mode():
    with _lock:
        return mode["value"]
