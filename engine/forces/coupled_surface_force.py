"""JPype Orekit force adapter using the same facet evaluator as attitude.

The ADCS publishes its true attitude/rate at each control tick. During the
orbit interval the rotation is extrapolated with that rate (first-order
partitioned orbit/attitude coupling). No independent isotropic SRP/drag is
registered alongside this adapter.
"""
import numpy as np
from engine.forces.base_force import Force


class CoupledSurfaceForce(Force):
    def __init__(self, provider):
        self.provider = provider
        self.proxy = None

    def register_with_propagator(self, propagator, body, universe, central_body,
                                 central_body_shape, inertial_frame):
        if not body.is_spacecraft:
            return
        import jpype
        from java.util import Collections
        from java.util.stream import Stream
        from org.hipparchus.geometry.euclidean.threed import Vector3D

        provider = self.provider

        class Implementation:
            def init(self, initial_state, target):
                pass

            def dependsOnPositionOnly(self):
                return False

            def dependsOnAttitudeRate(self):
                return True

            def getParametersDrivers(self):
                return Collections.emptyList()

            def getEventDetectors(self):
                return Stream.empty()

            def getFieldEventDetectors(self, field):
                return Stream.empty()

            def acceleration(self, state, parameters):
                pv = state.getPVCoordinates(inertial_frame)
                p, v = pv.getPosition(), pv.getVelocity()
                elapsed = float(state.getDate().durationFrom(provider._epoch_date))
                result = provider.surface_result(elapsed,
                    np.array([p.getX(), p.getY(), p.getZ()]),
                    np.array([v.getX(), v.getY(), v.getZ()]),
                    provider.predicted_attitude(elapsed))
                acc = (result.srp_force_eci_n + result.drag_force_eci_n) / body.mass
                return Vector3D(*map(float, acc))

            def addContribution(self, state, adder):
                adder.addNonKeplerianAcceleration(self.acceleration(state, []))

        self.proxy = jpype.JProxy('org.orekit.forces.ForceModel', inst=Implementation())
        propagator.addForceModel(self.proxy)
