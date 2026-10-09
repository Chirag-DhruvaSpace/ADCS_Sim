"""Onboard measurement holder and multiplicative attitude/bias EKF.

Only sensor receipts and onboard reference models enter this module.
Truth comparisons belong to operator telemetry, never filter updates.
"""
from __future__ import annotations

import numpy as np


def reconstruct_sun(outputs, normals, activation_threshold, min_cells=3):
    """Flight reconstruction from photocurrents and calibrated mount normals only."""
    outputs, normals = np.asarray(outputs, float), np.asarray(normals, float)
    normals = normals / np.linalg.norm(normals, axis=1)[:, None]
    mask = np.isfinite(outputs) & (outputs > activation_threshold)
    if np.count_nonzero(mask) < min_cells:
        return None, False, 'insufficient_cells', mask
    A = normals[mask]
    if np.linalg.matrix_rank(A) != 3:
        return None, False, 'degenerate_geometry', mask
    s = np.linalg.lstsq(A, outputs[mask], rcond=None)[0]
    length = np.linalg.norm(s)
    if length < 1e-12:
        return None, False, 'degenerate_geometry', mask
    return s / length, True, 'least_squares', mask


class ImuNav:
    """Hold the latest good gyro + magnetometer samples (the sensor belief).

    fallback_omega_rad_s / fallback_B_body_t are returned until the first
    good sample arrives (zero by default; never initialized from truth by
    the simulation loop). valid flags go False on a
    dropout tick but the last good sample is KEPT (a real flight computer
    coasts on its last good reading and marks it stale).
    """

    def __init__(self, fallback_omega_rad_s=None, fallback_B_body_t=None,
                 initial_quaternion=(1., 0., 0., 0.), sun_config=None,
                 filter_options=None, estimator_enabled=True,
                 enable_gyro_update=True, enable_magnetometer_update=True,
                 enable_sun_update=True, fusion_max_age_s=.5,
                 fusion_max_time_skew_s=.02) -> None:
        self.sun_config = sun_config
        self.estimator = AttitudeEstimator(initial_quaternion, **(filter_options or {}))
        self.estimator_enabled = bool(estimator_enabled)
        self.enable_gyro_update = bool(enable_gyro_update)
        self.enable_magnetometer_update = bool(enable_magnetometer_update)
        self.enable_sun_update = bool(enable_sun_update)
        self.fusion_max_age_s = fusion_max_age_s
        self.fusion_max_time_skew_s = fusion_max_time_skew_s
        self._unit_receipts = {'gyro': {}, 'mag': {}}
        self._unit_status = {'gyro': [], 'mag': []}
        self._omega = (np.zeros(3) if fallback_omega_rad_s is None
                       else np.asarray(fallback_omega_rad_s, dtype=float).reshape(3))
        self._B = (np.zeros(3) if fallback_B_body_t is None
                   else np.asarray(fallback_B_body_t, dtype=float).reshape(3))
        self._gyro = None
        self._mag = None
        self._sun = None
        self._gyro_valid = False       # a good gyro sample exists AND latest tick good
        self._mag_valid = False
        self._sun_valid = False
        self._gyro_saturated = False
        self._mag_saturated = False
        self._gyro_t_meas = None
        self._mag_t_meas = None
        self._sun_t_meas = None

    def update(self, t_seconds, gyro, mag, sun=None) -> None:
        """Store this tick's sensor outputs (any may be None = no tick).

        A returned measurement with valid=False is a DROPOUT sample: the
        valid flag goes False but the last good value is kept (coast).
        `sun` is the sun ARRAY receipt (SunArrayMeasurement from
        simulatesunsensor.py); reconstruction_valid is a separate, softer
        flag -- a valid receipt may still carry reconstructed_body=None
        (eclipse/degenerate geometry), which is NOT a dropout.
        """
        if isinstance(gyro, list):
            gyro = self._fuse_units(t_seconds, gyro, 'gyro')
        if isinstance(mag, list):
            mag = self._fuse_units(t_seconds, mag, 'mag')
        if gyro is not None:
            if gyro.valid:
                self._gyro = gyro
                self._omega = np.asarray(gyro.omega_body_rad_s, dtype=float).reshape(3)
                self._gyro_valid = True
                self._gyro_t_meas = float(gyro.t_meas_s)
            else:
                self._gyro_valid = False
            self._gyro_saturated = bool(gyro.saturated)
        if mag is not None:
            if mag.valid:
                self._mag = mag
                self._B = np.asarray(mag.magnetic_field_body_t, dtype=float).reshape(3)
                self._mag_valid = True
                self._mag_t_meas = float(mag.t_meas_s)
            else:
                self._mag_valid = False
            self._mag_saturated = bool(mag.saturated)
        if sun is not None:
            if sun.valid:
                if self.sun_config is not None:
                    from dataclasses import replace
                    cfg = self.sun_config
                    direction, good, method, mask = reconstruct_sun(
                        [c.output_fraction for c in sun.cells],
                        [c.normal_body for c in cfg.cells], cfg.activation_threshold,
                        cfg.min_cells_for_solution)
                    sun = replace(sun, reconstructed_body=direction,
                                  reconstruction_valid=good, method=method,
                                  cells=[replace(c, used=bool(u)) for c, u in zip(sun.cells, mask)])
                self._sun = sun                      # latest good RECEIPT kept
                self._sun_valid = True
                self._sun_t_meas = float(sun.t_meas_s)
            else:
                self._sun_valid = False              # dropout: keep last receipt

    def omega_body(self) -> np.ndarray:
        """Best-known body rate [X, Y, Z] (rad/s) -- SENSOR belief, not truth."""
        return self._omega.copy() - self.estimator.bias

    def _fuse_units(self, t, incoming, kind):
        """Calibrate and combine fresh, unsaturated receipts; never read truth.

        Weights are configured quality weights. Closely timed samples only;
        this is not an asynchronous smoother or an independent-bias EKF.
        """
        from dataclasses import replace
        from types import SimpleNamespace
        cache = self._unit_receipts[kind]
        present = {u.name for u, _ in incoming}
        for name in list(cache):
            if name not in present:
                del cache[name]
        for unit, msg in incoming:
            if msg is not None:
                cache[unit.name] = (unit, msg)
        usable = [(u, m) for u, m in cache.values() if m.valid and not m.saturated
                  and 0 <= t-m.t_meas_s <= self.fusion_max_age_s]
        newest = max((m.t_meas_s for _, m in usable), default=t)
        usable = [(u, m) for u, m in usable if newest-m.t_meas_s <= self.fusion_max_time_skew_s]
        selected = {u.name for u, _ in usable}
        self._unit_status[kind] = [dict(name=u.name, used=u.name in selected,
            valid=bool(m.valid), saturated=bool(m.saturated), age_s=max(0., t-m.t_meas_s))
            for u, m in cache.values()]
        if not usable:
            return SimpleNamespace(valid=False, saturated=False)
        field = 'omega_body_rad_s' if kind == 'gyro' else 'magnetic_field_body_t'
        weights = np.array([u.fusion_weight for u, _ in usable]); weights /= weights.sum()
        values = [np.linalg.solve(u.calibration_matrix, np.asarray(getattr(m, field))-u.calibration_bias)
                  for u, m in usable]
        return replace(usable[0][1], **{field: np.average(values, axis=0, weights=weights)},
                       t_meas_s=float(sum(w*m.t_meas_s for w, (_, m) in zip(weights, usable))),
                       t_arrival_s=float(t), valid=True, saturated=False)

    def estimate(self, t_seconds, magnetic_model_eci, sun_model_eci):
        """Fuse receipts using onboard reference models, with no truth input."""
        self.estimator.update(t_seconds,
                              self._omega if self.enable_gyro_update else self.estimator.bias.copy(),
                              self._mag if self.estimator_enabled and self.enable_magnetometer_update and self._mag_valid else None,
                              magnetic_model_eci,
                              self._sun if self.estimator_enabled and self.enable_sun_update and self._sun_valid else None,
                              sun_model_eci)

    def latest_gyro(self):
        """The most recent GOOD GyroMeasurement (None before the first one).
        The main loop uses this to decide whether a sensor sample exists."""
        return self._gyro

    def latest_mag(self):
        """The most recent GOOD MagnetometerMeasurement (None before first)."""
        return self._mag

    def latest_sun(self):
        """The most recent GOOD sun-array receipt (None before the first).
        Check receipt.reconstruction_valid before trusting reconstructed_body
        -- during eclipse the solve honestly fails and this returns a receipt
        with reconstructed_body=None."""
        return self._sun

    def sun_body(self):
        """The satellite's best-known body-frame sun direction (unit vector,
        from the array's onboard least-squares reconstruction) -- or None
        when no good receipt exists or the reconstruction failed (eclipse,
        degenerate geometry). SENSOR belief, not truth."""
        if (self._sun is not None and self._sun.reconstruction_valid
                and self._sun.reconstructed_body is not None):
            return np.asarray(self._sun.reconstructed_body, dtype=float).reshape(3).copy()
        return None

    def B_body(self) -> np.ndarray:
        """Best-known body magnetic field [X, Y, Z] (Tesla) -- SENSOR belief."""
        return self._B.copy()

    def telemetry(self) -> dict:
        """Dashboard dict. Keys exist only via this method (added only when
        the IMU is enabled); values are None until the first good sample."""
        g = self._gyro
        m = self._mag
        s = self._sun
        return {
            'imu_units': self._unit_status,
            'imu_navigation_mode': 'ekf' if self.estimator_enabled else 'gyro_only',
            "imu_gyro_valid": bool(self._gyro_valid),
            "imu_mag_valid": bool(self._mag_valid),
            "imu_sun_valid": bool(self._sun_valid),
            "imu_gyro_saturated": bool(self._gyro_saturated),
            "imu_mag_saturated": bool(self._mag_saturated),
            "imu_gyro_x_rad_s": None if g is None else float(g.omega_body_rad_s[0]),
            "imu_gyro_y_rad_s": None if g is None else float(g.omega_body_rad_s[1]),
            "imu_gyro_z_rad_s": None if g is None else float(g.omega_body_rad_s[2]),
            "imu_mag_x_nT": None if m is None else float(m.magnetic_field_body_t[0] * 1e9),
            "imu_mag_y_nT": None if m is None else float(m.magnetic_field_body_t[1] * 1e9),
            "imu_mag_z_nT": None if m is None else float(m.magnetic_field_body_t[2] * 1e9),
            "imu_sun_recon_valid": (None if s is None else bool(s.reconstruction_valid)),
            "imu_gyro_t_meas_s": self._gyro_t_meas,
            "imu_mag_t_meas_s": self._mag_t_meas,
            "imu_sun_t_meas_s": self._sun_t_meas,
        }


# ---------------------------------------------------------------------------
# The onboard ATTITUDE ESTIMATOR (the missing piece the IMU task documented).
#
# WHY IT EXISTS (plain language): a gyro measures SPIN RATE and a
# magnetometer measures a FIELD VECTOR -- neither measures attitude. The only
# way the satellite can know "which way am I pointing" from its own sensors
# is a small onboard program that combines them. Every real flight computer
# runs one; this is a basic, standard two-step version:
#
#   1. PREDICT: spin the attitude belief forward with the GYRO measurement
#      (q_dot = 0.5 * Omega(w) * q -- smooth, but it slowly drifts because
#      the gyro's bias means it never knows "still" perfectly).
#   2. CORRECT: every new magnetometer sample, compare the MEASURED body
#      field with what the onboard IGRF model says the field should be (the
#      model is computed at the GPS-believed position -- real flight software
#      has the IGRF model onboard); rotate the belief a small step toward
#      agreement. This kills the gyro drift but injects a little of the
#      magnetometer's own noise.
#
# Result: an attitude that jitters slightly and wanders a little (sensor
# noise, exactly like reality) but does not drift far (model correction).
# That jitter is what the dashboard's "pointing error (sat. own data)" shows.
# ---------------------------------------------------------------------------
def _quat_multiply(q1, q2):
    """Standard Hamilton product, scalar-first [q0,q1,q2,q3]. NOTE: this
    repo's C_bi composition is REVERSED (C_bi(qA (x) qB) = C_bi(qB) @ C_bi(qA),
    verified in the dynamics file) -- the estimator's correction below relies
    on that verified rule, so do NOT swap the arguments."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ])

def _dcm_bi_from_q(q):
    """body->ECI matrix from a scalar-first quaternion -- the repo's own
    formula (same as satellite_rotational_dynamics_var_mag_field), copied so
    this module stays lightweight (no Orekit import needed)."""
    q = np.asarray(q, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
    ])


def quat_angle_deg(q_a, q_b):
    """Angle between two attitudes [deg] -- the standard 2*acos(|dot|)."""
    dot = abs(float(np.dot(np.asarray(q_a, dtype=float).reshape(4),
                           np.asarray(q_b, dtype=float).reshape(4))))
    return 2.0 * np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))


def _skew(v):
    x, y, z = v
    return np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])


def _rotation_quaternion(v):
    angle = float(np.linalg.norm(v))
    return np.r_[np.cos(angle / 2), v * (np.sin(angle / 2) / angle if angle > 1e-12 else 0.5)]


class AttitudeEstimator:
    """Six-state multiplicative EKF: body attitude error and gyro bias.

    Quaternion convention is the simulator's passive scalar-first convention.
    Covariance has radian/rad-per-second units. Vector measurement variances
    are angular variances. Initialization is an explicit prior, not truth.
    Delayed body vectors are transported to arrival using measured rate;
    this is a constant-rate approximation, not an out-of-sequence smoother.
    """
    def __init__(self, q0_eci, correction_gain=None, gyro_noise=0.00016444,
                 bias_walk=0.0000283, mag_sigma=0.015, sun_sigma=0.025,
                 innovation_gate_chi2=16.27, max_bias_rad_s=0.005,
                 initial_attitude_sigma_deg=20., initial_bias_sigma_rad_s=0.002):
        q = np.asarray(q0_eci, float).reshape(4)
        if not np.all(np.isfinite(q)) or np.linalg.norm(q) < 1e-12:
            raise ValueError('attitude prior must be finite and nonzero')
        self._q = q / np.linalg.norm(q)
        self.bias = np.zeros(3)
        self.P = np.diag([np.radians(initial_attitude_sigma_deg)**2]*3 + [initial_bias_sigma_rad_s**2]*3)
        self.innovation_gate_chi2 = innovation_gate_chi2
        self.max_bias_rad_s = max_bias_rad_s
        self.gyro_noise, self.bias_walk = gyro_noise, bias_walk
        self.mag_sigma, self.sun_sigma = mag_sigma, sun_sigma
        self._last_t = None
        self._last_mag_t = self._last_sun_t = None
        self.corrections = self.propagations = 0
        self.sun_used_last = False

    @property
    def q_eci(self):
        return self._q.copy()

    def _correct(self, measured, reference, sigma, lag, omega):
        measured, reference = np.asarray(measured, float), np.asarray(reference, float)
        a, b = np.linalg.norm(measured), np.linalg.norm(reference)
        if not np.isfinite(a + b) or min(a, b) < 1e-15:
            return False
        past_q = _quat_multiply(self._q, _rotation_quaternion(-omega * lag))
        measured = _dcm_bi_from_q(self._q).T @ _dcm_bi_from_q(past_q) @ (measured / a)
        predicted = _dcm_bi_from_q(self._q).T @ (reference / b)
        H = np.zeros((3, 6))
        H[:, :3] = -_skew(predicted)
        R = np.eye(3) * sigma**2
        innovation = measured - predicted
        S = H @ self.P @ H.T + R
        # Reject inconsistent optical/model observations before they can be
        # integrated into gyro bias and hence the controller's rate feedback.
        if float(innovation @ np.linalg.solve(S, innovation)) > self.innovation_gate_chi2:
            return False
        K = np.linalg.solve(S, H @ self.P).T
        delta = K @ innovation
        self._q = _quat_multiply(_rotation_quaternion(delta[:3]), self._q)
        self._q /= np.linalg.norm(self._q)
        self.bias = np.clip(self.bias + delta[3:], -self.max_bias_rad_s, self.max_bias_rad_s)
        A = np.eye(6) - K @ H
        self.P = A @ self.P @ A.T + K @ R @ K.T
        # Reset the tangent error after injecting the finite correction.
        G = np.eye(6)
        G[:3, :3] -= 0.5 * _skew(delta[:3])
        self.P = G @ self.P @ G.T
        self.P = (self.P + self.P.T) / 2
        self.corrections += 1
        return True

    def update(self, t_seconds, omega_belief_body, mag_meas, B_model_eci,
               sun_meas=None, sun_model_eci=None):
        t = float(t_seconds)
        omega = np.asarray(omega_belief_body, float) - self.bias
        if self._last_t is not None:
            dt = t - self._last_t
            if dt < 0:
                raise ValueError('estimator time must not move backwards')
            if dt > 0:
                # The plant's Omega matrix is q_dot = q (x) [0,w]/2,
                # not [0,w] (x) q/2. These differ away from identity.
                midpoint = _quat_multiply(self._q, _rotation_quaternion(omega * dt * .5))
                self._q = _quat_multiply(self._q, _rotation_quaternion(omega * dt))
                self._q /= np.linalg.norm(self._q)
                # Left attitude error / right plant propagation: rate noise
                # and bias must be rotated into the error's tangent frame.
                T = _dcm_bi_from_q(midpoint).T
                Phi = np.eye(6)
                Phi[:3, 3:] = -T*dt
                G = np.vstack((-.5*dt*T, np.eye(3)))
                Qd = self.bias_walk**2*dt*(G@G.T)
                Qd[:3, :3] += np.eye(3)*(self.gyro_noise**2*dt + self.bias_walk**2*dt**3/12)
                self.P = Phi @ self.P @ Phi.T + Qd
                self.propagations += 1
        self._last_t = t
        self.sun_used_last = False
        if (mag_meas is not None and mag_meas.valid and not mag_meas.saturated
                and B_model_eci is not None and mag_meas.t_meas_s != self._last_mag_t):
            self._correct(mag_meas.magnetic_field_body_t, B_model_eci,
                          self.mag_sigma, max(0., t-mag_meas.t_meas_s), omega)
            self._last_mag_t = mag_meas.t_meas_s
        if (sun_meas is not None and sun_meas.valid and sun_meas.reconstruction_valid
                and sun_model_eci is not None and sun_meas.t_meas_s != self._last_sun_t):
            self.sun_used_last = self._correct(sun_meas.reconstructed_body, sun_model_eci,
                          self.sun_sigma, max(0., t-sun_meas.t_meas_s), omega)
            self._last_sun_t = sun_meas.t_meas_s

    def pointing_error_deg(self, q_target):
        return float(quat_angle_deg(self._q, q_target))


__all__ = ['ImuNav', 'AttitudeEstimator', 'quat_angle_deg']
