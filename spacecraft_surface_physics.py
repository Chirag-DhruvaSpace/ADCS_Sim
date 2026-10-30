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


from attitude_frames import body_to_eci, cross3



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
        self._arm_cross_normal = np.cross(self.arm, self.normal)
        self._absorbed_fraction = 1-self.specular
        self._diffuse_recoil = 2*self.diffuse/3
        self.blockers = geometry.blockers
        self._blocker_lo = np.array([np.asarray(box.center_body_m)-box.half_extents_m for box in self.blockers])
        self._blocker_hi = np.array([np.asarray(box.center_body_m)+box.half_extents_m for box in self.blockers])
        from engine.physics.facet_visibility import make_visibility
        self._native_visibility = make_visibility(self.position, self._blocker_lo, self._blocker_hi) if self.blockers else None

    def visibility(self, direction, active=None):
        """Ray/box visibility per quadrature patch, including folded panels."""
        if not self.blockers:
            return np.ones(len(self.position), dtype=bool)
        native = getattr(self, '_native_visibility', None)
        if native is not None:
            return native(direction, active)
        # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
        # Zero projected-area patches contribute exactly zero force. Preserve
        # slab arithmetic for every contributing patch, without tracing others.
        selected = self.position if active is None else self.position[active]
        origins = selected + direction*1e-6
        shape = (len(selected), len(self.blockers))
        near = np.full(shape, -np.inf)
        far = np.full(shape, np.inf)
        outside = np.zeros(shape, dtype=bool)
        # Slabs in two dimensions avoid materializing several N x boxes x 3
        # temporaries for every integrator stage. The ray test is unchanged.
        for axis in range(3):
            origin = origins[:, axis, None]
            lo, hi = self._blocker_lo[None, :, axis], self._blocker_hi[None, :, axis]
            if abs(direction[axis]) < 1e-12:
                outside |= (origin < lo) | (origin > hi)
            else:
                a, b = (lo-origin)/direction[axis], (hi-origin)/direction[axis]
                np.maximum(near, np.minimum(a, b), out=near)
                np.minimum(far, np.maximum(a, b), out=far)
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
        scale = -pressure * illumination * self.area * cosine
        absorbed = scale * self._absorbed_fraction
        reflected = scale * (2*self.specular*cosine + self._diffuse_recoil)
        # Distribute the sums over cross products. Fixed facet arms/normals
        # are prepared once; each stage avoids two patch-by-3 force arrays.
        srp_force = absorbed.sum()*to_sun + reflected @ self.normal
        srp_torque = cross3(absorbed @ self.arm, to_sun) + reflected @ self._arm_cross_normal
        relative = rotation.T @ (np.asarray(velocity_eci_mps) - atmospheric_velocity_eci_mps)
        speed = np.linalg.norm(relative)
        wind = relative / speed if speed > 0 else np.zeros(3)
        projected = np.maximum(self.normal @ wind, 0)
        projected *= self.visibility(wind, projected > 0)
        drag_scale = -.5*density_kg_m3*self.cd*speed**2*self.area*projected
        return SurfaceResult(rotation @ (srp_force), srp_torque,
                             rotation @ (drag_scale.sum()*wind), cross3(drag_scale @ self.arm, wind),
                             pressure, pressure*illumination, illumination, distance, density_kg_m3)
