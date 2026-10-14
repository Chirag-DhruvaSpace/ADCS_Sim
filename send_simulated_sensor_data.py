"""Read the sensors' cached raw outputs and send JSON to the C receiver.

The simulation samples each sensor once per tick. This sender reads that same
sample through get_raw_data(); it never generates another sample. While the C
receiver is absent, only one connection attempt every two seconds is made.
"""
from dataclasses import asdict, is_dataclass
import errno
import json
import math
import select
import socket
import time

MAX_MESSAGE_BYTES = 1024 * 1024


def json_value(value):
    """Convert sensor objects and NumPy values into ordinary JSON values."""
    if is_dataclass(value):
        value = asdict(value)
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, dict):
        return {name: json_value(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def sensor_units_json(readings):
    """Preserve each configured gyro/magnetometer's name and measurement."""
    if not isinstance(readings, list):
        return json_value(readings)
    result = []
    for unit, reading in readings:
        result.append({'name': unit.name, 'sample': json_value(reading)})
    return result


def get_raw_sensor_data(simulation_time_s, gps=None, gyro=None, mag=None, sun=None):
    """Build one JSON object from raw readings, with timing in seconds."""
    sun_output = None
    if sun is not None:
        sun_output = {
            't_meas_s': sun.t_meas_s, 't_arrival_s': sun.t_arrival_s,
            'valid': sun.valid,
            'calibration': 'provisional; vendor ICD not available',
            'sensors': json_value(sun.sensors),
        }
    return {
        'version': 3,
        't_sim_s': float(simulation_time_s),
        'gps': json_value(gps),
        'gyroscope': sensor_units_json(gyro),
        'magnetometer': sensor_units_json(mag),
        'sun_sensors': sun_output,
    }


def read_raw_sensor_data(simulation_time_s, gps_sensor, imu_sensor):
    """Call each simulator's public getter; no arguments means cached read."""
    gps_reading = None
    gyro_reading = None
    magnetic_reading = None
    sun_reading = None
    if gps_sensor is not None:
        gps_reading = gps_sensor.get_raw_data()
    if imu_sensor is not None:
        gyro_reading, magnetic_reading, sun_reading = imu_sensor.get_raw_data()
    return get_raw_sensor_data(simulation_time_s, gps_reading, gyro_reading,
                               magnetic_reading, sun_reading)


class SensorDataSender:
    """Optional TCP connection. Network operations never wait on the physics."""

    def __init__(self, host='127.0.0.1', port=5005, retry_s=2.0):
        self.address = (host, port)
        self.retry_s = retry_s
        self.connection = None
        self.connected = False
        self.next_connection_attempt_s = 0.0
        self.connection_deadline_s = 0.0
        self.send_deadline_s = 0.0
        self.pending_data = b''

    def close(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None
        self.connected = False
        self.pending_data = b''
        self.next_connection_attempt_s = time.monotonic() + self.retry_s

    def start_connection(self, current_time_s):
        """Begin connecting, then return immediately."""
        if current_time_s < self.next_connection_attempt_s:
            return False
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.setblocking(False)
        result = self.connection.connect_ex(self.address)
        connection_in_progress = (errno.EINPROGRESS, errno.EWOULDBLOCK,
                                  errno.EALREADY, 10035, 10036, 10037)
        if result != 0 and result not in connection_in_progress:
            self.close()
            return False
        self.connected = result == 0
        self.connection_deadline_s = current_time_s + 2.0
        return True

    def ready_to_send(self, current_time_s):
        """Check connection progress, disconnection, and a full TCP buffer."""
        if self.connection is None:
            if not self.start_connection(current_time_s):
                return False
        readable, writable, failed = select.select(
            [self.connection], [self.connection], [self.connection], 0)
        if failed:
            self.close()
            return False
        if not self.connected:
            if not writable:
                if current_time_s >= self.connection_deadline_s:
                    self.close()
                return False
            socket_error = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if socket_error:
                self.close()
                return False
            self.connected = True
        if readable:
            received = self.connection.recv(1, socket.MSG_PEEK)
            if received == b'':
                self.close()
                return False
        if self.pending_data and current_time_s >= self.send_deadline_s:
            self.close()
            return False
        return bool(writable)

    def send_simulated_sensor_data(self, collect_readings):
        """Collect and encode only when connected and ready for a new sample."""
        current_time_s = time.monotonic()
        try:
            if not self.ready_to_send(current_time_s):
                return False
            if not self.pending_data:
                sensor_data = collect_readings()
                json_text = json.dumps(sensor_data, allow_nan=False)
                self.pending_data = (json_text + '\n').encode('utf-8')
                if len(self.pending_data) > MAX_MESSAGE_BYTES:
                    self.pending_data = b''
                    return False
                self.send_deadline_s = current_time_s + 2.0
            # TCP can accept only part of a line. Keep its remaining bytes;
            # collecting another sample here would interleave two JSON lines.
            sent_bytes = self.connection.send(self.pending_data)
            if sent_bytes == 0:
                self.close()
                return False
            self.pending_data = self.pending_data[sent_bytes:]
            return not self.pending_data
        except BlockingIOError:
            return False
        except OSError:
            self.close()
            return False

    def send_from_sensors(self, simulation_time_s, gps_sensor, imu_sensor):
        """The main simulation's one call to the optional JSON sender."""
        def collect_readings():
            return read_raw_sensor_data(simulation_time_s, gps_sensor, imu_sensor)
        return self.send_simulated_sensor_data(collect_readings)
