"""simulate_startracker.py -- a single-head quaternion star tracker.

WHAT THIS IS (plain language): a camera that reports spacecraft orientation,
with small unequal axis errors, slow wander, delayed delivery and outages.
X/Y describe tilt; Z describes roll about the camera's +Z boresight.

CONFIGURE (satellite_parameters.yaml):
    star_tracker.enabled: true
    sensor_profiles.star_tracker: custom
    Profiles: off / perfect / nominal / degraded / stress / custom.
    perfect preserves the original exact, immediate truth passthrough.
    nominal uses the standard errors; degraded doubles errors and reduces
    availability; stress adds larger errors, bursts and longer acquisition.
    custom uses the complete star_tracker section. Restart after editing YAML.

SELF-TEST (from the project root):
    python simulate_startracker.py validate

PLAIN-LANGUAGE GLOSSARY:
    arcsec         1/3600 degree; all configured sigmas are 1-sigma.
    NEA            noise-equivalent angle: fresh temporal white jitter.
    LFSE           low-frequency spatial error: remembered FOV wander.
    bias           fixed error drawn once per seeded power-on.
    thermal drift  tilt offset relative to a configured reference temperature.
    latency        transport delay; measurement time remains the capture time.
    dropout        missing solution, represented by an invalid status receipt.
    blinding       Sun baffle/exclusion or Earth disk/atmospheric limb masking.
    exclusion      minimum Sun separation or clearance above the Earth limb.
    TFS            time to first solution, also used for lost-in-space recovery.
    valid-but-wrong occasional large errors with validity still asserted.
    anisotropy     roll uncertainty is about six times the tilt uncertainty.

MODELED ERRORS:
    NEA, Gauss-Markov LFSE, power-on bias and thermal tilt; star-count,
    temperature/rate, straylight and optional slow sky-position inflation.
    Rate and acceleration limits, acquisition, first-five low-trust solutions,
    timestamp error, bounded latency, random/burst/scheduled outages and outliers.
    Temperature/rate inflation uses the larger normalized temperature or rate
    excursion; a separate smooth factor increases errors near the rate cap.

DATA FLOW:
    Passed truth -> mounted tracker errors -> capture receipt -> delivery queue
    -> cached delivered receipt -> onboard attitude MEKF -> dashboard telemetry.
    get_raw_data(t, q_truth, r_eci, s_sun_eci, omega_body_rad_s) ticks once;
    get_raw_data() returns the cache without drawing random numbers.
    Position is ECI metres, Sun is an ECI direction, rates are body rad/s.

BOUNDARIES:
    Acquisition only; filtering belongs in compute_simulated_attitude.py.
    No optical/pixel/catalog simulation or truth propagation occurs here.
    White-noise validation isolates NEA: total error also contains LFSE/bias.
    Repeatable seeds repeat power-on bias; different seeds represent new starts.

GOLDEN RULES:
    1. Never fetch or advance truth: the loop passes all truth per tick.
    2. One owned numpy Generator, seeded from YAML; no shared sensor streams.
    3. Hamilton body-to-ECI attitude throughout. Mounted body errors multiply
       truth on the right; mounting values retain their YAML encoding.
    4. Receipts are what flight software consumes. Injected error diagnostics
       are for telemetry/validation only and never used as filter innovations.

VALIDATION PERFORMED:
    Commands below use the repository virtual environment (Orekit required).
    1. Perfect/off/cache: .venv/Scripts/python.exe simulate_startracker.py validate -- PASS.
    2. 30-minute isolated NEA: same command -- PASS; std 4.315/4.255/26.191 arcsec, ratio 6.112.
    3. 50 power-cycle means: same command -- PASS; spread 19.106/21.761/17.053 arcsec.
    4. LFSE/60-second averaging: same command -- PASS; spread exceeds white-only prediction.
    5. 1 deg/s slew and capture-time fusion: same command -- PASS; 150 ms lag.
    6. Sun/Earth angles and rotated mount: same command -- PASS.
    7. Rate loss, TFS and first-five trust: same command -- PASS.
    8. Repeatability and gyro/magnetic/Sun/GPS stream isolation: same command -- PASS.
    9. Mounted R, gate, trust rejection and all YAML profiles: same command -- PASS.
    10. Thermal/inflation/outliers/dropouts/orbit/delivery: same command -- PASS.
    Regression: .venv/Scripts/python.exe -m unittest validation.test_startracker
        validation.test_sensor_navigation validation.test_simulated_sensor_models
        validation.test_hardware_sensor_outputs -- PASS (34 tests; one command).
    Frontend: npm.cmd test (frontend directory) -- PASS (7 tests).
    Frontend build: npm.cmd run build -- --outDir <temporary directory outside repo>
        -- PASS; temporary build output deleted after verification.

ASSUMPTIONS AND VALIDATION LIMITS:
    A fixed seed represents the same power-on; distinct seeds represent distinct
    bias draws. Thermal reference is 20 C. LFSE starts in its stationary
    distribution. Sky position uses a smooth surrogate rather than a catalogue.
    Baseline NEA is measured separately from LFSE and bias: their combined
    standard deviation cannot equal the NEA-only engineering specification.
    Time alignment uses the estimator's constant measured-rate approximation;
    it is not historical gyro replay under changing rates. Orbit outage proof
    uses passed-in circular-orbit positions; a live dashboard orbit run was
    not performed. No SENSOR_INTERFACES.md exists, so none was created.
"""
from dataclasses import dataclass, field, replace
import sys

import numpy as np

from compute_simulated_attitude import _dcm_bi_from_q, _quat_multiply, _rotation_quaternion
from attitude_frames import mount_to_body
from satellite_parameters import StarTrackerParameters


ARCSEC_TO_RAD = np.pi / (180.0 * 3600.0)


@dataclass(frozen=True)
class StarTrackerMeasurement:
    t_meas_s: float
    t_arrival_s: float
    quaternion_eci: np.ndarray
    valid: bool = True
    mode: str = 'TRACKING'
    num_stars: int = 8
    quality: float = 1.0
    reason: str = 'OK'
    trusted: bool = True
    perfect: bool = True
    noise_arcsec: np.ndarray = field(default_factory=lambda: np.zeros(3))
    nea_arcsec: np.ndarray = field(default_factory=lambda: np.zeros(3))
    lfse_arcsec: np.ndarray = field(default_factory=lambda: np.zeros(3))
    covariance_body_rad2: np.ndarray = field(default_factory=lambda: np.zeros((3, 3)))
    mount_quaternion: tuple = (1.0, 0.0, 0.0, 0.0)
    sun_angle_deg: float | None = None
    earth_limb_angle_deg: float | None = None
    rate_deg_s: float = 0.0
    rate_limit_deg_s: float | None = None


def _angle_deg(first, second):
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    if not np.isfinite(denominator) or denominator < 1e-12:
        raise ValueError('Geometry vectors must be finite and nonzero')
    return float(np.degrees(np.arccos(np.clip(np.dot(first, second) / denominator, -1, 1))))


class SimulatedStarTracker:
    """An independent sensor clock, error state, delivery queue and receipt cache."""

    def __init__(self, enabled=True, config=None):
        self.cfg = StarTrackerParameters.perfect() if config is None else config
        self.enabled = bool(enabled and self.cfg.enabled and self.cfg.profile != 'off')
        self.rng = np.random.default_rng(self.cfg.seed)
        self.mount_rotation = mount_to_body(self.cfg.mount_quaternion)
        self._reading = None
        self._last_tick_s = None
        self._last_capture_s = None
        self._next_capture_s = None
        self._last_rate = None
        self._pending = []
        self._mode = 'ACQUISITION'
        self._acquisition_started_s = None
        self._acquisition_duration_s = self.cfg.cold_start_s
        self._untrusted_remaining = self.cfg.low_trust_packets
        self._star_count = 8.0
        self._burst_until_s = -np.inf
        self._sky_phase_rad = 0.0
        self._bias_arcsec = np.zeros(3)
        self._wander_arcsec = np.zeros(3)
        if self.cfg.profile != 'perfect':
            if self.cfg.enable_bias:
                self._bias_arcsec = self.rng.normal(size=3) * self.cfg.bias_sigma_arcsec
            if self.cfg.enable_lfse:
                self._wander_arcsec = self.rng.normal(size=3) * self.cfg.lfse_sigma_arcsec
            if self.cfg.enable_sky_position:
                self._sky_phase_rad = self.rng.uniform(0, 2 * np.pi)
        self.update_rate_hz = None if self.cfg.profile == 'perfect' else self.cfg.update_rate_hz

    def _geometry(self, quaternion, position_eci_m, sun_direction_eci):
        boresight_body = self.mount_rotation[:, 2]
        boresight_eci = _dcm_bi_from_q(quaternion) @ boresight_body
        sun_angle_deg = _angle_deg(boresight_eci, sun_direction_eci)
        position = np.asarray(position_eci_m, dtype=float).reshape(3)
        radius_m = np.linalg.norm(position)
        limb_radius_m = self.cfg.earth_limb_radius_km * 1000
        if not np.isfinite(radius_m) or radius_m <= limb_radius_m:
            raise ValueError('Star tracker spacecraft must be above the configured Earth limb')
        earth_radius_deg = np.degrees(np.arcsin(limb_radius_m / radius_m))
        limb_angle_deg = _angle_deg(boresight_eci, -position) - earth_radius_deg
        reason = 'OK'
        if self.cfg.enable_blinding:
            if sun_angle_deg < self.cfg.sun_hard_off_deg:
                reason = 'SUN_HARD_OFF'
            elif sun_angle_deg < self.cfg.sun_exclusion_deg:
                reason = 'SUN_EXCLUSION'
            elif limb_angle_deg < self.cfg.earth_exclusion_deg:
                reason = 'EARTH_EXCLUSION'
        inflation = 1.0
        if self.cfg.enable_straylight:
            sun_fraction = np.clip((self.cfg.sun_clean_deg - sun_angle_deg) /
                                  (self.cfg.sun_clean_deg - self.cfg.sun_exclusion_deg), 0, 1)
            earth_fraction = np.clip((self.cfg.earth_clean_deg - limb_angle_deg) /
                                    (self.cfg.earth_clean_deg - self.cfg.earth_exclusion_deg), 0, 1)
            inflation = 1 + 2 * max(sun_fraction, earth_fraction)
        return sun_angle_deg, float(limb_angle_deg), reason, float(inflation)

    def _update_mode(self, time_s, rate_deg_s, acceleration_deg_s2, geometry_reason):
        reason = geometry_reason
        if any(start <= time_s < end for start, end in self.cfg.outages_s):
            reason = 'SCHEDULED_OUTAGE'
        if reason != 'OK':
            self._mode = 'BLINDED' if reason != 'SCHEDULED_OUTAGE' else 'LOST'
            self._acquisition_started_s = None
            return reason
        if self.cfg.enable_kinematic_limits:
            if rate_deg_s > self.cfg.tracking_rate_limit_deg_s:
                self._mode = 'LOST'
                self._acquisition_started_s = None
                return 'RATE_LIMIT'
            if acceleration_deg_s2 > self.cfg.tracking_acceleration_limit_deg_s2:
                self._mode = 'LOST'
                self._acquisition_started_s = None
                return 'ACCELERATION_LIMIT'
            if self._mode != 'TRACKING' and rate_deg_s >= self.cfg.reacquisition_rate_limit_deg_s:
                self._mode = 'LOST'
                self._acquisition_started_s = None
                return 'WAITING_FOR_LOW_RATE'
        if self._mode != 'TRACKING':
            if self._acquisition_started_s is None:
                self._acquisition_started_s = time_s
                if self._mode != 'ACQUISITION':
                    self._acquisition_duration_s = self.cfg.reacquisition_s
                    self._acquisition_duration_s += self.rng.uniform(0, self.cfg.reacquisition_jitter_s)
                self._mode = 'ACQUISITION'
                self._untrusted_remaining = self.cfg.low_trust_packets
            if time_s - self._acquisition_started_s + 1e-9 < self._acquisition_duration_s:
                return 'ACQUIRING'
            self._mode = 'TRACKING'
        return 'OK'

    def _capture(self, time_s, quaternion, geometry, rate_deg_s, reason):
        elapsed_s = 1 / self.cfg.update_rate_hz
        if self._last_capture_s is not None:
            elapsed_s = time_s - self._last_capture_s
        self._last_capture_s = time_s
        if self.cfg.enable_star_count:
            self._star_count += self.rng.normal() * self.cfg.star_count_walk_sigma_per_sqrt_s * np.sqrt(elapsed_s)
            self._star_count = float(np.clip(self._star_count, 4, 8))
        number_stars = int(np.clip(round(self._star_count), 4, 8))
        inflation = geometry[3]
        if self.cfg.enable_star_count:
            inflation *= np.sqrt(8 / number_stars)
        if self.cfg.enable_temperature_rate_inflation:
            rate_fraction = np.clip((rate_deg_s - 1) / 2, 0, 1)
            temperature_fraction = np.clip((self.cfg.detector_temperature_c - 30) / 25, 0, 1)
            inflation *= 1 + 4 * max(rate_fraction, temperature_fraction)
            cap_fraction = np.clip((rate_deg_s / self.cfg.tracking_rate_limit_deg_s - .7) / .3, 0, 1)
            inflation *= 1 + 2 * cap_fraction
        if self.cfg.enable_sky_position:
            phase = 2 * np.pi * time_s / self.cfg.sky_position_period_s + self._sky_phase_rad
            inflation *= 1.9 + .9 * np.sin(phase)
        nea_sigma = np.zeros(3)
        lfse_sigma = np.zeros(3)
        if self.cfg.enable_nea:
            nea_sigma = np.asarray(self.cfg.nea_sigma_arcsec) * inflation
        if self.cfg.enable_lfse:
            lfse_sigma = np.asarray(self.cfg.lfse_sigma_arcsec) * inflation
            tau_s = self.cfg.lfse_tau_s / (1 + rate_deg_s / self.cfg.lfse_slew_scale_deg_s)
            decay = np.exp(-elapsed_s / tau_s)
            self._wander_arcsec = decay * self._wander_arcsec
            self._wander_arcsec += np.sqrt(1 - decay * decay) * np.asarray(self.cfg.lfse_sigma_arcsec) * self.rng.normal(size=3)
        white_arcsec = nea_sigma * self.rng.normal(size=3)
        wander_arcsec = self._wander_arcsec * inflation if self.cfg.enable_lfse else np.zeros(3)
        temporal_arcsec = white_arcsec + wander_arcsec
        if self.cfg.enable_outliers and self.rng.random() < self.cfg.outlier_probability:
            temporal_arcsec *= self.rng.uniform(self.cfg.outlier_multiplier_min, self.cfg.outlier_multiplier_max)
        thermal_arcsec = np.zeros(3)
        if self.cfg.enable_thermal:
            temperature_difference_c = self.cfg.detector_temperature_c - self.cfg.thermal_reference_temperature_c
            thermal_arcsec = np.asarray(self.cfg.thermal_slope_arcsec_per_deg_c) * temperature_difference_c
        error_arcsec = temporal_arcsec + self._bias_arcsec + thermal_arcsec
        error_body_rad = self.mount_rotation @ (error_arcsec * ARCSEC_TO_RAD)
        # Tracker errors are in body axes: apply them on the right of q_truth.
        measured_quaternion = _quat_multiply(quaternion, _rotation_quaternion(error_body_rad))
        measured_quaternion /= np.linalg.norm(measured_quaternion)
        covariance_tracker = np.diag((nea_sigma**2 + lfse_sigma**2) * ARCSEC_TO_RAD**2)
        covariance_body = self.mount_rotation @ covariance_tracker @ self.mount_rotation.T
        if self.cfg.enable_dropouts:
            if self.rng.random() < self.cfg.burst_start_probability:
                self._burst_until_s = time_s + self.cfg.burst_duration_s
            if time_s < self._burst_until_s:
                reason = 'BURST_DROPOUT' if reason == 'OK' else reason
            elif self.rng.random() < self.cfg.dropout_probability and reason == 'OK':
                reason = 'RANDOM_DROPOUT'
        valid = reason == 'OK'
        trusted = valid and self._untrusted_remaining == 0
        if valid and self._untrusted_remaining > 0:
            self._untrusted_remaining -= 1
        latency_s = 0.0
        timestamp_error_s = 0.0
        if self.cfg.enable_latency:
            latency_s = float(np.clip(self.rng.normal(self.cfg.latency_mean_s, self.cfg.latency_sigma_s),
                                      self.cfg.latency_min_s, self.cfg.latency_max_s))
            timestamp_error_s = self.rng.normal(0, self.cfg.timestamp_sigma_s)
        return StarTrackerMeasurement(
            t_meas_s=time_s + timestamp_error_s, t_arrival_s=time_s + latency_s,
            quaternion_eci=measured_quaternion, valid=valid, mode=self._mode,
            num_stars=number_stars if valid else 0, quality=float(1 / inflation**2) if valid else 0.0,
            reason=reason, trusted=trusted, perfect=False, noise_arcsec=error_arcsec,
            nea_arcsec=white_arcsec, lfse_arcsec=wander_arcsec,
            covariance_body_rad2=covariance_body, mount_quaternion=self.cfg.mount_quaternion,
            sun_angle_deg=geometry[0], earth_limb_angle_deg=geometry[1],
            rate_deg_s=rate_deg_s, rate_limit_deg_s=self.cfg.tracking_rate_limit_deg_s)

    def get_raw_data(self, t_seconds=None, q_truth=None, r_eci=None,
                     s_sun_eci=None, omega_body_rad_s=None):
        """Tick using supplied truth, or read the most recently delivered receipt."""
        if not self.enabled:
            return None
        if t_seconds is None:
            return self._reading
        time_s = float(t_seconds)
        if not np.isfinite(time_s):
            raise ValueError('Star tracker sampling time must be finite')
        if self._last_tick_s is not None:
            if time_s < self._last_tick_s:
                raise ValueError('Star tracker sampling time must move forward')
            if time_s == self._last_tick_s:
                return self._reading
        quaternion = np.asarray(q_truth, dtype=float).reshape(4)
        if not np.all(np.isfinite(quaternion)) or np.linalg.norm(quaternion) < 1e-12:
            raise ValueError('Star tracker quaternion must be finite and nonzero')
        if self.cfg.profile == 'perfect':
            if self._last_tick_s is not None:
                self.update_rate_hz = 1 / (time_s - self._last_tick_s)
            self._last_tick_s = time_s
            self._reading = StarTrackerMeasurement(time_s, time_s, quaternion.copy())
            return self._reading
        quaternion = quaternion / np.linalg.norm(quaternion)
        rate = np.asarray(omega_body_rad_s, dtype=float).reshape(3)
        if not np.all(np.isfinite(rate)):
            raise ValueError('Star tracker truth rate must be finite')
        rate_deg_s = float(np.degrees(np.linalg.norm(rate)))
        acceleration_deg_s2 = 0.0
        if self._last_tick_s is not None:
            acceleration_deg_s2 = float(np.degrees(np.linalg.norm(rate - self._last_rate)) / (time_s - self._last_tick_s))
        self._last_tick_s = time_s
        self._last_rate = rate.copy()
        geometry = self._geometry(quaternion, r_eci, s_sun_eci)
        reason = self._update_mode(time_s, rate_deg_s, acceleration_deg_s2, geometry[2])
        if self._next_capture_s is None:
            self._next_capture_s = time_s
        if time_s + 1e-9 >= self._next_capture_s:
            receipt = self._capture(time_s, quaternion, geometry, rate_deg_s, reason)
            self._pending.append(receipt)
            missed_intervals = int(np.floor(max(0, time_s - self._next_capture_s) * self.cfg.update_rate_hz + 1e-8))
            self._next_capture_s += (missed_intervals + 1) / self.cfg.update_rate_hz
        arrived = [receipt for receipt in self._pending if receipt.t_arrival_s <= time_s]
        self._pending = [receipt for receipt in self._pending if receipt.t_arrival_s > time_s]
        for receipt in sorted(arrived, key=lambda item: item.t_meas_s):
            if self._reading is None or receipt.t_meas_s > self._reading.t_meas_s:
                self._reading = receipt
        return self._reading


def _validation_configuration(**changes):
    """Isolate channels deliberately; individual proofs enable what they measure."""
    configuration = replace(
        StarTrackerParameters.nominal(), cold_start_s=0, low_trust_packets=0,
        enable_bias=False, enable_thermal=False, enable_star_count=False,
        enable_temperature_rate_inflation=False, enable_straylight=False,
        enable_dropouts=False, enable_outliers=False, enable_latency=False)
    return replace(configuration, **changes)


def _validation_sample(tracker, time_s, quaternion=None, rate=None, sun=None, position=None):
    if quaternion is None:
        quaternion = np.array([1.0, 0.0, 0.0, 0.0])
    if rate is None:
        rate = np.zeros(3)
    if sun is None:
        sun = np.array([1.0, 0.0, 0.0])
    if position is None:
        position = np.array([0.0, 0.0, 7000000.0])
    return tracker.get_raw_data(time_s, quaternion, position, sun, rate)


def _validate():
    """Run channel-isolated statistical proofs and delivery/fusion integration."""
    from compute_simulated_attitude import AttitudeEstimator

    tracker = SimulatedStarTracker()
    truth = np.array([.5, -.5, .5, -.5])
    for index in range(100):
        receipt = tracker.get_raw_data(index / 10, truth)
        np.testing.assert_array_equal(receipt.quaternion_eci, truth)
        assert receipt.valid and receipt.trusted
        assert receipt.t_meas_s == receipt.t_arrival_s
        assert tracker.get_raw_data() is receipt
    assert SimulatedStarTracker(enabled=False).get_raw_data(0, truth) is None
    print('PASS 1: perfect passthrough, cache, validity and off behavior')

    tracker = SimulatedStarTracker(config=_validation_configuration(enable_lfse=False))
    white_errors = []
    for index in range(18000):
        white_errors.append(_validation_sample(tracker, index / 10).noise_arcsec)
    white_errors = np.asarray(white_errors)
    standard_deviation = white_errors.std(axis=0)
    np.testing.assert_allclose(standard_deviation, [4.3, 4.3, 26], rtol=.04)
    ratio = standard_deviation[2] / np.mean(standard_deviation[:2])
    assert 5.7 < ratio < 6.4
    print(f'PASS 2: 30-minute isolated NEA std {standard_deviation}; roll/tilt {ratio:.3f}')

    power_cycle_means = []
    for seed in range(50):
        tracker = SimulatedStarTracker(config=_validation_configuration(
            seed=seed, enable_bias=True, enable_lfse=False))
        errors = []
        for index in range(100):
            errors.append(_validation_sample(tracker, index / 10).noise_arcsec)
        power_cycle_means.append(np.mean(errors, axis=0))
    bias_spread = np.std(power_cycle_means, axis=0)
    np.testing.assert_allclose(bias_spread, [20, 20, 17], rtol=.30)
    print(f'PASS 3: 50 independent seeded power-cycle mean spreads {bias_spread}')

    tracker = SimulatedStarTracker(config=_validation_configuration())
    combined_errors = []
    for index in range(18000):
        combined_errors.append(_validation_sample(tracker, index / 10).noise_arcsec)
    combined_errors = np.asarray(combined_errors)
    averaged_spread = combined_errors.reshape(30, 600, 3).mean(axis=1).std(axis=0)
    white_average_spread = np.asarray([4.3, 4.3, 26]) / np.sqrt(600)
    assert np.all(averaged_spread > 3 * white_average_spread)
    assert np.corrcoef(combined_errors[:-1, 2], combined_errors[1:, 2])[0, 1] > .1
    print(f'PASS 4: LFSE persists after 60-second averaging; std {averaged_spread}')

    configuration = _validation_configuration(
        enable_nea=False, enable_lfse=False, enable_latency=True,
        latency_sigma_s=0, timestamp_sigma_s=0, enable_kinematic_limits=False)
    tracker = SimulatedStarTracker(config=configuration)
    navigation = AttitudeEstimator([1, 0, 0, 0])
    angular_rate = np.radians([0.0, 0.0, 1.0])
    arrival_lags = []
    for index in range(401):
        time_s = index / 100
        truth = _rotation_quaternion(angular_rate * time_s)
        receipt = _validation_sample(tracker, time_s, quaternion=truth, rate=angular_rate)
        navigation.update(time_s, angular_rate, None, None, star_tracker=receipt)
        if receipt is not None:
            assert receipt.t_arrival_s <= time_s
            np.testing.assert_allclose(receipt.quaternion_eci,
                                       _rotation_quaternion(angular_rate * receipt.t_meas_s), atol=1e-14)
            arrival_lags.append(receipt.t_arrival_s - receipt.t_meas_s)
        np.testing.assert_allclose(navigation.q_eci, truth, atol=1e-10)
    np.testing.assert_allclose(arrival_lags, .15, atol=1e-12)
    assert navigation.corrections > 20
    assert np.trace(navigation.P[:3, :3]) > 0
    print('PASS 5: 1 deg/s slew, 150 ms delivery lag, capture-time fusion, nonzero covariance')

    configuration = _validation_configuration(enable_nea=False, enable_lfse=False, reacquisition_s=0)
    tracker = SimulatedStarTracker(config=configuration)
    for index, angle_deg in enumerate((0, 34, 40, 90)):
        sun = np.array([np.sin(np.radians(angle_deg)), 0, np.cos(np.radians(angle_deg))])
        receipt = _validation_sample(tracker, index * 5, sun=sun)
        assert receipt.valid == (angle_deg >= 35)
        if angle_deg == 0:
            assert receipt.reason == 'SUN_HARD_OFF'
        if angle_deg == 34:
            assert receipt.reason == 'SUN_EXCLUSION'
    earth_radius_rad = np.arcsin(configuration.earth_limb_radius_km / 7000)
    tracker = SimulatedStarTracker(config=configuration)
    for index, clearance_deg in enumerate((21, 25, 40)):
        nadir_angle_rad = earth_radius_rad + np.radians(clearance_deg)
        nadir = np.array([np.sin(nadir_angle_rad), 0, np.cos(nadir_angle_rad)])
        receipt = _validation_sample(tracker, index * 5, position=-7000000 * nadir)
        assert receipt.valid == (clearance_deg >= 22)
        np.testing.assert_allclose(receipt.earth_limb_angle_deg, clearance_deg, atol=1e-10)
    quaternion = _rotation_quaternion(np.array([.7, -.3, .4]))
    mount = _rotation_quaternion(np.array([-.2, .5, .3]))
    configuration = replace(configuration, mount_quaternion=tuple(mount))
    tracker = SimulatedStarTracker(config=configuration)
    boresight = _dcm_bi_from_q(quaternion) @ mount_to_body(mount)[:, 2]
    receipt = _validation_sample(tracker, 0, quaternion=quaternion, sun=boresight,
                                 position=boresight * 7000000)
    assert receipt.reason == 'SUN_HARD_OFF'
    receipt = _validation_sample(tracker, 5, quaternion=quaternion, sun=-boresight,
                                 position=boresight * 7000000)
    assert receipt.valid
    print('PASS 6: Sun 0/34/40/90 deg, Earth limb 21/25/40 deg, rotated mount and attitude')

    tracker = SimulatedStarTracker(config=_validation_configuration(
        cold_start_s=4, reacquisition_s=4, low_trust_packets=5))
    assert not _validation_sample(tracker, 0).valid
    assert _validation_sample(tracker, 4).valid
    receipt = _validation_sample(tracker, 5, rate=np.radians([0, 0, 4]))
    assert receipt.mode == 'LOST' and receipt.reason == 'RATE_LIMIT'
    _validation_sample(tracker, 6)
    receipt = _validation_sample(tracker, 6.1)
    assert receipt.mode == 'ACQUISITION'
    assert not _validation_sample(tracker, 10).valid
    trust_flags = []
    for index in range(6):
        receipt = _validation_sample(tracker, 10.1 + index / 10)
        assert receipt.valid
        trust_flags.append(receipt.trusted)
    assert trust_flags == [False, False, False, False, False, True]
    print('PASS 7: cold start, rate loss, TFS recovery and first-five low-trust solutions')

    first = SimulatedStarTracker(config=StarTrackerParameters.nominal())
    second = SimulatedStarTracker(config=StarTrackerParameters.nominal())
    for index in range(200):
        first_receipt = _validation_sample(first, index / 10)
        second_receipt = _validation_sample(second, index / 10)
        if first_receipt is None:
            assert second_receipt is None
        else:
            assert first_receipt.t_meas_s == second_receipt.t_meas_s
            assert first_receipt.t_arrival_s == second_receipt.t_arrival_s
            assert first_receipt.reason == second_receipt.reason
            np.testing.assert_array_equal(first_receipt.quaternion_eci, second_receipt.quaternion_eci)
    _validate_other_sensor_streams()
    print('PASS 8: identical seeded receipts and independent gyro/magnetic/Sun/GPS streams')
    _validate_fusion_and_profiles()
    print('PASS 9: mounted anisotropic covariance, innovation gate, untrusted rejection and YAML profiles')
    _validate_operating_channels()
    print('PASS 10: operating inflation, thermal drift, outliers, dropouts, orbit outages and delivery bounds')


def _validate_other_sensor_streams():
    """Interleave tracker ticks between matching independent acquisition streams."""
    from simulate_gyroscope import SimulatedGyroscope
    from simulate_magnetometer import SimulatedMagnetometer
    from simulate_sunsensor import SimulatedSunSensorArray
    from satellite_parameters import ImuSimParameters, SunSensorArrayParameters

    configuration = ImuSimParameters.nominal()
    first_gyro = SimulatedGyroscope(configuration)
    second_gyro = SimulatedGyroscope(configuration)
    first_magnetic = SimulatedMagnetometer(configuration)
    second_magnetic = SimulatedMagnetometer(configuration)
    first_sun = SimulatedSunSensorArray(SunSensorArrayParameters.nominal())
    second_sun = SimulatedSunSensorArray(SunSensorArrayParameters.nominal())
    tracker = SimulatedStarTracker(config=StarTrackerParameters.nominal())
    for index in range(50):
        time_s = index / 10
        truth = [1, 0, 0, 0]
        arguments = (time_s, truth, np.array([.01, -.02, .03]))
        gyro_reference = first_gyro.get_raw_data(*arguments)
        magnetic_reference = first_magnetic.get_raw_data(time_s, truth, [2e-5, 0, 3e-5])
        sun_reference = first_sun.get_raw_data(time_s, truth, [1, 0, 0], 1, [0, 0, 7000000])
        _validation_sample(tracker, time_s)
        gyro_actual = second_gyro.get_raw_data(*arguments)
        magnetic_actual = second_magnetic.get_raw_data(time_s, truth, [2e-5, 0, 3e-5])
        sun_actual = second_sun.get_raw_data(time_s, truth, [1, 0, 0], 1, [0, 0, 7000000])
        for reference, actual in ((gyro_reference, gyro_actual), (magnetic_reference, magnetic_actual)):
            if reference is None:
                assert actual is None
            else:
                assert reference.data == actual.data
        if sun_reference is not None:
            assert sun_reference == sun_actual
    # GPS imports initialize the JVM. Use independent frame context and
    # passed-in position/velocity; never advance the simulation engine.
    from simulate_gps import SimulatedGPS
    from satellite_parameters import GpsSimParameters
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from org.orekit.frames import FramesFactory
    from org.orekit.utils import IERSConventions

    provider = SimpleNamespace(
        epoch_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        inertial_frame=FramesFactory.getEME2000(),
        earth_fixed_frame=FramesFactory.getITRF(IERSConventions.IERS_2010, True))
    first_gps = SimulatedGPS(provider, GpsSimParameters.nominal())
    second_gps = SimulatedGPS(provider, GpsSimParameters.nominal())
    for index in range(20):
        time_s = 6 + index
        reference = first_gps.get_raw_data(time_s, [7000000, 0, 0], [0, 7500, 0])
        _validation_sample(tracker, time_s)
        actual = second_gps.get_raw_data(time_s, [7000000, 0, 0], [0, 7500, 0])
        if reference is None:
            assert actual is None
        else:
            assert reference.data == actual.data
            assert reference.t_meas_s == actual.t_meas_s
            assert reference.t_arrival_s == actual.t_arrival_s
    np.testing.assert_array_equal(first_gps.rng.normal(size=100), second_gps.rng.normal(size=100))


def _validate_fusion_and_profiles():
    from compute_simulated_attitude import AttitudeEstimator
    from satellite_parameters import _load_configuration
    from pathlib import Path
    import yaml

    mount = tuple(_rotation_quaternion(np.array([.3, .6, -.2])))
    truth = _rotation_quaternion(np.array([.4, -.5, .7]))
    configuration = _validation_configuration(mount_quaternion=mount, enable_lfse=False)
    tracker = SimulatedStarTracker(config=configuration)
    boresight = _dcm_bi_from_q(truth) @ tracker.mount_rotation[:, 2]
    receipt = _validation_sample(tracker, 0, quaternion=truth, sun=-boresight,
                                 position=boresight * 7000000)
    rotation = tracker.mount_rotation
    expected = rotation @ np.diag(np.square([4.3, 4.3, 26]) * ARCSEC_TO_RAD**2) @ rotation.T
    np.testing.assert_allclose(receipt.covariance_body_rad2, expected)
    measured_dcm = _dcm_bi_from_q(receipt.quaternion_eci)
    expected_dcm = _dcm_bi_from_q(truth) @ _dcm_bi_from_q(
        _rotation_quaternion(rotation @ receipt.noise_arcsec * ARCSEC_TO_RAD))
    np.testing.assert_allclose(measured_dcm, expected_dcm, atol=1e-14)
    estimator = AttitudeEstimator(truth)
    estimator.update(0, np.zeros(3), None, None, star_tracker=receipt)
    assert estimator.star_tracker_used_last
    np.testing.assert_allclose(estimator.q_eci, receipt.quaternion_eci, atol=1e-9)
    assert np.trace(estimator.P[:3, :3]) > 0
    outlier = replace(receipt, t_meas_s=.1, t_arrival_s=.1,
                      quaternion_eci=_quat_multiply(_rotation_quaternion(np.array([.1, 0, 0])), truth))
    estimator.update(.1, np.zeros(3), None, None, star_tracker=outlier)
    assert not estimator.star_tracker_used_last
    untrusted = replace(receipt, t_meas_s=.2, t_arrival_s=.2, trusted=False)
    estimator.update(.2, np.zeros(3), None, None, star_tracker=untrusted)
    assert not estimator.star_tracker_used_last
    data = yaml.safe_load(Path('satellite_parameters.yaml').read_text(encoding='utf-8'))
    loaded = _load_configuration()[10].star_tracker
    assert loaded.profile == data['sensor_profiles']['star_tracker']
    from copy import deepcopy
    from unittest.mock import patch
    for name in ('custom', 'perfect', 'off', 'nominal', 'degraded', 'stress'):
        selected_data = deepcopy(data)
        selected_data['use_advanced_satellite_model'] = False
        selected_data['star_tracker']['enabled'] = True
        selected_data['sensor_profiles']['star_tracker'] = name
        with patch('yaml.safe_load', return_value=selected_data):
            loaded = _load_configuration()[10]
        assert loaded.star_tracker.profile == name
        assert loaded.enable_star_tracker == (name != 'off')
        if name != 'custom':
            expected_preset = getattr(StarTrackerParameters, name)()
            np.testing.assert_array_equal(loaded.star_tracker.nea_sigma_arcsec, expected_preset.nea_sigma_arcsec)
        selected_data = deepcopy(data)
        selected_data['use_advanced_satellite_model'] = False
        selected_data['star_tracker']['enabled'] = False
        selected_data['sensor_profiles']['star_tracker'] = name
        with patch('yaml.safe_load', return_value=selected_data):
            assert not _load_configuration()[10].enable_star_tracker
    for rate_hz in (5, 8, 10):
        tracker = SimulatedStarTracker(config=replace(configuration, update_rate_hz=rate_hz))
        receipt = _validation_sample(tracker, 0, quaternion=truth, sun=-boresight,
                                     position=boresight * 7000000)
        np.testing.assert_allclose(receipt.covariance_body_rad2, expected)


def _validate_operating_channels():
    """Prove operating channels without depending on rare-event statistics."""
    base = _validation_configuration(enable_lfse=False)
    cold = SimulatedStarTracker(config=replace(base, enable_temperature_rate_inflation=True))
    hot = SimulatedStarTracker(config=replace(base, enable_temperature_rate_inflation=True,
                                              detector_temperature_c=55))
    cold_receipt = _validation_sample(cold, 0)
    hot_receipt = _validation_sample(hot, 0)
    np.testing.assert_allclose(hot_receipt.covariance_body_rad2,
                               25 * cold_receipt.covariance_body_rad2)
    thermal = SimulatedStarTracker(config=replace(
        base, enable_nea=False, enable_thermal=True, detector_temperature_c=40))
    np.testing.assert_allclose(_validation_sample(thermal, 0).noise_arcsec, [10, 10, 0])
    ring = SimulatedStarTracker(config=replace(base, enable_straylight=True))
    sun = [np.sin(np.radians(40)), 0, np.cos(np.radians(40))]
    ring_receipt = _validation_sample(ring, 0, sun=sun)
    assert ring_receipt.valid
    np.testing.assert_allclose(ring_receipt.covariance_body_rad2,
                               4 * cold_receipt.covariance_body_rad2)
    # Forced probability one makes the rare valid-but-wrong branch testable.
    outlier = SimulatedStarTracker(config=replace(
        base, enable_outliers=True, outlier_probability=1,
        outlier_multiplier_min=30, outlier_multiplier_max=30))
    outlier_receipt = _validation_sample(outlier, 0)
    assert outlier_receipt.valid
    np.testing.assert_allclose(outlier_receipt.noise_arcsec, 30 * cold_receipt.noise_arcsec)
    np.testing.assert_allclose(outlier_receipt.covariance_body_rad2,
                               cold_receipt.covariance_body_rad2)
    dropout = SimulatedStarTracker(config=replace(base, enable_dropouts=True, dropout_probability=1))
    assert _validation_sample(dropout, 0).reason == 'RANDOM_DROPOUT'
    burst = SimulatedStarTracker(config=replace(base, enable_dropouts=True, burst_start_probability=1))
    assert _validation_sample(burst, 0).reason == 'BURST_DROPOUT'
    scheduled = SimulatedStarTracker(config=replace(base, outages_s=((0, 2),)))
    assert _validation_sample(scheduled, 0).reason == 'SCHEDULED_OUTAGE'
    # An inertially fixed boresight sees the Earth disk cross its view as
    # the passed-in position moves around a circular polar orbit.
    orbit_tracker = SimulatedStarTracker(config=replace(base, reacquisition_s=0))
    observed_modes = set()
    for index in range(180):
        phase_rad = 2 * np.pi * index / 180
        position = 7000000 * np.array([np.sin(phase_rad), 0, np.cos(phase_rad)])
        receipt = _validation_sample(orbit_tracker, index, position=position)
        observed_modes.add(receipt.mode)
    assert 'TRACKING' in observed_modes and 'BLINDED' in observed_modes
    delayed = SimulatedStarTracker(config=replace(
        base, enable_latency=True, latency_sigma_s=.1))
    delivered = set()
    for index in range(1001):
        time_s = index / 100
        receipt = _validation_sample(delayed, time_s)
        if receipt is not None:
            assert receipt.t_arrival_s <= time_s
            delivered.add(receipt.t_meas_s)
            delay_s = receipt.t_arrival_s - receipt.t_meas_s
            assert .0798 < delay_s < .2502
    assert len(delivered) > 60


if __name__ == '__main__':
    if sys.argv[1:] == ['validate']:
        _validate()
    else:
        print('Run: python simulate_startracker.py validate')
