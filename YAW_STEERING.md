Yaw steering is firmware mode **12**. COSMOS selects it; the Python simulator
stays in `FIRMWARE_SITL` and applies the firmware's actuator commands.

The steering calculation is the `calculate_desired_yaw_angle()` function called
by the supplied `satellite_rotational_dynamics_yaw_steering.py`. It uses the same
Earth rotation rate, `7.2921159e-5 rad/s`, and keeps the original angle sign.
The alternative `calculate_yaw_steering_ephemeris()` function is not called by
that supplied dynamics script and is not used here.

Our existing nadir frame is retained: body +X faces Earth, body +Y is opposite
the orbit normal, and body +Z completes the frame. The supplied yaw angle turns
around body +X. No axis in the simulator, sensor model, or firmware was renamed.
The supplied scripts' initial 30-degree roll and orbit/plotting settings are
scenario settings; they are not imposed on this new mode.

To run it:

1. In `satellite_parameters.yaml`, set `pointing.strategy: firmware_sitl`.
   Your existing YAML selection was left untouched.
2. Start `Firmware/ACS/sitl_acs.exe` and the updated `Firmware/ADS/sitl_ads.exe`
   from `C:/Projects/Sim/ADCS_SITL`, using your existing launch procedure.
3. Restart COSMOS Command and Telemetry Server and Command Sender to load
   the updated active ADS target definitions in
   `C:/Cosmos/P30_COSMOS_C3/Demo/config/targets/ADS/cmd_tlm`.
   The repository copies in
   `C:/Projects/Firmware/Leap_2_ADCS_Firmware_V1/cosmos` are updated too.
4. Connect COSMOS to ADS as usual, then start the simulator with
   `.venv/Scripts/python.exe run_simulator.py`.
5. Allow the normal sensor and actuator startup to finish. In Command Sender,
   choose target `ADS`, command `YawSteering`, and Send. Alternatively send
   `ADS ChangeMode`, choosing `Mode = Yaw_steering` (numeric value **12**).
6. The simulator should report `YawSteering`. Its pointing card shows the
   steering offset and full orientation error. `ADS YawSteeringVarsPkt` reads
   the angle, target quaternion, target rate, error, torque, and validity.
7. Send `ADS ChangeMode` with `Sun_point` or `Nadir_point` to leave the mode.

Files added in the SITL firmware (`C:/Projects/Sim/ADCS_SITL/Firmware/ADS`):

| File | What it does |
|---|---|
| `Src/Guidance/yaw_steering/yaw_steering.c` | Supplied yaw formula, our nadir target, and target turning rate |
| `Inc/Guidance/yaw_steering/yaw_steering.h` | Declares the guidance outputs |
| `Src/control/yaw_steering/yaw_steering_control.c` | Existing style of wheel controller, allocation, and desaturation |
| `Inc/control/yaw_steering/yaw_steering_control.h` | Declares the controller functions |

Existing firmware files updated:

| File | Change |
|---|---|
| `Inc/base_shared.h` | Adds mode 12; existing mode numbers stay unchanged |
| `Inc/control/control_defaults.h` | Separate yaw-steering gain constants, initially matching nominal in-orbit |
| `Inc/control/state_machine.h` | Adds yaw-steering state and request event without shifting existing real state/event numbers |
| `Src/control/state_machine.c` | Activates the controller and handles exit, unusable navigation, and wheel faults |
| `Src/control/control_loop.c` | Computes the guidance and torque each cycle |
| `Src/architecture/cmd_handler.c` | Accepts mode 12 and returns the new variables packet |
| `Inc/command/command.h` | Adds variables-packet opcode 250 |

The state machine also gets its missing `propagator/tle_seed.h` include, needed
to declare the existing navigation availability function when rebuilding.
ACS needs no source change: it already carries the wheel and torquer commands.
The separate flight-board repository was not modified; this implements the
requested simulator-connected SITL firmware.

Simulator files:

| File | Change |
|---|---|
| `yaw_steering.py` | Matching Python reference target for display and verification |
| `firmware_sitl_link.py` | Recognizes mode 12 as `YawSteering` |
| `firmware_sitl_adapter.py` | Allows settling to be checked relative to a moving target's rate |
| `satellite_flight_visualisation.py` | Publishes steering angle, complete orientation error, nadir error, and target angles |
| `frontend/src/viewer/SimulationEngine.js` | Recognizes the mode, target display, wheel panel, and nadir guide |
| `frontend/src/components/PointingControls/PointingControls.jsx` | Shows the steering offset and error |
| `frontend/src/services/formatTelemetry.js` | Readable mode label |

The COSMOS command and telemetry definition files add `Yaw_steering = 12` and
`YawSteeringVarsPkt` / `YawSteeringVars` (opcode 250, 121-byte payload). The new
debug request event is 49; the event wildcard moves to 50. Existing usable
event numbers remain unchanged.

Rebuild from the simulator directory:

```powershell
.venv\Scripts\python.exe validation\tools\build_firmware_sitl.py
```

The result is `.cache/yaw_steering/sitl_ads.exe`. Close the running ADS process
before replacing `Firmware/ADS/sitl_ads.exe` with that result. The build helper
uses MinGW gcc and the existing SITL replacements for hardware-only drivers.

Verification:

```powershell
.venv\Scripts\python.exe -m pytest validation\test_yaw_steering.py validation\test_firmware_sitl.py validation\test_firmware_causality.py -q -p no:faulthandler
cd frontend
npm.cmd test
npm.cmd run build
```

The new tests compile the actual C code. They check the original supplied
formula, C/Python agreement across 150 orbital orientations, +X nadir
preservation, target-rate agreement, invalid inputs, mode transitions, the
COSMOS-format TCP command and telemetry packet, and 6,000 seconds of wheel
tracking. The long tracking test uses ideal attitude measurements and no
disturbances; its result is not an accuracy guarantee for noisy sensor runs.

`validation/tools/run_yaw_sitl_smoke.py` separately starts real ADS and ACS
processes on temporary ports 15001–15105 and runs 18 seconds of the normal noisy simulator. Its initial
attitude starts near the target to check the complete connection. It requires
those temporary ports to be free and stops only the processes it starts.
Results and build logs are written under `.cache/yaw_steering`.

Recorded results on 5 November 2026: 21 Python tests and 16 frontend tests
passed, and the frontend production build passed. The 6,000-second ideal
tracking test's maximum error after 400 seconds was 0.0344 degrees, with peak
wheel speed 626 RPM. The separate 18-second noisy end-to-end check ended in
`YawSteering` with 0.0597 degrees orientation error. This short run checks
integration; it does not establish long-duration accuracy with noisy sensors.
