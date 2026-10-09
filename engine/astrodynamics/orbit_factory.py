import math

from engine.math.vector3 import Vector3
from engine.astrodynamics.state_vector import StateVector
from engine.astrodynamics.orbital_elements import OrbitalElements
from engine.astrodynamics.constants import EARTH_MU


# =============================================================================
# ORBITAL ELEMENTS -> CARTESIAN STATE VECTOR
#
# Converts Classical Orbital Elements into:
#
# Position Vector
# Velocity Vector
#
# Assumes:
# - Two-body dynamics
# - Earth-centered inertial frame
#
# Its very easy to convert from state vectors to orbital elements, do calculations then with less computations and then convert this to state vector again, as calculating only in state vector is very complex.
# =============================================================================


def elements_to_state(elements: OrbitalElements, mu: float = EARTH_MU) -> StateVector:

    a = elements.a
    e = elements.e
    i = elements.i
    raan = elements.raan
    aop = elements.aop
    ta = elements.ta

    p = a * (1 - e ** 2)            # Semi-latus rectum

    r = p / (1 + e * math.cos(ta))          # Orbital radius

    r_pf = Vector3(             # Position in the perifocal frame
        r * math.cos(ta),
        r * math.sin(ta),
        0
    )

    factor = math.sqrt(mu / p)          # Velocity in the perifocal frame

    v_pf = Vector3(
        -factor * math.sin(ta),
        factor * (e + math.cos(ta)),
        0
    )

    cos_O = math.cos(raan)              # Rotation matrix terms
    sin_O = math.sin(raan)

    cos_i = math.cos(i)
    sin_i = math.sin(i)

    cos_w = math.cos(aop)
    sin_w = math.sin(aop)

    R11 = cos_O * cos_w - sin_O * sin_w * cos_i
    R12 = -cos_O * sin_w - sin_O * cos_w * cos_i
    R13 = sin_O * sin_i

    R21 = sin_O * cos_w + cos_O * sin_w * cos_i
    R22 = -sin_O * sin_w + cos_O * cos_w * cos_i
    R23 = -cos_O * sin_i

    R31 = sin_w * sin_i
    R32 = cos_w * sin_i
    R33 = cos_i

    position = Vector3(
        R11 * r_pf.x + R12 * r_pf.y + R13 * r_pf.z,
        R21 * r_pf.x + R22 * r_pf.y + R23 * r_pf.z,
        R31 * r_pf.x + R32 * r_pf.y + R33 * r_pf.z
    )

    velocity = Vector3(
        R11 * v_pf.x + R12 * v_pf.y + R13 * v_pf.z,
        R21 * v_pf.x + R22 * v_pf.y + R23 * v_pf.z,
        R31 * v_pf.x + R32 * v_pf.y + R33 * v_pf.z
    )

    return StateVector(position, velocity)