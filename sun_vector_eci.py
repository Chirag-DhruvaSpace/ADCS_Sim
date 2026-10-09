"""
sun_vector_eci.py

Approximate Sun position in ECI (mean equator/equinox, essentially GCRF/J2000 to within
arcsecond-level accuracy for decades around J2000) computed purely from UTC time --
no sun sensor needed. This is the standard low-precision solar ephemeris algorithm
(Vallado, "Fundamentals of Astrodynamics and Applications", Algorithm 29), good to
about 0.01 deg near J2000 and still sub-0.1 deg accurate for many decades either side --
more than enough for coarse sun-pointing (your stated 20 deg tolerance).

Since the Sun is ~1 AU away and LEO altitude is ~500km, the geocentric (Earth-center)
and topocentric (spacecraft-position) sun directions differ by at most
~500km/1.5e8km * 206265 arcsec =~ 0.0007 deg -- utterly negligible. So the spacecraft's
own position doesn't need to be folded in at all; only the clock (UTC time) matters.
"""
import numpy as np
from datetime import datetime, timezone


def _julian_date(utc_dt: datetime) -> float:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    y, m = utc_dt.year, utc_dt.month
    d = (utc_dt.day + utc_dt.hour/24 + utc_dt.minute/1440 +
         (utc_dt.second + utc_dt.microsecond/1e6)/86400)
    if m <= 2:
        y -= 1
        m += 12
    A = y // 100
    B = 2 - A + A // 4
    jd = int(365.25*(y+4716)) + int(30.6001*(m+1)) + d + B - 1524.5
    return jd


def sun_vector_eci(utc_dt: datetime) -> np.ndarray:
    """Returns the Earth->Sun unit vector in ECI (mean equator/equinox)."""
    jd = _julian_date(utc_dt)
    T_ut1 = (jd - 2451545.0) / 36525.0

    lam_M = np.radians((280.460 + 36000.771 * T_ut1) % 360.0)      # mean longitude
    M = np.radians((357.5291092 + 35999.05034 * T_ut1) % 360.0)     # mean anomaly

    lam_ecl = lam_M + np.radians(1.914666471*np.sin(M) + 0.019994643*np.sin(2*M))
    eps = np.radians(23.439291 - 0.0130042*T_ut1)                   # obliquity of ecliptic

    s_hat = np.array([
        np.cos(lam_ecl),
        np.cos(eps)*np.sin(lam_ecl),
        np.sin(eps)*np.sin(lam_ecl)
    ])
    return s_hat / np.linalg.norm(s_hat)


def sun_ra_dec_deg(utc_dt: datetime):
    """Handy sanity-check form: right ascension / declination in degrees."""
    s = sun_vector_eci(utc_dt)
    ra = np.degrees(np.arctan2(s[1], s[0])) % 360.0
    dec = np.degrees(np.arcsin(s[2]))
    return ra, dec


if __name__ == "__main__":
    # Sanity checks against well-known Sun behavior:
    # - equinoxes: declination ~ 0 deg
    # - summer solstice (~Jun 21): declination ~ +23.4 deg
    # - winter solstice (~Dec 21): declination ~ -23.4 deg
    for label, dt in [
        ("Mar equinox 2026-03-20", datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)),
        ("Jun solstice 2026-06-21", datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)),
        ("Sep equinox 2026-09-22", datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)),
        ("Dec solstice 2026-12-21", datetime(2026, 12, 21, 12, 0, 0, tzinfo=timezone.utc)),
        ("Mission epoch 2026-03-11 14:00 UTC", datetime(2026, 3, 11, 14, 0, 0, tzinfo=timezone.utc)),
    ]:
        ra, dec = sun_ra_dec_deg(dt)
        print(f"{label:35s}  RA={ra:7.3f} deg   Dec={dec:7.3f} deg")
