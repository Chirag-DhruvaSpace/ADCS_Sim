"""Record a fresh isolated ADS/ACS boot with the normal UDP simulator."""
import argparse
import csv
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from validation.tools.build_firmware_sitl import build

PORT_OFFSET = 10000
CSV_FIELDS = ('simulation_time_s', 'ads_mode', 'sun_pointing_error_deg',
              'mtr_current_a', 'rw_torques_mnm', 'firmware_command_state', 'firmware_packet_age_s')


def relocate(source, destination):
    destination.write_text(re.sub(r'(#define\s+\w*PORT\s+)(\d+)',
                           lambda match: match[1] + str(int(match[2]) + PORT_OFFSET),
                           source.read_text(encoding='utf-8')), encoding='utf-8')


def build_boards(directory):
    firmware = ROOT.parents[1] / 'Firmware'
    ads_main = directory / 'live_ads_main.c'
    relocate(firmware / 'ADS/Src/main.c', ads_main)
    ads = directory / 'live_ads.exe'
    build(ads, main_source=ads_main, defines=['SITL_FSM_TRACE'], object_directory=directory / 'objects')
    acs = firmware / 'ACS'
    acs_main = directory / 'live_acs_main.c'
    relocate(acs / 'Src/main.c', acs_main)
    includes = sorted({p.parent for p in (acs / 'Inc').rglob('*.h')})
    sources = sorted(str(p) for p in (acs / 'Src').rglob('*.c') if p.name != 'main.c')
    acs_exe = directory / 'live_acs.exe'
    subprocess.run(['gcc', '-O2', '-fcommon', *(f'-I{p}' for p in includes),
                    *sources, str(acs_main), '-o', str(acs_exe), '-lws2_32', '-lm'], check=True)
    return acs_exe, ads


def terminate(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=120.)
    parser.add_argument('--output', type=Path, default=ROOT.parents[1] / 'P30XL_SILS_Results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    directory = ROOT.parents[1] / '.p30xl-build/live'
    directory.mkdir(parents=True, exist_ok=True)
    for kind, ports in [(socket.SOCK_STREAM, [5001, 5101]),
                        (socket.SOCK_DGRAM, [5002, 5010, 5102, 5103, 5104, 5105])]:
        for port in ports:
            with socket.socket(socket.AF_INET, kind) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('0.0.0.0', port + PORT_OFFSET))
    programs = build_boards(directory)
    import jdk4py
    os.environ.setdefault('JAVA_HOME', str(jdk4py.JAVA_HOME))
    import satellite_flight_visualisation as sim
    import sensor_link
    import telemetry

    real_socket = socket.socket

    def relocate_binding(*args, **kwargs):
        class RelocatedSocket(real_socket):
            def bind(self, address):
                host, port = address
                return super().bind((host, port + PORT_OFFSET))

        return RelocatedSocket(*args, **kwargs)

    with patch('socket.socket', relocate_binding):
        import firmware_sitl_link as link

    link.TLM_SEND_PORT += PORT_OFFSET
    sensor_link.ADS_SENSOR_PORT += PORT_OFFSET
    telemetry.ADS_SIM_PORT += PORT_OFFSET
    with ExitStack() as stack:
        processes = []
        for board, program in zip(('acs', 'ads'), programs):
            log = stack.enter_context((output / f'live_boot_{board}.log').open('w', encoding='utf-8'))
            process = subprocess.Popen([str(program)], stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            stack.callback(terminate, process)
            processes.append(process)
        deadline = time.monotonic() + 15.
        while True:
            try:
                # The ADS entry point waits for a COSMOS-style TCP client.
                # Keep the connection open and let normal boot choose its mode.
                stack.enter_context(socket.create_connection(('127.0.0.1', 5001 + PORT_OFFSET), timeout=1))
                break
            except OSError:
                if time.monotonic() >= deadline or any(process.poll() is not None for process in processes):
                    raise
                time.sleep(.1)
        stream = stack.enter_context((output / 'live_boot_telemetry.csv').open('w', newline='', encoding='utf-8'))
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction='ignore')
        writer.writeheader()
        sim._telemetry_publisher.publish = writer.writerow
        stack.callback(sim._telemetry_publisher.close)
        sim.run_simulation(tf=args.duration)


if __name__ == '__main__':
    main()
