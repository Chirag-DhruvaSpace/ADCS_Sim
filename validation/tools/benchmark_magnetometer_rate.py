"""Measure field compute cost and isolated SITL magnetometer packet cadence.

Uses the existing local UDP harness; never connects to external firmware.
Run from the repository root with .venv/Scripts/python.exe -B followed by
this file. Results and a plot are written under .cache/magnetometer-rate.
"""
from pathlib import Path
import json
import os
import runpy
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import jdk4py
os.environ['JAVA_HOME'] = str(jdk4py.JAVA_HOME)
import numpy as np
import satellite_flight_visualisation as sim
import sensor_link
from simulate_magnetometer import SimulatedMagnetometer

output = ROOT / '.cache' / 'magnetometer-rate'
output.mkdir(parents=True, exist_ok=True)
field_times, sensor_times, preparation_times, integration_times, packets = [], [], [], [], []


def timed(function, values):
    def call(*args, **kwargs):
        start = time.perf_counter()
        result = function(*args, **kwargs)
        values.append(time.perf_counter() - start)
        return result
    return call


def stats(seconds):
    values = np.asarray(seconds) * 1000
    return dict(count=len(values), mean_ms=float(np.mean(values)),
                median_ms=float(np.median(values)), p99_ms=float(np.percentile(values, 99)),
                max_ms=float(np.max(values)), over_10ms=int(np.sum(values > 10)))


# Actual magnetic model plus coordinate transforms, without pacing or orbit work.
provider = sim._orbit_provider
provider.prepare_runtime()
position, _ = provider.initial_state()
field = provider.magnetic_field_eci
start = time.perf_counter()
field(0., position)
cold_ms = (time.perf_counter() - start) * 1000
for index in range(1500):
    start = time.perf_counter()
    field(index * .01, position)
    field_times.append(time.perf_counter() - start)
isolated_field = list(field_times)
field_times.clear()

send_imu = sensor_link.send_imu


def observed_send(sock, gyro, mag):
    # Timestamp the actual magnetometer sendto call, excluding gyro/state packets.
    class SocketProbe:
        def sendto(self, packet, address):
            import struct
            if len(packet) == struct.calcsize(sensor_link.IMU_PACKET_FORMAT):
                if struct.unpack(sensor_link.IMU_PACKET_FORMAT, packet)[0] == sensor_link.SENSOR_ID_MAG:
                    packets.append(time.perf_counter())
            return sock.sendto(packet, address)
    return send_imu(SocketProbe(), gyro, mag)


sys.argv = ['benchmark_sitl_timing.py', '--duration', '15']
with patch.object(provider, 'magnetic_field_eci', timed(field, field_times)), \
     patch.object(SimulatedMagnetometer, 'prepare_sample', timed(SimulatedMagnetometer.prepare_sample, preparation_times)), \
     patch.object(SimulatedMagnetometer, 'read_sample', timed(SimulatedMagnetometer.read_sample, sensor_times)), \
     patch.object(sim, 'solve_ivp', timed(sim.solve_ivp, integration_times)), \
     patch.object(sensor_link, 'send_imu', observed_send):
    runpy.run_path(str(ROOT / 'validation/tools/benchmark_sitl_timing.py'), run_name='__main__')

gaps = np.diff(packets)
report = dict(model=provider.magnetic_field.model_name, duration_sim_s=15,
              field_first_after_prepare_ms=cold_ms, field_isolated=stats(isolated_field),
              field_during_sim=stats(field_times), sensor_read=stats(sensor_times),
              sensor_prepare=stats(preparation_times),
              attitude_segment=stats(integration_times), mag_packets=len(packets),
              mag_wall_span_s=float(packets[-1] - packets[0]),
              mag_wall_rate_hz=float((len(packets)-1)/(packets[-1]-packets[0])),
              mag_packet_gaps=stats(gaps), external_firmware=False)
(output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
np.savez(output / 'timings.npz', isolated_field_s=isolated_field,
         field_during_sim_s=field_times, sensor_s=sensor_times,
         integration_s=integration_times, mag_packet_wall_s=packets)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, axes = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
for ax, values, title in zip(axes, (isolated_field, integration_times, gaps),
                            ('Magnetic field calculation (no pacing)',
                             'Attitude integration per firmware segment',
                             'Magnetometer UDP send intervals (wall clock)')):
    ax.plot(np.asarray(values)*1000, linewidth=.7)
    ax.axhline(10, color='red', linestyle='--', label='100 Hz: 10 ms budget')
    ax.set(title=title, ylabel='Milliseconds', xlabel='Sample index')
    ax.grid(alpha=.3)
    ax.legend()
fig.savefig(output / 'timings.png', dpi=150)
print('MAGNETOMETER_BENCHMARK', json.dumps(report, indent=2))
print('ARTIFACTS', output)
