"""Reject rates the live acquisition cadence cannot actually deliver."""
import math


def validate_sensor_schedule(dt, imu, gps, *, firmware=False):
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError('Control step must be finite and positive')
    def check(name, rate, cadence):
        if not math.isfinite(rate) or rate <= 0 or rate*cadence > 1+1e-9:
            raise ValueError(f'{name}: {rate} Hz exceeds acquisition cadence '
                             f'{1/cadence:g} Hz; reduce the rate or control step')
    if gps.enabled:
        check('GPS', gps.update_rate_hz, dt)
    if not imu.enabled:
        return
    for kind, flag in [('gyro', imu.enable_gyro), ('mag', imu.enable_magnetometer)]:
        if not flag:
            continue
        for index, unit in enumerate(imu.sensor_units(kind)):
            if unit.enabled:
                cfg = imu.unit_config(kind, unit, index)
                check(unit.name, getattr(cfg, kind+'_update_rate_hz'), .01 if firmware else dt)
    if imu.enable_sun_sensor and imu.sun_array.enabled and any(c.enabled for c in imu.sun_array.cells):
        check('Sun sensor', imu.sun_array.update_rate_hz, dt)
    if imu.enable_star_tracker and imu.star_tracker.enabled:
        check('Star tracker', imu.star_tracker.update_rate_hz, dt)
