from pathlib import Path
import yaml
root = Path(__file__).resolve().parent.parent
path = root / 'satellite_parameters.yaml'
text = path.read_text(encoding='utf-8')
data = yaml.safe_load(text)
advanced = data['configurations']
for record in advanced.values():
    provenance = record.pop('provenance')
    record['cad_inventory'] = provenance['cad_inventory']
    record['sun_array'].pop('blockers')  # Same blockers as geometry; loader inherits them.
header = '''# ADVANCED P-30XL MODEL — selected only when the basic file enables it.
# Restart the simulator after editing either file.
panels_deployed: true  # true = open/deployed; false = closed/stowed

# SI units, CAD body axes [X,Y,Z], scalar-first quaternions [w,x,y,z].
# Full inertia matrices use Euler-dynamics signs, not positive CAD products.
# The two report masses are preserved independently; this is no deployment event.
# Only runtime CAD values are kept here. Component labels, bounds, materials and
# hardware records are in each cad_inventory JSON and the corresponding GLB.
# Surface optics and Cd are assumptions; CAD does not supply calibration/noise.
# Each mode overrides the basic spacecraft, geometry, mounts and wheel axes.
# Surfaces are exterior rectangular bus/panel approximations, not all CAD parts.
# Sensor error/calibration settings remain in the basic file.
'''
class Dumper(yaml.SafeDumper):
    pass
def represent_list(dumper, value):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', value,
        flow_style=all(not isinstance(x,(dict,list)) for x in value))
Dumper.add_representer(list,represent_list)
(root/'advanced_satellite_parameters.yaml').write_text(header+yaml.dump({'configurations':advanced},Dumper=Dumper,sort_keys=False),encoding='utf-8')
text = text[:text.index('\n# CAD CONFIGURATION RECORDS')]
text = text.replace('# This is the single editable configuration file for the ADCS simulation.',
 '# Basic model and shared simulation settings. Advanced CAD overrides live in\n# advanced_satellite_parameters.yaml when the switch below is true.')
text = text.replace('# Shared actuator/environment settings. Mass, inertia, geometry and sensor\n# placements come from the selected CAD configuration at the end of this file.',
 '# Legacy spacecraft assumptions below are used when the advanced switch is false.\n# Actuator limits are shared by both models unless explicitly overridden.')
text = text.replace('spacecraft:\n', '''# MODEL SELECTION — true loads CAD overrides; false uses the legacy values below.
# Restart the simulator after changing this switch. No second viewer switch.
use_advanced_satellite_model: true

spacecraft:
  mass_kg: 6.0                    # Legacy SRP/orbit mass assumption [kg]
  body_radius_m: 0.259807621      # Circumscribed radius of the legacy 0.3 m cube
  inertia_kg_m2: [1.465, 1.176, 1.244]  # Legacy P-30XL open-panel diagonal inertia
  drag_reference_area_m2: 0.09    # Legacy reference cross-section [m²]
  srp_reference_area_m2: 0.09     # Legacy reference cross-section [m²]
  model_url: /static/models/P-30XL.glb  # Original simplified viewer model
''',1)
text = text.replace('panels_deployed: true  # RUN SELECTOR: true=open/deployed, false=closed/stowed; restart simulation',
 'panels_deployed: true  # Legacy state label; advanced deployment is chosen in its own file')
text = text.replace('inertia_is_principal_axes: false  # CAD output/body axes; full tensor is used',
 'inertia_is_principal_axes: true  # Legacy diagonal axes; advanced loader overrides this')
surfaces = []
for axis in range(3):
    for sign in (-1,1):
        n=[0.,0.,0.]; n[axis]=float(sign)
        p=[0.,0.,0.]; p[axis]=sign*.15
        surfaces.append(dict(name=f'legacy_{"XYZ"[axis]}_{sign:+}',area_m2=.09,normal_body=n,
            center_of_pressure_body_m=p,absorptivity=.6,diffuse_reflectivity=.2,specular_reflectivity=.2))
text = text.replace('geometry: {}  # Geometry comes from the selected configurations record below.',
 '# Legacy 0.3 m cube. Optics are assumed; facet forces/torques remain coupled.\n'+yaml.dump({'geometry':dict(center_of_mass_body_m=[0.,0.,0.],surfaces=surfaces,blockers=[])},Dumper=Dumper,sort_keys=False).rstrip())
text = text.replace('  mtr_dipole_step_Am2: 0.1          # Same command step as spacecraft above', '''  mtr_dipole_step_Am2: 0.1          # Same command step as spacecraft above
  sun_pointing_base_rate_deg_s: 0.2  # Nominal MTR governor slew rate
  # Post-convergence oscillation about body y or z; angular units are degrees.
  moon_spin_axis: z
  moon_spin_rate_deg_s: 0.06
  moon_spin_amplitude_deg: 12.0       # Symmetric ±amplitude
  moon_spin_achieve_threshold_deg: 2.0 # Start oscillation below this target error
  sun_sweep_axis: z
  sun_sweep_rate_deg_s: 0.06
  sun_sweep_amplitude_deg: 64.0
  sun_sweep_achieve_threshold_deg: 2.0''')
text = text.replace('  atmospheric_drag_enabled: true', '''  atmospheric_drag_enabled: true
  srp_enabled: true                    # Solar-pressure orbital force
  srp_torque_enabled: true             # Solar-pressure attitude moment
  solar_pressure_at_1au_pa: 4.56e-6    # Solar momentum flux at 1 AU [Pa]''')
text = text.replace('  null_space_desaturation_gain: 0.0005  # ASSUMPTION: controller tuning value', '''  null_space_desaturation_gain: 0.001  # Existing active allocator gain [1/s]
  saturation_reallocation_enabled: true # Redistribute torque to unsaturated wheels
  max_reallocation_passes: 4             # Maximum allocator redistribution iterations''')
text = text.replace('# =============================================================================\n# VIEWER-SAVED SENSOR MOUNTING OVERRIDES', '''# =============================================================================
# VIEWER LIGHTING — display only; does not change Sun, eclipse or sensor physics
# =============================================================================
viewer:
  earth_day_ambient: 0.20  # Texture multiplier at the daylight terminator
  earth_day_diffuse: 0.90  # Additional multiplier facing the Sun
  earth_night_floor: 0.06 # Minimum terrain visibility; keep small for dark nights

# =============================================================================
# VIEWER-SAVED SENSOR MOUNTING OVERRIDES''')
text = text.replace('live drag uses selected CAD facets','live drag uses selected model facets')
path.write_text(text,encoding='utf-8')
