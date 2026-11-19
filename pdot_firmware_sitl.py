"""Build and run the P-Dot OBC detumble routines against simulated registers."""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import weakref

import socket
import struct


def _flight_function(source, name):
    # Top-level C definitions in the OBC sources end with a column-zero brace.
    matches = re.findall(
        rf'^((?:static )?(?:void|uint32_t)\s+{name}\([^;{{]*\)\s*\{{.*?^\}})',
        source, re.MULTILINE | re.DOTALL)
    if len(matches) != 1:
        raise ValueError(f'Expected one P-Dot firmware definition of {name}')
    return matches[0]


def _release_library(library, build_directory):
    if os.name == 'nt':
        from _ctypes import FreeLibrary
        FreeLibrary(library._handle)
    build_directory.cleanup()


class PDotDetumbleFirmware:
    """A separate C instance per simulation, stepped by simulated time."""

    def __init__(self, source_root):
        compiler = shutil.which('gcc')
        if compiler is None:
            raise RuntimeError('P-Dot firmware SITL requires a native GCC compiler on PATH')
        core = Path(source_root) / 'PDOT-OBC' / 'Core'
        controller = (core / 'Src/acs.c').read_text(encoding='utf-8-sig')
        driver = (core / 'Src/icm20948i2c.c').read_text(encoding='utf-8-sig')
        constants = (core / 'Inc/globalmisc.h').read_text(encoding='utf-8-sig')
        driver_header = (core / 'Inc/icm20948i2c.h').read_text(encoding='utf-8-sig')
        definitions = re.findall(
            r'^#define\s+(?:BDOT_K[XYZ]|HARD_CUTOFF_DEG|DETUMBLING_CUTOFF_DEG|'
            r'SENSOR_LOG_INTERVAL_SHORT|COIL[XYZ]_NA|COIL_CURRENT_MAX_[XYZ]|I[XYZ][XYZ])\s+[^\n]+',
            constants, re.MULTILINE)
        definitions += re.findall(
            r'^#define\s+(?:ICM_GYRO_CALIBRATION_\w+|MAG_OFFSET_[XYZ]|ICM_\w*TEMPERATURE_\w+|'
            r'ICM20948_REG_BANK_SEL|ICM20948_GYRO_XOUT_H|AK09916_HXL)\s+[^\n]+',
            driver_header, re.MULTILINE)
        kalman_type = re.search(
            r'typedef struct __attribute__\(\(packed\)\)\s*\{[^}]+\}\s*simpleKalmanStruct;',
            driver_header).group()
        harness = Path(__file__).with_name('pdot_firmware_sitl.c').read_text(encoding='utf-8')
        routines = [_flight_function(driver, name) for name in (
            'ICM20948_readMagData', 'ICM20948_readGyroAndTempData', 'initKalman', 'updateEst')]
        routines += [_flight_function(controller, name) for name in (
            'readMagData', 'computeBDot', 'torquerCoils')]
        # The bridge holds ideal coil-current targets, with no INA220 wait.
        # Only the zero-current fast path of the original readMagData runs.
        definitions += ['#define UserBank0 0', '#define MAG_READTIME_OUT 1']
        build_directory = tempfile.TemporaryDirectory(prefix='pdot-sitl-')
        generated_source = Path(build_directory.name) / 'detumble.c'
        library_path = generated_source.with_suffix('.dll')
        generated_source.write_text('\n'.join(definitions + [kalman_type, harness] + routines), encoding='utf-8')
        result = subprocess.run([compiler, '-shared', '-O2', str(generated_source), '-o', str(library_path), '-lm'],
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f'P-Dot detumble firmware build failed:\n{result.stderr}')
        self.library = ctypes.CDLL(str(library_path))
        weakref.finalize(self, _release_library, self.library, build_directory)
        self.library.pdot_initialize.argtypes = []
        self.library.pdot_initialize.restype = None
        self.library.pdot_detumble_sample.argtypes = [
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_double)]
        self.library.pdot_detumble_sample.restype = None
        self.library.pdot_initialize()

    def step(self, milliseconds, gyroscope_registers, magnetometer_registers):
        currents = (ctypes.c_double * 4)()
        self.library.pdot_detumble_sample(
            1000 + milliseconds, gyroscope_registers, magnetometer_registers, currents)
        return tuple(currents)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Run the P-Dot OBC detumble firmware over local UDP')
    parser.add_argument('--port', type=int, default=5110)
    args = parser.parse_args()
    firmware = PDotDetumbleFirmware(Path(__file__).resolve().parents[1])
    sensor_packet = struct.Struct('<I10s8s')
    command_packet = struct.Struct('<I4d')
    previous_sender = None
    previous_timestamp = None
    response = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.bind(('127.0.0.1', args.port))
        print(f'P-Dot OBC detumble SITL listening on 127.0.0.1:{args.port}', flush=True)
        while True:
            packet, sender = connection.recvfrom(1024)
            if len(packet) != sensor_packet.size:
                continue
            timestamp, gyroscope, magnetometer = sensor_packet.unpack(packet)
            if sender != previous_sender:
                firmware.library.pdot_initialize()
                previous_sender, previous_timestamp = sender, None
            if previous_timestamp is None or timestamp > previous_timestamp:
                response = command_packet.pack(timestamp, *firmware.step(timestamp, gyroscope, magnetometer))
                previous_timestamp = timestamp
            if timestamp == previous_timestamp:
                connection.sendto(response, sender)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
