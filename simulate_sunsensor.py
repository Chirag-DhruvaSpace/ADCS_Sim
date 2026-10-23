"""simulate_sunsensor.py -- the simulated COARSE SUN SENSOR (CSS) ARRAY.

WHAT THIS IS (plain language): a stand-in for a real multi-cell analog coarse
sun sensor: several photocells on the spacecraft hull, each one reporting
sunlight as a FRACTION OF FULL SCALE (0..1, cosine response, field-of-view
cutoff). No single cell knows the sun direction -- the flight computer
RECONSTRUCTS it by least squares (A s = b) over the active cells, exactly
like the reference six-cell design this module extends. The array is the
attitude estimator's second reference (with the magnetometer the first).

Every cell is slightly wrong in the ways real hardware is wrong: a solder
misalignment of its mounting normal, a constant bias, a slowly-drifting
thermal offset, gain (scale) error, cubic nonlinearity, fresh white noise,
ADC quantization and saturation. The ARRAY as a whole additionally models
the environment hitting the hardware: gradual eclipse (penumbra), Earth
albedo on the nadir-facing cells, self-shadowing by bus/panel boxes,
measurement latency and occasional whole-receipt dropouts.

CONFIGURE (the ONE line, in satellite_parameters.py):
    IMU_SIM = ImuSimParameters.nominal()    # carries sun_array=...nominal()
    IMU_SIM = ImuSimParameters.off()        # no IMU at all (legacy behavior)
    (the array itself: SunSensorArrayParameters.off/perfect/nominal/degraded/stress)

SELF-TEST (from the project root):
    python simulate_sunsensor.py             # demo: per-cell table + reconstruction
    python simulate_sunsensor.py validate    # staged proof (13 stages)

PLAIN-LANGUAGE GLOSSARY:
    cell           one photocell: mounting normal n_i, cosine response,
                   reads 0 outside its field-of-view (FOV) cone.
    FOV            half-angle of the cone a cell can see (default 90 deg).
    penumbra       gradual eclipse: the engine lighting ratio F in [0,1]
                   scales the direct sun term (1 = full sun, 0 = umbra).
    self-shadowing a bus/panel box blocks the sun; ray-vs-box (slab) test
                   from the cell position along the sun ray.
    albedo         sunlight reflected off Earth, an ADDITIVE term on the
                   nadir-facing cells (simplified engineering model).
    alignment      the cell is mounted a hair off its nominal normal; drawn
                   once at power-on (the chip is soldered that way).
    bias / drift   constant electronic offset + Gauss-Markov thermal wander.
    scale / k3     gain error and cubic nonlinearity of the electronics.
    ADC counts     the digitized output (2^adc_bits - 1 == full scale).
    reconstruction the flight computer's least-squares solve for the body-
                   frame sun direction over the active cells.

UNITS: cell outputs are DIMENSIONLESS fractions of full scale (0..1); the
reconstructed sun direction is a dimensionless unit vector in the BODY frame
(order [X, Y, Z], the repo's convention). Angles are radians internally,
degrees in config/telemetry.

GOLDEN RULES (enforced below):
    1. This module NEVER advances or fetches simulation truth. Truth
       (attitude quaternion, sun direction, eclipse fraction, position) is
       passed IN by the loop each tick -- the sensor is a pure lying machine.
    2. ALL randomness comes from ONE numpy generator seeded from
       SunSensorArrayParameters.seed. No global np.random anywhere.
    3. Frame math only via the repo's own _dcm_bi_from_q copy
       (the B_body = C_bi.T @ B_eci convention). Do not "fix" it.
    4. Receipts (SunArrayMeasurement) are what flight software consumes.
       The in-memory records (receipt + stapled truth) exist ONLY for the
       demo/validation -- the ADCS never reads them.

NOTE ON CELL POSITIONS: the mounting offset p_i is physically irrelevant for
the DIRECTION measurement (parallax of a 0.25 m arm at 1 AU ~ 1e-11 rad); it
exists ONLY for the self-shadowing ray test against the blocker boxes. The
albedo term is intentionally NOT blocked by the shadow ray (a documented
simplification: reflected light arrives as a hemisphere, not a ray).
"""
from __future__ import annotations

import collections
import math
import sys
from bisect import bisect_right
from dataclasses import dataclass, replace

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

def sensor_to_body_matrix(normal_body, roll_rad=0.0):
    """Create sensor axes with local +Z along its facing normal."""
    sensor_z = np.asarray(normal_body, dtype=float)
    sensor_z = sensor_z / np.linalg.norm(sensor_z)
    reference_axis = np.array([1.0, 0.0, 0.0])
    if abs(sensor_z[0]) > 0.9:
        reference_axis = np.array([0.0, 1.0, 0.0])
    sensor_x = reference_axis - np.dot(reference_axis, sensor_z) * sensor_z
    sensor_x = sensor_x / np.linalg.norm(sensor_x)
    sensor_y = np.cross(sensor_z, sensor_x)
    rolled_x = math.cos(roll_rad) * sensor_x + math.sin(roll_rad) * sensor_y
    rolled_y = -math.sin(roll_rad) * sensor_x + math.cos(roll_rad) * sensor_y
    return np.column_stack((rolled_x, rolled_y, sensor_z))

def signed_16_bit(value):
    return max(-32768, min(32767, round(value)))

def quadrant_signal(direction_sensor, brightness, config):
    """Light reaching each quadrant, before electronic error and digitization."""
    direction_x, direction_y, direction_z = map(float, direction_sensor)
    if direction_z <= 0.0:
        return (0.0, 0.0, 0.0, 0.0)
    maximum_ratio = math.tan(config.fine_fov_half_angle_rad)
    horizontal_ratio = direction_x / direction_z
    vertical_ratio = direction_y / direction_z
    if abs(horizontal_ratio) > maximum_ratio or abs(vertical_ratio) > maximum_ratio:
        return (0.0, 0.0, 0.0, 0.0)
    spot_x = horizontal_ratio / maximum_ratio
    spot_y = vertical_ratio / maximum_ratio
    total_signal_counts = brightness * config.fine_total_signal_counts
    return (
        total_signal_counts * (1 + spot_x) * (1 + spot_y) / 4,
        total_signal_counts * (1 - spot_x) * (1 + spot_y) / 4,
        total_signal_counts * (1 - spot_x) * (1 - spot_y) / 4,
        total_signal_counts * (1 + spot_x) * (1 - spot_y) / 4,
    )

def simulate_fine_sensor(sun_direction_sensor, brightness, temperature_k, config,
                         noise_sigma, random_generator, albedo_direction_sensor=None,
                         albedo_brightness=0.0):
    """Form quadrants, then derive the sensor's reported vector from those counts.

    A pinhole shifts the light spot by distance*tan(angle). The four quadrant
    fractions use a linear split across that spot displacement. Vendor optical
    response curves can replace this equation once the FSS ICD is available.
    """
    maximum_ratio = math.tan(config.fine_fov_half_angle_rad)
    direct_counts = quadrant_signal(sun_direction_sensor, brightness, config)
    reflected_counts = (0.0, 0.0, 0.0, 0.0)
    if albedo_direction_sensor is not None:
        # Existing Earth-albedo irradiance uses the Earth-center direction as
        # a single optical source here, rather than resolving its extended disk.
        reflected_counts = quadrant_signal(albedo_direction_sensor, albedo_brightness, config)
    quadrants = []
    for direct_count, reflected_count in zip(direct_counts, reflected_counts):
        noise_counts = random_generator.normal(0.0, noise_sigma * config.fine_total_signal_counts / 4)
        measured_counts = round(direct_count + reflected_count + noise_counts)
        quadrants.append(max(0, min(config.fine_quadrant_max_counts, measured_counts)))
    quadrant_1, quadrant_2, quadrant_3, quadrant_4 = quadrants
    measured_total = sum(quadrants)
    dark = measured_total < config.fine_eclipse_threshold_counts
    coordinate_x_m = 0.0
    coordinate_y_m = 0.0
    alpha_rad = 0.0
    beta_rad = 0.0
    direction = np.zeros(3)
    if not dark:
        measured_spot_x = (quadrant_1 + quadrant_4 - quadrant_2 - quadrant_3) / measured_total
        measured_spot_y = (quadrant_1 + quadrant_2 - quadrant_3 - quadrant_4) / measured_total
        measured_ratio_x = measured_spot_x * maximum_ratio
        measured_ratio_y = measured_spot_y * maximum_ratio
        coordinate_x_m = config.fine_aperture_distance_m * measured_ratio_x
        coordinate_y_m = config.fine_aperture_distance_m * measured_ratio_y
        alpha_rad = math.atan(measured_ratio_x)
        beta_rad = math.atan(measured_ratio_y)
        direction = np.array([measured_ratio_x, measured_ratio_y, 1.0])
        direction = direction / np.linalg.norm(direction)
    temperature_counts = round((temperature_k - config.fine_temperature_zero_k)
                                * config.fine_temperature_counts_per_k)
    return {
        'Q1': quadrant_1, 'Q2': quadrant_2, 'Q3': quadrant_3, 'Q4': quadrant_4,
        'Temp': max(0, min(65535, temperature_counts)), 'Eclipse': int(dark),
        'CrdX': signed_16_bit(coordinate_x_m * config.fine_coordinate_counts_per_m),
        'CrdY': signed_16_bit(coordinate_y_m * config.fine_coordinate_counts_per_m),
        'VecX': signed_16_bit(direction[0] * config.fine_vector_scale_counts),
        'VecY': signed_16_bit(direction[1] * config.fine_vector_scale_counts),
        'VecZ': signed_16_bit(direction[2] * config.fine_vector_scale_counts),
        'Alpha': signed_16_bit(math.degrees(alpha_rad) * 100),
        'Beta': signed_16_bit(math.degrees(beta_rad) * 100),
    }

def earth_albedo_fractions(position_eci, sun_eci, body_to_eci, normals, fov_cos,
                           reflectivity, patches=2048):
    """Lambertian spherical Earth surface quadrature, normalized to solar flux.

    Uniform reflectivity, no clouds/terrain/atmospheric scattering. Includes
    inverse-square range, illuminated/visible surface and each sensor FOV.
    This is an engineering approximation, not a measured Earth albedo map.
    """
    radius = 6371008.8
    r = np.asarray(position_eci, float)
    if np.linalg.norm(r) <= radius:
        return np.zeros(len(normals))
    index = np.arange(patches)
    axis = r / np.linalg.norm(r)
    cap = radius / np.linalg.norm(r)
    z = cap + (1-cap) * (index + 0.5) / patches
    phi = index * (np.pi * (3 - np.sqrt(5)))
    rho = np.sqrt(1-z*z)
    helper = np.array([0., 0., 1.]) if abs(axis[2]) < .9 else np.array([1., 0., 0.])
    e1 = np.cross(helper, axis); e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    vector_length = rho[:, None]*np.cos(phi)[:, None]*e1 + rho[:, None]*np.sin(phi)[:, None]*e2 + z[:, None]*axis
    ray = vector_length * radius - r
    distance = np.linalg.norm(ray, axis=1)
    ray /= distance[:, None]
    illumination = np.maximum(0., vector_length @ sun_eci)
    emission = np.maximum(0., np.sum(vector_length * -ray, axis=1))
    weights = reflectivity * (2 * radius**2 * (1-cap) / patches) * illumination * emission / distance**2
    incidence = normals @ body_to_eci.T @ ray.T
    response = np.where((incidence >= fov_cos[:, None]) & (incidence > 0), incidence, 0.)
    return response @ weights











def _ray_hits_box(p_body, d_body, center, half_extents) -> bool:
    """Standard slab ray-vs-AABB test: does the ray from p along d (both body
    frame) intersect the axis-aligned box (center +/- half_extents)? Only
    intersections IN FRONT of the ray origin count (t > 0)."""
    p = np.asarray(p_body, dtype=float).reshape(3)
    d = np.asarray(d_body, dtype=float).reshape(3)
    lo = np.asarray(center, dtype=float).reshape(3) - np.asarray(half_extents, dtype=float).reshape(3)
    hi = np.asarray(center, dtype=float).reshape(3) + np.asarray(half_extents, dtype=float).reshape(3)
    t_near, t_far = -np.inf, np.inf
    for axis in range(3):
        if abs(d[axis]) < 1e-15:
            if p[axis] < lo[axis] or p[axis] > hi[axis]:
                return False          # ray parallel to this slab pair and outside
        else:
            later_time_s = (lo[axis] - p[axis]) / d[axis]
            t2 = (hi[axis] - p[axis]) / d[axis]
            if later_time_s > t2:
                later_time_s, t2 = t2, later_time_s
            t_near = max(t_near, later_time_s)
            t_far = min(t_far, t2)
            if t_near > t_far:
                return False
    return t_far >= max(t_near, 0.0) and t_far > 0.0

# ---------------------------------------------------------------------------
# Receipts -- one output of the whole array, units/frames explicit.
# ---------------------------------------------------------------------------
@dataclass
class SunCellSample:
    """One photocell's output for one array sample. output_fraction is the
    DIMENSIONLESS fraction of full scale (0..1); angle_deg is the cone angle
    between the cell normal and the reconstructed-against sun direction
    (arccos of the output, None when the cell reads 0)."""
    name: str
    output_fraction: float               # 0..1, fraction of full scale
    output_pct: float                    # 0..100 (dashboard convenience)
    adc_counts: int                      # digitized output (2^adc_bits-1 max)
    angle_deg: float | None              # arccos(output); None when output == 0
    used: bool                           # included in the reconstruction solve
    in_fov: bool                         # sun inside this cell's FOV cone
    shadowed: bool                       # blocked by a configured box
    saturated: bool                      # pre-ADC value exceeded full scale
    eclipse_factor_applied: float        # lighting ratio F applied (0..1)
    albedo_fraction: float               # additive Earth-albedo term (0..1)


@dataclass
class SunArrayMeasurement:
    """One full-array receipt (what the flight software consumes).
    reconstructed_body is the flight computer's unit-vector estimate of the
    sun direction in the BODY frame (or None when the solve fails -- during
    eclipse, for example; coasting on gyro+magnetometer is then correct and
    expected, not an error)."""
    t_meas_s: float
    t_arrival_s: float
    cells: list                          # list[SunCellSample]
    reconstructed_body: np.ndarray | None
    reconstruction_valid: bool
    method: str                          # "least_squares" | failure reason
    valid: bool                          # False on a dropout sample


@dataclass(frozen=True)
class RawSunCell:
    name: str
    adc_counts: int
    saturated: bool


@dataclass(frozen=True)
class RawFineSunSensor:
    name: str
    slave_id: int
    data: dict                         # Fields returned by FSS_GetTelemetry


@dataclass(frozen=True)
class RawSunSample:
    t_meas_s: float
    t_arrival_s: float
    valid: bool
    adc_bits: int
    cells: tuple
    sensors: tuple = ()


class SimulatedSunSensorArray:
    """The simulated coarse-sun-sensor ARRAY. Feed the TRUE state each loop
    tick with update(t, q_truth, sun_eci_truth, eclipse_fraction, r_eci_truth);
    it answers with a SunArrayMeasurement on its own fixed-rate grid, or None
    when the grid did not tick this update.

    It NEVER touches the simulation truth itself -- truth comes in as
    arguments (the "lying machine" rule).
    """

    def __init__(self, config, record_history=True) -> None:
        configuration = config
        self.cfg = configuration
        # SunSensorArrayParameters.post_init already validated everything
        # (fail loudly at startup); re-check the cheap invariants defensively.
        if len(configuration.cells) < 3:
            raise ValueError("sun sensor array needs at least 3 cells")
        self.rng = np.random.default_rng(configuration.seed)   # ONE generator, all randomness

        cells = list(configuration.cells)
        bits = int(cells[0].adc_bits)
        self._bits = bits
        self._full_scale = float(2 ** bits - 1)

        # ---- per-cell power-on draws (drawn ONCE -- soldered that way) ------
        self._names = [c.name for c in cells]
        self._n_nominal = []                 # NOMINAL normals (what the FC uses)
        self._n_effective = []               # AS-MOUNTED normals (physics uses)
        self._positions = []
        self._fov_cos = []                   # cos(half FOV) per cell
        self._bias0 = []
        self._drift = []
        self._scale = []
        self._k3 = []
        for c in cells:
            vector_length = np.asarray(c.normal_body, dtype=float).reshape(3)
            n_norm = float(np.linalg.norm(vector_length))
            if n_norm < 1e-9:
                raise ValueError(f"cell {c.name}: normal_body must be nonzero")
            vector_length = vector_length / n_norm
            if not (0.0 < float(c.fov_half_angle_deg) <= 90.0):
                raise ValueError(f"cell {c.name}: fov_half_angle_deg must be in (0, 90]")
            if not isinstance(c.adc_bits, int) or not (2 <= c.adc_bits <= 16):
                raise ValueError(f"cell {c.name}: adc_bits must be an int in [2, 16] "
                                 f"(the validate harness deliberately exercises 4 bits)")
            if int(c.adc_bits) != int(cells[0].adc_bits):
                raise ValueError("all cells must share one adc_bits depth")
            self._n_nominal.append(vector_length)
            self._positions.append(np.asarray(c.position_body_m, dtype=float).reshape(3))
            self._fov_cos.append(float(math.cos(math.radians(c.fov_half_angle_deg))))
            # (a) mounting misalignment: one small rotation vector, applied via
            #     the house trick R = _dcm_bi_from_q([1, 0.5*v]) (then renormalize).
            sig = math.radians(c.alignment_error_sigma_deg) if configuration.enable_alignment_error else 0.0
            v = np.array([white_noise(self.rng, sig) for _ in range(3)])
            R = _dcm_bi_from_q(np.concatenate(([1.0], 0.5 * v)))
            n_eff = R @ vector_length
            self._n_effective.append(n_eff / np.linalg.norm(n_eff))
            # (e) bias + thermal drift
            self._bias0.append(white_noise(self.rng, c.bias_sigma)
                               if configuration.enable_bias_drift else 0.0)
            self._drift.append(GaussMarkov(c.drift_sigma if configuration.enable_bias_drift else 0.0,
                                           c.drift_tau_s))
            # (f) scale + cubic nonlinearity
            self._scale.append(white_noise(self.rng, c.scale_error_sigma)
                               if configuration.enable_scale_nonlinearity else 0.0)
            self._k3.append(white_noise(self.rng, c.nonlinearity_k3_sigma)
                            if configuration.enable_scale_nonlinearity else 0.0)

        self._n_nominal = np.array(self._n_nominal)      # (n_cells, 3)
        self._n_effective = np.array(self._n_effective)
        self._positions = np.array(self._positions)
        self._fov_cos = np.array(self._fov_cos)
        self._bias0 = np.array(self._bias0)
        self._scale = np.array(self._scale)
        self._k3 = np.array(self._k3)

        # Covered CAD-mounted cells remain valid: the ray test reports their
        # physical self-shadowing, including sensors under folded panels.

        # ---- scheduling / bookkeeping (house pattern) -----------------------
        self._last_t = None
        self._last_k = -1
        # truth history (t, q, F, r_eci); 50 samples ~ 5 s at 0.1 s ticks,
        # far more than the largest configured latency.
        self._history = collections.deque(maxlen=50)
        self.samples = 0                       # grid outputs (valid + dropout)
        self.dropouts = 0

        # ---- in-memory records for validation ONLY (never read by the ADCS) -
        self.records = [] if record_history else collections.deque(maxlen=1)

    # ---- internal helpers ----------------------------------------------------
    def _sample_truth_at(self, t_meas_s):
        """Lookback into the buffered truth at a slightly-past moment
        (latency). The attitude quaternion is linearly interpolated
        component-wise then renormalized (fine over millisecond lags),
        exactly like simulate_magnetometer._sample_truth_at. The eclipse fraction and
        the ECI position change slowly, so they use the BRACKETING nearest
        history value (documented simplification)."""
        times = [h[0] for h in self._history]
        if t_meas_s <= times[0] or len(times) < 2:
            earlier_time_s, earlier_quaternion, earlier_lighting, earlier_position = self._history[0]
            return earlier_time_s, earlier_quaternion, earlier_lighting, earlier_position
        history_index = bisect_right(times, t_meas_s) - 1
        history_index = min(max(history_index, 0), len(times) - 2)
        earlier_time_s, earlier_quaternion, earlier_lighting, earlier_position = self._history[history_index]
        later_time_s, later_quaternion, later_lighting, later_position = self._history[history_index + 1]
        if np.dot(earlier_quaternion, later_quaternion) < 0:
            later_quaternion = -later_quaternion  # q and -q represent the same attitude; take the short arc
        interpolation_fraction = (t_meas_s - earlier_time_s) / (later_time_s - earlier_time_s) if later_time_s > earlier_time_s else 0.0
        quaternion = earlier_quaternion + interpolation_fraction * (later_quaternion - earlier_quaternion)
        quaternion /= np.linalg.norm(quaternion)
        f = later_lighting if interpolation_fraction >= 0.5 else earlier_lighting          # nearest bracket (changes slowly)
        position_eci = (later_position if interpolation_fraction >= 0.5 else earlier_position)        # nearest bracket (changes slowly)
        return (t_meas_s, quaternion, f, position_eci)

    @staticmethod
    def _latency_draw(rng, mean, sigma, lo, hi):
        """One random latency value, clipped into [lo, hi] (fenced dart)."""
        return float(np.clip(rng.normal(mean, sigma), lo, hi))

    # ---- the heartbeat -------------------------------------------------------
    def update(self, t_seconds, q_truth, sun_eci_truth, eclipse_fraction,
               r_eci_truth=None, raw_output=False):
        """Feed ONE loop tick of TRUE state. Returns a SunArrayMeasurement on
        the array's own grid, or None when the grid did not tick this update
        (a returned receipt with valid=False is a dropped sample).

        Truth is passed IN: q_truth = scalar-first body->ECI quaternion,
        sun_eci_truth = true unit Sun direction in ECI, eclipse_fraction =
        the engine lighting ratio F in [0,1] (1 = full sun), r_eci_truth =
        true ECI position (needed only for the Earth-albedo term; None
        disables albedo that tick).
        """
        configuration = self.cfg
        time_s = float(t_seconds)
        quaternion = np.asarray(q_truth, dtype=float).reshape(4)
        sun_eci = np.asarray(sun_eci_truth, dtype=float).reshape(3)
        vector_length = float(np.linalg.norm(sun_eci))
        if vector_length < 1e-12:
            return None
        sun_eci = sun_eci / vector_length
        lighting_ratio = 1.0 if eclipse_fraction is None else float(np.clip(eclipse_fraction, 0.0, 1.0))
        position_eci_m = None if r_eci_truth is None else np.asarray(r_eci_truth, dtype=float).reshape(3)

        if self._last_t is not None and time_s <= self._last_t:
            raise ValueError(
                f"SimulatedSunSensorArray.update received t={time_s} but the previous "
                f"call was t={self._last_t}. Time must move forward.")

        elapsed_time_s = 0.0 if self._last_t is None else time_s - self._last_t
        self._last_t = time_s
        self._history.append((time_s, quaternion.copy(), lighting_ratio, None if position_eci_m is None else position_eci_m.copy()))

        # advance the thermal-drift states by this tick's duration (every
        # tick, on-grid or not -- same pattern as the IMU's wander states)
        if configuration.enable_bias_drift:
            for drift_model in self._drift:
                drift_model.advance(elapsed_time_s, self.rng)

        # own fixed-rate grid; the slot is consumed even on a dropout so a
        # dropped sample is never retried ("bus on the hour")
        sample_index = math.floor(time_s * configuration.update_rate_hz + 1e-9)
        if sample_index <= self._last_k:
            return None
        self._last_k = sample_index
        sample_time_s = sample_index / configuration.update_rate_hz
        self.samples += 1

        # latency: the sample describes the geometry a few ms ago
        latency_s = self._latency_draw(self.rng, configuration.latency_mean_s, configuration.latency_sigma_s,
                                 configuration.latency_min_s, configuration.latency_max_s)
        measurement_time_s, q_meas, measured_lighting_ratio, r_meas = self._sample_truth_at(sample_time_s - latency_s)

        # (a) GEOMETRY: true sun direction in the body frame at t_meas,
        #     using the repo's own convention (B_body = C_bi.T @ B_eci).
        body_to_eci = _dcm_bi_from_q(q_meas)
        sun_direction_body = body_to_eci.T @ sun_eci
        sun_direction_body = sun_direction_body / np.linalg.norm(sun_direction_body)
        # (d) EARTH ALBEDO inputs (simplified engineering model): unit nadir
        #     in the body frame + the lit fraction of the visible disk.
        if r_meas is not None and configuration.enable_albedo:
            r_hat = np.asarray(r_meas, dtype=float) / np.linalg.norm(r_meas)
            earth_direction_body = body_to_eci.T @ (-r_hat)
            earth_illuminated_fraction = float(np.clip(0.5 * (1.0 + float(np.dot(sun_eci, r_hat))), 0.0, 1.0))
        else:
            earth_direction_body = None
            earth_illuminated_fraction = 0.0

        dots_eff = self._n_effective @ sun_direction_body
        dots_nom = self._n_nominal @ sun_direction_body
        dots_alb = (self._n_effective @ earth_direction_body) if earth_direction_body is not None else np.zeros(len(dots_eff))
        albedo_outputs = (earth_albedo_fractions(r_meas, sun_eci, body_to_eci,
                          self._n_effective, self._fov_cos, configuration.albedo_scale)
                          if earth_direction_body is not None else np.zeros(len(dots_eff)))

        # (j) DROPOUT: one per-sample dice for the WHOLE receipt
        valid = not (configuration.dropout_probability > 0.0
                     and self.rng.random() < configuration.dropout_probability)
        if not valid:
            self.dropouts += 1

        cell_samples = []
        outputs = np.zeros(len(self._names))
        for cell_index, cell_name in enumerate(self._names):
            cell = self._measure_cell(cell_index, cell_name, dots_eff[cell_index],
                measured_lighting_ratio, sun_direction_body, earth_direction_body, albedo_outputs)
            outputs[cell_index] = cell.output_fraction
            cell_samples.append(cell)

        # (3.3) ONBOARD RECONSTRUCTION -- NOMINAL normals (the as-mounted
        # error is unknown to the spacecraft; that ignorance IS the channel).
        if raw_output:
            # Operator diagnostics stay separate from the hardware interface.
            self._last_cell_diagnostics = {c.name: c for c in cell_samples}
            fine_sensors = []
            for index, cell in enumerate(cell_samples):
                cell_config = configuration.cells[index]
                sensor_to_body = sensor_to_body_matrix(self._n_effective[index], cell_config.sensor_roll_rad)
                direction_sensor = sensor_to_body.T @ sun_direction_body
                noise_sigma = cell_config.white_noise_sigma if configuration.enable_white_noise else 0.0
                direct_brightness = max(0.0, cell.output_fraction - cell.albedo_fraction)
                albedo_direction_sensor = None if earth_direction_body is None else sensor_to_body.T @ earth_direction_body
                data = simulate_fine_sensor(direction_sensor, direct_brightness,
                    configuration.fine_temperature_k, configuration, noise_sigma, self.rng,
                    albedo_direction_sensor, cell.albedo_fraction)
                fine_sensors.append(RawFineSunSensor(cell.name, 0x11 + index, data))
            self._raw_receipt = RawSunSample(measurement_time_s, sample_time_s, valid,
                configuration.cells[0].adc_bits, tuple(RawSunCell(c.name, c.adc_counts,
                c.saturated) for c in cell_samples), tuple(fine_sensors))
            return self._raw_receipt
        recon, recon_valid, method = self._reconstruct(outputs)
        for i, u in enumerate(self._used_mask):
            cell_samples[i].used = bool(u)
        used_count = int(np.sum(self._used_mask))

        meas = SunArrayMeasurement(
            t_meas_s=measurement_time_s, t_arrival_s=sample_time_s, cells=cell_samples,
            reconstructed_body=(None if recon is None else recon.copy()),
            reconstruction_valid=bool(recon_valid), method=method, valid=valid)

        # ---- record (receipt + stapled truth) -- VALIDATION ONLY -------------
        self.records.append({
            "t_meas": measurement_time_s, "t_arrival": sample_time_s, "valid": valid,
            "truth": sun_direction_body.copy(),              # true body-frame sun direction
            "ideal_direct": (dots_eff * (dots_eff >= self._fov_cos)).copy(),
            "ideal_direct_nom": (dots_nom * (dots_nom >= self._fov_cos)).copy(),
            "F": float(measured_lighting_ratio), "albedo_f_illum": float(earth_illuminated_fraction),
            "meas": (None if recon is None else recon.copy()),
            "reconstruction_valid": bool(recon_valid), "method": method,
            "outputs": outputs.copy(), "used": list(self._used_mask),
            "cells": cell_samples,
        })
        return meas

    def _measure_cell(self, cell_index, cell_name, incidence_cosine,
                      measured_lighting_ratio, sun_direction_body,
                      earth_direction_body, albedo_outputs):
        """Apply lighting, shadows, albedo and electronics to one photocell."""
        configuration = self.cfg
        in_fov = bool(incidence_cosine >= self._fov_cos[cell_index] and incidence_cosine > 0.0)
        # (a) cosine response, zero outside the FOV cone
        direct_signal = max(0.0, float(incidence_cosine)) if in_fov else 0.0
        ideal_direct = direct_signal
        # (b) PENUMBRA: gradual eclipse scales the direct term
        applied_lighting_ratio = measured_lighting_ratio if configuration.enable_penumbra else float(measured_lighting_ratio > 0.5)
        signal = direct_signal * applied_lighting_ratio
        # (c) SELF-SHADOWING: ray from the cell position along the sun ray
        shadowed = False
        if configuration.enable_self_shadowing and signal > 0.0:
            for blocker in configuration.blockers:
                if _ray_hits_box(self._positions[cell_index], sun_direction_body,
                                 blocker.center_body_m, blocker.half_extents_m):
                    shadowed = True
                    break
        if shadowed:
            signal = 0.0
        # (d) EARTH ALBEDO: additive, NOT blocked by the shadow ray.
        # Surface illumination is computed separately from direct eclipse.
        # Reflected light is real signal even when the Sun is outside FOV.
        albedo = 0.0
        if earth_direction_body is not None and configuration.enable_albedo:
            albedo = float(albedo_outputs[cell_index])
            signal += albedo
        # (e) BIAS + THERMAL DRIFT (gated: a dark cell stays dark when the
        #     channel is off -- no phantom signal with no sun)
        if configuration.enable_bias_drift:
            signal += self._bias0[cell_index] + self._drift[cell_index].value
        # (f) SCALE + NONLINEARITY (gated: multiplicative only, so exact
        #     darkness is preserved; both power-on draws are honored only
        #     when the channel switch is on)
        if configuration.enable_scale_nonlinearity:
            signal = (1.0 + self._scale[cell_index]) * signal + self._k3[cell_index] * signal ** 3
        # (g) WHITE NOISE
        if configuration.enable_white_noise:
            signal += white_noise(self.rng, configuration.cells[cell_index].white_noise_sigma)
        # (i) SATURATION flag: pre-ADC value above full scale
        signal_before_digitization = signal
        saturated = bool(configuration.enable_saturation and signal_before_digitization > 1.0)
        # (h) ADC QUANTIZATION (+ inherent clamp: a photocell cannot read <0 or >1)
        if configuration.enable_quantization:
            counts = int(round(float(np.clip(signal, 0.0, 1.0)) * self._full_scale))
            signal = counts / self._full_scale
        else:
            signal = float(np.clip(signal, 0.0, 1.0))
            counts = int(round(signal * self._full_scale))
        return SunCellSample(
            name=cell_name,
            output_fraction=float(signal),
            output_pct=100.0 * float(signal),
            adc_counts=counts,
            angle_deg=(None if signal <= 0.0 else float(np.degrees(np.arccos(np.clip(signal, 0.0, 1.0))))),
            used=False,
            in_fov=in_fov,
            shadowed=shadowed,
            saturated=saturated,
            eclipse_factor_applied=float(applied_lighting_ratio),
            albedo_fraction=float(albedo),
        )

    def get_raw_data(self, t_seconds=None, q_truth=None, sun_eci_truth=None,
                     eclipse_fraction=1.0, r_eci_truth=None):
        """Return FSS records plus separate photocell diagnostics for the UI."""
        if not self.cfg.enabled:
            return None
        if len(self.cfg.cells) > 6:
            raise ValueError('FSS interface supports at most six sensor addresses, 0x11..0x16')
        if t_seconds is None or t_seconds == getattr(self, '_raw_tick', None):
            return getattr(self, '_raw_receipt', None)
        self._raw_receipt = self.update(t_seconds, q_truth, sun_eci_truth,
            eclipse_fraction, r_eci_truth, raw_output=True)
        self._raw_tick = float(t_seconds)
        return self._raw_receipt

    def _reconstruct(self, outputs):
        """The flight computer's least-squares solve A s = b over ALL cells
        whose output exceeds the activation threshold. Requires at least
        min_cells_for_solution used cells AND a full-rank A (3 non-coplanar
        normals); normalizes the solution. Returns (unit vector | None,
        valid, method-string)."""
        from compute_simulated_attitude import reconstruct_sun
        direction, valid, method, self._used_mask = reconstruct_sun(
            outputs, self._n_nominal, self.cfg.activation_threshold,
            self.cfg.min_cells_for_solution)
        return direction, valid, method



# ---------------------------------------------------------------------------
# Self-test harness (house style: demo + staged validate, INSIDE this file).
# Pure synthetic truth -- no orbit provider, no JVM, runs in milliseconds.
# ---------------------------------------------------------------------------
def _angle_between(u, v) -> float:
    """Angle between two vectors in degrees."""
    c = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-30))
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def _feed(array, duration_s, dt, sun_eci, q=None, F=1.0, r_eci=None):
    """Feed a constant synthetic truth for duration_s (F may be a callable of
    the step index). Returns the array (records accumulate)."""
    q = np.array([1.0, 0.0, 0.0, 0.0]) if q is None else np.asarray(q, float)
    n_steps = int(round(duration_s / dt))
    for i in range(1, n_steps + 1):
        f = F(i) if callable(F) else F
        array.update(i * dt, q, sun_eci, f, r_eci)
    return array


def _status_string(c) -> str:
    if not c.in_fov:
        return "out-of-FOV"
    if c.shadowed:
        return "shadowed"
    if c.saturated:
        return "saturated"
    if c.eclipse_factor_applied < 1.0:
        return "eclipsed"
    return "used" if c.used else "in-FOV"


def run_demo() -> None:
    """Short standalone tour: constant attitude, three sun directions (one
    deliberately degenerate), NOMINAL array. Prints the per-cell table and
    the reconstruction error, in the reference six-cell design's style."""
    from satellite_parameters import SunSensorArrayParameters
    print("=" * 78)
    print(" SUN SENSOR ARRAY DEMO -- NOMINAL profile (realistic per-cell errors)")
    print("=" * 78)
    cfg = SunSensorArrayParameters.nominal()
    q = np.array([1.0, 0.0, 0.0, 0.0])          # constant attitude (identity)
    sun_dirs = {
        "45-deg (3 diagonals)": np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0),
        "+X broadside":        np.array([1.0, 0.0, 0.0]),
        "+Z (degenerate geom)": np.array([0.0, 0.0, 1.0]),
    }
    for label, sun in sun_dirs.items():
        array = SimulatedSunSensorArray(cfg)
        _feed(array, 1.0, 0.1, sun, q=q)
        rec = array.records[-1]
        print(f"\nsun direction: {label}  truth(body) = "
              f"[{rec['truth'][0]:+.4f}, {rec['truth'][1]:+.4f}, {rec['truth'][2]:+.4f}]")
        print(f"  {'cell':<22} | {'illum %':>8} | {'cone':>7} | status")
        print("  " + "-" * 52)
        for c in rec["cells"]:
            ang = "--" if c.angle_deg is None else f"{c.angle_deg:6.2f}"
            print(f"  {c.name:<22} | {c.output_pct:7.1f}% | {ang:>7} | {_status_string(c)}")
        if rec["reconstruction_valid"]:
            r = rec["meas"]
            err = _angle_between(r, rec["truth"])
            print(f"  reconstructed : [{r[0]:+.4f}, {r[1]:+.4f}, {r[2]:+.4f}]  "
                  f"error vs truth = {err:.4f} deg  ({rec['method']})")
        else:
            print(f"  reconstructed : FAILED ({rec['method']}) -- coast on gyro+mag")
    print("\ndone.")


# --- validation harness ------------------------------------------------------
_VAL_RESULTS = []
_VAL_DT = 0.1


def _check(stage: str, name: str, ok: bool, detail: str) -> None:
    _VAL_RESULTS.append((stage, name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {stage:<12} {name}: {detail}", flush=True)


def _sun_vec(*xyz):
    v = np.array(xyz, dtype=float)
    return v / np.linalg.norm(v)


# ---- STAGE 1: PERFECT -------------------------------------------------------
def _check_perfect() -> None:
    from satellite_parameters import SunSensorArrayParameters
    cfg = SunSensorArrayParameters.perfect()
    arr = _feed(SimulatedSunSensorArray(cfg), 20.0, _VAL_DT, _sun_vec(1, 1, 1))
    recs = arr.records
    good = [r for r in recs if r["reconstruction_valid"]]
    errs = np.array([float(np.max(np.abs(r["meas"] - r["truth"]))) for r in good])
    emax = float(errs.max()) if len(errs) else float("inf")
    _check("PERFECT", "1 recon == truth", len(good) == len(recs) and emax < 1e-9,
           f"max |recon-truth| = {emax:.3e} (< 1e-9), {len(good)}/{len(recs)} receipts solved")
    ts = np.array([r["t_arrival"] for r in recs])
    gaps = np.diff(ts)
    _check("PERFECT", "2 cadence exact", np.all(np.abs(gaps - _VAL_DT) < 1e-9),
           f"{len(ts)} samples, gaps all exactly {_VAL_DT} s")
    ok_lag = all(r["t_arrival"] >= r["t_meas"] - 1e-12 for r in recs)
    _check("PERFECT", "3 arrival >= meas", ok_lag, "t_arrival >= t_meas for every sample")
    _check("PERFECT", "4 no dropouts", all(r["valid"] for r in recs),
           f"{arr.dropouts} dropouts (expect 0)")

# ---- STAGE 2: WHITE ---------------------------------------------------------
def _check_white() -> None:
    from satellite_parameters import SunSensorArrayParameters
    cfg = replace(SunSensorArrayParameters.perfect(),
                  enable_white_noise=True, cells=tuple(
                      replace(c, white_noise_sigma=0.003) for c in
                      SunSensorArrayParameters.perfect().cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 60.0, _VAL_DT, _sun_vec(1, 1, 1))
    i = arr._names.index("+Z")
    outs = np.array([r["outputs"][i] for r in arr.records])
    std = float(outs.std())
    _check("WHITE", "5 cell noise std", abs(std - 0.003) < 0.001,
           f"+Z output std = {std:.5f} (target 0.003, tol +/-0.001)")

# ---- STAGE 3: BIAS ----------------------------------------------------------
def _check_bias() -> None:
    from satellite_parameters import SunSensorArrayParameters
    base = SunSensorArrayParameters.perfect()
    cfg = replace(base, enable_bias_drift=True,
                  cells=tuple(replace(c, bias_sigma=0.02, drift_sigma=0.0)
                              for c in base.cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 60.0, _VAL_DT, _sun_vec(1, 1, 1))
    means, widths, lit = [], [], []
    for i in range(len(arr._names)):
        errs = np.array([r["outputs"][i] - r["ideal_direct"][i] for r in arr.records
                         if r["ideal_direct"][i] > 0.1])   # bias is only observable on LIT cells
        lit.append(len(errs) > 0)
        if len(errs):
            means.append(float(errs.mean()))
            p = np.percentile(errs, [5, 95])
            widths.append(float(p[1] - p[0]))
        else:
            means.append(0.0)
            widths.append(0.0)
    n_lit = sum(lit)
    n_loaded = sum(1 for m, l in zip(means, lit) if l and abs(m) > 0.005)
    _check("BIAS", "6 persistent offsets", n_lit == 3 and n_loaded >= 2
           and max(abs(m) for m, l in zip(means, lit) if l) > 0.01,
           f"{n_loaded}/{n_lit} LIT cells with |mean offset| > 0.005 full scale "
           f"(lit-cell means: {[f'{m:+.4f}' for m, l in zip(means, lit) if l]})")
    _check("BIAS", "7 not fresh noise", max(widths) < 0.004,
           f"max 90-10 error width = {max(widths):.5f} (< 0.004 -- constant, not jumping)")

# ---- STAGE 4: DRIFT ---------------------------------------------------------
def _check_drift() -> None:
    from satellite_parameters import SunSensorArrayParameters
    base = SunSensorArrayParameters.perfect()
    cfg = replace(base, enable_bias_drift=True,
                  cells=tuple(replace(c, bias_sigma=0.0, drift_sigma=0.01,
                                      drift_tau_s=50.0) for c in base.cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 1000.0, _VAL_DT, _sun_vec(1, 1, 1))
    i = arr._names.index("+Z")
    errs = np.array([r["outputs"][i] - r["ideal_direct"][i] for r in arr.records])
    moving = float(errs[300:].std())
    x = errs - errs.mean()
    var = float(np.mean(x * x))
    acf1 = float(np.mean(x[:-10] * x[10:]) / var)   # lag 1 s (10 samples @10 Hz)
    _check("DRIFT", "8 changes over time", moving > 0.002,
           f"error std across run = {moving:.5f} (must be > 0.002 -- not a frozen bias)")
    _check("DRIFT", "9 temporally correlated", acf1 > 0.5,
           f"lag-1 s autocorr = {acf1:.2f} (must be > 0.5 -- white would be ~0)")

# ---- STAGE 5: ALIGNMENT -----------------------------------------------------
def _check_alignment() -> None:
    from satellite_parameters import SunSensorArrayParameters
    base = SunSensorArrayParameters.perfect()
    cfg = replace(base, enable_alignment_error=True,
                  cells=tuple(replace(c, alignment_error_sigma_deg=1.0)
                              for c in base.cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 20.0, _VAL_DT, _sun_vec(1, 1, 1))
    recs = [r for r in arr.records if r["reconstruction_valid"]]
    errs = np.array([_angle_between(r["meas"], r["truth"]) for r in recs])
    e = float(errs.mean())
    _check("ALIGN", "10 small nonzero angle", 0.05 < e < 5.0,
           f"mean reconstruction error = {e:.3f} deg (mounting channel; 0 < e < 5)")

# ---- STAGE 6: SCALE / NONLINEARITY ------------------------------------------
def _check_scale() -> None:
    from satellite_parameters import SunSensorArrayParameters
    base = SunSensorArrayParameters.perfect()
    cfg = replace(base, enable_scale_nonlinearity=True,
                  cells=tuple(replace(c, scale_error_sigma=0.2,
                                      nonlinearity_k3_sigma=0.0) for c in base.cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 20.0, _VAL_DT, _sun_vec(1, 1, 1))
    i = arr._names.index("+Z")
    ratios = np.array([r["outputs"][i] / r["ideal_direct"][i] for r in arr.records
                       if r["ideal_direct"][i] > 0.1])
    dev = abs(float(ratios.mean()) - 1.0)
    expected = 1.0 + arr._scale[i]
    _check("SCALE", "11 sampled gain applied", np.allclose(ratios, expected, atol=1e-12, rtol=0),
           f"+Z meas/ideal = {ratios.mean():.6f}, actual sampled gain = {expected:.6f}")

# ---- STAGE 7: QUANTIZATION --------------------------------------------------
def _check_quantization() -> None:
    from satellite_parameters import SunSensorArrayParameters
    base = SunSensorArrayParameters.perfect()
    cfg = replace(base, enable_quantization=True,
                  cells=tuple(replace(c, adc_bits=4) for c in base.cells))
    arr = _feed(SimulatedSunSensorArray(cfg), 20.0, _VAL_DT, _sun_vec(1, 1, 1))
    on_grid = all(abs(r["outputs"][i] * 15.0 - round(r["outputs"][i] * 15.0)) < 1e-12
                  for r in arr.records for i in range(len(arr._names)))
    _check("QUANT", "12 exact count grid", on_grid,
           "every output lands exactly on the 4-bit count grid (x*15 integer)")

# ---- STAGE 8: FOV -----------------------------------------------------------
def _check_fov() -> None:
    from satellite_parameters import SunSensorArrayParameters
    arr = _feed(SimulatedSunSensorArray(SunSensorArrayParameters.perfect()),
                10.0, _VAL_DT, _sun_vec(1, 0, 0))
    rec = arr.records[-1]
    i_x = arr._names.index("+X")
    others_zero = all(rec["outputs"][i] == 0.0 for i in range(len(arr._names)) if i != i_x)
    _check("FOV", "13 outside cone reads 0", others_zero and rec["outputs"][i_x] > 0.99,
           f"+X = {rec['outputs'][i_x]:.6f}, all other cells exactly 0.0 (sun broadside +X)")

# ---- STAGE 9: PENUMBRA ------------------------------------------------------
def _check_penumbra() -> None:
    from satellite_parameters import SunSensorArrayParameters
    cfg = SunSensorArrayParameters.perfect()      # penumbra stays ON in perfect
    arr = _feed(SimulatedSunSensorArray(cfg), 10.0, _VAL_DT, _sun_vec(1, 1, 1), F=0.5)
    rec = arr.records[-1]
    half = all(abs(rec["outputs"][i] - 0.5 * rec["ideal_direct"][i]) < 1e-12
               for i in range(len(arr._names)))
    _check("PENUMBRA", "14 F=0.5 halves direct", half,
           "every cell output == 0.5 x ideal direct term (gradual eclipse)")
    arr0 = _feed(SimulatedSunSensorArray(cfg), 10.0, _VAL_DT, _sun_vec(1, 1, 1), F=0.0)
    rec0 = arr0.records[-1]
    zeroed = all(rec0["outputs"][i] == 0.0 for i in range(len(arr0._names)))
    _check("PENUMBRA", "15 F=0 -> no solve", zeroed
           and (not rec0["reconstruction_valid"]) and rec0["method"] == "insufficient_cells",
           f"all outputs exactly 0, reconstruction FAILED ({rec0['method']}) -- coast is correct")

# ---- STAGE 10: ALBEDO -------------------------------------------------------
def _check_albedo() -> None:
    from satellite_parameters import SunSensorArrayParameters
    cfg = replace(SunSensorArrayParameters.perfect(), enable_albedo=True)
    arr = _feed(SimulatedSunSensorArray(cfg), 10.0, _VAL_DT, _sun_vec(0, 0, -1),
                r_eci=np.array([0.0, 0.0, -6871000.0]))  # illuminated Earth below +Z cell
    rec = arr.records[-1]
    i = arr._names.index("+Z")
    c = rec["cells"][i]
    _check("ALBEDO", "16 albedo-only signal",
           rec["ideal_direct"][i] == 0.0 and 0.0 < c.output_fraction < cfg.albedo_scale,
           f"+Z cell: direct 0, reflected output {c.output_fraction:.6f}, below reflectivity bound")

# ---- STAGE 11: SHADOWING ----------------------------------------------------
def _check_shadowing() -> None:
    from satellite_parameters import SunSensorArrayParameters, ShadowBlockerParameters
    blocker = ShadowBlockerParameters(name="test-panel",
                                      center_body_m=(0.173, 0.173, 0.423),
                                      half_extents_m=(0.08, 0.08, 0.08))
    cfg = replace(SunSensorArrayParameters.perfect(),
                  enable_self_shadowing=True, blockers=(blocker,))
    arr = _feed(SimulatedSunSensorArray(cfg), 10.0, _VAL_DT, _sun_vec(1, 1, 1))
    rec = arr.records[-1]
    i = arr._names.index("+Z")
    others = [c for c in rec["cells"] if c.name != "+Z"]
    _check("SHADOW", "17 blocked cell only", rec["cells"][i].output_fraction == 0.0
           and rec["cells"][i].shadowed
           and all(c.output_fraction > 0.0 and not c.shadowed for c in others if c.in_fov),
           f"+Z cell zeroed by the box (shadowed=True); every other lit cell unaffected")
    others_ok = all(abs(c.output_fraction - rec["ideal_direct"][i]) < 1e-12
                    for i, c in enumerate(rec["cells"]) if c.name != "+Z" and c.in_fov)
    _check("SHADOW", "18 honest degradation", others_ok
           and (not rec["reconstruction_valid"]) and rec["method"] == "insufficient_cells",
           f"other lit cells exactly at ideal; solve honestly reports "
           f"{rec['method']} (only 2 cells left -- coast on gyro+mag)")

# ---- STAGE 12: DEGENERATE ---------------------------------------------------
def _check_degenerate() -> None:
    from satellite_parameters import (SunSensorArrayParameters,
                                      SunSensorCellParameters)
    base = SunSensorArrayParameters.perfect()
    arr = _feed(SimulatedSunSensorArray(base), 10.0, _VAL_DT, _sun_vec(1, 0, 0))
    rec = arr.records[-1]
    _check("DEGEN", "19 too few cells", (not rec["reconstruction_valid"])
           and rec["method"] == "insufficient_cells",
           f"sun broadside +X: 1 active cell -> FAILED ({rec['method']})")
    coplanar = (
        SunSensorCellParameters("+X", (1.0, 0.0, 0.0), (0.25, 0.0, 0.0)),
        SunSensorCellParameters("-X", (-1.0, 0.0, 0.0), (-0.25, 0.0, 0.0)),
        SunSensorCellParameters("+Y", (0.0, 1.0, 0.0), (0.0, 0.25, 0.0)),
        SunSensorCellParameters("-Y", (0.0, -1.0, 0.0), (0.0, -0.25, 0.0)),
        SunSensorCellParameters("+diag", (0.7071, 0.7071, 0.0), (0.25, 0.25, 0.0)),
        SunSensorCellParameters("-diag", (-0.7071, -0.7071, 0.0), (-0.25, -0.25, 0.0)),
    )
    cfg2 = replace(base, cells=coplanar)
    arr2 = _feed(SimulatedSunSensorArray(cfg2), 10.0, _VAL_DT, _sun_vec(1, 1, 0))
    rec2 = arr2.records[-1]
    _check("DEGEN", "20 coplanar normals", (not rec2["reconstruction_valid"])
           and rec2["method"] == "degenerate_geometry",
           f"3 active cells but all normals coplanar -> rank(A) < 3 ({rec2['method']})")

# ---- STAGE 13: DETERMINISM --------------------------------------------------
def _check_determinism() -> None:
    from satellite_parameters import SunSensorArrayParameters
    cfg0 = SunSensorArrayParameters.nominal()
    a = _feed(SimulatedSunSensorArray(cfg0), 100.0, _VAL_DT, _sun_vec(1, 1, 1))
    b = _feed(SimulatedSunSensorArray(cfg0), 100.0, _VAL_DT, _sun_vec(1, 1, 1))
    oa = np.array([r["outputs"] for r in a.records])
    ob = np.array([r["outputs"] for r in b.records])
    ok_same = (oa.shape == ob.shape and float(np.max(np.abs(oa - ob))) == 0.0)
    _check("DETERM", "21 same seed identical", ok_same,
           f"max diff {float(np.max(np.abs(oa - ob))) if oa.shape == ob.shape else 'shape':.1e}"
           f" (expect exactly 0)")
    cfg1 = replace(cfg0, seed=cfg0.seed + 1)
    c = _feed(SimulatedSunSensorArray(cfg1), 100.0, _VAL_DT, _sun_vec(1, 1, 1))
    oc = np.array([r["outputs"] for r in c.records])
    ok_diff = oa.shape == oc.shape and float(np.max(np.abs(oa - oc))) > 0.0
    _check("DETERM", "22 different seed differs", ok_diff,
           f"max diff vs seed+1 = {float(np.max(np.abs(oa - oc))):.3e} (expect > 0)")

# ---- RUNNER -------------------------------------------------------------------
def run_validation() -> int:
    """Run all 13 stages (22 checks). Prints a PASS/FAIL table, returns the
    process exit code (0 = all pass, 1 = any failure)."""
    global _VAL_RESULTS
    _VAL_RESULTS = []
    print("=" * 78, flush=True)
    print(" SIMULATED SUN SENSOR ARRAY VALIDATION -- 13 stages, synthetic truth",
          flush=True)
    print("=" * 78, flush=True)
    _check_perfect()
    _check_white()
    _check_bias()
    _check_drift()
    _check_alignment()
    _check_scale()
    _check_quantization()
    _check_fov()
    _check_penumbra()
    _check_albedo()
    _check_shadowing()
    _check_degenerate()
    _check_determinism()
    n_pass = sum(1 for _, _, ok, _ in _VAL_RESULTS if ok)
    n_fail = len(_VAL_RESULTS) - n_pass
    print("-" * 78, flush=True)
    print(f" RESULT: {n_pass} PASS, {n_fail} FAIL out of {len(_VAL_RESULTS)} checks",
          flush=True)
    for stage, name, ok, detail in _VAL_RESULTS:
        if not ok:
            print(f"   FAILED: [{stage}] {name}: {detail}", flush=True)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower().startswith("valid"):
        sys.exit(run_validation())
    run_demo()

#TEST HASH2