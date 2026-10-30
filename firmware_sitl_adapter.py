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


# ADIS16545-1 (+/-125 deg/s) gyroscope error figures, Analog Devices product
# page / datasheet Rev. A, 1 sigma. Bias repeatability is the turn-on to turn-on
# bias the firmware sees (it has no gyro-bias estimation), so it is the
# startup bias; in-run bias stability drives the slow wander.
ADIS16545_ANGLE_RANDOM_WALK_DEG_RTHR = 0.07
ADIS16545_IN_RUN_BIAS_STABILITY_DEG_HR = 0.5
ADIS16545_BIAS_REPEATABILITY_DEG_HR = 63.0


def with_adis16545_gyro(imu_config):
    """imu_config with the gyro's random errors set to the ADIS16545 figures
    above, for the firmware IMU rate. SITL only. White noise is per sample:
    ARW [deg/sqrt(s)] * sqrt(sample rate). Wander keeps its configured time
    constant; scale error and misalignment are left as configured."""
    arw_deg_rts = ADIS16545_ANGLE_RANDOM_WALK_DEG_RTHR / 60.0
    return replace(imu_config,
                   gyro_white_noise_sigma_rad_s=math.radians(arw_deg_rts * math.sqrt(FIRMWARE_IMU_RATE_HZ)),
                   gyro_bias_sigma_rad_s=math.radians(ADIS16545_BIAS_REPEATABILITY_DEG_HR / 3600.0),
                   gyro_wander_sigma_rad_s=math.radians(ADIS16545_IN_RUN_BIAS_STABILITY_DEG_HR / 3600.0))


def imu_substep_times(t, dt):
    """Capture boundaries strictly inside the outer step; never look ahead."""
    count = int(round(dt * FIRMWARE_IMU_RATE_HZ))
    if count < 1 or not math.isclose(count / FIRMWARE_IMU_RATE_HZ, dt, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f'physics step {dt} s is not a whole number of {1/FIRMWARE_IMU_RATE_HZ} s IMU periods')
    return [t + k * dt / count for k in range(1, count)]


def integrate_firmware_step(t, dt, state, solve_segment, firmware, pacer,
                            acquire_imu, set_commands, *, defer_endpoint_publish=False):
    """Integrate only to the next IMU capture, then acquire and accept commands.

    The first capture/command poll is done by tick(). All subsequent captures
    use committed states, paced on wall time, before their following solve.
    No dense-output lookahead samples are transmitted.

    With defer_endpoint_publish, accepted state stays internal until the next
    acquisition deadline. The caller publishes endpoint wheel telemetry there;
    this leaves preparation work inside the packet interval's wall-time budget.
    """
    boundaries = [t, *imu_substep_times(t, dt), t+dt]
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if index:
            lag = pacer.wait_firmware_sample(start, 1/FIRMWARE_IMU_RATE_HZ)
            firmware.schedule_lag_s = max(firmware.schedule_lag_s, lag)
            firmware.send_imu(*acquire_imu(start, state[:4], state[4:7]))
            set_commands(*firmware.poll_commands(end-start))
        result = solve_segment(start, end, state)
        if not result.success or not math.isclose(result.t[-1], end, abs_tol=1e-10):
            raise RuntimeError(f'Firmware attitude step failed: {result.message}')
        state = result.y[:, -1].copy()
        state[:4] /= np.linalg.norm(state[:4])
        if not defer_endpoint_publish:
            lag = pacer.wait_firmware_sample(end, 1/FIRMWARE_IMU_RATE_HZ)
            firmware.schedule_lag_s = max(firmware.schedule_lag_s, lag)
        publish = index == len(boundaries)-2 and not defer_endpoint_publish
        if len(state) == 11:
            firmware.finish_tick(end-start, publish=publish, wheel_momentum=state[7:11])
        else:
            firmware.finish_tick(end-start, publish=publish)
    return state


def _valid_actuator_command(values):
    """An ACS SITL actuator packet (rwNo, mode, value): a wheel torque for
    wheels 0..3 or a torquer current for rods 0..2."""
    index, mode = values[0], values[1]
    if index != round(index):
        return False
    if mode == 0:
        return 0 <= index <= 3
    if mode == 2:
        return 0 <= index <= 2
    return False


class PacketSocket:
    def __init__(self, sock, fmt, notify, wheel=False):
        self.sock, self.fmt, self.notify, self.wheel = sock, fmt, notify, wheel
    def recvfrom(self, size):
        # Malformed traffic must not consume an unbounded sensor interval.
        for _ in range(256):
            data, address = self.sock.recvfrom(size)
            if len(data) != struct.calcsize(self.fmt):
                continue
            values = struct.unpack(self.fmt, data)
            if not all(math.isfinite(value) for value in values):
                continue
            if self.wheel and not _valid_actuator_command(values):
                continue
            self.notify()
            return data, address
        raise BlockingIOError('Packet validation budget exhausted')
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
        self.schedule_lag_s = 0.
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
             star=None, epoch_unix_s=0.0, control_period_s=None):
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
            import satellite_parameters as config
            self.sensor_link.send_fss(self.state_socket, sun, sun_cells,
                full_scale_counts=config.IMU_SIM.sun_array.fine_total_signal_counts,
                white_noise_enabled=config.IMU_SIM.sun_array.enable_white_noise)
        self.sensor_link.send_imu(self.state_socket, gyro, mag)
        self.sensor_link.send_star_tracker(self.state_socket, star, epoch_unix_s)
        return self.poll_commands(control_period_s)

    def poll_commands(self, control_period_s=None):
        """Drain new commands before the next causal physics interval."""
        self.link.poll_rw_torques()
        self.link.poll_mode()
        if control_period_s is None:
            import satellite_parameters as config
            control_period_s = config.CONTROL.control_loop_period_s
        wheels, dipole = self.link.apply_actuator_limits(control_period_s)
        with self.link._lock:
            mode = self.link._latest_ads_mode[0]
        if mode != self.last_mode:
            if self.received_at is not None:
                self.event_at = time.monotonic()
            self.last_mode = mode
            self.stable_since = None
        return wheels, dipole
    def send_imu(self, gyro, mag):
        """Send the current committed 10 ms capture at its paced boundary."""
        self.sensor_link.send_imu(self.state_socket, gyro, mag)
    def finish_tick(self, dt, publish=True, wheel_momentum=None):
        if wheel_momentum is None:
            self.link.step_wheel_momentum(dt)
        else:
            self.link.set_wheel_momentum(wheel_momentum)
        if publish:
            self.link.send_rw_telemetry()
    def metadata(self, t, errors, rates):
        mode = self.link.get_latest_ads_mode_name()
        reference = self.link.get_latest_fuse_source_name()
        reference_age = self.link.get_latest_fuse_source_age_s()
        reference_fresh = reference_age is not None and reference_age < 2.
        error = errors.get(mode)
        settled = error is not None and error < .5 and np.linalg.norm(np.degrees(rates)) < .05
        self.stable_since = (t if self.stable_since is None else self.stable_since) if settled else None
        now = time.monotonic()
        freshness = self.link.command_freshness()
        known = [(age, fresh) for ages, flags in
                 [(freshness['wheel_age_s'], freshness['wheel_fresh']),
                  (freshness['rod_age_s'], freshness['rod_fresh'])]
                 for age, fresh in zip(ages, flags) if age is not None]
        command_state = ('waiting' if not known else 'expired' if not any(f for _, f in known)
                         else 'partial_expiry' if not all(f for _, f in known) else 'fresh')
        state = ('red' if self.received_at is None or now-self.received_at > 2 else
                 'green' if self.event_at is not None and now-self.event_at < 2 else
                 'blue' if self.stable_since is not None and t-self.stable_since >= 1 else 'yellow')
        if command_state in ('waiting', 'expired'):
            state = 'red'
        elif command_state == 'partial_expiry':
            state = 'yellow'
        return dict(ads_mode=mode, firmware_pointing_error_deg=error, custom_pointing_status=state,
                    att_est_source=reference if reference_fresh else 'Awaiting fresh firmware status',
                    firmware_reference_age_s=reference_age,
                    star_tracker_used=reference_fresh and reference == 'Star tracker',
                    firmware_packet_age_s=None if self.received_at is None else now-self.received_at,
                    firmware_wheel_speed_rpm=[h/self.link.RW_MOI*60/(2*np.pi) for h in self.link._wheel_momentum],
                    firmware_command_freshness=freshness,
                    firmware_command_state=command_state,
                    firmware_schedule_lag_s=self.schedule_lag_s,
                    firmware_sensor_configuration=getattr(self, "sensor_configuration", {}))
