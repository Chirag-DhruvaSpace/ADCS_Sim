import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, timezone
from scipy.integrate import solve_ivp
import time
import requests 
#import satellite_rotational_dynamics_fixed_mag_field as srd
import satellite_rotational_dynamics_var_mag_field as srd  
import calculate_disturbances as cd
import torque_distribution as td
import moon_pointing as mpt
import nadir_pointing as nad
import nominal_in_orbit_pointing as niop
import kinematic_robustness_pointing as krp
import quat2eul as q2e 
import control_states as cs   # requested UI mode (SUN_POINTING/RW/MOON/...); needed for the DETUMBLE-fallback target below
#import matplotlib.pyplot as plt 
#import satellite_params as sp 
#import pandas as pd 
from scipy.spatial.transform import Rotation as R 
import store 
import satellite_params as sp
import satellite_parameters as config
import engine_adcs_bridge as engine_bridge
#import ground_track_velocity as gtv 
#import yaw_steering 
#import satellite_footprint as sf 
#import matplotlib.pyplot as plt
#import cartopy.crs as ccrs
#import cartopy.feature as cfeature
#import video_stream as vs 
#import rasterio 
#from pyproj import Transformer 
#import cv2 

#epoch_utc = datetime.now(timezone.utc) 
epoch_utc = config.EPOCH_UTC

# Engine-backed orbital propagation is the authoritative source of truth for the
# ADCS loop. The legacy hand-rolled solve_ivp orbit model is intentionally kept
# only as a compatibility path for the older root-level helpers.
_orbit_provider = engine_bridge.get_orbit_provider(epoch_utc)

# ---- Simulated GPS receiver ("FakeGPS") -- see simulategps.py docstring -----
# The satellite's POSITION/VELOCITY KNOWLEDGE now comes from a simulated GPS
# receiver (simulategps.py) instead of the perfect truth (bias + wander +
# noise + latency + dropouts, like a real chip). gps_navigation.py turns the
# raw receiver messages into what the satellite needs (ECI position/velocity,
# dead-reckoning between 1 Hz fixes). Physics and environment (magnetic field,
# SRP, sun/moon directions, true pointing-error metrics, rendering) keep using
# the TRUE r_vec/v_vec -- only the ADCS's position/velocity KNOWLEDGE is
# GPS-based. Turn GPS off / change intensity with the ONE line in
# satellite_parameters.py:
#   GPS_SIM = GpsSimParameters.off() / .perfect() / .nominal() / .degraded() / .stress()
from simulategps import SimulatedGPS
from gps_navigation import GpsNav
_gps_sim = SimulatedGPS(_orbit_provider, config.GPS_SIM) if config.GPS_SIM.enabled else None
_gps_nav = GpsNav(*_orbit_provider.initial_state())   # launch-vehicle-provided start

# ---- Simulated IMU (gyroscope + magnetometer) -- see simulateimu.py --------
# Hardware receives environment truth. ImuNav reconstructs sunlight and runs
# the attitude/bias MEKF from receipts and onboard reference models only.
# Control uses that belief; true state remains in plant physics and diagnostics.
from simulateimu import SimulatedIMU
from imu_navigation import ImuNav
_imu_sim = SimulatedIMU(config.IMU_SIM, record_history=False) if config.IMU_SIM.enabled else None
_imu_nav = ImuNav(initial_quaternion=config.IMU_SIM.initial_estimate_quaternion,
                  sun_config=config.IMU_SIM.sun_array,
                  filter_options=dict(
                      gyro_noise=config.IMU_SIM.gyro_white_noise_sigma_rad_s / np.sqrt(config.IMU_SIM.gyro_update_rate_hz),
                      bias_walk=config.IMU_SIM.gyro_wander_sigma_rad_s * np.sqrt(2 / config.IMU_SIM.gyro_wander_tau_s),
                      mag_sigma=np.radians(config.IMU_SIM.estimator_mag_sigma_deg),
                      sun_sigma=np.radians(config.IMU_SIM.estimator_sun_sigma_deg),
                      innovation_gate_chi2=config.IMU_SIM.estimator_innovation_gate_chi2,
                      max_bias_rad_s=config.IMU_SIM.estimator_max_bias_rad_s,
                      initial_attitude_sigma_deg=config.IMU_SIM.estimator_initial_attitude_sigma_deg,
                      initial_bias_sigma_rad_s=config.IMU_SIM.estimator_initial_bias_sigma_rad_s),
                  fusion_max_age_s=config.IMU_SIM.fusion_max_age_s,
                  fusion_max_time_skew_s=config.IMU_SIM.fusion_max_time_skew_s,
                  estimator_enabled=config.IMU_SIM.enable_attitude_estimator,
                  enable_gyro_update=config.IMU_SIM.enable_gyro_update,
                  enable_magnetometer_update=config.IMU_SIM.enable_magnetometer_update,
                  enable_sun_update=config.IMU_SIM.enable_sun_update)
# Onboard ATTITUDE ESTIMATOR: the satellite's own attitude belief, computed
# from its own sensors (gyro propagation + magnetometer correction against
# the onboard IGRF model at the GPS-believed position). This is what makes
# "pointing error according to the satellite's own data" real.
_att_est = _imu_nav.estimator

from telemetry_transport import LatestTelemetryPublisher
_telemetry_publisher = LatestTelemetryPublisher(config.SIMULATION.telemetry_url, config.SIMULATION.telemetry_timeout_s, command_sink=cs.accept_pointing_command)
_telemetry_publish_interval_s = config.SIMULATION.telemetry_publish_period_s
_last_telemetry_publish_monotonic = 0.0
from uuid import uuid4
_telemetry_session_id = str(uuid4())
_telemetry_sequence = 0


def sun_position_eci(utc_time):
    """Convert the existing Earth-to-Sun unit direction into an ECI position."""
    return _orbit_provider.sun_position_eci()


def eci_to_ecef_dcm(utc_time):
    """ECI->ECEF rotation matrix at utc_time, built by transforming the 3 ECI basis
    vectors through the same astropy GCRS->ITRS conversion already used/validated for
    the sun-direction line (eci_to_ecef.eci_vec_to_ecef). Columns = ECI basis vectors
    expressed in ECEF, i.e. v_ecef = M @ v_eci."""
    time_s = (utc_time - epoch_utc).total_seconds()
    ex = _orbit_provider.vector_eci_to_ecef(np.array([1.0, 0.0, 0.0]), time_s)
    ey = _orbit_provider.vector_eci_to_ecef(np.array([0.0, 1.0, 0.0]), time_s)
    ez = _orbit_provider.vector_eci_to_ecef(np.array([0.0, 0.0, 1.0]), time_s)
    M = np.column_stack([ex, ey, ez])
    for col in range(3):
        M[:, col] /= np.linalg.norm(M[:, col])
    return M

# --- Required (target) attitude for sun pointing, for display alongside the current
#     yaw/pitch/roll so per-axis accuracy can be read directly, not just the combined
#     error angle. Q_TARGET is static (set once at import from the sun-pointing target
#     frame), so this is computed once here rather than every loop iteration. NOTE: since
#     the sun-pointing target is only 2-DOF (rotation about the sun-line, i.e. the
#     "boresight roll" is unconstrained), one of these three numbers reflects an
#     arbitrary-but-fixed choice made when the target frame was built, not something the
#     controller is actually trying to hold -- see build_target_frame() in
#     periodic_lqr_design.py. The other two are the meaningful ones to compare against.
_qt = srd.sun_pointing.Q_TARGET
_target_yaw_deg, _target_pitch_deg, _target_roll_deg = np.degrees(
    q2e.euler_from_quaternion(_qt[0], _qt[1], _qt[2], _qt[3])
)

# --- Step 1: Initial state from orbital elements ---
r0, v0 = _orbit_provider.initial_state()
state0 = np.concatenate((r0, v0))          # [x, y, z, vx, vy, vz]

# --- RW saturation warning throttle ------------------------------------------
# Console warnings for reaction-wheel saturation are time-throttled (at most
# one every 300 simulated seconds) so a wheel sitting near its momentum limit
# doesn't print one line per second for hours. The huge negative start value
# lets the first warning fire immediately.
def run_simulation(tf=config.SIMULATION.default_duration_s, dt=config.CONTROL.control_loop_period_s):
    global _imu_sim, _telemetry_sequence

    firmware = None
    if config.POINTING['strategy'] == 'firmware_sitl':
        from firmware_sitl_adapter import FirmwareLink
        firmware = FirmwareLink()
    t = 0.0
    tf = float(tf)
    dt = float(dt)

    # Initial states: use the engine-propagated orbit state as the authoritative
    # ADCS data source, matching the validated main.py engine usage.
    X_trans = state0.copy()   # [r, v]
    X_rot   = srd.y0.copy()   # [q, w]


    utc_time = epoch_utc 

    from engine.simulation.pacing import SimulationPacer
    pacer = SimulationPacer(config.SIMULATION.speed)
    speed_path = Path(config.__file__).with_suffix('.yaml')
    custom_stable_since = None
    last_custom_command_id = None

    while t < tf:

        pacer.poll_speed(speed_path, t)
        pacer.wait_until(t)

        # ---- ENGINE-BASED TRANSLATION SOURCE ----
        r_vec, v_vec = _orbit_provider.state_at(t)
        t = float(_orbit_provider.clock.time)  # Orekit elapsed time is authoritative.
        _orbit_provider.set_attitude(t, X_rot[:4], X_rot[4:7])
        X_trans = np.concatenate((r_vec, v_vec))

        # ---- GPS KNOWLEDGE (simulated receiver; see simulategps.py) ----
        # The receiver is fed the TRUE state each tick and answers only on 1 Hz
        # boundaries (None otherwise, and None on dropped/cold-start seconds).
        # Between fixes the onboard holder dead-reckons with the last fix. The
        # ADCS below navigates on this knowledge (r_vec_nav/v_vec_nav); the
        # magnetic field, SRP, sun/moon/nadir directions, pointing-error
        # metrics and rendering keep using the TRUE r_vec/v_vec -- those are
        # physical environment measured by their own sensors; only position/
        # velocity knowledge comes from GPS.
        if _gps_sim is not None:
            _msg = _gps_sim.update(t, r_vec, v_vec)
            _boundary_had_fix = _msg is not None
            if _msg is not None:
                _gps_nav.register_fix(_msg, _boundary_had_fix)
            else:
                _gps_nav.register_boundary_no_fix()   # dropout second: keep last fix
            r_vec_nav, v_vec_nav = _gps_nav.extrapolate(t)
        else:
            r_vec_nav, v_vec_nav = r_vec, v_vec       # GPS disabled: unchanged behavior

        # ---- TIME UPDATE ----
        utc_time = epoch_utc + timedelta(seconds=t)
        
        # ---- POSITION ----
        r_vec = X_trans[:3]
        v_vec = X_trans[3:]

        B_eci = _orbit_provider.magnetic_field_eci(t, r_vec)

        # ---- SRP + ECLIPSE (moved above the IMU block) ----------------------
        # The sun sensor array's penumbra channel needs the engine lighting
        # ratio each tick (F in [0,1]); the same result feeds the disturbance
        # telemetry further down. Sensor physics uses TRUE geometry -- the
        # environment hitting hardware.
        tick_environment = _orbit_provider.surface_result(t, r_vec, v_vec, X_rot[:4])
        srp_result = _orbit_provider.srp_result(t, r_vec, v_vec, X_rot[:4], surface_result=tick_environment)

        # The Sun's ECI direction from the GPS clock -- needed by the IMU's
        # coarse sun sensor and the onboard attitude estimator (CLAUDE.md §5:
        # the direction itself needs no sensor, only the time).
        sun_eci = _orbit_provider.sun_position_eci()
        sun_eci = sun_eci / np.linalg.norm(sun_eci)
    
        # ---- IMU KNOWLEDGE (simulated gyro + magnetometer; see simulateimu.py)
        # The loop has the TRUE attitude quaternion + body rate (X_rot) and the
        # TRUE ECI field (B_eci above). Feed them to the sensor; the returned
        # MEASUREMENTS go to imu_navigation.ImuNav (the flight-software sensor
        # belief). B_sensor_eci is the sensor's view of the environment field:
        # physics below keeps integrating the TRUE state, but the CONTROLLERS
        # (detumble's B-dot, the MTR cross-product law) now steer from these
        # noisy sensor inputs whenever an IMU switch below is True.
        # B_sensor_body is recomputed INSIDE the dynamics from the propagated
        # quaternion (C_bi.T @ B_sensor_eci), exactly like the truth path --
        # the sensor belief therefore stays consistent with the body frame
        # even between 10 Hz IMU ticks.
        B_sensor_eci = B_eci
        from imu_mount_settings import consume_mount_config
        mount_config = consume_mount_config()
        if mount_config is not None:
            config.IMU_SIM = mount_config
            _imu_nav.sun_config = mount_config.sun_array
            _imu_nav._unit_receipts = {'gyro': {}, 'mag': {}}
            _imu_sim = SimulatedIMU(mount_config, record_history=False) if mount_config.enabled else None
        if _imu_sim is not None:
            _gyro_msg, _mag_msg, _sun_msg = _imu_sim.update(
                t, X_rot[:4], X_rot[4:7], B_eci, sun_eci,
                eclipse_fraction=srp_result.eclipse_fraction,
                position_eci=r_vec)
            _imu_nav.update(t, _gyro_msg, _mag_msg, _sun_msg)
            # use_mag_for_control switch: the magnetic laws (B-dot detumble,
            # MTR cross-product) see the SENSOR's field only when True; False
            # keeps them on the true field (A/B test the magnetometer alone).
            if _imu_nav.latest_mag() is not None and config.IMU_SIM.use_mag_for_control:
                B_sensor_body_now = _imu_nav.B_body()
                C_now = srd._dcm_bi_from_q(_att_est.q_eci)
                B_sensor_eci = C_now @ B_sensor_body_now
            # ---- Onboard attitude estimator (satellite's own data) ----
            # PREDICT from the gyro belief, CORRECT against the onboard IGRF
            # model evaluated at the GPS-BELIEVED position (real flight
            # software computes the same model onboard -- this is not the
            # truth channel, it is a model + the sensor's own reading).
            B_model_eci = _orbit_provider.magnetic_field_eci(t, r_vec_nav)
            _imu_nav.estimate(t, B_model_eci, sun_eci)
            if config.IMU_SIM.use_mag_for_control:
                B_sensor_eci = srd._dcm_bi_from_q(_att_est.q_eci) @ _imu_nav.B_body()
            # FULL sensor belief to the ADCS: measured rate, measured field,
            # and the ESTIMATED attitude -- the controllers (every mode) now
            # steer on what the satellite BELIEVES, exactly like real flight
            # software. The physics still integrates the true state.
            srd.set_imu_adcs_input(config.IMU_SIM.use_gyro_for_control,
                                   _imu_nav.omega_body(), _imu_nav.B_body(),
                                   q_belief_eci=_att_est.q_eci,
                                   use_attitude=config.IMU_SIM.use_attitude_estimate_for_control)
        else:
            srd.set_imu_adcs_input(False, use_attitude=False)

        # ---- ROTATION STEP (LIVE CONTROLS READ HERE) ----
        

        
        # Environment is sampled once per 0.1 s control tick; facet incidence
        # and moment arms are re-evaluated at every attitude RK stage.
        tick_sun = _orbit_provider.sun_position_eci()
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        air = _orbit_provider._atmosphere.getVelocity(_orbit_provider.clock.absolute_date(),
            Vector3D(*map(float, r_vec)), _orbit_provider.inertial_frame)
        tick_air = np.array([air.getX(), air.getY(), air.getZ()])
        facet_cache = [None, None, None]
        def facets_at(stage_t, stage_q):
            # SRP and drag request the same RK-stage geometry; evaluate it once.
            if facet_cache[0] != stage_t or facet_cache[1] is None or not np.array_equal(facet_cache[1], stage_q):
                facet_cache[:] = [stage_t, np.array(stage_q, copy=True),
                    _orbit_provider._surface_model.evaluate(stage_q, r_vec, v_vec, tick_sun,
                        tick_environment.eclipse_fraction, tick_environment.density_kg_m3, tick_air)]
            return facet_cache[2]
        srp_torque_for_step = lambda stage_t, stage_q: facets_at(stage_t, stage_q).srp_torque_body_nm
        drag_torque_for_step = lambda stage_t, stage_q: facets_at(stage_t, stage_q).drag_torque_body_nm

        if firmware is not None:
            wheels, dipole = firmware.tick(r_vec, v_vec, X_rot[:4], X_rot[4:7], utc_time.timestamp(),
                srd._dcm_bi_from_q(X_rot[:4]).T @ B_eci)
            srd.set_firmware_tick(wheels, dipole)
        custom_tick_command = cs.get_pointing_command()
        srd.set_custom_tick_target(custom_tick_command['desired_quaternion'])
        try:
            sol_rot = solve_ivp(
                lambda t, y: srd.rotational_equations_of_motion(
                    t, y, B_sensor_eci, r_vec_nav, v_vec_nav,
                    truth_field_eci=B_eci, truth_position_eci=r_vec, truth_velocity_eci=v_vec,   # ADCS navigates on GPS knowledge;
                    external_torque_body=srp_torque_for_step if cd.DISTURBANCES_ENABLED and sp.ENABLE_SRP and sp.ENABLE_SRP_TORQUE else None,
                    aerodynamic_torque_body=drag_torque_for_step,
                ),                                             # controllers sense the B_sensor_eci field above
                (t, t + dt),
                X_rot,
                rtol=config.SIMULATION.attitude_integrator_rel_tolerance,
                atol=config.SIMULATION.attitude_integrator_abs_tolerance
            )
        finally:
            srd.set_custom_tick_target(None)


        # Publish measurements and truth at the same sampling epoch t.
        # Commit the propagated state only after publishing this tick.
        X_rot_next = sol_rot.y[:, -1].copy()
        X_rot_next[:4] /= np.linalg.norm(X_rot_next[:4])
        q = X_rot[:4]
        X_rot[:4] = q / np.linalg.norm(q)

        # Advance the null-space wheel-momentum desaturation state by this
        # chunk's duration. Done here (once per OUTER step), same reasoning
        # as the sun-pointing reference governor just below: this MUST NOT
        # be called from inside rotational_equations_of_motion's ODE
        # right-hand-side, which solve_ivp evaluates an integrator-dependent
        # number of times per chunk (rejected trial steps, internal RK
        # stages, not necessarily in increasing time order) -- integrating
        # momentum in there would double/triple-count torque within a
        # single real second. td.reaction_wheel_torque_distribution() itself
        # (called from inside the RHS, once per mode branch) only READS the
        # current momentum state to compute the null-space correction --
        # that's safe to do many times per step; only the WRITE needs to
        # happen exactly once, here.
        if firmware is None:
            td.integrate_wheel_momentum(dt)

        # ---- RW SATURATION READOUT (once per outer step, after the momentum
        # state has advanced) ----
        # Makes the wheel limits VISIBLE rather than silent: the per-wheel
        # torques actually being commanded (post-clip, post-reallocation, in
        # mN*m), each wheel's stored momentum (mN*m*s), each wheel's fraction
        # of its momentum capacity used, and which wheels had their command
        # cut by saturation on the dynamics' most recent RHS pass. All of it
        # rides the existing telemetry POST (rw_* keys in data_to_send), so
        # the dashboard can pick it up from /api/latest without any Flask
        # changes.
        rw_torques_mnm = np.asarray(store.rw_torques) * 1000.0
        rw_momentum_mnms = (np.array(firmware.link._wheel_momentum) if firmware is not None else td.get_wheel_momentum()) * 1000.0
        rw_sat_fraction = np.abs(rw_momentum_mnms*.001)/td.MAX_WHEEL_MOMENTUM if firmware is not None else td.get_wheel_saturation_fraction()
        rw_torque_limited = td.get_last_command_limited()

        # Advance the sun-pointing reference governor by this chunk's wall-clock duration.
        # Done here (once per OUTER step), not inside rotational_equations_of_motion's ODE
        # right-hand-side, which solve_ivp evaluates an integrator-dependent number of times
        # per chunk -- advancing paced progress there would make the maneuver's speed depend
        # on solver internals instead of real elapsed time. See periodic_gain_sun_pointing.py.
        srd.sun_pointing.step_governor(dt)

        if firmware is not None:
            firmware.finish_tick(dt)

        # Physical integration, sensor sampling, momentum and reference governor
        # always advance. Display calculations run only when publication is due.
        now_monotonic = time.monotonic()
        global _last_telemetry_publish_monotonic
        publish_due = now_monotonic - _last_telemetry_publish_monotonic >= _telemetry_publish_interval_s
        if not publish_due:
            X_rot = X_rot_next
            t += dt
            continue
        lat, lon, alt = _orbit_provider.geodetic_at(t, r_vec_nav)
        truth_lat, truth_lon, truth_alt = _orbit_provider.geodetic_at(t, r_vec)

        # ---- DISTURBANCE TORQUE READOUT (once per outer step) ----
        # Live per-source disturbance magnitudes from calculate_disturbances.py,
        # body frame. Net vector sent in N*m (same SI convention as the existing
        # srp_torque_body_* fields); per-source magnitudes in µN*m because these
        # are 1-2 orders of magnitude below the SRP torque and would all print
        # as 0.000000 in mN*m. SRP is intentionally not included here -- it rides
        # the srp_* telemetry fields from solar_radiation_pressure.py.
        # Publish all disturbances at epoch t, matching orbit and sensors.
        dist_tau_body, dist_parts = cd.disturbance_torque_body(X_rot[:4], r_vec, v_vec, B_eci,
            drag_torque_body=srp_result.drag_torque_body_nm)
        dist_tau_body = dist_tau_body + srp_result.torque_body_nm
        dist_net_unm = np.linalg.norm(dist_tau_body) * 1e6
        dist_gg_unm = np.linalg.norm(dist_parts['gravity_gradient']) * 1e6
        dist_dipole_unm = np.linalg.norm(dist_parts['residual_dipole']) * 1e6
        dist_drag_unm = np.linalg.norm(dist_parts['atmospheric_drag']) * 1e6

        # ---- ATTITUDE ----
        q0, q1, q2, q3 = X_rot[:4]
        yaw, pitch, roll = np.degrees(q2e.euler_from_quaternion(q0, q1, q2, q3))

        # ---- TARGET EULER ANGLES for the 6 reaction-wheel modes ----------
        # Previously only "POINTING" (sun-pointing via MTR) sent its target
        # as Euler angles -- the other 6 modes' targets exist on the backend
        # (store.X_target_quat, set inside each mode branch of
        # rotational_equations_of_motion) but were never converted/sent, so
        # the dashboard's "Required Yaw/Pitch/Roll" readout only ever had
        # data to show for that one mode. Computed unconditionally every
        # cycle here, same pattern as the pointing-error metrics already
        # being sent for every mode regardless of which is currently active.
        nadir_target_yaw_deg, nadir_target_pitch_deg, nadir_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.nadir_target_quat))
        moon_target_yaw_deg, moon_target_pitch_deg, moon_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.moon_target_quat))
        sun_sweep_target_yaw_deg, sun_sweep_target_pitch_deg, sun_sweep_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.sun_sweep_target_quat))
        sun_pointing_rw_target_yaw_deg, sun_pointing_rw_target_pitch_deg, sun_pointing_rw_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.sun_pointing_rw_target_quat))
        nominal_in_orbit_target_yaw_deg, nominal_in_orbit_target_pitch_deg, nominal_in_orbit_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.nominal_in_orbit_target_quat))
        kinematic_robustness_target_yaw_deg, kinematic_robustness_target_pitch_deg, kinematic_robustness_target_roll_deg = \
            np.degrees(q2e.euler_from_quaternion(*store.kinematic_robustness_target_quat))
        
        #alignment = yaw_steering.check_yaw_alignment(r_vec, v_vec, yaw)
        #---- ATTITUDE RATES ----
        w_x_deg, w_y_deg, w_z_deg = np.degrees(X_rot[4]), np.degrees(X_rot[5]), np.degrees(X_rot[6])    
        w_net = np.sqrt(w_x_deg**2 + w_y_deg**2 + w_z_deg**2)

        # Same force used by the orbital propagator, at the published epoch.
        drag_acc_eci = srp_result.drag_force_eci_n / config.MASS_KG

        
        
        # ---- SUN DIRECTION (for the sun-pointing line in the viewer) ----
        # Sun unit vector in ECI, converted to ECEF (Cesium's world frame is ECEF-based).
        sun_eci = _orbit_provider.sun_position_eci()
        sun_eci = sun_eci / np.linalg.norm(sun_eci)
        sun_ecef = _orbit_provider.vector_eci_to_ecef(sun_eci, t)
        sun_ecef = sun_ecef / np.linalg.norm(sun_ecef)

        # ---- TRUE ORIENTATION FOR RENDERING (body -> ECEF quaternion) ----
        # NOT built from Euler angles + local-horizon Heading/Pitch/Roll: this
        # satellite's attitude is inertially referenced (sun-pointing must stay fixed
        # relative to the sun, not the local horizon), but the sub-satellite ENU/horizon
        # frame itself sweeps through nearly a full rotation every orbit. Rendering an
        # inertially-stable attitude through ENU-relative HPR made it appear to tumble
        # once per orbit even though the underlying physics was stable. Instead we
        # compose body->ECI (already have as C_bi, same formula used in the dynamics)
        # with ECI->ECEF directly, and send the resulting quaternion as-is.
        C_bi = np.array([
            [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
            [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
            [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
        ])   # body -> ECI (v_eci = C_bi @ v_body), matches the convention used throughout
        C_eci2ecef = eci_to_ecef_dcm(utc_time)
        # ---- RENDER ORIENTATION = the satellite's BELIEVED attitude ----
        # When the IMU is enabled (and render_estimated_attitude is True) the
        # 3D model is oriented from the onboard ESTIMATOR's belief (gyro +
        # magnetometer + sun sensor), NOT the perfect truth: the satellite on
        # screen shows what the satellite itself thinks its attitude is, so
        # sensor noise/bias is VISIBLE as small jitter/wander in the model.
        # The TRUE pointing-error rows below still use TRUE C_bi.
        C_bi_render = C_bi
        if _imu_sim is not None and config.IMU_SIM.render_estimated_attitude:
            C_bi_render = srd._dcm_bi_from_q(_att_est.q_eci)
        C_body2ecef = C_eci2ecef @ C_bi_render
        quat_xyzw = R.from_matrix(C_body2ecef).as_quat()   # scipy gives [x, y, z, w]

        # ---- POINTING ERROR ACCORDING TO THE SATELLITE'S OWN DATA ----
        # The onboard attitude estimator's belief (gyro + magnetometer, see
        # imu_navigation.AttitudeEstimator) vs the CURRENT mode's commanded
        # target. This is what the satellite itself would report as its
        # pointing error -- it jitters slightly with sensor noise and wanders
        # with gyro bias, while the true pointing error above stays smooth.
        # Also scored against truth (estimation error) for validation only.
        #
        # ORDERING: the reference directions (sun_eci / moon_eci_dir /
        # nadir_eci_dir) are computed in the SUN/MOON/NADIR sections FURTHER
        # DOWN in this loop. The own-axis rows therefore recompute the tiny
        # direction pieces they need LOCALLY (unit sun = provider ephemeris,
        # nadir = -r_vec, moon = spacecraft-to-moon) so this block can never
        # NameError on a first-tick ordering change. Values are identical to
        # the ones used below (same provider calls, same formulas).
        if _imu_sim is not None:
            q_est = _att_est.q_eci
            q_tgt = None
            # NOTE: store.mode is the LIVE mode the dynamics just set this tick
            # (DETUMBLE / POINTING / NADIR / MOON / ... -- probe-verified list),
            # NOT the Flask-requested mode name. Old code compared against
            # request names (SUN_POINTING etc.) which never match, so q_tgt
            # stayed None and the dashboard's "own data" row never updated.
            if store.mode == "POINTING":
                q_tgt = srd.sun_pointing.Q_TARGET
            elif store.mode == "NADIR":
                q_tgt = store.nadir_target_quat
            elif store.mode == "MOON":
                q_tgt = store.moon_target_quat
            elif store.mode == "SUN_SWEEP":
                q_tgt = store.sun_sweep_target_quat
            elif store.mode == "SUN_POINTING_RW":
                q_tgt = store.sun_pointing_rw_target_quat
            elif store.mode == "NOMINAL_IN_ORBIT":
                q_tgt = store.nominal_in_orbit_target_quat
            elif store.mode == "KINEMATIC_ROBUSTNESS":
                q_tgt = store.kinematic_robustness_target_quat
            elif store.mode == "CUSTOM":
                q_tgt = cs.get_pointing_target()
            elif store.mode == "RW":
                q_tgt = srd.Q_INITIAL_RW   # slider-zero reference (documented)
            imu_att_pointing_error_deg = (
                _att_est.pointing_error_deg(q_tgt) if q_tgt is not None else None)
            imu_att_est_error_deg = _att_est.pointing_error_deg(
                np.asarray(X_rot[:4], dtype=float))
            # The satellite ALSO reports the SAME mode-specific boresight error
            # the dashboard shows for truth (sun/moon/nadir axis angle) -- but
            # computed from its OWN estimated attitude. Same metric, same mode
            # axis, just q_est instead of truth: legitimately comparable.
            # (This REPLACES the old full-quaternion attitude error, which also
            # penalises twist about the boresight and therefore reads larger
            # than the boresight number for the same true attitude.)
            imu_own_axis_error_deg = None
            if q_est is not None:
                # Same body->ECI DCM the dynamics uses (imported as srd).
                C_est = srd._dcm_bi_from_q(q_est)
                # Live-mode names here too (see note above). DETUMBLE has no
                # target of its own: reuse the REQUESTED mode's target so the
                # row still reads the transition error instead of going blank.
                _live = store.mode
                _req = cs.get_mode()
                _show = _live if _live != "DETUMBLE" else _req
                # Local direction copies (same formulas as the truth sections
                # below; keeps this block order-independent).
                _own_sun = _orbit_provider.sun_position_eci()
                _own_sun = _own_sun / np.linalg.norm(_own_sun)
                _own_nadir = -r_vec / np.linalg.norm(r_vec)
                _own_rmoon = mpt.moon_position_eci_j2000(utc_time)
                _own_mlos = _own_rmoon - r_vec
                _own_moon = _own_mlos / np.linalg.norm(_own_mlos)
                if _show in ("POINTING", "SUN_POINTING", "SUN_POINTING_RW"):
                    tgt_dir = _own_sun
                    own_ax = C_est @ np.array([0.0, 0.0, -1.0])
                elif _show == "SUN_SWEEP":
                    tgt_dir = _own_sun
                    own_ax = C_est @ np.array([-1.0, 0.0, 0.0])
                elif _show == "MOON":
                    tgt_dir = _own_moon
                    own_ax = C_est @ np.array([-1.0, 0.0, 0.0])
                elif _show in ("NADIR", "NOMINAL_IN_ORBIT"):
                    tgt_dir = _own_nadir
                    own_ax = C_est @ np.array([1.0, 0.0, 0.0])
                elif _show == "KINEMATIC_ROBUSTNESS":
                    tgt_dir = _own_nadir
                    own_ax = C_est @ np.array([0.0, 0.0, 1.0])
                else:
                    tgt_dir, own_ax = None, None
                if tgt_dir is not None:
                    imu_own_axis_error_deg = float(np.degrees(np.arccos(
                        np.clip(np.dot(own_ax, tgt_dir), -1.0, 1.0))))
                else:
                    imu_own_axis_error_deg = None
        else:
            imu_own_axis_error_deg = None

        if store.mode == 'CUSTOM' and _imu_sim is not None:
            imu_own_axis_error_deg = imu_att_pointing_error_deg

        # ---- SUN-POINTING ACCURACY ----
        # Angle between the actual sun-pointing axis (body -X, per periodic_lqr_design.py's
        # build_target_frame) and the true sun direction, both expressed in ECI. This is a
        # 2-DOF error metric (rotation about the sun-line is deliberately not penalized,
        # matching the 2-DOF sun-pointing target) -- the number that actually reflects how
        # well the panels are aimed, independent of any display/rendering considerations.
        sun_pointing_axis_body = np.array([0.0, 0.0, -1.0])   # body -Z, see build_target_frame()
        sun_pointing_axis_eci = C_bi @ sun_pointing_axis_body
        sun_pointing_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(sun_pointing_axis_eci, sun_eci), -1.0, 1.0)
        ))

        # ---- MOON-POINTING (for the moon-direction line and accuracy metric) ----
        # Unlike the sun, the Moon is close enough to the spacecraft (~384,000km vs
        # a Sun distance of ~150,000,000km) that parallax genuinely matters --
        # this uses the SPACECRAFT-TO-MOON vector (geocentric moon position minus
        # r_vec), matching exactly what moon_pointing_quaternion() itself uses
        # internally, not just the geocentric moon direction.
        r_moon_eci = mpt.moon_position_eci_j2000(utc_time)
        moon_los_eci = r_moon_eci - r_vec
        moon_eci_dir = moon_los_eci / np.linalg.norm(moon_los_eci)
        moon_ecef = _orbit_provider.vector_eci_to_ecef(moon_eci_dir, t)
        moon_ecef = moon_ecef / np.linalg.norm(moon_ecef)

        moon_pointing_axis_body = np.array([-1.0, 0.0, 0.0])   # body -X -> Moon, see moon_pointing.py
        moon_pointing_axis_eci = C_bi @ moon_pointing_axis_body
        moon_pointing_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(moon_pointing_axis_eci, moon_eci_dir), -1.0, 1.0)
        ))

        # ---- NADIR-POINTING (for the nadir-direction line and accuracy metric) ----
        # Body Z -> Earth center, see nadir_pointing.py (direct port of calcNadirFrame).
        # Unlike sun/moon this target is purely geometric (no ephemeris), just
        # -r_vec itself, but computed the same way as a genuine ECI direction
        # for consistency with the sun/moon telemetry fields below.
        nadir_eci_dir = -r_vec / np.linalg.norm(r_vec)
        nadir_ecef = _orbit_provider.vector_eci_to_ecef(nadir_eci_dir, t)
        nadir_ecef = nadir_ecef / np.linalg.norm(nadir_ecef)

        nadir_pointing_axis_body = np.array([1.0, 0.0, 0.0])   # body +X -> nadir, see nadir_pointing.py
        nadir_pointing_axis_eci = C_bi @ nadir_pointing_axis_body
        nadir_pointing_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(nadir_pointing_axis_eci, nadir_eci_dir), -1.0, 1.0)
        ))

        # ---- SUN-SWEEP (RW-based, body -X -> Sun, NOT the same as the MTR
        # sun-pointing mode above which uses body -Z) ----
        # Reuses sun_eci (already computed above for the MTR mode's telemetry)
        # since it's the same actual Sun direction -- only the body axis and
        # actuator differ between the two sun-pointing modes.
        sun_sweep_ecef = _orbit_provider.vector_eci_to_ecef(sun_eci, t)
        sun_sweep_ecef = sun_sweep_ecef / np.linalg.norm(sun_sweep_ecef)

        sun_sweep_axis_body = np.array([-1.0, 0.0, 0.0])   # body -X -> Sun, see sun_pointing_rw.py
        sun_sweep_axis_eci = C_bi @ sun_sweep_axis_body
        sun_sweep_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(sun_sweep_axis_eci, sun_eci), -1.0, 1.0)
        ))

        # ---- SUN_POINTING_RW (plain RW sun pointing, SAME axis (body -Z)
        # as the existing MTR "SUN_POINTING" mode -- reuses sun_eci/sun_ecef
        # already computed above, only the axis differs from sun-sweep's -X) ----
        sun_pointing_rw_axis_body = np.array([0.0, 0.0, -1.0])   # body -Z -> Sun, see sun_pointing_rw_z.py
        sun_pointing_rw_axis_eci = C_bi @ sun_pointing_rw_axis_body
        sun_pointing_rw_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(sun_pointing_rw_axis_eci, sun_eci), -1.0, 1.0)
        ))

        # ---- NOMINAL_IN_ORBIT (nadir pointing + 45deg yaw bias about the
        # boresight -- SAME axis (body +X) as NADIR, since yaw about the
        # boresight itself doesn't move it) ----
        nominal_in_orbit_axis_body = np.array([1.0, 0.0, 0.0])   # body +X -> nadir, unaffected by yaw bias
        nominal_in_orbit_axis_eci = C_bi @ nominal_in_orbit_axis_body
        nominal_in_orbit_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(nominal_in_orbit_axis_eci, nadir_eci_dir), -1.0, 1.0)
        ))

        # ---- KINEMATIC_ROBUSTNESS (body +Z locked on nadir, continuously
        # spinning about that same axis -- unaffected by the spin itself,
        # same reasoning as nominal-in-orbit's yaw bias) ----
        kinematic_robustness_axis_body = np.array([0.0, 0.0, 1.0])   # body +Z -> nadir, unaffected by spin
        kinematic_robustness_axis_eci = C_bi @ kinematic_robustness_axis_body
        kinematic_robustness_error_deg = np.degrees(np.arccos(
            np.clip(np.dot(kinematic_robustness_axis_eci, nadir_eci_dir), -1.0, 1.0)
        ))

        # ---- TELEMETRY ----
        firmware_metadata = firmware.metadata(t, {'NadirPoint': float(nadir_pointing_error_deg), 'Sunpoint': float(sun_pointing_error_deg)}, X_rot[4:7]) if firmware is not None else {}
        custom_command = custom_tick_command
        custom_target = np.array(custom_command['desired_quaternion'])
        custom_error = float(2 * np.degrees(np.arccos(np.clip(abs(q2e.get_quaternion_error(custom_target, X_rot[:4])[0]), 0, 1))))
        command_age = custom_command['age_s']
        settled = store.mode == 'CUSTOM' and custom_error < .5 and np.linalg.norm(np.degrees(X_rot[4:7])) < .05
        if not settled or custom_command['command_id'] != last_custom_command_id:
            custom_stable_since = None
        if settled and custom_stable_since is None:
            custom_stable_since = t
        last_custom_command_id = custom_command['command_id']
        custom_state = ('red' if command_age is None else 'green' if command_age < 2 else
                        'blue' if custom_stable_since is not None and t-custom_stable_since >= 1 else 'yellow')
        data_to_send = {
            "spacecraft_configuration": config.SPACECRAFT.configuration,
            "panels_deployed": config.SPACECRAFT.panels_deployed,
            "spacecraft_mass_kg": config.MASS_KG,
            "spacecraft_model_url": config.SPACECRAFT.model_url,
            "center_of_mass_body_m": list(config.GEOMETRY.center_of_mass_body_m),
            "inertia_tensor_kg_m2": config.SPACECRAFT.inertia_matrix.tolist(),
            "srp_torque_body_x": float(srp_result.torque_body_nm[0]),
            "srp_torque_body_y": float(srp_result.torque_body_nm[1]),
            "srp_torque_body_z": float(srp_result.torque_body_nm[2]),
            "disturbance_srp_unm": float(np.linalg.norm(srp_result.torque_body_nm)*1e6),
            "atmospheric_density_kg_m3": srp_result.density_kg_m3,
            "solar_pressure_pa": srp_result.solar_pressure_pa,
            "effective_solar_pressure_pa": srp_result.effective_pressure_pa,
            "timestamp": utc_time.isoformat(),
            "moon_position_ecef_m": _orbit_provider.vector_eci_to_ecef(r_moon_eci, t).tolist(),
            "eci_to_ecef_matrix": np.column_stack([
                _orbit_provider.vector_eci_to_ecef(axis, t) for axis in np.eye(3)
            ]).tolist(),
            "latitude_deg":  lat,
            "longitude_deg": lon,
            "altitude_m":    alt,
            "yaw_deg":       yaw,
            "pitch_deg":     pitch,
            "roll_deg":      roll,
            "body_rate_x":   w_x_deg,
            "body_rate_y":   w_y_deg,
            "body_rate_z":   w_z_deg,
            "alpha_x": np.degrees(store.angular_acceleration[0]),
            "alpha_y": np.degrees(store.angular_acceleration[1]),
            "alpha_z": np.degrees(store.angular_acceleration[2]),
            "sun_ecef_x": float(sun_ecef[0]),
            "sun_ecef_y": float(sun_ecef[1]),
            "sun_ecef_z": float(sun_ecef[2]),
            "moon_ecef_x": float(moon_ecef[0]),
            "moon_ecef_y": float(moon_ecef[1]),
            "moon_ecef_z": float(moon_ecef[2]),
            "nadir_ecef_x": float(nadir_ecef[0]),
            "nadir_ecef_y": float(nadir_ecef[1]),
            "nadir_ecef_z": float(nadir_ecef[2]),
            "sun_sweep_ecef_x": float(sun_sweep_ecef[0]),
            "sun_sweep_ecef_y": float(sun_sweep_ecef[1]),
            "sun_sweep_ecef_z": float(sun_sweep_ecef[2]),
            "quat_x": float(quat_xyzw[0]),
            "quat_y": float(quat_xyzw[1]),
            "quat_z": float(quat_xyzw[2]),
            "quat_w": float(quat_xyzw[3]),
            "sun_pointing_error_deg": float(sun_pointing_error_deg),
            "moon_pointing_error_deg": float(moon_pointing_error_deg),
            "nadir_pointing_error_deg": float(nadir_pointing_error_deg),
            "sun_sweep_error_deg": float(sun_sweep_error_deg),
            "sun_pointing_rw_error_deg": float(sun_pointing_rw_error_deg),
            "nominal_in_orbit_error_deg": float(nominal_in_orbit_error_deg),
            "kinematic_robustness_error_deg": float(kinematic_robustness_error_deg),
            "target_yaw_deg": float(_target_yaw_deg),
            "target_pitch_deg": float(_target_pitch_deg),
            "target_roll_deg": float(_target_roll_deg),
            "nadir_target_yaw_deg": float(nadir_target_yaw_deg),
            "nadir_target_pitch_deg": float(nadir_target_pitch_deg),
            "nadir_target_roll_deg": float(nadir_target_roll_deg),
            "moon_target_yaw_deg": float(moon_target_yaw_deg),
            "moon_target_pitch_deg": float(moon_target_pitch_deg),
            "moon_target_roll_deg": float(moon_target_roll_deg),
            "sun_sweep_target_yaw_deg": float(sun_sweep_target_yaw_deg),
            "sun_sweep_target_pitch_deg": float(sun_sweep_target_pitch_deg),
            "sun_sweep_target_roll_deg": float(sun_sweep_target_roll_deg),
            "sun_pointing_rw_target_yaw_deg": float(sun_pointing_rw_target_yaw_deg),
            "sun_pointing_rw_target_pitch_deg": float(sun_pointing_rw_target_pitch_deg),
            "sun_pointing_rw_target_roll_deg": float(sun_pointing_rw_target_roll_deg),
            "nominal_in_orbit_target_yaw_deg": float(nominal_in_orbit_target_yaw_deg),
            "nominal_in_orbit_target_pitch_deg": float(nominal_in_orbit_target_pitch_deg),
            "nominal_in_orbit_target_roll_deg": float(nominal_in_orbit_target_roll_deg),
            "kinematic_robustness_target_yaw_deg": float(kinematic_robustness_target_yaw_deg),
            "kinematic_robustness_target_pitch_deg": float(kinematic_robustness_target_pitch_deg),
            "kinematic_robustness_target_roll_deg": float(kinematic_robustness_target_roll_deg),
            "mode": store.mode,
            "actuator_telemetry": {
                "time": float(store.time), "mode": store.mode,
                "rw_torques": np.asarray(store.rw_torques).tolist(),
                "mtr_torques": np.asarray(store.mtr_torques).tolist(),
                "mtr_dipole": np.asarray(store.mtr_dipole).tolist(),
                "mtr_currents": np.asarray(store.mtr_currents).tolist(),
            },
            **(dict(zip(('custom_target_yaw_deg', 'custom_target_pitch_deg', 'custom_target_roll_deg'), np.degrees(q2e.euler_from_quaternion(*custom_target)).tolist())) if config.POINTING['strategy'] == 'custom' else {}),
            "custom_pointing_status": custom_state,
            "custom_command_id": custom_command["command_id"],
            "custom_command_sequence": custom_command["sequence"],
            "custom_target_quaternion": custom_target.tolist() if config.POINTING['strategy'] == 'custom' else None,
            "custom_pointing_error_deg": custom_error if config.POINTING['strategy'] == 'custom' else None,
            # SRP telemetry kept minimal: only what the disturbance dropdown
            # displays (acceleration + eclipse). Force/torque/pressure/sun
            # distance were removed alongside the dashboard rows.
            "srp_acceleration_eci_x": float(srp_result.acceleration_eci_m_s2[0]),
            "srp_acceleration_eci_y": float(srp_result.acceleration_eci_m_s2[1]),
            "srp_acceleration_eci_z": float(srp_result.acceleration_eci_m_s2[2]),
            "eclipse_fraction": float(srp_result.eclipse_fraction),
            # ---- RW saturation telemetry (per wheel, computed once per outer
            # step above). Units: torques in mN*m, momentum in mN*m*s. Torque
            # limits are visible as rw_torques_mnm pinned at +/-4.0; momentum
            # saturation as rw_momentum_saturation_fraction reaching 1.0 ----
            "rw_torques_mnm": rw_torques_mnm.tolist(),
            "rw_momentum_mnms": rw_momentum_mnms.tolist(),
            "rw_momentum_saturation_fraction": rw_sat_fraction.tolist(),
            "rw_torque_limited": [bool(x) for x in rw_torque_limited],
            "rw_max_momentum_saturation_fraction": float(np.max(rw_sat_fraction)),
            # ---- Live environmental disturbance telemetry (calculate_
            # disturbances.py). Net vector in N*m (same SI convention as the
            # srp_torque_body_* fields); per-source magnitudes in µN*m.
            # Net includes SRP, drag, gravity gradient and residual dipole. ----
            "disturbance_torque_body_x": float(dist_tau_body[0]),
            "disturbance_torque_body_y": float(dist_tau_body[1]),
            "disturbance_torque_body_z": float(dist_tau_body[2]),
            "disturbance_net_unm": float(dist_net_unm),
            "disturbance_gravity_gradient_unm": float(dist_gg_unm),
            "disturbance_residual_dipole_unm": float(dist_dipole_unm),
            "disturbance_atmospheric_drag_unm": float(dist_drag_unm),
            "disturbances_enabled": bool(cd.DISTURBANCES_ENABLED),
            "disturbance_gravity_gradient_enabled": bool(cd.ENABLE_GRAVITY_GRADIENT),
            "disturbance_residual_dipole_enabled": bool(cd.ENABLE_RESIDUAL_DIPOLE),
            "disturbance_atmospheric_drag_enabled": bool(cd.ENABLE_ATMOSPHERIC_DRAG),
            # ---- REAL position (engine truth): ECI metres + ground coordinates ----
            "truth_pos_eci_x": float(r_vec[0]),
            "truth_pos_eci_y": float(r_vec[1]),
            "truth_pos_eci_z": float(r_vec[2]),
            "truth_lat_deg": float(truth_lat),
            "truth_lon_deg": float(truth_lon),
            "truth_alt_m": float(truth_alt),
            # ---- atmospheric drag acceleration (ECI m/s^2, disturbance dropdown) ----
            "drag_acceleration_eci_x": float(drag_acc_eci[0]),
            "drag_acceleration_eci_y": float(drag_acc_eci[1]),
            "drag_acceleration_eci_z": float(drag_acc_eci[2])

        }

        # ---- GPS receiver status (only when GPS is enabled; no new keys at
        # all when it is off, so the dashboard sees exactly the old fields) --
        if _gps_sim is not None:
            data_to_send.update(_gps_nav.telemetry())
            # The satellite's GPS-computed CURRENT position (the belief,
            # dead-reckoned between 1 Hz fixes from the last fix), ECI metres:
            data_to_send["gps_pos_eci_x"] = float(r_vec_nav[0])
            data_to_send["gps_pos_eci_y"] = float(r_vec_nav[1])
            data_to_send["gps_pos_eci_z"] = float(r_vec_nav[2])

        from engine.astrodynamics.orbit_display import osculating_orbit
        data_to_send['orbit_path_ecef_m'] = (osculating_orbit(r_vec, v_vec) @ C_eci2ecef.T).tolist()

        # ---- IMU sensor belief (only when IMU enabled; no new keys when off)
        if _imu_sim is not None:
            data_to_send.update(_imu_nav.telemetry())
            from imu_mount_settings import mounts
            data_to_send['imu_mounts'] = [m for m in mounts(config.IMU_SIM)
                if m.get('enabled', True) and {'Sun': config.IMU_SIM.enable_sun_sensor,
                    'Gyro': config.IMU_SIM.enable_gyro,
                    'Mag': config.IMU_SIM.enable_magnetometer}[m['kind']]]
            # Satellite's OWN boresight-axis error: the SAME mode-specific
            # metric the dashboard shows for truth (sun/moon/nadir axis
            # angle), but computed from the onboard estimate q_est instead of
            # truth -- directly comparable to the truth error rows.
            # (This is the row the dashboard actually draws; the old
            # full-quaternion imu_att_* numbers stay computed above for
            # validation but are no longer a separate row.)
            data_to_send["imu_own_axis_error_deg"] = (
                None if imu_own_axis_error_deg is None
                else float(imu_own_axis_error_deg))
            # Estimate-vs-truth gap [deg]: how far the satellite's BELIEF is
            # from reality right now. Sub-degree = healthy estimator; a
            # growing number = gyro drift dominating (watch with degraded()).
            data_to_send["imu_est_vs_truth_deg"] = float(imu_att_est_error_deg)

            # ---- Sun ARRAY + estimator + truth pairs (dashboard Sensors tab)
            # Truth channel is dashboard-only: the true body-frame sun
            # direction and the true body-frame field, from the TRUE attitude.
            C_true = srd._dcm_bi_from_q(X_rot[:4])
            _sun_truth_body = C_true.T @ sun_eci
            _sun_truth_body = _sun_truth_body / np.linalg.norm(_sun_truth_body)
            data_to_send["truth_mag_body_x_nT"] = float((C_true.T @ B_eci)[0] * 1e9)
            data_to_send["truth_mag_body_y_nT"] = float((C_true.T @ B_eci)[1] * 1e9)
            data_to_send["truth_mag_body_z_nT"] = float((C_true.T @ B_eci)[2] * 1e9)
            data_to_send["sun_arr_truth_x"] = float(_sun_truth_body[0])
            data_to_send["sun_arr_truth_y"] = float(_sun_truth_body[1])
            data_to_send["sun_arr_truth_z"] = float(_sun_truth_body[2])
            # the array's latest receipt (None before the first grid tick)
            _sun_rec = _imu_nav.latest_sun()
            if _sun_rec is not None:
                data_to_send["sun_arr_valid"] = bool(_sun_rec.valid)
                data_to_send["sun_arr_cells_used"] = int(sum(1 for c in _sun_rec.cells if c.used))
                data_to_send["sun_arr_cells_total"] = int(len(_sun_rec.cells))
                data_to_send["sun_arr_cells"] = [
                    {"name": c.name,
                     "output_pct": float(c.output_pct),
                     "adc_counts": int(c.adc_counts),
                     "angle_deg": (None if c.angle_deg is None else float(c.angle_deg)),
                     "used": bool(c.used), "in_fov": bool(c.in_fov),
                     "shadowed": bool(c.shadowed), "saturated": bool(c.saturated),
                     "eclipse_factor": float(c.eclipse_factor_applied),
                     "albedo_pct": float(c.albedo_fraction * 100.0)}
                    for c in _sun_rec.cells]
                data_to_send["sun_arr_method"] = str(_sun_rec.method)
                data_to_send["sun_arr_eclipse_factor"] = (
                    float(_sun_rec.cells[0].eclipse_factor_applied) if _sun_rec.cells else 1.0)
                if _sun_rec.reconstruction_valid and _sun_rec.reconstructed_body is not None:
                    data_to_send["sun_arr_recon_x"] = float(_sun_rec.reconstructed_body[0])
                    data_to_send["sun_arr_recon_y"] = float(_sun_rec.reconstructed_body[1])
                    data_to_send["sun_arr_recon_z"] = float(_sun_rec.reconstructed_body[2])
                    data_to_send["sun_arr_recon_valid"] = True
                    data_to_send["sun_arr_error_deg"] = float(np.degrees(np.arccos(np.clip(
                        float(np.dot(_sun_rec.reconstructed_body, _sun_truth_body)), -1.0, 1.0))))
                else:
                    # reconstruction honestly failed (eclipse / degenerate):
                    # the estimator coasts on gyro+magnetometer
                    data_to_send["sun_arr_recon_x"] = None
                    data_to_send["sun_arr_recon_y"] = None
                    data_to_send["sun_arr_recon_z"] = None
                    data_to_send["sun_arr_recon_valid"] = False
                    data_to_send["sun_arr_error_deg"] = None
            else:
                data_to_send["sun_arr_valid"] = False
                data_to_send["sun_arr_cells_used"] = None
                data_to_send["sun_arr_cells_total"] = None
                data_to_send["sun_arr_cells"] = None
                data_to_send["sun_arr_method"] = None
                data_to_send["sun_arr_eclipse_factor"] = None
                data_to_send["sun_arr_recon_x"] = None
                data_to_send["sun_arr_recon_y"] = None
                data_to_send["sun_arr_recon_z"] = None
                data_to_send["sun_arr_recon_valid"] = None
                data_to_send["sun_arr_error_deg"] = None
            # attitude estimator belief (quat in the SAME xyzw order as quat_*)
            _q_est = _att_est.q_eci
            for _axis, _value in zip(('w', 'x', 'y', 'z'), X_rot[:4]):
                data_to_send['truth_att_quat_' + _axis] = float(_value)
            data_to_send["att_est_quat_x"] = float(_q_est[1])
            data_to_send["att_est_quat_y"] = float(_q_est[2])
            data_to_send["att_est_quat_z"] = float(_q_est[3])
            data_to_send["att_est_quat_w"] = float(_q_est[0])
            data_to_send['att_est_euler_deg'] = np.degrees(q2e.euler_from_quaternion(*_q_est)).tolist()
            data_to_send['estimated_body_to_ecef_matrix'] = (
                C_eci2ecef @ srd._dcm_bi_from_q(_q_est)).tolist()
            data_to_send["att_est_error_deg"] = float(imu_att_est_error_deg)
            data_to_send["att_est_corrections"] = int(_att_est.corrections)
            data_to_send["att_est_propagations"] = int(_att_est.propagations)
            data_to_send["att_est_sun_used"] = bool(_att_est.sun_used_last)
        

        from dashboard_telemetry import enrich_dashboard
        _active_forces = {type(force).__name__ for force in _orbit_provider.universe.force_model.forces}
        _imu_cfg = _imu_sim.cfg if _imu_sim is not None else None
        enrich_dashboard(
            data_to_send, t=t, position_eci=r_vec, velocity_eci=v_vec,
            sun_eci_m=_orbit_provider.sun_position_eci(), eci_to_ecef=C_eci2ecef,
            body_to_eci=srd._dcm_bi_from_q(X_rot[:4]),
            mtr_torque=store.mtr_torques, mtr_dipole=store.mtr_dipole,
            mtr_current=store.mtr_currents, gps_enabled=_gps_sim is not None,
            spacecraft_name=config.SPACECRAFT.name,
            sensor_activation={
                'GPS receiver': _gps_sim is not None,
                'Gyroscope': bool(_imu_cfg and _imu_cfg.enable_gyro and
                                  (not _imu_cfg.gyros or any(unit.enabled for unit in _imu_cfg.gyros))),
                'Magnetometer': bool(_imu_cfg and _imu_cfg.enable_magnetometer and
                                     (not _imu_cfg.magnetometers or any(unit.enabled for unit in _imu_cfg.magnetometers))),
                'Sun sensor array': bool(_imu_sim and _imu_sim._sun_array is not None),
            },
            models={
                'Propagator': 'Orekit / DOP853',
                'Gravity': (f'EGM2008 {config.MODEL_DATA.gravity_degree}x'
                            f'{config.MODEL_DATA.gravity_order}'
                            if 'ZonalHarmonicsForce' in _active_forces else 'Central body'),
                'Atmosphere': ('NRLMSISE-00 / CAD facets' if 'CoupledSurfaceForce' in _active_forces and cd.DISTURBANCES_ENABLED and cd.ENABLE_ATMOSPHERIC_DRAG else 'Off'),
                'SRP': ('Eclipse-aware CAD force + torque' if 'CoupledSurfaceForce' in _active_forces and cd.DISTURBANCES_ENABLED and sp.ENABLE_SRP else 'Off'),
                'Inertial frame': 'EME2000 (J2000)',
                'Sun ephemeris': type(_orbit_provider._sun_ephemeris).__name__,
                'Moon ephemeris': 'Meeus J2000',
                'Magnetic field': type(_orbit_provider.magnetic_field).__name__.replace('Orekit', 'Orekit '),
            },
        )

        data_to_send.update(firmware_metadata)
        now_monotonic = time.monotonic()
        if now_monotonic - _last_telemetry_publish_monotonic >= _telemetry_publish_interval_s:
            try:
                _telemetry_sequence += 1
                data_to_send['telemetry_sequence'] = _telemetry_sequence
                data_to_send['telemetry_session_id'] = _telemetry_session_id
                data_to_send['simulation_step_dt_s'] = dt
                data_to_send.update(pacer.metrics(t))
                _telemetry_publisher.publish(data_to_send)
                _last_telemetry_publish_monotonic = now_monotonic
            except requests.RequestException:
                pass

        X_rot = X_rot_next
        t += dt




        # ---- REAL-TIME SYNC ----
