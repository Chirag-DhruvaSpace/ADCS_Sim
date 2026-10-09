from enum import Enum, auto

from engine.forces.base_force import Force


class GravityMode(Enum):
    N_BODY = auto()
    CENTRAL_BODY = auto()


class GravityForce(Force):
    """
    Newtonian point-mass gravity.

    CENTRAL_BODY mode:
        Registers nothing itself.  The central term is guaranteed by
        Universe._ensure_propagator(): if no registered force plugin flags
        itself with `provides_central_gravity = True` (the harmonics plugin
        does, because the EGM2008 field includes the degree-0 term), the
        Universe adds exactly one NewtonianAttraction(mu).  This makes the
        two-body term explicit and version-independent instead of relying
        on Orekit auto-supplying it for an empty force list.

    N_BODY mode:
        Registers Orekit ThirdBodyAttraction for every named celestial body
        in the universe (Sun, Moon, planets) using JPL DE ephemerides from
        orekit-data.  Add bodies named exactly "Sun", "Moon", "Mars", etc.
        to universe.bodies to activate them.  The central two-body term is
        handled exactly as in CENTRAL_BODY mode (Universe guarantee).
    """

    def __init__(
        self,
        mode: GravityMode = GravityMode.N_BODY,
        central_body_name: str | None = None,
    ) -> None:
        self.mode = mode
        self.central_body_name = central_body_name

    def register_with_propagator(
        self,
        propagator,
        body,
        universe,
        central_body,
        central_body_shape,
        inertial_frame,
    ) -> None:
        if self.mode == GravityMode.CENTRAL_BODY:
            # Central term supplied by the Universe guarantee
            # (NewtonianAttraction) or by a harmonics plugin (EGM field).
            return

        from org.orekit.forces.gravity import ThirdBodyAttraction
        from org.orekit.bodies import CelestialBodyFactory

        named = {
            "Sun":     CelestialBodyFactory.getSun(),
            "Moon":    CelestialBodyFactory.getMoon(),
            "Mercury": CelestialBodyFactory.getMercury(),
            "Venus":   CelestialBodyFactory.getVenus(),
            "Mars":    CelestialBodyFactory.getMars(),
            "Jupiter": CelestialBodyFactory.getJupiter(),
            "Saturn":  CelestialBodyFactory.getSaturn(),
            "Uranus":  CelestialBodyFactory.getUranus(),
            "Neptune": CelestialBodyFactory.getNeptune(),
        }

        for other in universe.bodies:
            if other is body or other is central_body:
                continue
            if other.name in named:
                propagator.addForceModel(ThirdBodyAttraction(named[other.name]))