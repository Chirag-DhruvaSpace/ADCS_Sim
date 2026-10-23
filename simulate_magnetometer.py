"""Simulated magnetometer: spacecraft truth in, hardware readings out.

CONFIGURATION (satellite_parameters.yaml)
---------------------------------------
sensor_profiles.magnetometer selects the preset; magnetometer contains custom settings.
  custom   : use the configured YAML error values.
  off      : produce no sensor receipts.
  perfect  : remove modeled errors and delivery delays.
  nominal  : use the standard sensor-error preset.
  degraded : increase errors and delivery problems.
  stress   : use the largest preset errors and dropout probability.
Each sensor has its own enabled master switch; false overrides every profile.

MODELED ERRORS
--------------
  - White noise: independent jitter in each magnetic reading.
  - Hard-iron bias: a constant magnetic offset from the spacecraft.
  - Scale error and axis misalignment: gain and mounting imperfections.
  - Spacecraft disturbance: fixed and slowly changing local magnetic fields.
  - Quantization and saturation: finite resolution and measurement range.
  - Latency/jitter and dropouts: delayed or missing sensor receipts.
Each effect uses the corresponding settings in this sensor's YAML section.
A seeded random generator makes repeated runs reproducible. Hardware register
conversion still applies in perfect mode: ideal physics has finite device counts.

DATA FLOW
---------
Truth vector -> body frame -> mounting/gain/offset/noise -> range/resolution
             -> timestamped delivery -> signed X_axis/Y_axis/Z_axis registers.
get_raw_data(t_seconds, q_truth, truth_vector) samples one chip.
get_raw_data() returns that same cached packet without drawing more noise.
update() retains the diagnostic physical-unit interface: magnetic field [tesla].

BOUNDARIES
----------
This module models acquisition only. Calibration, sensor fusion, filtering,
and attitude estimation belong in compute_simulated_attitude.py. No navigation
filter runs here, and this model does not modify firmware or SITL processing.
"""
from __future__ import annotations

import collections
import math
from dataclasses import dataclass

import numpy as np


def white_noise(random_generator, sigma):
    """One independent zero-mean noise sample, in the same units as sigma."""
    if sigma < 0:
        raise ValueError('Noise sigma must be nonnegative')
    return sigma * random_generator.standard_normal()

class GaussMarkov:
    """A slowly changing bias with an exponential memory time, tau seconds."""

    def __init__(self, sigma, tau, initial=0.0):
        if sigma < 0:
            raise ValueError('Drift sigma must be nonnegative')
        if tau <= 0:
            raise ValueError('Drift time constant must be positive')
        self.sigma = float(sigma)
        self.tau = float(tau)
        self._value = float(initial)

    @property
    def value(self):
        return self._value

    def advance(self, dt_seconds, rng):
        elapsed_time_s = float(dt_seconds)
        if elapsed_time_s <= 0:
            return
        decay = float(np.exp(-elapsed_time_s / self.tau))
        noise_scale = float(np.sqrt(1.0 - decay * decay)) * self.sigma
        self._value = decay * self._value + noise_scale * rng.standard_normal()

    def redraw(self, random_generator):
        self._value = self.sigma * random_generator.standard_normal()

    def reset(self):
        self._value = 0.0

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


@dataclass(frozen=True)
class RawMagnetometerSample:
    kind: str
    t_meas_s: float
    t_arrival_s: float
    data: dict                         # ICM_MAG_Typedef fields
    valid: bool
    saturated: bool

    @property
    def counts(self):
        return (self.data['X_axis'], self.data['Y_axis'], self.data['Z_axis'])


def encode_magnetometer_registers(sensor_field_t):
    """AK09916 signed 16-bit outputs; one count is 0.15 microtesla (150 nT)."""
    registers = {}
    for axis_name, magnetic_field_t in zip(('X_axis', 'Y_axis', 'Z_axis'), sensor_field_t):
        count = round(float(magnetic_field_t) / 150e-9)
        registers[axis_name] = max(-32768, min(32767, count))
    return registers


@dataclass
class MagnetometerMeasurement:
    """One magnetometer sample. Units: TESLA, BODY frame, order [X, Y, Z].
    This repo's live convention for the body field is Tesla (B_eci from
    engine_adcs_bridge is Tesla); the real hardware datasheet quotes nT
    (1e-9 T) -- see the module docstring / README for both."""
    t_meas_s: float
    t_arrival_s: float
    magnetic_field_body_t: np.ndarray     # measured body field [X, Y, Z] (T)
    hard_iron_bias_t: np.ndarray          # fixed spacecraft-hull offset applied [T]
    disturbance_body_t: np.ndarray        # spacecraft-generated field applied [T]
    white_noise_t: np.ndarray             # fresh noise that sample [T]
    saturated: bool                       # clipped to the measurement range?
    valid: bool                           # False on a dropout sample


class SimulatedMagnetometer:
    """One sensor chip with its own clock, latency history, errors, and cache.

    An optional generator lets the acquisition coordinator preserve the original
    shared random sequence. Used independently, the sensor owns its generator.
    """

    def __init__(self, config, epoch_utc=None, record_history=True, random_generator=None):
        self.cfg = config
        self.epoch_utc = epoch_utc
        seed = config.seed if config.mag_seed is None else config.mag_seed
        self.rng = (np.random.default_rng(seed)
                    if random_generator is None else random_generator)
        self._mag_mount = _dcm_bi_from_q(config.mag_mount_quaternion)
        self._M_mag = self._build_calibration_matrix(
            config.mag_scale_error, config.mag_misalignment_rad)
        if config.mag_hard_iron_bias_sigma_t > 0.0:
            self._mag_hard_iron = np.array([
                white_noise(self.rng, config.mag_hard_iron_bias_sigma_t) for _ in range(3)])
        else:
            self._mag_hard_iron = np.zeros(3)
        self._mag_disturb_fixed = np.asarray(config.mag_disturbance_t, dtype=float).reshape(3)
        self._mag_disturb_wander = ([
            GaussMarkov(config.mag_disturbance_wander_sigma_t,
                        config.mag_disturbance_wander_tau_s) for _ in range(3)]
            if config.mag_disturbance_wander_sigma_t > 0.0 else None)
        self._M_mag = np.asarray(config.mag_response_matrix) @ self._M_mag
        self._mag_hard_iron += np.asarray(config.mag_fixed_bias_t)
        self._last_t = None
        self._raw_tick = None
        self._raw_receipt = None
        self._mag_last_k = -1
        self._history = collections.deque(maxlen=50)
        self.mag_samples = 0
        self._last_mag_rec = None
        self.records = [] if record_history else collections.deque(maxlen=2)

    def prepare_sample(self, t_seconds, q_truth, B_eci_truth):
        """Advance this chip's clock and drifting errors before acquisition.

        Preparing both chips before reading them preserves the original order
        of shared random draws in the main simulation.
        """
        time_s = float(t_seconds)
        if self._last_t is not None and time_s <= self._last_t:
            raise ValueError('Sensor sampling time must move forward')
        elapsed_time_s = 0.0 if self._last_t is None else time_s - self._last_t
        self._last_t = time_s
        quaternion = np.asarray(q_truth, dtype=float).reshape(4)
        measurement = np.asarray(B_eci_truth, dtype=float).reshape(3)
        self._history.append((time_s, quaternion.copy(), measurement.copy()))
        if self._mag_disturb_wander is not None:
            for drift_model in self._mag_disturb_wander:
                drift_model.advance(elapsed_time_s, self.rng)

    def read_sample(self, raw_output=False):
        """Read the prepared tick on this sensor's configured sampling grid."""
        reading = (self._produce_mag(self._last_t, raw_output)
                   if self.cfg.enable_magnetometer else None)
        if raw_output:
            self._raw_receipt = reading
            self._raw_tick = self._last_t
        return reading

    def update(self, t_seconds, q_truth, B_eci_truth, raw_output=False):
        """Sample magnetic field [tesla] from supplied truth; never advance the physics."""
        self.prepare_sample(t_seconds, q_truth, B_eci_truth)
        return self.read_sample(raw_output)

    def get_raw_data(self, t_seconds=None, q_truth=None, B_eci_truth=None):
        """Return one hardware packet, or reread this tick's cached packet."""
        if not self.cfg.enabled:
            return None
        if t_seconds is None or t_seconds == self._raw_tick:
            return self._raw_receipt
        return self.update(t_seconds, q_truth, B_eci_truth, raw_output=True)

    def _build_calibration_matrix(self, scale_error: float, misalignment_rad: float):
        """Scale-factor + axis-misalignment matrix M (applied to the true
        vector, e.g. field_meas = M @ field_true).

        M = diag(1+sx, 1+sy, 1+sz) + small off-diagonal misalignment terms,
        each drawn once at power-on from N(0, misalignment_rad). Real sensors
        have this because the chip axes are not perfectly aligned to the
        spacecraft axes and the scale can be slightly off. Drawn from this
        sensor's own rng so it is deterministic for a given seed.
        """
        measurement_scale = 1.0 + np.array([white_noise(self.rng, scale_error) if scale_error > 0 else 0.0
                                for _ in range(3)])
        response_matrix = np.diag(measurement_scale)
        if misalignment_rad > 0.0:
            response_matrix[0, 1] = white_noise(self.rng, misalignment_rad)
            response_matrix[0, 2] = white_noise(self.rng, misalignment_rad)
            response_matrix[1, 0] = white_noise(self.rng, misalignment_rad)
            response_matrix[1, 2] = white_noise(self.rng, misalignment_rad)
            response_matrix[2, 0] = white_noise(self.rng, misalignment_rad)
            response_matrix[2, 1] = white_noise(self.rng, misalignment_rad)
        return response_matrix

    def _sample_truth_at(self, t_meas_s):
        """Interpolate buffered attitude and magnetic field for sensor latency."""
        from bisect import bisect_right

        times = [sample[0] for sample in self._history]
        if t_meas_s <= times[0] or len(times) < 2:
            return self._history[0]
        history_index = bisect_right(times, t_meas_s) - 1
        history_index = min(max(history_index, 0), len(times) - 2)
        earlier_time, earlier_quaternion, earlier_field = self._history[history_index]
        later_time, later_quaternion, later_field = self._history[history_index + 1]
        if np.dot(earlier_quaternion, later_quaternion) < 0:
            later_quaternion = -later_quaternion
        fraction = ((t_meas_s - earlier_time) / (later_time - earlier_time)
                    if later_time > earlier_time else 0.0)
        quaternion = earlier_quaternion + fraction * (later_quaternion - earlier_quaternion)
        quaternion /= np.linalg.norm(quaternion)
        field = earlier_field + fraction * (later_field - earlier_field)
        return t_meas_s, quaternion, field

    @staticmethod
    def _latency_draw(rng, mean, sigma, lo, hi):
        """One random latency value, clipped into [lo, hi] (chips have bounds)."""
        return float(np.clip(rng.normal(mean, sigma), lo, hi))

    def _on_grid(self, t, period, last_k):
        """1 Hz-style grid check for one sensor: returns (k, t_grid) on a new
        boundary, else None. The boundary is consumed even on dropout so a
        dropped sample is never retried."""
        sample_index = math.floor(t / period + 1e-9)
        if sample_index <= last_k:
            return None
        return sample_index, sample_index * period

    def _produce_mag(self, t, raw_output=False):
        """Build one magnetometer sample on the magnetometer's own grid."""
        configuration = self.cfg
        period = 1.0 / configuration.mag_update_rate_hz
        grid = self._on_grid(t, period, self._mag_last_k)
        if grid is None:
            return None
        sample_index, sample_time_s = grid
        self._mag_last_k = sample_index
        self.mag_samples += 1

        latency_s = self._latency_draw(self.rng, configuration.mag_latency_mean_s,
                                 configuration.mag_latency_sigma_s,
                                 configuration.mag_latency_min_s, configuration.mag_latency_max_s)
        measurement_time_s, q_meas, B_eci_meas = self._sample_truth_at(sample_time_s - latency_s)

        # TRUE field in the body frame, using the repo's own convention:
        #     B_body = C_bi.T @ B_eci   (C_bi = body->ECI from the quaternion)
        B_true_body = _dcm_bi_from_q(q_meas).T @ B_eci_meas

        disturbance = (np.array([drift_model.value for drift_model in self._mag_disturb_wander])
                       if self._mag_disturb_wander is not None else np.zeros(3))
        disturbance = disturbance + self._mag_disturb_fixed
        measurement_noise = np.array([white_noise(self.rng, configuration.mag_white_noise_sigma_t)
                          for _ in range(3)])
        local_field = B_true_body + np.asarray(configuration.mag_gradient_body_t_per_m) @ np.asarray(configuration.mag_position_body_m)
        unclipped_measurement = (self._M_mag @ (self._mag_mount.T @ (local_field + disturbance))
               + self._mag_hard_iron + measurement_noise)
        measurement_range_t = 4900e-6 if raw_output else configuration.mag_range_t
        saturated = bool(np.any(np.abs(unclipped_measurement) > measurement_range_t))
        B_meas = np.clip(unclipped_measurement, -measurement_range_t, measurement_range_t)
        if configuration.mag_quantization_t > 0.0:
            B_meas = np.round(B_meas / configuration.mag_quantization_t) * configuration.mag_quantization_t
        valid = not (configuration.mag_dropout_probability > 0.0
                     and self.rng.random() < configuration.mag_dropout_probability)

        if raw_output:
            hardware_limit_t = 4900e-6
            saturated = saturated or bool(np.any(np.abs(B_meas) > hardware_limit_t))
            sensor_field_t = np.clip(B_meas, -hardware_limit_t, hardware_limit_t)
            registers = encode_magnetometer_registers(sensor_field_t)
            return RawMagnetometerSample('mag', measurement_time_s, sample_time_s, registers, valid, saturated)

        B_meas = self._mag_mount @ B_meas
        meas = MagnetometerMeasurement(
            t_meas_s=measurement_time_s, t_arrival_s=sample_time_s, magnetic_field_body_t=B_meas,
            hard_iron_bias_t=self._mag_hard_iron, disturbance_body_t=disturbance,
            white_noise_t=measurement_noise, saturated=saturated, valid=valid)
        self._last_mag_rec = {
            "t_meas": measurement_time_s, "t_arrival": sample_time_s,
            "truth": np.asarray(B_true_body), "meas": np.asarray(B_meas),
            "hard_iron": np.asarray(self._mag_hard_iron),
            "disturbance": np.asarray(disturbance), "noise": np.asarray(measurement_noise),
            "valid": valid, "saturated": saturated}
        self.records.append(("mag", self._last_mag_rec))
        return meas
