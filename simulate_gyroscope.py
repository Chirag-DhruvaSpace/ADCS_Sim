"""Simulated gyroscope: spacecraft truth in, hardware readings out.

CONFIGURATION (satellite_parameters.yaml)
---------------------------------------
sensor_profiles.gyroscope selects the preset; gyroscope contains custom settings.
  custom   : use the configured YAML error values.
  off      : produce no sensor receipts.
  perfect  : remove modeled errors and delivery delays.
  nominal  : use the standard sensor-error preset.
  degraded : increase errors and delivery problems.
  stress   : use the largest preset errors and dropout probability.
Each sensor has its own enabled master switch; false overrides every profile.

MODELED ERRORS
--------------
  - White noise: independent jitter in each rate reading.
  - Fixed bias: a constant zero-rate offset for this sensor.
  - Bias wander: a slowly changing offset with a configured memory time.
  - Scale error and axis misalignment: gain and mounting imperfections.
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
update() retains the diagnostic physical-unit interface: angular rate [rad/s].

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
class RawGyroscopeSample:
    kind: str
    t_meas_s: float
    t_arrival_s: float
    data: dict                         # ADIS_GYRO_Typedef fields
    valid: bool
    saturated: bool

    @property
    def counts(self):
        return (self.data['X_axis'], self.data['Y_axis'], self.data['Z_axis'])


def gyro_register_scale_rad_s(hardware_range_deg_s):
    """SI rate represented by one ADIS16545 high-word count."""
    degrees_per_count = {125: 0.00625, 450: 0.025, 2000: 0.1}
    return math.radians(degrees_per_count[hardware_range_deg_s])

def encode_gyro_registers(sensor_rate_rad_s, hardware_range_deg_s):
    """Match ADIS_READ_GYRO: return the signed high word of each 32-bit output."""
    scale_rad_s = gyro_register_scale_rad_s(hardware_range_deg_s)
    registers = {}
    for axis_name, angular_rate in zip(('X_axis', 'Y_axis', 'Z_axis'), sensor_rate_rad_s):
        full_register = round(float(angular_rate) / scale_rad_s * 65536)
        high_word = full_register // 65536
        registers[axis_name] = max(-32768, min(32767, high_word))
    return registers


@dataclass
class GyroMeasurement:
    """One gyro sample. Units: radians/second, BODY frame, order [X, Y, Z].
    t_meas_s  = sim time the motion DESCRIBED; t_arrival_s = when it arrived
    (t_arrival_s >= t_meas_s when latency is enabled)."""
    t_meas_s: float
    t_arrival_s: float
    omega_body_rad_s: np.ndarray          # measured body rate [X, Y, Z] (rad/s)
    bias_rad_s: np.ndarray                # bias applied (constant + wander) [rad/s]
    wander_rad_s: np.ndarray              # only the wander part [rad/s]
    white_noise_rad_s: np.ndarray         # fresh noise that sample [rad/s]
    saturated: bool                       # clipped to the measurement range?
    valid: bool                           # False on a dropout sample


class SimulatedGyroscope:
    """One sensor chip with its own clock, latency history, errors, and cache.

    An optional generator lets the acquisition coordinator preserve the original
    shared random sequence. Used independently, the sensor owns its generator.
    """

    def __init__(self, config, epoch_utc=None, record_history=True, random_generator=None):
        self.cfg = config
        self.epoch_utc = epoch_utc
        seed = config.seed if config.gyro_seed is None else config.gyro_seed
        self.rng = (np.random.default_rng(seed)
                    if random_generator is None else random_generator)
        self._gyro_mount = _dcm_bi_from_q(config.gyro_mount_quaternion)
        self._M_gyro = self._build_calibration_matrix(
            config.gyro_scale_error, config.gyro_misalignment_rad)
        if config.gyro_bias_sigma_rad_s > 0.0:
            self._gyro_bias_const = np.array([
                white_noise(self.rng, config.gyro_bias_sigma_rad_s) for _ in range(3)])
        else:
            self._gyro_bias_const = np.zeros(3)
        self._gyro_wander = ([GaussMarkov(config.gyro_wander_sigma_rad_s, config.gyro_wander_tau_s)
                              for _ in range(3)]
                             if config.gyro_wander_sigma_rad_s > 0.0 else None)
        self._M_gyro = np.asarray(config.gyro_response_matrix) @ self._M_gyro
        self._gyro_bias_const += np.asarray(config.gyro_fixed_bias_rad_s)
        self._last_t = None
        self._raw_tick = None
        self._raw_receipt = None
        self._gyro_last_k = -1
        self._history = collections.deque(maxlen=50)
        self.gyro_samples = 0
        self._last_gyro_rec = None
        self.records = [] if record_history else collections.deque(maxlen=2)

    def prepare_sample(self, t_seconds, q_truth, omega_truth):
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
        measurement = np.asarray(omega_truth, dtype=float).reshape(3)
        self._history.append((time_s, measurement.copy()))
        if self._gyro_wander is not None:
            for drift_model in self._gyro_wander:
                drift_model.advance(elapsed_time_s, self.rng)

    def read_sample(self, raw_output=False):
        """Read the prepared tick on this sensor's configured sampling grid."""
        reading = (self._produce_gyro(self._last_t, raw_output)
                   if self.cfg.enable_gyro else None)
        if raw_output:
            self._raw_receipt = reading
            self._raw_tick = self._last_t
        return reading

    def update(self, t_seconds, q_truth, omega_truth, raw_output=False):
        """Sample angular rate [rad/s] from supplied truth; never advance the physics."""
        self.prepare_sample(t_seconds, q_truth, omega_truth)
        return self.read_sample(raw_output)

    def get_raw_data(self, t_seconds=None, q_truth=None, omega_truth=None):
        """Return one hardware packet, or reread this tick's cached packet."""
        if not self.cfg.enabled:
            return None
        if t_seconds is None or t_seconds == self._raw_tick:
            return self._raw_receipt
        return self.update(t_seconds, q_truth, omega_truth, raw_output=True)

    def _build_calibration_matrix(self, scale_error: float, misalignment_rad: float):
        """Scale-factor + axis-misalignment matrix M (applied to the true
        vector, e.g. omega_meas = M @ omega_true).

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
        """Interpolate the buffered body rate at the gyro's measurement time."""
        from bisect import bisect_right

        times = [sample[0] for sample in self._history]
        if t_meas_s <= times[0] or len(times) < 2:
            return self._history[0]
        history_index = bisect_right(times, t_meas_s) - 1
        history_index = min(max(history_index, 0), len(times) - 2)
        earlier_time, earlier_rate = self._history[history_index]
        later_time, later_rate = self._history[history_index + 1]
        fraction = ((t_meas_s - earlier_time) / (later_time - earlier_time)
                    if later_time > earlier_time else 0.0)
        return t_meas_s, earlier_rate + fraction * (later_rate - earlier_rate)

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

    def _produce_gyro(self, t, raw_output=False):
        """Build one gyro sample on the gyro's own grid (None off-grid)."""
        configuration = self.cfg
        period = 1.0 / configuration.gyro_update_rate_hz
        grid = self._on_grid(t, period, self._gyro_last_k)
        if grid is None:
            return None
        sample_index, sample_time_s = grid
        self._gyro_last_k = sample_index
        self.gyro_samples += 1

        # latency: the sample describes the motion a few ms ago
        latency_s = self._latency_draw(self.rng, configuration.gyro_latency_mean_s,
                                 configuration.gyro_latency_sigma_s,
                                 configuration.gyro_latency_min_s, configuration.gyro_latency_max_s)
        measurement_time_s, omega_true = self._sample_truth_at(sample_time_s - latency_s)

        drifting_bias = (np.array([drift_model.value for drift_model in self._gyro_wander])
                  if self._gyro_wander is not None else np.zeros(3))
        measurement_bias = self._gyro_bias_const + drifting_bias
        measurement_noise = np.array([white_noise(self.rng, configuration.gyro_white_noise_sigma_rad_s)
                          for _ in range(3)])
        unclipped_measurement = self._M_gyro @ (self._gyro_mount.T @ omega_true) + measurement_bias + measurement_noise
        measurement_range_rad_s = configuration.gyro_range_rad_s
        if raw_output:
            measurement_range_rad_s = math.radians(configuration.gyro_hardware_range_deg_s)
        saturated = bool(np.any(np.abs(unclipped_measurement) > measurement_range_rad_s))
        omega_meas = np.clip(unclipped_measurement, -measurement_range_rad_s, measurement_range_rad_s)
        if configuration.gyro_quantization_rad_s > 0.0:
            omega_meas = np.round(omega_meas / configuration.gyro_quantization_rad_s) * configuration.gyro_quantization_rad_s
        valid = not (configuration.gyro_dropout_probability > 0.0
                     and self.rng.random() < configuration.gyro_dropout_probability)

        if raw_output:
            hardware_limit_rad_s = math.radians(configuration.gyro_hardware_range_deg_s)
            saturated = saturated or bool(np.any(np.abs(omega_meas) > hardware_limit_rad_s))
            sensor_rate_rad_s = np.clip(omega_meas, -hardware_limit_rad_s, hardware_limit_rad_s)
            registers = encode_gyro_registers(sensor_rate_rad_s, configuration.gyro_hardware_range_deg_s)
            return RawGyroscopeSample('gyro', measurement_time_s, sample_time_s, registers, valid, saturated)

        omega_meas = self._gyro_mount @ omega_meas
        meas = GyroMeasurement(
            t_meas_s=measurement_time_s, t_arrival_s=sample_time_s, omega_body_rad_s=omega_meas,
            bias_rad_s=measurement_bias, wander_rad_s=drifting_bias, white_noise_rad_s=measurement_noise,
            saturated=saturated, valid=valid)
        self._last_gyro_rec = {
            "t_meas": measurement_time_s, "t_arrival": sample_time_s,
            "truth": np.asarray(omega_true), "meas": np.asarray(omega_meas),
            "bias": np.asarray(measurement_bias), "wander": np.asarray(drifting_bias),
            "noise": np.asarray(measurement_noise), "valid": valid, "saturated": saturated}
        self.records.append(("gyro", self._last_gyro_rec))
        return meas
