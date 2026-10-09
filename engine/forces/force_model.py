class ForceModel:
    """
    Aggregator of force plugins.  Each plugin registers its Orekit
    ForceModel with the propagator when the Universe builds it.
    """

    def __init__(self) -> None:
        self.forces = []

    def add_force(self, force) -> None:
        self.forces.append(force)

    def remove_force(self, force) -> None:
        self.forces.remove(force)

    def clear(self) -> None:
        self.forces.clear()

    def register_all_with_propagator(
        self,
        propagator,
        body,
        universe,
        central_body,
        central_body_shape,
        inertial_frame,
    ) -> None:
        for force in self.forces:
            force.register_with_propagator(
                propagator=propagator,
                body=body,
                universe=universe,
                central_body=central_body,
                central_body_shape=central_body_shape,
                inertial_frame=inertial_frame,
            )