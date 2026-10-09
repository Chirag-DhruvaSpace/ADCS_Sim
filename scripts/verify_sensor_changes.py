import compileall
import subprocess
import sys
from pathlib import Path
import re
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

files = ['simulateimu.py', 'simulatesunsensor.py', 'imu_navigation.py',
         'satellite_parameters.py', 'satellite_flight_visualisation.py',
         'satellite_rotational_dynamics_var_mag_field.py']
for file in files:
    compile(Path(file).read_text(encoding='utf-8-sig'), file, 'exec')
if '--integration' in sys.argv or '--stability' in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import os
    if '--multi' in sys.argv:
        from dataclasses import replace
        import satellite_parameters as cfg
        cfg.IMU_SIM = replace(cfg.IMU_SIM,
            gyros=(cfg.VectorSensorParameters('Gyro A'), cfg.VectorSensorParameters('Gyro B')),
            magnetometers=(cfg.VectorSensorParameters('Mag A'), cfg.VectorSensorParameters('Mag B')))
    if Path('C:/Program Files/Java/jdk-21').exists():
        os.environ['JAVA_HOME'] = 'C:/Program Files/Java/jdk-21'
    import satellite_flight_visualisation as sim
    captured = []
    if '--stability' in sys.argv:
        sim.srd.y0[4:7] = [0., 0., 0.]
        sim.cs.set_mode('SUN_POINTING_RW')
    sim._telemetry_publisher.publish = captured.append
    sim._telemetry_publish_interval_s = 0
    sim.run_simulation(tf=300. if '--stability' in sys.argv else 2., dt=.1)
    assert captured and len(captured[-1]['orbit_path_ecef_m']) == 257
    import numpy as np
    celestial = captured[-1]
    rotation = np.asarray(celestial['eci_to_ecef_matrix'])
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-10)
    assert np.isclose(np.linalg.det(rotation), 1.0)
    assert 3.4e8 < np.linalg.norm(celestial['moon_position_ecef_m']) < 4.2e8
    assert len(captured[-1]['imu_mounts']) == (10 if '--multi' in sys.argv else 8)
    import json
    json.dumps(captured[-1], allow_nan=False)
    if '--dashboard-fixture' in sys.argv:
        target = Path(sys.argv[sys.argv.index('--dashboard-fixture') + 1])
        target.write_text(json.dumps(captured, allow_nan=False), encoding='utf-8')
    print('Live Orekit/ADCS integration PASS:', len(captured), 'ticks; finite telemetry, orbit and mounts')
    if '--stability' in sys.argv:
        import numpy as np
        rates = [np.linalg.norm([d['body_rate_x'], d['body_rate_y'], d['body_rate_z']]) for d in captured]
        print('STABILITY:', 'max rate deg/s', max(rates), 'final rate', rates[-1],
              'final estimate error', captured[-1].get('att_est_error_deg'),
              'final pointing error', captured[-1].get('sun_pointing_rw_error_deg'), flush=True)
        assert max(rates) < sim.srd.DETUMBLE_ON_DEG_S
        assert captured[-1]['att_est_error_deg'] < 5., 'Attitude filter diverged'
        assert rates[-1] < .1, 'Acquisition did not settle'
        assert captured[-1]['sun_pointing_rw_error_deg'] < 5., 'Sun pointing did not converge'
    sys.exit(0)
failed = False
failed |= subprocess.run(['node', 'scripts/test_viewer_feed.cjs']).returncode != 0
for args in [['-m', 'unittest', 'validation.test_sensor_navigation', '-v'],
             ['simulatesunsensor.py', 'validate'], ['simulateimu.py', 'validate']]:
    result = subprocess.run([sys.executable, *args])
    failed |= result.returncode != 0
from app import app
html = app.test_client().get('/').get_data(as_text=True)
for i, (attrs, code) in enumerate(re.findall(r'<script([^>]*)>(.*?)</script>', html, re.S)):
    if 'importmap' in attrs or not code.strip():
        continue
    target = Path(f'validation/viewer_check_{i}.mjs')
    target.write_text(code, encoding='utf-8')
    result = subprocess.run(['node', '--check', str(target)])
    failed |= result.returncode != 0
    target.unlink()
sys.exit(int(failed))
