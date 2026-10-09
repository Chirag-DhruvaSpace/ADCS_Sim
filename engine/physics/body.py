from engine.astrodynamics.constants import G, GravityModel
from engine.astrodynamics.state_vector import StateVector
from engine.math.vector3 import Vector3
from engine.physics.physical_properties import PhysicalProperties


class Body:
    """
    Physical body in the simulation.

    central_body  : True for the body around which spacecraft orbit (Earth).
                    Skipped by the propagator.
    is_spacecraft : True if this body should be propagated by an Orekit
                    NumericalPropagator.  Set False for celestial ephemeris-
                    driven bodies (future).
    """

    def __init__(
        self,
        name: str,
        mass: float,
        radius: float,
        position: Vector3,
        velocity: Vector3,
        gravitational_parameter: float | None = None,
        gravity_model: GravityModel | None = None,
        physical_properties: PhysicalProperties | None = None,
        central_body: bool = False,
        is_spacecraft: bool = True,
    ) -> None:
        self.name = name
        self.mass = float(mass)
        self.radius = float(radius)
        self.gravitational_parameter = (
            float(gravitational_parameter)
            if gravitational_parameter is not None
            else G * float(mass)
        )
        self.gravity_model = gravity_model
        self.physical_properties = physical_properties
        self.state = StateVector(position, velocity)
        self.acceleration = Vector3()
        self.central_body = central_body
        self.is_spacecraft = is_spacecraft

    @property
    def position(self) -> Vector3:
        return self.state.position

    @position.setter
    def position(self, value: Vector3) -> None:
        self.state.position = value

    @property
    def velocity(self) -> Vector3:
        return self.state.velocity

    @velocity.setter
    def velocity(self, value: Vector3) -> None:
        self.state.velocity = value

    def reset_acceleration(self) -> None:
        self.acceleration = Vector3()