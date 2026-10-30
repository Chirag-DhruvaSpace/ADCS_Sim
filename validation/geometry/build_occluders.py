"""Optional cache warmup; normal startup prepares missing caches automatically.

Run: .venv/Scripts/python.exe -B validation/geometry/build_occluders.py
All model filenames, units and CAD node selectors come from the two YAML files.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    sys.path.insert(0, str(ROOT))
    import satellite_parameters as config
    from engine.physics.mesh_shadow import load_model_occluder, model_cache_path
    for deployed in [False, True]:
        settings = config._load_configuration(panels_deployed=deployed)
        for blocker in settings[10].sun_array.blockers:
            if blocker.sensor_model_node:
                load_model_occluder(blocker.sensor_model_file, blocker.sensor_model_node,
                                    blocker.sensor_model_scale_to_m)
                cache, _ = model_cache_path(blocker.sensor_model_file, blocker.sensor_model_node,
                                           blocker.sensor_model_scale_to_m)
                print(settings[0].configuration, blocker.name, cache)


if __name__ == '__main__':
    main()
