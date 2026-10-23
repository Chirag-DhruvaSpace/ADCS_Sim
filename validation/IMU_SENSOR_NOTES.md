# IMU and viewer changes

The default flight path is sensor-driven: physical truth feeds `SimulatedSensors`,
receipts feed `ImuNav`, and its reconstructed Sun vector and six-state
multiplicative EKF feed the controller. The EKF estimates attitude and gyro
bias. Magnetic references use the GPS-believed position; solar ephemerides
are onboard models. No initial true attitude or rate is injected.

The existing `use_*_for_control=False` and `IMU_SIM.off()` settings remain
explicit ideal-truth diagnostic modes. Keep all three control switches enabled
for sensor-only flight. Disable errors with `.perfect()` or zero noise/bias
parameters, not by bypassing onboard navigation.

## Sun physics

Direct output is `max(0, normal Ã‚Â· sun_direction) * eclipse_fraction` inside
the FOV, before blockers and electronics. Disabling penumbra selects a binary
shadow at 50% solar visibility; it no longer creates sunlight in umbra.
The FOV is a **half-angle**: 90Ã‚Â° covers a hemisphere.

Three orthogonal faces see a generic direction. The cube diagonal gives 57.735%
output on each, not 95%. The default 1.5% activation threshold is five nominal
white-noise sigmas. Uniformly distributed ideal directions yield about 95.5%
three-cell coverage; this is not guaranteed for an actual attitude trajectory,
eclipse or shadow. At exact axis alignment only one cell is illuminated. The
active-cell least-squares reconstruction refuses fewer than three independent
normals; the filter then uses gyro/magnetometer information.

Earth-reflected light is integrated over visible, illuminated Lambertian surface
patches with range, incidence and sensor-FOV factors. It can illuminate a cell
facing away from the Sun. `enable_albedo=False` removes it; disabling electronic
noise alone should not. `albedo_scale` is uniform surface reflectivity [0,1].
The arccos-output angle in telemetry is only a geometric incidence angle under
full direct illumination without albedo, saturation or electronic errors.

## Mounting and display

Settings has four tabs: View, Scene, Sensors, Performance. Sensors contains
visibility/glow switches and a live mount editor. Positions are body-frame metres;
Sun normals and FOV are editable. Runtime edits apply at the next tick and
restart sensor calibration, without rewriting permanent configuration.

Permanent settings are under `imu_sim` in `satellite_parameters.yaml`: positions,
scalar-first mounting quaternions, Sun array parameters and a 3Ãƒâ€”3 local magnetic
gradient in T/m. Gyro rate is independent of position on a rigid body. Magnetic
position dependence uses the configured linear gradient, not an electromagnetic
field solver. Mount rotations transform into chip axes before errors/clipping
and back into calibrated body axes for receipts.

Hardware markers are overlays, including internal devices. Sun glow follows
measured output; gyro/magnetometer glow indicates receipt validity. Attitude
display smoothing defaults on; disable it to inspect raw sample jitter.
`render_estimated_attitude=False` displays physical rather than estimated attitude.
Telemetry truth comparisons share the sampling epoch and ECI attitude frame.

Distant zoom uses the globe texture instead of overlapping detailed tiles. The
orbit line is an instantaneous two-body **osculating ellipse**, transformed into
current ECEF, not a future high-fidelity ground track. Hidden browser tabs skip
rendering and live diagnostic histories are bounded. Disabling video streaming
also avoids capture rendering and encoding.

## Verification and limits

Sensor checks run with `.venv/Scripts/python.exe -B -m pytest validation/test_sensor_navigation.py validation/test_hardware_sensor_outputs.py`. The original standalone model checks remain in `simulate_sunsensor.py validate` and `-m validation.test_simulated_sensor_models validate`.

These checks establish numerical behavior, not flight-qualified accuracy.
Albedo assumes a spherical Earth, uniform reflectivity, finite quadrature and
no cloud maps or reflected-light spacecraft occlusion. The EKF uses tuned
direction uncertainties and a local attitude prior; latency compensation assumes
constant rate rather than a historical-state smoother. Its bias random walk
approximates the simulated GaussÃ¢â‚¬â€œMarkov process. Absolute pointing accuracy
requires actual sensor calibration, geometry, field gradients and covariance
tuning. The existing disturbance budget also uses fallback spacecraft values.

References: [Basilisk coarse Sun sensor model](https://hanspeterschaub.info/basilisk/Documentation/simulation/sensors/coarseSunSensor/index.html)
and [NASA magnetometer/gyro attitude estimation](https://ntrs.nasa.gov/citations/20000091036).

## Optional multiple sensors and canonical configuration

`satellite_parameters.py` defines `VectorSensorParameters`; `satellite_parameters.yaml` sets `imu_sim.gyros` and
`IMU_SIM.magnetometers`. Empty tuples retain the existing single-chip defaults
and random sequence. Nonempty tuples instantiate independently seeded hardware;
each unit can inherit or override its family's sampling, latency, noise, range,
response matrix, fixed bias, mounting, and magnetic-gradient settings. An
explicit tuple whose members are all disabled produces no readings.

`ImuNav` applies only supplied onboard calibration to returned body vectors.
It excludes invalid, saturated, stale and excessively time-skewed units, then
combines them using configured confidence weights. It never subtracts the
simulator's hidden random error realization. This is a weighted common-vector
measurement and one aggregate-bias MEKF, not independent per-chip bias states
or asynchronous smoothing. Correlated errors do not disappear through averaging;
configure measurement/process uncertainty for the actual hardware ensemble.
On loss of all usable units the last known vector is retained and marked invalid.
Gyro propagation coasts with that last known rate; it cannot infer missing motion.

Gyros propagate attitude; magnetometer and reconstructed Sun vectors correct it.
The magnetic reference uses the onboard position belief and field model; the Sun
reference is an ephemeris direction. MTR allocation and B-dot use the measured
magnetic field with estimated attitude/rate under the default sensor-control
switches. The actual actuator torque still uses the physical field in the plant.
Explicit legacy `use_*_for_control=False` switches and `IMU_SIM.off()` retain
truth-based comparison modes. Turning ONLY the EKF off now means gyro-only
propagation, not truth feedback. Its innovation gate, bias bound and initial
covariance are wired to the canonical parameters.

Sensor locations, mount orientations and field gradients are configured in backend YAML. Optional `imu_mount_defaults` entries are applied at startup. Restart the simulation after editing them; no frontend mounting editor or mounting API remains.

## Viewer and verification scope

Four settings tabs occupy the inspector column. At small widths the scene and
panels stack vertically. Controls, tab changes, panel changes and details have
short UI transitions; reduced-motion preferences are honored. Numerical readings
are never interpolated by these animations. Existing optional attitude-display
smoothing is separate from the simulation equations.

The feed meter counts unique, successfully processed telemetry receipts per
rolling wall-clock second, plus a page-lifetime total. Sequence and session IDs
prevent repeated REST polls from being counted again. It does not estimate
unpublished integration steps or claim to count every server transmission.

`--integration --multi` exercises two gyros and two magnetometers through the
live engine and controller. The default 300-second stability regression remains
at 0.155179 degrees estimate error, 2.310464 degrees actual pointing error and
0.0306384 degrees/second final rate after the modularity changes. These are
scenario results, not precision guarantees. This change preserves the existing
plant integration and force equations. Earlier work DID change the sensor
albedo/eclipse model, quaternion propagation order, feedback routing and sample
timing; it would be incorrect to claim the entire effort made no assumptions or
left every preexisting equation untouched.


Current checks: `.venv/Scripts/python.exe -B -m pytest validation/test_sensor_navigation.py validation/test_hardware_sensor_outputs.py`; frontend: `npm.cmd test` and `npm.cmd run test:browser` from `frontend/`. The browser fixture is `validation/tools/viewer_test_server.py`. Sensor locations and mount orientations are configured in backend YAML only.
