"""Optional nonblocking raw-sensor TCP export (newline-delimited JSON).

The main simulation supplies its fresh receipts through one lazy function.
No collection/encoding happens without a receiver. Off-grid samples are null;
dropout receipts retain their validity flags. Slow receivers lose ticks rather
than slowing the physics. Only one bounded packet is retained.
"""
import errno
import json
import math
import select
import socket
import time


def _value(value): #pyhton list to json ``
    if hasattr(value, 'tolist'):
        return _value(value.tolist())
    if isinstance(value, (list, tuple)):
        return [_value(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def get_raw_sensor_data(t, gps=None, gyro=None, mag=None, sun=None):
    """Collect public hardware packets; never navigation or truth diagnostics."""
    from sensor_packets import packet_dict

    def units(incoming):
        if isinstance(incoming, list):
            return [{'name': unit.name, 'sample': packet_dict(sample)}
                    for unit, sample in incoming]
        return packet_dict(incoming)

    return {'version': 2, 't_sim_s': float(t), 'gps': packet_dict(gps),
            'gyroscope': units(gyro), 'magnetometer': units(mag),
            'sun_sensors': packet_dict(sun)}


class SensorDataSender:
    def __init__(self, host='127.0.0.1', port=5005, retry_s=2.0):
        self.address = (host, port)
        self.retry_s = retry_s
        self.sock = None
        self.connected = False
        self.next_retry = 0.0
        self.deadline = 0.0
        self.pending = b''

    def close(self):
        if self.sock is not None:
            self.sock.close()
        self.sock = None
        self.connected = False
        self.pending = b''
        self.next_retry = time.monotonic() + self.retry_s

    def send_simulated_sensor_data(self, collect):
        """Call collect() only when connected and ready; never block."""
        now = time.monotonic()
        try:
            if self.sock is None:
                if now < self.next_retry:
                    return False
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setblocking(False)
                result = self.sock.connect_ex(self.address)
                if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK,
                                  errno.EALREADY, 10035, 10036, 10037):
                    self.close()
                    return False
                self.connected = result == 0
                self.deadline = now + 2.0
            readable, writable, exceptional = select.select(
                [self.sock], [self.sock], [self.sock], 0)
            if exceptional:
                self.close()
                return False
            if not self.connected:
                if writable:
                    if self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                        self.close()
                        return False
                    self.connected = True
                elif now >= self.deadline:
                    self.close()
                    return False
                else:
                    return False
            if readable and not self.sock.recv(1, socket.MSG_PEEK):
                self.close()
                return False
            if self.pending and now >= self.deadline:
                self.close()
                return False
            if not writable:
                return False
            if not self.pending:
                self.pending = (json.dumps(collect(), allow_nan=False,
                                separators=(',', ':')) + '\n').encode('utf-8')
                if len(self.pending) > 1024 * 1024:
                    self.pending = b''
                    return False
                self.deadline = now + 2.0
            sent = self.sock.send(self.pending)
            self.pending = self.pending[sent:]
            return not self.pending
        except BlockingIOError:
            return False
        except OSError:
            self.close()
            return False
