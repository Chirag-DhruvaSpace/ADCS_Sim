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

    def metrics(self, simulation_seconds):
        elapsed = max(0.0, self.now() - self.started)
        return dict(simulation_speed_requested=self.speed,
                    simulation_speed_actual=(simulation_seconds-self.simulation_origin) / elapsed if elapsed else 0.0,
                    simulation_lag_s=max(0.0, elapsed * self.speed - (simulation_seconds-self.simulation_origin)),
                    simulation_speed_configuration_error=self.configuration_error)
