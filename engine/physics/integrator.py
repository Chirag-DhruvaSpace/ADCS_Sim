from dataclasses import dataclass

from engine.astrodynamics.constants import (
    DOP853_MIN_STEP,
    DOP853_MAX_STEP,
    DOP853_ABS_TOLERANCE,
    DOP853_REL_TOLERANCE,
)


@dataclass(frozen=True)
class TranslationalStateDerivative:
    """Kept for compatibility; not used by the Orekit path."""
    position_rate: object
    velocity_rate: object


class IntegratorConfig:
    """
    Holder for DOP853 (Dormand-Prince 8(5),3) configuration.
    Universe uses this when building each spacecraft's NumericalPropagator.
    """

    def __init__(
        self,
        min_step: float = DOP853_MIN_STEP,
        max_step: float = DOP853_MAX_STEP,
        abs_tolerance: float = DOP853_ABS_TOLERANCE,
        rel_tolerance: float = DOP853_REL_TOLERANCE,
    ) -> None:
        self.min_step = float(min_step)
        self.max_step = float(max_step)
        self.abs_tolerance = float(abs_tolerance)
        self.rel_tolerance = float(rel_tolerance)

    def build_hipparchus_integrator(self):
        from org.hipparchus.ode.nonstiff import DormandPrince853Integrator
        return DormandPrince853Integrator(
            self.min_step,
            self.max_step,
            self.abs_tolerance,
            self.rel_tolerance,
        )


class DOP853Integrator:
    """
    High-fidelity integrator.  Acts as a configuration holder; actual
    integration is performed inside each per-spacecraft Orekit
    NumericalPropagator (which uses Hipparchus DormandPrince853Integrator
    built from this config).
    """

    def __init__(self, config: IntegratorConfig | None = None) -> None:
        self.config = config if config is not None else IntegratorConfig()

    def step(self, dt: float, universe=None) -> None:
        if universe is None:
            raise ValueError("DOP853Integrator.step requires the universe.")
        universe.step(dt, integrator=self)