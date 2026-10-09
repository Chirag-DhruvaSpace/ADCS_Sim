from abc import ABC, abstractmethod

from engine.math.vector3 import Vector3
from engine.simulation.clock import SimulationClock


class SunEphemeris(ABC):
    """Interface for Sun position providers."""

    @abstractmethod
    def position(self, clock: SimulationClock | None) -> Vector3:
        raise NotImplementedError


class OrekitSunEphemeris(SunEphemeris):
    """
    Orekit-backed Sun position provider.

    Uses JPL DE ephemerides (loaded via orekit-data) for the Sun position
    in the configured inertial frame at the simulation time.
    """

    def __init__(self, inertial_frame=None) -> None:
        from org.orekit.bodies import CelestialBodyFactory
        from org.orekit.frames import FramesFactory

        self._sun = CelestialBodyFactory.getSun()
        self._frame = inertial_frame or FramesFactory.getEME2000()

    def position(self, clock: SimulationClock | None) -> Vector3:
        from org.orekit.time import AbsoluteDate
        if clock is None:
            date = AbsoluteDate.J2000_EPOCH
        else:
            date = clock.absolute_date()
        pv = self._sun.getPVCoordinates(date, self._frame)
        return Vector3(
            pv.getPosition().getX(),
            pv.getPosition().getY(),
            pv.getPosition().getZ(),
        )