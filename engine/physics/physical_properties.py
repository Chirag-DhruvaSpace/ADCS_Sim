from dataclasses import dataclass


@dataclass(frozen=True)
class AerodynamicProperties:
    """
    Spacecraft aerodynamic metadata used by future atmospheric drag models.

    This container intentionally excludes core body attributes such as mass and
    radius, which remain owned by Body. The separation keeps spacecraft drag
    metadata decoupled from orbital state and gravity configuration.
    """

    drag_coefficient: float
    reference_area_m2: float

    def __post_init__(self) -> None:
        if self.drag_coefficient <= 0.0:
            raise ValueError(
                "AerodynamicProperties.drag_coefficient must be > 0."
            )
        if self.reference_area_m2 <= 0.0:
            raise ValueError(
                "AerodynamicProperties.reference_area_m2 must be > 0."
            )


@dataclass(frozen=True)
class OpticalProperties:
    """
    Spacecraft optical metadata used by future solar radiation pressure models.

    This container intentionally excludes core body attributes such as mass and
    radius, which remain owned by Body. The separation keeps SRP metadata
    decoupled from orbital state and gravity configuration.
    """

    reflectivity_coefficient: float
    reference_area_m2: float

    def __post_init__(self) -> None:
        if self.reflectivity_coefficient < 0.0:
            raise ValueError(
                "OpticalProperties.reflectivity_coefficient must be >= 0."
            )
        if self.reference_area_m2 <= 0.0:
            raise ValueError(
                "OpticalProperties.reference_area_m2 must be > 0."
            )


@dataclass(frozen=True)
class PhysicalProperties:
    """
    Optional spacecraft-specific physical metadata for non-conservative forces.

    Body remains the owner of mass, radius, gravity model, and state. This
    aggregation only carries optional force-model metadata (aerodynamic and
    optical properties) needed by future drag and SRP plugins.
    """

    aerodynamic: AerodynamicProperties | None = None
    optical: OpticalProperties | None = None