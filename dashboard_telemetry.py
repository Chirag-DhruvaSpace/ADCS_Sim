"""Display-only snapshot fields; never feeds values back into the plant."""
import numpy as np


def enrich_dashboard(data, *, t, position_eci, velocity_eci, sun_eci_m,
                     eci_to_ecef, body_to_eci, mtr_torque, mtr_dipole,
                     mtr_current, models, gps_enabled, spacecraft_name=None,
                     sensor_activation=None):
    rotation = np.asarray(eci_to_ecef)
    data.update(
        simulation_time_s=float(t),
        satellite_position_ecef_m=(rotation @ position_eci).tolist(),
        satellite_velocity_eci_m_s=np.asarray(velocity_eci).tolist(),
        satellite_speed_m_s=float(np.linalg.norm(velocity_eci)),
        sun_position_ecef_m=(rotation @ sun_eci_m).tolist(),
        body_to_ecef_matrix=(rotation @ body_to_eci).tolist(),
        mtr_torque_nm=np.asarray(mtr_torque).tolist(),
        mtr_dipole_am2=np.asarray(mtr_dipole).tolist(),
        mtr_current_a=np.asarray(mtr_current).tolist(),
        orbital_models=models,
        satellite_name=spacecraft_name,
        sensor_activation=dict(sensor_activation or {}),
        gps_enabled=bool(gps_enabled),
        # The receiver models aggregate errors/counts, not PRNs or signal links.
        # Never turn the synthetic SV count into invented constellation positions.
        gps_links_available=False,
        gps_links_unavailable_reason=(
            'Receiver model does not publish individual GNSS ephemerides or tracked PRNs.'
            if gps_enabled else 'GPS receiver disabled.'),
        gps_satellites=[],
    )
    return data


def select_star_tracker_view(history, measurement, timestamp_tolerance_s=0.001):
    """Match operator camera truth to a delivered receipt, including invalid ones.

    Sensor timestamps have small clock noise. Select the nearest sampled tick
    within that noise tolerance; never substitute estimated attitude or fetch
    past engine truth. The bounded history belongs only to the dashboard.
    """
    if not history:
        return None
    current_view = history[-1]
    selected_view = current_view
    aligned = False
    if measurement is not None:
        nearest = min(history, key=lambda view: abs(view['time_s'] - measurement.t_meas_s))
        if abs(nearest['time_s'] - measurement.t_meas_s) <= timestamp_tolerance_s:
            selected_view = nearest
            aligned = True
    result = dict(selected_view)
    result['receipt_aligned'] = aligned
    result['receipt_time_s'] = measurement.t_meas_s if measurement is not None else None
    result['receipt_reason'] = measurement.reason if measurement is not None else None
    result['earth_limb_angle_deg'] = measurement.earth_limb_angle_deg if aligned else None
    return result
