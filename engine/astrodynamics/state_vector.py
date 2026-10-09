from engine.math.vector3 import Vector3


class StateVector:

    def __init__(self, position: Vector3, velocity: Vector3):

        self.position = position
        self.velocity = velocity

    def copy(self):

        return StateVector(

            Vector3(
                self.position.x,
                self.position.y,
                self.position.z
            ),

            Vector3(
                self.velocity.x,
                self.velocity.y,
                self.velocity.z
            )

        )

    def __repr__(self):
        return (
            f"StateVector(\n"
            f" Position={self.position},\n"
            f" Velocity={self.velocity}\n"
            f")"
        )