# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import unittest
from dataclasses import replace
from unittest.mock import patch
import numpy as np
import app
import control_states as cs
import satellite_parameters as config
from quat2eul import get_quaternion_error
from telemetry_transport import LatestTelemetryPublisher
from threading import Event
import time
from tempfile import TemporaryDirectory
from pathlib import Path
import yaml


class PointingInputs(unittest.TestCase):
    def setUp(self):
        self.strategy = patch.dict(config.POINTING, strategy='custom')
        self.strategy.start()
        self.addCleanup(self.strategy.stop)

    def test_error_reconstructs_target_and_stays_fixed(self):
        desired = np.array([.5, .5, .5, .5])
        reference = np.array([.7071067811865476, 0, .7071067811865476, 0])
        error = get_quaternion_error(desired, reference)
        actual = cs.set_pointing_input(error, input_kind='quaternion_error',
                                       reference_quaternion=reference)
        self.assertAlmostEqual(abs(np.dot(actual, desired)), 1)
        np.testing.assert_allclose(actual, cs.get_pointing_target())

    def test_api_rejects_invalid_inputs_without_changing_target(self):
        client = app.app.test_client()
        self.assertEqual(client.post('/api/pointing', json={'quaternion':[2,0,0,0]}).status_code, 200)
        before = cs.get_pointing_target()
        for payload in ({}, {'quaternion':[0,0,0,0]}, {'quaternion':[1,2,3]},
                        {'input':'quaternion_error','quaternion':[1,0,0,0]}):
            self.assertEqual(client.post('/api/pointing', json=payload).status_code, 400)
            np.testing.assert_array_equal(cs.get_pointing_target(), before)

    def test_sensor_profiles_preserve_cad_mounts_and_reset_nominal(self):
        for cfg in (config.GPS_SIM, config.IMU_SIM, config.IMU_SIM.sun_array):
            for name in ('custom','off','perfect','nominal','degraded','stress'):
                selected = config._apply_sensor_profile(cfg, name)
                self.assertEqual(selected.seed, cfg.seed)
                if hasattr(cfg, 'cells'):
                    self.assertEqual([c.position_body_m for c in selected.cells],
                                     [c.position_body_m for c in cfg.cells])
        stress = config._apply_sensor_profile(config.GPS_SIM, 'stress')
        nominal = config._apply_sensor_profile(stress, 'nominal')
        self.assertEqual(nominal.p_dropout, config.GpsSimParameters.nominal().p_dropout)

    def test_independent_profiles_load_from_yaml(self):
        data = yaml.safe_load(Path(config.__file__).with_suffix('.yaml').read_text(encoding='utf-8'))
        data['use_advanced_satellite_model'] = False
        data['sensor_profiles'].update(imu='nominal', gyroscope='stress', magnetometer='perfect', sun_array='off')
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'satellite_parameters.yaml'
            source.write_text(yaml.safe_dump(data), encoding='utf-8')
            imu = config._load_configuration(source)[10]
        self.assertEqual(imu.gyro_dropout_probability, config.ImuSimParameters.stress().gyro_dropout_probability)
        self.assertEqual(imu.mag_white_noise_sigma_t, 0)
        self.assertFalse(imu.sun_array.enabled)
        self.assertTrue(imu.enabled)

    def test_legacy_and_custom_ui_and_commands_are_separate(self):
        client = app.app.test_client()
        # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
        # React reads the strategy from bootstrap JSON; the browser test checks the DOM.
        with patch.dict(config.POINTING, strategy='legacy'):
            self.assertEqual(client.get('/api/viewer/config').json['pointing_strategy'], 'legacy')
            self.assertEqual(client.post('/api/pointing', json={'quaternion':[1,0,0,0]}).status_code,400)
            self.assertEqual(client.post('/update/mode', json={'mode':'NADIR'}).status_code,200)
        with patch.dict(config.POINTING, strategy='custom'):
            self.assertEqual(client.get('/api/viewer/config').json['pointing_strategy'], 'custom')
            self.assertEqual(client.post('/update/mode', json={'mode':'NADIR'}).status_code,400)
            self.assertEqual(client.post('/api/pointing', json={'quaternion':[1,0,0,0]}).status_code,200)

    def test_compact_compressed_and_unchanged_telemetry(self):
        import gzip
        snapshot = dict(sequence=1, orbit_path_ecef_m=[[1,2,3]]*181)
        app.accept_telemetry_snapshot(snapshot)
        client=app.app.test_client()
        plain=client.get('/api/latest')
        zipped=client.get('/api/latest',headers={'Accept-Encoding':'gzip'})
        self.assertEqual(gzip.decompress(zipped.data),plain.data)
        self.assertLess(len(zipped.data),len(plain.data))
        unchanged=client.get('/api/latest',headers={'If-None-Match':plain.headers['ETag']})
        self.assertEqual(unchanged.status_code,304)
        self.assertEqual(unchanged.data,b'')

    def test_local_delivery_avoids_http(self):
        delivered=[]
        with patch('requests.Session.post') as post:
            publisher=LatestTelemetryPublisher('http://unused',.1,sink=delivered.append)
            publisher.publish({'sequence':123})
            publisher.close()
            post.assert_not_called()
        self.assertEqual(delivered,[{'sequence':123}])

    def test_transport_does_not_wait_for_slow_http_and_bounds_backlog(self):
        entered, release = Event(), Event()
        delivered = []
        def slow_post(session, url, json, timeout):
            delivered.append(json['sequence'])
            entered.set()
            release.wait(2)
            return type('Response', (), {'raise_for_status': lambda self: None})()
        with patch('requests.Session.post', slow_post):
            publisher = LatestTelemetryPublisher('http://unused', .1)
            publisher.publish({'sequence':0})
            self.assertTrue(entered.wait(1))
            start = time.perf_counter()
            for i in range(1, 101):
                publisher.publish({'sequence':i})
            self.assertLess(time.perf_counter()-start, .5)
            self.assertEqual(publisher.replaced, 99)
            release.set()
            publisher.close()
            self.assertEqual(delivered, [0,100])



    def test_remote_command_reaches_actual_controller(self):
        import satellite_rotational_dynamics_var_mag_field as dynamics
        identity = np.array([1., 0, 0, 0])
        cs.set_pointing_input(identity)
        zero = dynamics._rw_control_torque(identity, np.zeros(3))
        response = app.app.test_client().post('/api/pointing', json={
            'quaternion': [.9238795325, 0, .3826834324, 0]}).json
        command = cs.get_pointing_command()
        with patch.object(cs, '_custom_target', identity.copy()), patch.object(cs, '_command_id', None):
            cs.accept_pointing_command(command)
            self.assertEqual(cs.get_pointing_command()['command_id'], response['command_id'])
            torque = dynamics._rw_control_torque(identity, np.zeros(3))
            self.assertGreater(np.linalg.norm(torque - zero), 1e-6)
            before = cs.get_pointing_command()
            cs.accept_pointing_command(command)
            self.assertEqual(before['sequence'], cs.get_pointing_command()['sequence'])

    def test_telemetry_response_returns_pending_command(self):
        cs.set_pointing_input([1, 0, 0, 0])
        response = app.app.test_client().post('/update_telemetry', json={'timestamp': '2026-10-07T00:00:00Z'})
        self.assertEqual(response.json['pointing_command']['command_id'], cs.get_pointing_command()['command_id'])

    def test_http_publisher_delivers_commands_without_extra_requests(self):
        cs.set_pointing_input([.9238795325, 0, .3826834324, 0])
        command = cs.get_pointing_command()
        delivered, ready = [], Event()
        def accept(value):
            delivered.append(value)
            ready.set()
        with patch('requests.Session.post') as post:
            post.return_value.json.return_value = {'pointing_command': command}
            publisher = LatestTelemetryPublisher('http://127.0.0.1:5000/update_telemetry', .25, command_sink=accept)
            try:
                publisher.publish({'timestamp': '2026-10-07T00:00:00Z'})
                self.assertTrue(ready.wait(2))
                self.assertEqual(delivered[0]['command_id'], command['command_id'])
                self.assertEqual(post.call_count, 1)
            finally:
                publisher.close()
