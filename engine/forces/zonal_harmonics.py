from engine.forces.base_force import Force


class ZonalHarmonicsForce(Force):
    """
    Earth spherical-harmonics gravity via Orekit
    HolmesFeatherstoneAttractionModel with the full EGM2008 field up to
    configurable degree/order.

    The EGM2008 provider's field INCLUDES the central (degree-0) term,
    so this plugin flags `provides_central_gravity = True`.  Universe uses
    that flag to avoid adding a duplicate NewtonianAttraction.
    """

    # Marker consumed by Universe._ensure_propagator().
    provides_central_gravity = True

    DEFAULT_DEGREE = 36
    DEFAULT_ORDER = 36

    def __init__(
        self,
        central_body_name: str,
        degree: int = DEFAULT_DEGREE,
        order: int = DEFAULT_ORDER,
    ) -> None:
        self.central_body_name = central_body_name
        self.degree = int(degree)
        self.order = int(order)

    def register_with_propagator(
        self,
        propagator,
        body,
        universe,
        central_body,
        central_body_shape,
        inertial_frame,
    ) -> None:
        from org.orekit.forces.gravity import HolmesFeatherstoneAttractionModel
        from org.orekit.forces.gravity.potential import GravityFieldFactory

        provider = GravityFieldFactory.getNormalizedProvider(self.degree, self.order)
        propagator.addForceModel(
            # Expects the body-fixed Frame, not the OneAxisEllipsoid.
            HolmesFeatherstoneAttractionModel(
                central_body_shape.getBodyFrame(), provider
            )
        )