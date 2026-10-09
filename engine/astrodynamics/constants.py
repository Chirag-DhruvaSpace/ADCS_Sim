import math
import os
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

G = 6.67430e-11

@dataclass(frozen=True)
class GravityModel:
    model_name: str
    gravity_reference_radius: float
    zonal_coefficients: Mapping[int, float]
    is_normalized: bool
    reference: str

    def zonal(self, degree: int) -> float:
        return float(self.zonal_coefficients.get(degree, 0.0))

EARTH_GRAVITY_MODEL = GravityModel(
    model_name="EGM2008",
    gravity_reference_radius=6378136.3,
    zonal_coefficients=MappingProxyType(
        {
            2: 1.0826261738706e-3,
            3: -2.5321531e-6,
            4: -1.6196216e-6,
        }
    ),
    is_normalized=False,
    reference=(
        "Pavlis et al., The Development and Evaluation of the Earth "
        "Gravitational Model 2008 (EGM2008), JGR, 2012"
    ),
)

EARTH_MASS = 5.97219e24
EARTH_RADIUS = 6378137.0
EARTH_MU = 3.986004418e14
EARTH_FLATTENING = 1.0 / 298.257223563  # WGS84

SUN_MASS = 1.98847e30
SUN_RADIUS = 696340000.0
SUN_MU = 1.32712440018e20

MOON_MASS = 7.34767309e22
MOON_RADIUS = 1737400.0
MOON_MU = 4.9048695e12

AU = 149597870700.0
EARTH_ROTATION_RATE_RAD_PER_SEC = 7.2921150e-5
SOLAR_RADIATION_PRESSURE_AT_1_AU_N_PER_M2 = 4.56e-6

DAY = 86400.0
HOUR = 3600.0

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi

# --- Orekit high-fidelity defaults ------------------------------------------
OREKIT_DATA_PATH = os.environ.get("OREKIT_DATA", "./orekit-data")

EGM2008_FULL_DEGREE = 219
EGM2008_FULL_ORDER = 215
EGM2008_DEFAULT_DEGREE = 36
EGM2008_DEFAULT_ORDER = 36

# Dormand-Prince 853 (DOP853) defaults.
# CHANGED: these now hold the tuned working values (abs 1e-3, rel 1e-6).
# BOTH the engine and the reference propagator in main.py build their
# integrator from this file (via IntegratorConfig), so the
# engine-vs-reference comparison is never polluted by a config mismatch.
# Note: with OrbitType.EQUINOCTIAL the error control mixes units
# (a in metres, ex/ey/hx/hy dimensionless, lv in radians); these scalars
# are the validated working set for LEO.
DOP853_MIN_STEP = 1.0e-3       # seconds
DOP853_MAX_STEP = 600.0        # seconds
DOP853_ABS_TOLERANCE = 1.0e-3  # ~1 mm on the semi-major-axis component
DOP853_REL_TOLERANCE = 1.0e-6