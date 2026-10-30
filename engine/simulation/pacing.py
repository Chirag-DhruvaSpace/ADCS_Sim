# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""Monotonic presentation pacing; never changes Orekit integration steps."""
import math
import time


class SimulationPacer:
    def __init__(self, speed, *, now=time.perf_counter, sleep=time.sleep):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('Simulation speed must be finite and positive')
        self.speed = speed
        self.now, self.sleep = now, sleep
        self.started = now()
        self._metrics_started = self.started
        self.simulation_origin = 0.0
        self._checked_at = -float('inf')
        self._signature = None
        self.configuration_error = None

    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    def set_speed(self, speed, simulation_seconds):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('Simulation speed must be finite and positive')
        if speed != self.speed:
            self.speed = speed
            self.started = self.now()
            self._metrics_started = self.started
            self.simulation_origin = simulation_seconds

    def poll_speed(self, path, simulation_seconds):
        now = self.now()
        if now-self._checked_at < 1.0:
            return
        self._checked_at = now
        import yaml
        try:
            signature = path.stat().st_mtime_ns
            if signature == self._signature:
                return
            with path.open(encoding='utf-8') as stream:
                speed = float(yaml.safe_load(stream)['simulation']['speed'])
            self.set_speed(speed, simulation_seconds)
            self._signature = signature
            self.configuration_error = None
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as error:
            self.configuration_error = str(error)

    def wait_until(self, simulation_seconds):
        delay = self.started + (simulation_seconds-self.simulation_origin) / self.speed - self.now()
        if delay > 0:
            self.sleep(delay)

    def wait_firmware_sample(self, simulation_seconds, period_s):
        """Pace acquisition; rebase after a missed period instead of bursting.

        An overloaded host runs slower than real time and reports lateness.
        It must not emit a backlog of fixed-dt IMU packets instantaneously.
        """
        deadline = self.started + (simulation_seconds-self.simulation_origin)/self.speed
        late = max(0., self.now()-deadline)
        if late >= period_s:
            self.started += late
        self.wait_until(simulation_seconds)
        return late

    def metrics(self, simulation_seconds):
        elapsed = max(0.0, self.now() - self._metrics_started)
        return dict(simulation_speed_requested=self.speed,
                    simulation_speed_actual=(simulation_seconds-self.simulation_origin) / elapsed if elapsed else 0.0,
                    simulation_lag_s=max(0.0, elapsed * self.speed - (simulation_seconds-self.simulation_origin)),
                    simulation_speed_configuration_error=self.configuration_error)
