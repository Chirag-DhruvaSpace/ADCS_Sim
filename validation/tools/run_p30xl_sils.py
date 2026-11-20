"""Run the P-30XL ADS SILS model-boundary replay from satellite_parameters.yaml."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import csv
import ctypes as c
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from scipy.spatial.transform import Rotation
import satellite_parameters as cfg
from simulate_magnetorquers import SimulatedMagnetorquers
from validation.tools.build_firmware_sitl import build
from validation.tools.p30xl_sils_cases import cases

RAD_TO_DEG = 180. / np.pi
FUSION = ('gyro only', 'star tracker', 'TRIAD', 'Sun 2-DOF')


def cross(a, b):
    x, y, z = a
    u, v, w = b
    return np.array([y*w-z*v, z*u-x*w, x*v-y*u])


def unit(v):
    return v / np.linalg.norm(v)


def opened(windows, timestamp):
    return any(start <= timestamp < end for start, end in windows)


def apply_values(base, overrides):
    values = deepcopy(base)
    for key, value in overrides.items():
        section, field = key.split('.')
        values[section][field] = value
    return values


@contextmanager
def load_firmware(filename):
    from _ctypes import FreeLibrary

    library = c.CDLL(str(filename))
    try:
        for name in ('state', 'event'):
            lookup = getattr(library, f'p30xl_{name}_name')
            lookup.argtypes = [c.c_int]
            lookup.restype = c.c_char_p
        double_ptr = np.ctypeslib.ndpointer(dtype=np.float64, flags='C_CONTIGUOUS')
        int_ptr = np.ctypeslib.ndpointer(dtype=np.int32, flags='C_CONTIGUOUS')
        library.p30xl_init.argtypes = [c.c_uint64, c.c_int, c.c_int, double_ptr, c.c_int, double_ptr]
        library.p30xl_init.restype = None
        library.p30xl_period_ms.restype = c.c_uint
        library.p30xl_step.argtypes = [c.c_uint32, double_ptr, int_ptr, double_ptr, int_ptr, int_ptr]
        library.p30xl_step.restype = c.c_int
        yield library
    finally:
        FreeLibrary(library._handle)


def sample_environment(orbit, duration, period_ms):
    """Use the normal Orekit orbit, WMM/IGRF and Sun ephemeris."""
    import jdk4py
    os.environ.setdefault('JAVA_HOME', str(jdk4py.JAVA_HOME))
    from engine_adcs_bridge import EngineOrbitProvider

    original = cfg.SIMULATION
    cfg.SIMULATION = replace(original, orbit_output_window_s=max(30., original.orbit_output_window_s))
    try:
        provider = EngineOrbitProvider(epoch_utc=orbit.epoch_utc)
        spacing = 5.
        grid = np.arange(0., duration + spacing, spacing)
        columns = []
        for t in grid:
            position, velocity = provider.state_at(t)
            field = provider.magnetic_field_eci(t, position)
            sun = provider.sun_position_eci()
            columns.append(np.concatenate((position, velocity, field, sun)))
        ticks = np.arange(0, int(round(duration * 1000)) + 1, period_ms) / 1000
        return np.column_stack([np.interp(ticks, grid, series) for series in np.asarray(columns).T])
    finally:
        cfg.SIMULATION = original


def initial_state(settings, environment, mtr_pointing):
    q = np.asarray(settings.initial_quaternion_scalar_first)
    attitude = Rotation.from_quat(q, scalar_first=True)
    sun_error = settings.firmware_replay_initial_sun_error_deg
    if sun_error is not None:
        sun = unit(environment[9:12] - environment[:3])
        # Choose the roll reference used by the selected acquisition method.
        if mtr_pointing:
            reference = np.eye(3)[0 if abs(sun[0]) < .9 else 1]
        else:
            reference = np.eye(3)[2 if abs(sun[2]) <= .95 else 1]
        axis = unit(cross(reference, -sun))
        aligned = Rotation.from_matrix(np.column_stack((axis, cross(-sun, axis), -sun)))
        attitude = Rotation.from_rotvec(np.radians(sun_error) * axis) * aligned
    rate = np.array(settings.initial_body_rates_deg_s)
    if settings.firmware_replay_initial_rate_deg_s is not None:
        field_body = unit(attitude.inv().apply(environment[6:9]))
        perpendicular = unit(cross(field_body, np.eye(3)[np.argmin(np.abs(field_body))]))
        angle = np.radians(settings.firmware_replay_initial_rate_field_angle_deg)
        rate = settings.firmware_replay_initial_rate_deg_s * (
            np.cos(angle) * field_body + np.sin(angle) * perpendicular)
    return attitude, np.radians(rate)


class Plant:
    def __init__(self, spacecraft, wheels, disturbances):
        self.inertia = spacecraft.inertia_matrix
        self.inverse_inertia = np.linalg.inv(self.inertia)
        self.rods = SimulatedMagnetorquers(
            spacecraft.magnetorquers, max_dipole_Am2=spacecraft.mtr_max_dipole_Am2,
            dipole_step_Am2=spacecraft.mtr_dipole_step_Am2, max_current_A=spacecraft.mtr_max_current_A)
        self.axis = np.array(wheels.firmware_axis_matrix_body) if wheels.firmware_axis_matrix_body else wheels.wheel_axes_body
        self.momentum = np.array(wheels.initial_momentum_Nms)
        self.wheels = wheels
        self.disturbances = disturbances

    def commands(self, rod_current_a, wheel_torque_nm, field_body, dt):
        magnetic = self.rods.apply_currents(rod_current_a, field_body)
        wheel = np.zeros(4) if self.wheels.firmware_replay_unavailable else np.clip(
            wheel_torque_nm, -self.wheels.max_torque_Nm, self.wheels.max_torque_Nm)
        # Match firmware_sitl_link: positive command torques the bus and
        # removes momentum from the rotor along the configured axis.
        new_momentum = np.clip(self.momentum - dt * wheel,
                               -self.wheels.max_momentum_Nms, self.wheels.max_momentum_Nms)
        delivered = (self.momentum - new_momentum) / dt
        return magnetic, delivered, new_momentum

    def advance(self, attitude, rate, position, field_body, magnetic, wheel_torque, new_momentum, dt):
        wheel_h = self.axis @ ((self.momentum + new_momentum) * .5)
        torque = magnetic.torque_body_Nm + self.axis @ wheel_torque
        disturbance = self.disturbances
        if disturbance.enabled and disturbance.gravity_gradient_enabled:
            radius = np.linalg.norm(position)
            radial_body = attitude.inv().apply(position / radius)
            torque += (3 * 3.986004418e14 / radius**3) * cross(radial_body, self.inertia @ radial_body)
        if disturbance.enabled and disturbance.residual_dipole_enabled:
            torque += cross(disturbance.residual_dipole_Am2, field_body)

        def acceleration(omega):
            return self.inverse_inertia @ (torque - cross(omega, self.inertia @ omega + wheel_h))

        k1 = acceleration(rate)
        k2 = acceleration(rate + .5 * dt * k1)
        k3 = acceleration(rate + .5 * dt * k2)
        k4 = acceleration(rate + dt * k3)
        next_rate = rate + (dt / 6) * (k1 + 2*k2 + 2*k3 + k4)
        attitude *= Rotation.from_rotvec(.5 * dt * (rate + next_rate))
        self.momentum = new_momentum
        return attitude, next_rate


def compare_mbd(configuration, environment, attitude, rates, dt, firmware_time):
    """Run the existing model-based bang-bang law on the same prescribed orbit and plant."""
    spacecraft, _, _, _, _, disturbances, _, wheels, simulation, *_ = configuration
    plant = Plant(spacecraft, wheels, disturbances)
    rate = np.radians(rates)
    maximum_current = 0.
    matching_rate = first_crossing = None
    max_index = min(len(environment) - 1, round(simulation.default_duration_s / dt))
    matched_index = round(firmware_time / dt)
    # Carry the reference through the firmware event timestamp for a like-time comparison.
    for index, env in enumerate(environment[:max_index + 1]):
        t = round(index * dt, 3)
        rate_deg = np.linalg.norm(rate) * RAD_TO_DEG
        if first_crossing is None and rate_deg < 1.:
            first_crossing = t
        if index == matched_index:
            matching_rate = float(rate_deg)
        field_body = attitude.inv().apply(env[6:9])
        desired = plant.rods.detumble(rate, field_body)
        magnetic, wheel, momentum = plant.commands(desired.currents_A, np.zeros(4), field_body, dt)
        maximum_current = max(maximum_current, float(np.max(np.abs(magnetic.currents_A))))
        if index >= matched_index and (first_crossing is not None or not all(plant.rods.available)):
            break
        attitude, rate = plant.advance(attitude, rate, env[:3], field_body, magnetic, wheel, momentum, dt)
    return dict(mbd_below_1_deg_s_at_s=first_crossing, mbd_observation_s=t,
                mbd_rate_at_firmware_end_deg_s=matching_rate, mbd_peak_rod_A=maximum_current)


def run_case(firmware, name, configuration, environment, output_path, *, compare_model):
    spacecraft, orbit, attitude_cfg, _, control, disturbances, _, wheels, simulation, gps, imu, _ = configuration
    plant = Plant(spacecraft, wheels, disturbances)
    sun_cfg = imu.sun_array
    dt_ms = firmware.p30xl_period_ms()
    dt = dt_ms / 1000.
    attitude, rate = initial_state(attitude_cfg, environment[0], wheels.firmware_replay_unavailable)
    initial_quat = attitude.as_quat(scalar_first=True)
    initial_rates = np.degrees(rate).tolist()
    resume_sun = control.firmware_replay_start_mode == 'sun_pointing'
    method = control.firmware_replay_bdot_method
    signs = np.asarray(control.firmware_replay_bdot_gain_signs, dtype=float)
    firmware.p30xl_init(int(orbit.epoch_utc.timestamp()), resume_sun,
                        method == 'finite_difference', signs, control.firmware_replay_sun_two_dof_enabled,
                        initial_quat)
    sample, out = np.zeros(27), np.zeros(23)
    flags, status, event_trace = np.zeros(9, dtype=np.int32), np.zeros(8, dtype=np.int32), np.zeros(24, dtype=np.int32)
    flags[4:7] = plant.rods.available
    flags[7] = not wheels.firmware_replay_unavailable
    normals = np.asarray([head.normal_body for head in sun_cfg.cells if head.enabled]).reshape(-1, 3)
    min_cos = np.cos(sun_cfg.fine_fov_half_angle_rad)
    mode_counts, fusion_counts, pre_fault_fusion, post_fault_fusion = Counter(), Counter(), Counter(), Counter()
    changes, search_changes = [], []
    state_previous = search_previous = field_previous = None
    bdot_peak = motor_peak = rod_peak = command_peak = max_law_error = 0.
    peak_momentum = 0.
    pre_fault_state = pre_fault_source = post_fault_state = post_fault_source = None
    threshold_s = achieved_s = None
    energies, angles = [], []
    fault_starts = [window[0] for windows in (gps.outages_s, gps.firmware_replay_position_outages_s,
                    imu.star_tracker.outages_s) for window in windows]
    fault_start = min(fault_starts, default=float('inf'))
    duration = float(simulation.default_duration_s)
    if not resume_sun and not all(plant.rods.available):
        duration = min(duration, 10.)  # Capture steady output after the terminal fault route.
    columns = ('t_s', 'state', 'mode_byte', 'fusion', 'gps_receipt', 'gps_healthy', 'position_usable',
               'sun_observation', 'eclipse', 'sun_error_deg', 'fused_error_deg', 'rate_deg_s',
               'wx_deg_s', 'wy_deg_s', 'wz_deg_s', 'energy_J', 'current_x_A', 'current_y_A', 'current_z_A',
               'wheel_1_Nm', 'wheel_2_Nm', 'wheel_3_Nm', 'wheel_4_Nm',
               'Bx_uT', 'By_uT', 'Bz_uT', 'bdot_mx', 'bdot_my', 'bdot_mz',
               'search_count', 'search_axis', 'target_qw', 'target_qx', 'target_qy', 'target_qz', 'achieved',
               'truth_qw', 'truth_qx', 'truth_qy', 'truth_qz', 'target_tracking_error_deg')
    with output_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for index, env in enumerate(environment[:int(round(duration / dt)) + 1]):
            t = round(index * dt, 3)
            position = env[:3]
            sun = unit(env[9:12] - position)
            inverse = attitude.inv()
            field = inverse.apply(env[6:9])
            sun_body = inverse.apply(sun)
            # Cylindrical shadow at the model boundary. Search tests can hold illumination fixed.
            along_sun = float(position @ sun)
            eclipse = (not sun_cfg.firmware_replay_continuous_sunlight and along_sun < 0
                       and position @ position - along_sun**2 < 6378137.**2)
            sun_visible = (not eclipse and sun_cfg.enabled and not opened(sun_cfg.outages_s, t)
                           and not opened(sun_cfg.firmware_replay_observation_outages_s, t)
                           and np.any(normals @ sun_body >= min_cos))
            sample[:6] = env[:6]
            sample[6:10] = attitude.as_quat(scalar_first=True)
            sample[10:13] = rate * RAD_TO_DEG
            sample[13:16] = field * 1e6
            sample[16:19] = env[6:9] * 1e6
            sample[20:24] = plant.momentum / wheels.rotor_inertia_kg_m2 * (60. / (2 * np.pi))
            sample[24:] = sun_body if sun_visible else 0.
            flags[0] = gps.enabled and not opened(gps.outages_s, t) and not opened(gps.firmware_replay_position_outages_s, t)
            flags[1] = not opened(gps.firmware_replay_position_outages_s, t)
            flags[2] = eclipse
            flags[3] = (imu.star_tracker.enabled and not opened(imu.star_tracker.outages_s, t)
                        and np.linalg.norm(sample[10:13]) < imu.star_tracker.tracking_rate_limit_deg_s)
            flags[8] = (control.firmware_replay_sun_reentry_s is not None
                        and index == round(control.firmware_replay_sun_reentry_s / dt))
            count = firmware.p30xl_step(index * dt_ms, sample, flags, out, status, event_trace)
            if not np.isfinite(out).all():
                raise RuntimeError(f'{name} produced nonfinite firmware output at {t:.1f} s')
            state = firmware.p30xl_state_name(int(status[0])).decode()
            fusion = FUSION[status[2]]
            mode_counts[state] += 1
            fusion_counts[fusion] += 1
            (pre_fault_fusion if t < fault_start else post_fault_fusion)[fusion] += 1
            if t < fault_start:
                pre_fault_state, pre_fault_source = state, fusion
            elif post_fault_state is None:
                post_fault_state, post_fault_source = state, fusion
            if count:
                for previous, event, following in event_trace[:3*count].reshape(-1, 3):
                    changes.append([t, firmware.p30xl_state_name(int(previous)).decode(),
                                    firmware.p30xl_event_name(int(event)).decode(),
                                    firmware.p30xl_state_name(int(following)).decode()])
            search_key = (int(status[4]), int(status[5]), *out[14:18])
            if status[4] and (search_key != search_previous or count):
                search_changes.append([t, *search_key])
                search_previous = search_key
            rate_deg = float(np.linalg.norm(sample[10:13]))
            if threshold_s is None and rate_deg < 1.:
                threshold_s = t
            if achieved_s is None and status[3]:
                achieved_s = t
            if method == 'finite_difference':
                law = np.zeros(3) if field_previous is None else -(sample[13:16] - field_previous) / dt
            else:
                law = cross(sample[10:13], sample[13:16])
            max_law_error = max(max_law_error, float(np.max(np.abs(signs * law - out[:3]))))
            bdot_peak = max(bdot_peak, float(np.linalg.norm(out[:3])))
            field_previous = sample[13:16].copy()
            magnetic, wheel_torque, next_momentum = plant.commands(out[3:6] * .001, out[6:10], field, dt)
            rod_peak = max(rod_peak, float(np.max(np.abs(magnetic.currents_A))))
            command_peak = max(command_peak, float(np.max(np.abs(out[3:6]))))
            motor_peak = max(motor_peak, float(np.max(np.abs(wheel_torque))))
            peak_momentum = max(peak_momentum, float(np.max(np.abs(next_momentum))))
            angle = float(np.arccos(np.clip(-sun_body[2], -1, 1)) * RAD_TO_DEG)
            energy = float(.5 * rate @ plant.inertia @ rate)
            angles.append(angle)
            energies.append(energy)
            if index < 3 or index % round(5 / dt) == 0 or count or state != state_previous or t == duration:
                fused_error = float(2 * np.arccos(np.clip(abs(sample[6:10] @ unit(out[10:14])), 0, 1)) * RAD_TO_DEG)
                target = out[14:18]
                target_error = (float(2 * np.arccos(np.clip(abs(sample[6:10] @ unit(target)), 0, 1)) * RAD_TO_DEG)
                                if np.linalg.norm(target) > 0 else None)
                writer.writerow((round(t, 3), state, status[1], fusion, flags[0], status[6], flags[1],
                                 int(sun_visible), int(eclipse), angle, fused_error, rate_deg, *sample[10:13],
                                 energy, *magnetic.currents_A, *wheel_torque, *sample[13:16], *out[:3],
                                 status[4], status[5], *target, status[3], *sample[6:10], target_error))
            state_previous = state
            if not resume_sun and state != 'Detumbling_MM' and all(plant.rods.available):
                break
            attitude, rate = plant.advance(attitude, rate, position, field, magnetic, wheel_torque, next_momentum, dt)
    last_60 = angles[-round(60/dt):]
    before = angles[max(0, round((fault_start - 60.)/dt)):round(fault_start/dt)] if np.isfinite(fault_start) else []
    after = angles[round(fault_start/dt):] if np.isfinite(fault_start) else []
    tail = min(len(energies), round(60 / dt))
    result = dict(case=name, duration_s=t, cad=spacecraft.configuration, epoch_utc=orbit.epoch_utc.isoformat(),
                initial_quaternion=initial_quat.tolist(), initial_rates_deg_s=initial_rates,
                final_rates_deg_s=sample[10:13].tolist(), final_rate_deg_s=rate_deg, below_1_deg_s_at_s=threshold_s,
                energy_initial_J=energies[0], energy_final_J=energies[-1], energy_tail_mean_J=float(np.mean(energies[-tail:])),
                energy_at_600_s_J=energies[round(600/dt)] if t >= 600 else None,
                peak_commanded_rod_mA=command_peak, peak_delivered_rod_A=rod_peak, peak_delivered_wheel_Nm=motor_peak,
                peak_wheel_momentum_Nms=peak_momentum,
                final_delivered_rod_A=magnetic.currents_A.tolist(), bdot_max_law_residual=max_law_error, bdot_peak=bdot_peak,
                initial_sun_error_deg=angles[0], minimum_sun_error_deg=min(angles), final_sun_error_deg=angles[-1],
                final_60_s_max_error_deg=max(last_60), sun_achieved_flag_at_s=achieved_s,
                pre_fault_60_s_max_error_deg=max(before, default=None), post_fault_max_error_deg=max(after, default=None),
                state_counts=dict(mode_counts), fusion_counts=dict(fusion_counts),
                pre_fault_fusion_counts=dict(pre_fault_fusion), post_fault_fusion_counts=dict(post_fault_fusion),
                pre_fault_state=pre_fault_state if np.isfinite(fault_start) else None,
                pre_fault_source=pre_fault_source if np.isfinite(fault_start) else None,
                post_fault_state=post_fault_state, post_fault_source=post_fault_source,
                transitions=changes, search_changes=search_changes, final_state=state)
    if compare_model:
        result.update(compare_mbd(configuration, environment, Rotation.from_quat(initial_quat, scalar_first=True),
                                  initial_rates, dt, t))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--suite', action='store_true', help='Apply the 65 matrix YAML value overlays')
    selection.add_argument('--case', choices=cases(), help='Apply one matrix YAML value overlay')
    parser.add_argument('--label', choices=cases(), help='Label a run whose case values are already in the YAML')
    parser.add_argument('--output', type=Path, default=ROOT.parents[1] / 'P30XL_SILS_Results')
    args = parser.parse_args()
    if args.label and (args.case or args.suite):
        parser.error('--label is for a manual YAML run')
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    base = cfg._read_parameter_yaml(cfg.ACTIVE_PARAMETER_PATH)
    if cfg.ACTIVE_PARAMETER_PATH.name != 'satellite_parameters.yaml':
        raise ValueError('Set active_satellite_parameters: null in satellite_parameters.yaml to select P-30XL')
    matrix = cases()
    selected = matrix if args.suite else {args.case: matrix[args.case]} if args.case else {args.label or 'configured': {}}
    build_dir = ROOT.parents[1] / '.p30xl-build'
    build_dir.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='replay-', dir=build_dir) as workspace:
        work_path = Path(workspace)
        library = work_path / 'p30xl.dll'
        build(library, shared=True, extra_sources=[ROOT / 'validation/p30xl_sils_driver.c'],
              defines=['SITL_REPLAY'], object_directory=work_path / 'objects')
        execute(library, base, selected, output)


def execute(library, base, selected, output):
    matrix = cases()
    duration = max(overrides.get('simulation.default_duration_s', cfg.SIMULATION.default_duration_s)
                   for overrides in selected.values())
    with load_firmware(library) as firmware:
        environment = sample_environment(cfg.ORBIT, duration, firmware.p30xl_period_ms())
    for name, overrides in selected.items():
        values = apply_values(base, overrides)
        configuration = cfg._load_configuration(cfg.ACTIVE_PARAMETER_PATH, values=values)
        compare_model = name.startswith('DET-') and int(name[4:]) <= 41
        with load_firmware(library) as firmware:
            result = run_case(firmware, name, configuration, environment, output / f'{name}.csv',
                              compare_model=compare_model)
        result['yaml_changes'] = overrides or {key: values[section][field]
            for key in matrix.get(name, {}) for section, field in [key.split('.')]}
        (output / f'{name}.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(f"{name} {result['final_state']} at {result['duration_s']:.1f} s, "
              f"rate {result['final_rate_deg_s']:.3f} deg/s, Sun error {result['final_sun_error_deg']:.2f} deg", flush=True)


if __name__ == '__main__':
    main()
