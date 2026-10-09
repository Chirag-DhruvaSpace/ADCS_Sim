"""
High-fidelity 24-hour LEO propagation with the engine.

Validates the engine against an independent raw-Orekit reference
propagator built with identical force models, identical integrator
configuration (both read from engine.astrodynamics.constants via
IntegratorConfig), identical frame, epoch and mu.

Expected outcome:
  * ENGINE (full) vs OREKIT REFERENCE -> ~0 m (identical computation;
    only the plugin plumbing differs)
  * Kepler-only vs reference          -> tens of km (J2+drag+SRP over 24 h)
  * EGM2008-only vs reference         -> hundreds of m to km (drag + SRP)

Usage:
    python main.py
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Start the orekit_jpype JVM and load orekit-data BEFORE any `from org.*`.
# ---------------------------------------------------------------------------
import engine.orekit_runtime  # noqa: F401  (side-effect import)

# ---------------------------------------------------------------------------
# 2. Now `from org.*` imports are safe.
# ---------------------------------------------------------------------------
import math
from dataclasses import dataclass

from engine.astrodynamics import orbital_math
from engine.astrodynamics.constants import EARTH_MASS, EARTH_MU, EARTH_RADIUS
from engine.forces.atmospheric_drag import AtmosphericDragForce
from engine.forces.gravity import GravityForce, GravityMode
from engine.forces.solar_radiation_pressure import SolarRadiationPressureForce
from engine.forces.zonal_harmonics import ZonalHarmonicsForce
from engine.math.vector3 import Vector3
from engine.physics.atmosphere import get_cssi_space_weather_data
from engine.physics.body import Body
from engine.physics.integrator import DOP853Integrator, IntegratorConfig
from engine.physics.physical_properties import (
    AerodynamicProperties,
    OpticalProperties,
    PhysicalProperties,
)
from engine.physics.shadow import CylindricalShadowModel
from engine.physics.sun_ephemeris import OrekitSunEphemeris
from engine.physics.universe import Universe
from engine.simulation.clock import SimulationClock

from org.hipparchus.geometry.euclidean.threed import Vector3D
from org.orekit.bodies import CelestialBodyFactory, OneAxisEllipsoid
from org.orekit.forces.drag import DragForce, IsotropicDrag
from org.orekit.forces.gravity import HolmesFeatherstoneAttractionModel
from org.orekit.forces.gravity.potential import GravityFieldFactory
from org.orekit.forces.radiation import (
    IsotropicRadiationSingleCoefficient,
    SolarRadiationPressure,
)
from org.orekit.frames import FramesFactory
from org.orekit.models.earth.atmosphere import NRLMSISE00
from org.orekit.orbits import CartesianOrbit, OrbitType
from org.orekit.propagation import SpacecraftState
from org.orekit.propagation.numerical import NumericalPropagator
from org.orekit.time import AbsoluteDate, TimeScalesFactory
from org.orekit.utils import Constants, IERSConventions, PVCoordinates

# ---------------------------------------------------------------------------
# Scenario constants - ISS-like LEO at 400 km
# ---------------------------------------------------------------------------
ALTITUDE_M = 400_000.0
INCLINATION_DEG = 51.6
SPACECRAFT_MASS = 200.0          # kg
DRAG_COEFFICIENT = 2.2
DRAG_AREA_M2 = 4.0
SRP_CR = 1.3
SRP_AREA_M2 = 6.0
EGM_DEGREE = 36
EGM_ORDER = 36
PROPAGATION_DURATION_S = 24 * 3600.0

EARTH_FLATTENING = 1.0 / 298.257223563
OREKIT_EARTH_MU = float(Constants.WGS84_EARTH_MU)

# Epoch must lie inside the SpaceWeather*.txt coverage in orekit-data.
SIM_EPOCH = AbsoluteDate(2022, 1, 1, 0, 0, 0.0, TimeScalesFactory.getUTC())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_initial_pv() -> tuple[Vector3, Vector3]:
    """Simple circular-LEO initial state in EME2000."""
    r = EARTH_RADIUS + ALTITUDE_M
    v = math.sqrt(EARTH_MU / r)
    pos = Vector3(r, 0.0, 0.0)
    vel = Vector3(
        0.0,
        v * math.cos(math.radians(INCLINATION_DEG)),
        v * math.sin(math.radians(INCLINATION_DEG)),
    )
    return pos, vel


def make_clock() -> SimulationClock:
    clock = SimulationClock()
    clock.set_epoch(SIM_EPOCH)
    return clock


@dataclass
class FinalState:
    name: str
    position_m: Vector3
    velocity_mps: Vector3


def vector_diff_magnitude(a: Vector3, b: Vector3) -> float:
    return (a - b).magnitude()


def describe_state(state: FinalState) -> str:
    """Physical sanity summary - catches gross force-model errors instantly.

    A healthy 400 km LEO after 24 h: |r| ~ 6770-6780 km, a ~ 6770 km,
    small e.  A straight-line (missing central gravity) run shows
    |r| ~ 600,000+ km; a double-counted gravity run shows a collapsed,
    decaying orbit (a far below Earth radius).
    """
    r = state.position_m.magnitude()
    a = orbital_math.semi_major_axis(
        state.position_m, state.velocity_mps, OREKIT_EARTH_MU
    )
    e = orbital_math.eccentricity(
        state.position_m, state.velocity_mps, OREKIT_EARTH_MU
    )
    i_deg = math.degrees(
        orbital_math.inclination(state.position_m, state.velocity_mps)
    )
    return (
        f"|r|={r / 1000:10.3f} km  alt={(r - EARTH_RADIUS) / 1000:8.3f} km  "
        f"a={a / 1000:10.3f} km  e={e:.6f}  i={i_deg:8.4f} deg"
    )


# ---------------------------------------------------------------------------
# Scenario 1: Engine with FULL force model
# ---------------------------------------------------------------------------
def run_engine_full() -> FinalState:
    print("\n[Engine] Building Universe with full force model...", flush=True)

    pos0, vel0 = make_initial_pv()

    earth = Body(
        name="Earth",
        mass=EARTH_MASS,
        radius=EARTH_RADIUS,
        position=Vector3(0.0, 0.0, 0.0),
        velocity=Vector3(0.0, 0.0, 0.0),
        gravitational_parameter=OREKIT_EARTH_MU,
        central_body=True,
        is_spacecraft=False,
    )
    sc = Body(
        name="Spacecraft",
        mass=SPACECRAFT_MASS,
        radius=1.0,
        position=pos0,
        velocity=vel0,
        physical_properties=PhysicalProperties(
            aerodynamic=AerodynamicProperties(DRAG_COEFFICIENT, DRAG_AREA_M2),
            optical=OpticalProperties(SRP_CR, SRP_AREA_M2),
        ),
        is_spacecraft=True,
    )

    universe = Universe(
        central_body_name="Earth",
        inertial_frame="EME2000",
        integrator_config=IntegratorConfig(),
    )
    universe.add_body(earth)
    universe.add_body(sc)
    universe.set_clock(make_clock())

    universe.add_force(GravityForce(GravityMode.CENTRAL_BODY, "Earth"))
    universe.add_force(ZonalHarmonicsForce("Earth", EGM_DEGREE, EGM_ORDER))
    universe.add_force(AtmosphericDragForce("Spacecraft"))
    universe.add_force(
        SolarRadiationPressureForce(
            "Spacecraft",
            OrekitSunEphemeris(),
            CylindricalShadowModel(EARTH_RADIUS),
        )
    )

    print("  Engine built. Propagating 24 hours in a single call...", flush=True)
    universe.step(PROPAGATION_DURATION_S, integrator=DOP853Integrator())

    print(
        f"  engine @ t = 24.00 h   pos = "
        f"({sc.position.x:14.3f}, {sc.position.y:14.3f}, {sc.position.z:14.3f}) m",
        flush=True,
    )
    return FinalState("Engine full", sc.position, sc.velocity)


# ---------------------------------------------------------------------------
# Scenario 2: Raw Orekit reference (industry standard), identical config
# ---------------------------------------------------------------------------
def run_orekit_reference() -> FinalState:
    print("\n[Reference] Building raw Orekit NumericalPropagator...", flush=True)

    pos0, vel0 = make_initial_pv()

    frame = FramesFactory.getEME2000()
    body_frame = FramesFactory.getITRF(IERSConventions.IERS_2010, False)
    date = SIM_EPOCH
    earth_shape = OneAxisEllipsoid(EARTH_RADIUS, EARTH_FLATTENING, body_frame)

    orbit = CartesianOrbit(
        PVCoordinates(
            Vector3D(float(pos0.x), float(pos0.y), float(pos0.z)),
            Vector3D(float(vel0.x), float(vel0.y), float(vel0.z)),
        ),
        frame,
        date,
        OREKIT_EARTH_MU,
    )
    initial_state = SpacecraftState(orbit, float(SPACECRAFT_MASS))

    # SAME integrator configuration as the engine (single source of truth).
    integrator = IntegratorConfig().build_hipparchus_integrator()
    propagator = NumericalPropagator(integrator)
    propagator.setOrbitType(OrbitType.EQUINOCTIAL)
    propagator.setMu(OREKIT_EARTH_MU)

    # Full EGM2008
    provider = GravityFieldFactory.getNormalizedProvider(EGM_DEGREE, EGM_ORDER)
    propagator.addForceModel(
        HolmesFeatherstoneAttractionModel(earth_shape.getBodyFrame(), provider)
    )

    # Drag with NRLMSISE-00
    sun = CelestialBodyFactory.getSun()
    atmosphere = NRLMSISE00(get_cssi_space_weather_data(), sun, earth_shape)
    propagator.addForceModel(
        DragForce(
            atmosphere,
            IsotropicDrag(float(DRAG_AREA_M2), float(DRAG_COEFFICIENT)),
        )
    )

    # SRP with body-shape-aware eclipse geometry
    sc_srp = IsotropicRadiationSingleCoefficient(
        float(SRP_AREA_M2), float(SRP_CR)
    )
    propagator.addForceModel(SolarRadiationPressure(sun, earth_shape, sc_srp))

    propagator.setInitialState(initial_state)
    target_date = date.shiftedBy(float(PROPAGATION_DURATION_S))

    print("  Reference built. Propagating 24 hours...", flush=True)
    final_state = propagator.propagate(target_date)
    pv = final_state.getPVCoordinates(frame)

    return FinalState(
        "Orekit reference",
        Vector3(
            pv.getPosition().getX(),
            pv.getPosition().getY(),
            pv.getPosition().getZ(),
        ),
        Vector3(
            pv.getVelocity().getX(),
            pv.getVelocity().getY(),
            pv.getVelocity().getZ(),
        ),
    )


# ---------------------------------------------------------------------------
# Scenario 3: Engine with reduced models (perturbation magnitudes)
# ---------------------------------------------------------------------------
def run_engine_reduced(
    name: str,
    *,
    with_harmonics: bool,
    with_drag: bool,
    with_srp: bool,
) -> FinalState:
    print(f"\n[Engine] Building Universe with reduced model: {name}...", flush=True)

    pos0, vel0 = make_initial_pv()

    earth = Body(
        name="Earth",
        mass=EARTH_MASS,
        radius=EARTH_RADIUS,
        position=Vector3(0.0, 0.0, 0.0),
        velocity=Vector3(0.0, 0.0, 0.0),
        gravitational_parameter=OREKIT_EARTH_MU,
        central_body=True,
        is_spacecraft=False,
    )
    sc = Body(
        name="Spacecraft",
        mass=SPACECRAFT_MASS,
        radius=1.0,
        position=pos0,
        velocity=vel0,
        physical_properties=PhysicalProperties(
            aerodynamic=AerodynamicProperties(DRAG_COEFFICIENT, DRAG_AREA_M2),
            optical=OpticalProperties(SRP_CR, SRP_AREA_M2),
        ),
    )

    universe = Universe(central_body_name="Earth", inertial_frame="EME2000")
    universe.add_body(earth)
    universe.add_body(sc)
    universe.set_clock(make_clock())

    universe.add_force(GravityForce(GravityMode.CENTRAL_BODY, "Earth"))
    if with_harmonics:
        universe.add_force(ZonalHarmonicsForce("Earth", EGM_DEGREE, EGM_ORDER))
    if with_drag:
        universe.add_force(AtmosphericDragForce("Spacecraft"))
    if with_srp:
        universe.add_force(
            SolarRadiationPressureForce(
                "Spacecraft",
                OrekitSunEphemeris(),
                CylindricalShadowModel(EARTH_RADIUS),
            )
        )

    universe.step(PROPAGATION_DURATION_S, integrator=DOP853Integrator())
    return FinalState(name, sc.position, sc.velocity)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(title: str, ref: FinalState, cand: FinalState) -> None:
    pos_err = vector_diff_magnitude(cand.position_m, ref.position_m)
    vel_err = vector_diff_magnitude(cand.velocity_mps, ref.velocity_mps)

    print(f"\n--- {title} ---", flush=True)
    print(f"  Reference : {describe_state(ref)}", flush=True)
    print(f"  Candidate : {describe_state(cand)}", flush=True)
    print(f"  Position error (m)   : {pos_err:.6e}", flush=True)
    print(f"  Velocity error (m/s) : {vel_err:.6e}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 78, flush=True)
    print(" HIGH-FIDELITY 24-HOUR LEO PROPAGATION - ENGINE vs OREKIT REFERENCE",
          flush=True)
    print("=" * 78, flush=True)
    print(f"  Orbit      : {ALTITUDE_M / 1000:.1f} km circular, "
          f"{INCLINATION_DEG} deg incl (ISS-like)", flush=True)
    print(f"  Epoch      : {SIM_EPOCH} (must be inside SpaceWeather coverage)",
          flush=True)
    print(f"  Spacecraft : {SPACECRAFT_MASS} kg, Cd={DRAG_COEFFICIENT}, "
          f"A_drag={DRAG_AREA_M2} m2, Cr={SRP_CR}, A_srp={SRP_AREA_M2} m2",
          flush=True)
    print(f"  Gravity    : EGM2008 {EGM_DEGREE}x{EGM_ORDER} "
          f"(HolmesFeatherstone, body frame)", flush=True)
    print(f"  Atmosphere : NRLMSISE-00 + CssiSpaceWeatherData", flush=True)
    print(f"  SRP        : conical shadow (Orekit body-shape model)", flush=True)
    print(f"  Integrator : DOP853, EQUINOCTIAL, "
          f"tol=({IntegratorConfig().abs_tolerance:g},{IntegratorConfig().rel_tolerance:g}), "
          f"step=[{IntegratorConfig().min_step:g},{IntegratorConfig().max_step:g}]s",
          flush=True)

    engine_full = run_engine_full()
    reference = run_orekit_reference()
    kepler_only = run_engine_reduced(
        "Kepler only (two-body)",
        with_harmonics=False, with_drag=False, with_srp=False,
    )
    harmonics_only = run_engine_reduced(
        "EGM2008 only",
        with_harmonics=True, with_drag=False, with_srp=False,
    )

    print_report("ENGINE (full) vs OREKIT REFERENCE", reference, engine_full)
    print_report("Kepler-only vs OREKIT REFERENCE", reference, kepler_only)
    print_report("EGM2008-only vs OREKIT REFERENCE", reference, harmonics_only)

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()