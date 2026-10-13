import json
import socket
import time
import unittest

from send_simulated_sensor_data import SensorDataSender, get_raw_sensor_data


class SensorTCPTests(unittest.TestCase):
    def test_late_start_disconnect_and_reconnect(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.close()
        sender = SensorDataSender(port=port, retry_s=0)
        calls = []

        def collect():
            calls.append(True)
            return get_raw_sensor_data(12.5)

        try:
            for _ in range(5):
                sender.send_simulated_sensor_data(collect)
            self.assertEqual(calls, [])
            sender.close()
            listener = socket.socket()
            listener.bind(('127.0.0.1', port))
            listener.listen()
            listener.settimeout(1)
            for _ in range(100):
                if sender.send_simulated_sensor_data(collect):
                    break
                time.sleep(.001)
            client, _ = listener.accept()
            client.settimeout(1)
            with client.makefile('rb') as stream:
                packet = json.loads(stream.readline())
            self.assertEqual(packet['t_sim_s'], 12.5)
            self.assertIsNone(packet['gps'])
            client.close()
            time.sleep(.01)
            sender.send_simulated_sensor_data(collect)
            self.assertFalse(sender.connected)
            for _ in range(100):
                if sender.send_simulated_sensor_data(collect):
                    break
                time.sleep(.001)
            client, _ = listener.accept()
            client.settimeout(1)
            self.assertIn(b'gyroscope', client.recv(8192))
            client.close()
        finally:
            sender.close()
            listener.close()


if __name__ == '__main__':
    unittest.main()
