# Mission telemetry dashboard

The viewer opens on Overview. Sensors and Pointing change only the overlay; they do not change the Three.js camera, control mode, attitude, quality settings, or stream settings. The header shows the timestamp of the last received simulation sample and measured render FPS. After five seconds without a new sample, it explicitly reports that the last sample is being held.

The desktop arrangement follows the supplied references: narrow overview side panels with orbital context; GPS, gyro and magnetometer cards opposite the Sun array and a wide estimator card; pointing controls above error/rate/acceleration graphs and an actuator/disturbance strip. Smaller laptops use compact spacing and scrollable rails. Mobile stacks the same live panels while keeping the simulation behind them. The selected header tab slides, panel entrances animate, and reduced-motion preferences disable these animations.

## Data contract

All numeric flight values come from `/api/latest`, or are explicit unit conversions/differences of fields in the same snapshot. No example values, random chart generators or simulated UI timers are used. `dashboard_telemetry.py` adds display fields without changing or feeding back into the physics or controllers.

| Display | Source |
| --- | --- |
| Date/time | `timestamp` (UTC) |
| FPS | Existing Three.js frame counter |
| Position/speed | `latitude_deg`, `longitude_deg`, `altitude_m`, `satellite_position_ecef_m`, `satellite_speed_m_s` |
| Orbit curve | `orbit_path_ecef_m` from the propagated state |
| Earth/Sun/Moon diagram | Earth-fixed satellite/Sun/Moon vectors at the snapshot timestamp |
| GPS | Receiver status, fix coordinates, PDOP, accuracy and latency fields |
| GPS belief error | Norm of `gps_pos_eci_* - truth_pos_eci_*`, metres |
| Gyro | `imu_gyro_*_rad_s` converted to degrees/s; compared with `body_rate_*` |
| Magnetic field | `imu_mag_*_nT` compared with `truth_mag_body_*_nT` |
| Sun cells | `sun_arr_cells`; reconstruction/truth/error fields from the sensor model |
| Reconstructed Sun arrow | Body-frame reconstruction transformed by `body_to_ecef_matrix` |
| Attitude estimator | Published estimate/truth quaternions, Euler angles, angular error and update counters |
| Pointing | Mode-specific target and error fields; wrapped Euler differences are labeled separately |
| Actuators/disturbances | Same-tick MTR and wheel arrays, eclipse and disturbance values |
| Orbital model labels | Backend configuration and active force classes |

GPS receiver simulation currently publishes aggregate SV counts and PDOP, not tracked PRNs or individual GNSS ephemerides. The GPS globe now draws up to four green *illustrative* links from a nominal constellation, with the reported count limiting them and PDOP affecting their spread. These markers are not actual receiver locks, and the UI labels them as simulated. A future provider may publish `gps_links_available: true` with `gps_satellites: [{prn, position_ecef_m: [x,y,z], used}]`; the widget then draws those reported markers and links. The current backend still reports that capability as unavailable.

Globe panels are schematic: marker sizes and Sun/Moon distances are compressed so they fit, with captions stating this. The overview's flat Sun–Earth–Moon positions are fixed for clarity; its spacecraft orbital phase and distance labels use backend coordinates. The Sun diagram is a Sun-aligned 2D cross-section with illumination from backend telemetry. The GPS globe uses one small WebGL context, with up to four simulated green links drawn on top. Only visible diagrams render, at no more than five refreshes per second. Both the main scene and the inset renderer import the vendored Three.js 0.160.0 package locally.

History contains at most 600 unique snapshots over a 120-second window. Repeated samples are ignored; session changes or backwards simulation time reset history. Missing/invalid sensor values produce gaps and unavailable labels. Gaps over five simulation seconds are not connected. Old truth values are not substituted for missing measurements.

## Verification

```
node scripts/test_dashboard_data.cjs
.venv/Scripts/python.exe -m unittest validation.test_dashboard_telemetry validation.test_sensor_navigation
.venv/Scripts/python.exe scripts/verify_sensor_changes.py --integration --dashboard-fixture "$env:TEMP/leap-dashboard-telemetry.json"
node scripts/browser_dashboard_check.cjs
node scripts/browser_sensor_check.cjs
node scripts/browser_visual_check.cjs
```

Browser checks use the existing Playwright installation in `%TEMP%/leap-viewer-check` and Chrome. The dashboard test replays actual snapshots captured by the live Orekit/ADCS integration. It checks values, graphs, unavailable GPS links, tab isolation, simulation-clock holding, settings, and layouts at 1614×975, 1366×768, 3840×2160, and 390×844. Screenshots are under `validation/results/dashboard-*.png`.
