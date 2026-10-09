import os

from engine.math.vector3 import Vector3
from engine.validation.validation_types import (
    PropagationResult,
    PropagationSample,
    PropagatorAdapter,
    ValidationConfig,
)


_OREKIT_INITIALIZED = False
_OREKIT_IMPORTS = {}

HF_ONLY = "HF_ONLY"
NEWTONIAN_ONLY = "NEWTONIAN_ONLY"
BOTH = "BOTH"
_VALID_FORCE_MODEL_MODES = {HF_ONLY, NEWTONIAN_ONLY, BOTH}


def initialize_orekit() -> dict:
    """
    Initialize Orekit VM and Orekit data once per Python process.
    """
    global _OREKIT_INITIALIZED
    global _OREKIT_IMPORTS

    if _OREKIT_INITIALIZED:
        return _OREKIT_IMPORTS

    import jdk4py
    import orekit_jpype

    jvm_path = os.path.join(jdk4py.JAVA_HOME, "bin", "server", "jvm.dll")
    print("Initializing Orekit JVM...")
    orekit_jpype.initVM(jvmpath=jvm_path)
    print("Orekit JVM initialized.")

    from orekit_jpype.pyhelpers import setup_orekit_data

    orekit_data_path = os.environ.get("OREKIT_DATA_PATH")
    if not orekit_data_path:
        raise RuntimeError(
            "OREKIT_DATA_PATH is not set. Point it to orekit-data.zip or an "
            "orekit-data directory."
        )

    print(f"OREKIT_DATA_PATH: {orekit_data_path}")
    setup_orekit_data(filenames=orekit_data_path)
    print("Orekit data loaded.")

    print("Importing Java Orekit classes...")
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.hipparchus.ode.nonstiff import ClassicalRungeKuttaIntegrator
    from org.orekit.forces.gravity import HolmesFeatherstoneAttractionModel
    from org.orekit.forces.gravity.potential import GravityFieldFactory
    from org.orekit.frames import FramesFactory
    from org.orekit.orbits import CartesianOrbit, OrbitType
    from org.orekit.propagation import SpacecraftState
    from org.orekit.propagation.numerical import NumericalPropagator
    from org.orekit.time import AbsoluteDate, TimeScalesFactory
    from org.orekit.utils import IERSConventions, PVCoordinates
    print("Java imports successful.")

    _OREKIT_IMPORTS = {
        "Vector3D": Vector3D,
        "ClassicalRungeKuttaIntegrator": ClassicalRungeKuttaIntegrator,
        "HolmesFeatherstoneAttractionModel": HolmesFeatherstoneAttractionModel,
        "GravityFieldFactory": GravityFieldFactory,
        "FramesFactory": FramesFactory,
        "CartesianOrbit": CartesianOrbit,
        "OrbitType": OrbitType,
        "SpacecraftState": SpacecraftState,
        "NumericalPropagator": NumericalPropagator,
        "AbsoluteDate": AbsoluteDate,
        "TimeScalesFactory": TimeScalesFactory,
        "IERSConventions": IERSConventions,
        "PVCoordinates": PVCoordinates,
    }

    try:
        from org.orekit.forces.gravity import NewtonianAttractionModel
        _OREKIT_IMPORTS["NewtonianAttractionModel"] = NewtonianAttractionModel
    except ImportError:
        try:
            from org.orekit.forces.gravity import NewtonianAttraction
            _OREKIT_IMPORTS["NewtonianAttractionModel"] = NewtonianAttraction
        except ImportError:
            print("WARNING: Could not import NewtonianAttractionModel or NewtonianAttraction.")
            print("24-hour Orekit propagation will be missing central gravity and will diverge.")
            _OREKIT_IMPORTS["NewtonianAttractionModel"] = None

    _OREKIT_INITIALIZED = True
    return _OREKIT_IMPORTS


# Candidate conversion from Fully Normalized Cbar(n,0) to Unnormalized Jn
# Reference: Vallado, 4th Ed, Eq 8-6
# Note: Pending numerical verification against Orekit documentation conventions.
def convert_cbar_to_jn(cbar_n0: float, degree: int) -> float:
    import math

    return -math.sqrt((2 * degree) + 1) * cbar_n0


class OrekitPropagatorAdapter(PropagatorAdapter):
    @property
    def name(self) -> str:
        return "Orekit"

    def _build_initial_state_and_gravity(
        self,
        config: ValidationConfig,
        imports: dict,
        degree: int,
        order: int = 0,
    ):
        Vector3D = imports["Vector3D"]
        HolmesFeatherstoneAttractionModel = imports["HolmesFeatherstoneAttractionModel"]
        GravityFieldFactory = imports["GravityFieldFactory"]
        FramesFactory = imports["FramesFactory"]
        CartesianOrbit = imports["CartesianOrbit"]
        SpacecraftState = imports["SpacecraftState"]
        AbsoluteDate = imports["AbsoluteDate"]
        TimeScalesFactory = imports["TimeScalesFactory"]
        IERSConventions = imports["IERSConventions"]
        PVCoordinates = imports["PVCoordinates"]

        utc = TimeScalesFactory.getUTC()
        epoch = config.epoch_utc
        initial_date = AbsoluteDate(
            epoch.year,
            epoch.month,
            epoch.day,
            epoch.hour,
            epoch.minute,
            float(epoch.second),
            utc,
        )

        inertial_frame = FramesFactory.getGCRF()
        earth_fixed_frame = FramesFactory.getITRF(IERSConventions.IERS_2010, True)

        initial_position = Vector3D(
            config.initial_position_m.x,
            config.initial_position_m.y,
            config.initial_position_m.z,
        )
        initial_velocity = Vector3D(
            config.initial_velocity_mps.x,
            config.initial_velocity_mps.y,
            config.initial_velocity_mps.z,
        )
        initial_pv = PVCoordinates(initial_position, initial_velocity)
        initial_orbit = CartesianOrbit(
            initial_pv,
            inertial_frame,
            initial_date,
            config.mu,
        )
        initial_state = SpacecraftState(initial_orbit, config.spacecraft_mass_kg)

        provider = GravityFieldFactory.getNormalizedProvider(degree, order)
        gravity_force = HolmesFeatherstoneAttractionModel(earth_fixed_frame, provider)

        return (
            initial_date,
            inertial_frame,
            earth_fixed_frame,
            initial_state,
            gravity_force,
            provider,
        )

    def collect_model_diagnostics(
        self,
        config: ValidationConfig,
        degree: int = 4,
        order: int = 0,
    ) -> dict:
        imports = initialize_orekit()

        ClassicalRungeKuttaIntegrator = imports["ClassicalRungeKuttaIntegrator"]
        OrbitType = imports["OrbitType"]
        NumericalPropagator = imports["NumericalPropagator"]

        (
            initial_date,
            inertial_frame,
            earth_fixed_frame,
            initial_state,
            gravity_force,
            provider,
        ) = self._build_initial_state_and_gravity(
            config=config,
            imports=imports,
            degree=degree,
            order=order,
        )

        integrator = ClassicalRungeKuttaIntegrator(config.time_step_seconds)
        propagator = NumericalPropagator(integrator)
        propagator.setOrbitType(OrbitType.CARTESIAN)
        propagator.setInitialState(initial_state)
        propagator.addForceModel(gravity_force)

        force_models = propagator.getAllForceModels()
        force_model_names = [force_models.get(i).getClass().getName() for i in range(force_models.size())]

        return {
            "inertial_frame_name": inertial_frame.getName(),
            "earth_fixed_frame_name": earth_fixed_frame.getName(),
            "provider_class": provider.getClass().getName(),
            "provider_mu_m3s2": provider.getMu(),
            "provider_reference_radius_m": provider.getAe(),
            "provider_degree": degree,
            "provider_order": order,
            "orbit_mu_m3s2": initial_state.getOrbit().getMu(),
            "integrator_class": integrator.getClass().getName(),
            "propagator_class": propagator.getClass().getName(),
            "gravity_force_class": gravity_force.getClass().getName(),
            "force_models_attached": force_model_names,
            "epoch": str(initial_date),
        }

    def inspect_coefficients(self, config: ValidationConfig) -> dict[str, float]:
        imports = initialize_orekit()

        TimeScalesFactory = imports["TimeScalesFactory"]
        AbsoluteDate = imports["AbsoluteDate"]
        GravityFieldFactory = imports["GravityFieldFactory"]

        utc = TimeScalesFactory.getUTC()
        epoch = config.epoch_utc
        absolute_date = AbsoluteDate(
            epoch.year,
            epoch.month,
            epoch.day,
            epoch.hour,
            epoch.minute,
            float(epoch.second),
            utc,
        )

        provider = GravityFieldFactory.getNormalizedProvider(4, 0)
        harmonics = provider.onDate(absolute_date)

        c20 = harmonics.getNormalizedCnm(2, 0)
        c30 = harmonics.getNormalizedCnm(3, 0)
        c40 = harmonics.getNormalizedCnm(4, 0)

        j2 = convert_cbar_to_jn(c20, 2)
        j3 = convert_cbar_to_jn(c30, 3)
        j4 = convert_cbar_to_jn(c40, 4)

        return {
            "c20_normalized": c20,
            "c30_normalized": c30,
            "c40_normalized": c40,
            "j2_unnormalized": j2,
            "j3_unnormalized": j3,
            "j4_unnormalized": j4,
        }

    def compute_acceleration_for_degree(
        self,
        config: ValidationConfig,
        degree: int,
    ) -> tuple[Vector3, Vector3]:
        imports = initialize_orekit()

        if degree == 0:
            r_vec = config.initial_position_m
            r = r_vec.magnitude()
            factor = -config.mu / (r ** 3)
            acceleration = Vector3(
                factor * r_vec.x,
                factor * r_vec.y,
                factor * r_vec.z,
            )
            return acceleration, Vector3(r_vec.x, r_vec.y, r_vec.z)

        (
            initial_date,
            inertial_frame,
            _,
            initial_state,
            gravity_force,
            _,
        ) = self._build_initial_state_and_gravity(
            config=config,
            imports=imports,
            degree=degree,
            order=0,
        )

        parameters = gravity_force.getParameters(initial_date)
        acceleration_java = gravity_force.acceleration(initial_state, parameters)
        position_java = initial_state.getPVCoordinates(inertial_frame).getPosition()

        return (
            Vector3(
                acceleration_java.getX(),
                acceleration_java.getY(),
                acceleration_java.getZ(),
            ),
            Vector3(
                position_java.getX(),
                position_java.getY(),
                position_java.getZ(),
            ),
        )

    def _normalize_force_model_mode(self, force_model_mode: str) -> str:
        normalized = force_model_mode.strip().upper()
        if normalized not in _VALID_FORCE_MODEL_MODES:
            raise ValueError(
                "Invalid Orekit force model mode "
                f"'{force_model_mode}'. Valid options: hf_only, newtonian_only, both."
            )
        return normalized

    def propagate(
        self,
        config: ValidationConfig,
        force_model_mode: str = BOTH,
    ) -> PropagationResult:
        imports = initialize_orekit()
        selected_mode = self._normalize_force_model_mode(force_model_mode)

        ClassicalRungeKuttaIntegrator = imports["ClassicalRungeKuttaIntegrator"]
        OrbitType = imports["OrbitType"]
        NumericalPropagator = imports["NumericalPropagator"]

        (
            initial_date,
            inertial_frame,
            _,
            initial_state,
            gravity_force,
            _,
        ) = self._build_initial_state_and_gravity(
            config=config,
            imports=imports,
            degree=4,
            order=0,
        )

        integrator = ClassicalRungeKuttaIntegrator(config.time_step_seconds)
        propagator = NumericalPropagator(integrator)
        propagator.setOrbitType(OrbitType.CARTESIAN)
        propagator.setInitialState(initial_state)

        if selected_mode in {HF_ONLY, BOTH}:
            propagator.addForceModel(gravity_force)

        if selected_mode in {NEWTONIAN_ONLY, BOTH}:
            if imports.get("NewtonianAttractionModel") is not None:
                NewtonianAttractionModel = imports["NewtonianAttractionModel"]
                central_force = NewtonianAttractionModel(config.mu)
                propagator.addForceModel(central_force)
            else:
                raise RuntimeError(
                    "Cannot execute Orekit propagation with Newtonian central gravity: "
                    "NewtonianAttractionModel is missing."
                )

        steps = int(config.duration_seconds / config.time_step_seconds)
        samples: list[PropagationSample] = []

        for step_index in range(steps + 1):
            current_time = step_index * config.time_step_seconds
            current_date = initial_date.shiftedBy(current_time)
            state = propagator.propagate(current_date)
            pv = state.getPVCoordinates(inertial_frame)

            samples.append(
                PropagationSample(
                    time_seconds=current_time,
                    position_m=Vector3(
                        pv.getPosition().getX(),
                        pv.getPosition().getY(),
                        pv.getPosition().getZ(),
                    ),
                    velocity_mps=Vector3(
                        pv.getVelocity().getX(),
                        pv.getVelocity().getY(),
                        pv.getVelocity().getZ(),
                    ),
                )
            )

        coeff_info = self.inspect_coefficients(config)

        assumptions = [
            "Holmes-Featherstone spherical harmonics gravity model.",
            "Equivalent zonal harmonics up to degree 4.",
            "Fixed-step classical Runge-Kutta numerical propagation.",
            f"Orekit force model mode: {selected_mode}",
        ]

        return PropagationResult(
            propagator_name=self.name,
            samples=samples,
            assumptions=assumptions,
            frame="GCRF",
            integrator="ClassicalRungeKuttaIntegrator",
            integrator_type="Fixed-step RK4",
            fixed_step_seconds=config.time_step_seconds,
            gravity_model="EGM2008 (Orekit data provider)",
            gravity_provider="NormalizedProvider(4,0)",
            gravity_degree=4,
            gravity_order=0,
            coefficient_convention="Normalized Cbar(n,0) internally; converted unnormalized Jn reported",
            epoch_utc=config.epoch_utc,
            time_scale=config.time_scale,
            metadata={**coeff_info, "orekit_force_model_mode": selected_mode},
        )