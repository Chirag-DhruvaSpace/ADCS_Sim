import numpy as np
import pymap3d as pm
import eci_to_ecef

def fov_lookat(r_eci, v_eci, utc_time, yaw, pitch, roll, boresight_body):

    Re = 6378137.0

    # -----------------------------
    # Convert spacecraft position to ECEF
    # -----------------------------
    r_ecef, _ = eci_to_ecef.eci_to_ecef_astropy(r_eci, v_eci, utc_time)

    # -----------------------------
    # Build LVLH frame (in ECI)
    # -----------------------------
    r_hat = r_eci / np.linalg.norm(r_eci)

    h = np.cross(r_eci, v_eci)
    h_hat = h / np.linalg.norm(h)

    t_hat = np.cross(h_hat, r_hat)   # along track

    i_eci = t_hat
    j_eci = h_hat
    k_eci = -r_hat

    # -----------------------------
    # Convert LVLH axes to ECEF
    # -----------------------------
    i = eci_to_ecef.eci_vec_to_ecef(i_eci, utc_time)
    j = eci_to_ecef.eci_vec_to_ecef(j_eci, utc_time)
    k = eci_to_ecef.eci_vec_to_ecef(k_eci, utc_time)

    i /= np.linalg.norm(i)
    j /= np.linalg.norm(j)
    k /= np.linalg.norm(k)

    R_lvlh_to_ecef = np.column_stack((i, j, k))

    # -----------------------------
    # Body → LVLH rotation
    # -----------------------------
    yaw = np.radians(yaw)
    pitch = np.radians(pitch)
    roll = np.radians(roll)

    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)

    R_body_to_lvlh = np.array([
        [cy*cp,  cy*sp*sr - sy*cr,  cy*sp*cr + sy*sr],
        [sy*cp,  sy*sp*sr + cy*cr,  sy*sp*cr - cy*sr],
        [-sp,    cp*sr,             cp*cr]
    ])

    # -----------------------------
    # Body → ECEF rotation
    # -----------------------------
    R_body_to_ecef = R_lvlh_to_ecef @ R_body_to_lvlh

    # -----------------------------
    # Instrument boresight (body frame)
    # -----------------------------
    #boresight_body = np.array([0, 0, 1])

    boresight_ecef = R_body_to_ecef @ boresight_body
    boresight_ecef /= np.linalg.norm(boresight_ecef)

    # -----------------------------
    # Ray–Earth intersection
    # -----------------------------
    r = r_ecef
    d = boresight_ecef

    A = np.dot(d, d)
    B = 2 * np.dot(r, d)
    C = np.dot(r, r) - Re**2

    t = (-B - np.sqrt(B*B - 4*A*C)) / (2*A)

    footprint_ecef = r + t * d

    # -----------------------------
    # Convert to geodetic coordinates
    # -----------------------------
    lat, lon, alt = pm.ecef2geodetic(
        footprint_ecef[0],
        footprint_ecef[1],
        footprint_ecef[2]
    )

    return lat, lon, alt

