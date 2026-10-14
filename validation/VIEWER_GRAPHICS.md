# Viewer graphics validation

The scene uses Earth-fixed coordinates. Earth geography stays fixed while Orekit transforms satellite state and the Sun into ITRF at simulation time. Celestial telemetry now also supplies the geocentric Moon position and EME2000-to-ITRF rotation. The viewer uses these for Moon parallax/angular size and star-field rotation. The Moon follows the existing Meeus ephemeris; lunar libration and a measured star catalogue are not implemented. The clock stops when telemetry stops.

Imagery tiles never write depth: curved parent and child meshes otherwise intersect between vertices and create flashing patches. They still depth-test against opaque scene objects, render coarse-to-fine, and discard back-horizon fragments. The base globe is recessed 4 km as a display-only underlay; physical/geodetic calculations retain WGS84 dimensions. Coarse tile tessellation is increased to keep it above that underlay. Esri mosaics can still contain real source-image colour boundaries.

The orbit appears beyond 120 km camera-to-satellite distance (previously 1000 km). The Begumpet label uses WGS84 17.4355 N, 78.4579 E and is hidden beyond the horizon. Saved controls retain their existing storage key. Low quality reduces stars, resolution and imagery budgets and disables glass blur. Maximum framebuffer allocation is bounded to 16 million pixels. Frame rate depends on the laptop GPU and viewport; no hardware-independent FPS guarantee is implied.

Checks:

- `.venv/Scripts/python.exe -m unittest validation.test_sensor_navigation`

Map tile detail still needs an internet connection. The bundled base/cloud/Moon textures load locally. Cloud imagery is not time-varying weather. Existing Sun/Moon size sliders deliberately allow nonphysical display magnification.

Current checks: `.venv/Scripts/python.exe -B -m pytest validation/test_sensor_navigation.py validation/test_hardware_sensor_outputs.py`; frontend: `npm.cmd test` and `npm.cmd run test:browser` from `frontend/`. The browser fixture is `validation/tools/viewer_test_server.py`. Sensor locations and mount orientations are configured in backend YAML only.
