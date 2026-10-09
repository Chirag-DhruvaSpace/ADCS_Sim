from engine.forces.base_force import Force
from engine.physics.atmosphere import get_cssi_space_weather_data


class AtmosphericDragForce(Force):
    """
    Atmospheric drag via Orekit DragForce + NRLMSISE-00 atmosphere and an
    IsotropicDrag spacecraft model built from the body's aerodynamic
    properties (Cd, reference area).

    The CssiSpaceWeatherData input (solar flux / geomagnetic indices) is
    parsed once per process and shared with every other consumer.
    """

    def __init__(self, spacecraft_name: str) -> None:
        if not spacecraft_name:
            raise ValueError(
                "AtmosphericDragForce.spacecraft_name must be a non-empty string."
            )
        self.spacecraft_name = spacecraft_name

    def register_with_propagator(
        self,
        propagator,
        body,
        universe,
        central_body,
        central_body_shape,
        inertial_frame,
    ) -> None:
        if body.name != self.spacecraft_name:
            return

        if (
            body.physical_properties is None
            or body.physical_properties.aerodynamic is None
        ):
            raise ValueError(
                f"Body '{body.name}' missing AerodynamicProperties for Orekit drag."
            )

        from org.orekit.forces.drag import DragForce, IsotropicDrag
        from org.orekit.models.earth.atmosphere import NRLMSISE00
        from org.orekit.bodies import CelestialBodyFactory

        input_params = get_cssi_space_weather_data()
        sun = CelestialBodyFactory.getSun()
        atmosphere = NRLMSISE00(input_params, sun, central_body_shape)

        aero = body.physical_properties.aerodynamic
        spacecraft = IsotropicDrag(
            float(aero.reference_area_m2),
            float(aero.drag_coefficient),
        )

        propagator.addForceModel(DragForce(atmosphere, spacecraft))