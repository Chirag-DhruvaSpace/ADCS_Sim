# Validation and experiments

These scripts are not part of the `launcher.py` runtime. They are retained for
regression studies, controller comparisons, plotting, and hardware-model
experiments.

- Root files in this folder are validation and plotting programs.
- `results/` contains generated plots and numerical result files.
- `experiments/` contains alternative controller and firmware experiments.
- `tools/` contains CAD import/configuration utilities, orbit checks, and the
  standalone browser fixture server. Run these from the repository root.

Sensor mounting is configured in backend YAML only. The viewer has no sensor
mount editor or mounting API. Generated screenshots are not validation inputs.
Run sensor regression checks with `.venv/Scripts/python.exe -B -m pytest
validation/test_sensor_navigation.py validation/test_hardware_sensor_outputs.py`.

The production launcher dependencies remain at the repository root and under
`engine/`.
