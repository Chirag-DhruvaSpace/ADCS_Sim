import math

from engine.math.vector3 import Vector3
from engine.astrodynamics.constants import EARTH_MU


# =============================================================================
# ANGULAR MOMENTUM
#
# h = r × v
#
# The angular momentum vector is perpendicular to the orbital plane.
#
# Direction  -> Orbit orientation
# Magnitude  -> Amount of orbital momentum
#
# Conserved in an ideal two-body system.
# =============================================================================


def angular_momentum(position: Vector3, velocity: Vector3) -> Vector3:
    return position.cross(velocity)


# =============================================================================
# SPECIFIC ORBITAL ENERGY
#
# ε = (v² / 2) - (μ / r)
#
# ε < 0  -> Elliptical Orbit
# ε = 0  -> Parabolic Escape
# ε > 0  -> Hyperbolic Orbit
#
# Conserved in an ideal two-body system.
# =============================================================================


def specific_orbital_energy(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    r = position.magnitude()
    v2 = velocity.magnitude_squared()
    return (v2 / 2) - (mu / r)


# =============================================================================
# CIRCULAR ORBIT VELOCITY
#
# vc = √(μ / r)
#
# Velocity required for a perfectly circular orbit.
# =============================================================================


def circular_velocity(radius: float, mu: float = EARTH_MU) -> float:
    return math.sqrt(mu / radius)


# =============================================================================
# ESCAPE VELOCITY
#
# ve = √(2μ / r)
#
# Minimum velocity required to escape the gravitational field.
# =============================================================================


def escape_velocity(radius: float, mu: float = EARTH_MU) -> float:
    return math.sqrt((2 * mu) / radius)


# =============================================================================
# VIS-VIVA EQUATION
#
# v² = μ ( 2/r - 1/a )
#
# Calculates orbital velocity at any point in an orbit.
#
# r = Current distance
# a = Semi-major axis
# =============================================================================


def vis_viva(radius: float, semi_major_axis: float, mu: float = EARTH_MU) -> float:
    return math.sqrt(
        mu *
        (
            (2 / radius) - (1 / semi_major_axis)
        )
    )


# =============================================================================
# ORBITAL PERIOD
#
# T = 2π √(a³ / μ)
#
# Time required for one complete orbit.
# =============================================================================


def orbital_period(semi_major_axis: float, mu: float = EARTH_MU) -> float:
    return (
        2 * math.pi * math.sqrt(
            semi_major_axis ** 3 / mu
        )
    )


# =============================================================================
# MEAN MOTION
#
# n = √(μ / a³)
#
# Average angular speed of an orbit.
#
# Units:
#
# radians / second
# =============================================================================


def mean_motion(semi_major_axis: float, mu: float = EARTH_MU) -> float:
    return math.sqrt(
        mu / (semi_major_axis ** 3)
    )


# =============================================================================
# ECCENTRICITY VECTOR
#
# e⃗ = (v × h) / μ - r̂
#
# Direction  -> Points toward periapsis
# Magnitude  -> Orbital eccentricity
#
# e = 0  -> Circle
# 0<e<1  -> Ellipse
# e = 1  -> Parabola
# e > 1  -> Hyperbola
# =============================================================================


def eccentricity_vector(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> Vector3:
    h = angular_momentum(position, velocity)
    r_hat = position.normalize()
    return (velocity.cross(h) / mu) - r_hat


# =============================================================================
# ECCENTRICITY
#
# e = |e⃗|
#
# Returns the scalar eccentricity.
# =============================================================================


def eccentricity(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    return eccentricity_vector(position, velocity, mu).magnitude()


# =============================================================================
# SEMI-MAJOR AXIS
#
# a = -μ / (2ε)
#
# Uses the specific orbital energy.
# =============================================================================


def semi_major_axis(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    energy = specific_orbital_energy(position, velocity, mu)
    return -mu / (2 * energy)


# =============================================================================
# NODE VECTOR
#
# n = k × h
#
# k = (0,0,1)
#
# Points toward the Ascending Node.
# =============================================================================


def node_vector(position: Vector3, velocity: Vector3) -> Vector3:
    k = Vector3(0, 0, 1)
    h = angular_momentum(position, velocity)
    return k.cross(h)


# =============================================================================
# INCLINATION
#
# i = acos(hz / |h|)
#
# Returns inclination in radians.
# =============================================================================


def inclination(position: Vector3, velocity: Vector3) -> float:
    h = angular_momentum(position, velocity)
    return math.acos(h.z / h.magnitude())


# =============================================================================
# PERIAPSIS RADIUS
#
# rp = a(1 - e)
# =============================================================================


def periapsis_radius(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    a = semi_major_axis(position, velocity, mu)
    e = eccentricity(position, velocity, mu)
    return a * (1 - e)


# =============================================================================
# APOAPSIS RADIUS
#
# ra = a(1 + e)
# =============================================================================


def apoapsis_radius(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    a = semi_major_axis(position, velocity, mu)
    e = eccentricity(position, velocity, mu)
    return a * (1 + e)


# =============================================================================
# RIGHT ASCENSION OF ASCENDING NODE (RAAN)
#
# Ω = acos(nx / |n|)
#
# If ny < 0:
#     Ω = 2π - Ω
#
# Returns RAAN in radians.
# =============================================================================


def raan(position: Vector3, velocity: Vector3) -> float:
    n = node_vector(position, velocity)

    if n.magnitude() == 0:
        return 0.0
    omega = math.acos(n.x / n.magnitude())

    if n.y < 0:
        omega = 2 * math.pi - omega
    return omega


# =============================================================================
# ARGUMENT OF PERIAPSIS
#
# ω = acos((n · e) / (|n||e|))
#
# If ez < 0:
#     ω = 2π - ω
#
# Returns Argument of Periapsis in radians.
# =============================================================================


def argument_of_periapsis(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    n = node_vector(position, velocity)
    e = eccentricity_vector(position, velocity, mu)

    if n.magnitude() == 0 or e.magnitude() == 0:
        return 0.0
    value = n.dot(e) / (n.magnitude() * e.magnitude())
    value = max(-1.0, min(1.0, value))
    omega = math.acos(value)

    if e.z < 0:
        omega = 2 * math.pi - omega
    return omega


# =============================================================================
# TRUE ANOMALY
#
# ν = acos((e · r) / (|e||r|))
#
# If r · v < 0:
#     ν = 2π - ν
#
# Returns True Anomaly in radians.
# =============================================================================


def true_anomaly(position: Vector3, velocity: Vector3, mu: float = EARTH_MU) -> float:
    e = eccentricity_vector(position, velocity, mu)

    if e.magnitude() == 0:
        return 0.0
    
    value = e.dot(position) / (e.magnitude() * position.magnitude())
    value = max(-1.0, min(1.0, value))
    nu = math.acos(value)

    if position.dot(velocity) < 0:
        nu = 2 * math.pi - nu
    return nu


# =============================================================================
# CARTESIAN -> CLASSICAL ORBITAL ELEMENTS
#
# Converts:
#
# Position + Velocity
#
# Into:
#
# a
# e
# i
# Ω
# ω
# ν
# =============================================================================


def orbital_elements(position: Vector3, velocity: Vector3, mu: float = EARTH_MU):
    from engine.astrodynamics.orbital_elements import OrbitalElements
    return OrbitalElements(
        semi_major_axis(position, velocity, mu),
        eccentricity(position, velocity, mu),
        inclination(position, velocity),
        raan(position, velocity),
        argument_of_periapsis(position, velocity, mu),
        true_anomaly(position, velocity, mu)
    )