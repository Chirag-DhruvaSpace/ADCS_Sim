import numpy as np
from astropy.time import Time
from scipy.spatial.transform import Rotation
import quat2eul as q2e


DEG2RAD = np.pi / 180.0
ARCSEC2RAD = DEG2RAD / 3600.0


# ============================================================
# Meeus lunar periodic terms
# ============================================================

LR_TERMS = np.array([
    [0, 0, 1, 0, 6288774, -20905355],
    [2, 0, -1, 0, 1274027, -3699111],
    [2, 0, 0, 0, 658314, -2955968],
    [0, 0, 2, 0, 213618, -569925],
    [0, 1, 0, 0, -185116, 48888],
    [0, 0, 0, 2, -114332, -3149],
    [2, 0, -2, 0, 58793, 246158],
    [2, -1, -1, 0, 57066, -152138],
    [2, 0, 1, 0, 53322, -170733],
    [2, -1, 0, 0, 45758, -204586],
    [0, 1, -1, 0, -40923, -129620],
    [1, 0, 0, 0, -34720, 108743],
    [0, 1, 1, 0, -30383, 104755],
    [2, 0, 0, -2, 15327, 10321],
    [0, 0, 1, 2, -12528, 0],
    [0, 0, 1, -2, 10980, 79661],
    [4, 0, -1, 0, 10675, -34782],
    [0, 0, 3, 0, 10034, -23210],
    [4, 0, -2, 0, 8548, -21636],
    [2, 1, -1, 0, -7888, 24208],
    [2, 1, 0, 0, -6766, 30824],
    [1, 0, -1, 0, -5163, -8379],
    [1, 1, 0, 0, 4987, -16675],
    [2, -1, 1, 0, 4036, -12831],
    [2, 0, 2, 0, 3994, -10445],
    [4, 0, 0, 0, 3861, -11650],
    [2, 0, -3, 0, 3665, 14403],
    [0, 1, -2, 0, -2689, -7003],
    [2, 0, -1, 2, -2602, 0],
    [2, -1, -2, 0, 2390, 10056],
    [1, 0, 1, 0, -2348, 6322],
    [2, -2, 0, 0, 2236, -9884],
    [0, 1, 2, 0, -2120, 5751],
    [0, 2, 0, 0, -2069, 0],
    [2, -2, -1, 0, 2048, -4950],
    [2, 0, 1, -2, -1773, 4130],
    [2, 0, 0, 2, -1595, 0],
    [4, -1, -1, 0, 1215, -3958],
    [0, 0, 2, 2, -1110, 0],
    [3, 0, -1, 0, -892, 3258],
    [2, 1, 1, 0, -810, 2616],
    [4, -1, -2, 0, 759, -1897],
    [0, 2, -1, 0, -713, -2117],
    [2, 2, -1, 0, -700, 2354],
    [2, 1, -2, 0, 691, 0],
    [2, -1, 0, -2, 596, 0],
    [4, 0, 1, 0, 549, -1423],
    [0, 0, 4, 0, 537, -1117],
    [4, -1, 0, 0, 520, -1571],
    [1, 0, -2, 0, -487, -1739],
    [2, 1, 0, -2, -399, 0],
    [0, 0, 2, -2, -381, -4421],
    [1, 1, 1, 0, 351, 0],
    [3, 0, -2, 0, -340, 0],
    [4, 0, -3, 0, 330, 0],
    [2, -1, 2, 0, 327, 0],
    [0, 2, 1, 0, -323, 1165],
    [1, 1, -1, 0, 299, 0],
    [2, 0, 3, 0, 294, 0],
    [2, 0, -1, -2, 0, 8752]
], dtype=float)


B_TERMS = np.array([
    [0, 0, 0, 1, 5128122],
    [0, 0, 1, 1, 280602],
    [0, 0, 1, -1, 277693],
    [2, 0, 0, -1, 173237],
    [2, 0, -1, 1, 55413],
    [2, 0, -1, -1, 46271],
    [2, 0, 0, 1, 32573],
    [0, 0, 2, 1, 17198],
    [2, 0, 1, -1, 9266],
    [0, 0, 2, -1, 8822],
    [2, -1, 0, -1, 8216],
    [2, 0, -2, -1, 4324],
    [2, 0, 1, 1, 4200],
    [2, 1, 0, -1, -3359],
    [2, -1, -1, 1, 2463],
    [2, -1, 0, 1, 2211],
    [2, -1, -1, -1, 2065],
    [0, 1, -1, -1, -1870],
    [4, 0, -1, -1, 1828],
    [0, 1, 0, 1, -1794],
    [0, 0, 0, 3, -1749],
    [0, 1, -1, 1, -1565],
    [1, 0, 0, 1, -1491],
    [0, 1, 1, 1, -1475],
    [0, 1, 1, -1, -1410],
    [0, 1, 0, -1, -1344],
    [1, 0, 0, -1, -1335],
    [0, 0, 3, 1, 1107],
    [4, 0, 0, -1, 1021],
    [4, 0, -1, 1, 833],
    [0, 0, 1, -3, 777],
    [4, 0, -2, 1, 671],
    [2, 0, 0, -3, 607],
    [2, 0, 2, -1, 596],
    [2, -1, 1, -1, 491],
    [2, 0, -2, 1, -451],
    [0, 0, 3, -1, 439],
    [2, 0, 2, 1, 422],
    [2, 0, -3, -1, 421],
    [2, 1, -1, 1, -366],
    [2, 1, 0, 1, -351],
    [4, 0, 0, 1, 331],
    [2, -1, 1, 1, 315],
    [2, -2, 0, -1, 302],
    [0, 0, 1, 3, -283],
    [2, 1, 1, -1, -229],
    [1, 1, 0, -1, 223],
    [1, 1, 0, 1, 223],
    [0, 1, -2, -1, -220],
    [2, 1, -1, -1, -220],
    [1, 0, 1, 1, -185],
    [2, -1, -2, -1, 181],
    [0, 1, 2, 1, -177],
    [4, 0, -2, -1, 176],
    [4, -1, -1, -1, 166],
    [1, 0, 1, -1, -164],
    [4, 0, 1, -1, 132],
    [1, 0, -1, -1, -119],
    [4, -1, 0, -1, 115],
    [2, -2, 0, 1, 107]
], dtype=float)


# ============================================================
# Moon position
# ============================================================

def moon_position_eci_j2000(timestamp_utc):
    """
    Analytical lunar position.

    Input:
        timestamp_utc : datetime

    Output:
        Moon geocentric J2000 ECI position [m]
    """

    # --------------------------------------------------------
    # Julian date
    # --------------------------------------------------------

    JD = Time(timestamp_utc, scale="utc").jd

    T = (JD - 2451545.0) / 36525.0

    # --------------------------------------------------------
    # Fundamental arguments
    # --------------------------------------------------------

    Lp = (
        218.3164477
        + 481267.88123421 * T
        - 0.0015786 * T**2
        + T**3 / 538841.0
        - T**4 / 65194000.0
    )

    D = (
        297.8501921
        + 445267.1114034 * T
        - 0.0018819 * T**2
        + T**3 / 545868.0
        - T**4 / 113065000.0
    )

    M = (
        357.5291092
        + 35999.0502909 * T
        - 0.0001536 * T**2
        + T**3 / 24490000.0
    )

    Mp = (
        134.9633964
        + 477198.8675055 * T
        + 0.0087414 * T**2
        + T**3 / 69699.0
        - T**4 / 14712000.0
    )

    F = (
        93.2720950
        + 483202.0175233 * T
        - 0.0036539 * T**2
        - T**3 / 3526000.0
        + T**4 / 863310000.0
    )

    Lp *= DEG2RAD
    D *= DEG2RAD
    M *= DEG2RAD
    Mp *= DEG2RAD
    F *= DEG2RAD

    E = 1.0 - 0.002516*T - 0.0000074*T**2
    E2 = E * E

    # --------------------------------------------------------
    # Periodic terms
    # --------------------------------------------------------

    sigma_l = 0.0
    sigma_r = 0.0
    sigma_b = 0.0

    for d, m, mp, f, coeff_l, coeff_r in LR_TERMS:

        arg = d*D + m*M + mp*Mp + f*F

        if abs(m) == 0:
            factor = 1.0
        elif abs(m) == 1:
            factor = E
        else:
            factor = E2

        sigma_l += coeff_l * factor * np.sin(arg)
        sigma_r += coeff_r * factor * np.cos(arg)

    for d, m, mp, f, coeff_b in B_TERMS:

        arg = d*D + m*M + mp*Mp + f*F

        if abs(m) == 0:
            factor = 1.0
        elif abs(m) == 1:
            factor = E
        else:
            factor = E2

        sigma_b += coeff_b * factor * np.sin(arg)

    # --------------------------------------------------------
    # Additional corrections
    # --------------------------------------------------------

    A1 = (119.75 + 131.849*T) * DEG2RAD
    A2 = (53.09 + 479264.290*T) * DEG2RAD
    A3 = (313.45 + 481266.484*T) * DEG2RAD

    sigma_l += (
        3958*np.sin(A1)
        + 1962*np.sin(Lp - F)
        + 318*np.sin(A2)
    )

    sigma_b += (
        -2235*np.sin(Lp)
        + 382*np.sin(A3)
        + 175*np.sin(A1 - F)
        + 175*np.sin(A1 + F)
        + 127*np.sin(Lp - Mp)
        - 115*np.sin(Lp + Mp)
    )

    # --------------------------------------------------------
    # Ecliptic coordinates
    # --------------------------------------------------------

    lam = Lp + sigma_l * 1e-6 * DEG2RAD
    beta = sigma_b * 1e-6 * DEG2RAD

    distance_km = 385000.56 + sigma_r * 1e-3

    # --------------------------------------------------------
    # Obliquity
    # --------------------------------------------------------

    eps = (
        23.439291111
        - 0.013004167*T
        - 1.64e-7*T**2
        + 5.04e-8*T**3
    ) * DEG2RAD

    # --------------------------------------------------------
    # Ecliptic -> equatorial of date
    # --------------------------------------------------------

    x = distance_km * np.cos(beta) * np.cos(lam)

    y = distance_km * (
        np.cos(beta)*np.sin(lam)*np.cos(eps)
        - np.sin(beta)*np.sin(eps)
    )

    z = distance_km * (
        np.cos(beta)*np.sin(lam)*np.sin(eps)
        + np.sin(beta)*np.cos(eps)
    )

    r_date = np.array([x, y, z])

    # --------------------------------------------------------
    # Precession: date -> J2000
    # --------------------------------------------------------

    zeta = (
        2306.2181*T
        + 0.30188*T**2
        + 0.017998*T**3
    ) * ARCSEC2RAD

    z_ang = (
        2306.2181*T
        + 1.09468*T**2
        + 0.018203*T**3
    ) * ARCSEC2RAD

    theta = (
        2004.3109*T
        - 0.42665*T**2
        - 0.041833*T**3
    ) * ARCSEC2RAD

    def R2(a):
        c = np.cos(a)
        s = np.sin(a)

        return np.array([
            [c, 0, -s],
            [0, 1, 0],
            [s, 0, c]
        ])

    def R3(a):
        c = np.cos(a)
        s = np.sin(a)

        return np.array([
            [c, s, 0],
            [-s, c, 0],
            [0, 0, 1]
        ])

    # FIXED precession composition (was R3(zeta) @ R1(-theta) @ R3(-z_ang), which
    # used the wrong rotation axis for theta -- R1 (X-axis) instead of R2
    # (Y-axis) -- and the wrong sign on z_ang. This is the mathematical inverse
    # of the standard IAU 1976 J2000->date precession matrix (needed here since
    # this converts date->J2000, the reverse direction). Verified against
    # astropy's independent JPL-based ephemeris: original error grew from
    # 0.009deg near J2000 to 0.38-0.48deg by 2026-2035 (classic precession-bug
    # signature); this form holds at ~0.01deg across that same range.
    C = (
        R3(zeta)
        @ R2(-theta)
        @ R3(z_ang)
    )

    return (C @ r_date) * 1000.0


# ============================================================
# Moon pointing
# ============================================================

def moon_pointing_quaternion(timestamp_utc, r_sc_eci_m):
    """
    Desired attitude for:

        BODY -X -> MOON

    Roll constraint:
        +Z is kept as close as possible to ECI +Z.

    Returns:
        q_desired = [q0, q1, q2, q3]
    """

    # Moon ECI position
    r_moon_eci = moon_position_eci_j2000(timestamp_utc)

    # Spacecraft -> Moon
    r_moon_sc = r_moon_eci - np.asarray(r_sc_eci_m)

    moon_los = r_moon_sc / np.linalg.norm(r_moon_sc)

    # -X body points toward Moon
    # Therefore +X body points AWAY from Moon.
    x_body_eci = -moon_los

    # Roll reference: ECI +Z
    z_ref = np.array([0.0, 0.0, 1.0])

    # Avoid singularity when Moon is near ECI Z
    if abs(np.dot(x_body_eci, z_ref)) > 0.95:
        z_ref = np.array([0.0, 1.0, 0.0])

    # Remove X component from reference vector
    z_body_eci = (
        z_ref
        - np.dot(z_ref, x_body_eci) * x_body_eci
    )

    z_body_eci /= np.linalg.norm(z_body_eci)

    # Complete right-handed frame
    y_body_eci = np.cross(z_body_eci, x_body_eci)
    y_body_eci /= np.linalg.norm(y_body_eci)

    # Re-orthogonalize
    z_body_eci = np.cross(x_body_eci, y_body_eci)

    # Body axes expressed in ECI
    C_IB = np.column_stack([
        x_body_eci,
        y_body_eci,
        z_body_eci
    ])

    # ECI -> Body
    C_BI = C_IB.T

    # SciPy returns [x,y,z,w]
    q_xyzw = Rotation.from_matrix(C_BI).as_quat()

    # Convert to your convention [q0,q1,q2,q3]
    q0 = q_xyzw[3]
    q1 = q_xyzw[0]
    q2 = q_xyzw[1]
    q3 = q_xyzw[2]

    return np.array([q0, q1, q2, q3])