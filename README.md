<!-- made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag -->
# Leap2_MBD_Simulation

See [CAD configuration and disturbance physics](CAD_CONFIGURATION.md) for the
deployed/stowed selector, supplied mass properties, CAD exports and validation.

Build the React frontend first: `cd frontend`, `npm.cmd install`, `npm.cmd run build`, then `cd ..`.
Run `.venv/Scripts/python.exe run_simulator.py` and open http://127.0.0.1:5000.
Use Java 21 (`JAVA_HOME`), required by the installed Orekit/JPype runtime.

<!-- made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag -->
The active frontend is the JavaScript/CSS Vite React app in [`frontend`](frontend/README.md).
It keeps the current UI and viewer animations. See that README for the folder structure,
development server, production build, performance limits and regression checks.

The top of `satellite_parameters.yaml` selects `pointing.strategy: legacy` or
`custom`. Legacy keeps the existing mode selector. Custom accepts scalar-first
body-to-ECI quaternions through `pointing.custom` or the real-time client:

```python
from pointing_client import send_pointing_input
send_pointing_input([1, 0, 0, 0])
# Error convention: inverse(desired) * reference.
send_pointing_input(q_error, quaternion_error=True, reference_quaternion=q_reference)
```

Restart after YAML changes. Sensor profiles are independently selectable there.

Overview uses the wheel to scrub the user's supplied space-zoom footage. The
close Earth remains the live 3D model, with elevated animated auroral curtains;
the original simulation sky stays visible until the camera turn. During that turn it fades into the reference-image celestial sphere; reverse scrolling restores the original sky. The transition to footage
occurs after Earth becomes tiny. Reverse scrolling returns to the live
Earth. The HUD slides out beyond the solar system and slides back when reversing. The footage keeps its
original 3840 × 1664 resolution and 30 fps; it has frequent keyframes for seeking.
The distant footage has a recorded camera path, so dragging there does not
change its camera. Flight physics and simulation time remain independent.
Restart the server and hard-refresh the browser after updating the viewer.

The main viewer batches CAD on a Web Worker, and attitude diagrams share the
resulting geometry and GPU buffers. Their full-resolution offscreen images use asynchronous WebGL2 pixel readback; unchanged diagrams reuse their last image. CAD and diagram textures are warmed during model loading. No vertices or triangles are removed. Charts retain
only the last 30 simulation seconds and clear their canvas before each redraw.

The distant imagery is the supplied reference, rather than a new scientific
propagation model. Display distances are calibrated to its shot progression,
not recovered camera metadata. Its galaxy is retained rather than replaced
with a less convincing synthetic model.
Textures and licensing are listed in [the texture credits](frontend/assets/textures/README.md).

Overview uses one GSAP scrub tween (0.18 seconds, overwritten on each wheel input) and paused, latest-position video seeking. The close view retains the original simulation sky. Its transition to the reference sky shares the camera rotation interval (reference seconds 78 to 89), with no independent animation queue. Only the distant footage uses a full-viewport cover crop, fading in when Earth is tiny. Footage is never wrapped, mirrored or projected into a simulated 3D starfield. Close Earth rotation remains available; distant footage follows its recorded camera.

During the final Earth pullback the camera turns toward the sunward side of Earth, keeping the live Sun behind the camera before the video handoff. The celestial sphere uses one continuous extension of the supplied reference image; it no longer blends a rectangular reference patch into a different Milky Way map.

The reference sky omits its baked-in tiny Earth/Moon so the live globe is not duplicated. The final pullback matches the measured globe centre and apparent size before the footage fades in (reference seconds 95 to 97). Fully opaque footage draws only its video plane. Switching tabs uses a smooth camera flight with logarithmic distance interpolation; telemetry diagrams retain their last image during the flight, then draw the newest sample. The complete orbital-context card, including Sun/Moon distances, hides at astronomical zoom.

Overview retains the live spacecraft orbit through the globe pullback and does not add an Earth label. Reference sky shaders always write background depth, preventing the sky from tinting Earth at the floating-coordinate handoff. Tab flights capture their starting offset relative to the spacecraft once and interpolate model scale with camera distance. Telemetry diagrams draw into staging canvases and replace their visible image only after GPU readback and labels complete.

## Simulation speed

Set `simulation.speed` in `satellite_parameters.yaml` (reloaded while running, at most once per real second): `1.0`
means one Orekit simulation second per real second, `2.0` means twice that
rate. The older `simulation.realtime` field is retained for configuration
compatibility; `speed` now controls pacing. Absolute monotonic deadlines avoid
clock corrections and accumulated per-step sleep drift. Orekit elapsed time
remains authoritative; physical control steps and solver tolerances are unchanged.
Telemetry publication remains limited by `telemetry_publish_period_s` in real
seconds, independently of speed. The viewer interpolates position along orbital
arcs and attitude with quaternion interpolation; active charts redraw at most 2 Hz.

If physics cannot keep up, no physical integration steps are skipped or fabricated.
`/api/latest` exposes `simulation_speed_requested`, `simulation_speed_actual`,
and `simulation_lag_s` to diagnose that computational limit. High speed settings
cannot guarantee real-time accuracy on hardware unable to calculate the requested
number of steps. The frontend still renders independently of the physics loop.

## Firmware SITL input

`pointing.strategy: firmware_sitl` selects external actuator control. The unchanged
`firmware_sitl_link.py` and `telemetry.py` are copied from the supplied files.
`firmware_sitl_adapter.py` polls their nonblocking UDP receivers once per control
tick, holds the commands through the RK stages, and retains environmental forces.
Python pointing laws and its automatic detumble override do not run in this mode;
the real firmware owns control-mode arbitration. Legacy and custom strategies
remain available for compatibility. Quaternion HTTP commands are rejected while
firmware control is selected.

- UDP 5104 input: `<3d` = wheel index 0..3, command mode 0, torque in mNm (24 bytes).
- UDP 5105 input: `<B3f` = ADS mode byte and body dipole x/y/z in A m^2 (13 bytes).
- UDP 5002 output: `<17d` = ECI position/velocity, scalar-first quaternion,
  body rate in rad/s, Unix UTC simulation time, body magnetic field in tesla
  (136 bytes). The copied file's older header says 13 doubles; its function sends 17.
- UDP 5103 output: four `<3d` wheel index, speed rpm, torque mNm packets per tick.

RW mNm is converted to Nm once before `A @ wheel_torque`; magnetic torque uses
`dipole x true_field_body`. The copied module's wheel-speed bookkeeping is kept,
with its `dh/dt = -T` sign and inertia 5.4e-5 kg m^2. It does not model electrical
wheel hardware; wheel-speed input commands are unsupported in the supplied module.
Current telemetry is not invented from the pre-driver dipole packet.

Status dots indicate red when no packet has arrived for two real seconds, green
for two seconds after connection or an ADS mode change, yellow while working,
and blue after a known NadirPoint/Sunpoint geometric error <0.5 degrees and rate
<0.05 deg/s remain settled for a simulated second. Repeated actuator packets do
not restart the green timer. Other target modes have no transmitted reference
quaternion, so their target error and settled state cannot be inferred.
The supplied modules hold the last actuator command between packets; a red
indicator does not zero that command. Launch with `python run_simulator.py` and
run the matching ADS/ACS firmware separately. For accelerated closed-loop SITL,
the firmware must use the transmitted simulation time consistently; this repo
cannot verify a firmware clock without its C code/binary.

The live browser polls only `/api/latest`; bootstrap and mount/settings routes
are on-demand. Old actuator endpoints remain compatibility routes, with no
independent browser polling. HTTP route count itself is not a physics cost.

`simulation.orbit_output_window_s: 0.5` computes bounded half-second orbital
segments with the same Orekit forces and solver tolerances, then samples native
DOP853 dense output at each 0.1-second ADCS tick. This reduces repeated integration
startup work; it does not skip sensor, attitude or firmware-control ticks. Coupled
facet forces use the existing attitude/rate predictor over the segment. A short
10-second comparison found a maximum position difference of 5.42e-8 m against
0.1-second propagation, below the configured 0.001 m scalar solver tolerance;
this is a test case, not a bound for every maneuver. Set the window to `0.1` to
restore the original immediate orbit/attitude coupling. Restart after changing
this window. Ephemeris memory is bounded to the current window.


### Viewer motion and exact shadow-work reduction

Workspace tabs now retain outgoing instruments briefly for a fade, while immediately
stopping their subscriptions. Eye mode retains the active page layout offscreen and
suspends updates, so restoring it produces a real slide-in instead of a display jump.
The clock and action buttons remain visible. Settings open/close transitions can be
reversed without leaving stale animations. Reduced-motion preferences are respected.
Auroras use one fragmented animated oval in each hemisphere, with reduced brightness
and geometry; daytime visibility is faint rather than abruptly clipped.

Facet shadow tests now skip only patches whose projected area is zero. All contributing
rays retain the original slab intersection arithmetic. Randomized comparisons verify
bit-for-bit identical forces and torques. The control period, solver tolerances, force
models, sensor sampling and YAML parameters are unchanged by this optimization.

There are 15 HTTP routes (HEAD/OPTIONS omitted):

| Route | Methods | Purpose |
| --- | --- | --- |
| `/api/latest` | GET | Latest bundled telemetry; the only continuous viewer poll |
| `/update_telemetry` | POST | Separate-process telemetry ingestion and command receipt |
| `/api/viewer/config` | GET | Initial model, lighting and pointing configuration |
| `/api/spacecraft` | GET | Mass, model, configuration and centre of mass |
| `/api/imu/mounts` | GET, POST | Read or apply sensor mounting |
| `/api/imu/defaults` | POST | Save mounting defaults to YAML |
| `/api/pointing` | GET, POST | Read reference state; quaternion input only with custom strategy |
| `/update/mode` | POST | Legacy/custom mode commands, subject to configured strategy |
| `/update/control/inputs` | POST | Legacy yaw/pitch/roll inputs |
| `/rw_telemetry` | GET | Compatibility wheel torque readout; not polled by current viewer |
| `/mtr_telemetry` | GET | Compatibility magnetic torque/dipole/current readout; not polled |
| `/` | GET | Built React application |
| `/frontend/<path:filename>` | GET | Compiled frontend assets |
| `/assets/<path:filename>` | GET | Models, imagery and reference video |
| `/ground/track/no/yaw/steering` | GET | Compatibility redirect to the viewer |

`showSun`, `showGyro` and `showMag` settings control marker visibility. Physical sensor
activation is configured under `gps_sim` and `imu_sim` in YAML. Hiding markers does not
remove physical sensor, force or orbit computation. The shared-process launcher avoids
HTTP telemetry delivery; only the compatibility separate-process path uses it.
