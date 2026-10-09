import math
from dataclasses import dataclass

from engine.astrodynamics.orbital_math import orbital_elements
from engine.math.vector3 import Vector3
from engine.validation.validation_types import ErrorSample, PropagationResult, ValidationConfig
from engine.validation.validation_utils import (
    rad_to_deg,
    smallest_angular_difference_rad,
)


TIME_ALIGNMENT_TOLERANCE_SECONDS = 1.0e-9


@dataclass(frozen=True)
class ElementComparison:
    aether: float
    orekit: float
    absolute_error: float
    relative_error_percent: float


@dataclass(frozen=True)
class ComparisonMetrics:
    samples_count: int
    final_position_error_m: float
    final_velocity_error_mps: float
    rms_position_error_m: float
    rms_velocity_error_mps: float
    max_position_error_m: float
    max_position_error_time_s: float
    max_velocity_error_mps: float
    max_velocity_error_time_s: float
    final_energy_error_jkg: float
    final_h_magnitude_error_km2s: float
    semi_major_axis_m: ElementComparison
    eccentricity: ElementComparison
    inclination_deg: ElementComparison
    raan_deg: ElementComparison
    aop_deg: ElementComparison
    ta_deg: ElementComparison
    error_history: list[ErrorSample]


def _norm_diff(a: Vector3, b: Vector3) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    dz = a.z - b.z
    return math.sqrt((dx * dx) + (dy * dy) + (dz * dz))


def _rel_error_percent(delta: float, reference: float) -> float:
    if reference == 0.0:
        return 0.0
    return 100.0 * abs(delta / reference)


def _specific_energy(position: Vector3, velocity: Vector3, mu: float) -> float:
    radius = position.magnitude()
    speed_squared = velocity.magnitude_squared()
    return (speed_squared / 2.0) - (mu / radius)


def _h_magnitude(position: Vector3, velocity: Vector3) -> float:
    return position.cross(velocity).magnitude()


def _scalar_compare(aether_value: float, orekit_value: float) -> ElementComparison:
    delta = aether_value - orekit_value
    return ElementComparison(
        aether=aether_value,
        orekit=orekit_value,
        absolute_error=abs(delta),
        relative_error_percent=_rel_error_percent(delta, orekit_value),
    )


def _angle_compare_deg(aether_angle_rad: float, orekit_angle_rad: float) -> ElementComparison:
    delta_rad = smallest_angular_difference_rad(aether_angle_rad, orekit_angle_rad)
    aether_deg = rad_to_deg(aether_angle_rad)
    orekit_deg = rad_to_deg(orekit_angle_rad)
    delta_deg = abs(rad_to_deg(delta_rad))
    return ElementComparison(
        aether=aether_deg,
        orekit=orekit_deg,
        absolute_error=delta_deg,
        relative_error_percent=_rel_error_percent(delta_deg, orekit_deg),
    )


def _validate_datasets(
    aether_result: PropagationResult,
    orekit_result: PropagationResult,
) -> None:
    aether_count = len(aether_result.samples)
    orekit_count = len(orekit_result.samples)

    if aether_count == 0:
        raise ValueError(
            f"{aether_result.propagator_name} produced no samples; "
            "cannot compute comparison metrics."
        )

    if orekit_count == 0:
        raise ValueError(
            f"{orekit_result.propagator_name} produced no samples; "
            "cannot compute comparison metrics."
        )

    if aether_count != orekit_count:
        raise ValueError(
            "Sample count mismatch between propagators: "
            f"{aether_result.propagator_name} has {aether_count} samples, "
            f"{orekit_result.propagator_name} has {orekit_count} samples."
        )

    for index in range(aether_count):
        aether_time = aether_result.samples[index].time_seconds
        orekit_time = orekit_result.samples[index].time_seconds
        if abs(aether_time - orekit_time) > TIME_ALIGNMENT_TOLERANCE_SECONDS:
            raise ValueError(
                "Propagation time mismatch between propagators at index "
                f"{index}: {aether_result.propagator_name} time={aether_time:.15f} s, "
                f"{orekit_result.propagator_name} time={orekit_time:.15f} s, "
                f"delta={abs(aether_time - orekit_time):.15e} s exceeds tolerance "
                f"{TIME_ALIGNMENT_TOLERANCE_SECONDS:.1e} s."
            )


def compute_metrics(
    config: ValidationConfig,
    aether_result: PropagationResult,
    orekit_result: PropagationResult,
) -> ComparisonMetrics:
    _validate_datasets(aether_result, orekit_result)
    samples_count = len(aether_result.samples)

    pos_sq_accum = 0.0
    vel_sq_accum = 0.0

    max_position_error_m = -1.0
    max_position_error_time_s = 0.0
    max_velocity_error_mps = -1.0
    max_velocity_error_time_s = 0.0

    history: list[ErrorSample] = []

    for index in range(samples_count):
        aether_sample = aether_result.samples[index]
        orekit_sample = orekit_result.samples[index]

        pos_error = _norm_diff(aether_sample.position_m, orekit_sample.position_m)
        vel_error = _norm_diff(aether_sample.velocity_mps, orekit_sample.velocity_mps)

        pos_sq_accum += pos_error * pos_error
        vel_sq_accum += vel_error * vel_error

        history.append(
            ErrorSample(
                time_seconds=aether_sample.time_seconds,
                position_error_m=pos_error,
                velocity_error_mps=vel_error,
            )
        )

        if pos_error > max_position_error_m:
            max_position_error_m = pos_error
            max_position_error_time_s = aether_sample.time_seconds

        if vel_error > max_velocity_error_mps:
            max_velocity_error_mps = vel_error
            max_velocity_error_time_s = aether_sample.time_seconds

    rms_position_error_m = math.sqrt(pos_sq_accum / samples_count)
    rms_velocity_error_mps = math.sqrt(vel_sq_accum / samples_count)

    aether_final = aether_result.samples[samples_count - 1]
    orekit_final = orekit_result.samples[samples_count - 1]

    final_position_error_m = _norm_diff(aether_final.position_m, orekit_final.position_m)
    final_velocity_error_mps = _norm_diff(aether_final.velocity_mps, orekit_final.velocity_mps)

    aether_elements = orbital_elements(
        aether_final.position_m,
        aether_final.velocity_mps,
        config.mu,
    )
    orekit_elements = orbital_elements(
        orekit_final.position_m,
        orekit_final.velocity_mps,
        config.mu,
    )

    aether_energy = _specific_energy(aether_final.position_m, aether_final.velocity_mps, config.mu)
    orekit_energy = _specific_energy(orekit_final.position_m, orekit_final.velocity_mps, config.mu)
    final_energy_error_jkg = abs(aether_energy - orekit_energy)

    aether_h_mag = _h_magnitude(aether_final.position_m, aether_final.velocity_mps)
    orekit_h_mag = _h_magnitude(orekit_final.position_m, orekit_final.velocity_mps)
    final_h_magnitude_error_km2s = abs(aether_h_mag - orekit_h_mag) / 1.0e6

    return ComparisonMetrics(
        samples_count=samples_count,
        final_position_error_m=final_position_error_m,
        final_velocity_error_mps=final_velocity_error_mps,
        rms_position_error_m=rms_position_error_m,
        rms_velocity_error_mps=rms_velocity_error_mps,
        max_position_error_m=max_position_error_m,
        max_position_error_time_s=max_position_error_time_s,
        max_velocity_error_mps=max_velocity_error_mps,
        max_velocity_error_time_s=max_velocity_error_time_s,
        final_energy_error_jkg=final_energy_error_jkg,
        final_h_magnitude_error_km2s=final_h_magnitude_error_km2s,
        semi_major_axis_m=_scalar_compare(aether_elements.a, orekit_elements.a),
        eccentricity=_scalar_compare(aether_elements.e, orekit_elements.e),
        inclination_deg=_angle_compare_deg(aether_elements.i, orekit_elements.i),
        raan_deg=_angle_compare_deg(aether_elements.raan, orekit_elements.raan),
        aop_deg=_angle_compare_deg(aether_elements.aop, orekit_elements.aop),
        ta_deg=_angle_compare_deg(aether_elements.ta, orekit_elements.ta),
        error_history=history,
    )


def _print_header(result: PropagationResult) -> None:
    print(f"Propagator: {result.propagator_name}")
    print(f"Frame: {result.frame}")
    print(f"Integrator: {result.integrator}")
    print(f"Integrator Type: {result.integrator_type}")
    print(f"Fixed Step: {result.fixed_step_seconds:.3f} s")
    print(f"Gravity Model: {result.gravity_model}")
    print(f"Gravity Provider: {result.gravity_provider}")
    print(f"Gravity Degree: {result.gravity_degree}")
    print(f"Gravity Order: {result.gravity_order}")
    print(f"Coefficient Convention: {result.coefficient_convention}")
    print(f"Epoch (UTC): {result.epoch_utc.isoformat()}")
    print(f"Time Scale: {result.time_scale}")
    print(f"Number of Samples: {len(result.samples)}")


def print_report(
    config: ValidationConfig,
    aether_result: PropagationResult,
    orekit_result: PropagationResult,
    metrics: ComparisonMetrics,
) -> None:
    print("------------------------------------------------")
    print("AETHER / OREKIT CROSS-VALIDATION REPORT")
    print("------------------------------------------------")
    print("MODEL DOCUMENTATION")
    print("AETHER: Closed-form Cartesian J2/J3/J4 equations")
    print("Orekit: Holmes-Featherstone spherical harmonics, degree 4, order 0")
    print(
        "These are mathematically equivalent physical models implemented "
        "through different numerical formulations."
    )
    print("------------------------------------------------")
    print("TIME VALIDATION")
    print(f"Epoch: {config.epoch_utc.isoformat()}")
    print(f"Time Scale: {config.time_scale}")
    print(f"Duration: {config.duration_seconds:.1f} s")
    print(f"Step Size: {config.time_step_seconds:.1f} s")
    print(f"Propagation Steps: {metrics.samples_count}")
    print("------------------------------------------------")
    print("AETHER METADATA")
    _print_header(aether_result)
    print("------------------------------------------------")
    print("OREKIT METADATA")
    _print_header(orekit_result)
    print("------------------------------------------------")
    print("FRAME VALIDATION")
    print(f"AETHER Frame: {aether_result.frame}")
    print(f"Orekit Frame: {orekit_result.frame}")
    if aether_result.frame != orekit_result.frame:
        print("WARNING: Frame labels differ. Verify frame alignment assumptions.")
    else:
        print("Frame labels match.")
    print("------------------------------------------------")
    print("RMS DEFINITIONS")
    print(
        "RMS Position Error = sqrt(mean(||r_aether - r_orekit||^2)) over all "
        "samples at 30 s interval."
    )
    print(
        "RMS Velocity Error = sqrt(mean(||v_aether - v_orekit||^2)) over all "
        "samples at 30 s interval."
    )
    print("------------------------------------------------")
    print("FINAL STATE VECTOR ERRORS")
    print(f"Position Error (m): {metrics.final_position_error_m:.6f}")
    print(f"Velocity Error (m/s): {metrics.final_velocity_error_mps:.9f}")
    print(f"RMS Position Error (m): {metrics.rms_position_error_m:.6f}")
    print(f"RMS Velocity Error (m/s): {metrics.rms_velocity_error_mps:.9f}")
    print("MAX ERRORS OVER 24h")
    print(
        f"Max Position Error (m): {metrics.max_position_error_m:.6f} "
        f"at t = {metrics.max_position_error_time_s:.1f} s"
    )
    print(
        f"Max Velocity Error (m/s): {metrics.max_velocity_error_mps:.9f} "
        f"at t = {metrics.max_velocity_error_time_s:.1f} s"
    )
    print("------------------------------------------------")
    print("ORBITAL ELEMENT COMPARISON AT 24h")
    print("Quantity               AETHER               Orekit             Abs Error        Rel Error %")
    print(
        f"Semi-major axis (m)    {metrics.semi_major_axis_m.aether:18.6f} "
        f"{metrics.semi_major_axis_m.orekit:18.6f} "
        f"{metrics.semi_major_axis_m.absolute_error:14.6f} "
        f"{metrics.semi_major_axis_m.relative_error_percent:12.6f}"
    )
    print(
        f"Eccentricity           {metrics.eccentricity.aether:18.12f} "
        f"{metrics.eccentricity.orekit:18.12f} "
        f"{metrics.eccentricity.absolute_error:14.12f} "
        f"{metrics.eccentricity.relative_error_percent:12.6f}"
    )
    print(
        f"Inclination (deg)      {metrics.inclination_deg.aether:18.9f} "
        f"{metrics.inclination_deg.orekit:18.9f} "
        f"{metrics.inclination_deg.absolute_error:14.9f} "
        f"{metrics.inclination_deg.relative_error_percent:12.6f}"
    )
    print(
        f"RAAN (deg)             {metrics.raan_deg.aether:18.9f} "
        f"{metrics.raan_deg.orekit:18.9f} "
        f"{metrics.raan_deg.absolute_error:14.9f} "
        f"{metrics.raan_deg.relative_error_percent:12.6f}"
    )
    print(
        f"AOP (deg)              {metrics.aop_deg.aether:18.9f} "
        f"{metrics.aop_deg.orekit:18.9f} "
        f"{metrics.aop_deg.absolute_error:14.9f} "
        f"{metrics.aop_deg.relative_error_percent:12.6f}"
    )
    print(
        f"True Anomaly (deg)     {metrics.ta_deg.aether:18.9f} "
        f"{metrics.ta_deg.orekit:18.9f} "
        f"{metrics.ta_deg.absolute_error:14.9f} "
        f"{metrics.ta_deg.relative_error_percent:12.6f}"
    )
    print("------------------------------------------------")
    print("CONSERVATION INVARIANT COMPARISON (Final State)")
    print(f"Two-body Specific Orbital Energy Error (J/kg): {metrics.final_energy_error_jkg:.9f}")
    print(
        "Two-body Angular Momentum Magnitude Error (km^2/s): "
        f"{metrics.final_h_magnitude_error_km2s:.9f}"
    )
    print("------------------------------------------------")
    print("STATUS: MEASUREMENT ONLY")
    print(
        "Scientifically justified acceptance tolerances are not locked yet, "
        "so this report intentionally provides measurements without PASS/FAIL."
    )
    print("------------------------------------------------")
    print("VALIDATION NOTES")
    print("Small differences can appear without either implementation being wrong due to:")
    print("- floating point arithmetic")
    print("- coefficient normalization")
    print("- frame transformations")
    print("- interpolation")
    print("- implementation details")
    print("------------------------------------------------")
    print("NOTE: Full error history (position/velocity vs time) is stored in metrics.error_history for future plotting.")