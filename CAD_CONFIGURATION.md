# P-30XL deployed and stowed simulation

The basic file `satellite_parameters.yaml` contains shared simulation settings
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
Orbit DOP853 settings, attitude integration tolerances and telemetry endpoint/
timeout are grouped under `simulation`. Physical actuator limits are defined
once under `spacecraft` and inherited by control and allocation.
Wheel null-space direction is calculated from the selected wheel-axis matrix.
Physical constants, ephemeris coefficient tables and numerical safeguards remain
in code. Stored periodic-LQR gains remain an offline design artifact; editing
YAML does not redesign that controller.

| Report / CAD configuration | Mass | COM in CAD output axes, metres | Placed components |
|---|---:|---|---:|
| Stowed (`Stoved` source file) | 30.40 kg | (-0.01682, -0.01421, -0.12967) | 1,017 |
| Deployed | 27.29 kg | (-0.01855, -0.01489, -0.16821) | 1,025 |

The reports differ by 3.11 kg. Each mass is preserved independently; this is a
choice of initial spacecraft configuration, not an in-flight deployment event
that discards mass. Confirm the assembly inclusion lists before treating that
difference as a physical flight event.

The reports use kg mm² and SOLIDWORKS positive product-of-inertia notation.
The runtime matrix divides by 1e6 and negates off-diagonal products for Euler
dynamics. Its eigenvalues reproduce the independently reported principal moments.
Unused report tables have been removed from the runtime YAML. Rounded principal
directions are not used to rotate the spacecraft. See the
[SOLIDWORKS mass-property definitions](https://help.solidworks.com/2021/english/SolidWorks/sldworks/hidd_massproperty_text_dlg.htm?format=P&value=).

## CAD and visuals

`frontend/assets/models/P-30XL-deployed.glb` and `P-30XL-stowed.glb` preserve placed component
names and approximately 5.1 million tessellated triangles each. Meshopt compression
reduces the models to approximately 22 MB each. The matching `*-inventory.json`
files record each component's assembly path, bounds, center, material assignment
and triangle count. Mechanical sensor/wheel mounting directions are also recorded.
The render origin is the selected COM and the axes are the CAD output axes.

Materials distinguish aluminium structure, dark solar surfaces, green PCBs,
instrument housings and magnetorquer hardware. These are visual interpretations
of component labels, not measured optical properties. No component mass is
invented from a label or from an arbitrary material density.

Six FSS boards use their placed CAD locations and dominant planar-face normals;
the ±Y boards are tilted approximately 15 degrees. The ADIS16547 gyro uses its CAD
package location. Four RW060 wheel spindle directions are derived from planar
CAD faces and feed the allocator. Three SPPE113 magnetorquer and two GPS antenna
positions are retained in the hardware inventory. CAD labels do not
unambiguously identify the magnetometer chip, so its existing assumed mount stays
explicit. Supplier actuator limits and sensor noise/calibration remain the
existing configuration values; a CAD part name does not establish those values.

## Disturbance physics

`spacecraft_surface_physics.py` supplies both orbital force and body-frame torque.
SRP includes absorption, specular and Lambertian diffuse reflection, incidence,
inverse-square Sun distance, Orekit eclipse illumination, and moment arms from
facet position minus COM. Drag uses the same NRLMSISE-00 density and atmospheric
velocity as the orbit callback, projected area, Cd, and facet lever arms. The
separate isotropic orbit SRP/drag models are not registered in the ADCS provider.
Gravity gradient uses the same full inertia matrix as Euler dynamics; residual
dipole uses the true magnetic field. Net disturbance telemetry includes SRP,
drag, gravity gradient and residual dipole at the same published epoch.

The detailed CAD is used for rendering. Disturbance/shadow physics uses an
exterior rectangular bus/panel macromodel derived from CAD bounds, with 4×4
quadrature per face and ray/box occlusion. Internal parts, small appendage forces,
apertures, flexible panels, thermal recoil, detailed aerodynamic accommodation
and lift are not modeled. A covered sun-sensor cell remains valid and reports
self-shadowing. An aperture absent from the rectangular approximation may need
an explicit refined occluder before analyzing that sensor quantitatively.

Orbit/attitude integration is partitioned at the configured control tick (default
0.1 s). Orbit stages extrapolate the tick attitude with its true angular rate;
attitude stages recalculate incidence at their own quaternion with tick-sampled
environment data. Orekit dense output is reset at attitude updates so it cannot
reuse forces evaluated with an old orientation. Reduce the control period and
check convergence for faster tumbles or precision disturbance studies.

Optical coefficients and Cd are explicitly assumed. CAD does not supply sensor
calibration, residual magnetism, or qualified actuator limits. Existing controller
gains are retained; changing the spacecraft inertia does not constitute a new
controller stability qualification.

## Rebuild and verification

Run from the repository root with the CAD export dependencies installed:

```powershell
python scripts/export_satellite_cad.py '../P-30XL Deployed 22-09-2026.STEP' deployed
python scripts/export_satellite_cad.py '../P-30XL Stoved 22-09-2026.STEP' stowed
npm.cmd install --prefix .tools/gltf @gltf-transform/cli
node scripts/extract_cad_mounts.mjs
python scripts/build_cad_configurations.py
```

Dependencies for conversion are `cadquery-ocp`, `numpy`, `trimesh`, and `pyyaml`.
Compress each exported model with `gltf-transform meshopt`, using position
quantization of 16 bits, and replace the raw GLB with the compressed output.
The configuration builder does not change the selected deployment flag. Native
CAD sensor axes can be extracted before or after compression. See
[glTF Transform compression documentation](https://gltf-transform.dev/).

Validation commands:

```powershell
python -m pytest validation/test_spacecraft_configurations.py validation/test_sensor_navigation.py validation/test_dashboard_telemetry.py -q
python scripts/verify_cad_physics.py deployed
python scripts/verify_cad_physics.py stowed
python scripts/verify_sensor_changes.py
```

The live mode checks use a sunlit starting phase without editing the YAML, match
the registered Orekit force to telemetry, and isolate each SRP/drag moment in the
actual Euler RHS. Analytic checks cover photon momentum, drag direction, COM
lever arms, rotation covariance, eclipse/penumbra, inverse-square scaling, and
the selected reports' principal moments. Both modes were visually inspected.

## Surface physics and GPS reception

`spacecraft_surface_physics.py` converts the selected exterior surfaces and current
attitude/environment into SRP and drag forces plus their moments about COM.
It handles incidence, reflection, shadows, eclipse and lever arms once, so orbit,
attitude and telemetry use the same result. It does not render CAD or simulate GPS
radio signals. Earth display brightness is independent of this physics.

See [GPS_DIAGRAM_INTEGRATION.md](GPS_DIAGRAM_INTEGRATION.md) for the existing viewer
contract and the constellation, reception and per-channel measurement integration
needed to display actual received GPS data.
