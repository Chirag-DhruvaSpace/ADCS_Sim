from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.math.vector3 import Vector3
from engine.simulation.clock import SimulationClock


@dataclass(frozen=True)
class AtmosphericState:
    geometric_altitude_m: float
    density_kg_per_m3: float
    temperature_kelvin: float
    pressure_pascals: float
    atmospheric_velocity_mps: Vector3

    def __post_init__(self) -> None:
        if self.geometric_altitude_m < -1000.0:
            raise ValueError("geometric_altitude_m must be >= -1000.0")
        if self.density_kg_per_m3 < 0.0:
            raise ValueError("density_kg_per_m3 must be >= 0")
        if self.temperature_kelvin < 0.0:
            raise ValueError("temperature_kelvin must be >= 0")
        if self.pressure_pascals < 0.0:
            raise ValueError("pressure_pascals must be >= 0")


class AtmosphericModel(ABC):
    @abstractmethod
    def state_at(
        self,
        position_m: Vector3,
        clock: SimulationClock | None,
    ) -> AtmosphericState:
        raise NotImplementedError


class NullAtmosphere(AtmosphericModel):
    """Vacuum model - zero density. Used when no drag is desired."""

    def state_at(self, position_m, clock):
        return AtmosphericState(
            geometric_altitude_m=0.0,
            density_kg_per_m3=0.0,
            temperature_kelvin=0.0,
            pressure_pascals=0.0,
            atmospheric_velocity_mps=Vector3(0.0, 0.0, 0.0),
        )


# ---------------------------------------------------------------------------
# Cached space-weather data (shared by drag force, query atmosphere, main.py)
# ---------------------------------------------------------------------------
_CSSI_SPACE_WEATHER = None


def get_cssi_space_weather_data():
    """
    Process-wide cached CssiSpaceWeatherData.

    Parsing the SpaceWeather file is relatively expensive; parse it once
    and share the instance across every propagator / atmosphere built in
    this process.  Uses the Orekit 11+ constructor with the strict regex
    supportedNames pattern and the default DataContext + UTC timescale.
    """
    global _CSSI_SPACE_WEATHER
    if _CSSI_SPACE_WEATHER is None:
        from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData
        from org.orekit.data import DataContext
        from org.orekit.time import TimeScalesFactory

        dpm = DataContext.getDefault().getDataProvidersManager()
        utc = TimeScalesFactory.getUTC()
        # Regex pattern strictly required by Orekit (NOT a file glob).
        _CSSI_SPACE_WEATHER = CssiSpaceWeatherData("SpaceWeather.*\\.txt", dpm, utc)
    return _CSSI_SPACE_WEATHER


class NRLMSISE00Atmosphere(AtmosphericModel):
    """
    Orekit NRLMSISE-00 wrapper for direct density queries (logging,
    post-processing, GUI display).  During drag propagation, Orekit's
    NRLMSISE00 is used directly inside DragForce - this class is for
    out-of-band queries only.

    FIXED: uses the Orekit 11+ 3-argument constructor
    (CssiSpaceWeatherData, sun, shape); the old 1-argument
    NRLMSISE00(shape) constructor no longer exists.
    """

    def __init__(self, central_body_shape) -> None:
        from org.orekit.models.earth.atmosphere import NRLMSISE00
        from org.orekit.bodies import CelestialBodyFactory

        self._nrlmsise = NRLMSISE00(
            get_cssi_space_weather_data(),
            CelestialBodyFactory.getSun(),
            central_body_shape,
        )

    def state_at(self, position_m, clock):
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        from org.orekit.frames import FramesFactory
        from org.orekit.time import AbsoluteDate

        from engine.astrodynamics.constants import EARTH_RADIUS
        from engine.physics.earth_rotation import EarthRotation

        if clock is None:
            # NOTE: J2000 may lie outside the SpaceWeather file coverage;
            # prefer always passing a clock with a valid epoch.
            date = AbsoluteDate.J2000_EPOCH
            frame = FramesFactory.getEME2000()
        else:
            date = clock.absolute_date()
            frame = self._frame_for(clock)

        pos = Vector3D(float(position_m.x), float(position_m.y), float(position_m.z))
        density = float(self._nrlmsise.getDensity(date, pos, frame))

        v_atm = EarthRotation.atmospheric_velocity(position_m)
        geom_alt = position_m.magnitude() - EARTH_RADIUS

        return AtmosphericState(
            geometric_altitude_m=geom_alt,
            density_kg_per_m3=density,
            temperature_kelvin=0.0,
            pressure_pascals=0.0,
            atmospheric_velocity_mps=v_atm,
        )

    @staticmethod
    def _frame_for(clock):
        # If clock carries a frame hint, use it; otherwise EME2000.
        return getattr(clock, "_frame", None) or FramesFactory.getEME2000()