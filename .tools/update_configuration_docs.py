from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=root/'CAD_CONFIGURATION.md';t=p.read_text(encoding='utf-8')
start=t.index('Select the run');end=t.index('| Report / CAD',start)
t=t[:start]+'''The basic file `satellite_parameters.yaml` contains shared simulation settings
and the previous legacy assumptions. Set its top-level switch:

```yaml
use_advanced_satellite_model: true  # false uses the basic legacy model
```

When enabled, select deployment at the top of `advanced_satellite_parameters.yaml`:

```yaml
panels_deployed: true  # true=open/deployed; false=closed/stowed
```

Restart after changing either file. The advanced file retains only runtime CAD
mass, COM, inertia, exterior surfaces, blockers, active sensor mounts and wheel
axes. Unused origin-inertia reports, principal-axis tables, and duplicate hardware
records were removed from the editable configuration. Component-level records
remain in the existing CAD inventories, not in the basic settings.

Advanced mode overrides mass, inertia, geometry, sun-sensor/gyro mounts and wheel
axes together. Shared noise/calibration, controller settings and actuator limits
stay in the basic file. The viewer follows the simulator model URL and COM.

Legacy mode uses the original viewer GLB, 6 kg orbit/SRP mass assumption,
diagonal inertia [1.465, 1.176, 1.244] kg m², and a centered 0.3 m optical cube.
It retains the corrected force/torque coupling. A centered uniform cube has zero
SRP/drag moment through symmetry; that is physically expected. The basic legacy
panel flag labels its fixed geometry and does not articulate the original GLB.

The basic YAML now groups model selection, spacecraft, orbit, attitude,
environment data, controller tuning/sweeps, disturbance switches, optical
geometry, wheel allocation, execution, GPS, IMU/sun sensors and viewer lighting.
The mounting override mapping remains last so viewer save-defaults preserves
all configuration documentation. Active epoch, PD tuning, slew/sweep rates,
target-rate finite-difference step, SRP pressure/switches and wheel reallocation
settings are read from these groups rather than duplicated across modules.
Wheel null-space direction is calculated from the selected wheel-axis matrix.
Physical constants, ephemeris coefficient tables and numerical safeguards remain
in code. Stored periodic-LQR gains remain an offline design artifact; editing
YAML does not redesign that controller.

'''+t[end:]
t=t.replace('The raw positive products, rounded principal directions, principal moments and\norigin inertia are retained in each record\'s `provenance`. Rounded principal\ndirections are not used to rotate the spacecraft.',
 'Unused report tables have been removed from the runtime YAML. Rounded principal\ndirections are not used to rotate the spacecraft.')
t=t.replace('hardware inventory/provenance','hardware inventory')
t=t.replace('Each is preserved independently;', 'Each mass is preserved independently;')
t += '''
## Surface physics and GPS reception

`spacecraft_surface_physics.py` converts the selected exterior surfaces and current
attitude/environment into SRP and drag forces plus their moments about COM.
It handles incidence, reflection, shadows, eclipse and lever arms once, so orbit,
attitude and telemetry use the same result. It does not render CAD or simulate GPS
radio signals. Earth display brightness is independent of this physics.

See [GPS_DIAGRAM_INTEGRATION.md](GPS_DIAGRAM_INTEGRATION.md) for the existing viewer
contract and the constellation, reception and per-channel measurement integration
needed to display actual received GPS data.
'''
p.write_text(t,encoding='utf-8')
