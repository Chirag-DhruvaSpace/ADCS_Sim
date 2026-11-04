# ADCS Sim -- P-30XL Attitude Determination & Control System Simulator

> High-fidelity Model-Based Design simulator for the **Dhruva Space P-30XL** ADCS -- Orekit orbital physics, sensor emulation, pointing laws, RW + MTQ actuation, firmware SITL, and a React + Three.js mission viewer.

![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)
![Orekit](https://img.shields.io/badge/Orekit-13.0_JDK21-orange?style=flat-square)
![Flask](https://img.shields.io/badge/Flask-3.1-black?style=flat-square)
![React](https://img.shields.io/badge/React-19_Vite-61DAFB?style=flat-square&logo=react)
![Three.js](https://img.shields.io/badge/Three.js-0.160-black?style=flat-square)

<p align="center">
  <img src="frontend/assets/loading/dhruva-logo.webp" alt="Dhruva Space logo" width="260" />
</p>

## Table of Contents

- [1. Overview](#1-overview)
- [2. Features](#2-features)
- [3. Repository Structure](#3-repository-structure)
- [4. Prerequisites](#4-prerequisites)
- [5. Quick Start](#5-quick-start)
- [6. Configuration](#6-configuration)
- [7. Pointing Modes](#7-pointing-modes--controllers)
- [8. Physics Engine](#8-physics-engine)
- [9. Sensors](#9-sensors--navigation)
- [10. Actuators](#10-actuators)
- [11. Firmware SITL](#11-firmware-sitl-hardware-in-the-loop)
- [12. Viewer & API](#12-web-viewer--telemetry-api)
- [13. Tests](#13-validation--tests)
- [14. CAD Pipeline](#14-cad-pipeline)
- [15. Troubleshooting](#15-troubleshooting)
- [16. Docs & Credits](#16-additional-documentation)
- [17. Credits & License](#17-credits--license)

---

## 1. Overview

Closed-loop ADCS simulation for a ~500 km Sun-synchronous orbit (97 deg) P-30XL mission:

- **Orbit truth** -- Orekit Java propagator via JPype: EGM2008, NRLMSISE-00 drag + weather, SRP + eclipse, Sun/Moon ephemerides, IGRF field.
- **Attitude truth** -- Euler dynamics + quaternion kinematics at 10 Hz, coupled to faceted CAD surface physics.
- **Flight belief** -- emulated GPS, IMU (gyro + mag), sun-sensor array with noise/bias/latency/dropouts feeding a MEKF.
- **Control** -- B-dot detumble, Sun/Moon/Nadir, RW PD, periodic-gain LQR for MTQs, custom-quaternion, firmware-SITL.
- **Viewer** -- React + Three.js dashboard at `http://127.0.0.1:5000`.

Default: `500.003 km` circular SSO, epoch `2026-10-01T15:00:00Z`, DOP853, 10 Hz loop.

## Screenshots

![Mission dashboard](frontend/assets/reference-analysis/reference-video-5fps/frames/00333.jpg)
*Live mission dashboard -- 3D spacecraft, Earth, orbit track and telemetry charts.*

![Orbit viewer](frontend/assets/reference-analysis/earth-balanced.png)
![Sensor viewer](frontend/assets/reference-analysis/cad-stowed.png)


---

## 2. Features

| Area | Capability |
|------|------------|
| Orbit | Orekit DOP853, EGM2008, NRLMSISE-00 + weather, SRP + shadow, dense-output interp |
| Attitude | Quaternion kinematics, Euler dynamics, 0.1 s tick, GG/aero/SRP/dipole torques |
| Spacecraft | CAD deployed (27.29 kg) / stowed (30.40 kg) + legacy 6 kg cube |
| Pointing | SUN_POINTING, SUN_POINTING_RW, RW, MOON, NADIR, SUN_SWEEP, NOMINAL_IN_ORBIT, KINEMATIC_ROBUSTNESS, CUSTOM, FIRMWARE_SITL |
| Sensors | GPS + nav filter, IMU + MEKF, 6-face sun array |
| Actuators | 4-wheel tetra array (55 deg, ~4 mN-m) + 3-axis MTQs (0.1 A-m2 quant) |
| SITL | UDP bridge to real flight firmware |
| Viewer | React 19 + Vite + Three.js 0.160 + GSAP 3.15 |
| Ops | Live speed reload, one-click setup, pytest + browser suites |

---

## 3. Repository Structure

```text
run_simulator.py                  # Main entry: physics + Flask viewer
app.py                            # Flask server (API + serves frontend/dist)
launcher.py                       # Alias -> run_simulator.main()
main.py                           # 24-h engine-vs-Orekit check (headless)
satellite_parameters.yaml         # PRIMARY CONFIG
advanced_satellite_parameters.yaml# CAD mass/inertia/facets/mounts
satellite_flight_visualisation.py # Main ADCS closed-loop sim (10 Hz)
engine/                           # Validated Orekit propagator wrapper
engine_adcs_bridge.py             # Bridge: ADCS <-> engine orbit provider
*_pointing.py                     # Controllers (sun, moon, nadir, RW, ...)
MTR_allocator.py / torque_distribution.py / cross_b_torque.py
calculate_disturbances.py / spacecraft_surface_physics.py
simulate_gps.py / compute_simulated_position.py
simulate_gyroscope.py / simulate_magnetometer.py / compute_simulated_attitude.py
simulate_sunsensor.py / sun_vector_eci.py
firmware_sitl_adapter.py / firmware_sitl_link.py / telemetry.py
pointing_client.py / control_states.py / store.py
frontend/                         # Vite + React + Three.js viewer
validation/ / orekit-data/
Setup.bat / setup.ps1 / requirements.txt
K_seq.npy / t_grid.npy            # Stored periodic-LQR gains
```

---

## 4. Prerequisites

| Requirement | Notes |
|-------------|-------|
| OS | Windows 10/11 64-bit (primary). Linux works with adapted steps. |
| Python | 3.12 64-bit with py launcher (enforced by setup). |
| Java | JDK 21 via jdk4py>=21,<22. JDK 25 breaks Orekit. |
| Node.js | LTS 18+ with npm -- frontend build only. |
| Resources | 8+ GB RAM, ~2 GB free. Port 5000 free. |

Python deps: flask, waitress, requests, numpy, scipy, pyyaml, orekit-jpype, jdk4py, astropy, pymap3d, matplotlib, trimesh, pytest. Frontend: react 19, three 0.160.0, gsap 3.15.0, vite 6.

---

## 5. Quick Start

### 5.1 One-click setup (Windows)

Double-click **Setup.bat** -- checks Python 3.12 / Node / orekit-data / port 5000, (re)creates .venv, installs deps, fixes JAVA_HOME, builds frontend, smoke-tests JVM + Orekit, boots sim until / returns 200.

```batch
Setup.bat                :: full setup (nuke .venv, reinstall, build, prove boot)
Setup.bat -ReuseVenv     :: keep .venv (fast re-run)
Setup.bat -KeepRunning   :: leave sim running after proof
Setup.bat -ViewerOnly    :: viewer only, skip physics/Java
Setup.bat -SkipFrontend  :: skip npm build
Setup.bat -NoSmoke       :: skip smoke tests
```

Log: setup.log.

### 5.2 Manual setup

```powershell
py -V:3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:JAVA_HOME = (python -c "import jdk4py; print(jdk4py.JAVA_HOME)")
cd frontend; npm.cmd install; npm.cmd run build; cd ..
```

### 5.3 Run

```powershell
.\.venv\Scripts\python.exe run_simulator.py
# open http://127.0.0.1:5000
```

| Command | Purpose |
|---------|---------|
| python run_simulator.py | Full sim (physics + viewer). Use this. |
| python app.py | Viewer only, no physics/Java. |
| python launcher.py | Alias of run_simulator.py. |
| python main.py | 24-h engine-vs-Orekit headless check. |

Restart after YAML edits (except simulation.speed, hot-reloaded). Rebuild frontend + hard-refresh after viewer changes.

```powershell
cd frontend
npm.cmd run dev      # -> http://127.0.0.1:5173/frontend/ (proxies to Flask)
npm.cmd run preview  # preview production build
npm.cmd test         # regression checks
```

---

## 6. Configuration

All tuning lives in **satellite_parameters.yaml** (+ CAD overrides in advanced_satellite_parameters.yaml). Conventions: SI units unless named otherwise, body vectors [X, Y, Z], quaternions scalar-first [w, x, y, z] (body -> ECI), sigma = 1-sigma.

### Spacecraft model (CAD vs legacy)

```yaml
# satellite_parameters.yaml
use_advanced_satellite_model: true   # true = CAD, false = legacy cube
# advanced_satellite_parameters.yaml
panels_deployed: true                # true = deployed, false = stowed
```

| Model | Mass | COM (m) | Notes |
|-------|------|---------|-------|
| Deployed | 27.29 kg | (-0.01855, -0.01489, -0.16821) | Open panels, facet physics |
| Stowed | 30.40 kg | (-0.01682, -0.01421, -0.12967) | Closed config |
| Legacy | 6.0 kg | centered | 0.3 m cube, inertia [1.465, 1.176, 1.244] |

See CAD_CONFIGURATION.md.

### Pointing strategy

```yaml
pointing:
  strategy: legacy          # legacy | custom | firmware_sitl
  legacy_mode: SUN_POINTING
  custom:
    input: desired_quaternion
    quaternion: [1.0, 0.0, 0.0, 0.0]
    reference_quaternion: [1.0, 0.0, 0.0, 0.0]
```

- legacy -- dashboard selector (SUN_POINTING, RW, MOON, NADIR, SUN_SWEEP, SUN_POINTING_RW, NOMINAL_IN_ORBIT, KINEMATIC_ROBUSTNESS).
- custom -- scalar-first body->ECI quaternions via YAML or live client:

```python
from pointing_client import send_pointing_input
send_pointing_input([1, 0, 0, 0])
send_pointing_input(q_err, quaternion_error=True, reference_quaternion=q_ref)
```

- firmware_sitl -- external firmware owns actuation over UDP (see section 11).

### Sensor profiles

Values: custom / off / perfect / nominal / degraded / stress.

```yaml
sensor_profiles:
  gps: custom
  gyroscope: custom
  magnetometer: custom
  sun_sensor: custom
  star_tracker: perfect
```

Each sensor has its own `enabled` master switch and settings under `gps`, `gyroscope`, `magnetometer`, `sun_sensor`, or `star_tracker`. A false master switch overrides its profile. Star tracker supports the same profile names; `custom` uses its YAML errors and `perfect` removes modeled errors.

`magnetorquers` defines the coil plant in `simulate_magnetorquers.py`: any number
of named rods with YAML positions, axes, electrical constants, current/dipole
limits and individual `enabled` switches. The selected advanced configuration
supplies the three CAD-derived P-30XL rod placements. Settings > Sensors >
Magnetorquer markers controls their visibility; orange illumination follows
achieved coil dipole. Physical disabling uses YAML. Multiple magnetometers use
`magnetometer.units`; each Sun-sensor head also has its own `enabled` switch.
All sensors may be disabled together. Use `custom` profiles for literal error
settings. See [magnetic hardware configuration](CAD_CONFIGURATION.md#configurable-magnetic-hardware)
for YAML inheritance, firmware channel mapping, hardware scales and limitations.

`gyroscope.use_for_control`, `magnetometer.use_for_control`, `attitude_navigation.use_for_control`, and `attitude_navigation.render_estimated_attitude` select sensor belief versus truth for A/B tests.

### Simulation speed

```yaml
simulation:
  speed: 10.0                  # sim-sec per real-sec (hot-reloaded, max 1 Hz)
  telemetry_publish_period_s: 0.25
  orbit_output_window_s: 0.5   # 0.1 restores legacy coupling
```

1.0 = realtime. Steps are never skipped -- if hardware lags, /api/latest reports simulation_speed_requested / simulation_speed_actual / simulation_lag_s. Charts redraw at most 2 Hz, keep last 30 sim-seconds.

---

## 7. Pointing Modes & Controllers

| File | Law |
|------|-----|
| periodic_gain_sun_pointing.py (+ K_seq.npy, t_grid.npy) | Periodic-gain LQR + governor, MTR Sun-pointing (body -Z -> Sun) |
| sun_pointing_rw.py / sun_pointing_rw_z.py | RW Sun-pointing PD variants |
| moon_pointing.py / nadir_pointing.py | Moon / Nadir (LVLH) tracking |
| nominal_in_orbit_pointing.py | Nominal orbital attitude |
| kinematic_robustness_pointing.py | Robust kinematic test law |
| satellite_rotational_dynamics_var_mag_field.py | Dynamics + DETUMBLE/RW/SUN switching (hysteresis 2.0 / 0.5 deg/s) |
| adcs_target_frame.py / quat2eul.py / sun_vector_eci.py | Frames + conversions |

Boresight: body -Z to Sun (2 DOF; spin about Sun line is free). Design derivation: CLAUDE.md.

---

## 8. Physics Engine

Attitude uses one convention in Python control and firmware SITL: scalar-first
Hamilton `q = [w,x,y,z]`, `v_eci = R(q) @ v_body`, and
`q_dot = 0.5 * q * [0,omega_body]`. Sensors, facet forces, disturbances,
navigation, targets and rendering share `attitude_frames.py`. Existing YAML
sensor mounting quaternions retain their historical passive encoding through
`mount_to_body`; they are not spacecraft attitude quaternions. The configured
star-tracker mounting matches firmware `RelQuat[3]`/`RelDCM[3]`.

Firmware actuator commands are held for each 10 ms attitude interval inside the
existing outer control/display tick. IMU acquisition is paced before the next
interval is integrated; ACS commands are polled between intervals. The existing
UDP layouts, outer telemetry rate, launch commands and legacy speed controls are
preserved. Late firmware intervals rebase the pacing deadline rather than replay
queued captures in a burst. Actual speed and lag still include the delay; a busy
host may run slower than 1x. This is not a hard real-time or HIL timing guarantee.

Each wheel and torquer command expires independently after
`simulation.firmware_command_timeout_s` wall seconds (default 2), producing zero
actuation until a new valid command for that actuator arrives. Mode/status packets
cannot refresh actuator lifetimes. Wheel momentum persists through expiry.
Telemetry publishes per-actuator ages/freshness, command state and scheduling lag.
Wheel torque/impulse and ACS-commanded rod current/dipole remain bounded by the
configured plant. The live plant integrates `[q, omega, h_wheels]` together:
positive wheel commands mean positive body reaction torque and `h_dot = -u`.
The Euler equation includes `omega cross (I omega + A h)`, using the active
mode's configured wheel axes. Set `reaction_wheels.initial_momentum_Nms` in YAML
to initialize spinning wheels. This is an ideal momentum-exchange model, without
motor electrical dynamics. The seven-component derivative API remains available
for existing analysis callers; live runs commit accepted eleven-component states.

Native orbit/environment models initialize before the firmware pacing clock
starts. The viewer caps rendering at `viewer.max_fps` (shipped value 30) to reduce
contention on high-refresh displays; this does not change physics or sensor rates.

Facet shadow rays use the bundled generic Java helper when a Java compiler is
available, compiled once into `.cache` for the active JVM. NumPy remains the
fallback. Both paths test the same quadrature points and blocker geometry.
SITL prepares the next outer tick before its packet deadline, then sends at the
deadline; it does not replay missed samples in a burst or accelerate firmware.

Initial plant attitude and the surface predictor use the same validated,
normalized `attitude.initial_quaternion_scalar_first`; the estimator prior stays
independent. Sensor rates above their actual acquisition cadence now raise a
clear startup error (legacy: outer tick; SITL: gyro/magnetometer 100 Hz, other
sensors outer tick). Reduce the rate or control step instead of losing samples.

Orekit loads `model_data.orekit_data_path` relative to the YAML file. Magnetic
selection is explicitly `WMM` or `IGRF`, with no automatic substitution; the
weather loader uses `space_weather_file_pattern`. Restart to change datasets.
Actual selections and paths appear in telemetry's model list.

Historical magnetic-pointing gains have no recoverable design/Floquet provenance.
`magnetic_gain_manifest.json` records a compatibility baseline with plant, orbit,
epoch, frames, dataset and gain hashes; it does **not** certify those gains.
Configuration/artifact mismatches are rejected. The shipped
`simulation.allow_unverified_magnetic_gains: true` explicitly preserves historical
legacy operation and emits a warning. Set it false to require verified designs.
The magnetic target deliberately remains fixed on the configured epoch Sun;
reaction-wheel Sun targets track the current Sun. A new gain design requires its
own reproducible generator and validation evidence, not relabeling this baseline.

For an isolated timing check, run
`.venv/Scripts/python.exe -B validation/tools/benchmark_sitl_timing.py --duration 30`.
Add `--unpaced` to measure CPU headroom. This harness starts with nonzero tumble
rates and uses private UDP ports; it does not execute or validate external firmware.
The model list reports whether accelerated facet shadows are active. Restart the
simulator after code changes; the normal launcher intentionally has no autoreloader.

SITL honors both `sun_sensor.enable_albedo` and `enable_fine_albedo` (enabled in
the shipped configuration). Fine-head albedo integrates the extended illuminated
Earth disk through each head's optical window. It does not concentrate a coarse
cell's hemispheric light into a single Earth-center spot. Reflected light can
still produce eligible fine readings; firmware must resolve contradictory heads.
Sensor markers exaggerate faint light for visibility, transitioning from grey
through yellow to orange at high received light, without changing sensor counts.
Markers use the same light percentages as the Sun sensor table. Fine-only
telemetry falls back to quadrant counts with its configured noise envelope. Select
`sensor_profiles.sun_sensor: perfect` for ideal Sun readings without noise,
albedo or self-shadowing; `custom` uses the detailed switches below that section.
Changing a YAML profile requires restarting the simulator. In firmware mode,
tracker receipt validity follows the sensor clock, while its usage indicator
follows the firmware's reported reference. A stale firmware report is marked
as awaiting fresh status rather than displaying a stale usage indication.
Gyro presets and board magnetic calibration are
explicit `simulation.firmware_gyro_preset` (`adis16545` or `configured`) and
`firmware_board_magnetometer_calibration` settings. Restart after changing these
settings. The `firmware_sensor_configuration` telemetry records effective error
values, rates and albedo/shadow switches. Enabling albedo exposes the firmware to
reflected-light measurements; it does not assert that its estimator rejects them.

Python Sun targets use the Orekit DE ephemeris in EME2000. Live Sun RW/sweep
targets include navigated spacecraft position; sensor truth uses true spacecraft
position. The initial orbit is unchanged: true anomaly 180 degrees. Commit
`c775cb51` changed it from 0 to 180 degrees, reversing the starting side of the
circular orbit for the same RAAN. RAAN alone does not determine eclipse or the
Sun-relative starting side; epoch, argument of perigee and true anomaly matter.

Sun-head shadowing first checks configured blocker envelopes. Blockers with
`sensor_model_node` also use triangles from the configured GLB, preserving real
openings. The engine contains generic geometry code only. Generated trees live in
ignored `.cache/model-occlusion`, keyed by source content, node selector and unit
scale. Replacing a model invalidates its cache automatically. Normal startup
prepares missing caches; no satellite-specific builder or engine data is needed.
The standard setup's Node/frontend dependencies are needed for first preparation;
warm runtime ray tests use NumPy only. An optional warmup command remains
`.venv/Scripts/python.exe -B validation/geometry/build_occluders.py`.

### Replacing a satellite with two YAML files and root GLBs

Place your two GLBs beside `satellite_parameters.yaml` and
`advanced_satellite_parameters.yaml`. Edit each selected configuration, for example:

```yaml
# advanced_satellite_parameters.yaml: configurations.stowed.spacecraft
model_file: MySatellite-stowed.glb
model_scale_to_m: 1.0        # Use 0.001 for millimetre geometry
model_recenter: false       # Sensor geometry uses the CAD body-frame origin
star_tracker_model_node: MyTrackerBaffle  # Optional unique CAD node name/suffix
```

Use the corresponding deployed filename under `configurations.deployed`.
`model_file` is relative to the YAML directory; the viewer serves that configured
file automatically, so no move into frontend assets or Python edit is required.
The root-file workflow accepts GLB 2.0 with uncompressed or meshopt geometry for
sensor shadows. Convert STEP/STL to GLB; Draco-compressed sensor geometry must be
exported uncompressed or with meshopt. Node hierarchy, transforms, unit scale,
multiple primitives and sparse/interleaved accessors are handled during import.
A `sensor_model_node` identifies the occluding mesh/group in a blocker definition;
its envelope and all sensor positions remain body-frame SI values in YAML.

Update mass, inertia, force facets/optics, wheel axes and sensor mounts/error
settings in the two YAML files for the new satellite. Geometry alone cannot
supply those physical/calibration values. `firmware_axis_matrix_body` explicitly
defines the external firmware's wheel numbering; an empty value uses the physical
wheel geometry. External firmware retains its own hardware configuration and must
match the selected satellite. Restart after changing model/physics configuration.

Sun markers follow the same received-light percentages shown in the telemetry
table, even outside the fine head's angle-measurement window. Zero is opaque
grey; increasing light moves smoothly through yellow (50%) to orange (100%).
Fine-head Q sum is used only when photocell percentages are unavailable.
Eligibility does not force a marker to full brightness. `enable_albedo` is the
master reflected-light switch; `enable_fine_albedo` gates its fine-head subset.
`albedo_scale` is Earth reflectivity, not a second illumination contribution.

The performance brief's allocation/lifecycle items are also addressed by bounded
live GPS diagnostics, an eight-entry time/PV-keyed environment cache, disposal of
replaced/stale viewer models, and reuse of marker vectors/colors. Java environment
queries are cached independently of attitude; facet forces are still evaluated
for the actual attitude. Validation checks state/time cache keys and a synthetic
replacement satellite loaded from root GLBs and the two YAML files.

For the 10 ms firmware intervals, attitude integration uses adaptive RK23 with
the existing absolute/relative error tolerances and an initial step equal to the
interval. Legacy integration continues using RK45. The scalar cross product and
facet slab intersections avoid unnecessary NumPy temporaries. Regression checks
compare the firmware path against high-accuracy DOP853, retain real-time sample
boundaries, and verify that envelope visibility results are unchanged.

- Orbit (engine/ + engine_adcs_bridge.py): Orekit NumericalPropagator DOP853 -- central + EGM2008 Holmes-Featherstone, NRLMSISE-00 + CSSI weather, SRP + shadow. EngineOrbitProvider gives state, dense output, ECI/ECEF, Sun/Moon, IGRF, facet-coupled forces.
- Attitude: solve_ivp Euler + quaternion per 0.1 s tick; orbit segments extrapolate tick attitude; dense output resets at attitude updates.
- Disturbances: calculate_disturbances.py (GG, aero, SRP, residual dipole, per-channel switches); spacecraft_surface_physics.py unifies facet forces/moments for orbit + attitude + telemetry.
- Headless proof: python main.py -- engine-full vs raw-Orekit ~0 m; Kepler-only tens of km; EGM-only hundreds of m (24 h).

---

## 9. Sensors & Navigation

| Chain | Truth -> Measurement -> Belief |
|-------|-------------------------------|
| GPS | simulate_gps.py (bias/wander/noise/latency/dropouts ~1 Hz) -> compute_simulated_position.py (ECI pos/vel + dead-reckoning). Only ADCS knowledge is GPS-based. |
| IMU | simulate_gyroscope.py / simulate_magnetometer.py (mounts, bias walk, noise, quant) -> compute_simulated_attitude.py (sunlight-gated MEKF). Mounts are configured only in backend YAML. See imu_README.md. |
| Sun | simulate_sunsensor.py (6 faces, 90 deg FOV, albedo, penumbra, self-shadowing) -> vector solution (min 3 cells). |

---

## 10. Actuators

- Reaction wheels (torque_distribution.py): tetra 4-wheel array, 55 deg wedge, pseudo-inverse + null-space desat. dh/dt = -T, inertia 5.4e-5 kg-m2.
- Magnetorquers (MTR_allocator.py, cross_b_torque.py): B-cross allocator; dipole quant 0.1 A-m2, 2 Hz ZOH; published as dipole x true_body_field.
- Limits defined once under spacecraft: in YAML, inherited by control + allocation.

---

## 11. Firmware SITL (Hardware-in-the-Loop)

pointing.strategy: firmware_sitl -- real firmware owns arbitration over non-blocking UDP (polled per tick, held through RK stages):

| Direction | Port | Format | Contents |
|-----------|------|--------|----------|
| In (wheels) | UDP 5104 | 3d (24 B) | wheel idx 0-3, mode 0, torque mNm |
| In (MTQ) | UDP 5105 | B3f (13 B) | ADS mode + dipole X/Y/Z A-m2 |
| Out (state) | UDP 5002 | 17d (136 B) | ECI pos/vel, quat, rate rad/s, UTC sim-time, body B-field T |
| Out (wheels) | UDP 5103 | 4x 3d | wheel idx, speed rpm, torque mNm per tick |

Status dots: red = no packet for 2 s, green = 2 s after connect or mode change, yellow = working. Tests: `validation/test_firmware_sitl.py`.

---

## 12. Web Viewer & Telemetry API

Flask serves frontend/dist/index.html + /frontend/* + /assets/*. Browser polls only /api/latest (gzip + ETag).

| Route | Methods | Purpose |
|-------|---------|---------|
| /api/latest | GET | Latest bundled telemetry (only continuous poll) |
| /update_telemetry | POST | Separate-process ingestion (compat) |
| /api/viewer/config | GET | Model, lighting, pointing bootstrap |
| /api/spacecraft | GET | Mass, model URL, config, COM |
| /api/pointing | GET, POST | Reference state; quat input (custom only) |
| /update/mode | POST | Mode command (strategy-gated) |
| /update/control/inputs | POST | Legacy yaw/pitch/roll sliders |
| /rw_telemetry, /mtr_telemetry | GET | Compat readouts (not polled) |
| / | GET | Built React app |
| /frontend/:path | GET | Compiled assets |
| /assets/:path | GET | Models, imagery, reference video |
| /ground/track/no/yaw/steering | GET | Compat redirect |

Viewer: worker CAD batching, GPU diagrams w/ async readback, 30-s chart windows, Earth/aurora/clouds, GSAP cosmic-zoom video, Overview/Sensors/Pointing pages. Details: frontend/README.md.

---

## 13. Validation & Tests

```powershell
python -m pytest validation/ -q
python -m pytest validation/test_spacecraft_configurations.py validation/test_sensor_navigation.py validation/test_dashboard_telemetry.py -q
python validation/tools/verify_cad_physics.py deployed
python validation/tools/verify_cad_physics.py stowed
cd frontend; npm.cmd test
```

Browser/GPU (needs Chrome): terminal 1 -- python validation/tools/viewer_test_server.py; terminal 2 -- cd frontend; npm.cmd run test:browser. Orbit proof: python main.py.

---

## 14. CAD Pipeline

Requires cadquery-ocp, numpy, trimesh, pyyaml (+ gltf-transform CLI):

```powershell
python validation/tools/export_satellite_cad.py '../P-30XL Deployed 22-09-2026.STEP' deployed
python validation/tools/export_satellite_cad.py '../P-30XL Stoved 22-09-2026.STEP' stowed
npm.cmd install --prefix .tools/gltf @gltf-transform/cli
node validation/tools/extract_cad_mounts.mjs
python validation/tools/build_cad_configurations.py
```

Compress each GLB with gltf-transform meshopt (pos quant 16-bit). Physics uses a rectangular bus/panel macromodel from CAD bounds. Full notes: CAD_CONFIGURATION.md.

---

## 15. Troubleshooting

| Symptom | Fix |
|---------|-----|
| PS script blocked | Use Setup.bat (passes -ExecutionPolicy Bypass). |
| Python 3.12 not found | Install python.org 3.12 64-bit with py launcher. |
| port 5000 busy | Kill leftover python.exe via Task Manager. |
| JVM / Orekit crash | Force JDK 21: $env:JAVA_HOME = (python -c "import jdk4py; print(jdk4py.JAVA_HOME)"). Never JDK 25. |
| Viewer 503 | frontend/dist missing -- rebuild frontend. |
| Charts frozen | Physics warming up; check simulation_lag_s in /api/latest. |
| Edits invisible | YAML needs restart (except speed); viewer needs rebuild + Ctrl+Shift+R. |
| orekit-data/ missing | Re-extract zip or download orekit-data-main.zip as orekit-data/. |
| SITL red dot | No UDP 2 s -- check firmware, firewall, ports 5104/5105/5002/5103. |

Logs: setup.log, Flask console + browser devtools, hs_err_pid*.log (JVM).

---

## 16. Additional Documentation

- frontend/README.md -- viewer architecture, dev/build, perf.
- CAD_CONFIGURATION.md -- deployed/stowed physics + mass properties.
- GPS_DIAGRAM_INTEGRATION.md -- viewer GPS contract.
- imu_README.md -- IMU emulation + MEKF.
- frontend/assets/textures/README.md -- texture credits.
- CLAUDE.md -- full ADCS study (LTP diagnosis, periodic-LQR, validation).
- validation/README.md -- suite map.

---

## 17. Credits & License

Made by **Chirag Malik** -- malikchirag.2005@gmail.com -- [LinkedIn: malikchirag](https://linkedin.com/in/malikchirag) for Dhruva Space.

CAD STEP files, GLBs, textures, and reference footage retain their original licenses. Orekit by the Orekit community; 3D via Three.js, animation via GSAP. Please credit the author when reusing.

---
*Config changed? Restart (except simulation.speed). Viewer changed? Rebuild + hard-refresh. Happy flying.*
