"""Magnetorquer plant: YAML coils, allocation, electrical limits and m x B.

Controllers request a body dipole; firmware requests signed currents by rod
index. Both paths use this plant. Positions are CAD/body coordinates in metres;
the ambient field is uniform across the spacecraft, so no r x F term applies.
Coil self-fields at magnetometers, inductance and hysteresis are not modeled.
Importing this module does not initialize Orekit or open firmware UDP sockets.
"""
from dataclasses import dataclass, field, replace

import numpy as np


@dataclass(frozen=True)
class MagnetorquerParameters:
    name: str
    axis_body: tuple
    position_body_m: tuple = (0., 0., 0.)
    enabled: bool = True
    max_dipole_Am2: float | None = None  # None inherits spacecraft defaults
    dipole_step_Am2: float | None = None
    max_current_A: float | None = None
    dipole_per_amp_Am2_per_A: float = 6.149961754311725
    resistance_ohm: float = 18.2
    cad_node: str = ''  # provenance only; physics reads the explicit YAML axes

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('Magnetorquer name must be nonempty')
        if not isinstance(self.enabled, bool):
            raise ValueError('Magnetorquer enabled must be boolean')
        for key in ('axis_body', 'position_body_m'):
            value = np.asarray(getattr(self, key), dtype=float)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f'Magnetorquer {key} must be a finite 3-vector')
        axis = np.asarray(self.axis_body, dtype=float)
        axis_length = float(np.linalg.norm(axis))
        if not np.isfinite(axis_length) or axis_length < 1e-12:
            raise ValueError('Magnetorquer axis cannot be zero')
        object.__setattr__(self, 'axis_body', tuple(axis / axis_length))
        for key in ('max_dipole_Am2', 'max_current_A', 'dipole_per_amp_Am2_per_A', 'resistance_ohm'):
            value = getattr(self, key)
            if value is None and key in ('max_dipole_Am2', 'max_current_A'):
                continue
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f'Magnetorquer {key} must be finite and positive')
        if self.dipole_step_Am2 is not None and (not np.isfinite(self.dipole_step_Am2) or self.dipole_step_Am2 < 0):
            raise ValueError('Magnetorquer dipole step must be finite and nonnegative')


def _legacy_units():
    return tuple(MagnetorquerParameters('MTR-' + name, tuple(axis))
                 for name, axis in zip('XYZ', np.eye(3)))


@dataclass(frozen=True)
class MagnetorquerArrayParameters:
    enabled: bool = True
    quantize_commands: bool = False  # retain continuous legacy allocation
    units: tuple = field(default_factory=_legacy_units)

    def __post_init__(self):
        if not isinstance(self.enabled, bool) or not isinstance(self.quantize_commands, bool):
            raise ValueError('Magnetorquer switches must be boolean')
        if any(not isinstance(u, MagnetorquerParameters) for u in self.units):
            raise ValueError('Invalid magnetorquer units')
        names = [u.name for u in self.units]
        if len(set(names)) != len(names):
            raise ValueError('Magnetorquer names must be unique')


def load_parameters(values, advanced=None):
    """Merge shared electrical defaults with selected CAD unit placements.

    An advanced units list replaces the basic list. Missing per-unit limits
    inherit spacecraft limits; coil constants inherit this section's defaults.
    Empty lists retain the historical three-axis plant.
    """
    from dataclasses import fields
    values = {**values, **(advanced or {})}
    allowed = {'enabled', 'quantize_commands', 'units', 'dipole_per_amp_Am2_per_A', 'resistance_ohm'}
    if set(values) - allowed:
        raise ValueError(f'Unknown magnetorquers settings: {sorted(set(values) - allowed)}')
    units = []
    unit_fields = {f.name for f in fields(MagnetorquerParameters)}
    records = values.get('units') or [dict(name=u.name, axis_body=u.axis_body) for u in _legacy_units()]
    for record in records:
        if set(record) - unit_fields:
            raise ValueError(f'Unknown magnetorquer unit settings: {sorted(set(record) - unit_fields)}')
        defaults = {key: values[key] for key in ('dipole_per_amp_Am2_per_A', 'resistance_ohm') if key in values}
        units.append(MagnetorquerParameters(**{**defaults, **record}))
    return MagnetorquerArrayParameters(values.get('enabled', True), values.get('quantize_commands', False), tuple(units))


@dataclass(frozen=True)
class MagnetorquerState:
    dipoles_Am2: np.ndarray  # signed scalar dipole of each configured rod
    currents_A: np.ndarray
    body_dipole_Am2: np.ndarray
    torque_body_Nm: np.ndarray
    power_W: float


def magnetic_torque_body(dipole_Am2, field_body_t):
    """Uniform-field torque in N m; the coil centroid adds no moment arm."""
    return np.cross(dipole_Am2, field_body_t)


class SimulatedMagnetorquers:
    def __init__(self, parameters, *, max_dipole_Am2=2., dipole_step_Am2=.1, max_current_A=(.3, .3, 2.)):
        units = tuple(replace(u,
            max_dipole_Am2=max_dipole_Am2 if u.max_dipole_Am2 is None else u.max_dipole_Am2,
            dipole_step_Am2=dipole_step_Am2 if u.dipole_step_Am2 is None else u.dipole_step_Am2,
            max_current_A=max_current_A[int(np.argmax(np.abs(u.axis_body)))] if u.max_current_A is None else u.max_current_A)
            for u in parameters.units)
        parameters = replace(parameters, units=units)
        self.cfg = parameters
        self.axes = np.asarray([u.axis_body for u in parameters.units], dtype=float).reshape(-1, 3).T
        self.constants = np.asarray([u.dipole_per_amp_Am2_per_A for u in parameters.units])
        self.steps = np.asarray([u.dipole_step_Am2 for u in parameters.units])
        self.resistances = np.asarray([u.resistance_ohm for u in parameters.units])
        self.limits = np.asarray([min(u.max_dipole_Am2, u.max_current_A * k)
                                  if parameters.enabled and u.enabled else 0.
                                  for u, k in zip(parameters.units, self.constants)])
        self.available = self.limits > 0
        self.inverse_axes = np.linalg.pinv(self.axes[:, self.available])
        axes = self.axes[:, self.available]
        self.orthogonal = np.allclose(axes.T @ axes, np.eye(axes.shape[1]), atol=1e-12)

    @staticmethod
    def _vector(value, size):
        value = np.asarray(value, dtype=float)
        if value.shape != (size,) or not np.all(np.isfinite(value)):
            raise ValueError(f'Magnetorquer command must contain {size} finite values')
        return value

    def _limit(self, commands, quantize):
        limits = self.limits.copy()
        commands = np.clip(commands, -limits, limits)
        if quantize:
            selected = self.steps > 0
            limits[selected] = np.floor(limits[selected] / self.steps[selected] + 1e-12) * self.steps[selected]
            commands[selected] = np.round(commands[selected] / self.steps[selected]) * self.steps[selected]
        return np.clip(commands, -limits, limits)

    def _state(self, commands, field_body_t):
        field_body_t = self._vector(field_body_t, 3)
        body_dipole = self.axes @ commands
        currents = commands / self.constants
        return MagnetorquerState(commands, currents, body_dipole,
                                 magnetic_torque_body(body_dipole, field_body_t), float(np.sum(currents**2 * self.resistances)))

    def apply_dipole(self, body_dipole_Am2, field_body_t=(0., 0., 0.)):
        """Bounded least-squares distribution; disabled coils have no authority.

        Saturation redistributes demand to available rods. Rank-deficient
        layouts retain their reachable dipole.
        """
        desired = self._vector(body_dipole_Am2, 3)
        commands = np.zeros(len(self.cfg.units))
        commands[self.available] = self.inverse_axes @ desired
        if np.any(np.abs(commands) > self.limits):
            axes = self.axes[:, self.available]
            # Orthogonal rods have an exact component-wise clipping solution.
            if not self.orthogonal:
                from scipy.optimize import lsq_linear
                bounds = self.limits[self.available]
                commands[self.available] = lsq_linear(axes, desired, bounds=(-bounds, bounds),
                                                       method='bvls', tol=1e-12).x
        return self._state(self._limit(commands, self.cfg.quantize_commands), field_body_t)

    def detumble(self, angular_rate_body_rad_s, field_body_t):
        """Bang-bang B-dot law in the installed rod axes, preserving XYZ signs."""
        rate = self._vector(angular_rate_body_rad_s, 3)
        field_body_t = self._vector(field_body_t, 3)
        b_dot = -np.cross(rate, field_body_t)
        commands = -self.limits * np.sign(self.axes.T @ b_dot)
        return self._state(self._limit(commands, self.cfg.quantize_commands), field_body_t)

    def apply_currents(self, currents_A, field_body_t=(0., 0., 0.)):
        """Firmware channels are units-list indices; retain hardware quantization."""
        currents = self._vector(currents_A, len(self.cfg.units))
        return self._state(self._limit(currents * self.constants, True), field_body_t)

    def with_field(self, state, field_body_t):
        """Evaluate held coil commands at the evolving true attitude/field."""
        return self._state(state.dipoles_Am2.copy(), field_body_t)

    def torque_to_dipole(self, torque_body_Nm, field_body_t):
        torque = self._vector(torque_body_Nm, 3)
        field_body_t = np.asarray(field_body_t, dtype=float).reshape(3)
        field_sq = float(field_body_t @ field_body_t)
        if not np.isfinite(field_sq) or field_sq < 1e-12:
            return np.zeros(3), np.zeros(3)
        state = self.apply_dipole(np.cross(field_body_t, torque) / field_sq, field_body_t)
        return state.body_dipole_Am2, state.torque_body_Nm

    def telemetry(self, state):
        return [dict(name=u.name, kind='MTR', position=list(u.position_body_m), axis_body=list(u.axis_body),
                     enabled=self.cfg.enabled and u.enabled, cad_node=u.cad_node,
                     dipole_Am2=float(moment), current_A=float(current), power_W=float(current**2 * resistance),
                     active=bool(self.cfg.enabled and u.enabled and abs(moment) > 1e-12),
                     level=float(abs(moment) / limit) if limit > 0 else 0.)
                for u, moment, current, resistance, limit in zip(self.cfg.units, state.dipoles_Am2,
                                                               state.currents_A, self.resistances, self.limits)]


def configured_model():
    # Cache by immutable configuration identity, while allowing tests/config reloads.
    import satellite_parameters as config
    parameters = config.SPACECRAFT.magnetorquers
    defaults = (config.SPACECRAFT.mtr_max_dipole_Am2, config.SPACECRAFT.mtr_dipole_step_Am2,
                tuple(config.SPACECRAFT.mtr_max_current_A))
    if (getattr(configured_model, '_parameters', None) is not parameters
            or getattr(configured_model, '_defaults', None) != defaults):
        model = SimulatedMagnetorquers(parameters, max_dipole_Am2=defaults[0],
            dipole_step_Am2=defaults[1], max_current_A=defaults[2])
        configured_model._parameters = parameters
        configured_model._defaults = defaults
        configured_model._model = model
    return configured_model._model


def torque_to_dipole(tau, B_body):
    return configured_model().torque_to_dipole(tau, B_body)


def compute_MTR_power(m):
    """Compatibility tuple: total watts and absolute body-axis current sums."""
    model = configured_model()
    state = model.apply_dipole(m)
    currents = np.abs(model.axes) @ np.abs(state.currents_A)
    return (state.power_W, *currents)
