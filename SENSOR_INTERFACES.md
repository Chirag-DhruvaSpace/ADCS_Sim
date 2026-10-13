# Raw sensors and replaceable navigation

The main simulation now follows this boundary:

```
engine truth -> sensor errors -> raw digital packet
                                |-> external SILS / TCP export
                                |-> Python navigation -> controller inputs
```

These are generic hardware-style interfaces, independent of firmware. A raw
packet represents what a digital gyro, magnetometer, photocell array or GPS
receiver can report. It does not claim compatibility with a named chip's SPI,
UART, NMEA, or proprietary binary protocol. A named-device adapter can be added
without changing physics or navigation. No raw packet contains truth, applied
bias/noise, an ECI navigation solution, or reconstructed attitude/sun direction.

## Sampling and reading

Call `get_raw_data(truth arguments...)` once per simulation tick. Sensor timing,
latency, noise, drift, dropout, saturation and YAML profiles remain in the
existing simulator. Calls at the same tick return the same cached result;
`get_raw_data()` with no arguments reads the current tick without resampling.
`None` means no new receipt on that tick. Gyro/magnetometer/sun dropout receipts
carry `valid=False`; GPS remains silent during dropout, cold start or blackout.
Keep a last-received packet on the consumer side if a held reading is needed.

```python
gps_raw = gps.get_raw_data(t, position_eci_m, velocity_eci_m_s)
gyro_raw, mag_raw, sun_raw = imu.get_raw_data(
    t, quaternion, body_rate_rad_s, magnetic_field_eci_t, sun_direction_eci,
    eclipse_fraction=lighting_ratio, position_eci=position_eci_m)

# Repeated reads do not advance the RNG or consume another sensor tick.
gyro_raw = imu.get_gyroscope_raw_data()
mag_raw = imu.get_magnetometer_raw_data()
sun_raw = imu.get_sun_sensor_raw_data()

# A standalone photocell array exposes the same raw interface.
sun_raw = sun_array.get_raw_data(t, quaternion, sun_direction_eci,
                               lighting_ratio, position_eci_m)
```

The engine is advanced only by the simulation loop, never by sensor getters.
When multiple units are configured, gyro/magnetometer results are lists of
`(unit_configuration, packet_or_None)`. Only enabled units appear. The TCP
export sends their names and raw packets, not their calibration/configuration.

## Formats

Definitions live in `sensor_packets.py`. Immutable packets have `to_bytes()`
and matching `from_bytes()`. All wire formats are little-endian, version 1,
without C padding. Sampling/arrival times in seconds are simulation transport
metadata. In production hardware, the driver or transport supplies this timing.

| Sensor | Raw fields | Decoder knowledge |
|---|---|---|
| Gyro | Signed X/Y/Z counts in gyro axes, valid/saturated | ADC bits, range in rad/s, mounting rotation |
| Magnetometer | Signed X/Y/Z counts in magnetometer axes, valid/saturated | ADC bits, range in tesla, mounting rotation |
| Coarse sun array | Named unsigned photocell ADC counts, ADC bits, valid/saturated | Nominal cell normals and reconstruction settings |
| GPS | Week/TOW, fix status, satellite count, PDOP, geodetic position, ECEF/ENU velocity, accuracy and latency | Epoch and ECI/ECEF frames |

Vector register magnitude is `2**(adc_bits-1)-1`. One count represents
`configured_range / register_magnitude` in rad/s or tesla. The output is
symmetric signed full scale. `gyro_adc_bits` and `mag_adc_bits` are configurable
in `satellite_parameters.yaml` (default 16, supported 8..24), including per-unit
overrides. Counts occupy signed 32-bit transport fields to support all depths;
they are not a dump of a native C struct.

Vector byte layout is `<BBdd3iBB`: version, kind (1 gyro / 2 magnetometer),
measurement time, arrival time, three signed counts, valid, saturated: **32 bytes**.

Sun counts range from zero to `2**adc_bits-1`; the existing cell `adc_bits`
setting defaults to 12. Sun byte layout starts with `<BddBBH`: version,
measurement time, arrival time, valid, ADC bits, cell count. Each cell follows as
`<H` UTF-8 name length, name bytes, `<HB` ADC count and saturation flag.

GPS uses `<BIdddBB16d`: version, GPS week, TOW, measurement/arrival time,
fix type, satellite count, then PDOP, latitude, longitude, ellipsoid altitude,
ECEF position[3], ECEF velocity[3], ENU velocity[3], horizontal accuracy,
vertical accuracy, latency: **159 bytes**. Latitude/longitude are degrees,
position/altitude/accuracy metres, velocity m/s, and time seconds.

Intrinsic digital output necessarily rounds to registers even with the error
profile `perfect` or an additional quantization error disabled. Existing
`gyro_quantization_rad_s`, `mag_quantization_t`, and sun quantization controls
still control extra sensor-stage quantization before final digital output.
Perfect therefore means zero injected error, with finite register resolution.

## Navigation and simulation inputs

```python
gps_nav.process_raw_data(gps_raw, epoch_utc, inertial_frame, earth_fixed_frame)
position_belief, velocity_belief = gps_nav.get_processed_data(t)

imu_nav.process_raw_data(t, gyro_raw, mag_raw, sun_raw, imu_config)
imu_nav.estimate(t, magnetic_reference_eci, sun_reference_eci)
processed = imu_nav.get_processed_data()
```

`GpsNav.process_raw_data()` owns ECEF-to-ECI position/velocity conversion and fix
acceptance. `ImuNav.process_raw_data()` decodes ADC counts, rotates sensor axes
into body axes, invokes existing per-unit calibration/fusion, and reconstructs
sunlight from counts. `estimate()` runs the onboard attitude/bias estimator.
Both processed-data getters expose the inputs used by the main loop, independently
of how the raw data was produced. The loop passes IMU results into
`satellite_rotational_dynamics_var_mag_field.set_imu_adcs_input()` and passes
GPS position/velocity into the rotational controller call.

External SILS can consume the raw packet bytes instead of running these Python
navigation functions. It can return processed belief/controller inputs through
the same downstream boundary, or actuator commands through an actuator bridge.
This change does not implement or modify a firmware integration.

`update()` is retained as the legacy physical-unit compatibility API for
existing validation scripts. Do not mix legacy and raw sampling at different
paths for the same hardware tick. The live main loop uses only `get_raw_data()`.

## Transport and operator diagnostics

`send_simulated_sensor_data.get_raw_sensor_data()` collects only public raw
packets. Its JSON envelope is now version 2; gyro/magnetometer values are counts,
sun outputs are ADC counts, and GPS contains no ECI navigation fields. It does
not resample sensors. A disconnected TCP sender skips collection/encoding.
`to_bytes()` is available for binary transports; TCP users must add framing
and handle partial reads/writes rather than assuming one receive per packet.

The UI still shows decoded measurements, estimated attitude and physical
environment diagnostics. Sun shadow/FOV/albedo details come from a separate
simulator diagnostics tap and never enter raw packets or navigation.

Validation: `python -B -m unittest validation.test_raw_sensor_interfaces
validation.test_sensor_navigation validation.test_sensor_tcp`.
