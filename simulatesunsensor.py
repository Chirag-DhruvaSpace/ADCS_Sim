"""simulatesunsensor.py -- the simulated COARSE SUN SENSOR (CSS) ARRAY.

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
    python simulatesunsensor.py             # demo: per-cell table + reconstruction
    python simulatesunsensor.py validate    # staged proof (13 stages)

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
    i = np.arange(patches)
    axis = r / np.linalg.norm(r)
    cap = radius / np.linalg.norm(r)
    z = cap + (1-cap) * (i + 0.5) / patches
    phi = i * (np.pi * (3 - np.sqrt(5)))
    rho = np.sqrt(1-z*z)
    helper = np.array([0., 0., 1.]) if abs(axis[2]) < .9 else np.array([1., 0., 0.])
    e1 = np.cross(helper, axis); e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    n = rho[:, None]*np.cos(phi)[:, None]*e1 + rho[:, None]*np.sin(phi)[:, None]*e2 + z[:, None]*axis
    ray = n * radius - r
    distance = np.linalg.norm(ray, axis=1)
    ray /= distance[:, None]
    illumination = np.maximum(0., n @ sun_eci)
    emission = np.maximum(0., np.sum(n * -ray, axis=1))
    weights = reflectivity * (2 * radius**2 * (1-cap) / patches) * illumination * emission / distance**2
    incidence = normals @ body_to_eci.T @ ray.T
    response = np.where((incidence >= fov_cos[:, None]) & (incidence > 0), incidence, 0.)
    return response @ weights


def _dcm_bi_from_q(q):
    """Attitude matrix dcm body->ECI (v_eci = C_bi @ v_body) from a
    scalar-first [q0, q1, q2, q3] quaternion -- copied EXACTLY from
    satellite_rotational_dynamics_var_mag_field.py (same formula as the
    copies in simulateimu.py / calculate_disturbances.py). The repo's
    load-bearing convention for body-frame vectors is:
        B_body = C_bi.T @ B_eci
    using this same matrix. Do NOT "fix" this formula -- it IS the repo.
    """
    q = np.asarray(q, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2 * (q2**2 + q3**2),     2 * (q1 * q2 + q0 * q3),     2 * (q1 * q3 - q0 * q2)],
        [2 * (q1 * q2 - q0 * q3),     1 - 2 * (q1**2 + q3**2),     2 * (q2 * q3 + q0 * q1)],
        [2 * (q1 * q3 + q0 * q2),     2 * (q2 * q3 - q0 * q1),     1 - 2 * (q1**2 + q2**2)],
    ])


def white_noise(rng, sigma: float) -> float:
    """One fresh, memoryless random draw of size `sigma` (zero on average).
    Same helper as simulateimu.py / simulategps.py (house pattern)."""
    if sigma < 0.0:
        raise ValueError("white-noise sigma must be >= 0")
    return sigma * rng.standard_normal()


class GaussMarkov:
    """One axis of a slowly-wandering error (wants: sigma >= 0, tau > 0).

    Advance rule (exact for a discrete step of any size):
        b_new = exp(-dt/tau) * b + sqrt(1 - exp(-2*dt/tau)) * sigma * N(0,1)
    With dt = 0 the state is left unchanged, so the very first call is safe.
    (Same small class as simulateimu.py's GaussMarkov, kept self-contained so
    this file stands alone like the other sensor modules do.)
    """

    __slots__ = ("sigma", "tau", "_value")

    def __init__(self, sigma: float, tau: float, initial: float = 0.0) -> None:
        if sigma < 0.0:
            raise ValueError("GaussMarkov sigma must be >= 0")
        if tau <= 0.0:
            raise ValueError("GaussMarkov tau must be > 0")
        self.sigma = float(sigma)
        self.tau = float(tau)
        self._value = float(initial)

    @property
    def value(self) -> float:
        return self._value

    def advance(self, dt_seconds: float, rng) -> None:
        dt = float(dt_seconds)
        if dt <= 0.0:
            return
        decay = float(np.exp(-dt / self.tau))
        self._value = (decay * self._value
                       + float(np.sqrt(1.0 - decay * decay)) * self.sigma * rng.standard_normal())

    def reset(self) -> None:
        self._value = 0.0


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
            t1 = (lo[axis] - p[axis]) / d[axis]
            t2 = (hi[axis] - p[axis]) / d[axis]
            if t1 > t2:
                t1, t2 = t2, t1
            t_near = max(t_near, t1)
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


class SimulatedSunSensorArray:
    """The simulated coarse-sun-sensor ARRAY. Feed the TRUE state each loop
    tick with update(t, q_truth, sun_eci_truth, eclipse_fraction, r_eci_truth);
    it answers with a SunArrayMeasurement on its own fixed-rate grid, or None
    when the grid did not tick this update.

    It NEVER touches the simulation truth itself -- truth comes in as
    arguments (the "lying machine" rule).
    """

    def __init__(self, config, record_history=True) -> None:
        cfg = config
        self.cfg = cfg
        # SunSensorArrayParameters.post_init already validated everything
        # (fail loudly at startup); re-check the cheap invariants defensively.
        if len(cfg.cells) < 3:
            raise ValueError("sun sensor array needs at least 3 cells")
        self.rng = np.random.default_rng(cfg.seed)   # ONE generator, all randomness

        cells = list(cfg.cells)
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
            n = np.asarray(c.normal_body, dtype=float).reshape(3)
            n_norm = float(np.linalg.norm(n))
            if n_norm < 1e-9:
                raise ValueError(f"cell {c.name}: normal_body must be nonzero")
            n = n / n_norm
            if not (0.0 < float(c.fov_half_angle_deg) <= 90.0):
                raise ValueError(f"cell {c.name}: fov_half_angle_deg must be in (0, 90]")
            if not isinstance(c.adc_bits, int) or not (2 <= c.adc_bits <= 16):
                raise ValueError(f"cell {c.name}: adc_bits must be an int in [2, 16] "
                                 f"(the validate harness deliberately exercises 4 bits)")
            if int(c.adc_bits) != int(cells[0].adc_bits):
                raise ValueError("all cells must share one adc_bits depth")
            self._n_nominal.append(n)
            self._positions.append(np.asarray(c.position_body_m, dtype=float).reshape(3))
            self._fov_cos.append(float(math.cos(math.radians(c.fov_half_angle_deg))))
            # (a) mounting misalignment: one small rotation vector, applied via
            #     the house trick R = _dcm_bi_from_q([1, 0.5*v]) (then renormalize).
            sig = math.radians(c.alignment_error_sigma_deg) if cfg.enable_alignment_error else 0.0
            v = np.array([white_noise(self.rng, sig) for _ in range(3)])
            R = _dcm_bi_from_q(np.concatenate(([1.0], 0.5 * v)))
            n_eff = R @ n
            self._n_effective.append(n_eff / np.linalg.norm(n_eff))
            # (e) bias + thermal drift
            self._bias0.append(white_noise(self.rng, c.bias_sigma)
                               if cfg.enable_bias_drift else 0.0)
            self._drift.append(GaussMarkov(c.drift_sigma if cfg.enable_bias_drift else 0.0,
                                           c.drift_tau_s))
            # (f) scale + cubic nonlinearity
            self._scale.append(white_noise(self.rng, c.scale_error_sigma)
                               if cfg.enable_scale_nonlinearity else 0.0)
            self._k3.append(white_noise(self.rng, c.nonlinearity_k3_sigma)
                            if cfg.enable_scale_nonlinearity else 0.0)

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
        exactly like simulateimu._sample_truth_at. The eclipse fraction and
        the ECI position change slowly, so they use the BRACKETING nearest
        history value (documented simplification)."""
        times = [h[0] for h in self._history]
        if t_meas_s <= times[0] or len(times) < 2:
            t0, q0, f0, r0 = self._history[0]
            return t0, q0, f0, r0
        j = bisect_right(times, t_meas_s) - 1
        j = min(max(j, 0), len(times) - 2)
        t0, q0, f0, r0 = self._history[j]
        t1, q1, f1, r1 = self._history[j + 1]
        if np.dot(q0, q1) < 0:
            q1 = -q1  # q and -q represent the same attitude; take the short arc
        w = (t_meas_s - t0) / (t1 - t0) if t1 > t0 else 0.0
        q = q0 + w * (q1 - q0)
        q /= np.linalg.norm(q)
        f = f1 if w >= 0.5 else f0          # nearest bracket (changes slowly)
        r = (r1 if w >= 0.5 else r0)        # nearest bracket (changes slowly)
        return (t_meas_s, q, f, r)

    @staticmethod
    def _latency_draw(rng, mean, sigma, lo, hi):
        """One random latency value, clipped into [lo, hi] (fenced dart)."""
        return float(np.clip(rng.normal(mean, sigma), lo, hi))

    # ---- the heartbeat -------------------------------------------------------
    def update(self, t_seconds, q_truth, sun_eci_truth, eclipse_fraction,
               r_eci_truth=None):
        """Feed ONE loop tick of TRUE state. Returns a SunArrayMeasurement on
        the array's own grid, or None when the grid did not tick this update
        (a returned receipt with valid=False is a dropped sample).

        Truth is passed IN: q_truth = scalar-first body->ECI quaternion,
        sun_eci_truth = true unit Sun direction in ECI, eclipse_fraction =
        the engine lighting ratio F in [0,1] (1 = full sun), r_eci_truth =
        true ECI position (needed only for the Earth-albedo term; None
        disables albedo that tick).
        """
        cfg = self.cfg
        t = float(t_seconds)
        q = np.asarray(q_truth, dtype=float).reshape(4)
        sun_eci = np.asarray(sun_eci_truth, dtype=float).reshape(3)
        n = float(np.linalg.norm(sun_eci))
        if n < 1e-12:
            return None
        sun_eci = sun_eci / n
        F = 1.0 if eclipse_fraction is None else float(np.clip(eclipse_fraction, 0.0, 1.0))
        r_eci = None if r_eci_truth is None else np.asarray(r_eci_truth, dtype=float).reshape(3)

        if self._last_t is not None and t <= self._last_t:
            raise ValueError(
                f"SimulatedSunSensorArray.update received t={t} but the previous "
                f"call was t={self._last_t}. Time must move forward.")

        dt = 0.0 if self._last_t is None else t - self._last_t
        self._last_t = t
        self._history.append((t, q.copy(), F, None if r_eci is None else r_eci.copy()))

        # advance the thermal-drift states by this tick's duration (every
        # tick, on-grid or not -- same pattern as the IMU's wander states)
        if cfg.enable_bias_drift:
            for gm in self._drift:
                gm.advance(dt, self.rng)

        # own fixed-rate grid; the slot is consumed even on a dropout so a
        # dropped sample is never retried ("bus on the hour")
        k = math.floor(t * cfg.update_rate_hz + 1e-9)
        if k <= self._last_k:
            return None
        self._last_k = k
        t_grid = k / cfg.update_rate_hz
        self.samples += 1

        # latency: the sample describes the geometry a few ms ago
        tau = self._latency_draw(self.rng, cfg.latency_mean_s, cfg.latency_sigma_s,
                                 cfg.latency_min_s, cfg.latency_max_s)
        t_meas, q_meas, F_meas, r_meas = self._sample_truth_at(t_grid - tau)

        # (a) GEOMETRY: true sun direction in the body frame at t_meas,
        #     using the repo's own convention (B_body = C_bi.T @ B_eci).
        C_bi = _dcm_bi_from_q(q_meas)
        s_body = C_bi.T @ sun_eci
        s_body = s_body / np.linalg.norm(s_body)
        # (d) EARTH ALBEDO inputs (simplified engineering model): unit nadir
        #     in the body frame + the lit fraction of the visible disk.
        if r_meas is not None and cfg.enable_albedo:
            r_hat = np.asarray(r_meas, dtype=float) / np.linalg.norm(r_meas)
            a_body = C_bi.T @ (-r_hat)
            f_illum = float(np.clip(0.5 * (1.0 + float(np.dot(sun_eci, r_hat))), 0.0, 1.0))
        else:
            a_body = None
            f_illum = 0.0

        dots_eff = self._n_effective @ s_body
        dots_nom = self._n_nominal @ s_body
        dots_alb = (self._n_effective @ a_body) if a_body is not None else np.zeros(len(dots_eff))
        albedo_outputs = (earth_albedo_fractions(r_meas, sun_eci, C_bi,
                          self._n_effective, self._fov_cos, cfg.albedo_scale)
                          if a_body is not None else np.zeros(len(dots_eff)))

        # (j) DROPOUT: one per-sample dice for the WHOLE receipt
        valid = not (cfg.dropout_probability > 0.0
                     and self.rng.random() < cfg.dropout_probability)
        if not valid:
            self.dropouts += 1

        cell_samples = []
        outputs = np.zeros(len(self._names))
        used_flags = []
        for i, name in enumerate(self._names):
            in_fov = bool(dots_eff[i] >= self._fov_cos[i] and dots_eff[i] > 0.0)
            # (a) cosine response, zero outside the FOV cone
            x_dir = max(0.0, float(dots_eff[i])) if in_fov else 0.0
            ideal_direct = x_dir
            # (b) PENUMBRA: gradual eclipse scales the direct term
            F_applied = F_meas if cfg.enable_penumbra else float(F_meas > 0.5)
            x = x_dir * F_applied
            # (c) SELF-SHADOWING: ray from the cell position along the sun ray
            shadowed = False
            if cfg.enable_self_shadowing and x > 0.0:
                for blocker in cfg.blockers:
                    if _ray_hits_box(self._positions[i], s_body,
                                     blocker.center_body_m, blocker.half_extents_m):
                        shadowed = True
                        break
            if shadowed:
                x = 0.0
            # (d) EARTH ALBEDO: additive, NOT blocked by the shadow ray.
            # Surface illumination is computed separately from direct eclipse.
            # Reflected light is real signal even when the Sun is outside FOV.
            albedo = 0.0
            if a_body is not None and cfg.enable_albedo:
                albedo = float(albedo_outputs[i])
                x += albedo
            # (e) BIAS + THERMAL DRIFT (gated: a dark cell stays dark when the
            #     channel is off -- no phantom signal with no sun)
            if cfg.enable_bias_drift:
                x += self._bias0[i] + self._drift[i].value
            # (f) SCALE + NONLINEARITY (gated: multiplicative only, so exact
            #     darkness is preserved; both power-on draws are honored only
            #     when the channel switch is on)
            if cfg.enable_scale_nonlinearity:
                x = (1.0 + self._scale[i]) * x + self._k3[i] * x ** 3
            # (g) WHITE NOISE
            if cfg.enable_white_noise:
                x += white_noise(self.rng, cfg.cells[i].white_noise_sigma)
            # (i) SATURATION flag: pre-ADC value above full scale
            pre_adc = x
            saturated = bool(cfg.enable_saturation and pre_adc > 1.0)
            # (h) ADC QUANTIZATION (+ inherent clamp: a photocell cannot read <0 or >1)
            if cfg.enable_quantization:
                counts = int(round(float(np.clip(x, 0.0, 1.0)) * self._full_scale))
                x = counts / self._full_scale
            else:
                x = float(np.clip(x, 0.0, 1.0))
                counts = int(round(x * self._full_scale))
            outputs[i] = x
            used_flags.append(False)
            cell_samples.append(SunCellSample(
                name=name,
                output_fraction=float(x),
                output_pct=100.0 * float(x),
                adc_counts=counts,
                angle_deg=(None if x <= 0.0 else float(np.degrees(np.arccos(np.clip(x, 0.0, 1.0))))),
                used=False,
                in_fov=in_fov,
                shadowed=shadowed,
                saturated=saturated,
                eclipse_factor_applied=float(F_applied),
                albedo_fraction=float(albedo),
            ))

        # (3.3) ONBOARD RECONSTRUCTION -- NOMINAL normals (the as-mounted
        # error is unknown to the spacecraft; that ignorance IS the channel).
        recon, recon_valid, method = self._reconstruct(outputs)
        for i, u in enumerate(self._used_mask):
            cell_samples[i].used = bool(u)
        used_count = int(np.sum(self._used_mask))

        meas = SunArrayMeasurement(
            t_meas_s=t_meas, t_arrival_s=t_grid, cells=cell_samples,
            reconstructed_body=(None if recon is None else recon.copy()),
            reconstruction_valid=bool(recon_valid), method=method, valid=valid)

        # ---- record (receipt + stapled truth) -- VALIDATION ONLY -------------
        self.records.append({
            "t_meas": t_meas, "t_arrival": t_grid, "valid": valid,
            "truth": s_body.copy(),              # true body-frame sun direction
            "ideal_direct": (dots_eff * (dots_eff >= self._fov_cos)).copy(),
            "ideal_direct_nom": (dots_nom * (dots_nom >= self._fov_cos)).copy(),
            "F": float(F_meas), "albedo_f_illum": float(f_illum),
            "meas": (None if recon is None else recon.copy()),
            "reconstruction_valid": bool(recon_valid), "method": method,
            "outputs": outputs.copy(), "used": list(self._used_mask),
            "cells": cell_samples,
        })
        return meas

    def _reconstruct(self, outputs):
        """The flight computer's least-squares solve A s = b over ALL cells
        whose output exceeds the activation threshold. Requires at least
        min_cells_for_solution used cells AND a full-rank A (3 non-coplanar
        normals); normalizes the solution. Returns (unit vector | None,
        valid, method-string)."""
        from imu_navigation import reconstruct_sun
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
