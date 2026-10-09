# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""Tick-boundary adapter for the unchanged supplied UDP modules."""
import math
import socket
import struct
import time
import numpy as np

class PacketSocket:
    def __init__(self, sock, fmt, notify, wheel=False):
        self.sock, self.fmt, self.notify, self.wheel = sock, fmt, notify, wheel
    def recvfrom(self, size):
        while True:
            data, address = self.sock.recvfrom(size)
            if len(data) != struct.calcsize(self.fmt):
                continue
            values = struct.unpack(self.fmt, data)
            if not all(math.isfinite(value) for value in values):
                continue
            if self.wheel and (values[0] != round(values[0]) or not 0 <= values[0] <= 3 or values[1] != 0):
                continue
            self.notify()
            return data, address
    def __getattr__(self, name):
        return getattr(self.sock, name)

class FirmwareLink:
    def __init__(self):
        import firmware_sitl_link as link
        import telemetry
        self.link, self.telemetry = link, telemetry
        self.state_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.received_at = self.event_at = None
        self.last_mode = None
        self.stable_since = None
        link._cmd_sock = PacketSocket(link._cmd_sock, link.CMD_FORMAT, self.received, True)
        link._mode_sock = PacketSocket(link._mode_sock, link.MODE_STATUS_FORMAT, self.received)
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    def received(self):
        now = time.monotonic()
        if self.received_at is None or now-self.received_at > 2:
            self.event_at = now
        self.received_at = now
    def tick(self, position, velocity, quaternion, rates, unix_time, field_body):
        self.telemetry.send_state(self.state_socket, position, velocity, quaternion, rates, unix_time, field_body)
        self.link.poll_rw_torques()
        self.link.poll_mode()
        with self.link._lock:
            wheels = np.array(self.link._latest_torque_mNm)*1e-3
            dipole = np.array(self.link._latest_mtr_dipole_Am2)
            mode = self.link._latest_ads_mode[0]
        if mode != self.last_mode:
            if self.received_at is not None:
                self.event_at = time.monotonic()
            self.last_mode = mode
            self.stable_since = None
        return wheels, dipole
    def finish_tick(self, dt):
        self.link.step_wheel_momentum(dt)
        self.link.send_rw_telemetry()
    def metadata(self, t, errors, rates):
        mode = self.link.get_latest_ads_mode_name()
        error = errors.get(mode)
        settled = error is not None and error < .5 and np.linalg.norm(np.degrees(rates)) < .05
        self.stable_since = (t if self.stable_since is None else self.stable_since) if settled else None
        now = time.monotonic()
        state = ('red' if self.received_at is None or now-self.received_at > 2 else
                 'green' if self.event_at is not None and now-self.event_at < 2 else
                 'blue' if self.stable_since is not None and t-self.stable_since >= 1 else 'yellow')
        return dict(ads_mode=mode, firmware_pointing_error_deg=error, custom_pointing_status=state,
                    firmware_packet_age_s=None if self.received_at is None else now-self.received_at,
                    firmware_wheel_speed_rpm=[h/self.link.RW_MOI*60/(2*np.pi) for h in self.link._wheel_momentum])
