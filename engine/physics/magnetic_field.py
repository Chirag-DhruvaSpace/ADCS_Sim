from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np

from engine.math.vector3 import Vector3


class OrekitIGRF:
    """Time-varying IGRF field queried through Orekit's geomagnetic model."""

    def __init__(self, earth_shape, inertial_frame, earth_fixed_frame) -> None:
        from org.orekit.models.earth import GeoMagneticFieldFactory

        self.earth_shape = earth_shape
        self.inertial_frame = inertial_frame
        self.earth_fixed_frame = earth_fixed_frame
        self._factory = GeoMagneticFieldFactory
        self._models: dict[float, object] = {}

    @staticmethod
    def _decimal_year(utc_dt: datetime) -> float:
        utc_dt = utc_dt.astimezone(timezone.utc)
        start = datetime(utc_dt.year, 1, 1, tzinfo=timezone.utc)
        next_start = datetime(utc_dt.year + 1, 1, 1, tzinfo=timezone.utc)
        return utc_dt.year + (utc_dt - start).total_seconds() / (next_start - start).total_seconds()

    def field_eci(self, position_eci_m: np.ndarray, utc_dt: datetime, absolute_date) -> Vector3:
        from org.hipparchus.geometry.euclidean.threed import Vector3D

        position = Vector3D(*np.asarray(position_eci_m, dtype=float).reshape(3))
        geodetic = self.earth_shape.transform(position, self.inertial_frame, absolute_date)
        decimal_year = self._decimal_year(utc_dt)
        model_year = math.floor(decimal_year)
        model = self._models.get(model_year)
        if model is None:
            # The repository's WMM resource covers the current operational
            # epoch; keep IGRF available for historical dates through Orekit's
            # own validity selection rather than embedding coefficients here.
            try:
                model = self._factory.getIGRF(float(decimal_year))
            except Exception:
                model = self._factory.getWMM(float(decimal_year))
            self._models[model_year] = model

        elements = model.calculateField(
            geodetic.getLatitude(),
            geodetic.getLongitude(),
            geodetic.getAltitude() / 1000.0,
        )
        ned = elements.getFieldVector()
        lat = geodetic.getLatitude()
        lon = geodetic.getLongitude()

        # Orekit returns the geomagnetic vector in north/east/down, in tesla.
        north, east, down = float(ned.getX()), float(ned.getY()), float(ned.getZ())
        ecef = np.array([
            -math.sin(lat) * math.cos(lon) * north - math.sin(lon) * east - math.cos(lat) * math.cos(lon) * down,
            -math.sin(lat) * math.sin(lon) * north + math.cos(lon) * east - math.cos(lat) * math.sin(lon) * down,
            math.cos(lat) * north - math.sin(lat) * down,
        ])
        ecef_vector = Vector3D(*ecef)
        eci_vector = self.earth_fixed_frame.getTransformTo(self.inertial_frame, absolute_date).transformVector(ecef_vector)
        return Vector3(eci_vector.getX(), eci_vector.getY(), eci_vector.getZ())
