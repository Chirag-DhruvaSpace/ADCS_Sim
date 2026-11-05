"""Short local ADS + ACS + noisy simulator check. Requires their ports to be free."""
from pathlib import Path
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import jdk4py
os.environ.setdefault('JAVA_HOME', str(jdk4py.JAVA_HOME))
import numpy as np
import satellite_parameters as settings

# Select SITL for this process without editing the user's YAML.
settings.POINTING['strategy'] = 'firmware_sitl'
import satellite_flight_visualisation as sim
import yaw_steering
from validation.tools.build_firmware_sitl import build

directory = ROOT / '.cache/yaw_steering'
firmware = ROOT.parents[1] / 'Firmware'
offset = 10000
for kind, ports in [(socket.SOCK_STREAM, [15001, 15101]),
                    (socket.SOCK_DGRAM, [15002, 15010, 15103, 15104, 15105])]:
    for port in ports:
        with socket.socket(socket.AF_INET, kind) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('0.0.0.0', port))

# Only temporary entry-point copies get different port constants.
for board in ['ADS', 'ACS']:
    main = (firmware / board / 'Src/main.c').read_text()
    main = re.sub(r'(#define\s+\w*PORT\s+)(\d+)',
                  lambda match: match[1]+str(int(match[2])+offset), main)
    (directory / f'smoke_{board}_main.c').write_text(main)
build(directory / 'smoke_ads.exe', main_source=directory / 'smoke_ADS_main.c')
acs = firmware / 'ACS'
includes = sorted({p.parent for p in (acs / 'Inc').rglob('*.h')})
sources = [str(p) for p in (acs / 'Src').rglob('*.c') if p.name != 'main.c']
subprocess.run(['gcc', '-O2', '-fcommon'] + [f'-I{p}' for p in includes]
               + sources + [str(directory / 'smoke_ACS_main.c'), '-o',
                            str(directory / 'smoke_acs.exe'), '-lws2_32', '-lm'], check=True)

real_socket = socket.socket
class RelocatedSocket:
    def __init__(self, *args, **kwargs): self.sock=real_socket(*args, **kwargs)
    def bind(self, address): self.sock.bind((address[0], address[1]+offset))
    def __getattr__(self, name): return getattr(self.sock, name)
with patch('socket.socket', RelocatedSocket):
    import firmware_sitl_link as link
import telemetry
import sensor_link
link.TLM_SEND_PORT += offset
telemetry.ADS_SIM_PORT += offset
sensor_link.ADS_SENSOR_PORT += offset

processes, files, snapshots = [], [], []
client = None
try:
    for name, executable in [('ACS', directory / 'smoke_acs.exe'),
                             ('ADS', directory / 'smoke_ads.exe')]:
        log = (directory / f'smoke_{name}.log').open('w')
        files.append(log)
        processes.append(subprocess.Popen([str(executable)], stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    deadline = time.monotonic()+15
    while client is None:
        try:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError('A test firmware process exited; see smoke_ADS/ACS.log')
            client = socket.create_connection(('127.0.0.1', 15001), timeout=1)
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError('ADS did not open its COSMOS command connection')
            time.sleep(0.1)

    # A near-target start checks integration; the long test checks acquisition.
    r, v = sim.state0[:3], sim.state0[3:6]
    sim.srd.y0[:4] = yaw_steering.yaw_steering_quaternion(r, v)
    sim.srd.y0[4:7] = yaw_steering.yaw_steering_target_rate(r, v)
    started, last_command = time.monotonic(), 0.0
    def publish(snapshot):
        global last_command
        snapshots.append(snapshot)
        now = time.monotonic()
        # Mode selection is checked while the normal actuator startup completes.
        if now-started > 8 and now-last_command > 1 and snapshot.get('ads_mode') != 'YawSteering':
            client.sendall(struct.pack('<BBBHBHB', 0x23, 1, 70, 1, 12, 0xFFFF, 0x3B))
            last_command=now
    sim._telemetry_publisher.publish=publish
    sim.run_simulation(tf=18)
    yaw_samples = [row for row in snapshots if row.get('ads_mode') == 'YawSteering']
    assert yaw_samples, 'Firmware never reported YawSteering; see smoke_ADS.log'
    last=yaw_samples[-1]
    for key in ['yaw_steering_angle_deg', 'yaw_steering_error_deg',
                'firmware_pointing_error_deg', 'firmware_target_yaw_deg']:
        assert np.isfinite(last[key]), (key, last.get(key))
    result = {'snapshots': len(snapshots), 'yaw_steering_snapshots': len(yaw_samples),
              'final_mode': snapshots[-1].get('ads_mode'),
              'final_angle_deg': last['yaw_steering_angle_deg'],
              'final_error_deg': last['yaw_steering_error_deg'],
              'conditions': 'Real ADS/ACS processes, normal noisy sensors and disturbance configuration'}
    (directory / 'smoke_result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
finally:
    if client is not None:
        client.close()
    sim._telemetry_publisher.close()
    for process in reversed(processes):
        process.terminate()
        process.wait(timeout=5)
    for file in files:
        file.close()
