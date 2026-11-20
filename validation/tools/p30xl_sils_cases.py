"""YAML value changes for the requested P-30XL firmware matrix."""


def cases():
    matrix = {}
    det = {'spacecraft.cad_panels_deployed': False,
           'control.firmware_replay_start_mode': 'boot',
           'simulation.default_duration_s': 4202.0}
    rods = ['MTR-X', 'MTR-Y', 'MTR-Z']
    for rate in (3.0, 10.0):
        for angle in (90.0, 5.0):
            for strength, failed in [(1., []), (.5, [])] + [
                    (strength, [rod]) for strength in (1., .5) for rod in rods]:
                matrix[f'DET-{len(matrix) + 1:03}'] = {
                    **det, 'attitude.firmware_replay_initial_rate_deg_s': rate,
                    'attitude.firmware_replay_initial_rate_field_angle_deg': angle,
                    'magnetorquers.physical_strength_scale': strength,
                    'magnetorquers.disabled_units': failed,
                }
    for axis in range(3):
        for sign in (1, -1):
            matrix[f'DET-{len(matrix) + 1:03}'] = {
                **det, 'attitude.initial_body_rates_deg_s': [3. * sign if i == axis else 0. for i in range(3)],
            }
    for rod in rods:
        matrix[f'DET-{len(matrix) + 1:03}'] = {
            **matrix['DET-001'], 'magnetorquers.disabled_units': [other for other in rods if other != rod],
        }
    matched = {**matrix['DET-001'], 'simulation.default_duration_s': 600.}
    for number, signs in enumerate(([-1, -1, -1], [-1, 1, 1], [1, -1, 1], [1, 1, -1]), 42):
        matrix[f'DET-{number:03}'] = {**matched, 'control.firmware_replay_bdot_gain_signs': signs}
    matrix['DET-046'] = {**matched, 'control.firmware_replay_bdot_method': 'finite_difference'}
    matrix['DET-047'] = {**matched, 'control.firmware_replay_bdot_method': 'rate_cross_field'}

    sun = {'spacecraft.cad_panels_deployed': True, 'control.firmware_replay_start_mode': 'sun_pointing'}
    for start in (1, 7):
        mtr = start == 7
        setup = {**sun, 'reaction_wheels.firmware_replay_unavailable': mtr}
        for offset, angle in enumerate((10., 90., 170.)):
            matrix[f'SUN-{start + offset:03}'] = {
                **setup, 'attitude.firmware_replay_initial_sun_error_deg': angle,
                'simulation.default_duration_s': 7202. if mtr else 602.,
            }
        stable = {**setup, 'attitude.firmware_replay_initial_sun_error_deg': 0.,
                  'simulation.default_duration_s': 600.}
        loss_window = [[180., 601.]]
        matrix[f'SUN-{start + 3:03}'] = {**stable, 'star_tracker.outages_s': loss_window}
        matrix[f'SUN-{start + 4:03}'] = {**stable, 'gps.outages_s': loss_window}
        matrix[f'SUN-{start + 5:03}'] = {
            **stable, 'gps.outages_s': loss_window, 'gps.firmware_replay_position_outages_s': loss_window,
            'star_tracker.outages_s': loss_window,
        }
    for start in (13, 16):
        search = {
            **sun, 'reaction_wheels.firmware_replay_unavailable': start == 16,
            'control.firmware_replay_sun_two_dof_enabled': False,
            'gps.enabled': False, 'gps.firmware_replay_position_outages_s': [[0., 1000.]],
            'sun_sensor.firmware_replay_continuous_sunlight': True,
        }
        matrix[f'SUN-{start:03}'] = {
            **search, 'simulation.default_duration_s': 360.,
            'sun_sensor.firmware_replay_observation_outages_s': [[0., 165.]],
        }
        matrix[f'SUN-{start + 1:03}'] = {
            **search, 'simulation.default_duration_s': 905.,
            'sun_sensor.firmware_replay_observation_outages_s': [[0., 906.]],
        }
        matrix[f'SUN-{start + 2:03}'] = {
            **search, 'simulation.default_duration_s': 155., 'control.firmware_replay_sun_reentry_s': 75.,
            'sun_sensor.firmware_replay_observation_outages_s': [[0., 156.]],
        }
    return matrix
