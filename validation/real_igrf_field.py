"""
real_igrf_field.py

Real IGRF-14 magnetic field in ECI, reusing this repo's own
calculate_eci_position_and_velocity.py machinery (magnetic_field_eci(),
which calls pyIGRF.igrf_value() under the hood). pyIGRF was broken in this
environment (missing its coefficient data file, a packaging bug on PyPI) --
fixed by downloading igrf14coeffs.txt directly from pyIGRF's own official
GitHub repo (zzyztyy/pyIGRF) to where the installed package expects it, with
explicit approval before doing so.

Supersedes the tilted-dipole approximation used earlier this session
(b_field_eci() in bdot_realistic_detumbling.py) for anything where the
field's true periodic structure matters -- notably SunPointing_M1, whose
gain schedule (kSunPointingM1KSeq) is a Floquet-verified PERIODIC regulator
built on the real field's orbital periodicity. A fixed or approximated
field breaks that design assumption; this does not.
"""
import numpy as np
import pymap3d as pm
from datetime import timedelta

import orbit_parameters as op
import environment_parameters as ep
from calculate_eci_position_and_velocity import convert_orbit_params_to_ECI, magnetic_field_eci

MU = ep.mu


def mean_motion():
    return np.sqrt(MU / op.a**3)


def eci_position(t_seconds, e=None, i_deg=None, Omega_deg=None):
    """Real (near-circular, first-order equation-of-center corrected)
    orbital position in ECI at elapsed time t_seconds, using this repo's
    own orbit_parameters.py elements."""
    e = op.e if e is None else e
    i_deg = op.i if i_deg is None else i_deg
    Omega_deg = op.Omega if Omega_deg is None else Omega_deg
    n = mean_motion()
    M = n * t_seconds
    nu_deg = np.degrees(M + 2*e*np.sin(M))
    r_eci, v_eci = convert_orbit_params_to_ECI(op.a, e, i_deg, Omega_deg, 0.0, nu_deg, MU)
    return np.array(r_eci)


def b_field_eci_real_igrf(t_seconds, epoch_utc, r_eci_m=None):
    """Real IGRF-14 B field in ECI (Tesla) at elapsed time t_seconds past
    epoch_utc. Computes orbital position internally unless r_eci_m is
    supplied (e.g. if the caller already propagated a slightly different
    trajectory)."""
    if r_eci_m is None:
        r_eci_m = eci_position(t_seconds)
    utc_time = epoch_utc + timedelta(seconds=t_seconds)

    r_norm = np.linalg.norm(r_eci_m)
    gmst = pm.datetime2sidereal(utc_time, 0.0)
    c, s = np.cos(gmst), np.sin(gmst)
    R_eci2ecef = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
    r_ecef = R_eci2ecef @ r_eci_m

    lat, lon, alt_m = pm.ecef2geodetic(r_ecef[0], r_ecef[1], r_ecef[2])
    alt_km = alt_m / 1000.0

    # magnetic_field_eci() -> get_magnetic_field() already converts nT to
    # Tesla internally (*10**-9) -- do NOT convert again here.
    B_eci = magnetic_field_eci(lat, lon, alt_km, utc_time)
    return np.array(B_eci)
