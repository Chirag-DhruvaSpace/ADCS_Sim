"""simulategps.py -- the simulated GPS receiver ("FakeGPS"), all in one file.

WHAT THIS IS (plain language): a stand-in for the real GPS receiver chip the
satellite will carry. Once per simulated second it "reports" the satellite's
position, velocity and status, slightly wrong in the same ways a real
receiver is wrong: a constant bias, a slowly-drifting wander, fresh jitter,
~0.08 s staleness, a nanosecond-wrong clock, occasional silent seconds, and
status numbers (satellite count, geometry quality) that random-walk.

The satellite's onboard belief of where it is comes from this receiver (see
gps_navigation.py); the orbit truth keeps driving the physics unchanged, so
the two can always be compared and scored.

CONFIGURE (the ONE line, in satellite_parameters.py):
    GPS_SIM = GpsSimParameters.nominal()    # realistic (default)
    GPS_SIM = GpsSimParameters.off()        # behave exactly like before GPS
    GPS_SIM = GpsSimParameters.perfect()    # zero error (plumbing check)
    GPS_SIM = GpsSimParameters.degraded()   # errors x2.5, 5% dropouts
    GPS_SIM = GpsSimParameters.stress()     # errors x5, 15% dropouts, 30 s silence

SELF-TEST (from the project root):
    python simulategps.py            # 600 s demo, prints the first 20 messages
    python simulategps.py validate   # full three-stage proof (20 checks)

PLAIN-LANGUAGE GLOSSARY:
    ECI      "star book" coordinates (EME2000 here): what the ADCS wants.
    ECEF     "floor book" coordinates (ITRF here): what GPS chips report.
    ENU      East/North/Up compass frame at the satellite.
    bias     an error the receiver starts with and keeps (constant offset).
    wander   an error that drifts smoothly around zero, remembering where it
             was (Gauss-Markov process; tau = seconds until it forgets).
    white    fresh, memoryless jitter, redrawn every fix.
    latency  the fix describes where you WERE slightly in the past.
    dropout  a second where the receiver reports nothing.
    PDOP     geometry-quality figure a receiver reports (small = good).
    cold start / TTFF   no output right after power-on.

GOLDEN RULES (enforced below):
    1. This module NEVER advances the orbit truth -- truth (r_eci, v_eci) is
       passed IN by the simulation loop each tick.
    2. ALL randomness comes from ONE numpy generator seeded from
       GpsSimParameters.seed. No global np.random anywhere.
    3. No hand-rolled frame math -- only the Orekit transforms below (the
       full PV transform is essential: a rotation-only transform corrupts
       velocities by ~460 m/s because the Earth-fixed frame spins).
"""
from __future__ import annotations

import collections
import math
import sys
from bisect import bisect_right
from datetime import timedelta

import numpy as np

import engine.orekit_runtime  # noqa: F401  side-effect JVM bootstrap (same pattern as engine_adcs_bridge)
from engine.orekit_runtime import ensure_initialized


# ---------------------------------------------------------------------------
# Orekit helpers (verified against engine_adcs_bridge's own validated
# convention: inertial_frame.getTransformTo(itrf, date) maps ECI -> ECEF)
# ---------------------------------------------------------------------------
def absolute_date(epoch_utc, t_seconds: float):
    """Orekit AbsoluteDate at (epoch_utc + t_seconds), UTC.

    Built independently from the engine's simulation clock, so nothing here
    can advance or disturb the shared engine clock.
    """
    from org.orekit.time import AbsoluteDate, TimeScalesFactory

    dt = epoch_utc + timedelta(seconds=float(t_seconds))
    return AbsoluteDate(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                        float(dt.second) + dt.microsecond / 1e6,
                        TimeScalesFactory.getUTC())

def eci_to_ecef_pv(r_eci, v_eci, inertial_frame, itrf, date):
    """FULL position+velocity transform ECI -> ECEF.

    A rotation-only transform here is a BUG (~460 m/s velocity error): the
    Earth-fixed frame rotates, so the velocity needs the extra rotation-rate
    term that transformPVCoordinates applies. (Position-only helpers such as
    engine_adcs_bridge.vector_eci_to_ecef are for DIRECTIONS, not velocities.)
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.utils import PVCoordinates

    tf = inertial_frame.getTransformTo(itrf, date)
    pv = tf.transformPVCoordinates(PVCoordinates(
        Vector3D(float(r_eci[0]), float(r_eci[1]), float(r_eci[2])),
        Vector3D(float(v_eci[0]), float(v_eci[1]), float(v_eci[2]))))
    return (np.array([pv.getPosition().getX(), pv.getPosition().getY(), pv.getPosition().getZ()]),
            np.array([pv.getVelocity().getX(), pv.getVelocity().getY(), pv.getVelocity().getZ()]))


def ecef_to_eci_pv(p_ecef, v_ecef, inertial_frame, itrf, date):
    """Inverse of eci_to_ecef_pv: ECEF -> ECI, full position+velocity.

    Used for the onboard ECEF->ECI conversion -- exactly what flight software
    computes from a receiver message before feeding the attitude controllers.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.utils import PVCoordinates

    tf = itrf.getTransformTo(inertial_frame, date)
    pv = tf.transformPVCoordinates(PVCoordinates(
        Vector3D(float(p_ecef[0]), float(p_ecef[1]), float(p_ecef[2])),
        Vector3D(float(v_ecef[0]), float(v_ecef[1]), float(v_ecef[2]))))
    return (np.array([pv.getPosition().getX(), pv.getPosition().getY(), pv.getPosition().getZ()]),
            np.array([pv.getVelocity().getX(), pv.getVelocity().getY(), pv.getVelocity().getZ()]))


def enu_frame_at(earth_wgs84, p_ecef, itrf, date):
    """East/North/Up basis + WGS84 geodetic coordinates at an ECEF position.

    Returns (R_enu_to_ecef, lat_deg, lon_deg, alt_m) where R_enu_to_ecef
    converts ENU coordinates to ECEF:  v_ecef = R @ v_enu  (and back: R.T).
    Columns are the East/North/Up unit vectors expressed in ECEF. Orekit does
    all the geodesy -- no hand-rolled lat/lon math anywhere.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    gp = earth_wgs84.transform(
        Vector3D(float(p_ecef[0]), float(p_ecef[1]), float(p_ecef[2])), itrf, date)
    east = np.array([gp.getEast().getX(), gp.getEast().getY(), gp.getEast().getZ()])
    north = np.array([gp.getNorth().getX(), gp.getNorth().getY(), gp.getNorth().getZ()])
    up = np.array([gp.getZenith().getX(), gp.getZenith().getY(), gp.getZenith().getZ()])
    R = np.column_stack([east, north, up])
    return R, math.degrees(gp.getLatitude()), math.degrees(gp.getLongitude()), float(gp.getAltitude())


_GPS_EPOCH = None


def _gps_epoch():
    """Lazily-built GPS epoch (1980-01-06T00:00:00 GPS scale), built once."""
    global _GPS_EPOCH
    if _GPS_EPOCH is None:
        ensure_initialized()
        from org.orekit.time import AbsoluteDate, TimeScalesFactory
        _GPS_EPOCH = AbsoluteDate("1980-01-06T00:00:00.000", TimeScalesFactory.getGPS())
    return _GPS_EPOCH


def gps_week_tow(epoch_utc, t_seconds: float):
    """GPS calendar time (week, time-of-week) at (epoch_utc + t_seconds).

    Receivers run on GPS time, which is exactly 18 s ahead of UTC (leap
    seconds); Orekit's GPS/UTC time scales handle that -- no manual offsets.
    Returns (week:int, tow:float, t_gps_s:float).
    """
    t_gps_s = absolute_date(epoch_utc, t_seconds).durationFrom(_gps_epoch())
    week = int(t_gps_s // 604800.0)
    tow = t_gps_s - 604800.0 * week
    return week, tow, t_gps_s

def white_noise(rng, sigma: float) -> float:
    """One fresh, memoryless random draw of size `sigma` (zero on average)."""
    if sigma < 0.0:
        raise ValueError("white-noise sigma must be >= 0")
    return sigma * rng.standard_normal()


class GaussMarkov:
    """One axis of a slowly-wandering error (wants: sigma >= 0, tau > 0).

    Advance rule (exact for a discrete step of any size):
        b_new = exp(-dt/tau) * b + sqrt(1 - exp(-2*dt/tau)) * sigma * N(0,1)
    With dt = 0 the state is left unchanged, so the very first call is safe.
    """

    __slots__ = ("sigma", "tau", "_value")

    def __init__(self, sigma: float, tau: float, initial: float = 0.0) -> None:
        if sigma < 0.0:
            raise ValueError("GaussMarkov sigma must be >= 0")
        if tau <= 0.0:
            raise ValueError("GaussMarkov tau must be > 0")
        self.sigma = float(sigma)
        self.tau = float(tau)
        self._value = float(initial)

    @property
    def value(self) -> float:
        return self._value

    def advance(self, dt_seconds: float, rng) -> None:
        """Move the wander forward by dt_seconds of simulated time."""
        dt = float(dt_seconds)
        if dt <= 0.0:
            return
        decay = float(np.exp(-dt / self.tau))
        self._value = (decay * self._value
                       + float(np.sqrt(1.0 - decay * decay)) * self.sigma * rng.standard_normal())

    def redraw(self, rng) -> None:
        """Jump to a completely fresh draw from N(0, sigma) -- used for the
        sudden error change when the GPS constellation geometry changes."""
        self._value = self.sigma * rng.standard_normal()

    def reset(self) -> None:
        self._value = 0.0


class StepEvents:
    """Schedules the constellation-change jumps: the waiting time between
    jumps is random with a mean of `mean_interval_s` (exponential waiting
    times, like real constellation hand-overs)."""

    def __init__(self, mean_interval_s: float, rng) -> None:
        if mean_interval_s <= 0.0:
            raise ValueError("step mean interval must be > 0")
        self._mean = float(mean_interval_s)
        self._rng = rng
        self._next = float(rng.exponential(self._mean))

    def due(self, t_seconds: float) -> bool:
        return float(t_seconds) >= self._next

    def reschedule(self) -> None:
        self._next += float(self._rng.exponential(self._mean))


class ClockErrorModel:
    """The receiver's own clock error, in seconds.

    Real receivers do not know the exact time either: their clock has a fixed
    offset from true time (bias), slowly wanders, and has a little jitter on
    every reading. Realistic receivers are excellent at this -- nanoseconds --
    which is why GPS time is usable for sun-vector and magnetic-field models.
    """

    def __init__(self, cfg, rng) -> None:
        self.enabled = bool(cfg.enable_clock_error)
        if self.enabled:
            self.bias = float(cfg.clock_bias_sigma_s) * rng.standard_normal()
            self.wander = GaussMarkov(cfg.clock_wander_sigma_s, cfg.clock_wander_tau_s)
        else:
            self.bias = 0.0
            self.wander = None
        self.white_sigma = float(cfg.clock_white_sigma_s)

    def advance(self, dt_seconds: float, rng) -> None:
        if self.wander is not None:
            self.wander.advance(dt_seconds, rng)

    def sample(self, rng) -> float:
        """One reading of the clock error [s] (0 if the model is disabled)."""
        if not self.enabled:
            return 0.0
        value = self.bias
        if self.wander is not None:
            value += self.wander.value
        return value + white_noise(rng, self.white_sigma)

# ---------------------------------------------------------------------------
# GpsMeasurement -- one GPS receiver "message", in receiver-style formats.
# ---------------------------------------------------------------------------
from dataclasses import dataclass


@dataclass
class GpsMeasurement:
    """One 1 Hz GPS receiver output. Units live in the field names.

    week/tow: GPS calendar (week since 1980-01-06 + seconds into the week).
    fix_type 3 = full 3-D fix (receiver convention). vel_enu ORDER: [E, N, U].
    """

    week: int                                  # GPS week number (since 1980-01-06)
    tow: float                                 # GPS time-of-week [s], receiver clock error INCLUDED
    t_meas_s: float                            # true sim time the fix describes [s since epoch_utc]
    t_arrival_s: float                         # sim time the fix was produced at [s] (the 1 Hz grid point)
    clock_error_s: float                       # receiver clock error included in week/tow [s]
    fix_type: int                              # 3 = 3D fix (receiver convention)
    num_sv: int                                # number of satellites used (simulated random walk)
    pdop: float                                # position dilution of precision (geometry quality)
    lat_deg: float                             # WGS84 geodetic latitude [deg], quantized like a real chip
    lon_deg: float                             # WGS84 geodetic longitude [deg], quantized
    alt_ell_m: float                           # WGS84 ellipsoidal altitude [m], quantized
    pos_ecef_m: np.ndarray                     # measured position, ECEF [m] (3,)
    vel_ecef_m_s: np.ndarray                   # measured velocity, ECEF [m/s] (3,)
    vel_enu_m_s: np.ndarray                    # measured velocity in ENU [m/s] (3,) -- ORDER [East, North, Up]
    h_acc_m: float                             # receiver-reported horizontal accuracy estimate [m]
    v_acc_m: float                             # receiver-reported vertical accuracy estimate [m]
    latency_s: float                           # how stale the fix was when produced [s]
    nav_pos_eci_m: np.ndarray                  # onboard ECEF->ECI conversion of pos_ecef_m [m] (3,)
    nav_vel_eci_mps: np.ndarray                # onboard ECEF->ECI conversion of vel_ecef_m_s [m/s] (3,)


# ---------------------------------------------------------------------------
# GpsMeasurement -- one GPS receiver "message", in receiver-style formats.
# ---------------------------------------------------------------------------
from dataclasses import dataclass


@dataclass
class GpsMeasurement:
    """One 1 Hz GPS receiver output. Units live in the field names.

    week/tow: GPS calendar (week since 1980-01-06 + seconds into the week).
    fix_type 3 = full 3-D fix (receiver convention). vel_enu ORDER: [E, N, U].
    """

    week: int                                  # GPS week number (since 1980-01-06)
    tow: float                                 # GPS time-of-week [s], receiver clock error INCLUDED
    t_meas_s: float                            # true sim time the fix describes [s since epoch_utc]
    t_arrival_s: float                         # sim time the fix was produced at [s] (the 1 Hz grid point)
    clock_error_s: float                       # receiver clock error included in week/tow [s]
    fix_type: int                              # 3 = 3D fix (receiver convention)
    num_sv: int                                # number of satellites used (simulated random walk)
    pdop: float                                # position dilution of precision (geometry quality)
    lat_deg: float                             # WGS84 geodetic latitude [deg], quantized like a real chip
    lon_deg: float                             # WGS84 geodetic longitude [deg], quantized
    alt_ell_m: float                           # WGS84 ellipsoidal altitude [m], quantized
    pos_ecef_m: np.ndarray                     # measured position, ECEF [m] (3,)
    vel_ecef_m_s: np.ndarray                   # measured velocity, ECEF [m/s] (3,)
    vel_enu_m_s: np.ndarray                    # measured velocity in ENU [m/s] (3,) -- ORDER [East, North, Up]
    h_acc_m: float                             # receiver-reported horizontal accuracy estimate [m]
    v_acc_m: float                             # receiver-reported vertical accuracy estimate [m]
    latency_s: float                           # how stale the fix was when produced [s]
    nav_pos_eci_m: np.ndarray                  # onboard ECEF->ECI conversion of pos_ecef_m [m] (3,)
    nav_vel_eci_mps: np.ndarray                # onboard ECEF->ECI conversion of vel_ecef_m_s [m/s] (3,)


class SimulatedGPS:
    """The simulated receiver. Feed it the TRUE state each loop tick with
    update(t, r_eci, v_eci); it answers with a GpsMeasurement on 1 Hz
    boundaries (None otherwise, and None on dropped/cold-start seconds).

    It NEVER touches the orbit propagator -- truth comes in as arguments.
    """

    def __init__(self, orbit_provider, config) -> None:
        self.cfg = config
        # Frames/epoch are REUSED from the provider -- no new frames created.
        self.epoch_utc = orbit_provider.epoch_utc
        self.inertial_frame = orbit_provider.inertial_frame        # EME2000 ("star book")
        self.itrf = orbit_provider.earth_fixed_frame               # ITRF ("floor book")
        ensure_initialized()
        from org.orekit.bodies import OneAxisEllipsoid
        from org.orekit.utils import Constants

        # WGS84 ellipsoid built ONCE on the provider's own ITRF frame.
        self._earth_wgs84 = OneAxisEllipsoid(
            Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
            Constants.WGS84_EARTH_FLATTENING, self.itrf)

        # ONE random generator for the whole receiver (seed from config).
        self.rng = np.random.default_rng(config.seed)
        cfg = config

        # Constant biases: drawn ONCE at power-on, fixed for the whole run.
        # Horizontal axes (E, N) and the vertical axis (U) have different
        # sizes -- real GPS really is worse vertically.
        if cfg.enable_bias:
            self._pos_bias_enu = np.array([
                white_noise(self.rng, cfg.pos_bias_sigma_h_m),
                white_noise(self.rng, cfg.pos_bias_sigma_h_m),
                white_noise(self.rng, cfg.pos_bias_sigma_v_m)])
            self._vel_bias_enu = np.array([
                white_noise(self.rng, cfg.vel_bias_sigma_m_s) for _ in range(3)])
        else:
            self._pos_bias_enu = np.zeros(3)
            self._vel_bias_enu = np.zeros(3)

        # Slowly-wandering error states, one per axis (start at zero).
        self._pos_gm = ([GaussMarkov(cfg.gm_sigma_pos_h_m, cfg.gm_tau_pos_s),
                         GaussMarkov(cfg.gm_sigma_pos_h_m, cfg.gm_tau_pos_s),
                         GaussMarkov(cfg.gm_sigma_pos_v_m, cfg.gm_tau_pos_s)]
                        if cfg.enable_wander else None)
        self._vel_gm = ([GaussMarkov(cfg.gm_sigma_vel_m_s, cfg.gm_tau_vel_s) for _ in range(3)]
                        if cfg.enable_wander else None)
        self._clock = ClockErrorModel(cfg, self.rng)
        self._steps = StepEvents(cfg.step_mean_interval_s, self.rng) if cfg.enable_steps else None

        # Status random walks (satellite count, geometry quality).
        self._num_sv = int(cfg.num_sv_start)
        self._pdop = float(cfg.pdop_start)

        # Bookkeeping: no output before the first boundary; truth history for
        # the latency lookback (100 samples x 0.1 s ~ 10 s -- far more than
        # the 0.2 s maximum latency ever needs).
        self._last_t = None
        self._last_grid_k = -1
        self._history = collections.deque(maxlen=100)
        self.boundaries_seen = 0        # 1 Hz grid points crossed (for dropout stats)
        self.step_count = 0             # constellation-change jumps so far

        # In-memory records for the validation harness.
        self.records = []

    def update(self, t_seconds, r_eci_m, v_eci_mps):
        """Feed one loop tick of TRUTH; returns GpsMeasurement on 1 Hz
        boundaries (else None). Called in time order, exactly once per tick.
        """
        cfg = self.cfg
        t = float(t_seconds)
        r_eci = np.asarray(r_eci_m, dtype=float).reshape(3)
        v_eci = np.asarray(v_eci_mps, dtype=float).reshape(3)

        # The orbit provider is stateful and only moves forward, so out-of-
        # order calls would silently feed nonsense -- fail loudly instead.
        if self._last_t is not None and t <= self._last_t:
            raise ValueError(
                f"SimulatedGPS.update received t={t} but the previous call was t={self._last_t}. "
                "Time must move forward: the truth provider is stateful, never rewind it.")

        dt = 0.0 if self._last_t is None else t - self._last_t
        self._last_t = t
        self._history.append((t, r_eci.copy(), v_eci.copy()))

        # 1) advance every wandering error by this tick's duration
        if self._pos_gm is not None:
            for gm in self._pos_gm:
                gm.advance(dt, self.rng)
        if self._vel_gm is not None:
            for gm in self._vel_gm:
                gm.advance(dt, self.rng)
        self._clock.advance(dt, self.rng)

        # 2) constellation-change jump: instantly redraw the position wander
        #    (the geometry changed, so the receiver's slowly-varying errors
        #    jump to a fresh draw). Velocity wander is unaffected.
        if self._steps is not None and self._pos_gm is not None and self._steps.due(t):
            for gm in self._pos_gm:
                gm.redraw(self.rng)
            self._steps.reschedule()
            self.step_count += 1

        # 3) output scheduling: one output per 1 Hz grid point. If this tick
        #    does not cross a boundary, there is nothing to say this tick.
        period = 1.0 / cfg.update_rate_hz
        k = math.floor(t / period + 1e-9)
        if k <= self._last_grid_k:
            return None
        t_grid = k * period
        # IMPORTANT: the boundary is consumed in EVERY branch below (including
        # dropouts) so a dropped second is never retried later.
        self._last_grid_k = k
        self.boundaries_seen += 1

        # 4) availability gates: cold start, scheduled outages, random dropout
        if t < cfg.cold_start_s:
            return None
        for window in cfg.outages_s:
            if window[0] <= t <= window[1]:
                return None
        if cfg.enable_dropout and cfg.p_dropout > 0.0 and self.rng.random() < cfg.p_dropout:
            return None

        # 5) latency: the fix describes the slightly-past state
        if cfg.enable_latency:
            tau = float(np.clip(self.rng.normal(cfg.latency_mean_s, cfg.latency_sigma_s),
                                cfg.latency_min_s, cfg.latency_max_s))
        else:
            tau = 0.0
        t_meas = t_grid - tau

        # 6) truth at t_meas: linear interpolation between the two bracketing
        #    buffered samples (the buffer holds ~10 s, latency needs <= 0.6 s;
        #    only in the first second of a run can t_meas fall off the front).
        times = [h[0] for h in self._history]
        if len(times) < 2 or t_meas < times[0]:
            return None
        j = bisect_right(times, t_meas) - 1
        if j > len(times) - 2:
            j = len(times) - 2
        t0, r0, v0 = self._history[j]
        t1, r1, v1 = self._history[j + 1]
        w = (t_meas - t0) / (t1 - t0)
        r_interp = r0 + w * (r1 - r0)
        v_interp = v0 + w * (v1 - v0)

        # 7) ECI -> ECEF with the FULL PV transform (rotation-only would be a
        #    ~460 m/s velocity bug), then the ENU basis and WGS84 geodetic.
        date = absolute_date(self.epoch_utc, t_meas)
        true_pos_ecef, true_vel_ecef = eci_to_ecef_pv(
            r_interp, v_interp, self.inertial_frame, self.itrf, date)
        R_enu, _, _, _ = enu_frame_at(self._earth_wgs84, true_pos_ecef, self.itrf, date)

        # 8) status random walks (satellite count, geometry quality)
        if cfg.enable_status:
            self._num_sv = int(np.clip(self._num_sv + (1 if self.rng.random() < 0.5 else -1),
                                       cfg.num_sv_min, cfg.num_sv_max))
            self._pdop = float(np.clip(self._pdop + self.rng.normal(0.0, cfg.pdop_step_sigma),
                                       cfg.pdop_min, cfg.pdop_max))

        # 9) the error components (each only if its enable flag is on). The
        #    velocity errors are INDEPENDENT draws -- real receivers get
        #    velocity from a different mechanism (Doppler), so the velocity
        #    error must not be correlated with the position error.
        err_pos_enu = np.zeros(3)
        err_vel_enu = np.zeros(3)
        if cfg.enable_bias:
            err_pos_enu += self._pos_bias_enu
            err_vel_enu += self._vel_bias_enu
        if self._pos_gm is not None:
            err_pos_enu += np.array([gm.value for gm in self._pos_gm])
        if self._vel_gm is not None:
            err_vel_enu += np.array([gm.value for gm in self._vel_gm])
        if cfg.enable_white_noise:
            err_pos_enu += np.array([
                white_noise(self.rng, cfg.white_sigma_pos_h_m),
                white_noise(self.rng, cfg.white_sigma_pos_h_m),
                white_noise(self.rng, cfg.white_sigma_pos_v_m)])
            err_vel_enu += np.array([
                white_noise(self.rng, cfg.white_sigma_vel_m_s) for _ in range(3)])

        # ENU error -> ECEF error through the local East/North/Up basis.
        meas_pos_ecef = true_pos_ecef + R_enu @ err_pos_enu
        meas_vel_ecef = true_vel_ecef + R_enu @ err_vel_enu
        # The receiver also reports velocity in its own compass frame (ENU):
        # the TRUE velocity expressed in ENU, plus the same ENU error.
        meas_vel_enu = R_enu.T @ true_vel_ecef + err_vel_enu

        # 10) clock error: the reported time is stamped with the receiver's
        #     own (slightly wrong) clock, like a real chip. GPS week/tow are
        #     computed from that reported time.
        clock_err = self._clock.sample(self.rng)
        t_reported = t_meas + clock_err
        week, tow, _ = gps_week_tow(self.epoch_utc, t_reported)

        # 11) reported accuracy -- real receivers are OVERCONFIDENT (they
        #     quote roughly 60% of their actual horizontal error), which is
        #     reproduced here on purpose.
        actual_h = math.hypot(err_pos_enu[0], err_pos_enu[1])
        h_acc = max(0.5, 0.6 * actual_h + self.rng.normal(0.0, 0.2))
        v_acc = 1.6 * h_acc

        # 12) the reported lat/lon/alt come from the MEASURED (wrong)
        #     position, because that is what a real receiver reports.
        _, lat_deg, lon_deg, alt_m = enu_frame_at(self._earth_wgs84, meas_pos_ecef, self.itrf, date)
        if cfg.enable_quantization:
            lat_deg = round(lat_deg / 1e-7) * 1e-7        # 1e-7 deg ~ 1 cm
            lon_deg = round(lon_deg / 1e-7) * 1e-7
            alt_m = round(alt_m / 1e-3) * 1e-3            # 1 mm
            meas_vel_enu = np.round(np.asarray(meas_vel_enu) / 1e-3) * 1e-3   # 1 mm/s
        # NOTE: pos_ecef_m / vel_ecef_m_s are NOT quantized (real receivers'
        # binary outputs are float).

        # 13) the onboard conversion every flight computer does: receiver
        #     ECEF message -> ECI for the attitude controllers.
        nav_pos_eci, nav_vel_eci = ecef_to_eci_pv(
            meas_pos_ecef, meas_vel_ecef, self.inertial_frame, self.itrf, date)

        msg = GpsMeasurement(
            week=week, tow=tow, t_meas_s=t_meas, t_arrival_s=t_grid,
            clock_error_s=clock_err, fix_type=3, num_sv=int(self._num_sv),
            pdop=float(self._pdop), lat_deg=lat_deg, lon_deg=lon_deg, alt_ell_m=alt_m,
            pos_ecef_m=meas_pos_ecef, vel_ecef_m_s=meas_vel_ecef,
            vel_enu_m_s=meas_vel_enu, h_acc_m=h_acc, v_acc_m=v_acc, latency_s=tau,
            nav_pos_eci_m=nav_pos_eci, nav_vel_eci_mps=nav_vel_eci)

        # 14) in-memory record (truth columns are validation-only)
        rec = {
            "t_meas_s": t_meas, "t_arrival_s": t_grid, "week": week, "tow": tow,
            "clock_error_s": clock_err, "fix_type": msg.fix_type,
            "num_sv": msg.num_sv, "pdop": msg.pdop, "latency_s": tau,
            "truth_pos_ecef": true_pos_ecef, "truth_vel_ecef": true_vel_ecef,
            "truth_pos_eci": r_interp, "truth_vel_eci": v_interp,
            "meas_pos_ecef": np.asarray(meas_pos_ecef), "meas_vel_ecef": np.asarray(meas_vel_ecef),
            "err_pos_enu": err_pos_enu, "err_vel_enu": err_vel_enu,
            "h_acc_m": h_acc, "v_acc_m": v_acc,
            "nav_pos_eci": np.asarray(nav_pos_eci), "nav_vel_eci": np.asarray(nav_vel_eci),
        }
        self.records.append(rec)
        return msg

# ---------------------------------------------------------------------------
# SELF-TEST: python simulategps.py [demo|validate]
# ---------------------------------------------------------------------------
def run_demo() -> None:
    """600 s standalone tour with the NOMINAL (realistic) profile: prints the
    first 20 receiver messages plus summary statistics."""
    print("=" * 78)
    print(" GPS SIMULATOR DEMO -- 600 s, NOMINAL profile (realistic errors)")
    print("=" * 78)

    ensure_initialized()
    import satellite_parameters as config
    from engine_adcs_bridge import EngineOrbitProvider
    provider = EngineOrbitProvider(epoch_utc=config.EPOCH_UTC)
    print(f"epoch: {provider.epoch_utc}  orbit: "
          f"{config.ORBIT.altitude_m / 1000.0:.1f} km, i={config.ORBIT.inclination_deg} deg")

    gps = SimulatedGPS(provider, config.GPS_SIM)

    import time
    msgs = []
    t0 = time.perf_counter()
    for i in range(1, 6001):                      # 600 s at 0.1 s
        t = i * 0.1
        r_vec, v_vec = provider.state_at(t)
        msg = gps.update(t, r_vec, v_vec)
        if msg is not None:
            msgs.append(msg)
    wall = time.perf_counter() - t0

    missing = gps.boundaries_seen - len(gps.records)
    print(f"flew 600 s in {wall:.1f} s wall clock; {gps.boundaries_seen} receiver "
          f"seconds, {len(gps.records)} fixes, {missing} missing seconds "
          f"(dropouts + the first-second lookback edge)")

    print("\nfirst 20 receiver messages (lat/lon = the receiver's measured position):")
    print(f"{'t_arr':>6} {'lat_deg':>11} {'lon_deg':>11} {'alt_m':>10} "
          f"{'sv':>3} {'pdop':>5} {'h_acc':>6} {'latency':>8}")
    for m in msgs[:20]:
        print(f"{m.t_arrival_s:6.1f} {m.lat_deg:11.5f} {m.lon_deg:11.5f} "
              f"{m.alt_ell_m:10.2f} {m.num_sv:3d} {m.pdop:5.2f} "
              f"{m.h_acc_m:6.2f} {m.latency_s:8.3f}")

    err = np.array([r["err_pos_enu"] for r in gps.records])
    verr = np.array([r["err_vel_enu"] for r in gps.records])
    lat = np.array([r["latency_s"] for r in gps.records])
    print("\nsummary statistics (NOMINAL profile):")
    print(f"  position error std  E/N/U : "
          f"{err[:, 0].std():.3f} / {err[:, 1].std():.3f} / {err[:, 2].std():.3f} m")
    print(f"  position error mean E/N/U : "
          f"{err[:, 0].mean():+.3f} / {err[:, 1].mean():+.3f} / {err[:, 2].mean():+.3f} m")
    print(f"  velocity error std  E/N/U : "
          f"{verr[:, 0].std():.4f} / {verr[:, 1].std():.4f} / {verr[:, 2].std():.4f} m/s")
    print(f"  mean latency              : {lat.mean() * 1000.0:.1f} ms "
          f"(min {lat.min() * 1000.0:.1f}, max {lat.max() * 1000.0:.1f})")
    print(f"  constellation-change steps: {gps.step_count}")
    print("\ndone.")

# --- validation harness state ------------------------------------------------
_VAL_RESULTS = []                 # (stage, name, ok, detail)
_VAL_DT = 0.1
_STAGE1_END, _STAGE2_END, _STAGE3_END = 1800.0, 3600.0, 15600.0


def _check(stage: str, name: str, ok: bool, detail: str) -> None:
    _VAL_RESULTS.append((stage, name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {stage:<8} {name}: {detail}", flush=True)


def _drive(provider, gps: SimulatedGPS, t_start: float, t_end: float, label: str) -> None:
    """Feed truth exactly like the main loop: step 0.1 s, call update().
    The provider is stateful -- times only ever move forward."""
    import time
    n_steps = int(round((t_end - t_start) / _VAL_DT))
    t0 = time.perf_counter()
    next_progress = t_start + 1200.0
    for i in range(1, n_steps + 1):
        t = t_start + i * _VAL_DT
        r_vec, v_vec = provider.state_at(t)
        gps.update(t, r_vec, v_vec)
        if t >= next_progress and i < n_steps:
            print(f"    [{label}] t={t:.0f}s ({len(gps.records)} fixes, "
                  f"{time.perf_counter() - t0:.0f}s wall)...", flush=True)
            next_progress += 1200.0
    print(f"    [{label}] done: {len(gps.records)} fixes in "
          f"{time.perf_counter() - t0:.0f}s wall", flush=True)

def _check_perfect(provider, gps: SimulatedGPS) -> None:
    """Stage 1: every error switched OFF -- the receiver must return the
    truth (to numerical noise) in every format it reports."""
    recs = gps.records

    pos_err = max(float(np.linalg.norm(r["meas_pos_ecef"] - r["truth_pos_ecef"]))
                  for r in recs)
    _check("PERFECT", "1 position==truth", pos_err < 1e-3,
           f"max |meas-truth| = {pos_err:.3e} m (< 1e-3)")

    vel_err = max(abs(float(np.linalg.norm(r["meas_vel_ecef"]))
                      - float(np.linalg.norm(r["truth_vel_ecef"]))) for r in recs)
    _check("PERFECT", "2 velocity==truth", vel_err < 0.05,
           f"max ||v_meas|-|v_truth|| = {vel_err:.3e} m/s (< 0.05; rotation-only bug would fail by ~460)")

    nav_err = max(float(np.linalg.norm(r["nav_pos_eci"] - r["truth_pos_eci"])) for r in recs)
    _check("PERFECT", "3 ECEF->ECI roundtrip", nav_err < 1e-3,
           f"max |nav_pos_eci - truth_eci| = {nav_err:.3e} m (< 1e-3)")

    worst = 0.0
    for a, b in zip(recs, recs[1:]):
        dt = b["t_arrival_s"] - a["t_arrival_s"]
        dp = (b["meas_pos_ecef"] - a["meas_pos_ecef"]) / dt
        v_mean = 0.5 * (a["meas_vel_ecef"] + b["meas_vel_ecef"])
        worst = max(worst, float(np.linalg.norm(dp - v_mean)))
    _check("PERFECT", "4 p/v self-consistency", worst < 10.0,
           f"max |dp/dt - v| = {worst:.3f} m/s (< 10 over 1 s gaps)")

    arr = [r["t_arrival_s"] for r in recs]
    gaps_ok = all(abs(b - a - 1.0) < 1e-9 for a, b in zip(arr, arr[1:]))
    _check("PERFECT", "5 one output per second", len(recs) == 1800 and gaps_ok,
           f"{len(recs)} outputs (expect 1800, k=1..1800; k=0 is the first-second "
           f"lookback edge), cadence gaps {'all exactly 1.0 s' if gaps_ok else 'IRREGULAR'}")

    # 6) ENU basis sanity, recomputed independently from buffered truth
    from org.orekit.bodies import OneAxisEllipsoid
    from org.orekit.utils import Constants
    earth = OneAxisEllipsoid(Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
                             Constants.WGS84_EARTH_FLATTENING, provider.earth_fixed_frame)
    worst_ang, worst_ez = 0.0, 0.0
    for r in recs[::73]:
        R, _, _, _ = enu_frame_at(earth, r["truth_pos_ecef"], provider.earth_fixed_frame,
                                  absolute_date(provider.epoch_utc, r["t_meas_s"]))
        phat = r["truth_pos_ecef"] / np.linalg.norm(r["truth_pos_ecef"])
        cosang = float(np.clip(np.dot(R @ np.array([0.0, 0.0, 1.0]), phat), -1.0, 1.0))
        worst_ang = max(worst_ang, math.degrees(math.acos(cosang)))
        worst_ez = max(worst_ez, abs(float(np.dot(R @ np.array([1.0, 0.0, 0.0]),
                                                  [0.0, 0.0, 1.0]))))
    _check("PERFECT", "6 ENU basis sanity", worst_ang < 0.5 and worst_ez < 0.01,
           f"max angle(R@up, r_hat) = {worst_ang:.4f} deg (< 0.5), "
           f"max |R@east . z_hat| = {worst_ez:.2e} (< 0.01)")

    # 7) GPS time is exactly 18 s ahead of UTC, measured by parsing the SAME
    #    wall-clock string on both scales (their difference IS the offset).
    #    (Comparing the two 1980 epochs directly gives 0 -- both strings denote
    #    the SAME physical instant, because the GPS epoch is DEFINED as
    #    1980-01-06T00:00:00 UTC, when TAI-UTC = 19 s = TAI-GPS.)
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    s_utc = "2026-06-01T12:00:00.000"
    offset = float(AbsoluteDate(s_utc, TimeScalesFactory.getUTC()).durationFrom(
        AbsoluteDate(s_utc, TimeScalesFactory.getGPS())))
    _check("PERFECT", "7 GPS-UTC == 18 s", abs(offset - 18.0) < 1e-6,
           f"offset = {offset:.9f} s (18.0 +/- 1e-6)")

    # 8) week/tow must reconstruct the measurement time. week/tow encode the
    #    receiver's GPS-clock reading = physical seconds elapsed since the
    #    GPS-epoch instant, so the measurement instant is simply GPS epoch
    #    instant + that reading. (The 18 s GPS-UTC offset is NOT applied
    #    here: it matters only when converting week/tow into a UTC wall-clock
    #    reading, and it is verified separately in check 7.)
    gps_epoch_utc = AbsoluteDate("1980-01-06T00:00:00.000", TimeScalesFactory.getUTC())
    epoch_date = absolute_date(provider.epoch_utc, 0.0)
    worst_t = 0.0
    for r in recs:
        t_gps = r["week"] * 604800.0 + r["tow"]
        recon = gps_epoch_utc.shiftedBy(t_gps).durationFrom(epoch_date)
        worst_t = max(worst_t, abs(recon - (r["t_meas_s"] + r["clock_error_s"])))
    _check("PERFECT", "8 week/tow reconstruct time", worst_t < 1e-3,
           f"max |recon - t_meas| = {worst_t:.3e} s (< 1e-3)")

def _check_white(gps: SimulatedGPS) -> None:
    """Stage 2: only fresh jitter enabled -- the scatter of the error must
    match the configured jitter size (per axis), and Up must be worse than
    horizontal in the configured ratio."""
    recs = gps.records
    err = np.array([r["err_pos_enu"] for r in recs])       # (N, 3) E/N/U
    stds = err.std(axis=0)                                  # population std
    target = np.array([0.5, 0.5, 0.8])                      # white sigmas
    lo, hi = target * 0.8, target * 1.2
    ok9 = bool(np.all(stds >= lo) and np.all(stds <= hi))
    _check("WHITE", "9 jitter std per axis", ok9,
           f"std E/N/U = {stds[0]:.3f}/{stds[1]:.3f}/{stds[2]:.3f} m "
           f"(targets 0.5/0.5/0.8, +/-20%)")

    ratio = stds[2] / (0.5 * (stds[0] + stds[1]))
    _check("WHITE", "10 U/H ratio 1.6", 1.2 <= ratio <= 2.0,
           f"std_U / mean(std_E,std_N) = {ratio:.3f} (1.6 +/- 25%)")


def _check_nominal(gps: SimulatedGPS) -> None:
    """Stage 3: the full realistic model -- statistics must match the
    configured error sizes and behaviours."""
    recs = gps.records
    err = np.array([r["err_pos_enu"] for r in recs])
    stds = err.std(axis=0)
    means = err.mean(axis=0)

    # 11) position std vs sqrt(gm^2 + white^2) per axis
    target = np.array([math.sqrt(1.4**2 + 0.5**2),
                       math.sqrt(1.4**2 + 0.5**2),
                       math.sqrt(2.7**2 + 0.8**2)])
    ok11 = bool(np.all(stds >= target * 0.75) and np.all(stds <= target * 1.25))
    _check("NOMINAL", "11 position std", ok11,
           f"std E/N/U = {stds[0]:.3f}/{stds[1]:.3f}/{stds[2]:.3f} m "
           f"(targets {target[0]:.2f}/{target[1]:.2f}/{target[2]:.2f}, +/-25%)")

    # 12) |mean error| small (bias draw + wander average)
    ok12 = bool(abs(means[0]) < 2.5 and abs(means[1]) < 2.5 and abs(means[2]) < 4.0)
    _check("NOMINAL", "12 mean error", ok12,
           f"mean E/N/U = {means[0]:+.3f}/{means[1]:+.3f}/{means[2]:+.3f} m "
           f"(|E|,|N| < 2.5, |U| < 4.0)")

    # 13) velocity error std vs sqrt(0.03^2 + 0.01^2)
    verr = np.array([r["err_vel_enu"] for r in recs])
    vstd = verr.std(axis=0)
    vtgt = math.sqrt(0.03**2 + 0.01**2)
    ok13 = bool(np.all(vstd >= 0.7 * vtgt) and np.all(vstd <= 1.3 * vtgt))
    _check("NOMINAL", "13 velocity std", ok13,
           f"std E/N/U = {vstd[0]:.4f}/{vstd[1]:.4f}/{vstd[2]:.4f} m/s "
           f"(target {vtgt:.4f}, +/-30%)")

    # 14) the wander must actually wander: autocorrelation time of the East
    #     error ~ tau=60 s (pure white noise would drop below 0.5 instantly)
    x = err[:, 0] - err[:, 0].mean()
    var = float(np.mean(x * x))
    acf_lag = None
    for lag in range(1, 301):
        if float(np.mean(x[:-lag] * x[lag:]) / var) < 0.5:
            acf_lag = lag
            break
    _check("NOMINAL", "14 wander autocorrelation",
           acf_lag is not None and 20 <= acf_lag <= 80,
           f"first lag with ACF < 0.5 = {acf_lag} s (expect ~42 s, window [20, 80])")

    # 15) latency statistics
    lat = np.array([r["latency_s"] for r in recs])
    ok15 = bool(abs(lat.mean() - 0.08) <= 0.015 and lat.min() >= 0.04 and lat.max() <= 0.20)
    _check("NOMINAL", "15 latency", ok15,
           f"mean={lat.mean():.4f} s (0.08+/-0.015), min={lat.min():.3f} (>=0.04), "
           f"max={lat.max():.3f} (<=0.20)")

    # 16) dropout fraction vs p_dropout
    frac = 1.0 - len(recs) / max(1, gps.boundaries_seen)
    _check("NOMINAL", "16 dropout fraction", abs(frac - 0.005) <= 0.01,
           f"{1.0 - frac:.4f} of {gps.boundaries_seen} boundaries delivered "
           f"(p_dropout=0.005, +/-0.01)")

    # 17) constellation-change jumps happened
    _check("NOMINAL", "17 constellation steps", gps.step_count >= 3,
           f"{gps.step_count} steps in {_STAGE3_END - _STAGE2_END:.0f} s "
           f"(mean interval 600 s, need >= 3)")

    # 18) status fields always inside their clamps, fix_type always 3D
    ok18 = bool(all(5 <= r["num_sv"] <= 12 and 1.2 <= r["pdop"] <= 4.0
                    and r["fix_type"] == 3 for r in recs))
    _check("NOMINAL", "18 num_sv/pdop/fix_type", ok18,
           f"num_sv in [5,12], pdop in [1.2,4.0], fix_type==3 for all {len(recs)} fixes")

    # 19) reported accuracy is overconfident (median ratio ~0.6, not ~1.0)
    ratios = np.array([r["h_acc_m"] / math.hypot(r["err_pos_enu"][0], r["err_pos_enu"][1])
                       for r in recs])
    med = float(np.median(ratios))
    _check("NOMINAL", "19 overconfident accuracy", 0.3 <= med <= 1.1,
           f"median(h_acc / actual_h) = {med:.3f} (expect ~0.6, window [0.3, 1.1])")

    # 20) clock error stays nanosecond-small
    cmax = max(abs(r["clock_error_s"]) for r in recs)
    _check("NOMINAL", "20 clock error", cmax < 2e-6,
           f"max |clock_error| = {cmax:.3e} s (< 2e-6)")


def run_validation() -> None:
    """Three sequential stages on ONE shared forward-only orbit, then a
    PASS/FAIL table; exits non-zero if ANY check failed."""
    import sys
    import time
    from dataclasses import replace

    print("=" * 78, flush=True)
    print(" GPS SIMULATOR VALIDATION (three stages, one shared forward-only orbit)",
          flush=True)
    print("=" * 78, flush=True)

    ensure_initialized()
    import satellite_parameters as config
    from satellite_parameters import GpsSimParameters
    from engine_adcs_bridge import get_orbit_provider
    provider = get_orbit_provider()          # one shared provider, forward-only
    print(f"  epoch     : {config.EPOCH_UTC}", flush=True)
    print(f"  loop step : {_VAL_DT} s (same as the real simulation loop)", flush=True)
    print(f"  stages    : PERFECT [0,{_STAGE1_END:.0f}]s, WHITE "
          f"[{_STAGE1_END:.0f},{_STAGE2_END:.0f}]s, NOMINAL "
          f"[{_STAGE2_END:.0f},{_STAGE3_END:.0f}]s", flush=True)

    # ---- Stage 1: PERFECT --------------------------------------------------
    print("\n[stage 1/3] PERFECT -- every error switched OFF", flush=True)
    gps1 = SimulatedGPS(provider, GpsSimParameters.perfect())
    _drive(provider, gps1, 0.0, _STAGE1_END, "PERFECT")
    _check_perfect(provider, gps1)

    # ---- Stage 2: WHITE (perfect + fresh jitter only, quantization OFF) ----
    print("\n[stage 2/3] WHITE -- perfect + white noise only, quantization OFF", flush=True)
    cfg2 = replace(GpsSimParameters.perfect(), enable_white_noise=True)
    gps2 = SimulatedGPS(provider, cfg2)
    _drive(provider, gps2, _STAGE1_END, _STAGE2_END, "WHITE")
    _check_white(gps2)

    # ---- Stage 3: NOMINAL (the full realistic model) -----------------------
    print("\n[stage 3/3] NOMINAL -- full realistic error model", flush=True)
    gps3 = SimulatedGPS(provider, GpsSimParameters.nominal())
    _drive(provider, gps3, _STAGE2_END, _STAGE3_END, "NOMINAL")
    _check_nominal(gps3)

    # ---- Report -------------------------------------------------------------
    failed = [r for r in _VAL_RESULTS if not r[2]]
    print("\n" + "=" * 78, flush=True)
    print(f" RESULT: {len(_VAL_RESULTS) - len(failed)}/{len(_VAL_RESULTS)} checks PASSED",
          flush=True)
    print("=" * 78, flush=True)
    for stage, name, ok, detail in _VAL_RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {stage:<8} {name}", flush=True)
    if failed:
        print("\nFAILED CHECKS:", flush=True)
        for stage, name, _, detail in failed:
            print(f"  {stage} {name}: {detail}", flush=True)
        sys.exit(1)
    print("\nAll validation checks passed.", flush=True)
    print(f"(total wall time: {time.perf_counter() - _VAL_T0:.0f} s)", flush=True)


_VAL_T0 = 0.0

if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "demo"
    if mode in ("validate", "v", "validation"):
        import time
        _VAL_T0 = time.perf_counter()  # module global, read by run_validation()
        run_validation()
    elif mode in ("demo", "d", ""):
        run_demo()
    else:
        print("usage: python simulategps.py [demo|validate]")
        sys.exit(2)