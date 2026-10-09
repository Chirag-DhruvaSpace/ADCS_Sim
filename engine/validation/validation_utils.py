import math
from dataclasses import dataclass
from typing import Protocol

from engine.astrodynamics.orbital_math import orbital_elements
from engine.math.vector3 import Vector3


TWO_PI = 2.0 * math.pi


def normalize_angle_rad(angle: float) -> float:
    """
    Normalize an angle to [0, 2*pi).
    """
    value = angle % TWO_PI
    if value < 0.0:
        value += TWO_PI
    return value


def wrap_to_pi_rad(angle: float) -> float:
    """
    Wrap an angle to (-pi, pi].
    """
    value = (angle + math.pi) % TWO_PI - math.pi
    if value <= -math.pi:
        value += TWO_PI
    return value


def smallest_angular_difference_rad(target: float, reference: float) -> float:
    """
    Signed smallest angular difference: target - reference in (-pi, pi].
    """
    return wrap_to_pi_rad(target - reference)


def unwrap_relative_to_reference_rad(angle: float, reference: float) -> float:
    """
    Return an unwrapped version of angle that is closest to reference.
    """
    return reference + smallest_angular_difference_rad(angle, reference)


def rad_to_deg(angle: float) -> float:
    return math.degrees(angle)


# =============================================================================
# SPECIFIC ORBITAL ENERGY
#
# epsilon = (v^2 / 2) - (mu / r)
# =============================================================================
def specific_orbital_energy(
    position: Vector3,
    velocity: Vector3,
    mu: float,
) -> float:
    radius = position.magnitude()
    speed_squared = velocity.magnitude_squared()
    return (speed_squared / 2.0) - (mu / radius)


# =============================================================================
# ANGULAR MOMENTUM VECTOR
#
# h_vec = r x v
# =============================================================================
def angular_momentum_vector(position: Vector3, velocity: Vector3) -> Vector3:
    return position.cross(velocity)


# =============================================================================
# ANGULAR MOMENTUM MAGNITUDE
#
# h = |h_vec|
# =============================================================================
def angular_momentum_magnitude(h_vec: Vector3) -> float:
    return h_vec.magnitude()


@dataclass(frozen=True)
class OrbitalSnapshot:
    a: float
    e: float
    i: float
    raan: float
    aop: float
    ta: float


def snapshot_from_cartesian(
    position: Vector3,
    velocity: Vector3,
    mu: float,
) -> OrbitalSnapshot:
    elements = orbital_elements(position, velocity, mu)
    return OrbitalSnapshot(
        a=elements.a,
        e=elements.e,
        i=elements.i,
        raan=normalize_angle_rad(elements.raan),
        aop=normalize_angle_rad(elements.aop),
        ta=normalize_angle_rad(elements.ta),
    )


# =============================================================================
# J2 SECULAR RAAN DRIFT (Vallado, 4th Ed., Non-spherical Earth perturbations)
#
# dOmega/dt = -(3/2) * J2 * n * (R/p)^2 * cos(i)
#
# n = sqrt(mu / a^3)
# p = a * (1 - e^2)
# =============================================================================
def expected_j2_raan_drift_rad(
    duration_seconds: float,
    a: float,
    e: float,
    i: float,
    mu: float,
    j2: float,
    gravity_reference_radius: float,
) -> float:
    p = a * (1.0 - e * e)
    if p == 0.0:
        return 0.0

    mean_motion = math.sqrt(mu / (a ** 3))
    raan_rate = (
        -1.5
        * j2
        * mean_motion
        * ((gravity_reference_radius / p) ** 2)
        * math.cos(i)
    )
    return raan_rate * duration_seconds


class PropagatorAdapter(Protocol):
    """
    Minimal adapter interface for future external propagators.
    """
    def propagate(self, duration_seconds: float, dt_seconds: float) -> None:
        ...

    def current_position(self) -> Vector3:
        ...

    def current_velocity(self) -> Vector3:
        ...