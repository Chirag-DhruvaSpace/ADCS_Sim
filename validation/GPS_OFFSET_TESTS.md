# GPS position and velocity offset tests

Edit the existing entries in `satellite_parameters.yaml`, then restart the simulator.
Do not add a second `gps` or `sensor_profiles` section.

Set `sensor_profiles.gps: custom`. For firmware-filter testing, also select
`pointing.strategy: firmware_sitl` and run the ADS/ACS SITL processes as usual.

Under `gps`, disable random errors so that the deterministic offset is isolated:

```yaml
  enabled: true
  update_rate_hz: 1.0
  enable_bias: false
  enable_wander: false
  enable_white_noise: false
  enable_steps: false
  enable_latency: false
  enable_dropout: false
  enable_clock_error: false
  enable_quantization: false
  enable_status: false
  cold_start_s: 0.0
  outages_s: []
  seed: 42

  fixed_position_offset_eci_m: [0.0, 0.0, 0.0]
  fixed_velocity_offset_eci_m_s: [0.0, 0.0, 0.0]
```

The explicit offsets are independent of `enable_bias`. That switch controls only
the existing random East/North/Up startup bias. The new vectors are constant,
signed EME2000/ECI `[X, Y, Z]` offsets, in metres and metres/second. They affect GPS
measurements, not simulator truth, spacecraft dynamics or the orbit propagator.

Use these proposed characterization values for the original six test cases:

| Case | `fixed_position_offset_eci_m` | `fixed_velocity_offset_eci_m_s` |
| --- | --- | --- |
| Baseline | `[0.0, 0.0, 0.0]` | `[0.0, 0.0, 0.0]` |
| GPS-001: X position | `[10.0, 0.0, 0.0]` | `[0.0, 0.0, 0.0]` |
| GPS-002: Y position | `[0.0, 10.0, 0.0]` | `[0.0, 0.0, 0.0]` |
| GPS-003: Z position | `[0.0, 0.0, 10.0]` | `[0.0, 0.0, 0.0]` |
| GPS-004: X velocity | `[0.0, 0.0, 0.0]` | `[0.1, 0.0, 0.0]` |
| GPS-005: Y velocity | `[0.0, 0.0, 0.0]` | `[0.0, 0.1, 0.0]` |
| GPS-006: Z velocity | `[0.0, 0.0, 0.0]` | `[0.0, 0.0, 0.1]` |
| Combined | `[10.0, -20.0, 30.0]` | `[0.1, -0.2, 0.3]` |

Start a fresh simulator and firmware run for each row, with the same orbit,
initial conditions and seed. Negative values inject negative offsets. Restore
both vectors to zero after testing. Non-custom GPS profiles explicitly reset
both offsets to zero, so `perfect`, `nominal`, `degraded`, `stress` and `off`
cannot accidentally retain a previous custom test offset. The GPS master switch
still disables all receipts.

## What to measure

1. Compare raw GPS converted back to ECI with independent orbit truth at the
   measurement epoch. Before encoding, the difference should equal the configured
   offset on the selected axes, with zero additional error on the other axes.
2. ORION integer fields always round ECEF position to 0.01 m and ECEF velocity to
   0.01 m/s, even with `enable_quantization: false`. Allow for that wire-level
   resolution: up to approximately 0.009 m or 0.009 m/s on a recovered ECI axis
   with all other errors off. This allowance describes encoding only, not a
   mission filter-accuracy requirement. The full rotating-frame PV transform
   keeps a position-only ECI offset from adding an unintended ECI velocity offset.
3. Capture firmware raw, predicted and filtered states for the same update and
   verify `filtered = predicted + K_fixed * (raw - predicted)`. The filtered
   error is not expected to equal the injected raw offset. Compare with the
   matched zero-offset baseline; a startup constant offset may also affect how
   the firmware initializes its predicted orbit.
4. `SimulatedGPS.records` retains unmodified truth, measured ECEF states, total
   local error and the two configured offset vectors for diagnostic scripts.
   This is simulator diagnostic data, not a new firmware packet or UI control.

If latency is enabled, compare against truth at `t_meas_s`, not arrival time.
If other error channels are enabled, the deterministic offsets add to them.
Use offsets representable by the ORION signed integer fields; unrepresentable
values are rejected by the existing encoder.

## Automated checks

From `Satellite/ADCS_Sim`, using its Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:faulthandler validation/test_gps_fixed_offsets.py -q
```

The tests cover signed individual axes, combined offsets, real Orekit rotating
frames over several epochs, truth preservation, packet encoding and firmware
sensor-link layout, invalid configuration, profile resets, disabled GPS, old
YAML compatibility, and coexistence with seeded random errors and latency.
