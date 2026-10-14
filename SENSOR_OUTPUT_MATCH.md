# Sensor outputs and firmware interfaces

Firmware was read from `C:\Projects\Firmware\Leap_2_ADCS_Firmware_V1` and was
not modified. JSON remains the transport. The `data` object inside each sensor
reading contains device fields; timestamps and validity outside it are transport
metadata. There are no binary packets or native C struct dumps.

## What changed

| Sensor | Previous raw output | Current raw output |
|---|---|---|
| Gyro | Generic range/ADC-dependent counts | ADIS16545 signed high-word X_axis, Y_axis, Z_axis |
| Magnetometer | Generic range/ADC-dependent counts | AK09916/ICM20948 signed X_axis, Y_axis, Z_axis at 150 nT/count |
| GPS | Floating-point receiver fields | ORION GPS integer fields, including all five DOPs and MSL height |
| Sun array | One ADC count per coarse photocell | Six FSS-style records with four quadrants, coordinates, vector, angles and temperature |

The main loop samples sensors once. `send_from_sensors()` calls their cached
`get_raw_data()` functions only while connected, then sends one JSON line.
Navigation continues to decode the same raw readings into SI controller inputs.

## Confirmed device conversions

ADIS16545's `ADIS_READ_GYRO()` returns the signed high word of a 32-bit rate
register. The hardware range is configured with `gyro_hardware_range_deg_s`:
125 (default), 450, or 2000. Count scales are 0.00625, 0.025, and 0.1 deg/s,
respectively. Simulation rates remain rad/s internally. Export converts at the
device boundary and preserves high-word truncation, including negative values.
The firmware detects the actual variant at boot; select the matching variant
when preparing a later SILS test. Accelerometer and SPI registers are outside
this gyro-only interface; no fictitious acceleration is added.

Magnetic field stays in tesla internally. `encode_magnetometer_registers()`
converts to signed 16-bit counts using 0.15 microtesla/count. Both sensors return
sensor-axis values. The configured mounting rotation remains the source of the
simulation's sensor orientation; navigation rotates readings back into body axes.

The ORION `data` object matches `ORION_GPS_TypeDef` field names:

| Fields | Integer representation |
|---|---|
| fix_mode, num_SV | uint8; fix mode 3 is 3D GNSS |
| GNSS_Week | uint16 |
| GNSS_TOW | uint32, 0.01 seconds/count |
| Latitude, Longitude | int32, 1e-7 degrees/count |
| Ellipsoid_altitude, Mean_Sea_Level_Altitude | int32, 0.01 metres/count |
| GDOP, PDOP, HDOP, VDOP, TDOP | uint16, 0.01/count |
| ECEF_X, ECEF_Y, ECEF_Z | int32, 0.01 metres/count |
| ECEF_VX, ECEF_VY, ECEF_VZ | int32, 0.01 m/s/count |

The GPS geometry functions inside `simulategps.py` use a synthetic circular 24-satellite constellation,
not a live almanac, to derive consistent DOP ratios. The existing PDOP profile
scales that covariance. MSL altitude is ellipsoid altitude minus Orekit geoid
undulation using degree/order 36 EGM2008. This is an engineering geoid model;
the receiver's exact onboard geoid data is not available. Existing noise,
latency, cold start, drift, status and dropout models remain active.

The ADCS firmware's active GPS input is the OBC-forwarded `AdsGpsData`, containing
decoded doubles. That is a different boundary from the real ORION sensor's
integer output. No OBC commands or firmware processing have been integrated.

## Fine sun sensor: known layout, provisional calibration

Firmware `FSS_TLM_t` defines uint16 Q1/Q2/Q3/Q4/Temp, uint8 Eclipse, and int16
CrdX/CrdY/VecX/VecY/VecZ/Alpha/Beta. Firmware comments establish that Alpha and
Beta are centidegrees. Slave IDs are 0x11 through 0x16. The repository contains
no FSS manufacturer/model/ICD, and public searches did not identify its protocol.
Consequently an exact vendor-calibrated match cannot yet be claimed.

The fine-sensor functions inside `simulatesunsensor.py` implement a provisional pinhole/four-quadrant model.
Quadrant imbalance produces measured spot coordinates and a reported local
vector; vector/angles are calculated from measured quadrants, not copied from
simulation truth. Sunlight, eclipse, shadows, alignment errors and the existing
brightness errors affect the readings. Earth albedo is a separate optical source
in the Earth-center direction; this approximates an extended illuminated disk.
White noise perturbs quadrants. Internal sensor temperature is a configurable
fixed kelvin input; a thermal dynamics model has not been assumed.

The YAML `fine_*` values explicitly state assumed aperture size, quadrant count
scale, coordinate scale, vector scale and temperature scale. FSS JSON carries
`calibration: provisional; vendor ICD not available`. These assumptions must be
replaced with the actual sensor ICD/calibration before claiming exact matching.
Firmware's 10000 quadrant garbage cutoff is a parser limit, not proof of the
sensor's actual full scale. Its 35-degree gate is a consumer acceptance limit,
not proof of the hardware's optical FOV.

The original coarse-cell diagnostics remain available to the UI and legacy
validation API. The exported JSON contains the fine sensor records. Live
navigation combines the reported local fine-sensor vectors using configured
mount normals/rolls; it no longer treats those records as coarse cosine readings.

## Where to read the code

- `simulateimu.py`: `encode_gyro_registers()`, `encode_magnetometer_registers()`,
  `SimulatedIMU.get_raw_data()`.
- `simulategps.py`: `_orion_output()` and `get_raw_data()`.
- `simulatesunsensor.py`: `quadrant_signal()`, `simulate_fine_sensor()`,
  environment/error model and FSS array acquisition.
- `gps_navigation.py` / `imu_navigation.py`: raw decoding and navigation.
- `send_simulated_sensor_data.py`: `read_raw_sensor_data()` and `send_from_sensors()`.
- `C:\Projects\Simulator\receive_simulated_sensor_data.c`: `main()` listens;
  `receive_sensor_data()` assembles lines; `print_sensor_json()` calls `printf()`.

Firmware definitions, under `leap1_p30_ads_lqfp_v1/Core`:

- `Inc/sensor/ADIS16545.h`, `Src/sensor/ADIS16545.c`.
- `Inc/sensor/ICM20948.h`, `Src/sensor/ICM20948.c`.
- `Inc/sensor/ORIONB16.h`, `Src/sensor/ORIONB16.c`.
- `Inc/sensor/FSS.h`, `Src/sensor/FSS.c`, and `Src/task_defs.c`'s `fssTask()`.

Primary references:

- https://www.analog.com/media/en/technical-documentation/data-sheets/adis16545-adis16547.pdf
- https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ds-000189-icm-20948-v1.5.pdf
- https://www.orekit.org/site-orekit-13.1.2/apidocs/org/orekit/models/earth/Geoid.html
