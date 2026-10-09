"""Bounded latest-snapshot HTTP delivery, independent of physics timing."""
from copy import deepcopy
from threading import Condition, Thread
import requests


class LatestTelemetryPublisher:
    def __init__(self, url, timeout, sink=None, command_sink=None):
        self.url, self.timeout = url, timeout
        self._condition = Condition()
        self._pending = None
        self._closed = False
        self._sink = sink
        self._command_sink = command_sink
        self.sent = self.failed = self.replaced = 0
        self._thread = Thread(target=self._run, name='telemetry-http', daemon=True)
        self._thread.start()

    def publish(self, snapshot):
        # Lists/arrays may be reused by the next tick; take ownership now.
        snapshot = deepcopy(snapshot)
        with self._condition:
            if self._closed:
                return
            if self._pending is not None:
                self.replaced += 1
            self._pending = snapshot
            self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify()
        self._thread.join(timeout=self.timeout + 1)

    def set_sink(self, sink):
        """Use direct snapshot delivery when viewer and physics share a process."""
        with self._condition:
            self._sink = sink

    def _run(self):
        with requests.Session() as session:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._closed or self._pending is not None)
                    if self._closed and self._pending is None:
                        return
                    snapshot, self._pending = self._pending, None
                    sink = self._sink
                try:
                    if sink is not None:
                        sink(snapshot)
                    else:
                        response = session.post(self.url, json=snapshot, timeout=self.timeout)
                        response.raise_for_status()
                        if self._command_sink is not None:
                            self._command_sink(response.json().get('pointing_command'))
                    self.sent += 1
                except (requests.RequestException, ValueError, TypeError):
                    self.failed += 1
