<!-- made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag -->
# Simulation frontend

JavaScript React app built with Vite. The migration preserves the existing dashboard, Three.js rendering, GSAP/WAAPI animations, telemetry APIs, local settings, payload camera, and scroll-controlled reference video. The Three.js version remains 0.160.0 and GSAP remains 3.15.0 to match the previous viewer. GLTF, Draco, KTX2, Meshopt and geometry utilities come from the installed Three.js package.

From the repository root, build the frontend once:

```powershell
cd frontend
npm.cmd install
npm.cmd run build
cd ..
.venv/Scripts/python.exe run_simulator.py
```

Open `http://127.0.0.1:5000`. Flask serves `frontend/dist/index.html` and the fingerprinted assets under `/frontend/assets/`. Rebuild after source changes. A missing build produces an explicit setup message instead of silently loading the old frontend.

For frontend development, keep the simulation backend running and use another terminal:

```powershell
cd frontend
npm.cmd run dev
```

Open the URL Vite prints, normally `http://127.0.0.1:5173/frontend/`. API requests, imagery, models, decoder binaries and video requests proxy to Flask. Set `LEAP_BACKEND_URL` to use another backend address. `npm.cmd run preview` previews the production build with the same proxy.

<!-- made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag -->
The source structure separates responsibilities:

```text
src/
  assets/       Asset URL catalog; original media stays in ../static
  components/   Prop-based cards, charts, diagrams, settings and selectors
  hooks/        Telemetry subscriptions
  layouts/      Viewer canvas, mission header and dashboard shell
  pages/        Overview, Sensors and Pointing
  routes/       Persistent workspace panels and active-page subscriptions
  services/     Telemetry store, conversions, lifecycle and settings bindings
  viewer/       Simulation orchestration and camera/telemetry animation loop
    cosmos/     Reference video, calibrated zoom and 3D star backgrounds
    diagrams/   Shared GPU diagrams with atomic canvas commits
    earth/      Earth materials, atmosphere, clouds and aurora
    imagery/    Tiled imagery loading, visibility, cache and fades
    spacecraft/ CAD loading, geometry worker and sensor markers
  App.jsx
  App.css
  main.jsx
  index.css
```

Each visual component has a matching `.jsx`/`.css` pair. Shared card styling belongs to `MissionCard`; individual cards inherit it. React owns the visible dashboard. The 3D engine owns the main canvas, projected labels and high-frequency animation state. Hidden diagnostic bindings preserve existing engine controls; they are deliberately memoized so React never overwrites values maintained by the engine.

React does not itself increase GPU FPS or video frame rate. This structure avoids React renders on animation frames, subscribes only the visible page to telemetry, retains bounded chart history, and builds cacheable dependency chunks. It preserves mesh detail, texture settings and the original video's resolution. FPS and 1% lows still depend on GPU work, video decoding, imagery uploads and device load; compare production builds under identical settings before claiming an improvement. Vite development speed is separate from simulation FPS.

Run data regression checks with `npm.cmd test`. For Chrome integration checks, start the read-only fixture from the repository root, then run the browser check in another terminal:

```powershell
.venv/Scripts/python.exe scripts/viewer_test_server.py
# In another terminal:
cd frontend
npm.cmd run test:browser
```

The browser test requires installed Google Chrome. It intercepts flight-control POSTs, injects changing fixture telemetry and delays GPU readback to check diagram stability. `LEAP_TEST_URL` can change the fixture URL. Use the fixture rather than a live mission backend for these checks.

The requested credit appears at the top and inside authored JavaScript, JSX, CSS and documentation files. `package.json` uses author/description metadata because JSON does not support comments. Generated lockfiles, build output, installed dependencies and original binary/media assets retain their valid formats and original licensing. `node_modules` and `dist` are ignored; keep `package-lock.json` for reproducible installs.

Runtime models, textures, icons, reference media and decoder binaries are stored in `frontend/assets/` and served once at `/assets/`. Vite proxies those URLs in development; the large reference video is not duplicated in `dist`. Offline extracted reference frames and screenshots are kept in the ignored `frontend/assets/reference-analysis/` directory. Retired HTML templates and static JavaScript/CSS have been removed; the old ground-track page URL redirects to Overview.

Defaults match the approved look out of the box: Ultra preset, Sharp tiles, cloud opacity 0.15, FPS + sim-feed meters on, video streaming off, all sensor markers on. Existing saved settings receive these defaults once via a revision flag; subsequent user tweaks persist in localStorage as before. Sensor hardware remains enabled by the YAML configuration. Satellite views receive brighter night-side terrain and city lights; Overview retains its original terrain brightness.

The startup screen uses the supplied Dhruva Space logo and black-hole background in `assets/loading/`. Progress follows configuration, model transfer/geometry preparation, Earth imagery and the first ready simulation frame. Failures remain visible; the splash does not finish on a timer. Overview now makes a limited camera turn, delays the footage crossfade until a smaller Earth, and fades orbital context into a view scale. The scale follows camera projection in 3D; footage distances are explicitly approximate because the source contains no camera-distance metadata.

Magnetorquer plots now publish only physical magnetic torque (`dipole x true body magnetic field`). Previously total achieved actuator torque, including wheel torque, was mislabeled as magnetorquer torque. Angular acceleration retains the actual total dynamics response.


The shared liquid-glass variables are at the top of `src/layouts/DashboardLayout/DashboardLayout.glass.css`; they control tint, transparency, blur, borders and reflections across panels, menus and settings.
