"""Convert the supplied STEP assemblies to SI glTF and a labelled CAD inventory.

Run with cadquery-ocp, numpy and trimesh installed. Assembly locations are
accumulated; millimetres are converted to metres without rotating CAD axes.
CAD contains geometry, not validated optical, aerodynamic or sensor calibration.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.XCAFDoc import XCAFDoc_DocumentTool


def label_name(label):
    attribute = TDataStd_Name()
    return attribute.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attribute) else 'unnamed'


def material(name, bounds):
    lower = name.lower()
    extent = bounds[1] - bounds[0]
    # Material assignments are visual interpretations, retained in inventory.
    if any(k in lower for k in ('solar', 'panel', 'mospd', 'pbspb')):
        return 'solar cells', [18, 28, 52, 255], .35, .42
    if any(k in lower for k in ('pcb', 'board')):
        return 'PCB', [20, 73, 40, 255], .1, .65
    if any(k in lower for k in ('mtr', 'torquer', 'coil')):
        return 'magnetorquer', [135, 70, 35, 255], .6, .48
    if any(k in lower for k in ('baffle', 'lens', 'sensor', 'camera', 'fss', 'adis16547')):
        return 'instrument', [38, 43, 49, 255], .25, .6
    if any(k in lower for k in ('kapton', 'mli', 'foil')):
        return 'thermal blanket', [187, 136, 46, 255], .7, .4
    return 'aluminium', [170, 180, 190, 255], .65, .38


def tessellate(shape):
    BRepMesh_IncrementalMesh(shape, 0.8, False, 0.35, True).Perform()
    vertices, triangles = [], []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is not None:
            offset = len(vertices)
            transform = location.Transformation()
            for i in range(1, mesh.NbNodes() + 1):
                p = mesh.Node(i).Transformed(transform)
                vertices.append((p.X() * .001, p.Y() * .001, p.Z() * .001))
            for i in range(1, mesh.NbTriangles() + 1):
                ids = list(mesh.Triangle(i).Get())
                if face.Orientation() == TopAbs_REVERSED:
                    ids.reverse()
                triangles.append([offset + j - 1 for j in ids])
        explorer.Next()
    return trimesh.Trimesh(vertices=vertices, faces=triangles, process=False)


def export(source, mode, output):
    doc = TDocStd_Document(TCollection_ExtendedString('satellite'))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    print(f'Reading {source.name}', flush=True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone or not reader.Transfer(doc):
        raise RuntimeError(f'Cannot import {source}')
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    scene, parts = trimesh.Scene(), []

    def visit(label, placement, path):
        name = label_name(label)
        path = path + [name]
        if shape_tool.IsReference_s(label):
            target = TDF_Label()
            shape_tool.GetReferredShape_s(label, target)
            visit(target, placement.Multiplied(shape_tool.GetLocation_s(label)), path)
            return
        if shape_tool.IsAssembly_s(label):
            children = TDF_LabelSequence()
            shape_tool.GetComponents_s(label, children)
            for i in range(1, children.Length() + 1):
                visit(children.Value(i), placement, path)
            return
        shape = shape_tool.GetShape_s(label).Moved(placement)
        if shape.IsNull():
            return
        mesh = tessellate(shape)
        if len(mesh.faces) == 0:
            return
        bounds = mesh.bounds
        category, color, metallic, roughness = material('/'.join(path), bounds)
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=category, baseColorFactor=color, metallicFactor=metallic,
            roughnessFactor=roughness, doubleSided=False))
        key = f'{len(parts):04d}_{name}'
        scene.add_geometry(mesh, node_name=key, geom_name=key)
        parts.append(dict(name=name, path=path, node=key, material=category,
                          bounds_body_m=bounds.tolist(), center_body_m=bounds.mean(axis=0).tolist(),
                          triangles=len(mesh.faces)))
        if len(parts) % 100 == 0:
            print(f'{mode}: {len(parts)} placed parts', flush=True)

    for i in range(1, roots.Length() + 1):
        visit(roots.Value(i), TopLoc_Location(), [])
    output.mkdir(parents=True, exist_ok=True)
    scene.export(output / f'P-30XL-{mode}.glb')
    inventory = dict(source=source.name, mode=mode, coordinate_frame='CAD output axes, SI metres',
                     bounds_body_m=scene.bounds.tolist(), parts=parts,
                     material_provenance='Visual interpretation of STEP component labels; not measured optical constants')
    (output / f'P-30XL-{mode}-inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    print(f'{mode}: exported {len(parts)} components; bounds {scene.bounds.tolist()}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('mode', choices=['deployed', 'stowed'])
    parser.add_argument('--output', type=Path, default=Path('frontend/assets/models'))
    args = parser.parse_args()
    export(args.source.resolve(), args.mode, args.output)
