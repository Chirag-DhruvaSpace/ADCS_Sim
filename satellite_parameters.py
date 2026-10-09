"""Runtime parameter types and YAML loader for the ADCS engine.

Values marked as assumptions must be replaced with measured, CAD, or supplier
values before flight-quality analysis. Keeping them in satellite_parameters.yaml makes every such
assumption visible and prevents the engine and ADCS code from using different
spacecraft definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SpacecraftParameters:
    name: str
    mass_kg: float
    body_radius_m: float
    inertia_kg_m2: tuple[float, float, float]
    drag_reference_area_m2: float
    drag_coefficient: float
    srp_reference_area_m2: float
    srp_reflectivity_coefficient: float
    panels_deployed: bool
    mtr_max_dipole_Am2: float
    mtr_dipole_step_Am2: float
    mtr_max_current_A: tuple[float, float, float]
    wheel_max_torque_Nm: float
    wheel_max_momentum_Nms: float
    inertia_tensor_kg_m2: tuple = ()
    configuration: str = 'deployed'
    model_url: str = '/assets/models/P-30XL.glb'

    def __post_init__(self) -> None:
        if self.mass_kg <= 0.0 or self.body_radius_m <= 0.0:
            raise ValueError("spacecraft mass and radius must be positive")
        if len(self.inertia_kg_m2) != 3 or any(x <= 0.0 for x in self.inertia_kg_m2):
            raise ValueError("principal inertias must be three positive values")
        for value in (
            self.drag_reference_area_m2,
            self.srp_reference_area_m2,
            self.drag_coefficient,
            self.srp_reflectivity_coefficient,
            self.mtr_max_dipole_Am2,
            self.mtr_dipole_step_Am2,
            self.wheel_max_torque_Nm,
            self.wheel_max_momentum_Nms,
        ):
            if value <= 0.0:
                raise ValueError("spacecraft physical limits and areas must be positive")

    @property
    def inertia_matrix(self) -> np.ndarray:
        if self.inertia_tensor_kg_m2:
            tensor = np.asarray(self.inertia_tensor_kg_m2, dtype=float)
            if tensor.shape != (3, 3) or not np.allclose(tensor, tensor.T) or np.any(np.linalg.eigvalsh(tensor) <= 0):
                raise ValueError('inertia tensor must be symmetric positive definite')
            return tensor
        return np.diag(self.inertia_kg_m2)


@dataclass(frozen=True)
class OrbitParameters:
    epoch_utc: datetime
    altitude_m: float
    inclination_deg: float
    eccentricity: float = 0.0
    raan_deg: float = 0.0
    argument_of_perigee_deg: float = 0.0
    true_anomaly_deg: float = 0.0

    def __post_init__(self) -> None:
        if self.epoch_utc.tzinfo is None:
            raise ValueError("orbit epoch must be timezone-aware")
        if self.altitude_m <= 0.0:
            raise ValueError("orbit altitude must be positive")
        if not 0.0 <= self.eccentricity < 1.0:
            raise ValueError("eccentricity must be in [0, 1)")
        if not 0.0 <= self.inclination_deg <= 180.0:
            raise ValueError("inclination must be between 0 and 180 degrees")


@dataclass(frozen=True)
class AttitudeParameters:
    initial_quaternion_scalar_first: tuple[float, float, float, float]
    initial_body_rates_deg_s: tuple[float, float, float]
    inertia_is_principal_axes: bool = True


@dataclass(frozen=True)
class ModelDataParameters:
    orekit_data_path: Path
    magnetic_model: str = "WMM"
    space_weather_file_pattern: str = r"SpaceWeather.*\.txt"
    gravity_degree: int = 36
    gravity_order: int = 36


@dataclass(frozen=True)
class ControlParameters:
    detumble_on_rate_deg_s: float
    detumble_off_rate_deg_s: float
    sun_pointing_rate_cap_deg_s: float
    control_loop_period_s: float
    mtr_max_dipole_Am2: float
    mtr_dipole_step_Am2: float
    sun_pointing_base_rate_deg_s: float = 0.2
    pointing_natural_frequency_rad_s: float = 0.05
    pointing_damping_ratio: float = 1.0
    manual_rw_natural_frequency_rad_s: float = 0.018
    manual_rw_damping_ratio: float = 1.0
    magnetic_pd_natural_frequency_rad_s: float = 0.1
    magnetic_pd_damping_ratio: float = 1.5
    kinematic_spin_rate_deg_s: float = 1.0
    target_rate_difference_step_s: float = 0.2
    moon_spin_axis: str = 'z'
    moon_spin_rate_deg_s: float = 0.06
    moon_spin_amplitude_deg: float = 12.0
    moon_spin_achieve_threshold_deg: float = 2.0
    sun_sweep_axis: str = 'z'
    sun_sweep_rate_deg_s: float = 0.06
    sun_sweep_amplitude_deg: float = 64.0
    sun_sweep_achieve_threshold_deg: float = 2.0

    def __post_init__(self):
        for axis in (self.moon_spin_axis, self.sun_sweep_axis):
            if axis not in ('y', 'z'):
                raise ValueError('Sweep axes must be y or z')
        for name in ('moon_spin_rate_deg_s', 'moon_spin_amplitude_deg',
                     'sun_sweep_rate_deg_s', 'sun_sweep_amplitude_deg',
                     'pointing_natural_frequency_rad_s', 'pointing_damping_ratio',
                     'manual_rw_natural_frequency_rad_s', 'manual_rw_damping_ratio',
                     'magnetic_pd_natural_frequency_rad_s', 'magnetic_pd_damping_ratio',
                     'target_rate_difference_step_s'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')


@dataclass(frozen=True)
class DisturbanceParameters:
    enabled: bool
    residual_dipole_Am2: tuple[float, float, float]
    drag_density_kg_m3: float
    drag_coefficient: float
    drag_area_m2: float
    center_of_pressure_arm_body_m: tuple[float, float, float]
    gravity_gradient_enabled: bool
    residual_dipole_enabled: bool
    atmospheric_drag_enabled: bool
    srp_enabled: bool = True
    srp_torque_enabled: bool = True
    solar_pressure_at_1au_pa: float = 4.56e-6


@dataclass(frozen=True)
class SurfaceParameters:
    name: str
    area_m2: float
    normal_body: tuple[float, float, float]
    center_of_pressure_body_m: tuple[float, float, float]
    absorptivity: float
    diffuse_reflectivity: float
    specular_reflectivity: float
    tangent_u_body: tuple = ()
    tangent_v_body: tuple = ()
    half_size_m: tuple = ()

    def __post_init__(self):
        if self.area_m2 <= 0 or not np.isclose(np.linalg.norm(self.normal_body), 1):
            raise ValueError(f'{self.name}: positive area and unit normal required')
        optical = (self.absorptivity, self.diffuse_reflectivity, self.specular_reflectivity)
        if any(x < 0 or x > 1 for x in optical) or not np.isclose(sum(optical), 1):
            raise ValueError(f'{self.name}: optical fractions must sum to one')


@dataclass(frozen=True)
class GeometryParameters:
    surfaces: tuple[SurfaceParameters, ...]
    center_of_mass_body_m: tuple[float, float, float]
    blockers: tuple = ()


@dataclass(frozen=True)
class SimulationParameters:
    default_duration_s: float
    telemetry_publish_period_s: float
    realtime: bool
    attitude_integrator_abs_tolerance: float
    attitude_integrator_rel_tolerance: float
    orbit_integrator_min_step_s: float = 0.001
    orbit_integrator_max_step_s: float = 600.0
    orbit_integrator_abs_tolerance: float = 0.001
    orbit_integrator_rel_tolerance: float = 1e-6
    telemetry_url: str = 'http://127.0.0.1:5000/update_telemetry'
    telemetry_timeout_s: float = 0.25
    speed: float = 1.0
    orbit_output_window_s: float = 0.1

    def __post_init__(self):
        for name in ('orbit_output_window_s', 'speed', 'orbit_integrator_min_step_s', 'orbit_integrator_max_step_s',
                     'orbit_integrator_abs_tolerance', 'orbit_integrator_rel_tolerance',
                     'attitude_integrator_abs_tolerance', 'attitude_integrator_rel_tolerance',
                     'telemetry_timeout_s'):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.orbit_integrator_max_step_s < self.orbit_integrator_min_step_s:
            raise ValueError('Orbit maximum step must be >= minimum step')


@dataclass(frozen=True)
class ReactionWheelParameters:
    count: int
    axis_matrix_body: tuple[tuple[float, float, float, float], ...]
    max_torque_Nm: float
    max_momentum_Nms: float
    null_space_desaturation_gain: float
    saturation_reallocation_enabled: bool = True
    max_reallocation_passes: int = 4


@dataclass(frozen=True)
class ViewerParameters:
    earth_day_ambient: float = 0.12
    earth_day_diffuse: float = 0.78
    earth_night_floor: float = 0.015

    def __post_init__(self):
        if any(not np.isfinite(v) or not 0 <= v <= 2 for v in
               (self.earth_day_ambient, self.earth_day_diffuse, self.earth_night_floor)):
            raise ValueError('Earth lighting values must be finite and between 0 and 2')


# ---------------------------------------------------------------------------
# Simulated GPS receiver ("FakeGPS") -- see gps_sim/README.md.
# The satellite's POSITION/VELOCITY KNOWLEDGE comes from this simulated
# receiver (bias + wander + noise + latency + dropouts, like a real chip);
# the orbit TRUTH keeps driving the physics unchanged. Intensity is selected
# with the ONE module-level line at the bottom of this block.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GpsSimParameters:
    """Configuration of the simulated GPS receiver. All sigmas are 1-sigma
    (standard deviation) sizes of each error component; tau fields are the
    wander time constants [s]; units live in the field names."""

    enabled: bool = True                     # master switch (False = no GPS at all)
    update_rate_hz: float = 1.0              # receiver output rate (real chips: 1-10 Hz)

    # --- position/velocity error components (each gated by its enable flag;
    #     a flag gates the SAME component type on both position and velocity) ---
    enable_bias: bool = True                 # constant startup offset
    enable_wander: bool = True               # slowly-drifting error (Gauss-Markov)
    enable_white_noise: bool = True          # fresh jitter on every fix
    enable_steps: bool = True                # sudden jumps when the constellation geometry changes
    enable_latency: bool = True              # fix describes the slightly-past state
    enable_dropout: bool = True              # randomly missing seconds
    enable_clock_error: bool = True          # receiver clock error inside the reported time
    enable_quantization: bool = True         # round lat/lon/alt/vel_enu like a real chip
    enable_status: bool = True               # satellite-count and DOP random walks

    # --- position error sizes [m] ---
    pos_bias_sigma_h_m: float = 0.5          # 1-sigma of the constant horizontal offset (drawn once)
    pos_bias_sigma_v_m: float = 1.0          # 1-sigma of the constant vertical offset (drawn once)
    gm_tau_pos_s: float = 60.0               # wander time constant
    gm_sigma_pos_h_m: float = 1.4            # wander size, horizontal (E and N each)
    gm_sigma_pos_v_m: float = 2.7            # wander size, Up (real GPS is worse vertically)
    white_sigma_pos_h_m: float = 0.5         # fresh jitter per fix, horizontal (E and N each)
    white_sigma_pos_v_m: float = 0.8         # fresh jitter per fix, Up
    step_mean_interval_s: float = 600.0      # mean time between constellation-change jumps

    # --- velocity error sizes [m/s] (independent draws from position) ---
    vel_bias_sigma_m_s: float = 0.01         # 1-sigma of the constant velocity offset
    gm_tau_vel_s: float = 10.0               # velocity wander time constant
    gm_sigma_vel_m_s: float = 0.03           # velocity wander size (per axis)
    white_sigma_vel_m_s: float = 0.01        # fresh velocity jitter per fix (per axis)

    # --- latency: the fix describes where you WERE ~0.08 s ago ---
    latency_mean_s: float = 0.08             # mean latency (clipped into [min, max])
    latency_sigma_s: float = 0.02            # spread of the latency draw
    latency_min_s: float = 0.04              # hard floor
    latency_max_s: float = 0.20              # hard ceiling

    # --- receiver clock error [s] (nanoseconds -- like a real receiver) ---
    clock_bias_sigma_s: float = 50e-9        # 1-sigma of the constant clock offset
    clock_wander_tau_s: float = 100.0        # clock wander time constant
    clock_wander_sigma_s: float = 20e-9      # clock wander size
    clock_white_sigma_s: float = 10e-9       # fresh clock jitter per fix

    # --- availability ---
    p_dropout: float = 0.005                 # probability a given second is dropped
    cold_start_s: float = 0.0                # "time to first fix" after power-on [s]
    outages_s: tuple[tuple[float, float], ...] = ()   # scheduled (start_s, end_s) blackouts

    # --- status random walks ---
    num_sv_start: int = 8                    # satellites used, start value
    num_sv_min: int = 5                      # a 3D fix needs >= 4; walk clamps here
    num_sv_max: int = 12
    pdop_start: float = 2.0                  # geometry-quality figure, start value
    pdop_step_sigma: float = 0.1             # per-fix random-walk step
    pdop_min: float = 1.2
    pdop_max: float = 4.0

    seed: int = 42                           # RNG seed (all randomness flows from this)

    def __post_init__(self) -> None:
        if self.update_rate_hz <= 0.0:
            raise ValueError("gps update_rate_hz must be positive")
        for name in (
            "pos_bias_sigma_h_m", "pos_bias_sigma_v_m",
            "gm_sigma_pos_h_m", "gm_sigma_pos_v_m",
            "white_sigma_pos_h_m", "white_sigma_pos_v_m",
            "vel_bias_sigma_m_s", "gm_sigma_vel_m_s", "white_sigma_vel_m_s",
            "clock_bias_sigma_s", "clock_wander_sigma_s", "clock_white_sigma_s",
            "latency_sigma_s", "pdop_step_sigma",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"gps {name} must be >= 0")
        for name in ("gm_tau_pos_s", "gm_tau_vel_s", "clock_wander_tau_s", "step_mean_interval_s"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"gps {name} must be > 0")
        if self.latency_min_s > self.latency_max_s:
            raise ValueError("gps latency_min_s must be <= latency_max_s")
        if self.pdop_min > self.pdop_max:
            raise ValueError("gps pdop_min must be <= pdop_max")
        if self.num_sv_min < 4:
            raise ValueError("gps num_sv_min must be >= 4 (a 3D fix needs 4 satellites)")
        if self.num_sv_min > self.num_sv_max:
            raise ValueError("gps num_sv_min must be <= num_sv_max")
        if not 0.0 <= self.p_dropout <= 1.0:
            raise ValueError("gps p_dropout must be in [0, 1]")
        if self.cold_start_s < 0.0:
            raise ValueError("gps cold_start_s must be >= 0")
        for window in self.outages_s:
            if len(window) != 2 or window[0] > window[1]:
                raise ValueError("gps outages_s entries must be (start_s, end_s) with start <= end")
        if not isinstance(self.seed, (int, np.integer)):
            raise ValueError("gps seed must be an int")

    # --- intensity presets (NA) ---
    @classmethod
    def off(cls) -> "GpsSimParameters":
        """No GPS at all -- the simulation behaves exactly as before GPS."""
        return cls(enabled=False)

    @classmethod
    def perfect(cls) -> "GpsSimParameters":
        """GPS on, ZERO error -- useful to check the plumbing alone."""
        return cls(enable_bias=False, enable_wander=False, enable_white_noise=False,
                   enable_steps=False, enable_latency=False, enable_dropout=False,
                   enable_clock_error=False, enable_quantization=False,
                   enable_status=False)

    @classmethod
    def nominal(cls) -> "GpsSimParameters":
        """THE REALISTIC SETTING -- all defaults above (a good LEO GPS fix)."""
        return cls()

    @classmethod
    def degraded(cls) -> "GpsSimParameters":
        """Poor geometry / partial sky view: all position/velocity sigmas
        x2.5, more dropouts, faster steps, worse clock, bigger latency."""
        return cls(
            pos_bias_sigma_h_m=1.25, pos_bias_sigma_v_m=2.5,
            gm_sigma_pos_h_m=3.5, gm_sigma_pos_v_m=6.75,
            white_sigma_pos_h_m=1.25, white_sigma_pos_v_m=2.0,
            step_mean_interval_s=300.0,
            vel_bias_sigma_m_s=0.025, gm_sigma_vel_m_s=0.075, white_sigma_vel_m_s=0.025,
            latency_mean_s=0.12, latency_sigma_s=0.04, latency_min_s=0.05, latency_max_s=0.30,
            clock_bias_sigma_s=2.5e-6, clock_wander_sigma_s=1.0e-6, clock_white_sigma_s=5.0e-7,
            p_dropout=0.05, pdop_max=6.0,
        )

    @classmethod
    def stress(cls) -> "GpsSimParameters":
        """Worst case: sigmas x5, 15% dropouts, 30 s cold start, huge clock
        error, very stale fixes. For robustness testing only."""
        return cls(
            pos_bias_sigma_h_m=2.5, pos_bias_sigma_v_m=5.0,
            gm_sigma_pos_h_m=7.0, gm_sigma_pos_v_m=13.5,
            white_sigma_pos_h_m=2.5, white_sigma_pos_v_m=4.0,
            step_mean_interval_s=200.0,
            vel_bias_sigma_m_s=0.05, gm_sigma_vel_m_s=0.15, white_sigma_vel_m_s=0.05,
            latency_mean_s=0.30, latency_sigma_s=0.10, latency_min_s=0.10, latency_max_s=0.60,
            clock_bias_sigma_s=2.5e-5, clock_wander_sigma_s=1.0e-5, clock_white_sigma_s=5.0e-6,
            p_dropout=0.15, cold_start_s=30.0, pdop_max=8.0,
        )




# ---------------------------------------------------------------------------
# Simulated COARSE SUN SENSOR (CSS) ARRAY -- see simulatesunsensor.py.
# Six photocells on the hull, each reporting sunlight as a fraction of full
# scale (0..1) with a cosine response and a field-of-view cutoff; the flight
# computer reconstructs the body-frame sun direction by least squares over
# the active cells. Errors modelled per cell: mounting misalignment, bias,
# thermal drift, scale, cubic nonlinearity, white noise, ADC quantization;
# array-level physics: eclipse penumbra, Earth albedo, self-shadowing,
# dropouts and latency. All sigmas are fractions of full scale unless the
# name says otherwise; degrees where the name says deg.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SunSensorCellParameters:
    name: str
    normal_body: tuple[float, float, float]      # facing direction (normalized on use)
    position_body_m: tuple[float, float, float] = (0.0, 0.0, 0.0)  # shadow ray test only
    fov_half_angle_deg: float = 90.0
    alignment_error_sigma_deg: float = 0.1       # as-mounted normal error (drawn once)
    bias_sigma: float = 0.005                    # fraction of full scale, drawn once
    drift_sigma: float = 0.002                   # Gauss-Markov wander (thermal proxy)
    drift_tau_s: float = 200.0                   # its time constant [s]
    scale_error_sigma: float = 0.005             # gain error (drawn once)
    nonlinearity_k3_sigma: float = 0.01          # cubic response coefficient (drawn once)
    white_noise_sigma: float = 0.003             # fresh noise per sample
    adc_bits: int = 12                           # digitizer depth (all cells share it)


@dataclass(frozen=True)
class ShadowBlockerParameters:
    """One axis-aligned box (body frame) that blocks the direct sun term of
    any cell whose ray to the sun passes through it."""
    name: str
    center_body_m: tuple[float, float, float]
    half_extents_m: tuple[float, float, float]


def _default_sun_cells() -> tuple:
    """The six reference cells: one per cube face (+/-X, +/-Y, +/-Z).

    Positions sit on the hull faces ~0.25 m from the center, normals point
    straight out of each face (the same axes the 3D satellite model is
    built around, so +X cell looks out the +X face, etc.). With a 90 degree
    half-angle, three faces see a generic direction before thresholding and
    shadowing. This is NOT true at 60 degrees. Output is cosine incidence,
    not the percentage of the sky covered by the array. (ASSUMPTION: the offset only matters for the
    self-shadowing ray test -- direction parallax at 1 AU from a 0.25 m
    arm is ~1e-11 rad)."""
    p = 0.25
    return (
        SunSensorCellParameters("+X", (1.0, 0.0, 0.0), (p, 0.0, 0.0)),
        SunSensorCellParameters("-X", (-1.0, 0.0, 0.0), (-p, 0.0, 0.0)),
        SunSensorCellParameters("+Y", (0.0, 1.0, 0.0), (0.0, p, 0.0)),
        SunSensorCellParameters("-Y", (0.0, -1.0, 0.0), (0.0, -p, 0.0)),
        SunSensorCellParameters("+Z", (0.0, 0.0, 1.0), (0.0, 0.0, p)),
        SunSensorCellParameters("-Z", (0.0, 0.0, -1.0), (0.0, 0.0, -p)),
    )


def _default_sun_blockers() -> tuple:
    """One bus box 0.3 x 0.3 x 0.3 m centered at the origin (matches the
    existing bus-area assumption). Add solar-panel plates the same way, e.g.
        ShadowBlockerParameters("panel+Y", (0.0, 0.45, 0.0), (0.30, 0.02, 0.10))
    """
    return (ShadowBlockerParameters("bus-box", (0.0, 0.0, 0.0), (0.15, 0.15, 0.15)),)


@dataclass(frozen=True)
class SunSensorArrayParameters:
    """Configuration of the simulated coarse-sun-sensor ARRAY (error channels
    documented in simulatesunsensor.py). A 0 sigma disables that per-cell
    effect; the enable_* flags toggle whole channels."""

    enabled: bool = True                     # master switch
    seed: int = 42                           # RNG seed (all randomness flows from this)
    update_rate_hz: float = 10.0             # == ADCS loop rate (0.1 s)
    cells: tuple = field(default_factory=_default_sun_cells)
    blockers: tuple = field(default_factory=_default_sun_blockers)  # bus/panel boxes block the sun

    # --- error-channel switches (True = realistic; False = channel off) ---
    enable_alignment_error: bool = True
    enable_bias_drift: bool = True
    enable_scale_nonlinearity: bool = True
    enable_white_noise: bool = True
    enable_saturation: bool = True
    enable_quantization: bool = True
    enable_albedo: bool = True
    enable_penumbra: bool = True
    enable_self_shadowing: bool = True

    # --- reconstruction + array-level knobs ---
    albedo_scale: float = 0.15               # uniform Lambertian Earth reflectivity [0,1]
    activation_threshold: float = 0.015      # 1.5% full scale; 5x nominal white-noise sigma
    min_cells_for_solution: int = 3          # flight computer refuses below this
    dropout_probability: float = 0.0         # per-sample chance the whole receipt is lost
    latency_mean_s: float = 0.01             # measurement staleness (~10 ms)
    latency_sigma_s: float = 0.002
    latency_min_s: float = 0.002
    latency_max_s: float = 0.05

    def __post_init__(self) -> None:
        if len(self.cells) < 3:
            raise ValueError("sun array needs at least 3 cells")
        if self.update_rate_hz <= 0.0:
            raise ValueError("sun update_rate_hz must be positive")
        if self.min_cells_for_solution < 3:
            raise ValueError("min_cells_for_solution must be >= 3 (rank needs 3 normals)")
        if not 0.0 <= self.dropout_probability <= 1.0:
            raise ValueError("sun dropout_probability must be in [0, 1]")
        if self.latency_min_s > self.latency_max_s:
            raise ValueError("sun latency_min_s must be <= latency_max_s")
        if self.albedo_scale < 0.0 or self.activation_threshold < 0.0:
            raise ValueError("sun albedo_scale / activation_threshold must be >= 0")
        if not np.isfinite(self.albedo_scale) or self.albedo_scale > 1.0:
            raise ValueError('Lambertian Earth reflectivity must be in [0,1]')
        if not isinstance(self.seed, (int, np.integer)):
            raise ValueError("sun seed must be an int")
        bits = None
        for c in self.cells:
            if float(np.linalg.norm(c.normal_body)) < 1e-9:
                raise ValueError(f"sun cell {c.name}: normal_body must be nonzero")
            if not 0.0 < c.fov_half_angle_deg <= 90.0:
                raise ValueError(f"sun cell {c.name}: fov_half_angle_deg must be in (0, 90]")
            if not isinstance(c.adc_bits, int) or not 2 <= c.adc_bits <= 16:
                raise ValueError(f"sun cell {c.name}: adc_bits must be an int in [2, 16]")
            if bits is None:
                bits = c.adc_bits
            elif c.adc_bits != bits:
                raise ValueError("all sun cells must share one adc_bits depth")
        for b in self.blockers:
            if any(h <= 0.0 for h in b.half_extents_m):
                raise ValueError(f"sun blocker {b.name}: half_extents must be positive")
        # CAD-mounted sensors can be covered by folded panels. A cell inside
        # an occluder is valid hardware and reports self-shadowing, rather
        # than preventing the stowed configuration from loading.

    # --- intensity presets (exact numbers; these are what the user picks) ---
    @classmethod
    def off(cls) -> "SunSensorArrayParameters":
        """Array absent (the IMU master switch usually handles this)."""
        return cls(enabled=False)

    @classmethod
    def perfect(cls) -> "SunSensorArrayParameters":
        """Array on, ZERO error -- geometry/penumbra still physical."""
        return cls(cells=tuple(replace(c, alignment_error_sigma_deg=0.0,
                                       bias_sigma=0.0, drift_sigma=0.0,
                                       scale_error_sigma=0.0,
                                       nonlinearity_k3_sigma=0.0,
                                       white_noise_sigma=0.0)
                               for c in _default_sun_cells()),
                   enable_alignment_error=False, enable_bias_drift=False,
                   enable_scale_nonlinearity=False, enable_white_noise=False,
                   enable_quantization=False, enable_albedo=False,
                   enable_self_shadowing=False, dropout_probability=0.0,
                   latency_mean_s=0.0, latency_sigma_s=0.0,
                   latency_min_s=0.0, latency_max_s=0.0)

    @classmethod
    def nominal(cls) -> "SunSensorArrayParameters":
        """THE REALISTIC SETTING -- all defaults above."""
        return cls()

    @classmethod
    def degraded(cls) -> "SunSensorArrayParameters":
        """~2.5x the sigmas, 2% receipt dropouts, laggier electronics."""
        return cls(cells=tuple(replace(c, alignment_error_sigma_deg=0.25,
                                       bias_sigma=0.0125, drift_sigma=0.005,
                                       scale_error_sigma=0.0125,
                                       nonlinearity_k3_sigma=0.025,
                                       white_noise_sigma=0.0075)
                               for c in _default_sun_cells()),
                   dropout_probability=0.02,
                   latency_mean_s=0.025, latency_sigma_s=0.005,
                   latency_min_s=0.005, latency_max_s=0.12)

    @classmethod
    def stress(cls) -> "SunSensorArrayParameters":
        """~5x the sigmas, 15% dropouts, coarse 8-bit ADC, 5 Hz sampling."""
        return cls(cells=tuple(replace(c, alignment_error_sigma_deg=0.5,
                                       bias_sigma=0.025, drift_sigma=0.01,
                                       drift_tau_s=100.0,
                                       scale_error_sigma=0.025,
                                       nonlinearity_k3_sigma=0.05,
                                       white_noise_sigma=0.015,
                                       adc_bits=8)
                               for c in _default_sun_cells()),
                   update_rate_hz=5.0, dropout_probability=0.15,
                   latency_mean_s=0.04, latency_sigma_s=0.015,
                   latency_min_s=0.01, latency_max_s=0.20)


# ---------------------------------------------------------------------------
# Simulated IMU (gyroscope + magnetometer) -- see simulateimu_README.md.
# The flight software's ATTITUDE-RATE and BODY-MAGNETIC-FIELD knowledge comes
# from this simulated IMU (scale/misalignment + bias + wander + white noise +
# hard-iron + disturbance + latency + dropouts, like a real chip). The orbit
# and attitude TRUTH keeps driving the physics unchanged. Intensity is
# selected with the ONE module-level line at the bottom of this block.
#
# UNITS: the repo's live simulation works in radians/second for body rate and
# TESLA for the magnetic field (B_eci from engine_adcs_bridge is Tesla), so
# those are the units used here. The real hardware datasheets quote deg/s and
# nT -- the numbers below include a human-readable note in those units.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VectorSensorParameters:
    """One optional gyro/magnetometer. Empty unit lists retain the default chip.

    overrides contains (parameter_name, value) pairs, using the gyro_* or
    mag_* fields below: exact rate, noise, bias, latency, range, response matrix,
    etc. Unspecified values inherit IMU_SIM. Calibration is onboard knowledge
    applied to the receipt, never the simulator's random error realization.
    """
    name: str
    enabled: bool = True
    position_body_m: tuple | None = None
    mount_quaternion: tuple | None = None
    seed: int | None = None
    overrides: tuple = ()
    fusion_weight: float = 1.0
    calibration_matrix: tuple = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    calibration_bias: tuple = (0., 0., 0.)  # body-frame rad/s or Tesla

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise ValueError('Each sensor needs a nonempty name')
        if not np.isfinite(self.fusion_weight) or self.fusion_weight <= 0:
            raise ValueError('fusion_weight must be positive')
        for value, shape in ((self.calibration_matrix, (3, 3)), (self.calibration_bias, (3,))):
            a = np.asarray(value, float)
            if a.shape != shape or not np.all(np.isfinite(a)):
                raise ValueError('Sensor calibration must have finite matrix/vector entries')
        if abs(np.linalg.det(self.calibration_matrix)) < 1e-12:
            raise ValueError('Calibration matrix must be invertible')
        for value, size in ((self.position_body_m, 3), (self.mount_quaternion, 4)):
            if value is not None and (np.asarray(value).shape != (size,) or not np.all(np.isfinite(value))):
                raise ValueError('Mount coordinates/quaternion must be finite')
        if self.mount_quaternion is not None and np.linalg.norm(self.mount_quaternion) < 1e-12:
            raise ValueError('Mount quaternion cannot be zero')


@dataclass(frozen=True)
class ImuSimParameters:
    """Configuration of the simulated IMU (gyroscope + magnetometer).

    All sigmas are 1-sigma (standard deviation) sizes; tau fields are wander
    time constants [s]; units live in the field names (rad/s and Tesla, the
    repo's live conventions). A 0 value disables that error effect.
    """

    enabled: bool = True                     # master switch (False = no IMU at all)
    seed: int = 42                           # RNG seed (all randomness flows from this)

    # Flight-software switches: all live in this single configuration object.
    enable_attitude_estimator: bool = True
    enable_gyro_update: bool = True
    enable_magnetometer_update: bool = True
    enable_sun_update: bool = True
    estimator_innovation_gate_chi2: float = 16.27  # 99.9% gate for 3-vector updates
    estimator_max_bias_rad_s: float = 0.005
    estimator_initial_attitude_sigma_deg: float = 20.0
    estimator_initial_bias_sigma_rad_s: float = 0.002
    # Empty = inherited single unit, so no additional configuration is needed.
    # Nonempty = exactly the listed units; disabled units produce no receipts.
    gyros: tuple = ()
    magnetometers: tuple = ()
    fusion_max_age_s: float = 0.5
    fusion_max_time_skew_s: float = 0.02

    initial_estimate_quaternion: tuple = (1.0, 0.0, 0.0, 0.0)
    estimator_mag_sigma_deg: float = 0.86     # model + measurement direction uncertainty
    estimator_sun_sigma_deg: float = 1.43    # includes coarse-sensor reconstruction error
    gyro_position_body_m: tuple = (0.0, 0.0, 0.0)
    mag_position_body_m: tuple = (0.0, 0.0, 0.20)
    gyro_mount_quaternion: tuple = (1.0, 0.0, 0.0, 0.0)
    mag_mount_quaternion: tuple = (1.0, 0.0, 0.0, 0.0)
    # Local linear magnetic field gradient: rows field axes, columns position.
    mag_gradient_body_t_per_m: tuple = ((0.0, 0.0, 0.0),) * 3

    # --- gyroscope (body angular rate, rad/s, order [X, Y, Z]) ---
    enable_gyro: bool = True                 # gyro present?
    gyro_update_rate_hz: float = 10.0        # == ADCS loop rate (0.1 s). This simulation's
                                             # main loop is the clock -- it cannot sample
                                             # faster than the loop ticks (see README).
    gyro_white_noise_sigma_rad_s: float = 0.00052   # fresh noise (0.03 deg/s, ADIS16545-like)
    gyro_bias_sigma_rad_s: float = 0.00035          # startup bias draw once (0.02 deg/s)
    gyro_wander_sigma_rad_s: float = 0.00020        # slowly-drifting bias (0.011 deg/s)
    gyro_wander_tau_s: float = 100.0                # wander memory [s]
    gyro_scale_error: float = 0.001          # per-axis scale error (relative; 0.1%)
    gyro_misalignment_rad: float = 0.001     # cross-axis coupling (0.057 deg)
    gyro_range_rad_s: float = 4.36           # +/-250 deg/s measurement range
    gyro_dropout_probability: float = 0.0    # per-sample probability the gyro says nothing
    gyro_latency_mean_s: float = 0.005       # measurement staleness (~5 ms, chips are fast)
    gyro_latency_sigma_s: float = 0.001
    gyro_latency_min_s: float = 0.001
    gyro_latency_max_s: float = 0.02
    gyro_quantization_rad_s: float = 0.0     # ADC step size (0 = no quantization)
    gyro_response_matrix: tuple = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    gyro_fixed_bias_rad_s: tuple = (0., 0., 0.)  # exact chip-frame bias, additive to random bias

    # --- magnetometer (body magnetic field, TESLA, order [X, Y, Z]) ---
    enable_magnetometer: bool = True         # magnetometer present?
    mag_update_rate_hz: float = 10.0         # == ADCS loop rate (see gyro note)
    mag_white_noise_sigma_t: float = 80.0e-9      # fresh noise (80 nT, ICM20948-like)
    mag_hard_iron_bias_sigma_t: float = 150.0e-9  # fixed hard-iron offset (150 nT)
    mag_scale_error: float = 0.005           # per-axis scale error (0.5%)
    mag_misalignment_rad: float = 0.002      # cross-axis coupling (0.11 deg)
    mag_disturbance_t: tuple[float, float, float] = (100.0e-9, -50.0e-9, 25.0e-9)
                                              # fixed spacecraft-generated field (body frame, T)
    mag_disturbance_wander_sigma_t: float = 20.0e-9   # slow variation of the spacecraft field
    mag_disturbance_wander_tau_s: float = 200.0       # its time constant [s]
    mag_range_t: float = 1.0e-3               # +/-1000 uT measurement range
    mag_dropout_probability: float = 0.0     # per-sample probability the magnetometer says nothing
    mag_latency_mean_s: float = 0.01         # measurement staleness (~10 ms)
    mag_latency_sigma_s: float = 0.002
    mag_latency_min_s: float = 0.002
    mag_latency_max_s: float = 0.05
    mag_quantization_t: float = 0.0          # ADC step size (0 = no quantization)
    mag_response_matrix: tuple = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
    mag_fixed_bias_t: tuple = (0., 0., 0.)

    # --- coarse sun sensor ARRAY (second reference for the attitude estimator).
    # The whole sensor lives in the nested SunSensorArrayParameters below
    # (simulatesunsensor.py): six photocells with the full per-cell error
    # pipeline plus eclipse penumbra / Earth albedo / self-shadowing. A
    # magnetometer alone can only see 2 of the 3 rotation axes (the rotation
    # AROUND the magnetic field line is unobservable); the array's
    # reconstructed body-frame sun direction is the second reference.
    enable_sun_sensor: bool = True           # sun sensor array present?
    sun_array: SunSensorArrayParameters = field(
        default_factory=SunSensorArrayParameters.nominal)

    # --- WHO STEERS THE SATELLITE (the "does the ADCS actually listen to the
    # IMU?" switches). True = the attitude controllers use the simulated
    # sensor's noisy reading, exactly like real flight software. False = they
    # silently fall back to perfect truth (useful to A/B test the sensor's
    # effect on the satellite's motion). ---
    use_gyro_for_control: bool = True        # controllers damp the MEASURED rate
    use_mag_for_control: bool = True         # magnetic laws use the MEASURED field
    render_estimated_attitude: bool = True   # 3D model oriented from the ESTIMATED
                                             # attitude (the satellite's own belief),
                                             # not perfect truth -- sensor noise shows
                                             # as jitter in the model. False = truth.
    use_attitude_estimate_for_control: bool = True
                                             # controllers compute their pointing
                                             # error against the ESTIMATED attitude
                                             # (the full sensor belief); False =
                                             # true attitude (A/B test the estimator)

    def __post_init__(self) -> None:
        for group in (self.gyros, self.magnetometers):
            if any(not isinstance(u, VectorSensorParameters) for u in group):
                raise ValueError('Sensor groups must contain VectorSensorParameters')
        names = [u.name for u in self.sensor_units('gyro') + self.sensor_units('mag')]
        if len(names) != len(set(names)) or set(names) & {c.name for c in self.sun_array.cells}:
            raise ValueError('Sensor names must be unique across the IMU')
        for name in ('fusion_max_age_s', 'fusion_max_time_skew_s', 'estimator_max_bias_rad_s',
                     'estimator_initial_attitude_sigma_deg', 'estimator_initial_bias_sigma_rad_s'):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        for name in ('gyro_response_matrix', 'mag_response_matrix'):
            a = np.asarray(getattr(self, name), float)
            if a.shape != (3, 3) or not np.all(np.isfinite(a)):
                raise ValueError(f'{name} must be a finite 3x3 matrix')
        for name in ('gyro_fixed_bias_rad_s', 'mag_fixed_bias_t'):
            a = np.asarray(getattr(self, name), float)
            if a.shape != (3,) or not np.all(np.isfinite(a)):
                raise ValueError(f'{name} must be a finite 3-vector')
        for name in ("gyro_white_noise_sigma_rad_s", "gyro_bias_sigma_rad_s",
                     "gyro_wander_sigma_rad_s", "gyro_range_rad_s",
                     "mag_white_noise_sigma_t", "mag_hard_iron_bias_sigma_t",
                     "mag_range_t", "mag_disturbance_wander_sigma_t"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"imu {name} must be >= 0")
        for name in ('gyro_position_body_m', 'mag_position_body_m'):
            value = np.asarray(getattr(self, name), float)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f'{name} must be a finite body-frame 3-vector')
        for name in ('gyro_mount_quaternion', 'mag_mount_quaternion', 'initial_estimate_quaternion'):
            value = np.asarray(getattr(self, name), float)
            if value.shape != (4,) or not np.all(np.isfinite(value)) or np.linalg.norm(value) < 1e-12:
                raise ValueError(f'{name} must be a finite nonzero scalar-first quaternion')
        gradient = np.asarray(self.mag_gradient_body_t_per_m, float)
        if gradient.shape != (3, 3) or not np.all(np.isfinite(gradient)):
            raise ValueError('mag_gradient_body_t_per_m must be a finite 3x3 matrix')
        for name in ('estimator_mag_sigma_deg', 'estimator_sun_sigma_deg'):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not np.isfinite(self.estimator_innovation_gate_chi2) or self.estimator_innovation_gate_chi2 <= 0:
            raise ValueError('estimator_innovation_gate_chi2 must be finite and positive')
        for name in ("gyro_wander_tau_s", "mag_disturbance_wander_tau_s"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"imu {name} must be > 0")
        if self.gyro_update_rate_hz <= 0.0 or self.mag_update_rate_hz <= 0.0:
            raise ValueError("imu update rates must be positive")
        if self.gyro_latency_min_s > self.gyro_latency_max_s:
            raise ValueError("imu gyro_latency_min_s must be <= gyro_latency_max_s")
        if self.mag_latency_min_s > self.mag_latency_max_s:
            raise ValueError("imu mag_latency_min_s must be <= mag_latency_max_s")
        if not 0.0 <= self.gyro_dropout_probability <= 1.0:
            raise ValueError("imu gyro_dropout_probability must be in [0, 1]")
        if not 0.0 <= self.mag_dropout_probability <= 1.0:
            raise ValueError("imu mag_dropout_probability must be in [0, 1]")
        if len(self.mag_disturbance_t) != 3:
            raise ValueError("imu mag_disturbance_t must be a 3-vector (X, Y, Z)")
        if not isinstance(self.seed, (int, np.integer)):
            raise ValueError("imu seed must be an int")

    # --- intensity presets (exact numbers; these are what the user picks) ---
    def sensor_units(self, kind):
        group = self.gyros if kind == 'gyro' else self.magnetometers
        name = 'Gyroscope' if kind == 'gyro' else 'Magnetometer'
        return group or (VectorSensorParameters(name),)

    def unit_config(self, kind, unit, index=0):
        from dataclasses import fields
        allowed = {f.name for f in fields(self) if f.name.startswith(kind + '_')}
        overrides = dict(unit.overrides)
        if set(overrides) - allowed:
            raise ValueError(f'Unsupported {kind} overrides: {set(overrides) - allowed}')
        overrides[kind + '_position_body_m'] = (unit.position_body_m if unit.position_body_m is not None
                                               else getattr(self, kind + '_position_body_m'))
        overrides[kind + '_mount_quaternion'] = (unit.mount_quaternion if unit.mount_quaternion is not None
                                                else getattr(self, kind + '_mount_quaternion'))
        return replace(self, **overrides, gyros=(), magnetometers=(), enable_sun_sensor=False,
                       seed=unit.seed if unit.seed is not None else self.seed + index*1009 + (0 if kind == 'gyro' else 100003),
                       enable_gyro=kind == 'gyro', enable_magnetometer=kind == 'mag')

    @classmethod
    def off(cls) -> "ImuSimParameters":
        """No IMU at all -- the flight software keeps using perfect truth."""
        return cls(enabled=False)

    @classmethod
    def perfect(cls) -> "ImuSimParameters":
        """IMU on, ZERO error -- useful to check the plumbing alone."""
        return cls(enable_gyro=True, enable_magnetometer=True,
                   enable_sun_sensor=True,
                   gyro_white_noise_sigma_rad_s=0.0, gyro_bias_sigma_rad_s=0.0,
                   gyro_wander_sigma_rad_s=0.0, gyro_scale_error=0.0,
                   gyro_misalignment_rad=0.0, gyro_dropout_probability=0.0,
                   gyro_quantization_rad_s=0.0,
                   mag_white_noise_sigma_t=0.0, mag_hard_iron_bias_sigma_t=0.0,
                   mag_scale_error=0.0, mag_misalignment_rad=0.0,
                   mag_disturbance_t=(0.0, 0.0, 0.0),
                   mag_disturbance_wander_sigma_t=0.0,
                   mag_dropout_probability=0.0, mag_quantization_t=0.0,
                   sun_array=SunSensorArrayParameters.perfect())

    @classmethod
    def nominal(cls) -> "ImuSimParameters":
        """THE REALISTIC SETTING -- all defaults above (good MEMS IMU)."""
        return cls()

    @classmethod
    def degraded(cls) -> "ImuSimParameters":
        """Noticeably worse but still plausible: 2x noise/bias/wander,
        0.5% scale, stronger misalignment, bigger disturbance, 2% dropouts,
        slower/laggier sampling."""
        return cls(
            gyro_white_noise_sigma_rad_s=0.00104,   # 0.06 deg/s
            gyro_bias_sigma_rad_s=0.00070,          # 0.04 deg/s
            gyro_wander_sigma_rad_s=0.00040,
            gyro_scale_error=0.005, gyro_misalignment_rad=0.003,
            gyro_dropout_probability=0.02,
            gyro_latency_mean_s=0.02, gyro_latency_sigma_s=0.005,
            gyro_latency_min_s=0.005, gyro_latency_max_s=0.06,
            mag_white_noise_sigma_t=180.0e-9,
            mag_hard_iron_bias_sigma_t=350.0e-9,
            mag_scale_error=0.01, mag_misalignment_rad=0.005,
            mag_disturbance_t=(250.0e-9, -120.0e-9, 60.0e-9),
            mag_disturbance_wander_sigma_t=60.0e-9,
            mag_dropout_probability=0.02,
            mag_latency_mean_s=0.03, mag_latency_sigma_s=0.008,
            mag_latency_min_s=0.008, mag_latency_max_s=0.10,
            sun_array=SunSensorArrayParameters.degraded(),
        )

    @classmethod
    def stress(cls) -> "ImuSimParameters":
        """Very poor sensor conditions useful for robustness testing (still
        physically plausible for a broken/lightly-calibrated IMU): 10x noise,
        1% scale, visible misalignment, 8% dropouts, slow wander."""
        return cls(
            gyro_white_noise_sigma_rad_s=0.0052,    # 0.3 deg/s
            gyro_bias_sigma_rad_s=0.0035,           # 0.2 deg/s
            gyro_wander_sigma_rad_s=0.0020,
            gyro_scale_error=0.01, gyro_misalignment_rad=0.01,
            gyro_dropout_probability=0.08,
            gyro_latency_mean_s=0.05, gyro_latency_sigma_s=0.02,
            gyro_latency_min_s=0.01, gyro_latency_max_s=0.15,
            mag_white_noise_sigma_t=1.0e-6,
            mag_hard_iron_bias_sigma_t=2.0e-6,
            mag_scale_error=0.02, mag_misalignment_rad=0.02,
            mag_disturbance_t=(500.0e-9, -250.0e-9, 125.0e-9),
            mag_disturbance_wander_sigma_t=150.0e-9,
            mag_dropout_probability=0.08,
            mag_latency_mean_s=0.08, mag_latency_sigma_s=0.03,
            mag_latency_min_s=0.02, mag_latency_max_s=0.25,
            sun_array=SunSensorArrayParameters.stress(),
        )



def apply_imu_mount_defaults(cfg, defaults):
    """Apply viewer-saved mounting literals without changing sensor physics."""
    for name, values in defaults.items():
        position = tuple(values['position'])
        group = next((key for key in ('gyros', 'magnetometers')
                      if any(u.name == name for u in getattr(cfg, key))), None)
        if group:
            cfg = replace(cfg, **{group: tuple(replace(u, position_body_m=position)
                if u.name == name else u for u in getattr(cfg, group))})
        elif name in ('Gyroscope', 'Magnetometer'):
            key = 'gyro_position_body_m' if name == 'Gyroscope' else 'mag_position_body_m'
            cfg = replace(cfg, **{key: position})
        elif any(c.name == name for c in cfg.sun_array.cells):
            cfg = replace(cfg, sun_array=replace(cfg.sun_array, cells=tuple(
                replace(c, position_body_m=position, normal_body=tuple(values['normal']),
                        fov_half_angle_deg=values['fov']) if c.name == name else c
                for c in cfg.sun_array.cells)))
        else:
            raise ValueError(f'Saved mounting refers to unknown sensor: {name}')
    return cfg

# satellite_parameters.yaml is the sole persisted configuration. The classes above
# provide validation and the API used by existing simulation code.
def _tuple_values(value):
    if isinstance(value, list):
        return tuple(_tuple_values(item) for item in value)
    return value


def _from_yaml(cls, values):
    from dataclasses import fields
    allowed = {item.name for item in fields(cls)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} settings: {sorted(unknown)}")
    return cls(**{key: _tuple_values(value) for key, value in values.items()})


def _apply_sensor_profile(cfg, profile):
    from dataclasses import fields
    if profile == 'custom':
        return cfg
    if profile not in ('off', 'perfect', 'nominal', 'degraded', 'stress'):
        raise ValueError(f'Unknown sensor profile: {profile}')
    cls = type(cfg)
    preset, nominal = getattr(cls, profile)(), cls.nominal()
    candidates = [getattr(cls, name)() for name in ('off', 'perfect', 'degraded', 'stress')]
    error_fields = {f.name for f in fields(cls)
                    if f.name not in ('sun_array', 'cells', 'blockers')
                    and any(getattr(other, f.name) != getattr(nominal, f.name) for other in candidates)}
    changes = {name: getattr(preset, name) for name in error_fields}
    if isinstance(cfg, SunSensorArrayParameters):
        base, target = nominal.cells[0], preset.cells[0]
        error_fields = {f.name for f in fields(base)
                        if f.name not in ('name', 'normal_body', 'position_body_m', 'fov_half_angle_deg')}
        changes['cells'] = tuple(replace(c, **{name: getattr(target, name) for name in error_fields})
                                 for c in cfg.cells)
    return replace(cfg, **changes)


def validate_pointing_configuration(values):
    if not isinstance(values, dict) or set(values) != {'strategy', 'legacy_mode', 'custom'}:
        raise ValueError('pointing requires strategy, legacy_mode and custom')
    if values['strategy'] not in ('legacy', 'custom', 'firmware_sitl'):
        raise ValueError('pointing.strategy must be legacy, custom or firmware_sitl')
    if values['legacy_mode'] not in ('SUN_POINTING', 'RW', 'MOON', 'NADIR', 'SUN_SWEEP',
                                     'SUN_POINTING_RW', 'NOMINAL_IN_ORBIT', 'KINEMATIC_ROBUSTNESS'):
        raise ValueError('Invalid pointing.legacy_mode')
    if values['strategy'] == 'custom':
        custom = values['custom']
        if not isinstance(custom, dict) or custom.get('input') not in ('desired_quaternion', 'quaternion_error'):
            raise ValueError('custom.input must be desired_quaternion or quaternion_error')
        keys = ['quaternion'] + (['reference_quaternion'] if custom['input'] == 'quaternion_error' else [])
        for key in keys:
            q = np.asarray(custom.get(key), dtype=float)
            if q.shape != (4,) or not np.all(np.isfinite(q)) or np.max(np.abs(q)) < 1e-12:
                raise ValueError(f'custom.{key} must be a finite nonzero quaternion')


def _load_configuration(source=None, *, panels_deployed=None, use_advanced_satellite_model=None):
    import yaml
    source = Path(source) if source is not None else Path(__file__).resolve().with_suffix('.yaml')
    with source.open(encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {source}")
    expected = {'spacecraft', 'orbit', 'attitude', 'model_data', 'control',
                'disturbances', 'geometry', 'reaction_wheels', 'simulation',
                'gps_sim', 'imu_sim', 'imu_mount_defaults', 'viewer', 'use_advanced_satellite_model', 'pointing', 'sensor_profiles'}
    if set(data) != expected:
        raise ValueError(f"YAML sections differ from expected: {sorted(set(data) ^ expected)}")
    profiles = data['sensor_profiles']
    if not isinstance(profiles, dict) or set(profiles) != {'gps', 'imu', 'gyroscope', 'magnetometer', 'sun_array'}:
        raise ValueError('sensor_profiles must specify gps, imu, gyroscope, magnetometer, sun_array')
    if any(value not in ('custom', 'off', 'perfect', 'nominal', 'degraded', 'stress') for value in profiles.values()):
        raise ValueError('Unknown sensor profile')
    validate_pointing_configuration(data['pointing'])
    def section(name, cls):
        values = data[name]
        if not isinstance(values, dict):
            raise ValueError(f"{name} must be a YAML mapping")
        return _from_yaml(cls, values)
    spacecraft_data = dict(data['spacecraft'])
    advanced = data['use_advanced_satellite_model'] if use_advanced_satellite_model is None else use_advanced_satellite_model
    if not isinstance(advanced, bool):
        raise ValueError('use_advanced_satellite_model must be true or false')
    selected = {}
    if advanced:
        advanced_path = source.parent / 'advanced_satellite_parameters.yaml'
        with advanced_path.open(encoding='utf-8') as handle:
            advanced_data = yaml.safe_load(handle)
        deployed = advanced_data['panels_deployed'] if panels_deployed is None else panels_deployed
        if not isinstance(deployed, bool):
            raise ValueError('advanced panels_deployed must be true or false')
        spacecraft_data['panels_deployed'] = deployed
        mode = 'deployed' if deployed else 'stowed'
        selected = advanced_data['configurations'][mode]
        data['attitude'] = {**data['attitude'], 'inertia_is_principal_axes': False}
    if panels_deployed is not None:
        spacecraft_data['panels_deployed'] = bool(panels_deployed)
    mode = 'deployed' if spacecraft_data['panels_deployed'] else 'stowed'
    spacecraft_data.update(selected.get('spacecraft', {}))
    spacecraft_data['configuration'] = mode if advanced else 'legacy'
    spacecraft = _from_yaml(SpacecraftParameters, spacecraft_data)
    # Physical limits have one editable source; control/allocation inherit them.
    for key in ('mtr_max_dipole_Am2', 'mtr_dipole_step_Am2'):
        data['control'][key] = getattr(spacecraft, key)
    data['reaction_wheels']['max_torque_Nm'] = spacecraft.wheel_max_torque_Nm
    data['reaction_wheels']['max_momentum_Nms'] = spacecraft.wheel_max_momentum_Nms
    data['disturbances']['drag_coefficient'] = spacecraft.drag_coefficient
    # Force validation of the full tensor on load.
    spacecraft.inertia_matrix
    orbit_data = dict(data['orbit'])
    epoch = orbit_data['epoch_utc']
    orbit_data['epoch_utc'] = datetime.fromisoformat(epoch.replace('Z', '+00:00')) if isinstance(epoch, str) else epoch
    orbit = _from_yaml(OrbitParameters, orbit_data)
    model_data = dict(data['model_data'])
    model_data['orekit_data_path'] = (source.parent / model_data['orekit_data_path']).resolve()
    geometry_data = dict(selected.get('geometry', data['geometry']))
    geometry_data['surfaces'] = tuple(_from_yaml(SurfaceParameters, item) for item in geometry_data['surfaces'])
    geometry_data['blockers'] = tuple(_from_yaml(ShadowBlockerParameters, item) for item in geometry_data.get('blockers', []))
    geometry = _from_yaml(GeometryParameters, geometry_data)
    imu_data = dict(data['imu_sim'])
    sun_data = dict(imu_data['sun_array'])
    base_cells = {c['name']: c for c in sun_data['cells']}
    sun_data.update(selected.get('sun_array', {}))
    if advanced:
        sun_data['blockers'] = geometry_data['blockers']
    sun_data['cells'] = [{**base_cells.get(c['name'], {}), **c} for c in sun_data['cells']]
    sun_data['cells'] = tuple(_from_yaml(SunSensorCellParameters, item) for item in sun_data['cells'])
    sun_data['blockers'] = tuple(item if isinstance(item, ShadowBlockerParameters) else
                                 _from_yaml(ShadowBlockerParameters, item) for item in sun_data['blockers'])
    imu_data['sun_array'] = _from_yaml(SunSensorArrayParameters, sun_data)
    for group in ('gyros', 'magnetometers'):
        imu_data[group] = tuple(_from_yaml(VectorSensorParameters, item) for item in imu_data[group])
    imu_data.update(selected.get('sensor_mounts', {}))
    imu = _apply_sensor_profile(_from_yaml(ImuSimParameters, imu_data), data['sensor_profiles']['imu'])
    for key, prefix, flag in (('gyroscope', 'gyro_', 'enable_gyro'), ('magnetometer', 'mag_', 'enable_magnetometer')):
        profile = profiles[key]
        if profile != 'custom':
            selected_profile = _apply_sensor_profile(imu, profile)
            from dataclasses import fields
            changes = {f.name: getattr(selected_profile, f.name) for f in fields(imu)
                       if f.name.startswith(prefix) and 'position_body' not in f.name and 'mount_quaternion' not in f.name}
            changes[flag] = profile != 'off'
            imu = replace(imu, **changes)
    imu = replace(imu, sun_array=_apply_sensor_profile(imu.sun_array, profiles['sun_array']))
    mounts = data['imu_mount_defaults'] or {}
    if not isinstance(mounts, dict):
        raise ValueError('imu_mount_defaults must be a mapping')
    wheels = _from_yaml(ReactionWheelParameters, {**data['reaction_wheels'], **selected.get('reaction_wheels', {})})
    return (spacecraft, orbit, section('attitude', AttitudeParameters),
            _from_yaml(ModelDataParameters, model_data), section('control', ControlParameters),
            section('disturbances', DisturbanceParameters), geometry,
            wheels,
            section('simulation', SimulationParameters), _apply_sensor_profile(section('gps_sim', GpsSimParameters), data['sensor_profiles']['gps']),
            apply_imu_mount_defaults(imu, mounts), mounts)


(SPACECRAFT, ORBIT, ATTITUDE, MODEL_DATA, CONTROL, DISTURBANCES, GEOMETRY,
 REACTION_WHEELS, SIMULATION, GPS_SIM, IMU_SIM, IMU_MOUNT_DEFAULTS) = _load_configuration()

def _load_viewer_parameters():
    import yaml
    with Path(__file__).with_suffix('.yaml').open(encoding='utf-8') as handle:
        return _from_yaml(ViewerParameters, yaml.safe_load(handle)['viewer'])

VIEWER = _load_viewer_parameters()


#solar panel deployment, movement of intertia, initial angular velocity, max dipole movement
# Compatibility constants for modules that still use the old flat parameter API.
MASS_KG = SPACECRAFT.mass_kg
BODY_RADIUS_M = SPACECRAFT.body_radius_m
DRAG_AREA_M2 = SPACECRAFT.drag_reference_area_m2
DRAG_COEFFICIENT = SPACECRAFT.drag_coefficient
SRP_AREA_M2 = SPACECRAFT.srp_reference_area_m2
SRP_CR = SPACECRAFT.srp_reflectivity_coefficient
ALTITUDE_M = ORBIT.altitude_m
INCLINATION_DEG = ORBIT.inclination_deg
EPOCH_UTC = ORBIT.epoch_utc
IXX, IYY, IZZ = SPACECRAFT.inertia_kg_m2
MTR_MAX_DIPOLE_AM2 = SPACECRAFT.mtr_max_dipole_Am2
MTR_DIPOLE_STEP_AM2 = SPACECRAFT.mtr_dipole_step_Am2
WHEEL_MAX_TORQUE_NM = SPACECRAFT.wheel_max_torque_Nm
WHEEL_MAX_MOMENTUM_NMS = SPACECRAFT.wheel_max_momentum_Nms


def initial_body_rates_rad_s() -> np.ndarray:
    return np.radians(ATTITUDE.initial_body_rates_deg_s)


def validate() -> None:
    """Validate configuration and expose accidental non-finite values early."""
    values = np.array([
        MASS_KG, BODY_RADIUS_M, DRAG_AREA_M2, DRAG_COEFFICIENT,
        SRP_AREA_M2, SRP_CR, ALTITUDE_M, INCLINATION_DEG,
        IXX, IYY, IZZ, MTR_MAX_DIPOLE_AM2, MTR_DIPOLE_STEP_AM2,
        WHEEL_MAX_TORQUE_NM, WHEEL_MAX_MOMENTUM_NMS,
    ])
    if not np.all(np.isfinite(values)):
        raise ValueError("satellite parameter configuration contains non-finite values")
    if not MODEL_DATA.orekit_data_path.exists():
        raise FileNotFoundError(f"Orekit data directory not found: {MODEL_DATA.orekit_data_path}")


validate()



def _load_pointing():
    import yaml
    with Path(__file__).with_suffix('.yaml').open(encoding='utf-8') as handle:
        return yaml.safe_load(handle)['pointing']
POINTING = _load_pointing()
