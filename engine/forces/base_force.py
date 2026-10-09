from abc import ABC, abstractmethod


class Force(ABC):
    """
    Force plugin contract.

    Each plugin builds and registers its own Orekit ForceModel with the
    per-spacecraft NumericalPropagator via register_with_propagator(...).
    No manual acceleration path; propagation is Orekit-only.
    """

    @abstractmethod
    def register_with_propagator(
        self,
        propagator,
        body,
        universe,
        central_body,
        central_body_shape,
        inertial_frame,
    ) -> None:
        """Add the Orekit ForceModel for this plugin to the propagator."""
        raise NotImplementedError