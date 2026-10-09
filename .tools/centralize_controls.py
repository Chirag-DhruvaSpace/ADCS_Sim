from pathlib import Path
root=Path(__file__).resolve().parent.parent
p=root/'satellite_rotational_dynamics_var_mag_field.py'
t=p.read_text(encoding='utf-8')
import re
for prefix in ('MOON_SPIN','SUN_SWEEP'):
    for suffix in ('AXIS','RATE_DEG_S','AMPLITUDE_DEG','ACHIEVE_THRESHOLD_DEG'):
        key=prefix+'_'+suffix
        t=re.sub(r'^'+key+r'\s*=.*$',key+' = config.CONTROL.'+key.lower(),t,flags=re.M)
start=t.index('# Standalone constant, matching satellite_flight_visualisation.py')
end=t.index('\ndef _dcm_bi_from_q',start)
t=t[:start]+'# All orbit and target dates use the same configured UTC epoch.\nEPOCH_UTC = config.ORBIT.epoch_utc\n'+t[end:]
p.write_text(t,encoding='utf-8')
# Rebuilding CAD must never inflate or overwrite the user's basic parameter file.
p=root/'scripts/build_cad_configurations.py'
t=p.read_text(encoding='utf-8')
start=t.index("    path = ROOT/'satellite_parameters.yaml'")
end=t.index('    if args.recolor:',start)
t=t[:start]+'''    path = ROOT/'advanced_satellite_parameters.yaml'
    previous = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
    for mode, record in data.items():
        record['cad_inventory'] = record.pop('provenance')['cad_inventory']
        record['sun_array'].pop('blockers')
    header = '# Advanced CAD overrides. Shared errors/controller settings stay in the basic file.\\n'
    header += '# panels_deployed: true=open/deployed, false=closed/stowed. Restart after editing.\\n'
    path.write_text(header + yaml.safe_dump(dict(panels_deployed=previous.get('panels_deployed', True),
                    configurations=data), sort_keys=False), encoding='utf-8')
'''+t[end:]
p.write_text(t,encoding='utf-8')
