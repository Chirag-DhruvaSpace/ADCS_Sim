"""Configuration binding for historical magnetic-pointing gain artifacts.

The manifest is a compatibility baseline, not evidence of a past gain design
or Floquet verification. Unknown provenance requires an explicit YAML opt-in.
"""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import warnings
import satellite_parameters as config

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'magnetic_gain_manifest.json'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def configuration_contract():
    model = asdict(config.MODEL_DATA)
    data_path = model.pop('orekit_data_path')
    resources = ({str(p.relative_to(data_path)).replace('\\','/'): sha256(p)
                  for p in sorted(data_path.rglob('*')) if p.is_file()}
                 if data_path.is_dir() else {data_path.name: sha256(data_path)})
    return json.loads(json.dumps(dict(
        orbit=asdict(config.ORBIT), inertia=config.SPACECRAFT.inertia_matrix.tolist(),
        mass_kg=config.SPACECRAFT.mass_kg, geometry=asdict(config.GEOMETRY),
        disturbances=asdict(config.DISTURBANCES), model=model, resources=resources,
        frame='Hamilton scalar-first body-to-EME2000',
        target='fixed body -Z at epoch Sun; unconstrained roll', phase='elapsed seconds from configured epoch'),
        default=str, sort_keys=True))


def validate_schedule(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    if manifest['configuration'] != configuration_contract():
        raise RuntimeError('Magnetic gain configuration/dataset mismatch. Redesign and validate the gains for this plant; see magnetic_gain_manifest.json.')
    for name, expected in manifest['artifacts'].items():
        if sha256(ROOT / name) != expected:
            raise RuntimeError('Magnetic gain artifact hash mismatch: '+name)
    if not manifest['design_verified']:
        if not config.SIMULATION.allow_unverified_magnetic_gains:
            raise RuntimeError('Historical magnetic gains have unknown design provenance; use a verified design or explicitly enable simulation.allow_unverified_magnetic_gains')
        warnings.warn('Using explicitly permitted historical magnetic gains: configuration matches, design/Floquet provenance is unverified.', RuntimeWarning, stacklevel=2)
    return 'historical_unverified' if not manifest['design_verified'] else 'verified_design'
