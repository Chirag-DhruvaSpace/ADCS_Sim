from engine.forces.base_force import Force
from engine.physics.shadow import CylindricalShadowModel
from engine.physics.sun_ephemeris import SunEphemeris


class SolarRadiationPressureForce(Force):
    """
    Solar Radiation Pressure via Orekit SolarRadiationPressure force with
    a conical shadow model (penumbra + umbra), using the body's optical
    properties (Cr, reference area) and the JPL-DE Sun ephemeris.

    The sun_ephemeris / shadow_model constructor arguments are kept for
    architecture compatibility but are NOT used by the Orekit path: Orekit
    provides its own Sun and conical shadow internally.
    """

    def __init__(
        self,
        spacecraft_name: str,
        sun_ephemeris: SunEphemeris,
        shadow_model: CylindricalShadowModel,
    ) -> None:
        if not spacecraft_name:
            raise ValueError(
                "SolarRadiationPressureForce.spacecraft_name must be non-empty."
            )
        self.spacecraft_name = spacecraft_name
        self.sun_ephemeris = sun_ephemeris
        self.shadow_model = shadow_model

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
            or body.physical_properties.optical is None
        ):
            raise ValueError(
                f"Body '{body.name}' missing OpticalProperties for Orekit SRP."
            )

        from org.orekit.forces.radiation import (
            SolarRadiationPressure,
            IsotropicRadiationSingleCoefficient,
        )
        from org.orekit.bodies import CelestialBodyFactory

        sun = CelestialBodyFactory.getSun()
        optical = body.physical_properties.optical

        spacecraft = IsotropicRadiationSingleCoefficient(
            float(optical.reference_area_m2),
            float(optical.reflectivity_coefficient),
        )

        # Use Orekit's body-shape-aware SRP constructor; it internally handles
        # eclipse geometry against the provided OneAxisEllipsoid.
        propagator.addForceModel(
            SolarRadiationPressure(sun, central_body_shape, spacecraft)
        )