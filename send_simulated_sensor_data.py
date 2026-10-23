"""Collect independent sensors and send their cached raw outputs as JSON.

SimulatedSensors coordinates acquisition; all sensor physics stays in each
sensor's own file. The simulation samples each sensor once per tick. This sender reads that same
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


class SimulatedSensors:
    """Collect independent sensor models; no navigation or sensor physics here.

    The two-phase prepare/read order preserves the former combined simulator's
    seeded readings. Each sensor still exposes its own get_raw_data() function.
    """

    def __init__(self, config, epoch_utc=None, record_history=True):
        import collections
        import numpy as np
        from simulate_gyroscope import SimulatedGyroscope
        from simulate_magnetometer import SimulatedMagnetometer
        from simulate_sunsensor import SimulatedSunSensorArray
        from simulate_startracker import SimulatedStarTracker

        self.cfg = config
        self.epoch_utc = epoch_utc
        random_generator = np.random.default_rng(config.seed)
        self.gyroscope = SimulatedGyroscope(config, epoch_utc, record_history, random_generator)
        self.magnetometer = SimulatedMagnetometer(config, epoch_utc, record_history, random_generator)
        self.star_tracker = SimulatedStarTracker(enabled=config.enable_star_tracker)
        self.sun_sensor = (SimulatedSunSensorArray(config.sun_array, record_history=record_history)
                           if config.enable_sun_sensor and config.sun_array.enabled else None)
        self._raw_tick = None
        self._raw_receipts = (None, None, None)
        self.sun_samples = 0
        self.records = [] if record_history else collections.deque(maxlen=2)
        self._units = {}
        for kind, group in (('gyro', config.gyros), ('mag', config.magnetometers)):
            if group:
                self._units[kind] = [
                    (unit, SimulatedSensors(config.unit_config(kind, unit, index),
                                            record_history=record_history))
                    for index, unit in enumerate(group) if unit.enabled]

    @property
    def gyro_samples(self):
        return self.gyroscope.gyro_samples

    @property
    def mag_samples(self):
        return self.magnetometer.mag_samples

    def _read_vector_sensor(self, kind, time_s, quaternion, angular_rate, magnetic_field, raw_output):
        enabled = self.cfg.enable_gyro if kind == 'gyro' else self.cfg.enable_magnetometer
        if kind in self._units:
            if not enabled:
                return []
            readings = []
            for unit, sensors in self._units[kind]:
                gyro, magnetic, _ = sensors.update(time_s, quaternion, angular_rate,
                                                   magnetic_field, raw_output=raw_output)
                readings.append((unit, gyro if kind == 'gyro' else magnetic))
            return readings

        sensor = self.gyroscope if kind == 'gyro' else self.magnetometer
        reading = sensor.read_sample(raw_output)
        if reading is not None and not raw_output:
            record = sensor._last_gyro_rec if kind == 'gyro' else sensor._last_mag_rec
            self.records.append((kind, record))
        return reading

    def update(self, t_seconds, q_truth, omega_truth, B_eci_truth,
               sun_eci_truth=None, eclipse_fraction=1.0, position_eci=None,
               raw_output=False):
        """Acquire gyro, magnetic, and Sun readings on their original clocks."""
        self.gyroscope.prepare_sample(t_seconds, q_truth, omega_truth)
        self.magnetometer.prepare_sample(t_seconds, q_truth, B_eci_truth)
        gyro = self._read_vector_sensor('gyro', t_seconds, q_truth, omega_truth,
                                        B_eci_truth, raw_output)
        magnetic = self._read_vector_sensor('mag', t_seconds, q_truth, omega_truth,
                                            B_eci_truth, raw_output)
        sun = None
        if self.sun_sensor is not None and sun_eci_truth is not None:
            if raw_output:
                sun = self.sun_sensor.get_raw_data(t_seconds, q_truth, sun_eci_truth,
                                                   eclipse_fraction, position_eci)
            else:
                sun = self.sun_sensor.update(t_seconds, q_truth, sun_eci_truth,
                                             eclipse_fraction, position_eci)
            if sun is not None:
                self.sun_samples += 1
        return gyro, magnetic, sun

    def get_raw_data(self, t_seconds=None, q_truth=None, omega_truth=None,
                     B_eci_truth=None, sun_eci_truth=None, eclipse_fraction=1.0,
                     position_eci=None):
        """Sample each sensor once; argument-free calls only read the cache."""
        if not self.cfg.enabled:
            return (None, None, None)
        if t_seconds is None or t_seconds == self._raw_tick:
            return self._raw_receipts
        self._raw_receipts = self.update(t_seconds, q_truth, omega_truth, B_eci_truth,
                                         sun_eci_truth, eclipse_fraction, position_eci,
                                         raw_output=True)
        self._raw_tick = float(t_seconds)
        return self._raw_receipts

    def get_gyroscope_raw_data(self, *args, **kwargs):
        return self.get_raw_data(*args, **kwargs)[0]

    def get_magnetometer_raw_data(self, *args, **kwargs):
        return self.get_raw_data(*args, **kwargs)[1]

    def get_sun_sensor_raw_data(self, *args, **kwargs):
        return self.get_raw_data(*args, **kwargs)[2]


def sensor_layout(configuration):
    """Read-only sensor positions in metres for operator displays."""
    layout = []
    for cell in configuration.sun_array.cells:
        layout.append(dict(name=cell.name, kind='Sun',
            position=list(cell.position_body_m), normal=list(cell.normal_body),
            fov=cell.fov_half_angle_deg))
    for sensor_kind, label in [('gyro', 'Gyro'), ('mag', 'Mag')]:
        for unit in configuration.sensor_units(sensor_kind):
            position = unit.position_body_m
            if position is None:
                position = getattr(configuration, sensor_kind + '_position_body_m')
            layout.append(dict(name=unit.name, kind=label,
                position=list(position), enabled=unit.enabled))
    return layout


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
