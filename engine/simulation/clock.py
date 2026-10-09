from __future__ import annotations


class SimulationClock:
    """
    Simulation clock with an Orekit AbsoluteDate epoch + elapsed seconds.

    The epoch defaults to J2000 (2000-01-01T12:00:00 TAI) the first time it
    is queried, so every time-dependent Orekit force model (NRLMSISE-00,
    Sun ephemeris, tesseral harmonics, EOPs) gets the correct absolute date.
    """

    def __init__(self, epoch=None) -> None:
        self.time = 0.0
        self._epoch = epoch

    def set_epoch(self, epoch) -> None:
        """Set an org.orekit.time.AbsoluteDate as the simulation t=0."""
        self._epoch = epoch

    @property
    def epoch(self):
        if self._epoch is None:
            from engine.orekit_runtime import start_jvm  # ensures JVM is up
            start_jvm()
            from org.orekit.time import AbsoluteDate  # type: ignore[reportMissingImports]
            self._epoch = AbsoluteDate.J2000_EPOCH
        return self._epoch

    def absolute_date(self):
        """Current simulation time as an Orekit AbsoluteDate."""
        return self.epoch.shiftedBy(float(self.time))

    def advance(self, dt) -> None:
        self.time += float(dt)

    def reset(self) -> None:
        self.time = 0.0