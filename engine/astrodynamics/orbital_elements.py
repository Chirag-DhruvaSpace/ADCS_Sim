class OrbitalElements:

    def __init__(
        self,
        semi_major_axis,
        eccentricity,
        inclination,
        raan,
        argument_of_periapsis,
        true_anomaly,
    ):

        self.a = semi_major_axis
        self.e = eccentricity
        self.i = inclination
        self.raan = raan
        self.aop = argument_of_periapsis
        self.ta = true_anomaly

    def __repr__(self):
        return (
            f"OrbitalElements(\n"
            f" a={self.a}\n"
            f" e={self.e}\n"
            f" i={self.i}\n"
            f" RAAN={self.raan}\n"
            f" AOP={self.aop}\n"
            f" TA={self.ta}\n"
            f")"
        )