import math

class Vector3:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float (z)
    
    def __add__(self, other):
        return Vector3(
            self.x + other.x, self.y + other.y, self.z + other.z
        )
    
    def __sub__(self, other):
        return Vector3(
            self.x - other.x, self.y - other.y, self.z - other.z
        )
    
    def __mul__(self, scalar):
        return Vector3(
            self.x * scalar, self.y * scalar, self.z * scalar
        )
    
    def __truediv__(self, scalar):
        return Vector3(
            self.x / scalar, self.y / scalar, self.z / scalar
        )
    
    def magnitude (self):
        return math.sqrt(
            self.x**2 + self.y**2 + self.z**2
        )
    
    def normalize(self):                # unit vector = direction/ distance
        mag = self.magnitude()
    
        if mag == 0:
            return Vector3()
        else:
            return self / mag
    
    def dot(self, other):
        return (
            self.x * other.x + self.y * other.y + self.z * other.z
            )
    
    def cross(self, other):
        return Vector3(
            self.y * other.z - self.z * other.y, self.z * other.x - self.x * other.z, self.x * other.y - self.y * other.x
            )
    
    def magnitude_squared(self):
        return (
            self.x ** 2 + self.y ** 2 + self.z ** 2
        )
    
    def distance_to(self, other):
        return (
            other - self
        ).magnitude()
    
    def distance_squared(self, other):
        return (
            other - self
        ).magnitude_squared()
    
    def angle_between(self, other):         # a · b = |a||b| cos θ  becomes -> θ = cos⁻¹( (a · b) / (|a||b|) )
        dot = self.dot(other)
        mag = self.magnitude() * other.magnitude()
        if mag == 0:
            return 0
        value = max(
            -1,
            min(
                1, dot / mag
            )
        )
        return math.acos(value)