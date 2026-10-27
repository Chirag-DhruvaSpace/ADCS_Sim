# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""Tick-boundary adapter for the unchanged supplied UDP modules."""
import math
import socket
import struct
import time
from dataclasses import replace
import numpy as np

# The real board's magnetometer error, as the firmware's magApplyCal()
# (ADIS16545.c) removes it: h_cal = A @ (h_raw - b), in sensor axes. Keep in
# step with magCalBias/magCalMatrix there (and sitl_task_defs.c's copy).
BOARD_MAG_CAL_BIAS_UT = (-17.2540, -5.3328, 23.3669)
BOARD_MAG_CAL_MATRIX = ((1.046503, -0.026631, 0.010970),
                        (-0.026631, 0.977446, -0.010631),
                        (0.010970, -0.010631, 0.979232))


def with_board_magnetometer(imu_config):
    """imu_config with the board's magnetometer error added, so the raw words
    read h_raw = A^-1 @ h + b and the firmware calibration returns h. SITL
    only: the Python estimator used by the other modes has no matching
    calibration. The random hard-iron draw and white noise are not passed
    through A^-1 (sub-uT terms against a ~5% soft-iron correction)."""
    soft_iron_inverse = np.linalg.inv(np.array(BOARD_MAG_CAL_MATRIX))
    board_bias_t = np.array(BOARD_MAG_CAL_BIAS_UT) * 1e-6
    response = soft_iron_inverse @ np.asarray(imu_config.mag_response_matrix, dtype=float)
    fixed_bias = soft_iron_inverse @ np.asarray(imu_config.mag_fixed_bias_t, dtype=float) + board_bias_t
    return replace(imu_config,
                   mag_response_matrix=tuple(tuple(float(v) for v in row) for row in response),
                   mag_fixed_bias_t=tuple(float(v) for v in fixed_bias))

# Flight imuTask reads the ADIS16545 and AK09916 every 10 ms
# (DEFAULT_ICM_READ_INTERVAL), and fuseAttitude()'s per-cycle gains are tuned
# for that rate. The SITL firmware integrates each IMU sample with exactly this
# period, so Python must send one sample per 10 ms of simulated time.
FIRMWARE_IMU_RATE_HZ = 100.0


def with_firmware_imu_rate(imu_config):
    """imu_config with the gyro and magnetometer sampling at the flight imuTask
    rate. Per-sample white noise is left as configured: it is the noise of one
    read, which does not depend on how often the chip is read."""
    return replace(imu_config,
                   gyro_update_rate_hz=FIRMWARE_IMU_RATE_HZ,
                   mag_update_rate_hz=FIRMWARE_IMU_RATE_HZ)


def imu_substep_times(t, dt):
    """The IMU sample times strictly inside the physics step [t, t + dt): the
    sample at t itself goes out with the step's other sensors (tick()), these
    follow once the step has been integrated (send_imu())."""
    count = int(round(dt * FIRMWARE_IMU_RATE_HZ))
    if count < 1 or not math.isclose(count / FIRMWARE_IMU_RATE_HZ, dt, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f'physics step {dt} s is not a whole number of {1/FIRMWARE_IMU_RATE_HZ} s IMU periods')
    return [t + k * dt / count for k in range(1, count)]


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
        import sensor_link
        self.link, self.telemetry, self.sensor_link = link, telemetry, sensor_link
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
    def tick(self, position, velocity, quaternion, rates, unix_time, field_body,
             gps=None, sun=None, sun_cells=(), gyro=None, mag=None,
             star=None, epoch_unix_s=0.0):
        """rates in rad/s; sent in deg/s, the unit of AdsMdl.bodyRate.
        gps/sun/gyro/mag/star: this tick's raw sensor samples (None when the
        sensor did not sample this tick), forwarded to the ADS on sensor_link's
        port. The firmware takes its body rate and field from gyro/mag; the rate
        and field in the state packet are no longer applied (sim_link.c).
        epoch_unix_s: Unix time of sim t = 0, for the star tracker timestamp."""
        self.telemetry.send_state(self.state_socket, position, velocity, quaternion,
                                  np.degrees(np.asarray(rates, dtype=float)), unix_time, field_body)
        if gps is not None:
            self.sensor_link.send_gps(self.state_socket, gps)
        if sun is not None:
            self.sensor_link.send_fss(self.state_socket, sun, sun_cells)
        self.sensor_link.send_imu(self.state_socket, gyro, mag)
        self.sensor_link.send_star_tracker(self.state_socket, star, epoch_unix_s)
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
    def send_imu(self, gyro, mag):
        """One extra 10 ms IMU sample from inside the physics step (see
        imu_substep_times). Sent in time order; the firmware queues them and
        runs one imuTask pass per sample."""
        self.sensor_link.send_imu(self.state_socket, gyro, mag)
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
