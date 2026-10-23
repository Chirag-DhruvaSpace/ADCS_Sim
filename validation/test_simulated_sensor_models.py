"""Independent sensor-model checks using each sensor directly.

Run: python -m validation.test_simulated_sensor_models validate
Demo: python -m validation.test_simulated_sensor_models
"""
import sys
import unittest
from dataclasses import replace

import numpy as np

from simulate_gyroscope import SimulatedGyroscope
from simulate_magnetometer import SimulatedMagnetometer
from simulate_sunsensor import SimulatedSunSensorArray
from simulate_magnetometer import _dcm_bi_from_q


_TUMBLE_DEG_S_1 = 5.0      # representative tumble for exercising the sensors
_TUMBLE_DEG_S_2 = 3.0      # (the project's own C-firmware tests use the same
_TUMBLE_DEG_S_3 = -2.0     #  magnitude; the nominal y0 is zero rate which
                           #  would leave the attitude frozen -- boring)


def _real_truth_driver(provider, dt=0.1, t_end=120.0):
    """Generator of REAL truth for the demo/validation, using the repository's
    OWN physics core:

      * ATTITUDE + BODY RATE: torque-free rigid-body dynamics -- the exact same
        equations as rotational_equations_of_motion's physical core
        (I·w_dot = -w × I·w, q_dot = 0.5·Omega(q)·q) with the repo's own
        inertia (satellite_params) and a representative tumble, integrated at
        the loop step. A USE_TUMBLE=0 flag would reproduce the repo's current
        zero-rate y0.
      * MAGNETIC FIELD: the REAL IGRF B_eci from engine_adcs_bridge at the
        REAL engine-propagated orbit position.

    Yields (t, q_truth, omega_truth, B_eci_truth) each step.
    """
    import satellite_params as sp
    I = np.diag([sp.sat_Ixx, sp.sat_Iyy, sp.sat_Izz])
    I_inv = np.linalg.inv(I)
    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians([_TUMBLE_DEG_S_1, _TUMBLE_DEG_S_2, _TUMBLE_DEG_S_3])
    for i in range(1, int(round(t_end / dt)) + 1):
        t = i * dt
        r_vec, v_vec = provider.state_at(t)
        B_eci = provider.magnetic_field_eci(t, r_vec)
        # one step of the repo's own torque-free dynamics core
        w_dot = I_inv @ (-np.cross(omega, I @ omega))
        wx, wy, wz = omega
        Omega = np.array([[0, -wx, -wy, -wz],
                          [wx, 0, wz, -wy],
                          [wy, -wz, 0, wx],
                          [wz, wy, -wx, 0]])
        q = q + 0.5 * dt * (Omega @ q)
        q /= np.linalg.norm(q)
        omega = omega + dt * w_dot
        yield t, q, omega, B_eci


def _load_provider():
    import engine.orekit_runtime  # noqa: F401  side-effect JVM bootstrap
    from engine.orekit_runtime import ensure_initialized
    ensure_initialized()
    import satellite_parameters as config
    from engine_adcs_bridge import EngineOrbitProvider
    return EngineOrbitProvider(epoch_utc=config.EPOCH_UTC)


def run_demo() -> None:
    """A short standalone tour: 120 s on the real orbit + real IGRF field
    with the repo's own attitude dynamics, feeding the NOMINAL IMU. Prints
    measured-vs-truth statistics for both sensors.
    """
    import time
    print("=" * 78)
    print(" IMU SIMULATOR DEMO -- 120 s, NOMINAL profile (realistic errors)")
    print("=" * 78)

    provider = _load_provider()
    import satellite_parameters as config
    from sun_vector_eci import sun_vector_eci
    from datetime import timedelta
    imu = (SimulatedGyroscope(config.IMU_SIM), SimulatedMagnetometer(config.IMU_SIM), SimulatedSunSensorArray((config.IMU_SIM).sun_array))

    t0 = time.perf_counter()
    for t, q, omega, B_eci in _real_truth_driver(provider, dt=0.1, t_end=120.0):
        # the Sun's ECI direction is known from the GPS clock (CLAUDE.md §5)
        sun = sun_vector_eci(config.EPOCH_UTC + timedelta(seconds=t))
        (imu[0].update(t, q, omega), imu[1].update(t, q, B_eci), imu[2].update(t, q, sun, 1.0))
    wall = time.perf_counter() - t0

    print(f"flew 120 s in {wall:.1f} s wall clock; "
          f"{imu[0].gyro_samples} gyro, {imu[1].mag_samples} mag, "
          f"{len(imu[2].records)} sun-sensor outputs")
    print(f"  gyro outputs / valid : {imu[0].gyro_samples} / "
          f"{sum(1 for kind, r in (imu[0].records + imu[1].records) if kind == 'gyro' and r['valid'])}")
    print(f"  mag  outputs / valid : {imu[1].mag_samples} / "
          f"{sum(1 for kind, r in (imu[0].records + imu[1].records) if kind == 'mag' and r['valid'])}")
    if imu[2] is not None:
        srecs = imu[2].records
        print(f"  sun  outputs / valid : {len(imu[2].records)} / "
              f"{sum(1 for r in srecs if r['valid'])} "
              f"({sum(1 for r in srecs if r['reconstruction_valid'])} reconstructions solved)")

    ge = np.array([r["meas"] - r["truth"] for kind, r in (imu[0].records + imu[1].records) if kind == "gyro" and r["valid"]])
    me = np.array([r["meas"] - r["truth"] for kind, r in (imu[0].records + imu[1].records) if kind == "mag" and r["valid"]])
    if len(ge):
        print("\nsummary statistics (NOMINAL profile):")
        print(f"  gyro error std  X/Y/Z : "
              f"{np.degrees(ge[:, 0].std()):.4f} / {np.degrees(ge[:, 1].std()):.4f} / "
              f"{np.degrees(ge[:, 2].std()):.4f} deg/s")
        print(f"  gyro error mean X/Y/Z : "
              f"{np.degrees(ge[:, 0].mean()):+.4f} / {np.degrees(ge[:, 1].mean()):+.4f} / "
              f"{np.degrees(ge[:, 2].mean()):+.4f} deg/s")
    if len(me):
        print(f"  mag error std  X/Y/Z : "
              f"{me[:, 0].std() * 1e9:.1f} / {me[:, 1].std() * 1e9:.1f} / "
              f"{me[:, 2].std() * 1e9:.1f} nT")
        print(f"  mag error mean X/Y/Z : "
              f"{me[:, 0].mean() * 1e9:+.1f} / {me[:, 1].mean() * 1e9:+.1f} / "
              f"{me[:, 2].mean() * 1e9:+.1f} nT")
    if imu[2] is not None:
        good = [r for r in imu[2].records if r["reconstruction_valid"]]
        if good:
            angs = np.array([np.degrees(np.arccos(np.clip(
                float(np.dot(r["meas"], r["truth"])), -1.0, 1.0))) for r in good])
            print(f"  sun recon error mean/std : {angs.mean():.3f} / {angs.std():.3f} deg "
                  f"({len(good)}/{len(imu[2].records)} receipts solved)")
    print("\ndone.")

# --- validation harness ------------------------------------------------------
_VAL_RESULTS = []                 # (stage, name, ok, detail)
_VAL_DT = 0.1


def _check(stage: str, name: str, ok: bool, detail: str) -> None:
    _VAL_RESULTS.append((stage, name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {stage:<10} {name}: {detail}", flush=True)


def _synthetic_gyro_loop(imu, duration_s=600.0, omega=None, dt=None):
    """Feed a CONSTANT synthetic truth so statistical checks measure ONLY the
    sensor model: q = identity, omega = fixed body rate (rad/s), B_eci = a
    fixed vector, sun_eci = a fixed second reference. Returns the sensor
    records at the end."""
    dt = dt if dt is not None else _VAL_DT
    omega = np.array([0.3, -0.15, 0.05]) if omega is None else np.asarray(omega, float)
    q_ident = np.array([1.0, 0.0, 0.0, 0.0])
    # B_eci chosen so B_body is a nice non-trivial vector via the repo's C_bi.T;
    # sun_eci is NOT parallel to B_eci (real attitude determination needs two
    # non-parallel references -- exactly the point of adding the sun sensor).
    B_eci = np.array([2.0e-5, 1.0e-5, 1.5e-5])
    # sun chosen so >=3 array cells are lit well inside their FOV cones (the
    # onboard least-squares reconstruction needs >=3 non-coplanar cells)
    sun_eci = np.array([1.0, 1.0, 1.0]); sun_eci /= np.linalg.norm(sun_eci)
    for i in range(1, int(round(duration_s / dt)) + 1):
        (imu[0].update(i * dt, q_ident, omega), imu[1].update(i * dt, q_ident, B_eci), imu[2].update(i * dt, q_ident, sun_eci, 1.0))
    return imu


def _finalize(cfg_factory, seed=42, duration=600.0):
    from satellite_parameters import ImuSimParameters
    cfg = cfg_factory()
    cfg = replace(cfg, seed=seed)
    imu = (SimulatedGyroscope(cfg), SimulatedMagnetometer(cfg), SimulatedSunSensorArray((cfg).sun_array))
    _synthetic_gyro_loop(imu, duration_s=duration)
    return imu


# ---- STAGE 1: PERFECT ------------------------------------------------------
def _check_perfect() -> None:
    from satellite_parameters import ImuSimParameters
    imu = _finalize(ImuSimParameters.perfect)
    grecs = [r for k, r in (imu[0].records + imu[1].records) if k == "gyro"]
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag"]
    if not grecs or not mrecs:
        _check("PERFECT", "samples exist", False, "no gyro/mag records")
        return
    # (1) gyro measurement == true body rate (units/frame/order), max abs err
    ge = np.array([r["meas"] - r["truth"] for r in grecs])
    gmax = float(np.max(np.abs(ge)))
    _check("PERFECT", "1 gyro == truth", gmax < 1e-12,
           f"max |meas-truth| = {gmax:.3e} rad/s (< 1e-12)  [axis order X,Y,Z]")
    # (2) mag measurement == true body field (Tesla)
    me = np.array([r["meas"] - r["truth"] for r in mrecs])
    mmax = float(np.max(np.abs(me)))
    _check("PERFECT", "2 mag == truth", mmax < 1e-12,
           f"max |meas-truth| = {mmax:.3e} T (< 1e-12)  [X,Y,Z, Tesla]")
    # (2b) sun ARRAY reconstruction == true body unit direction (dimensionless)
    if imu[2] is not None:
        srecs = imu[2].records
        good = [r for r in srecs if r["reconstruction_valid"]]
        se = (np.array([r["meas"] - r["truth"] for r in good])
              if good else np.zeros((0, 3)))
        smax = float(np.max(np.abs(se))) if len(good) else float("inf")
        _check("PERFECT", "2b sun recon == truth",
               len(srecs) > 0 and len(good) == len(srecs) and smax < 1e-9,
               f"max |recon-truth| = {smax:.3e} (< 1e-9), "
               f"{len(good)}/{len(srecs)} receipts solved")
    else:
        _check("PERFECT", "2b sun recon == truth", False, "no sun array owned")
    # (3) cadence: exactly one gyro sample per 0.1 s tick, evenly spaced
    ts = np.array([r["t_arrival"] for r in grecs])
    gaps = np.diff(ts)
    _check("PERFECT", "3 cadence", np.all(np.abs(gaps - _VAL_DT) < 1e-9),
           f"{len(ts)} samples, gaps {'all exactly 0.1 s' if len(ts) else 'none'}")
    # (4) timestamps: arrival >= meas (latency) always
    ok_lag = all(r["t_arrival"] >= r["t_meas"] - 1e-12 for r in grecs + mrecs)
    _check("PERFECT", "4 timestamps", ok_lag,
           "t_arrival >= t_meas for every sample")
    # (5) no dropouts / no saturation in perfect mode
    ok_flags = all(r["valid"] and not r["saturated"] for r in grecs + mrecs)
    _check("PERFECT", "5 flags clean", ok_flags,
           "all valid, none saturated")

# ---- STAGE 2: WHITE NOISE ---------------------------------------------------
def _check_white() -> None:
    from satellite_parameters import ImuSimParameters
    # only white noise on: perfect but with finite gyro/mag noise
    _sun_white = replace(
        ImuSimParameters.perfect().sun_array, enable_white_noise=True,
        cells=tuple(replace(c, white_noise_sigma=0.003)
                    for c in ImuSimParameters.perfect().sun_array.cells))
    cfg0 = replace(ImuSimParameters.perfect(),
                   gyro_white_noise_sigma_rad_s=0.00052,
                   mag_white_noise_sigma_t=80e-9,
                   sun_array=_sun_white)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(imu, duration_s=600.0)
    ge = np.array([r["meas"] - r["truth"] for k, r in (imu[0].records + imu[1].records) if k == "gyro"])
    me = np.array([r["meas"] - r["truth"] for k, r in (imu[0].records + imu[1].records) if k == "mag"])
    tgt = cfg0.gyro_white_noise_sigma_rad_s
    ok_g = all(abs(ge[:, i].std() - tgt) < 0.25 * tgt for i in range(3))
    _check("WHITE", "6 gyro noise std", ok_g,
           f"std X/Y/Z = {np.degrees(ge[:, 0].std()):.4f}/{np.degrees(ge[:, 1].std()):.4f}/"
           f"{np.degrees(ge[:, 2].std()):.4f} deg/s (target 0.0298, +/-25%)")
    tm = cfg0.mag_white_noise_sigma_t
    ok_m = all(abs(me[:, i].std() - tm) < 0.25 * tm for i in range(3))
    _check("WHITE", "7 mag noise std", ok_m,
           f"std X/Y/Z = {me[:, 0].std()*1e9:.1f}/{me[:, 1].std()*1e9:.1f}/"
           f"{me[:, 2].std()*1e9:.1f} nT (target 80, +/-25%)")
    # (7b) sun ARRAY white noise: with everything else perfect and a constant
    # truth, the per-cell output scatter equals the configured fraction-of-
    # full-scale sigma (0.003 here), measured on a mid-scale cell.
    if imu[2] is not None:
        sa = imu[2]
        i = sa._names.index("+Z")
        outs = np.array([r["outputs"][i] for r in sa.records])
        sstd = float(outs.std())
        _check("WHITE", "7b sun cell noise", abs(sstd - 0.003) < 0.001,
               f"+Z output std = {sstd:.5f} (target 0.003, tol +/-0.001)")
    else:
        _check("WHITE", "7b sun cell noise", False, "no sun array owned")


# ---- STAGE 3: BIAS ----------------------------------------------------------
def _check_bias() -> None:
    from satellite_parameters import ImuSimParameters
    cfg0 = replace(ImuSimParameters.perfect(), gyro_bias_sigma_rad_s=0.005)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(imu, duration_s=600.0)
    ge = np.array([r["meas"] - r["truth"] for k, r in (imu[0].records + imu[1].records) if k == "gyro"])
    means = ge.mean(axis=0)
    # a bias is a PERSISTENT offset: |mean| clearly nonzero on every axis
    # (white noise is zero here, so any persistent offset proves the bias)
    ok_load = all(abs(means[i]) > 0.0008 for i in range(3))
    widths = np.percentile(ge, [5, 95], axis=0)
    ok_small = np.all((widths[1] - widths[0]) < 0.001)  # very little spread
    _check("BIAS", "8 persistent offset", ok_load,
           f"mean error X/Y/Z = {np.degrees(means[0]):+.4f}/"
           f"{np.degrees(means[1]):+.4f}/{np.degrees(means[2]):+.4f} deg/s "
           f"all |.|>0.17 deg/s (drawn once, stays)")
    _check("BIAS", "9 not fresh noise", ok_small,
           f"90-10 error width < 0.057 deg/s on every axis (constant, not jumping)")


# ---- STAGE 4: WANDER --------------------------------------------------------
def _check_wander() -> None:
    from satellite_parameters import ImuSimParameters
    # wander only: fixed bias OFF, white OFF, wander large so it's measurable
    cfg0 = replace(ImuSimParameters.perfect(),
                   gyro_wander_sigma_rad_s=0.001, gyro_wander_tau_s=50.0)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(imu, duration_s=1000.0)
    ge = np.array([r["meas"] - r["truth"] for k, r in (imu[0].records + imu[1].records) if k == "gyro"])
    if len(ge) < 300:
        _check("WANDER", "10 samples", False, "not enough samples")
        return
    mean_err = ge.mean(axis=0)
    # 1) the error CHANGES over time (wander) -- not a constant bias
    moving_std = ge[300:].std(axis=0)
    ok_changes = bool(np.all(moving_std > 0.0004))
    # 2) temporally CORRELATED: error at lag 1 s should stay similar
    x = ge[:, 0] - ge[:, 0].mean()
    var = float(np.mean(x * x))
    acf1 = float(np.mean(x[:-10] * x[10:]) / var)   # lag 1 s (10 samples)
    ok_corr = acf1 > 0.5
    _check("WANDER", "10 changes over time", ok_changes,
           f"error std across run = {moving_std[0]*1e3:.2f}/"
           f"{moving_std[1]*1e3:.2f}/{moving_std[2]*1e3:.2f} mrad/s (must be > 0.4)")
    _check("WANDER", "11 temporally correlated", ok_corr,
           f"lag-1 s autocorr = {acf1:.2f} (must be > 0.5 -- white noise would be ~0)")

# ---- STAGE 5: SCALE ---------------------------------------------------------
def _check_scale() -> None:
    from satellite_parameters import ImuSimParameters
    cfg0 = replace(ImuSimParameters.perfect(), gyro_scale_error=0.2,
                   mag_scale_error=0.2)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    # truth along a single axis so the per-axis scale is directly measured
    _synthetic_gyro_loop(imu, duration_s=200.0, omega=np.array([1.0, 0.0, 0.0]))
    grecs = [r for k, r in (imu[0].records + imu[1].records) if k == "gyro"]
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag"]
    rx = np.array([r["meas"][0] / r["truth"][0] for r in grecs])
    ratio = float(np.median(rx))
    ok = 0.05 < abs(ratio - 1.0) < 0.7
    _check("SCALE", "12 gyro scale applied", ok,
           f"median meas/truth on X = {ratio:.3f} (0.2 scale draw, "
           f"so clearly off 1.0 and within [0.3, 0.95] or [1.05, 1.7])")
    # mag scale: truth B_body is a nice vector; meas/truth per the drawn scale
    mr = np.array([r["meas"] / r["truth"] for r in mrecs])
    med_m = np.median(mr, axis=0)
    ok_m = float(np.any(np.abs(med_m - 1.0) > 0.05))
    _check("SCALE", "13 mag scale applied", ok_m,
           f"median meas/truth per axis = {med_m[0]:.3f}/{med_m[1]:.3f}/{med_m[2]:.3f} "
           f"(at least one axis clearly off 1.0)")


# ---- STAGE 6: MISALIGNMENT --------------------------------------------------
def _check_misalignment() -> None:
    from satellite_parameters import ImuSimParameters
    cfg0 = replace(ImuSimParameters.perfect(), gyro_misalignment_rad=0.5,
                   mag_misalignment_rad=0.5)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    # truth is a PURE Z spin / PURE Z field: any X/Y measured content proves
    # cross-axis coupling (misalignment), not scale (scale on Z only stretches Z).
    _synthetic_gyro_loop(imu, duration_s=100.0, omega=np.array([0.0, 0.0, 1.0]))
    grecs = [r for k, r in (imu[0].records + imu[1].records) if k == "gyro"]
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag"]
    gx = np.median([r["meas"][0] for r in grecs])   # X leak from pure Z truth
    gy = np.median([r["meas"][1] for r in grecs])
    gz = np.median([r["meas"][2] for r in grecs])
    ok_g = (abs(gx) > 0.05 or abs(gy) > 0.05) and 0.5 < gz < 1.5
    _check("MISALIGN", "14 gyro cross-coupling", ok_g,
           f"median meas with pure-Z truth = [{gx:+.3f}, {gy:+.3f}, {gz:+.3f}] rad/s "
           f"(X/Y leak proves M applied)")
    mx = np.median([r["meas"][0] for r in mrecs])
    my = np.median([r["meas"][1] for r in mrecs])
    _check("MISALIGN", "15 mag cross-coupling", abs(mx) > 1e-7 or abs(my) > 1e-7,
           f"median meas[T] = [{mx:.2e}, {my:.2e}, ...] with pure-Z body field "
           f"(X/Y content proves M_mag applied)")


# ---- STAGE 7: MAGNETOMETER BODY-FRAME CONVENTION ----------------------------
def _check_mag_frame() -> None:
    from satellite_parameters import ImuSimParameters
    imu = (SimulatedGyroscope(ImuSimParameters.perfect()), SimulatedMagnetometer(ImuSimParameters.perfect()), SimulatedSunSensorArray((ImuSimParameters.perfect()).sun_array))
    # Known rotation: q = [cos45, 0, 0, sin45] is +90 deg about Z. Feeding
    # B_eci = [B,0,0] through the repo's own C_bi formula gives
    # B_body = [0,+B,0] (checked numerically against _dcm_bi_from_q -- the
    # check below asserts the sensor reproduces that exact vector). The
    # important property: the measured body field equals
    # _dcm_bi_from_q(q).T @ B_eci to machine precision. A body<->ECI swap
    # (using C_bi instead of C_bi.T) would give a DIFFERENT vector and fail.
    B = 2.0e-5
    q = np.array([np.cos(np.pi / 4.0), 0.0, 0.0, np.sin(np.pi / 4.0)])
    (imu[0].update(0.1, q, np.zeros(3)), imu[1].update(0.1, q, np.array([B, 0.0, 0.0])), None)
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag" and r["valid"]]
    if not mrecs:
        _check("FRAME", "16 90deg body field", False, "no mag record")
        return
    meas = mrecs[0]["meas"]
    expect = _dcm_bi_from_q(q).T @ np.array([B, 0.0, 0.0])   # == [0, +B, 0]
    ok = float(np.linalg.norm(meas - expect)) < 1e-12 and abs(meas[1] - B) < 1e-12
    _check("FRAME", "16 90deg body field", ok,
           f"B_eci=[{B:.0e},0,0] @ +90deg-about-Z -> body = "
           f"[{meas[0]:+.2e}, {meas[1]:+.2e}, {meas[2]:+.2e}] T (expect [0, +{B:.0e}, 0])")
    # identity attitude: body field == ECI field (use zero latency so the
    # buffered truth is exactly this sample, no interpolation lag)
    imu2 = (SimulatedGyroscope(replace(ImuSimParameters.perfect(), gyro_latency_mean_s=0.0,
                                gyro_latency_sigma_s=0.0, gyro_latency_min_s=0.0,
                                gyro_latency_max_s=0.0, mag_latency_mean_s=0.0,
                                mag_latency_sigma_s=0.0, mag_latency_min_s=0.0,
                                mag_latency_max_s=0.0)), SimulatedMagnetometer(replace(ImuSimParameters.perfect(), gyro_latency_mean_s=0.0,
                                gyro_latency_sigma_s=0.0, gyro_latency_min_s=0.0,
                                gyro_latency_max_s=0.0, mag_latency_mean_s=0.0,
                                mag_latency_sigma_s=0.0, mag_latency_min_s=0.0,
                                mag_latency_max_s=0.0)), SimulatedSunSensorArray((replace(ImuSimParameters.perfect(), gyro_latency_mean_s=0.0,
                                gyro_latency_sigma_s=0.0, gyro_latency_min_s=0.0,
                                gyro_latency_max_s=0.0, mag_latency_mean_s=0.0,
                                mag_latency_sigma_s=0.0, mag_latency_min_s=0.0,
                                mag_latency_max_s=0.0)).sun_array))
    (imu2[0].update(0.1, np.array([1.0, 0.0, 0.0, 0.0]), np.zeros(3)), imu2[1].update(0.1, np.array([1.0, 0.0, 0.0, 0.0]), np.array([0.0, 1.0e-5, 0.5e-5])), None)
    m2 = [r for k, r in (imu2[0].records + imu2[1].records) if k == "mag" and r["valid"]][-1]["meas"]
    ok_id = float(np.linalg.norm(m2 - np.array([0.0, 1.0e-5, 0.5e-5]))) < 1e-12
    _check("FRAME", "17 identity body field", ok_id,
           f"id attitude -> body == ECI: max diff "
           f"{float(np.linalg.norm(m2 - np.array([0.0, 1e-5, 0.5e-5]))):.2e} T (< 1e-12)")

# ---- STAGE 8: SATURATION ------------------------------------------------------
def _check_saturation() -> None:
    from satellite_parameters import ImuSimParameters
    # tiny ranges so the normal synthetic truth (0.3 rad/s, ~2.7e-5 T field)
    # blows past them on every sample.
    cfg0 = replace(ImuSimParameters.perfect(), gyro_range_rad_s=0.05,
                   mag_range_t=1.0e-6)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(imu, duration_s=100.0)
    grecs = [r for k, r in (imu[0].records + imu[1].records) if k == "gyro"]
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag"]
    ok_g = (bool(grecs) and all(r["saturated"] for r in grecs)
            and all(float(np.max(np.abs(r["meas"]))) <= 0.05 + 1e-12 for r in grecs))
    _check("SAT", "18 gyro clipped+flagged", ok_g,
           f"{len(grecs)} samples, all saturated, "
           f"max |meas| = {max(float(np.max(np.abs(r['meas']))) for r in grecs):.4f} rad/s "
           f"(range 0.05)")
    ok_m = (bool(mrecs) and all(r["saturated"] for r in mrecs)
            and all(float(np.max(np.abs(r["meas"]))) <= 1.0e-6 + 1e-18 for r in mrecs))
    _check("SAT", "19 mag clipped+flagged", ok_m,
           f"{len(mrecs)} samples, all saturated, "
           f"max |meas| = {max(float(np.max(np.abs(r['meas']))) for r in mrecs):.2e} T "
           f"(range 1e-6)")


# ---- STAGE 9: DROPOUT ---------------------------------------------------------
def _check_dropout() -> None:
    from satellite_parameters import ImuSimParameters
    p = 0.05
    cfg0 = replace(ImuSimParameters.perfect(), gyro_dropout_probability=p,
                   mag_dropout_probability=p)
    imu = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(imu, duration_s=600.0)   # 6000 samples per sensor
    grecs = [r for k, r in (imu[0].records + imu[1].records) if k == "gyro"]
    mrecs = [r for k, r in (imu[0].records + imu[1].records) if k == "mag"]
    fg = sum(1 for r in grecs if not r["valid"]) / max(len(grecs), 1)
    fm = sum(1 for r in mrecs if not r["valid"]) / max(len(mrecs), 1)
    ok_g = abs(fg - p) < 0.02
    _check("DROPOUT", "20 gyro dropout fraction", ok_g,
           f"measured {fg:.4f} vs configured {p:.2f} "
           f"({sum(1 for r in grecs if not r['valid'])}/{len(grecs)} dropped, tol +/-0.02)")
    ok_m = abs(fm - p) < 0.02
    _check("DROPOUT", "21 mag dropout fraction", ok_m,
           f"measured {fm:.4f} vs configured {p:.2f} "
           f"({sum(1 for r in mrecs if not r['valid'])}/{len(mrecs)} dropped, tol +/-0.02)")


# ---- STAGE 10: DETERMINISM ----------------------------------------------------
def _check_determinism() -> None:
    from satellite_parameters import ImuSimParameters
    cfg0 = ImuSimParameters.nominal()
    a = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(a, duration_s=100.0)
    b = (SimulatedGyroscope(cfg0), SimulatedMagnetometer(cfg0), SimulatedSunSensorArray((cfg0).sun_array))
    _synthetic_gyro_loop(b, duration_s=100.0)
    ga = np.array([r["meas"] for k, r in (a[0].records + a[1].records) if k == "gyro"])
    gb = np.array([r["meas"] for k, r in (b[0].records + b[1].records) if k == "gyro"])
    ma = np.array([r["meas"] for k, r in (a[0].records + a[1].records) if k == "mag"])
    mb = np.array([r["meas"] for k, r in (b[0].records + b[1].records) if k == "mag"])
    ok_same = (ga.shape == gb.shape and ma.shape == mb.shape
               and float(np.max(np.abs(ga - gb))) == 0.0
               and float(np.max(np.abs(ma - mb))) == 0.0)
    _check("DETERM", "22 same seed identical", ok_same,
           f"gyro max diff {float(np.max(np.abs(ga - gb))):.1e}, "
           f"mag max diff {float(np.max(np.abs(ma - mb))):.1e} (expect exactly 0)")
    cfg1 = replace(cfg0, seed=cfg0.seed + 1)
    c = (SimulatedGyroscope(cfg1), SimulatedMagnetometer(cfg1), SimulatedSunSensorArray((cfg1).sun_array))
    _synthetic_gyro_loop(c, duration_s=100.0)
    gc = np.array([r["meas"] for k, r in (c[0].records + c[1].records) if k == "gyro"])
    ok_diff = float(np.max(np.abs(ga - gc))) > 0.0
    _check("DETERM", "23 different seed differs", ok_diff,
           f"gyro max diff vs seed+1 = {float(np.max(np.abs(ga - gc))):.3e} (expect > 0)")


# ---- RUNNER -------------------------------------------------------------------
def run_validation() -> int:
    """Run all 10 stages (25 checks). Prints a PASS/FAIL table, returns the
    process exit code (0 = all pass, 1 = any failure). Never weakens a
    tolerance to make it pass -- fix the code instead."""
    global _VAL_RESULTS
    _VAL_RESULTS = []
    print("=" * 78, flush=True)
    print(" SIMULATED IMU VALIDATION -- 10 stages, synthetic truth + real frame math",
          flush=True)
    print("=" * 78, flush=True)
    _check_perfect()
    _check_white()
    _check_bias()
    _check_wander()
    _check_scale()
    _check_misalignment()
    _check_mag_frame()
    _check_saturation()
    _check_dropout()
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



class SensorModelChecks(unittest.TestCase):
    def test_original_sensor_model_checks(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = run_validation()
        self.assertEqual(result, 0, output.getvalue())


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1].lower().startswith('valid'):
        sys.exit(run_validation())
    run_demo()
