"""Instantaneous two-body osculating ellipse, for operator visualization only."""
import numpy as np
from engine.astrodynamics.constants import EARTH_MU


def osculating_orbit(position, velocity, points=257):
    r, v = np.asarray(position, float), np.asarray(velocity, float)
    h = np.cross(r, v)
    hn = np.linalg.norm(h)
    rn = np.linalg.norm(r)
    if hn < 1e-9 or rn < 1:
        return np.empty((0, 3))
    eccentricity = np.cross(v, h) / EARTH_MU - r / rn
    e = np.linalg.norm(eccentricity)
    if e >= 1:
        return np.empty((0, 3))
    u = eccentricity / e if e > 1e-10 else r / rn
    w = np.cross(h / hn, u)
    theta = np.linspace(0, 2*np.pi, points)
    radius = (hn*hn / EARTH_MU) / (1 + e*np.cos(theta))
    return radius[:, None] * (np.cos(theta)[:, None]*u + np.sin(theta)[:, None]*w)
