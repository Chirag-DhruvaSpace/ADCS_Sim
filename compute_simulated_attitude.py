"""Onboard measurement holder and multiplicative attitude/bias EKF.

Only sensor receipts and onboard reference models enter this module.
Truth comparisons belong to operator telemetry, never filter updates.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass


def _dcm_bi_from_q(quaternion):
    quaternion = np.asarray(quaternion, dtype=float).reshape(4)
    quaternion = quaternion / np.linalg.norm(quaternion)
    scalar, vector_x, vector_y, vector_z = quaternion
    return np.array([
        [1 - 2 * (vector_y**2 + vector_z**2),
         2 * (vector_x * vector_y + scalar * vector_z),
         2 * (vector_x * vector_z - scalar * vector_y)],
        [2 * (vector_x * vector_y - scalar * vector_z),
         1 - 2 * (vector_x**2 + vector_z**2),
         2 * (vector_y * vector_z + scalar * vector_x)],
        [2 * (vector_x * vector_z + scalar * vector_y),
         2 * (vector_y * vector_z - scalar * vector_x),
         1 - 2 * (vector_x**2 + vector_y**2)],
    ])

@dataclass
class DecodedVector:
    """Onboard SI measurement; no simulator error realization attached."""
    t_meas_s: float
    t_arrival_s: float
    valid: bool
    saturated: bool
    omega_body_rad_s: object = None
    magnetic_field_body_t: object = None


def reconstruct_sun(outputs, normals, activation_threshold, min_cells=3):
    """Flight reconstruction from photocurrents and calibrated mount normals only."""
    outputs, normals = np.asarray(outputs, float), np.asarray(normals, float)
    normals = normals / np.linalg.norm(normals, axis=1)[:, None]
    mask = np.isfinite(outputs) & (outputs > activation_threshold)
    if np.count_nonzero(mask) < min_cells:
        return None, False, 'insufficient_cells', mask
    A = normals[mask]
    if np.linalg.matrix_rank(A) != 3:
        return None, False, 'degenerate_geometry', mask
    s = np.linalg.lstsq(A, outputs[mask], rcond=None)[0]
    length = np.linalg.norm(s)
    if length < 1e-12:
        return None, False, 'degenerate_geometry', mask
    return s / length, True, 'least_squares', mask


def decode_vector_sample(sample, sensor_kind, configuration):
    """Convert signed sensor registers to SI values in satellite body axes."""
    if sample is None:
        return None
    if sample.kind != sensor_kind:
        raise ValueError('Unexpected raw sensor kind')
    counts = np.asarray(sample.counts)
    if counts.shape != (3,) or not np.all(np.isfinite(counts)):
        raise ValueError('Sensor must return three finite register values')
    if np.any(counts != np.rint(counts)) or np.any(counts < -32768) or np.any(counts > 32767):
        raise ValueError('Sensor registers must be signed 16-bit integers')
    if sensor_kind == 'gyro':
        from simulate_gyroscope import gyro_register_scale_rad_s
        scale = gyro_register_scale_rad_s(configuration.gyro_hardware_range_deg_s)
        mount = configuration.gyro_mount_quaternion
    else:
        scale = 150e-9
        mount = configuration.mag_mount_quaternion
    sensor_vector = counts * scale
    body_vector = _dcm_bi_from_q(mount) @ sensor_vector
    decoded = DecodedVector(sample.t_meas_s, sample.t_arrival_s, sample.valid, sample.saturated)
    if sensor_kind == 'gyro':
        decoded.omega_body_rad_s = body_vector
    else:
        decoded.magnetic_field_body_t = body_vector
    return decoded


def decode_vector_group(readings, sensor_kind, configuration):
    if not isinstance(readings, list):
        return decode_vector_sample(readings, sensor_kind, configuration)
    decoded_units = []
    for unit_index, (unit, reading) in enumerate(readings):
        unit_configuration = configuration.unit_config(sensor_kind, unit, unit_index)
        decoded = decode_vector_sample(reading, sensor_kind, unit_configuration)
        decoded_units.append((unit, decoded))
    return decoded_units


def fine_sensor_body_direction(sensor, cell_configuration, sun_configuration):
    """Return a trusted local FSS vector rotated into body axes, or None."""
    from simulate_sunsensor import sensor_to_body_matrix
    data = sensor.data
    signal_counts = data['Q1'] + data['Q2'] + data['Q3'] + data['Q4']
    if signal_counts < sun_configuration.fine_eclipse_threshold_counts:
        return None
    if abs(data['Alpha']) > 3500 or abs(data['Beta']) > 3500:
        return None
    direction_sensor = np.array([data['VecX'], data['VecY'], data['VecZ']], dtype=float)
    direction_length = np.linalg.norm(direction_sensor)
    if direction_length == 0:
        return None
    mounting = sensor_to_body_matrix(cell_configuration.normal_body, cell_configuration.sensor_roll_rad)
    return mounting @ (direction_sensor / direction_length)


def decode_sun_sample(sample, configuration):
    """Reconstruct the configured photocells, then try fine sensor vectors."""
    from simulate_sunsensor import SunArrayMeasurement, SunCellSample
    if sample is None:
        return None
    expected_names = tuple(cell.name for cell in configuration.cells)
    if sample.adc_bits != configuration.cells[0].adc_bits:
        raise ValueError('Sun ADC resolution does not match configuration')
    if tuple(cell.name for cell in sample.cells) != expected_names:
        raise ValueError('Sun photocell names do not match configuration')
    full_scale_count = 2**sample.adc_bits - 1
    decoded_cells = []
    for cell in sample.cells:
        if not 0 <= cell.adc_counts <= full_scale_count:
            raise ValueError('Invalid photocell register')
        fraction = cell.adc_counts / full_scale_count
        angle_deg = None
        if fraction > 0:
            angle_deg = float(np.degrees(np.arccos(fraction)))
        decoded_cells.append(SunCellSample(
            name=cell.name, output_fraction=fraction, output_pct=fraction * 100,
            adc_counts=cell.adc_counts, angle_deg=angle_deg, used=False,
            in_fov=None, shadowed=None, saturated=cell.saturated,
            eclipse_factor_applied=None, albedo_fraction=None))
    decoded = SunArrayMeasurement(sample.t_meas_s, sample.t_arrival_s,
        decoded_cells, None, False, 'not_processed', sample.valid)
    # The provisional fine-sensor interface must not narrow the configured
    # photocells' field of view. Use their ADC readings whenever geometry allows.
    direction, good, method, used = reconstruct_sun(
        [cell.output_fraction for cell in decoded_cells],
        [cell.normal_body for cell in configuration.cells],
        configuration.activation_threshold, configuration.min_cells_for_solution)
    if good:
        decoded.reconstructed_body = direction
        decoded.reconstruction_valid = True
        decoded.method = method
        for cell, is_used in zip(decoded_cells, used):
            cell.used = bool(is_used)
        return decoded
    if not sample.sensors:
        return decoded
    if tuple(sensor.name for sensor in sample.sensors) != expected_names:
        raise ValueError('Fine sun sensor names do not match configuration')
    accepted_directions = []
    for sensor, cell_configuration, cell in zip(sample.sensors, configuration.cells, decoded_cells):
        direction = fine_sensor_body_direction(sensor, cell_configuration, configuration)
        cell.used = direction is not None
        if direction is not None:
            accepted_directions.append(direction)
    decoded.method = 'fine_sensor_vectors'
    if not accepted_directions:
        return decoded
    direction_sum = np.sum(accepted_directions, axis=0)
    direction_length = np.linalg.norm(direction_sum)
    if direction_length > 1e-12:
        decoded.reconstructed_body = direction_sum / direction_length
        decoded.reconstruction_valid = True
    return decoded


class ImuNav:
    """Hold the latest good gyro + magnetometer samples (the sensor belief).

    fallback_omega_rad_s / fallback_B_body_t are returned until the first
    good sample arrives (zero by default; never initialized from truth by
    the simulation loop). valid flags go False on a
    dropout tick but the last good sample is KEPT (a real flight computer
    coasts on its last good reading and marks it stale).
    """

    def __init__(self, fallback_omega_rad_s=None, fallback_B_body_t=None,
                 initial_quaternion=(1., 0., 0., 0.), sun_config=None,
                 filter_options=None, estimator_enabled=True,
                 enable_gyro_update=True, enable_magnetometer_update=True,
                 enable_sun_update=True, fusion_max_age_s=.5,
                 fusion_max_time_skew_s=.02) -> None:
        self.sun_config = sun_config
        self.estimator = AttitudeEstimator(initial_quaternion, **(filter_options or {}))
        self.estimator_enabled = bool(estimator_enabled)
        self.enable_gyro_update = bool(enable_gyro_update)
        self.enable_magnetometer_update = bool(enable_magnetometer_update)
        self.enable_sun_update = bool(enable_sun_update)
        self.fusion_max_age_s = fusion_max_age_s
        self.fusion_max_time_skew_s = fusion_max_time_skew_s
        self.estimator.star_tracker_max_age_s = fusion_max_age_s
        self._star_tracker = None
        self._unit_receipts = {'gyro': {}, 'mag': {}}
        self._unit_status = {'gyro': [], 'mag': []}
        self._omega = (np.zeros(3) if fallback_omega_rad_s is None
                       else np.asarray(fallback_omega_rad_s, dtype=float).reshape(3))
        self._B = (np.zeros(3) if fallback_B_body_t is None
                   else np.asarray(fallback_B_body_t, dtype=float).reshape(3))
        self._gyro = None
        self._mag = None
        self._sun = None
        self._gyro_valid = False       # a good gyro sample exists AND latest tick good
        self._mag_valid = False
        self._sun_valid = False
        self._gyro_saturated = False
        self._mag_saturated = False
        self._gyro_t_meas = None
        self._mag_t_meas = None
        self._sun_t_meas = None

    def update(self, t_seconds, gyro, mag, sun=None, star_tracker=None) -> None:
        """Store this tick's sensor outputs (any may be None = no tick).

        A returned measurement with valid=False is a DROPOUT sample: the
        valid flag goes False but the last good value is kept (coast).
        `star_tracker` is an optional absolute-attitude receipt; existing
        gyro/magnetometer/Sun callers keep their original interface.
        `sun` is the sun ARRAY receipt (SunArrayMeasurement from
        simulate_sunsensor.py); reconstruction_valid is a separate, softer
        flag -- a valid receipt may still carry reconstructed_body=None
        (eclipse/degenerate geometry), which is NOT a dropout.
        """
        if star_tracker is not None:
            self._star_tracker = star_tracker
        if isinstance(gyro, list):
            gyro = self._fuse_units(t_seconds, gyro, 'gyro')
        if isinstance(mag, list):
            mag = self._fuse_units(t_seconds, mag, 'mag')
        if gyro is not None:
            if gyro.valid:
                self._gyro = gyro
                self._omega = np.asarray(gyro.omega_body_rad_s, dtype=float).reshape(3)
                self._gyro_valid = True
                self._gyro_t_meas = float(gyro.t_meas_s)
            else:
                self._gyro_valid = False
            self._gyro_saturated = bool(gyro.saturated)
        if mag is not None:
            if mag.valid:
                self._mag = mag
                self._B = np.asarray(mag.magnetic_field_body_t, dtype=float).reshape(3)
                self._mag_valid = True
                self._mag_t_meas = float(mag.t_meas_s)
            else:
                self._mag_valid = False
            self._mag_saturated = bool(mag.saturated)
        if sun is not None:
            if sun.valid:
                if self.sun_config is not None and sun.method != 'fine_sensor_vectors':
                    from dataclasses import replace
                    configuration = self.sun_config
                    direction, good, method, mask = reconstruct_sun(
                        [c.output_fraction for c in sun.cells],
                        [c.normal_body for c in configuration.cells], configuration.activation_threshold,
                        configuration.min_cells_for_solution)
                    sun = replace(sun, reconstructed_body=direction,
                                  reconstruction_valid=good, method=method,
                                  cells=[replace(c, used=bool(u)) for c, u in zip(sun.cells, mask)])
                self._sun = sun                      # latest good RECEIPT kept
                self._sun_valid = True
                self._sun_t_meas = float(sun.t_meas_s)
            else:
                self._sun_valid = False              # dropout: keep last receipt

    def process_raw_data(self, t_seconds, gyro, mag, sun, config, star_tracker=None):
        """Decode raw sensors, then pass their SI measurements to navigation."""
        if not config.enable_star_tracker:
            # Disabling the tracker must also discard an earlier cached receipt.
            self._star_tracker = None
            star_tracker = None
        gyro_measurement = decode_vector_group(gyro, 'gyro', config)
        magnetic_measurement = decode_vector_group(mag, 'mag', config)
        sun_measurement = decode_sun_sample(sun, config.sun_array)
        if sun is not None:
            self.sun_config = config.sun_array
        self.update(t_seconds, gyro_measurement, magnetic_measurement, sun_measurement,
                    star_tracker=star_tracker)



    def get_processed_data(self):
        """Replaceable satellite input: SI body vectors and estimated attitude."""
        return dict(omega_body_rad_s=self.omega_body(),
                    magnetic_field_body_t=self.B_body(),
                    quaternion_eci=self.estimator.q_eci,
                    sun_body=self.sun_body())

    def omega_body(self) -> np.ndarray:
        """Best-known body rate [X, Y, Z] (rad/s) -- SENSOR belief, not truth."""
        return self._omega.copy() - self.estimator.bias

    def _fuse_units(self, t, incoming, kind):
        """Calibrate fresh units and combine them using configured confidence."""
        from dataclasses import replace
        from types import SimpleNamespace
        time_s = float(t)
        cache = self._unit_receipts[kind]
        present_names = {unit.name for unit, _ in incoming}
        for unit_name in list(cache):
            if unit_name not in present_names:
                del cache[unit_name]
        for unit, measurement in incoming:
            if measurement is not None:
                cache[unit.name] = (unit, measurement)

        usable_readings = []
        for unit, measurement in cache.values():
            age_s = time_s - measurement.t_meas_s
            fresh = 0 <= age_s <= self.fusion_max_age_s
            if measurement.valid and not measurement.saturated and fresh:
                usable_readings.append((unit, measurement))
        newest_time_s = max((measurement.t_meas_s for _, measurement in usable_readings), default=time_s)
        synchronized_readings = []
        for unit, measurement in usable_readings:
            if newest_time_s - measurement.t_meas_s <= self.fusion_max_time_skew_s:
                synchronized_readings.append((unit, measurement))
        selected_names = {unit.name for unit, _ in synchronized_readings}
        self._unit_status[kind] = []
        for unit, measurement in cache.values():
            self._unit_status[kind].append({
                'name': unit.name, 'used': unit.name in selected_names,
                'valid': bool(measurement.valid), 'saturated': bool(measurement.saturated),
                'age_s': max(0.0, time_s - measurement.t_meas_s)})
        if not synchronized_readings:
            return SimpleNamespace(valid=False, saturated=False)

        measurement_field = 'omega_body_rad_s' if kind == 'gyro' else 'magnetic_field_body_t'
        weights = []
        calibrated_vectors = []
        measurement_times = []
        for unit, measurement in synchronized_readings:
            measured_vector = np.asarray(getattr(measurement, measurement_field))
            without_bias = measured_vector - unit.calibration_bias
            calibrated_vector = np.linalg.solve(unit.calibration_matrix, without_bias)
            weights.append(unit.fusion_weight)
            calibrated_vectors.append(calibrated_vector)
            measurement_times.append(measurement.t_meas_s)
        normalized_weights = np.asarray(weights) / np.sum(weights)
        combined_vector = np.average(calibrated_vectors, axis=0, weights=normalized_weights)
        combined_time_s = sum(weight * sample_time for weight, sample_time in zip(normalized_weights, measurement_times))
        return replace(synchronized_readings[0][1],
            **{measurement_field: combined_vector}, t_meas_s=float(combined_time_s),
            t_arrival_s=time_s, valid=True, saturated=False)


    def estimate(self, t_seconds, magnetic_model_eci, sun_model_eci):
        """Fuse receipts using onboard reference models, with no truth input."""
        self.estimator.update(t_seconds,
                              self._omega if self.enable_gyro_update else self.estimator.bias.copy(),
                              self._mag if self.estimator_enabled and self.enable_magnetometer_update and self._mag_valid else None,
                              magnetic_model_eci,
                              self._sun if self.estimator_enabled and self.enable_sun_update and self._sun_valid else None,
                              sun_model_eci,
                              star_tracker=self._star_tracker if self.estimator_enabled else None)

    def latest_gyro(self):
        """The most recent GOOD GyroMeasurement (None before the first one).
        The main loop uses this to decide whether a sensor sample exists."""
        return self._gyro

    def latest_mag(self):
        """The most recent GOOD MagnetometerMeasurement (None before first)."""
        return self._mag

    def latest_sun(self):
        """The most recent GOOD sun-array receipt (None before the first).
        Check receipt.reconstruction_valid before trusting reconstructed_body
        -- during eclipse the solve honestly fails and this returns a receipt
        with reconstructed_body=None."""
        return self._sun

    def sun_body(self):
        """The satellite's best-known body-frame sun direction (unit vector,
        from the array's onboard least-squares reconstruction) -- or None
        when no good receipt exists or the reconstruction failed (eclipse,
        degenerate geometry). SENSOR belief, not truth."""
        if (self._sun is not None and self._sun.reconstruction_valid
                and self._sun.reconstructed_body is not None):
            return np.asarray(self._sun.reconstructed_body, dtype=float).reshape(3).copy()
        return None

    def B_body(self) -> np.ndarray:
        """Best-known body magnetic field [X, Y, Z] (Tesla) -- SENSOR belief."""
        return self._B.copy()

    def _star_tracker_telemetry(self):
        measurement = self._star_tracker
        now = self.estimator._last_t
        quaternion = (_usable_star_tracker_quaternion(measurement, now, self.fusion_max_age_s)
                      if now is not None else None)
        valid = quaternion is not None
        return {
            'star_tracker_valid': valid,
            'star_tracker_mode': 'TRACKING' if valid else 'STANDBY',
            'star_tracker_used': self.estimator.star_tracker_used_last,
            'star_tracker_quaternion_eci': (measurement.quaternion_eci.tolist()
                                            if valid else None),
            'star_tracker_boresight_eci': (_dcm_bi_from_q(quaternion)[:, 2].tolist()
                                          if valid else None),
            'star_tracker_latency_ms': ((measurement.t_arrival_s - measurement.t_meas_s) * 1000
                                        if valid else None),
            'star_tracker_noise_arcsec': 0.0 if valid else None,
        }

    def telemetry(self) -> dict:
        """Dashboard dict. Keys exist only via this method (added only when
        the IMU is enabled); values are None until the first good sample."""
        g = self._gyro
        m = self._mag
        s = self._sun
        navigation_mode = 'ekf' if self.estimator_enabled else 'gyro_only'
        if self.estimator.star_tracker_used_last:
            navigation_mode = 'star_tracker'
        return {
            **self._star_tracker_telemetry(),
            'imu_units': self._unit_status,
            'imu_navigation_mode': navigation_mode,
            "imu_gyro_valid": bool(self._gyro_valid),
            "imu_mag_valid": bool(self._mag_valid),
            "imu_sun_valid": bool(self._sun_valid),
            "imu_gyro_saturated": bool(self._gyro_saturated),
            "imu_mag_saturated": bool(self._mag_saturated),
            "imu_gyro_x_rad_s": None if g is None else float(g.omega_body_rad_s[0]),
            "imu_gyro_y_rad_s": None if g is None else float(g.omega_body_rad_s[1]),
            "imu_gyro_z_rad_s": None if g is None else float(g.omega_body_rad_s[2]),
            "imu_mag_x_nT": None if m is None else float(m.magnetic_field_body_t[0] * 1e9),
            "imu_mag_y_nT": None if m is None else float(m.magnetic_field_body_t[1] * 1e9),
            "imu_mag_z_nT": None if m is None else float(m.magnetic_field_body_t[2] * 1e9),
            "imu_sun_recon_valid": (None if s is None else bool(s.reconstruction_valid)),
            "imu_gyro_t_meas_s": self._gyro_t_meas,
            "imu_mag_t_meas_s": self._mag_t_meas,
            "imu_sun_t_meas_s": self._sun_t_meas,
        }


# ---------------------------------------------------------------------------
# The onboard ATTITUDE ESTIMATOR (the missing piece the IMU task documented).
#
# WHY IT EXISTS (plain language): a gyro measures SPIN RATE and a
# magnetometer measures a FIELD VECTOR -- neither measures attitude. The only
# way the satellite can know "which way am I pointing" from its own sensors
# is a small onboard program that combines them. Every real flight computer
# runs one; this is a basic, standard two-step version:
#
#   1. PREDICT: spin the attitude belief forward with the GYRO measurement
#      (q_dot = 0.5 * Omega(w) * q -- smooth, but it slowly drifts because
#      the gyro's bias means it never knows "still" perfectly).
#   2. CORRECT: every new magnetometer sample, compare the MEASURED body
#      field with what the onboard IGRF model says the field should be (the
#      model is computed at the GPS-believed position -- real flight software
#      has the IGRF model onboard); rotate the belief a small step toward
#      agreement. This kills the gyro drift but injects a little of the
#      magnetometer's own noise.
#
# Result: an attitude that jitters slightly and wanders a little (sensor
# noise, exactly like reality) but does not drift far (model correction).
# That jitter is what the dashboard's "pointing error (sat. own data)" shows.
# ---------------------------------------------------------------------------
def _quat_multiply(q1, q2):
    """Standard Hamilton product, scalar-first [q0,q1,q2,q3]. NOTE: this
    repo's C_bi composition is REVERSED (C_bi(qA (x) qB) = C_bi(qB) @ C_bi(qA),
    verified in the dynamics file) -- the estimator's correction below relies
    on that verified rule, so do NOT swap the arguments."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ])




def quat_angle_deg(q_a, q_b):
    """Angle between two attitudes [deg] -- the standard 2*acos(|dot|)."""
    dot = abs(float(np.dot(np.asarray(q_a, dtype=float).reshape(4),
                           np.asarray(q_b, dtype=float).reshape(4))))
    return 2.0 * np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))


def _skew(v):
    signal, y, z = v
    return np.array([[0., -z, y], [z, 0., -signal], [-y, signal, 0.]])


def _rotation_quaternion(v):
    angle = float(np.linalg.norm(v))
    return np.r_[np.cos(angle / 2), v * (np.sin(angle / 2) / angle if angle > 1e-12 else 0.5)]


def _usable_star_tracker_quaternion(measurement, time_s, max_age_s):
    """Accept a valid, recent absolute attitude in the simulator's convention."""
    if measurement is None or not measurement.valid:
        return None
    age_s = time_s - measurement.t_meas_s
    if not 0 <= age_s <= max_age_s:
        return None
    quaternion = np.asarray(measurement.quaternion_eci, dtype=float)
    if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)):
        return None
    length = np.linalg.norm(quaternion)
    return quaternion / length if length > 1e-12 else None


class AttitudeEstimator:
    """Six-state multiplicative EKF: body attitude error and gyro bias.

    Quaternion convention is the simulator's passive scalar-first convention.
    Covariance has radian/rad-per-second units. Vector measurement variances
    are angular variances. Initialization is an explicit prior, not truth.
    Delayed body vectors are transported to arrival using measured rate;
    this is a constant-rate approximation, not an out-of-sequence smoother.
    """
    def __init__(self, q0_eci, correction_gain=None, gyro_noise=0.00016444,
                 bias_walk=0.0000283, mag_sigma=0.015, sun_sigma=0.025,
                 innovation_gate_chi2=16.27, max_bias_rad_s=0.005,
                 initial_attitude_sigma_deg=20., initial_bias_sigma_rad_s=0.002):
        quaternion = np.asarray(q0_eci, float).reshape(4)
        if not np.all(np.isfinite(quaternion)) or np.linalg.norm(quaternion) < 1e-12:
            raise ValueError('attitude prior must be finite and nonzero')
        self._q = quaternion / np.linalg.norm(quaternion)
        self.bias = np.zeros(3)
        self.P = np.diag([np.radians(initial_attitude_sigma_deg)**2]*3 + [initial_bias_sigma_rad_s**2]*3)
        self.innovation_gate_chi2 = innovation_gate_chi2
        self.max_bias_rad_s = max_bias_rad_s
        self.gyro_noise, self.bias_walk = gyro_noise, bias_walk
        self.mag_sigma, self.sun_sigma = mag_sigma, sun_sigma
        self._last_t = None
        self._last_mag_t = self._last_sun_t = None
        self.corrections = self.propagations = 0
        self.sun_used_last = False
        self.star_tracker_used_last = False
        self.star_tracker_max_age_s = 0.5
        self._last_star_tracker_t = None

    @property
    def q_eci(self):
        return self._q.copy()

    def _correct(self, measured, reference, sigma, lag, omega):
        measured, reference = np.asarray(measured, float), np.asarray(reference, float)
        measurement_length, reference_length = np.linalg.norm(measured), np.linalg.norm(reference)
        if not np.isfinite(measurement_length + reference_length) or min(measurement_length, reference_length) < 1e-15:
            return False
        past_q = _quat_multiply(self._q, _rotation_quaternion(-omega * lag))
        measured = _dcm_bi_from_q(self._q).T @ _dcm_bi_from_q(past_q) @ (measured / measurement_length)
        predicted = _dcm_bi_from_q(self._q).T @ (reference / reference_length)
        observation_matrix = np.zeros((3, 6))
        observation_matrix[:, :3] = -_skew(predicted)
        measurement_covariance = np.eye(3) * sigma**2
        innovation = measured - predicted
        innovation_covariance = observation_matrix @ self.P @ observation_matrix.T + measurement_covariance
        # Reject inconsistent optical/model observations before they can be
        # integrated into gyro bias and hence the controller's rate feedback.
        if float(innovation @ np.linalg.solve(innovation_covariance, innovation)) > self.innovation_gate_chi2:
            return False
        kalman_gain = np.linalg.solve(innovation_covariance, observation_matrix @ self.P).T
        delta = kalman_gain @ innovation
        self._q = _quat_multiply(_rotation_quaternion(delta[:3]), self._q)
        self._q /= np.linalg.norm(self._q)
        self.bias = np.clip(self.bias + delta[3:], -self.max_bias_rad_s, self.max_bias_rad_s)
        residual_projection = np.eye(6) - kalman_gain @ observation_matrix
        self.P = residual_projection @ self.P @ residual_projection.T + kalman_gain @ measurement_covariance @ kalman_gain.T
        # Reset the tangent error after injecting the finite correction.
        reset_jacobian = np.eye(6)
        reset_jacobian[:3, :3] -= 0.5 * _skew(delta[:3])
        self.P = reset_jacobian @ self.P @ reset_jacobian.T
        self.P = (self.P + self.P.T) / 2
        self.corrections += 1
        return True

    def update(self, t_seconds, omega_belief_body, mag_meas, B_model_eci,
               sun_meas=None, sun_model_eci=None, star_tracker=None):
        """Prefer absolute star attitude; otherwise retain the existing MEKF.

        Flow: fresh ideal star quaternion -> attitude directly.
              Between star receipts -> gyro prediction.
              Invalid/stale/absent star receipt -> gyro + magnetic/Sun MEKF.

        The ideal sensor currently has zero error, so blending its reading with
        noisier vectors would reduce accuracy. No star camera filter is modeled.
        """
        time_s = float(t_seconds)
        if self._last_t is not None and time_s < self._last_t:
            raise ValueError('Estimator time must not move backwards')
        self.star_tracker_used_last = False
        self.sun_used_last = False
        quaternion = _usable_star_tracker_quaternion(
            star_tracker, time_s, self.star_tracker_max_age_s)
        if quaternion is not None:
            if (self._last_star_tracker_t is None
                    or star_tracker.t_meas_s > self._last_star_tracker_t):
                self._q = quaternion.copy()
                # An exact absolute attitude removes attitude uncertainty. Keep
                # gyro-bias uncertainty for subsequent prediction/fallback.
                self.P[:3, :] = 0.0
                self.P[:, :3] = 0.0
                self._last_t = time_s
                self._last_star_tracker_t = star_tracker.t_meas_s
                self.star_tracker_used_last = True
                self.corrections += 1
                return
        angular_rate_rad_s = np.asarray(omega_belief_body, dtype=float) - self.bias
        if self._last_t is not None:
            elapsed_time_s = time_s - self._last_t
            if elapsed_time_s < 0:
                raise ValueError('Estimator time must not move backwards')
            if elapsed_time_s > 0:
                self._predict(angular_rate_rad_s, elapsed_time_s)
        self._last_t = time_s
        self.sun_used_last = False
        if quaternion is not None:
            return  # Coast between star samples without reusing one correction.
        self._use_magnetometer(time_s, angular_rate_rad_s, mag_meas, B_model_eci)
        self._use_sun_sensor(time_s, angular_rate_rad_s, sun_meas, sun_model_eci)

    def _predict(self, angular_rate_rad_s, elapsed_time_s):
        """Propagate quaternion and uncertainty from the measured body rate."""
        half_step_rotation = _rotation_quaternion(angular_rate_rad_s * elapsed_time_s * .5)
        full_step_rotation = _rotation_quaternion(angular_rate_rad_s * elapsed_time_s)
        midpoint = _quat_multiply(self._q, half_step_rotation)
        # The plant multiplies the rotation on the right; reversing that order
        # changes the coordinate convention and gives the wrong attitude.
        self._q = _quat_multiply(self._q, full_step_rotation)
        self._q = self._q / np.linalg.norm(self._q)
        rate_to_attitude = _dcm_bi_from_q(midpoint).T
        state_transition = np.eye(6)
        state_transition[:3, 3:] = -rate_to_attitude * elapsed_time_s
        bias_noise_mapping = np.vstack((-.5 * elapsed_time_s * rate_to_attitude, np.eye(3)))
        process_covariance = self.bias_walk**2 * elapsed_time_s * (bias_noise_mapping @ bias_noise_mapping.T)
        attitude_noise = self.gyro_noise**2 * elapsed_time_s
        attitude_noise += self.bias_walk**2 * elapsed_time_s**3 / 12
        process_covariance[:3, :3] += np.eye(3) * attitude_noise
        self.P = state_transition @ self.P @ state_transition.T + process_covariance
        self.propagations += 1

    def _use_magnetometer(self, time_s, angular_rate_rad_s, measurement, reference_eci):
        if measurement is None or reference_eci is None:
            return
        if not measurement.valid or measurement.saturated:
            return
        if measurement.t_meas_s == self._last_mag_t:
            return
        measurement_age_s = max(0.0, time_s - measurement.t_meas_s)
        self._correct(measurement.magnetic_field_body_t, reference_eci,
                      self.mag_sigma, measurement_age_s, angular_rate_rad_s)
        self._last_mag_t = measurement.t_meas_s

    def _use_sun_sensor(self, time_s, angular_rate_rad_s, measurement, reference_eci):
        if measurement is None or reference_eci is None:
            return
        if not measurement.valid or not measurement.reconstruction_valid:
            return
        if measurement.t_meas_s == self._last_sun_t:
            return
        measurement_age_s = max(0.0, time_s - measurement.t_meas_s)
        self.sun_used_last = self._correct(measurement.reconstructed_body, reference_eci,
            self.sun_sigma, measurement_age_s, angular_rate_rad_s)
        self._last_sun_t = measurement.t_meas_s






    def pointing_error_deg(self, q_target):
        return float(quat_angle_deg(self._q, q_target))


__all__ = ['ImuNav', 'AttitudeEstimator', 'quat_angle_deg']
