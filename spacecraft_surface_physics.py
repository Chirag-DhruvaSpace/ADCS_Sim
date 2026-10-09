# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""One facet model for orbit forces and attitude moments, in SI/CAD axes.

Normals point outwards; to_sun points from spacecraft to Sun. Radiation
pressure includes absorption, Lambertian diffuse and specular reflection.
Aerodynamics uses projected area with diffuse free-molecular drag (Cd).
Torque uses each facet centroid relative to the reported centre of mass.
"""
from dataclasses import dataclass
import numpy as np

AU_M = 149597870700.0
from satellite_parameters import DISTURBANCES
PRESSURE_AT_AU_PA = DISTURBANCES.solar_pressure_at_1au_pa


def body_to_eci(q):
    q = np.asarray(q, dtype=float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    # Matches the simulator's passive scalar-first quaternion convention.
    return np.array([[1-2*(y*y+z*z), 2*(x*y+w*z), 2*(x*z-w*y)],
                     [2*(x*y-w*z), 1-2*(x*x+z*z), 2*(y*z+w*x)],
                     [2*(x*z+w*y), 2*(y*z-w*x), 1-2*(x*x+y*y)]])


@dataclass
class SurfaceResult:
    srp_force_eci_n: np.ndarray
    srp_torque_body_nm: np.ndarray
    drag_force_eci_n: np.ndarray
    drag_torque_body_nm: np.ndarray
    solar_pressure_pa: float
    effective_pressure_pa: float
    eclipse_fraction: float
    sun_distance_m: float
    density_kg_m3: float


class SurfaceForceModel:
    def __init__(self, spacecraft, geometry):
        self.mass = spacecraft.mass_kg
        self.cd = spacecraft.drag_coefficient
        patches = []
        for f in geometry.surfaces:
            center = np.asarray(f.center_of_pressure_body_m, float)
            samples = [center]
            if f.half_size_m:
                u, v = np.asarray(f.tangent_u_body), np.asarray(f.tangent_v_body)
                samples = [center + a*f.half_size_m[0]*u + b*f.half_size_m[1]*v
                           for a in (-.75,-.25,.25,.75) for b in (-.75,-.25,.25,.75)]
            patches.extend((f.area_m2/len(samples), f.normal_body, p,
                            f.diffuse_reflectivity, f.specular_reflectivity) for p in samples)
        self.area = np.array([p[0] for p in patches])
        self.normal = np.array([p[1] for p in patches])
        self.position = np.array([p[2] for p in patches])
        self.arm = self.position - geometry.center_of_mass_body_m
        self.diffuse = np.array([p[3] for p in patches])
        self.specular = np.array([p[4] for p in patches])
        self.blockers = geometry.blockers
        self._blocker_lo = np.array([np.asarray(box.center_body_m)-box.half_extents_m for box in self.blockers])
        self._blocker_hi = np.array([np.asarray(box.center_body_m)+box.half_extents_m for box in self.blockers])

    def visibility(self, direction, active=None):
        """Ray/box visibility per quadrature patch, including folded panels."""
        if not self.blockers:
            return np.ones(len(self.position), dtype=bool)
        # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
        # Zero projected-area patches contribute exactly zero force. Preserve
        # slab arithmetic for every contributing patch, without tracing others.
        selected = self.position if active is None else self.position[active]
        origins = (selected + direction*1e-6)[:, None, :]
        parallel = np.abs(direction) < 1e-12
        a = self._blocker_lo[None, :, :]-origins
        b = self._blocker_hi[None, :, :]-origins
        np.divide(a, direction, out=a, where=~parallel)
        np.divide(b, direction, out=b, where=~parallel)
        near = np.max(np.where(parallel, -np.inf, np.minimum(a,b)), axis=2)
        far = np.min(np.where(parallel, np.inf, np.maximum(a,b)), axis=2)
        outside = np.any(parallel & ((origins < self._blocker_lo) | (origins > self._blocker_hi)), axis=2)
        hit = ~outside & (far >= np.maximum(near, 0)) & (far > 1e-7)
        visible = ~np.any(hit, axis=1)
        if active is None:
            return visible
        result = np.zeros(len(self.position), dtype=bool)
        result[active] = visible
        return result

    def evaluate(self, q, position_eci_m, velocity_eci_mps, sun_position_eci_m,
                 illumination, density_kg_m3, atmospheric_velocity_eci_mps):
        rotation = body_to_eci(q)
        sun = np.asarray(sun_position_eci_m) - position_eci_m
        distance = float(np.linalg.norm(sun))
        if distance <= 0 or density_kg_m3 < 0:
            raise ValueError('Positive Sun distance and nonnegative density required')
        illumination = float(np.clip(illumination, 0, 1))
        to_sun = rotation.T @ (sun / distance)
        cosine = np.maximum(self.normal @ to_sun, 0)
        cosine *= self.visibility(to_sun, cosine > 0)
        pressure = PRESSURE_AT_AU_PA * (AU_M / distance)**2
        # Incoming momentum points away from Sun; reflected recoil is inward.
        srp = -pressure * illumination * (self.area * cosine)[:, None] * (
            (1-self.specular)[:, None] * to_sun +
            (2*self.specular*cosine + 2*self.diffuse/3)[:, None] * self.normal)
        relative = rotation.T @ (np.asarray(velocity_eci_mps) - atmospheric_velocity_eci_mps)
        speed = np.linalg.norm(relative)
        wind = relative / speed if speed > 0 else np.zeros(3)
        projected = np.maximum(self.normal @ wind, 0)
        projected *= self.visibility(wind, projected > 0)
        drag = (-.5*density_kg_m3*self.cd*speed**2*self.area*projected)[:, None] * wind
        return SurfaceResult(rotation @ srp.sum(axis=0), np.cross(self.arm, srp).sum(axis=0),
                             rotation @ drag.sum(axis=0), np.cross(self.arm, drag).sum(axis=0),
                             pressure, pressure*illumination, illumination, distance, density_kg_m3)
