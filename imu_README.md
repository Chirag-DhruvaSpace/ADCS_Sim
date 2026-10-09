# Simulated IMU (gyroscope + magnetometer) â€” plain-language guide

> The implementation has changed. See [current IMU physics, filtering, mounting and validation notes](validation/IMU_SENSOR_NOTES.md).
> The older discussion below describes earlier filter behavior and is retained as historical context.

Physics integrates truth; the default controller now uses simulated sensor estimates.
`simulateimu.py` is that lying machine for rotation sensing, the same way
`simulategps.py` is the lying machine for position.

## 1. What the sensors measure (one line each)

- GYROSCOPE = how fast the satellite spins, rad/s, body axes [X, Y, Z].
  It does NOT know attitude â€” only spin rate.
- MAGNETOMETER = Earth's magnetic field felt ON the body, Tesla (dashboard
  shows nanotesla, nT = Tesla x 1,000,000,000), axes [X, Y, Z].
  It does NOT know attitude either â€” only the field vector.
- SUN SENSOR ARRAY = six photocells on the hull (simulatesunsensor.py), each
  reading sunlight as a fraction of full scale with a cosine response and a
  60-degree field-of-view cone. The onboard flight computer reconstructs the
  body-frame sun direction by least squares over the active cells. Per-cell
  errors (alignment, bias, thermal drift, scale, nonlinearity, noise, ADC)
  plus eclipse penumbra, Earth albedo and self-shadowing are modelled. The
  old single-vector sun sensor is gone - this array replaced it.

## 2. What each error means (one line each)

- bias = sensor offset drawn once at startup, stays all run.
- wander = slowly changing error that remembers its value (Gauss-Markov,
  drifts over minutes, not fresh jumps).
- white = fresh random noise, new jitter every sample, no memory.
- scale = reports slightly too large/small (e.g. 1.001x).
- misalignment = one axis slightly leaks into another (3x3 matrix M).
- hard-iron = fixed magnetic offset from spacecraft hardware (mag only).
- disturbance = extra slowly-varying magnetic fog from the craft (mag only).
- saturation = cannot report beyond range (clipped + flag raised).
- dropout = sample missing/invalid (valid=False, old value kept).
- latency = sample describes motion a few ms ago (t_meas < t_arrival).
- quantization = rounding to digital steps like a real ADC (OFF by default).

## 3. Where truth comes from (no new physics invented)

- TRUE ATTITUDE: `X_rot[:4]` in `run_simulation()`
  (satellite_flight_visualisation.py) â€” quaternion from
  satellite_rotational_dynamics_var_mag_field.py. Scalar-first, body->ECI.
- TRUE BODY RATE: `X_rot[4:7]` in the same loop (rad/s, [X,Y,Z]).
- TRUE MAG FIELD: engine `magnetic_field_eci(t, r_vec)` (ECI, Tesla).
- FRAME RULE: `B_body = C_bi.T @ B_eci` (same as the detumbling controller).
- UNITS: Tesla in code; nanotesla on the dashboard.

## 4. Where measurements go

TRUE state (X_rot quaternion + rate, engine B_eci)
  fed IN by the main loop each tick (the IMU never fetches truth itself)
  -> SimulatedIMU.update(t, q, omega, B_eci) adds errors
  -> (gyro, mag): None = sensor did not tick, valid=False = dropout
  -> ImuNav (imu_navigation.py): latest good samples = sensor belief
  -> imu_* telemetry keys on the dashboard.

PHYSICS IS UNTOUCHED: dynamics, environment, torques, rendering and truth
metrics keep the TRUE state. Sensor-based paths get the noisy data ONLY
through the controlled switches:

- rate damping (B-dot detumble, RW PD modes, ...) uses the MEASURED gyro rate
  when `use_gyro_for_control` is True (default), else falls back to truth.
- magnetic laws (detumble's B-dot, the MTR cross-product) use the MEASURED
  field when `use_mag_for_control` is True (default), else truth.
  Both switches live in the ImuSimParameters block (satellite_parameters.yaml)
  so you can A/B the sensor's effect on the satellite's motion.

## 4b. The onboard ATTITUDE ESTIMATOR ("satellite's own data")

Gyro + magnetometer together STILL do not give attitude by themselves --
attitude needs an ESTIMATOR that combines them. This project now ships a
small, honest one (imu_navigation.AttitudeEstimator):

  PREDICT: every tick, rotate the attitude belief by the measured gyro rate
           (the gyro is the fast, smooth narrator of the motion).
  CORRECT: when a magnetometer sample arrives, compare the field the belief
           would predict (onboard IGRF model at the GPS-BELIEVED position)
           against the field the magnetometer actually measured, and nudge
           the belief a small step toward agreement (gain 0.05).

Seeded from the TRUE initial attitude (like real flight software gets a
start attitude from the launcher). The belief is displayed on the dashboard
as "Pointing error (sat. own data)" (green <2 deg, orange <15, red above),
plus "imu_att_est_error_deg" vs the true attitude for validation only.

FULL-BELIEF INTEGRATION (all modes): the attitude controllers now compute
their error against the ESTIMATE (q_ctrl from AttitudeEstimator), and the
3D model is oriented from the estimate too (render_estimated_attitude
switch, satellite_parameters.yaml). The satellite steers and is displayed on
what it BELIEVES -- exactly like real flight software -- while physics
keeps integrating the true state. New telemetry key: imu_est_vs_truth_deg
(the belief-vs-reality gap; sub-degree = healthy estimator).

HONEST LIMITS -- one vector is not enough:
  * A SINGLE reference vector (the magnetometer alone) cannot observe
    rotations about the magnetic field line. Proven: a 30 deg starting error
    converges to exactly the unobservable about-B component (~20 deg here)
    even with a PERFECT gyro. That is real physics, not a bug.
  * Started AT the truth (the real operating case), the belief TRACKS the
    truth well: ~0.1-0.7 deg error with ~0.13 deg jitter over a commanded
    spin (verified numerically). That small jitter is the sensor's
    fingerprint on the display.
  * Real missions add a SECOND reference (sun sensor / star tracker) for
    full 3-axis observability -- a natural future upgrade.

## 5. Configuration â€” the ONE line (satellite_parameters.yaml)

IMU_SIM = ImuSimParameters.nominal()

Presets: .off() = disabled, no new keys; .perfect() = equals truth;
.nominal() = realistic default; .degraded() = worse but plausible;
.stress() = very poor, for robustness testing.
Each preset carries a matching nested sun array (ImuSimParameters.sun_array,
a SunSensorArrayParameters with its own off/perfect/nominal/degraded/stress
presets - see simulatesunsensor.py). Self-test of the array alone:
    .venv\Scripts\python.exe simulatesunsensor.py            # demo
    .venv\Scripts\python.exe simulatesunsensor.py validate   # 13 stages, 22 checks

Nominal: gyro noise 0.00052 rad/s (0.03 deg/s), startup bias 0.00035,
wander 0.00020 (tau 100 s), scale 0.001, misalignment 0.001 rad; mag noise
80 nT, hard-iron 150 nT, spacecraft disturbance (100, -50, 25) nT fixed +
20 nT wander (tau 200 s); gyro + mag 10 Hz (== the 0.1 s ADCS loop, the
fastest this loop can tick); latency ~5 ms gyro / ~10 ms mag.

## 6. Demo, validation, logs

.venv\Scripts\python.exe simulateimu.py            # 10-min demo + stats
.venv\Scripts\python.exe simulateimu.py validate   # 10 stages, 23 checks

Validation must print 25 PASS, 0 FAIL (nonzero exit otherwise). All randomness
flows from one seeded generator, so runs are exactly reproducible.

## 7. Integration Report

ADDED: simulateimu.py (~900 lines: measurements, GaussMarkov, SimulatedIMU
with ONE rng, demo, validation); imu_navigation.py (~250 lines:
ImuNav holder + imu_* telemetry + AttitudeEstimator + quaternion helpers);
imu_README.md (this file).

CONFIGURATION: satellite_parameters.yaml (IMU and sensor values); satellite_flight_visualisation.py, exactly a few spots: (1)
module level ~line 58: imports + _imu_sim/_imu_nav/_att_est; (2) loop after
B_eci ~line 231: _imu_sim.update(t, X_rot[:4], X_rot[4:7], B_eci) ->
_imu_nav.update(...) -> _att_est.update(t, gyro_belief, mag, model_B_eci);
(3) loop ~line 452: compute imu_att_pointing_error_deg (satellite's own
data, vs the current mode's target) + imu_att_est_error_deg (validation);
(4) telemetry ~line 690: data_to_send gains the imu_* + sat-own-data keys
only when IMU enabled.

NOT MODIFIED: engine/, engine_adcs_bridge.py, rotational dynamics core,
torque_distribution, calculate_disturbances, pointing modules, store,
quat2eul, simulategps.py, gps_navigation.py. GPS behavior unchanged.

## 8. Estimator status (what exists, what is next)

WHAT EXISTS NOW (imu_navigation.py):
  * AttitudeEstimator ("satellite's own data" belief) -- PREDICT with the
    measured gyro rate, CORRECT with the magnetometer against the onboard
    IGRF model at the GPS-believed position. Seed = true initial attitude.
  * ImuNav -- latest-good gyro/mag holder (the sensor belief) + telemetry.
  * Display: "Pointing error (sat. own data)" + estimate-vs-truth, on the
    dashboard, only when IMU is enabled.

WHAT IS NEXT (documented, NOT built -- deliberate):
  * Feed the ESTIMATE into the ADCS attitude-error path (the controllers
    currently still use the TRUE attitude for the error angle; rate and
    magnetic field already come from the sensors). That is the step that
    makes the satellite's motion itself depend on the estimated attitude.
  * Add a SECOND reference (sun sensor / star tracker) for full 3-axis
    observability and to kill the magnetometer-only about-B residual.
  * A full filter (complementary / EKF / TRIAD / QUEST) if you want
    covariance and gyro-bias estimation.
No changes inside simulateimu.py are needed for any of these.


