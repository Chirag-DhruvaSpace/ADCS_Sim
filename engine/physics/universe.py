from engine.astrodynamics.constants import EARTH_FLATTENING
from engine.astrodynamics.state_vector import StateVector
from engine.forces.force_model import ForceModel
from engine.math.vector3 import Vector3
from engine.physics.atmosphere import AtmosphericModel, NullAtmosphere
from engine.physics.integrator import IntegratorConfig


class Universe:
    """
    Modular simulation universe powered by Orekit (orekit_jpype).

    Architecture (preserved):
        bodies              - list of Body objects
        force_model         - aggregator of Force plugins
        atmosphere_model    - AtmosphericModel (direct queries)
        clock               - SimulationClock abstraction
        add_body / add_force / set_clock / ...

    Internals:
        - One NumericalPropagator per spacecraft Body (DOP853, EQUINOCTIAL).
        - Each Force plugin's register_with_propagator(...) is called when
          the propagator is built.
        - Central-gravity guarantee: exactly one source of the two-body
          term.  A harmonics plugin flags `provides_central_gravity = True`
          (its EGM field already contains the central term); if no plugin
          supplies it, Universe adds one NewtonianAttraction(mu).  This is
          version-independent and never double-counts.
        - step(dt, integrator) propagates every spacecraft to
          clock.time + dt and writes PV back into body.state.
    """

    def __init__(
        self,
        force_model: ForceModel | None = None,
        atmosphere_model: AtmosphericModel | None = None,
        inertial_frame: str = "EME2000",
        central_body_name: str = "Earth",
        integrator_config: IntegratorConfig | None = None,
        ensure_central_gravity: bool = True,
    ) -> None:
        # Ensure JVM + data are loaded before any Orekit class is touched.
        from engine.orekit_runtime import ensure_initialized
        ensure_initialized()

        self.bodies = []
        self.force_model = force_model if force_model is not None else ForceModel()
        self.atmosphere_model = (
            atmosphere_model if atmosphere_model is not None else NullAtmosphere()
        )
        self.clock = None
        self.inertial_frame_name = inertial_frame
        self.central_body_name = central_body_name
        self.integrator_config = (
            integrator_config if integrator_config is not None else IntegratorConfig()
        )
        self.ensure_central_gravity = ensure_central_gravity

        self._inertial_frame = None
        self._central_body_shape = None
        self._propagators = {}  # body.name -> NumericalPropagator

    # ------------------------------------------------------------------
    # Body / force / clock management
    # ------------------------------------------------------------------
    def add_body(self, body) -> None:
        self.bodies.append(body)

    def remove_body(self, body) -> None:
        self.bodies.remove(body)
        self._propagators.pop(body.name, None)

    def set_clock(self, clock) -> None:
        self.clock = clock

    def add_force(self, force) -> None:
        self.force_model.add_force(force)
        self._propagators.clear()  # forces changed -> rebuild propagators

    def remove_force(self, force) -> None:
        self.force_model.remove_force(force)
        self._propagators.clear()

    # ------------------------------------------------------------------
    # Direct environment query (logging / GUI display)
    # ------------------------------------------------------------------
    def atmosphere_at(self, position_m):
        return self.atmosphere_model.state_at(position_m, self.clock)

    # ------------------------------------------------------------------
    # Orekit internals
    # ------------------------------------------------------------------
    def _get_inertial_frame(self):
        if self._inertial_frame is None:
            from org.orekit.frames import FramesFactory
            from org.orekit.utils import IERSConventions
            name = self.inertial_frame_name.lower()
            if name in ("gcrf", "eme2000", "eci"):
                self._inertial_frame = FramesFactory.getEME2000()
            elif name in ("itrf", "ecef"):
                self._inertial_frame = FramesFactory.getITRF(
                    IERSConventions.IERS_2010, False
                )
            else:
                self._inertial_frame = FramesFactory.getEME2000()
        return self._inertial_frame

    def _find_central_body(self):
        for b in self.bodies:
            if b.name == self.central_body_name or getattr(b, "central_body", False):
                return b
        return None

    def _get_central_body_shape(self):
        if self._central_body_shape is None:
            from org.orekit.bodies import OneAxisEllipsoid
            from org.orekit.frames import FramesFactory
            from org.orekit.utils import IERSConventions
            central_body = self._find_central_body()
            if central_body is None:
                raise ValueError(
                    f"Central body '{self.central_body_name}' not in universe.bodies."
                )
            self._central_body_shape = OneAxisEllipsoid(
                central_body.radius,
                EARTH_FLATTENING,
                FramesFactory.getITRF(IERSConventions.IERS_2010, False),
            )
        return self._central_body_shape

    def _build_spacecraft_state(self, body):
        from org.orekit.utils import PVCoordinates
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        from org.orekit.orbits import CartesianOrbit
        from org.orekit.propagation import SpacecraftState

        central_body = self._find_central_body()
        mu = (
            central_body.gravitational_parameter
            if central_body is not None
            else body.gravitational_parameter
        )

        pos = Vector3D(
            float(body.position.x), float(body.position.y), float(body.position.z)
        )
        vel = Vector3D(
            float(body.velocity.x), float(body.velocity.y), float(body.velocity.z)
        )
        orbit = CartesianOrbit(
            PVCoordinates(pos, vel),
            self._get_inertial_frame(),
            self.clock.absolute_date(),
            float(mu),
        )
        return SpacecraftState(orbit, float(body.mass))

    def _ensure_propagator(self, body):
        if body.name in self._propagators:
            return self._propagators[body.name]

        from org.orekit.propagation.numerical import NumericalPropagator
        from org.orekit.orbits import OrbitType

        integrator = self.integrator_config.build_hipparchus_integrator()
        propagator = NumericalPropagator(integrator)

        # EQUINOCTIAL prevents the Cartesian step-size shrinkage deadlock.
        propagator.setOrbitType(OrbitType.EQUINOCTIAL)

        central_body = self._find_central_body()
        propagator.setMu(float(central_body.gravitational_parameter))

        central_shape = self._get_central_body_shape()
        inertial = self._get_inertial_frame()

        self.force_model.register_all_with_propagator(
            propagator=propagator,
            body=body,
            universe=self,
            central_body=central_body,
            central_body_shape=central_shape,
            inertial_frame=inertial,
        )

        # --- Central-gravity guarantee --------------------------------
        # Exactly one source of the two-body term:
        #   * a harmonics plugin flags provides_central_gravity = True
        #     (its EGM field includes the central term), or
        #   * Universe adds one explicit NewtonianAttraction(mu).
        # This is correct whether or not the Orekit build auto-supplies
        # the central term for an empty force list, and never
        # double-counts when harmonics are active.
        if self.ensure_central_gravity:
            central_covered = any(
                getattr(f, "provides_central_gravity", False)
                for f in self.force_model.forces
            )
            if not central_covered:
                from org.orekit.forces.gravity import NewtonianAttraction
                propagator.addForceModel(
                    NewtonianAttraction(
                        float(central_body.gravitational_parameter)
                    )
                )

        propagator.setInitialState(self._build_spacecraft_state(body))
        self._propagators[body.name] = propagator
        return propagator

    def reset_propagators(self) -> None:
        """Drop cached propagators (e.g. after editing body state directly)."""
        self._propagators.clear()

    # ------------------------------------------------------------------
    # Step - pure Orekit propagation
    # ------------------------------------------------------------------
    def step(self, dt: float, integrator=None) -> None:
        if self.clock is None:
            raise RuntimeError("Universe.set_clock(...) must be called before step().")

        # Allow caller to swap integrator config at runtime.
        if integrator is not None and hasattr(integrator, "config"):
            self.integrator_config = integrator.config

        target_date = self.clock.absolute_date().shiftedBy(float(dt))

        central_body = self._find_central_body()
        for body in self.bodies:
            body.reset_acceleration()
            if body is central_body:
                continue
            if not getattr(body, "is_spacecraft", True):
                continue

            propagator = self._ensure_propagator(body)
            new_state = propagator.propagate(target_date)
            pv = new_state.getPVCoordinates(self._get_inertial_frame())

            body.position = Vector3(
                pv.getPosition().getX(),
                pv.getPosition().getY(),
                pv.getPosition().getZ(),
            )
            body.velocity = Vector3(
                pv.getVelocity().getX(),
                pv.getVelocity().getY(),
                pv.getVelocity().getZ(),
            )

        self.clock.advance(dt)