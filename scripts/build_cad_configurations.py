"""Rebuild configuration records from CAD inventories and the supplied reports.

Detailed render meshes are separate from a rectangular exterior macromodel.
Bounding boxes provide exposed bus/panel facets and sun-sensor occluders;
4x4 quadrature resolves partial occlusion. Optical constants, Cd and sensor
calibration remain assumptions. CAD part labels do not encode calibration.
"""
import json
from pathlib import Path
import numpy as np
import trimesh
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORTS = {
    'stowed': dict(mass=30.40, com=[-.01682,-.01421,-.12967],
                   tensor=[[1.22157185,-.00845668,.00685571],[-.00845668,.96667654,.01546644],[.00685571,.01546644,1.08575350]],
                   principal=[.96448009,1.08726972,1.22225207],
                   axes=[[-.03,.99,.12],[.06,-.12,.99],[1.,.04,-.05]],
                   origin_tensor=[[1.73895008,-.001190,.07318215],[-.001190,1.48652314,.07147775],[.07318215,.07147775,1.10049499]]),
    'deployed': dict(mass=27.29, com=[-.01855,-.01489,-.16821],
                     tensor=[[1.91995486,-.01564290,-.01448170],[-.01564290,.89113454,.00581086],[-.01448170,.00581086,1.83157276]],
                     principal=[.89085808,1.82933196,1.92247211],
                     axes=[[-.02,1.,.01],[-.16,-.01,.99],[.99,.01,.16]],
                     origin_tensor=[[2.69831463,-.00810082,.07070690],[-.00810082,1.67283743,.07418616],[.07070690,.07418616,1.84702295]])}
BUS_BOUNDS = np.array([[-.180,-.210,-.340],[.180,.210,0]])


def box_record(name, bounds):
    bounds = np.asarray(bounds)
    return dict(name=name, center_body_m=bounds.mean(axis=0).tolist(),
                half_extents_m=((bounds[1]-bounds[0])/2).tolist())


def box_surfaces(name, bounds, solar=False):
    lo, hi = np.asarray(bounds)
    size = hi-lo
    center = (lo+hi)/2
    result = []
    for axis in range(3):
        tangent = [j for j in range(3) if j != axis]
        for sign in (-1,1):
            n = np.eye(3)[axis]*sign
            cp = center.copy(); cp[axis] = hi[axis] if sign > 0 else lo[axis]
            result.append(dict(name=f'{name}:{"XYZ"[axis]}{sign:+}', area_m2=float(np.prod(size[tangent])),
                               normal_body=n.tolist(), center_of_pressure_body_m=cp.tolist(),
                               absorptivity=.85 if solar else .6,
                               diffuse_reflectivity=.1 if solar else .2,
                               specular_reflectivity=.05 if solar else .2,
                               tangent_u_body=np.eye(3)[tangent[0]].tolist(),
                               tangent_v_body=np.eye(3)[tangent[1]].tolist(),
                               half_size_m=(size[tangent]/2).tolist()))
    return result


def configuration(mode):
    inventory = json.loads((ROOT/f'frontend/assets/models/P-30XL-{mode}-inventory.json').read_text())
    report = REPORTS[mode]
    # SOLIDWORKS positive notation reports products ∫xy dm, ∫xz dm, ∫yz dm.
    # Euler's inertia matrix uses their negatives. This conversion reproduces
    # the separately reported principal moments (an independent sign check).
    tensor = 2*np.diag(np.diag(report['tensor']))-np.array(report['tensor'])
    origin_tensor = 2*np.diag(np.diag(report['origin_tensor']))-np.array(report['origin_tensor'])
    parts = inventory['parts']
    panel_parts = [p for p in parts if 'MOSPD' in p['name'] or 'PBSPB' in p['name']]
    blockers = [box_record('bus-envelope',BUS_BOUNDS)]
    surfaces = box_surfaces('bus-envelope',BUS_BOUNDS)
    for i, part in enumerate(panel_parts):
        name = f'panel-{i+1}:{part["name"]}'
        blockers.append(box_record(name,part['bounds_body_m']))
        surfaces.extend(box_surfaces(name,part['bounds_body_m'],solar=True))
    sensors = [p for p in parts if p['name']=='11_SPPX_PB_ADCS_FSS_V1(2)']
    cells = []
    for p in sensors:
        bounds = np.array(p['bounds_body_m'])
        axis = np.argmin(bounds[1]-bounds[0])
        center = bounds.mean(axis=0)
        sign = 1 if center[axis] > BUS_BOUNDS.mean(axis=0)[axis] else -1
        pos = center.copy()
        pos[axis] = bounds[1,axis] if sign > 0 else bounds[0,axis]
        # Sensor board face is inferred from its thinnest CAD extent. The
        # photosensitive die offset and calibration are not supplied.
        normal = np.array(p.get('mount_normal_body',np.eye(3)[axis]*sign))
        pos += normal*.0005
        cells.append(dict(name=f'{"+" if sign>0 else "-"}{"XYZ"[axis]}',
                          normal_body=normal.tolist(), position_body_m=pos.tolist()))
    gyro = next(p for p in parts if p['name']=='ADIS16547-1BMLZ')
    wheels = [p for p in parts if p['name']=='SP_RW060 - RevE _27-11-2024']
    wheel_axes = [p.get('mount_normal_body') for p in wheels]
    if any(axis is None for axis in wheel_axes):
        raise ValueError('Run node scripts/extract_cad_mounts.mjs first to extract wheel mounting axes')
    # No unambiguous magnetometer chip label: retain the documented assumption.
    bounds = np.array(inventory['bounds_body_m'])
    return dict(
        spacecraft=dict(mass_kg=report['mass'], body_radius_m=float(np.max(np.linalg.norm(bounds-np.array(report['com']),axis=1))),
                        inertia_kg_m2=np.diag(tensor).tolist(), inertia_tensor_kg_m2=tensor.tolist(),
                        drag_reference_area_m2=float(.36*.42 + sum((np.array(p['bounds_body_m'])[1]-p['bounds_body_m'][0])[:2].prod() for p in panel_parts)),
                        srp_reference_area_m2=float(.36*.42 + sum((np.array(p['bounds_body_m'])[1]-p['bounds_body_m'][0])[:2].prod() for p in panel_parts)),
                        model_url=f'/assets/models/P-30XL-{mode}.glb'),
        geometry=dict(center_of_mass_body_m=report['com'],surfaces=surfaces,blockers=blockers),
        sun_array=dict(cells=cells,blockers=blockers),
        sensor_mounts=dict(gyro_position_body_m=gyro['center_body_m']),
        reaction_wheels=dict(axis_matrix_body=np.array(wheel_axes).T.tolist()),
        provenance=dict(mass_inertia='User mass-property report, 22 September 2026; kg mm² divided by 1e6; positive-notation products negated for Euler inertia matrix',
                        principal_moments_kg_m2=report['principal'],
                        principal_axes_report_rounded=report['axes'],
                        report_positive_products_at_com_kg_m2=report['tensor'],
                        report_positive_products_at_origin_kg_m2=report['origin_tensor'],
                        inertia_at_cad_origin_kg_m2=origin_tensor.tolist(),
                        cad_inventory=f'frontend/assets/models/P-30XL-{mode}-inventory.json',
                        geometry='CAD bus and panel bounding-box macromodel; 4x4 face quadrature with ray occlusion',
                        sun_sensors='Six FSS CAD board placements and dominant planar-face normals; photosensitive die offsets and calibration assumed',
                        reaction_wheels='CAD RW060 spindle axes from dominant planar faces, ordered by inventory; existing torque/momentum limits retained pending supplier data',
                        gyro='ADIS16547 CAD package centroid; chip mounting rotation/calibration assumed identity',
                        magnetometer='Chip cannot be identified unambiguously from labels; existing assumed mount retained',
                        optical='ASSUMPTION: bus absorption/diffuse/specular 0.6/0.2/0.2; panels 0.85/0.1/0.05',
                        aerodynamic='ASSUMPTION: Cd=2.2, projected-area diffuse free-molecular drag; no measured lift',
                        mass_difference='Reports differ by 3.11 kg; preserved independently, no in-flight deployment mass change',
                        hardware_mounts=[dict(name=p['name'],position_body_m=p['center_body_m'],bounds_body_m=p['bounds_body_m'])
                                         for p in parts if p['name'] in ('SPPE113_003','SP_RW060 - RevE _27-11-2024','ADFGP.25E.07.0060A','ADIS16547-1BMLZ')]))


def recolor(mode):
    from export_satellite_cad import material
    path = ROOT/f'frontend/assets/models/P-30XL-{mode}.glb'
    scene = trimesh.load(path, force='scene')
    inventory_path = ROOT/f'frontend/assets/models/P-30XL-{mode}-inventory.json'
    inventory = json.loads(inventory_path.read_text())
    for part in inventory['parts']:
        mesh = scene.geometry[part['node']]
        category,color,metallic,roughness = material('/'.join(part['path']),np.array(part['bounds_body_m']))
        part['material'] = category
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=category,baseColorFactor=color,metallicFactor=metallic,roughnessFactor=roughness))
    scene.export(path)
    inventory_path.write_text(json.dumps(inventory,indent=2))


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--recolor',action='store_true',help='Recolor uncompressed exports; not needed after exporter uses current material rules')
    args=parser.parse_args()
    data = {mode:configuration(mode) for mode in REPORTS}
    path = ROOT/'advanced_satellite_parameters.yaml'
    previous = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
    for mode, record in data.items():
        record['cad_inventory'] = record.pop('provenance')['cad_inventory']
        record['sun_array'].pop('blockers')
    header = '# Advanced CAD overrides. Shared errors/controller settings stay in the basic file.\n'
    header += '# panels_deployed: true=open/deployed, false=closed/stowed. Restart after editing.\n'
    class CompactDumper(yaml.SafeDumper):
        pass
    CompactDumper.add_representer(list, lambda dumper, values:
        dumper.represent_sequence('tag:yaml.org,2002:seq', values,
            flow_style=all(not isinstance(value, (dict, list)) for value in values)))
    path.write_text(header + yaml.dump(dict(panels_deployed=previous.get('panels_deployed', True),
                    configurations=data), Dumper=CompactDumper, sort_keys=False), encoding='utf-8')
    if args.recolor:
        for mode in REPORTS:
            recolor(mode)
    print('Both mass-property reports, CAD geometry and sensor locations saved.')
