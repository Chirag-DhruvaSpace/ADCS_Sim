# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import unittest
from engine.simulation.pacing import SimulationPacer


class PacingTests(unittest.TestCase):
    def pacer(self, speed=1):
        self.wall = 100.0
        def sleep(seconds):
            self.wall += seconds
        return SimulationPacer(speed, now=lambda: self.wall, sleep=sleep)

    def test_absolute_deadlines_do_not_accumulate_work_time(self):
        p = self.pacer()
        for tick in range(1, 101):
            self.wall += .003
            p.wait_until(tick * .02)
        self.assertAlmostEqual(self.wall, 102.)

    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    def test_speed_and_slow_host_preserve_simulation_time(self):
        p = self.pacer(4)
        p.wait_until(4)
        self.assertAlmostEqual(self.wall, 101.)
        self.wall += 2
        p.wait_until(5)
        self.assertAlmostEqual(self.wall, 103.)
        self.assertEqual(p.metrics(5)['simulation_lag_s'], 7)

    def test_invalid_speeds(self):
        for speed in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                self.pacer(speed)

    def test_rate_change_keeps_simulated_time_continuous(self):
        p = self.pacer()
        p.wait_until(2)
        p.set_speed(2, 2)
        p.wait_until(4)
        self.assertAlmostEqual(self.wall, 103.)
        self.assertEqual(p.metrics(4)['simulation_speed_requested'], 2)
        self.assertAlmostEqual(p.metrics(4)['simulation_speed_actual'], 2)

    def test_live_yaml_speed_edit(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            path = Path(directory)/'parameters.yaml'
            path.write_text('simulation: {speed: 1.0}', encoding='utf-8')
            p = self.pacer()
            p.poll_speed(path, 0)
            self.wall += 1.1
            path.write_text('simulation: {speed: 4.0}', encoding='utf-8')
            p.poll_speed(path, 1.1)
            self.assertEqual(p.speed, 4)
            self.wall += 1.1
            path.write_text('simulation: {speed: -1}', encoding='utf-8')
            p.poll_speed(path, 2.2)
            self.assertEqual(p.speed, 4)
            self.assertIsNotNone(p.configuration_error)
