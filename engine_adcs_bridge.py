from __future__ import annotations

import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import satellite_parameters as config

import engine.orekit_runtime  # noqa: F401  side-effect bootstrap for Orekit JVM/data
from engine.astrodynamics.constants import EARTH_MASS, EARTH_MU, EARTH_RADIUS
from engine.forces.gravity import GravityForce, GravityMode
from engine.forces.zonal_harmonics import ZonalHarmonicsForce
from engine.math.vector3 import Vector3
from engine.physics.body import Body
from engine.physics.integrator import DOP853Integrator, IntegratorConfig
from engine.physics.magnetic_field import OrekitIGRF
from engine.physics.physical_properties import (
    AerodynamicProperties,
    OpticalProperties,
    PhysicalProperties,
)
from engine.physics.sun_ephemeris import OrekitSunEphemeris
from engine.physics.universe import Universe
from engine.simulation.clock import SimulationClock
from spacecraft_surface_physics import SurfaceForceModel
from engine.forces.coupled_surface_force import CoupledSurfaceForce


ALTITUDE_M = config.ALTITUDE_M
INCLINATION_DEG = config.INCLINATION_DEG
SPACECRAFT_MASS = config.MASS_KG
DRAG_COEFFICIENT = config.DRAG_COEFFICIENT
DRAG_AREA_M2 = config.DRAG_AREA_M2
SRP_CR = config.SRP_CR
SRP_AREA_M2 = config.SRP_AREA_M2
EGM_DEGREE = config.MODEL_DATA.gravity_degree
EGM_ORDER = config.MODEL_DATA.gravity_order


class EngineOrbitProvider:
    """Bridge between the legacy ADCS simulation and the validated engine propagator."""

    def __init__(
        self,
        epoch_utc: datetime | None = None,
        altitude_m: float = ALTITUDE_M,
        inclination_deg: float = INCLINATION_DEG,
    ) -> None:
        self.epoch_utc = epoch_utc or config.EPOCH_UTC
        self.altitude_m = float(altitude_m)
        self.inclination_deg = float(inclination_deg)
        self.clock = SimulationClock()
        self.clock.set_epoch(self._to_absolute_date(self.epoch_utc))
        self._epoch_date = self._to_absolute_date(self.epoch_utc)
        self._dense = None
        self._dense_generator = None
        self._dense_start = self._dense_end = 0.0
        self._attitude_time = 0.0
        self._attitude_q = np.asarray(config.ATTITUDE.initial_quaternion_scalar_first, dtype=float)
        self._attitude_rates = config.initial_body_rates_rad_s()
        self._surface_model = SurfaceForceModel(config.SPACECRAFT, config.GEOMETRY)
        self.universe = self._build_universe()
        self.earth = self.universe.bodies[0]
        self.spacecraft = self.universe.bodies[1]
        from org.orekit.frames import FramesFactory
        from org.orekit.utils import IERSConventions
        self.inertial_frame = FramesFactory.getEME2000()
        self.earth_fixed_frame = FramesFactory.getITRF(IERSConventions.IERS_2010, False)
        self._sun_ephemeris = OrekitSunEphemeris(self.inertial_frame)
        self.magnetic_field = OrekitIGRF(
            self.universe._get_central_body_shape(),
            self.inertial_frame,
            self.earth_fixed_frame,
        )
        from org.orekit.bodies import CelestialBodyFactory
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        from org.orekit.orbits import CartesianOrbit
        from org.orekit.propagation import SpacecraftState
        from org.orekit.utils import PVCoordinates
        self._surface_java = (Vector3D, CartesianOrbit, SpacecraftState, PVCoordinates)
        self._surface_sun = CelestialBodyFactory.getSun()
        from org.orekit.forces.radiation import (
            IsotropicRadiationSingleCoefficient,
            SolarRadiationPressure,
        )
        optical = self.spacecraft.physical_properties.optical
        self._srp_model = SolarRadiationPressure(
            CelestialBodyFactory.getSun(),
            self.universe._get_central_body_shape(),
            IsotropicRadiationSingleCoefficient(
                float(optical.reference_area_m2),
                float(optical.reflectivity_coefficient),
            ),
        )
        from org.orekit.models.earth.atmosphere import NRLMSISE00
        from engine.physics.atmosphere import get_cssi_space_weather_data
        self._atmosphere = NRLMSISE00(get_cssi_space_weather_data(), CelestialBodyFactory.getSun(),
                                    self.universe._get_central_body_shape())
        self._initial_position, self._initial_velocity = self._make_initial_pv()
        self.spacecraft.position = Vector3(*self._initial_position)
        self.spacecraft.velocity = Vector3(*self._initial_velocity)
        self.clock.reset()
        self.clock.set_epoch(self._to_absolute_date(self.epoch_utc))

    def _to_absolute_date(self, utc_dt: datetime): #convert python date time to orekit date time
        from engine.orekit_runtime import ensure_initialized

        ensure_initialized()
        from org.orekit.time import AbsoluteDate, TimeScalesFactory

        return AbsoluteDate(
            utc_dt.year,
            utc_dt.month,
            utc_dt.day,
            utc_dt.hour,
            utc_dt.minute,
            float(utc_dt.second) + utc_dt.microsecond / 1e6,
            TimeScalesFactory.getUTC(),
        )

    def _make_initial_pv(self):  #initial orbit state
        orbit = config.ORBIT
        a = EARTH_RADIUS + self.altitude_m
        e = orbit.eccentricity
        inclination = math.radians(self.inclination_deg)
        raan = math.radians(orbit.raan_deg)
        argument_of_perigee = math.radians(orbit.argument_of_perigee_deg)
        true_anomaly = math.radians(orbit.true_anomaly_deg)
        p = a * (1.0 - e * e)
        radius = p / (1.0 + e * math.cos(true_anomaly))
        position_perifocal = np.array([
            radius * math.cos(true_anomaly),
            radius * math.sin(true_anomaly),
            0.0,
        ])
        velocity_perifocal = math.sqrt(EARTH_MU / p) * np.array([
            -math.sin(true_anomaly),
            e + math.cos(true_anomaly),
            0.0,
        ])
        rotation = np.array([
            [
                math.cos(raan) * math.cos(argument_of_perigee)
                - math.sin(raan) * math.sin(argument_of_perigee) * math.cos(inclination),
                -math.cos(raan) * math.sin(argument_of_perigee)
                - math.sin(raan) * math.cos(argument_of_perigee) * math.cos(inclination),
                math.sin(raan) * math.sin(inclination),
            ],
            [
                math.sin(raan) * math.cos(argument_of_perigee)
                + math.cos(raan) * math.sin(argument_of_perigee) * math.cos(inclination),
                -math.sin(raan) * math.sin(argument_of_perigee)
                + math.cos(raan) * math.cos(argument_of_perigee) * math.cos(inclination),
                -math.cos(raan) * math.sin(inclination),
            ],
            [
                math.sin(argument_of_perigee) * math.sin(inclination),
                math.cos(argument_of_perigee) * math.sin(inclination),
                math.cos(inclination),
            ],
        ])
        return rotation @ position_perifocal, rotation @ velocity_perifocal

    def initial_state(self): #copy of p and v in an array for adcs sim
        return self._initial_position.copy(), self._initial_velocity.copy()

    def initial_state_vector(self):
        pos, vel = self.initial_state()
        return np.concatenate((pos, vel))

    def _build_universe(self):
        earth = Body(
            name="Earth",
            mass=EARTH_MASS,
            radius=EARTH_RADIUS,
            position=Vector3(0.0, 0.0, 0.0),
            velocity=Vector3(0.0, 0.0, 0.0),
            gravitational_parameter=EARTH_MU,
            central_body=True,
            is_spacecraft=False,
        )
        sc = Body(
            name="Spacecraft",
            mass=SPACECRAFT_MASS,
            radius=config.BODY_RADIUS_M,
            position=Vector3(*self._make_initial_pv()[0]),
            velocity=Vector3(*self._make_initial_pv()[1]),
            physical_properties=PhysicalProperties(
                aerodynamic=AerodynamicProperties(DRAG_COEFFICIENT, DRAG_AREA_M2),
                optical=OpticalProperties(SRP_CR, SRP_AREA_M2),
            ),
            is_spacecraft=True,
        )

        universe = Universe(
            central_body_name="Earth",
            inertial_frame="EME2000",
        )
        universe.add_body(earth)
        universe.add_body(sc)
        universe.set_clock(self.clock)

        universe.add_force(GravityForce(GravityMode.CENTRAL_BODY, "Earth"))
        universe.add_force(ZonalHarmonicsForce("Earth", EGM_DEGREE, EGM_ORDER))
        universe.add_force(CoupledSurfaceForce(self))
        return universe

    def state_at(self, elapsed_seconds: float):
        target_time = float(elapsed_seconds)
        dt = target_time - self.clock.time
        if dt < 0 and self._dense is not None:
            self._dense = self._dense_generator = None
            self._dense_start = self._dense_end = target_time
            self.universe._propagators.clear()
        if config.SIMULATION.orbit_output_window_s > config.CONTROL.control_loop_period_s and dt >= 0:
            return self._dense_state_at(target_time)
        if abs(dt) > 1e-12:
            settings = config.SIMULATION
            self.universe.step(dt, integrator=DOP853Integrator(IntegratorConfig(
                min_step=settings.orbit_integrator_min_step_s,
                max_step=settings.orbit_integrator_max_step_s,
                abs_tolerance=settings.orbit_integrator_abs_tolerance,
                rel_tolerance=settings.orbit_integrator_rel_tolerance)))
        pos = np.array([self.spacecraft.position.x, self.spacecraft.position.y, self.spacecraft.position.z], dtype=float)
        vel = np.array([self.spacecraft.velocity.x, self.spacecraft.velocity.y, self.spacecraft.velocity.z], dtype=float)
        return pos, vel

    def _dense_state_at(self, target):
        if target == 0 and self._dense is None:
            return self._initial_position.copy(), self._initial_velocity.copy()
        settings = config.SIMULATION
        while self._dense is None or target > self._dense_end + 1e-12:
            start = self._dense_end
            end = start + settings.orbit_output_window_s
            self.clock.time = start
            self.universe.integrator_config = IntegratorConfig(
                min_step=settings.orbit_integrator_min_step_s,
                max_step=settings.orbit_integrator_max_step_s,
                abs_tolerance=settings.orbit_integrator_abs_tolerance,
                rel_tolerance=settings.orbit_integrator_rel_tolerance)
            propagator = self.universe._ensure_propagator(self.spacecraft)
            if self._dense_generator is None:
                self._dense_generator = propagator.getEphemerisGenerator()
            self.universe.step(end-start)
            self._dense = self._dense_generator.getGeneratedEphemeris()
            self._dense_start, self._dense_end = start, end
        state = self._dense.propagate(self._epoch_date.shiftedBy(float(target)))
        pv = state.getPVCoordinates(self.inertial_frame)
        p, v = pv.getPosition(), pv.getVelocity()
        self.spacecraft.position = Vector3(p.getX(), p.getY(), p.getZ())
        self.spacecraft.velocity = Vector3(v.getX(), v.getY(), v.getZ())
        self.clock.time = target
        return np.array([p.getX(),p.getY(),p.getZ()]), np.array([v.getX(),v.getY(),v.getZ()])

    def magnetic_field_eci(self, elapsed_seconds: float, position_eci_m=None):
        """Return the Orekit IGRF field in EME2000, in tesla."""
        if position_eci_m is None:
            position_eci_m = np.array([
                self.spacecraft.position.x,
                self.spacecraft.position.y,
                self.spacecraft.position.z,
            ])
        utc_dt = self.epoch_utc + timedelta(seconds=float(elapsed_seconds))
        vector = self.magnetic_field.field_eci(
            position_eci_m,
            utc_dt,
            self.clock.absolute_date(),
        )
        return np.array([vector.x, vector.y, vector.z], dtype=float)

    def srp_acceleration_eci(self, elapsed_seconds: float, position_eci_m, velocity_eci_mps):
        """Return the same eclipse-aware facet acceleration as propagation."""
        return self.surface_result(elapsed_seconds, position_eci_m, velocity_eci_mps,
                                   self.predicted_attitude(elapsed_seconds)).srp_force_eci_n / self.spacecraft.mass

    def set_attitude(self, elapsed_seconds, quaternion, rates_rad_s):
        self._attitude_time = float(elapsed_seconds)
        self._attitude_q = np.asarray(quaternion, dtype=float).copy()
        self._attitude_q /= np.linalg.norm(self._attitude_q)
        self._attitude_rates = np.asarray(rates_rad_s, dtype=float).copy()
        # Discard dense output computed beyond this tick with the previous
        # held attitude. Otherwise Orekit could reuse stale panel incidence.
        for propagator in self.universe._propagators.values():
            propagator.resetInitialState(self.universe._build_spacecraft_state(self.spacecraft))

    def predicted_attitude(self, elapsed_seconds):
        w = self._attitude_rates
        magnitude = np.linalg.norm(w)
        if magnitude < 1e-15:
            return self._attitude_q
        theta = magnitude * (elapsed_seconds - self._attitude_time)
        a, b, c = w / magnitude * np.sin(theta/2)
        d = np.cos(theta/2)
        # exp(Omega dt/2) uses exactly the attitude ODE multiplication.
        return np.array([[d,-a,-b,-c],[a,d,c,-b],[b,-c,d,a],[c,b,-a,d]]) @ self._attitude_q

    def surface_result(self, elapsed_seconds, position_eci_m, velocity_eci_mps, quaternion):
        Vector3D, CartesianOrbit, SpacecraftState, PVCoordinates = self._surface_java
        date = self._epoch_date.shiftedBy(float(elapsed_seconds))
        position = Vector3D(*map(float, position_eci_m))
        velocity = Vector3D(*map(float, velocity_eci_mps))
        state = SpacecraftState(CartesianOrbit(PVCoordinates(position, velocity), self.inertial_frame,
                                              date, float(self.earth.gravitational_parameter)), float(self.spacecraft.mass))
        sun = self._surface_sun.getPosition(date, self.inertial_frame)
        illumination = float(self._srp_model.getLightingRatio(state))
        density = float(self._atmosphere.getDensity(date, position, self.inertial_frame))
        air = self._atmosphere.getVelocity(date, position, self.inertial_frame)
        result = self._surface_model.evaluate(quaternion, np.asarray(position_eci_m), np.asarray(velocity_eci_mps),
            np.array([sun.getX(), sun.getY(), sun.getZ()]), illumination, density,
            np.array([air.getX(), air.getY(), air.getZ()]))
        import calculate_disturbances as disturbances
        if not disturbances.DISTURBANCES_ENABLED or not disturbances.ENABLE_ATMOSPHERIC_DRAG:
            result.drag_force_eci_n[:] = 0
            result.drag_torque_body_nm[:] = 0
        # The compatibility SRP switches govern both sides of the coupling.
        import satellite_params as sp
        if not sp.ENABLE_SRP or not disturbances.DISTURBANCES_ENABLED:
            result.srp_force_eci_n[:] = 0
            result.srp_torque_body_nm[:] = 0
        if not sp.ENABLE_SRP_TORQUE:
            result.srp_torque_body_nm[:] = 0
        return result

    def srp_result(self, elapsed_seconds: float, position_eci_m, velocity_eci_mps, quaternion=None, surface_result=None):
        """Return shared facet force/moment with Orekit ephemeris and eclipse."""
        result = surface_result if surface_result is not None else self.surface_result(elapsed_seconds, position_eci_m, velocity_eci_mps,
                                     self.predicted_attitude(elapsed_seconds) if quaternion is None else quaternion)
        force = result.srp_force_eci_n
        return SimpleNamespace(
            force_eci_n=force,
            acceleration_eci_m_s2=force / self.spacecraft.mass,
            torque_body_nm=result.srp_torque_body_nm,
            solar_pressure_pa=result.solar_pressure_pa,
            effective_pressure_pa=result.effective_pressure_pa,
            eclipse_fraction=result.eclipse_fraction,
            sun_distance_m=result.sun_distance_m,
            drag_force_eci_n=result.drag_force_eci_n,
            drag_torque_body_nm=result.drag_torque_body_nm,
            density_kg_m3=result.density_kg_m3,
        )

    def geodetic_at(self, elapsed_seconds: float, position_eci_m): #eci to lat, long, alt
        """Return Orekit geodetic latitude, longitude, altitude (degrees/metres)."""
        from org.hipparchus.geometry.euclidean.threed import Vector3D

        point = self.universe._get_central_body_shape().transform(
            Vector3D(*np.asarray(position_eci_m, dtype=float).reshape(3)),
            self.inertial_frame,
            self.clock.absolute_date(),
        )
        return (
            math.degrees(point.getLatitude()),
            math.degrees(point.getLongitude()),
            float(point.getAltitude()),
        )

    def sun_position_eci(self):
        """Return the Orekit DE ephemeris Sun position in EME2000."""
        sun = self._sun_ephemeris.position(self.clock)
        return np.array([sun.x, sun.y, sun.z], dtype=float)

    def vector_eci_to_ecef(self, vector_eci, elapsed_seconds: float):
        """Transform a vector from EME2000 to ITRF using Orekit."""
        from org.hipparchus.geometry.euclidean.threed import Vector3D

        vector = self.earth_fixed_frame.getTransformTo(
            self.inertial_frame,
            self.clock.absolute_date(),
        ).getInverse().transformVector(
            Vector3D(*np.asarray(vector_eci, dtype=float).reshape(3))
        )
        return np.array([vector.getX(), vector.getY(), vector.getZ()], dtype=float)

    def propagate_to(self, elapsed_seconds: float):
        return self.state_at(elapsed_seconds)


_global_orbit_provider = None


def get_orbit_provider(epoch_utc: datetime | None = None) -> EngineOrbitProvider: #one orbit sim for whole sim
    global _global_orbit_provider
    if _global_orbit_provider is None:
        _global_orbit_provider = EngineOrbitProvider(epoch_utc=epoch_utc)
    return _global_orbit_provider
