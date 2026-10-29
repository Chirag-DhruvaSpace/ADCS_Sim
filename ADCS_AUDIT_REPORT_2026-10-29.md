# ADCS simulator technical audit

Date: 29 October 2026 (Asia/Calcutta). Audited commit: a 0c18439a10f1a324090215b9bce42b95561837c.

## Executive summary

**Do not use this simulator as a flight-physics or HIL acceptance oracle yet.** The audit reproduced errors in magnetic-field altitude units, attitude-frame interpretation, target-quaternion construction, zero-field allocation, and identified an incomplete reaction-wheel momentum model. Several can coexist with apparently successful pointing because the controller, sensors, and reported errors share conventions or reference models.

There are **41 findings: 5 P0, 17 P1, 16 P2, and 3 P3**. Severity follows the supplied brief, including its unusually broad P0 definition covering incorrect physics and reproducible numerical failures. Findings include active defects, defects in callable legacy paths, and explicit fidelity limitations; each identifies its exposure. Counts are observations from this audit, not a claim that no other defects exist.

The architecture has useful foundations: an Orekit force-registration interface, a shared facet force/moment evaluator, sensor acquisition separated from navigation, seeded sensor generators, bounded asynchronous dashboard delivery, and an operational React/Three.js frontend. However, the owner's mental model only partly matches implementation. Orekit is Java accessed from Python through JPype; there is no authored Java backend here. The bundled gravity field actually loaded is **EIGEN-6S**, not EGM2008. The contemporary magnetic model selected in the tested environment is **WMM**, reached through an IGRF-first fallback. The simulator's firmware boundary uses **UDP**, with the external COSMOS/TCP/flight-software leg outside this repository. Most YAML changes require a restart; speed polling is a specific exception. The advanced model uses rectangular exterior approximations and box blockers, not an exact aerodynamic/optical mesh.

**Coverage limitation:** this report does not meet the brief's literal 100% line-by-line coverage requirement. It would be false to certify that it does. All 19,674 tracked paths were inventoried; all 126 project Python files, totaling 22,822 lines, received an AST syntax/structure scan. The audit then examined the core boundaries and selected source ranges in depth, ran the validation suite and focused reproductions, and exercised the viewer. Thousands of bundled environment files, much frontend source/CSS, experimental code, and most historical patches were not semantically reviewed. The coverage appendix distinguishes review from automated inspection and enumerates remaining scope. This is a substantial but incomplete audit, not the exhaustive clearance requested by the brief.

No source, configuration, dependency, or existing artifact was intentionally changed. The report is the sole persistent deliverable. No suggested fixes below were applied.

## Verification record

Both supplied documents were read. The Markdown contains the complete brief. The ten-page PDF contains a cover and the same eight-section brief; its cover/font streams and nine body-page content streams were decoded in memory. No additional operational requirement was found in the PDF.

| Check | Observed result | Limit |
|---|---|---|
| Python validation suite | 102 passed, 2 failed, 20 subtests passed | Two runs; the second explicitly selected bundled JDK 21 and used disposable pytest storage |
| Frontend unit tests | 9 passed | Telemetry/store/coordinate and fullscreen unit coverage |
| Frontend source build | Vite 6.4.3 production build passed; 151 modules; 3.00 s reported build time | Native config loader, temporary output outside repository, removed afterward; existing dist was not overwritten |
| Browser smoke | Exit 0; no page errors; CAD ready; loading splash gone; no startup error | Existing local build, Chrome/Playwright, isolated fixture; not the full repository browser regression script |
| Browser render snapshot | 19 geometries, 10 textures, 15 draw calls | One frame/configuration; not an FPS or GPU-memory benchmark |
| Headless closed loop | 10 simulated seconds in 2.435 s; 101 loop iterations; 9 snapshots | In-memory legacy SUN_POINTING_RW selection, pacing/speed polling disabled, direct in-memory telemetry sink; no external firmware |
| Magnetic API comparison | 46.378110 microtesla at 500 m versus 36.023634 microtesla at 500,000 m | WMM 2026.0, latitude 0.5 rad, longitude 1 rad; same installed Orekit model |
| Target singularities | Kinematic targets returned NaNs for two ordinary circular-orbit geometries | Direct function calls, not a long mission run |
| Gravity provenance | Loaded-data names include orekit-data/Potential/eigen-6s.gfc | Runtime observation, not inference from filenames alone |
| Python source scan | 126 files / 22,822 lines; no syntax errors | Parsing is not semantic line-by-line review |

The first pytest run inherited JAVA_HOME pointing at JDK 25. The JDK-21 rerun reproduced both test failures. Windows/JPype access-violation diagnostic stacks appeared during suite collection, including in the rerun, although pytest continued and reported results. Minimal Orekit probes and the isolated headless run completed. These diagnostics are recorded as an unresolved environment/runtime observation, not attributed to a proven repository bug or presented as a clean full-stack runtime bill of health.

The installed environment reported orekit-jpype 13.1.9.0, JPype1 1.7.1, jdk4py 21.0.8.2, NumPy 2.5.4, and SciPy 1.18.1. These observations are environment evidence, not recommended versions.

## Findings

### A001 — P0 — Magnetic-field altitude is divided by 1,000 incorrectly

**Location/evidence:** engine/physics/magnetic_field.py:48–52 passes geodetic.getAltitude() / 1000.0 to model.calculateField().

**Impact:** the roughly 500 km spacecraft is evaluated near 500 m. The direct API reproduction above increased field magnitude by 28.74%. This changes sensor outputs, magnetic control authority, momentum dumping, and residual-dipole disturbance torque. Using the same wrong field for both sensor truth and onboard reference can hide the error from the estimator.

**Confidence:** confirmed by source and installed-API reproduction. **Exposure:** active default firmware and legacy paths.

**Suggested fix:** pass geodetic altitude in metres. Add an independent high-altitude field reference test that checks magnitude and direction, not just consistency between two callers of this wrapper. Orekit's official API specifies metres for height: [GeoMagneticField API](https://www.orekit.org/site-orekit-13.1.5/apidocs/org/orekit/models/earth/GeoMagneticField.html).

### A002 — P0 — Quaternion kinematics and environment transforms disagree

**Location/evidence:** satellite_rotational_dynamics_var_mag_field.py:951–956,1002 uses q_dot = 0.5 * Omega @ q, the right Hamilton body-rate product. Its helper at 128–145 returns the transpose of the corresponding active body-to-inertial matrix. Legacy magnetic physics uses that helper's transpose at 931,938; firmware actuation uses the untransposed matrix at 789. spacecraft_surface_physics.py:22–24,91,97 treats the same passive matrix as body-to-ECI. calculate_disturbances.py:258,275 uses its transpose for gravity-gradient and residual magnetic moments. The renderer explicitly transposes only for firmware at satellite_flight_visualisation.py:569–575.

**Impact/reproduction:** with identity initial attitude and a positive 90-degree rotation about body Z, an inertially fixed +X vector must appear along body -Y. The legacy field transform returned +Y; the firmware transform returned -Y. The surface evaluator sent a body +X normal toward inertial -Y, opposite the kinematic rotation. Thus firmware sensor/actuator corrections do not repair the shared facet and disturbance models. An end-to-end legacy convergence test cannot independently validate these conventions.

**Confidence:** confirmed by algebra and direct numerical probes. **Exposure:** active; especially misleading when comparing firmware and legacy modes.

**Suggested fix:** choose one explicit quaternion/frame contract, derive its rate equation and transforms together, and convert exactly once at external boundaries. Verify rotating basis vectors, torque work, mounted sensors, rendering, and free rigid-body angular-momentum conservation against independent constructions.

### A003 — P0 — Valid 180-degree target rotations produce NaNs

**Location/evidence:** quat2eul.py:95–98 computes q0 = sqrt(1 + trace(R))/2 and divides the other components by 4*q0. kinematic_robustness_pointing.py:79 calls that converter.

**Impact/reproduction:** rotmat_to_quaternion(diag(1,-1,-1)) returned [0,nan,nan,nan]. The actual kinematic target function also returned all NaNs at t=0 for r=[7e6,0,0], v=[0,7500,0], and for r=[0,0,7e6], v=[7500,0,0]. Both are valid circular-orbit geometries. Target generation can fail before control tuning matters.

**Confidence:** confirmed by reproduction. **Exposure:** kinematic mode and any caller of the shared converter; periodic_gain_sun_pointing.py:104–107 repeats the same vulnerable formula for its fixed target.

**Suggested fix:** use a branch-stable largest-component/Shepperd conversion or a vetted rotation library, with explicit finite/proper-rotation checks. nadir_pointing.py already contains a robust conversion pattern worth consolidating.

### A004 — P0 — Zero-field allocation violates its return contract

**Location/evidence:** MTR_allocator.py:8–9 returns a single np.zeros(3) when B2 < 1e-12; line 19 normally returns M, tau_actual. periodic_gain_sun_pointing.py:186 unpacks two results.

**Impact/reproduction:** unpacking torque_to_dipole(zeros(3), zeros(3)) raised ValueError: too many values to unpack (expected 2). A missing/zero initial magnetic belief, a model substitute, or a low-field test turns a safeguard into a runtime failure.

**Confidence:** confirmed by reproduction. **Exposure:** legacy magnetic-pointing path and direct allocation callers.

**Suggested fix:** always return the same two-vector structure, and define an explicit low-field/invalid-field actuator policy. Test exactly zero and values around the threshold.

### A005 — P0 — Reaction-wheel dynamics do not conserve total angular momentum

**Location/evidence:** satellite_rotational_dynamics_var_mag_field.py:1000 evaluates I_inv @ (tau_actual + external_torque + tau_disturbance - cross(omega,I@omega)); there is no rotor-momentum contribution. Firmware wheel momentum is tracked separately in firmware_sitl_link.py:215–224. Legacy momentum advances with +store.rw_torques*dt at torque_distribution.py:268 while the body receives +A@rw_t at dynamics line 823.

**Impact:** a spinning wheel cluster contributes body-frame momentum A*h and a gyroscopic term involving omega cross A*h. The firmware's bookkeeping is not fed into the plant equation, so wheel-speed telemetry can drive firmware compensation for a physical effect absent from the simulated spacecraft. In the legacy convention, if tracked h is interpreted as physical wheel momentum along A's declared spin axes, body and wheel torque signs also add rather than cancel. This invalidates coupled high-rate/desaturation predictions.

**Confidence:** confirmed equation/state inspection and conservation-law analysis; no calibrated wheel hardware run. **Exposure:** all wheel modes; particularly SITL/HIL.

**Suggested fix:** integrate rotor momenta and bus state as one physical system, with a declared motor/body reaction sign and consistent total momentum. Include initial spinning wheels and nonzero body rates in torque-free conservation tests. Treat display-only momentum as such until it participates in the physical model.

### A006 — P1 — Firmware actuation bypasses the configured plant limits

**Location/evidence:** firmware_sitl_adapter.py:148–150 copies received wheel torques and dipoles directly. Dynamics line 789 applies them without the legacy allocator. firmware_sitl_link.py:223–224 integrates wheel momentum without torque, speed, or momentum limits. Its lines 79–83 explicitly document passing pre-driver MTR commands instead of saturated/encoded hardware current.

**Impact:** finite but arbitrarily large commands produce corresponding bus torque, and wheels can spin beyond configured capacity indefinitely. A firmware controller or desaturation implementation can pass SITL despite requiring impossible actuator behavior. This is an explicitly documented simplification, but it materially contradicts a realistic actuator acceptance model.

**Confidence:** confirmed source. **Exposure:** default firmware mode; HIL preparation.

**Suggested fix:** place actuator torque/speed/momentum/current limits and response dynamics in a plant layer shared by all controllers. Report requested versus achieved commands. Keep a separate explicit ideal-actuator experiment mode if needed.

### A007 — P1 — Lost firmware commands remain applied forever

**Location/evidence:** firmware_sitl_link.py:59–60,133–135,168–175 retains the latest values indefinitely. firmware_sitl_adapter.py:147–156 always returns those values. Its metadata at 171–175 turns status red after two wall seconds but does not change actuation.

**Impact:** killing ADS/ACS or losing a command stream leaves the spacecraft accelerating under its last wheel/dipole commands. One active stream can refresh the combined received_at timestamp while another channel is stale. Red dashboard status does not provide a plant-side failsafe.

**Confidence:** confirmed source. **Exposure:** active SITL; disconnection/HIL cases.

**Suggested fix:** time-tag and expire each command channel independently, with a specified zero/hold/ramp policy and explicit startup/reconnection states. Exercise partial-channel loss as well as total disconnect.

### A008 — P1 — The 100 Hz firmware IMU is delivered in bursts after integration

**Location/evidence:** satellite_flight_visualisation.py:397–418 sends the tick's sensors, polls commands once, then integrates the complete dt interval. Lines 427–433 subsequently send every interior 10 ms IMU sample in a tight loop. sensor_link.py:213 serializes only sensor ID and register counts, without capture timestamp or sequence number.

**Impact:** at the default 0.1 s plant step, nine intermediate samples are sent as a burst rather than at their physical 10 ms acquisition instants. Firmware cannot affect that already-integrated interval. Queue behavior and response latency depend on wall-clock scheduling and host performance. This is unsuitable as a timing-equivalent 100 Hz HIL loop even though it generates the correct number of samples.

**Confidence:** confirmed transmission/control ordering; actual external firmware scheduling effects not measured. **Exposure:** active SITL and HIL timing claims.

**Suggested fix:** use timestamped lockstep scheduling, or pace acquisition and accept commands at the intended hardware cadence. Specify what the firmware integrates between timestamps, queue bounds, and lag/deadline behavior. Measure the complete firmware loop before claiming real-time equivalence.

### A009 — P1 — Attitude updates do not invalidate dense orbital output

**Location/evidence:** engine_adcs_bridge.py:282–285 says it discards dense output but only resets propagator initial state; it leaves self._dense and self._dense_end intact. Lines 233–248 reuse that ephemeris until its window ends. The default YAML sets orbit_output_window_s: 0.5 at line 243, exceeding the 0.1 s control tick.

**Impact/reproduction:** with a 10 s output window, after generating the window, changing attitude at 0.1 s and querying 0.2 s reused exactly the same cached ephemeris object. Orbit drag/SRP therefore continue reflecting the previous extrapolated attitude while attitude torques use the updated geometry. The default configuration exposes the same issue within each 0.5 s window; numerical impact depends on the maneuver and area/mass ratio.

**Confidence:** confirmed source and cache-identity reproduction; long-orbit position error not quantified.

**Suggested fix:** invalidate/rebuild future ephemerides whenever force-driving attitude changes, or use an explicitly bounded coupling scheme whose cache error is validated. Rebase epoch/state consistently at the invalidation instant.

### A010 — P1 — Configured initial attitude does not initialize the attitude plant

**Location/evidence:** satellite_parameters.yaml:95–96 defines initial_quaternion_scalar_first. engine_adcs_bridge.py:60 reads it for orbit surface prediction. Dynamics line 1019 instead defines y0 starting with [1,0,0,0]; satellite_flight_visualisation.py:231 copies that y0 into X_rot.

**Impact:** a deployment or recovery experiment configured with a nonidentity initial attitude still begins its bus integration at identity. The orbit provider and attitude plant may initially assume different orientations. This can make a worst-case recovery study silently test an easier case.

**Confidence:** confirmed source/dataflow. **Exposure:** any nonidentity initial attitude configuration.

**Suggested fix:** validate/normalize the configured quaternion once and use that same initial state for the plant, surface predictor, control reference, and diagnostics. Keep estimator prior independently configurable.

### A011 — P1 — Star-tracker geometry contradicts its firmware mounting

**Location/evidence:** satellite_parameters.yaml:581–586 documents the flight mount and comments out its quaternion, then selects identity. sensor_link.py:77 and 236 still use the fixed flight relative quaternion for wire conversion. The existing validation/test_sensor_link.py:227 mount assertion fails: identity differs in 7/9 matrix entries from the firmware mount.

**Impact:** the detector's Sun/Earth exclusion geometry and anisotropic error axes correspond to an identity-mounted camera, while the interface is described as the flight-mounted unit. Algebraically undoing a fixed mount on the wire does not make the optical boresight or availability realistic. Identity may be an intentional experiment; it should not masquerade as flight configuration.

**Confidence:** confirmed mismatch and failing regression; actual hardware mounting not independently measured. **Exposure:** default nominal tracker/SITL configuration.

**Suggested fix:** establish the authoritative physical mounting and derive detector geometry, display, firmware conversion, and contract tests from it. If identity is desired experimentally, label the configuration and update its expectations explicitly.

### A012 — P1 — Single-chip navigation does not expire stale measurements

**Location/evidence:** compute_simulated_attitude.py:266–283 sets validity on receipt but leaves it unchanged when subsequent input is None. estimate() at 385–391 feeds the retained gyro and vectors without an age check for the single-sensor path. Age/skew enforcement at 345–353 only covers multi-unit fusion. The default YAML units lists are empty, selecting the single-chip path.

**Impact/reproduction:** one valid gyro/magnetometer reading at t=0 followed by no readings at t=10 still yielded imu_gyro_valid=True and imu_mag_valid=True with fusion_max_age_s=0.5, and kept the old angular rate. A missing sensor can keep steering and propagating attitude while telemetry says it is valid. Saturated single-chip gyro samples are likewise stored as valid and used for propagation/control.

**Confidence:** confirmed reproduction and source. **Exposure:** active default single-chip path, dropouts/outages, sensor replacement.

**Suggested fix:** apply common freshness, saturation, and quality rules before both single- and multi-unit paths. Separate receipt-valid, held-value, usable-for-control, and estimator propagation/coasting status.

### A013 — P1 — Increasing configured sensor rate does not generate the requested samples

**Location/evidence:** simulate_gyroscope.py:264–281 and simulate_magnetometer.py:265–282 emit only the latest crossed grid index per call. The normal simulation calls acquisition once per control tick at satellite_flight_visualisation.py:327. Only the firmware-specific path creates interior IMU samples at 427–433.

**Impact/reproduction:** a gyro configured for 100 Hz but called at 0,0.1,0.2 s generated 3 samples rather than 21. Similar skipped-grid behavior exists in the other sampled models. Changing YAML can alter stated update rate/noise assumptions without changing actual throughput, invalidating rate-dependent estimator and controller studies.

**Confidence:** confirmed gyro reproduction and scheduling inspection. **Exposure:** legacy configurations with sensor rate above loop rate or large control steps.

**Suggested fix:** schedule each sensor independently against truth interpolation and deliver every due sample, or reject unsupported rate/step combinations explicitly. The firmware count workaround should become a general scheduler rather than a mode exception.

### A014 — P1 — Control-step values can pass configuration validation and make time stop or reverse

**Location/evidence:** ControlParameters.__post_init__ at satellite_parameters.py:128–139 validates sweep/gain fields but not control_loop_period_s or detumble threshold ordering. run_simulation at 224–226 merely casts dt; the loop advances t += dt at 1173.

**Impact/reproduction:** replace(CONTROL,control_loop_period_s=0) was accepted. A zero/nonfinite/negative step can lead to a nonadvancing loop, invalid integration interval, or time reversal. In firmware mode, imu_substep_times later rejects steps that are not whole multiples of 10 ms, after simulation work has begun.

**Confidence:** confirmed acceptance/source; the zero-step loop was not allowed to run indefinitely. **Exposure:** configuration edits or programmatic callers.

**Suggested fix:** reject nonfinite/nonpositive dt at configuration and function entry; validate firmware sample-grid compatibility and hysteresis thresholds before startup. Validate requested duration and final partial-step policy too.

### A015 — P1 — Attitude integration failure is not checked before committing state

**Location/evidence:** satellite_flight_visualisation.py:406–418 calls solve_ivp; line 438 adopts sol_rot.y[:,-1], and the loop later advances by the complete dt. There is no sol_rot.success or final-time check. Firmware dense sampling at 430 assumes the solution covers every interior timestamp.

**Impact:** if the adaptive solver returns an unsuccessful or short integration, the simulator can credit a complete tick, integrate wheel momentum for that tick, and publish a partially propagated state. Quaternion normalization does not detect incomplete time advancement.

**Confidence:** confirmed missing error-path check; an actual solve_ivp short-step failure was not forced in the mission loop. **Exposure:** pathological states, stringent tolerances, future stiff actuator models.

**Suggested fix:** require successful integration, finite state, nonzero quaternion norm, and a final time matching the intended interval before committing state or sampling dense output. Publish a stopped/error state on failure.

### A016 — P1 — Adaptive ODE trial evaluations mutate persistent control state

**Location/evidence:** dynamics lines 760–763 changes detumbling_complete inside the RHS. _moon_pointing_control_torque at 341–342 latches convergence time; the sun-sweep counterpart does so at 421–422. periodic_gain_sun_pointing.py:169–173 initializes governor state from an RHS attitude.

**Impact:** trial/rejected solver stages can change mode hysteresis or latch a sweep start even when that stage is not part of the accepted trajectory. An event can be recorded at a trial time later than the next accepted state. Results then depend on solver stage sequence and tolerances rather than solely on physical state and the declared control period. Moving only governor progress and wheel-momentum increments outside the RHS does not make all other persistent writes safe.

**Confidence:** confirmed source mechanism; mission-level event divergence not quantified. **Exposure:** threshold crossings and mode transitions.

**Suggested fix:** sample control state transitions at committed control ticks, or use solver event handling with accepted state/time. Make RHS evaluation pure apart from replaceable diagnostics; keep latched modes/references in explicit step state.

### A017 — P1 — Fixed magnetic target and gain artifacts are not bound to active configuration

**Location/evidence:** adcs_target_frame.py:10 hardcodes 2026-10-01T15:00Z; build_target_frame() defaults to that value. periodic_gain_sun_pointing.py:53–57 loads two bare NumPy arrays and derives a period; lines 101–109 build Q_TARGET once. No orbit/inertia/epoch/frame/model fingerprint is checked. The cited design generator is not present among tracked files.

**Impact:** changing epoch, orbit, CAD inertia, or magnetic model does not redesign or reject the schedule. Even without edits, Q_TARGET remains inertially fixed while the Sun moves during the default 100,000 s run. A Floquet claim for one design plant cannot be transferred to arbitrary YAML-selected plants. The historical CLAUDE.md narrative itself describes earlier dipole-field gain generation; this audit did not prove which physics generated the current arrays.

**Confidence:** confirmed missing binding/static target; current gain stability/provenance remains unverified. **Exposure:** legacy magnetic pointing and configuration studies.

**Suggested fix:** store a reproducible design tool and artifact metadata containing configuration/data hashes, frame convention, epoch, phase, boresight, and validation results. Reject mismatched designs or regenerate them; explicitly decide whether the target is fixed or tracks the current Sun.

### A018 — P1 — RW Sun targets use a different celestial frame than sensor/environment truth

**Location/evidence:** sun_vector_eci.py:38–50 computes a low-precision mean-of-date solar direction using date-dependent longitude/obliquity but no transformation to EME2000. SUN_POINTING_RW uses it through sun_pointing_rw_z.py:45 and dynamics line 510. Sensor/environment truth uses the Orekit DE ephemeris in EME2000.

**Impact/reproduction:** at the configured mission epoch the normalized directions differ by 0.365612 degrees. This is a deterministic reference discrepancy rather than sensor noise or settling error, and consumes much of a subdegree pointing budget. The module's arcsecond-level J2000 frame claim is not supported by that comparison. Its topocentric/parallax explanation also uses altitude instead of geocentric spacecraft distance, understating the maximum effect.

**Confidence:** confirmed installed DE-440 comparison; precession is the inferred principal source of the discrepancy. **Exposure:** RW Sun pointing and Sun sweep.

**Suggested fix:** generate onboard Sun reference in an explicitly specified frame, using the same frame contract as attitude knowledge. If preserving a low-cost flight algorithm, perform the required date-to-J2000 transformation and validate it independently across mission epochs. Retain actual onboard-model error as a deliberate tested channel.

### A019 — P1 — Manual control API accepts nonfinite values

**Location/evidence:** app.py:112–124 passes value through to control_states.set_control(); control_states.py:114 stores float(value) without a finite/range check.

**Impact/reproduction:** POSTs with value "nan" and "infinity" both returned HTTP 200 and stored NaN/infinity in yaw. Legacy RW target construction then receives those values, contaminating the target and potentially stopping integration. Unknown labels also return success without changing state; malformed values can produce server errors.

**Confidence:** confirmed Flask test-client reproduction. **Exposure:** manual-control endpoint; operational effect in legacy modes.

**Suggested fix:** require a JSON object, allowlisted label, finite numeric value and declared angular bounds; reject invalid commands atomically with a 4xx response before modifying state.

### A020 — P1 — GPS initialization freezes the navigation position until the first fix

**Location/evidence:** compute_simulated_position.py:79 initializes _t_meas=None; lines 110–111 return unchanged initial position and velocity while that remains None.

**Impact/reproduction:** a navigation holder initialized at [7e6,0,0] with velocity [0,7500,0] returned exactly the same position at t=60 s before a fix. Cold start/outage studies feed increasingly incorrect position to target generation and the reference magnetic model instead of propagating the launch-provided state. This differs from the between-fix dead reckoning implemented after a fix.

**Confidence:** confirmed reproduction. **Exposure:** nonzero GPS cold start, startup outages, absent first fix.

**Suggested fix:** time-tag the initial state at t=0 and propagate it with a declared navigation model until receiver updates arrive. Track uncertainty and age explicitly; make the behavior distinguishable from GPS-disabled truth access.

### A021 — P1 — EGM2008 labels and verification do not identify the loaded gravity model

**Location/evidence:** engine/orekit_runtime.py:140–142 calls the generic GravityFieldFactory.getNormalizedProvider(2,0) and calls that EGM2008 verification. ZonalHarmonicsForce:43 uses the same generic factory. satellite_flight_visualisation.py:1146–1148 labels the model EGM2008. The only tracked potential file is orekit-data/Potential/eigen-6s.gfc, whose header identifies EIGEN-6S.

**Impact/reproduction:** after runtime initialization and a 36x36 request, Orekit's loaded-data names identified eigen-6s.gfc; provider mu=398600441500000 and ae=6378136.46. These are not proof of an EGM2008 run. Comparisons and mission-review claims can therefore name the wrong gravity model while passing startup verification.

**Confidence:** confirmed data/runtime inspection. **Exposure:** active propagation, geoid metadata, documentation and dashboard.

**Suggested fix:** select and verify the intended coefficient reader/file explicitly; record model identity, degree/order, reference radius, mu and hash in run metadata. If EIGEN-6S is intended, label it accurately. Degree 36 is a configured truncation, not intrinsically an error; demonstrate its convergence against the mission error budget.

### A022 — P2 — Geomagnetic secular variation is frozen at the first query of each year

**Location/evidence:** engine/physics/magnetic_field.py:35–46 computes decimal_year but caches the returned transformed model under floor(decimal_year).

**Impact:** later queries in the same year reuse the field transformed to the first query's decimal date. The field can then jump when the year changes. Direct factory calls at 2026.0 and 2026.8 yielded different vectors, demonstrating the temporal information discarded by that cache. A model selected during a later date can also be reused for an earlier query in the same year.

**Confidence:** confirmed cache logic and direct API temporal variation. **Exposure:** long-duration runs and reuse across dates.

**Suggested fix:** cache the base epoch model, then transform/interpolate to query time at a documented resolution. Validate chronological and out-of-order queries against uncached results.

### A023 — P2 — Several YAML environment controls do not control runtime selection

**Location/evidence:** satellite_parameters.py:1231–1232 resolves model_data.orekit_data_path, but engine/orekit_runtime.py:24–30 searches OREKIT_DATA and working-directory candidates and auto-initializes at 177. atmosphere.py:74 hardcodes the space-weather regex. magnetic_field.py:42–45 always tries IGRF then WMM rather than selecting ModelDataParameters.magnetic_model.

**Impact:** editing the advertised data path, weather pattern, or magnetic model can leave the actual data/model unchanged. The loader only verifies that the configured data directory exists, which does not establish that Orekit consumed it. Reproducibility can depend on working directory or environment instead of the recorded YAML.

**Confidence:** confirmed source/dataflow. **Exposure:** alternative datasets and model-selection experiments.

**Suggested fix:** pass one validated environment configuration into runtime initialization before data loading; log the resolved resources and actual fallback choice. Reject unsupported selectors rather than silently ignoring them.

### A024 — P2 — Timezone-aware epochs are accepted but calendar fields are interpreted as UTC

**Location/evidence:** OrbitParameters accepts any non-naive epoch at satellite_parameters.py:75–77. engine_adcs_bridge.py:112–119 constructs an Orekit UTC date from its unnormalized year/hour fields; adcs_target_frame.py:39–46 has the same construction style.

**Impact/reproduction:** 2026-10-01T15:00+05:30 and the equivalent UTC instant produced Orekit dates differing by 19,800 s through the bridge conversion. Python timestamps and other paths that honor tzinfo can disagree with orbital/environment time.

**Confidence:** confirmed reproduction. **Exposure:** offset ISO dates or programmatic provider construction; default Z epoch is unaffected.

**Suggested fix:** normalize to timezone.utc before extracting calendar components, or require and validate zero UTC offset at the public boundary. Test equivalent instant representations.

### A025 — P2 — Legacy wheel momentum uses the final RHS torque and clips away delivered impulse

**Location/evidence:** torque_distribution.py:268 integrates the last store.rw_torques times the full dt; line 279 clips momentum. The bus was integrated using stage-dependent torques through solve_ivp.

**Impact/reproduction:** starting 0.00005 Nms below the limit and applying 0.004 Nm for 0.1 s credited only 0.00005 Nms although the simulated torque impulse was 0.0004 Nms. Also, a final-stage torque is not generally the interval average. Near saturation, bus impulse and rotor bookkeeping diverge. This is a distinct finite-step saturation defect in addition to the missing coupled model in A005.

**Confidence:** confirmed bookkeeping reproduction and integration inspection. **Exposure:** legacy wheel saturation/transients.

**Suggested fix:** integrate rotor momentum with the physical state and stop/limit torque at the actual capacity boundary. If retaining held commands, integrate their exact held impulse and limit the interval before capacity is crossed.

### A026 — P2 — GPS fix status is cleared on nonsampling control ticks

**Location/evidence:** satellite_flight_visualisation.py:268–275 calls register_boundary_no_fix whenever get_raw_data returns None. SimulatedGPS._next_sample_time returns None between receiver boundaries at simulate_gps.py:585–587, as well as for dropouts. compute_simulated_position.py:95 then clears gps_fix.

**Impact:** at a 1 Hz GPS/10 Hz loop, nine ordinary inter-fix ticks can report no fix even when the latest receiver solution is valid. The dashboard confuses “no new packet this tick” with a failed receiver boundary. Wall-clock-throttled publication can emphasize either state depending on phase.

**Confidence:** confirmed scheduling/status dataflow. **Exposure:** default receiver/loop rates.

**Suggested fix:** distinguish no scheduled acquisition from a scheduled acquisition that failed; retain current receiver fix status until a defined timeout or explicit invalid status.

### A027 — P2 — Runtime GPS diagnostic history grows without a bound

**Location/evidence:** simulate_gps.py:441–442 initializes records=[]; lines 545–556 append a dictionary containing truth/measurement arrays on every produced measurement. The main loop constructs the runtime GPS with no history-disable option at satellite_flight_visualisation.py:57.

**Impact:** the default 100,000 s run retains roughly 100,000 per-fix records at 1 Hz, including arrays not needed by live navigation. Multiple/long runs or Monte Carlo workers retain increasingly large histories. No measured total memory number is claimed here.

**Confidence:** confirmed allocation/retention path. **Exposure:** long runs and batch scaling.

**Suggested fix:** provide the same disabled/bounded history option used by the gyro/magnetometer runtime; stream optional audit data to an explicitly managed recorder with bounded buffering.

### A028 — P2 — Starting a second run in one interpreter reuses the previous run's state

**Location/evidence:** module-global orbit provider at engine_adcs_bridge.py:379–386; global sensors/navigation at satellite_flight_visualisation.py:43–109. run_simulation resets t to 0 at 224 but does not recreate these objects. Sensor methods explicitly reject nonincreasing sampling times; wheel/governor state also persists.

**Impact:** invoking run_simulation twice can raise a backward-time sensor error or inherit navigation bias, wheel momentum, and mode/reference state. Multiple spacecraft or Monte Carlo cases cannot be independent by construction. Seeding the generators once is insufficient for repeatable repeated runs.

**Confidence:** confirmed lifecycle inspection; separate-process smoke runs do not test same-process reset.

**Suggested fix:** make a simulation instance own clock, plant, sensors, navigation, controller and transport state. Define reset/close semantics and a configuration/seed bundle per run.

### A029 — P2 — Firmware command sockets listen on every network interface

**Location/evidence:** firmware_sitl_link.py:63,67 binds UDP command/mode sockets to 0.0.0.0. PacketSocket validates layout/finiteness but ignores sender address; pollers also discard the source.

**Impact:** where host networking permits reachability, a sender other than the intended local ACS/ADS can alter torques/mode with correctly shaped packets. Outbound traffic is explicitly loopback, so the receive exposure exceeds that declared local topology. No intrusion or external exploit test was performed.

**Confidence:** confirmed bind/acceptance behavior. **Exposure:** networked SITL workstations and future remote/HIL links.

**Suggested fix:** bind loopback for local SITL, or configure and validate the expected peer/interface. For a remote boundary, add an authenticated/session-aware command contract appropriate to the test setup, including sequencing and freshness.

### A030 — P2 — Telemetry ingress accepts JSON shapes that break other API endpoints

**Location/evidence:** app.py:31–34 accepts any JSON as latest_telemetry. viewer_configuration at 88 assumes a mapping and calls .get.

**Impact/reproduction:** POST /update_telemetry with [] returned 200; GET /api/latest then returned[], and GET /api/viewer/config returned 500 with AttributeError. This can prevent a new viewer from initializing until a good snapshot arrives.

**Confidence:** confirmed Flask test-client reproduction. **Exposure:** split-process/external telemetry ingress.

**Suggested fix:** require a mapping and validate the minimal snapshot schema, timestamps and finite numerical fields before atomically replacing the last good snapshot. Bound request sizes and retain an explicit rejected-ingress counter.

### A031 — P2 — Retained validation adapters cannot import their declared types

**Location/evidence:** engine/validation/orekit_adapter.py:4–9 and comparison_report.py:6 import engine.validation.validation_types. That module is absent from the tracked tree.

**Impact/reproduction:** importing engine.validation.orekit_adapter raised ModuleNotFoundError for validation_types. An engineer trying to use the retained comparison infrastructure gets an import failure despite a passing syntax scan. The ordinary pytest suite does not cover this entry point.

**Confidence:** confirmed import reproduction and AST import scan. **Exposure:** validation tools, not the live launcher.

**Suggested fix:** restore the actual maintained validation contract or retire the broken entry points. Add an import/use check for supported validation commands; do not confuse main.py's separate comparison with this adapter working.

### A032 — P2 — The current regression contract is not green and CI does not enforce it

**Location/evidence:** validation/test_spacecraft_configurations.py:21 expects the aggregate IMU bundle enabled flag to become false when all profiles are off; the loader at satellite_parameters.py:1313–1319 turns individual sensor flags off but leaves the aggregate bundle enabled. The mount failure is separately analyzed in A011. The only tracked workflow, .github/workflows/notify_parent.yml:9–21, sends a parent-repository dispatch; it does not run tests/build/physics checks.

**Impact:** both validation runs ended with 2 failures. The aggregate flag failure is **not evidence that disabled sensors emit readings**: their individual flags are off. It is an unresolved test/API expectation, potentially a stale test. Without a gate, these mismatches and defects such as A001–A004 can be promoted through the parent notification workflow.

**Confidence:** confirmed runs and workflow inspection. **Exposure:** development/release regression process.

**Suggested fix:** decide the aggregate bundle semantics, test observable sensor behavior, and restore a green suite. Gate parent promotion on deterministic numerical invariants, interface contracts, frontend checks and supported-entry-point imports. This finding does not assert that external parent CI is absent; it was not inspected.

### A033 — P2 — Setup deletes the dependency lockfile when installation fails

**Location/evidence:** setup.ps1:763–766 removes node_modules and package-lock.json before retrying npm install. requirements.txt also uses broad version ranges without a resolved environment lock.

**Impact:** a transient installation failure can replace the reviewed JavaScript dependency graph with a newly resolved one. Two clean machines or later Python installs can use different numerical/runtime versions, making results and regressions difficult to reproduce. The lockfile deletion is stronger than merely recommending a fresh installation.

**Confidence:** confirmed source; setup was not executed.

**Suggested fix:** preserve the reviewed lockfile and use a reproducible install command; diagnose transport/cache/package failures independently. Record a resolved Python environment and data hashes for validated simulator releases. No known-CVE claim is made by this audit.

### A034 — P1 — Setup can forcibly stop an unrelated application on port5000

**Location/evidence:** setup.ps1:429–430 enumerates every listener on local port5000 and calls Stop-Process -Force on its owner. Stop-VenvProcesses is invoked at 680, independent of the executable ownership checks earlier in that function.

**Impact:** running setup while another Flask service or development tool owns 5000 can terminate that unrelated process and lose its in-memory work. The comment that setup stops a running simulator is not an ownership check.

**Confidence:** confirmed source; no processes were killed during the audit. **Exposure:** installer reruns on shared development machines.

**Suggested fix:** verify executable path and command identity for the specific owned simulator before termination. Otherwise report the conflict or select another port. Keep process teardown scoped to processes created by the setup invocation.

### A035 — P2 — Firmware mode silently changes the configured sensor experiment

**Location/evidence:** satellite_flight_visualisation.py:209–223 applies hardcoded firmware gyro/board presets and without_fine_sun_sensor_albedo(). firmware_sitl_adapter.py:70–79 forces enable_fine_albedo=False and explains that it avoids a known firmware response to Earth-reflected light.

**Impact:** the default firmware experiment cannot expose the described albedo-triggered failure despite the YAML array having albedo enabled. Operators can mistake a pointing pass for a pass with the requested environment/error channels. The explanatory comment is useful, but it does not make the effective configuration visible or selectable in a run artifact. The alleged flight-firmware defect itself was not independently verified because that firmware source was outside this audit.

**Confidence:** confirmed overrides; external firmware failure claim remains a documented claim. **Exposure:** default firmware-mode sensor fidelity.

**Suggested fix:** name and record effective SITL sensor overrides, expose albedo-on acceptance cases, and separate a workaround demonstration from a flight-realistic regression. Preserve tests for both behaviors.

### A036 — P2 — Replacing a loaded CAD scene does not release its GPU resources

**Location/evidence:** frontend/src/viewer/spacecraft/SpacecraftLoader.js:60 calls modelHolder.clear() when a new model finishes loading. It does not traverse/dispose the previous model's geometry/materials/textures. The engine's final cleanup at SimulationEngine.js:1939–1945 traverses only the then-current scene.

**Impact:** switching model URLs as telemetry/configuration changes can leave buffers/material resources from the removed model allocated. The final scene traversal cannot reach already detached models. This matters for large CAD exports and repeated configuration changes; the single-load browser smoke did not reproduce a measured leak.

**Confidence:** confirmed missing replacement cleanup; growth size unmeasured. **Exposure:** model replacement and long-lived viewer sessions.

**Suggested fix:** dispose the previous owned scene before detaching it, with shared-resource reference handling. Also release stale asynchronous load results and clean up partially initialized viewers on startup failure. Verify renderer resource counts over repeated replacements.

### A037 — P2 — A telemetry snapshot mixes tick-start state with later-stage actuator data

**Location/evidence:** satellite_flight_visualisation.py:436–441 deliberately retains X_rot at tick-start for publication, after integrating to t+dt. Lines 456–482 advance wheel/governor/firmware bookkeeping before publication. Lines 827–829 publish store.angular_acceleration, which dynamics line 1014 last wrote during a later solver stage; store.time is also written inside the RHS at 948.

**Impact:** timestamped attitude/rates can describe t while wheel momentum, actuator diagnostics, and acceleration describe an endpoint or last RHS stage. Correlating torque with rate changes, judging settling, or checking firmware response latency from the dashboard can therefore be off by a control tick. An internally consistent JSON snapshot is not necessarily a temporally consistent measurement.

**Confidence:** confirmed ordering; magnitude depends on transient. **Exposure:** telemetry analysis and timing validation.

**Suggested fix:** publish a committed state snapshot for one epoch, or time-tag channels individually. Integrate and record actual actuator impulse separately from instantaneous commanded/achieved torque.

### A038 — P2 — The repository tracks a machine-local environment and thousands of bytecode files

**Location/evidence:** git ls-files lists 17,573 files under .tools, totaling 886,672,670 bytes, and 5,236 cached-bytecode paths across the tracked tree. .gitignore contains .tools/, __pycache__/ and *.pyc, but ignore rules do not remove already tracked files.

**Impact:** clones and reviews include an architecture/interpreter-specific CAD environment and generated caches. Review coverage and dependency provenance are obscured, repository transfers are larger, and stale compiled artifacts can confuse environment diagnosis. This audit did not establish any secret leak in those files and does not claim they were semantically audited.

**Confidence:** confirmed inventory. **Exposure:** onboarding, reproducibility and repository maintenance.

**Suggested fix:** use a documented reproducible CAD-tool environment and artifact provenance; remove generated environments/caches from future source tracking through a separately reviewed maintenance change. Preserve required license/data artifacts deliberately. No deletion was performed here.

### A039 — P3 — The state-packet constant and documentation describe the old packet

**Location/evidence:** telemetry.py:6–8 describes 13 doubles/104 bytes; PACKET_FORMAT at 20 is <13d. send_state at 25 actually packs <17d,136 bytes.

**Impact:** a downstream implementer using the exported constant or module ICD will build the wrong receiver length even though the current Python sender works. This is particularly costly at a hardware interface where packet length mismatch resembles a transport failure.

**Confidence:** confirmed source and struct sizes. **Exposure:** interface reuse/HIL integration.

**Suggested fix:** make serialization, size assertions and interface documentation use one authoritative versioned packet definition; generate cross-language layout tests from it.

### A040 — P3 — Frontend browser-test instructions point to a nonexistent path

**Location/evidence:** frontend/README.md:58 directs users to scripts/viewer_test_server.py; the actual maintained file is validation/tools/viewer_test_server.py.

**Impact:** the documented regression procedure fails before starting its fixture, making the browser checks harder to run and encouraging testing against a live simulator instead. The audit used the actual isolated fixture path.

**Confidence:** confirmed path inventory. **Exposure:** frontend development/validation.

**Suggested fix:** correct and execute the documented command in documentation validation, keeping the explicit no-flight-command fixture workflow.

### A041 — P3 — Euler conversion documentation states the wrong input units/order

**Location/evidence:** quat2eul.py:24–30 says quaternion_from_euler expects radians, but calls np.radians on each input. cross_b_torque.py:14 advertises [roll,pitch,yaw] in radians and passes it directly to that degree-based [yaw,pitch,roll] helper at 44.

**Impact:** a caller following the documented API gets a rotation scaled by pi/180 again and potentially permuted. Existing slider callers pass degrees, so this is not evidence that the active slider path itself uses radians incorrectly. The legacy magnetic helper also retains inconsistent PD/B-cross sign conventions and should not be treated as validated reusable control code merely because it is importable.

**Confidence:** confirmed documentation/implementation mismatch. **Exposure:** helper reuse and legacy paths.

**Suggested fix:** define and name the unit/order contract explicitly, correct the docstrings, and retire or independently validate unused control helpers. Keep conversion tests independent of the function under test.

## Performance analysis

The measured headless case used the deployed configuration, the existing 0.1 s tick, and legacy SUN_POINTING_RW. Pacing and speed-file polling were disabled in memory; telemetry went to an in-memory sink. No source or YAML was edited. It is a single short profiled run, not a comparative optimization benchmark.

| Ranked measured compute path | Calls / cumulative time | Interpretation and estimated opportunity |
|---|---|---|
| Attitude integration/RHS | 101 solve_ivp calls:1.173 s; 934 RHS calls:1.151 s | About 48% of elapsed profiled wall time, including nested facet/control work. Halving this whole path has a theoretical overall ceiling near 1.32x in this run, not a demonstrated gain. Preserve physical tick semantics when optimizing. |
| Facet evaluation | 1,373 evaluate calls:0.943 s | About 39% of elapsed time, overlapping the first row. Focus first on visibility and repeated frame/vector construction. A hypothetical 2x improvement has an Amdahl ceiling near 1.24x overall for this case. |
| Facet box visibility | 2,746 calls:0.644 s | About 26% of elapsed time, nested within facet evaluation. A hypothetical 2x improvement caps near 1.15x overall. Investigate precomputed geometry/broad-phase rejection and reduce arrays only after fixing frame/cache correctness. |
| Orbit state retrieval | 101 calls:0.671 s | Includes 20 Universe.step calls:0.496 s and 340 coupled-force contributions:0.376 s. These overlap facet work and must not be added to the earlier rows. Correct A009 before treating cached output as a valid optimization. |
| Orbit environmental wrapper | 441 surface_result calls:0.464 s | Includes Java/Python conversion and environmental queries. Reuse valid per-epoch data with explicit attitude/time cache keys, then measure again. |

Elapsed time was 2.435 s for 10 simulated seconds, approximately 4.11 simulated seconds per wall second under instrumentation. There were 101 loop iterations because floating-point t repeatedly incremented by 0.1 remained just below 10; this is a measured scheduling detail, not a long-duration accuracy conclusion. Some profiler output attributed waiting time to threading.wait_for with overlapping elapsed intervals; that was not treated as a removable physics bottleneck or added to compute totals.

A separate provider-only 100-interval probe measured 0.125 ms median,20.489 ms 95th percentile, and 209.962 ms maximum state/attitude-update cost, totaling 0.596 s including initialization effects within the loop. These are host-specific and cache-dependent observations; they do not demonstrate a deadline guarantee. The outlier exceeds a 0.1 s HIL tick, so end-to-end latency distributions and overload behavior require explicit measurement.

No browser FPS improvement is claimed. The browser smoke observed 15 draw calls in one ready frame, showing that batching is operational in that build. It did not measure repeated-load leaks, texture upload stalls, tile-network behavior, or high-refresh GPU frame time. Active React telemetry uses a bounded history and avoids a React state update on every animation frame, which is a sensible design. Browser receipt cadence is 250 ms polling in SimulationEngine.js:156,1363; that is presentation throughput, not the physics step rate or firmware IMU rate.

GPS diagnostic retention in A027 is the clearest unbounded memory path found. No whole-process memory soak or Monte Carlo scaling measurement was performed. Cold JVM/data startup is outside the 10 s run's timing and should be measured separately from sustained throughput.

## Architecture, conventions, and modularity

| Boundary | Actual contract/path | Audit assessment |
|---|---|---|
| Orbit | Python Universe -> JPype -> Java Orekit NumericalPropagator; EME2000 state, ITRF body shape | Useful plugin registration; scalar DOP853 tolerances on equinoctial components need a convergence/error-budget study before precision claims |
| Environment | DE-440 Sun; generic gravity factory; NRLMSISE-00/CSSI; IGRF-first/WMM fallback | Model/data identity must be recorded and corrected; A001/A021–A024 |
| Orbit/attitude coupling | EngineOrbitProvider held/extrapolated attitude -> shared rectangular facet evaluator | Good force/moment reuse, but wrong orientation and stale future ephemeris compromise consistency |
| Attitude plant | Seven-state quaternion/rate solve_ivp, global controller state, wheel momentum external to ODE | Not a complete wheel-coupled spacecraft model; several state writes depend on solver stage order |
| Sensors | Independent seeded acquisition; raw register outputs; decoded SI navigation | Useful separation; configured rates, missing/stale single-chip data and physical mounting need correction |
| Internal estimation | Six-state multiplicative attitude/bias filter; Joseph covariance update and symmetrization; innovation gates | Better than an additive quaternion EKF; no claim of consistency/NEES validation or large-error global convergence from this audit |
| Firmware state | UDP 5002,17 little-endian doubles; body rates converted from rad/s to deg/s | Constant/doc mismatch; external receiver source not present for independent cross-check |
| Firmware sensors | UDP 5010: ID plus GPS/FSS/gyro/mag/star-tracker layouts | Packed sizes have assertions and unit tests; timestamps/sequence/ABI generation are incomplete across the boundary |
| Actuator return | UDP 5104 wheel commands, UDP 5105 mode/dipole/fused quaternion; UDP 5103 wheel telemetry | Fixed packet framing, finite-value adapter validation; missing plant limits, peer checks and independent-channel expiry |
| Viewer | Flask/Waitress, polling HTTP snapshots; React dashboard plus persistent Three.js engine | Bounded latest-only telemetry and cache/ETag support are useful; startup/CAD smoke works; per-model disposal remains incomplete |
| Configuration | Basic YAML plus optional selected advanced mode, loaded mostly at import | Restart-driven by design in current docs; only speed is hot-polled. No general atomic runtime reconfiguration API was found |

Force plugins can register their Orekit counterparts without changing the integration loop, which is real modularity. It does not imply that appending any celestial Body automatically creates ephemeris forces: GravityForce only registers third-body forces in N_BODY mode, using a hardcoded name map. The live bridge selects CENTRAL_BODY and adds only Earth and the spacecraft. New spacecraft identity also needs care: Universe caches propagators by body.name and does not reject duplicate names, so its current two-list API is not a safe arbitrary multi-spacecraft manager. The bridge and most downstream state are singleton/configuration-coupled.

Orekit usage is not confined to engine/: engine_adcs_bridge.py, simulate_gps.py, adcs_target_frame.py, and parts of the outer simulation loop import Java classes. This is a layering observation, not itself a correctness defect. Replacing the propagation/environment backend would currently require changing these callers as well as engine plugins.

The same shared facet model can produce both acceleration and moment, and the loader preserves full CAD inertia tensors rather than forcing principal axes. These are useful choices. Exterior rectangular surfaces with 16 patch samples per sized facet and axis-aligned box blockers remain geometric approximations. No defect is inferred simply from using engineering approximations. Their error needs comparison to a higher-fidelity geometry/reference before claiming measured physical realism. CAD mode selection represents distinct initial configurations; different reported stowed/deployed masses are explicitly documented, and were not mislabeled here as an in-flight mass-loss bug.

The supplied brief describes an EKF-based firmware pipeline and COSMOS/TCP path. This repository proves only the Python-side UDP boundary and an internal MEKF. It cannot establish what the external firmware actually estimates, whether all packet declarations still match its current build, or where COSMOS is in the live topology. Comments quoting C filenames are useful leads, not a substitute for inspecting and testing that C implementation.

## Future readiness

For HIL, the first blockers are physical truth correctness, actuator dynamics, and causal scheduling. A real processor introduces independent clocks, transport jitter, queue limits, late commands, startup synchronization and resets. The current 0.1 s held-command plant with post-step 100 Hz sensor bursts needs an explicit timing contract. Each accepted sample/command should have capture/application time, sequence/session identity, quality and expiry. Real wheel hardware also needs a declared interface for measured speed/torque, current limits, fault behavior and an emergency stop policy owned by the test rig.

For repeatable mission studies, a run must own all mutable state and record the effective YAML after overrides, sensor seeds, dependency versions, gain-artifact identity, environment-data hashes and wall/sim timing settings. Same-seed sensors do not make asynchronous real-time firmware command arrival deterministic. Separate deterministic lockstep studies from wall-clock scheduling tests and label their results accordingly.

For multiple spacecraft/developers, the global orbit provider, controller boxes, telemetry arrays and fixed four-wheel wire conventions will break before the force-plugin interface does. Move ownership into per-vehicle objects and validate unique IDs/counts before adding spacecraft. Keep a narrow environment interface that supplies explicit frames and epochs instead of allowing models to read an ambient mutable clock.

For growth, bounded diagnostics and reproducible dependency/data builds are inexpensive now. They become much harder after Monte Carlo scripts depend on global state or a firmware team relies on an accidental packet layout. Maintain both the simple-model and advanced-CAD baselines as supported tests; do not silently replace flight realism with idealized sensor/actuator workarounds.

## Prioritized roadmap

1. **Repair the physical truth contract first:** A001–A005. Establish signed frame and conservation-law reference tests before tuning controllers. Include nonidentity attitudes, nonzero rotor momentum,180-degree targets and zero/invalid fields.
2. **Make the firmware plant and timing testable:** A006–A009,A011–A016. Add physical actuator bounds, per-channel expiry, accepted-state control scheduling and a timestamped sensor/command contract. Validate actual external C layouts and firmware clocks against an identified build.
3. **Make configuration mean what the operator selected:** A010,A017–A024,A035. Bind offline gains and model resources to the effective configuration; normalize time; reconcile Sun references and tracker mounting; publish actual model/data identities and all sensor overrides.
4. **Close navigation and integration error paths:** A012–A015,A020,A025–A028,A037. Enforce stale/saturated-data policies, check solver completion, time-tag initial navigation, integrate impulses consistently and make per-run state resettable.
5. **Restore a trustworthy validation/release path:** A031–A034,A038–A041. Resolve both regression failures without mistaking aggregate flags for observable behavior; restore missing adapters or retire them; add gating CI; preserve lockfiles and process ownership; document supported commands and wire formats.
6. **Optimize after correctness measurements are stable:** profile visibility/facet costs, eliminate unnecessary environment conversions, bound GPS records, and verify CAD resource disposal. Re-measure throughput, memory and timing tails using declared scenarios rather than extrapolating from a single short run.

Cheap-now/expensive-later items are the frame/units interface contract, timestamped/session-aware packet schema, configuration/data/gain fingerprints, and per-run state ownership. Resolve them before additional hardware adapters or spacecraft variants encode today's implicit assumptions.

## Reproducing selected checks

Run commands from the repository root with the existing virtual environment. The audit used bytecode-disabled Python and the pytest cache plugin disabled. For the suite, it selected the bundled JDK21 in the child process and supplied a disposable pytest base directory, removed afterward. The equivalent test invocation is:

```text
.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp <new temporary path outside repository> validation
cd frontend
node --test tests/telemetry.test.js tests/startupFullscreen.test.js
node node_modules/vite/bin/vite.js build --configLoader native --outDir <new temporary path outside repository> --emptyOutDir
```

Use genuinely new temporary paths and remove them afterward; do not point the empty-output option at existing work. These are reproduction instructions, not changes made to project scripts. The following Python can be supplied on standard input to the virtual-environment interpreter; it changes JAVA_HOME only in its own process and opens no firmware sockets:

```python
import os
import jdk4py
os.environ['JAVA_HOME'] = str(jdk4py.JAVA_HOME)
import numpy as np
import engine.orekit_runtime
from org.orekit.models.earth import GeoMagneticFieldFactory
from org.orekit.data import DataContext
from org.orekit.forces.gravity.potential import GravityFieldFactory
from kinematic_robustness_pointing import kinematic_robustness_pointing_quaternion
from MTR_allocator import torque_to_dipole
from compute_simulated_position import GpsNav
from compute_simulated_attitude import ImuNav, DecodedVector

model = GeoMagneticFieldFactory.getWMM(2026.0)
for altitude_m in (500.0, 500000.0):
    print(altitude_m, model.calculateField(.5, 1., altitude_m).getFieldVector().getNorm())
GravityFieldFactory.getNormalizedProvider(36, 36)
print(DataContext.getDefault().getDataProvidersManager().getLoadedDataNames())
with np.errstate(invalid='ignore', divide='ignore'):
    print(kinematic_robustness_pointing_quaternion([7e6,0,0], [0,7500,0], 0))
try:
    moment, torque = torque_to_dipole(np.zeros(3), np.zeros(3))
except ValueError as error:
    print(type(error).__name__, str(error))
nav = GpsNav([7e6,0,0], [0,7500,0])
print('Unfixed navigation at t=60:', nav.extrapolate(60)[0])
imu = ImuNav(fusion_max_age_s=.5)
imu.update(0, DecodedVector(0,0,True,False,omega_body_rad_s=np.array([0.,0.,.01])),
           DecodedVector(0,0,True,False,magnetic_field_body_t=np.array([1e-5,0.,0.])))
imu.estimate(0, None, None)
imu.update(10, None, None)
imu.estimate(10, None, None)
print('Stale validity:', imu.telemetry()['imu_gyro_valid'], imu.telemetry()['imu_mag_valid'])
```

## Rejected conclusions and unverified questions

- **Missing central gravity was not established.** Some comments wrongly imply the harmonics model itself supplies the central term. The actual installed propagator force list contained HolmesFeatherstoneAttractionModel, the coupled surface JProxy, and NewtonianAttraction. The orbit remained near its initial 6878 km radius in the short probe. This report does not turn misleading comments into a false missing-gravity finding.
- **All sensors off does not mean sensors still produce outputs.** The failing aggregate-flag assertion in A032 is an API/test disagreement, not proof of unwanted sensor receipts.
- **No known dependency vulnerability or leaked secret is certified.** A vulnerability database/complete vendored-secret/history scan was not performed. Broad version constraints and tracked environments are reproducibility findings, not evidence of compromise.
- **No external firmware bug is proven from Python comments.** The albedo workaround and mounting constants require cross-repository confirmation against the actual flight/SITL build.
- **No long-term stability or precision approval is given.** There was no multi-orbit covariance consistency study, independent force-model convergence campaign, Monte Carlo recovery envelope, thermal/current wheel characterization, or real-HIL deadline test.
- **No blanket condemnation of engineering approximations.** EIGEN-6S36x36, scalar tolerances, rectangular facets, constant-rate delay transport, simple GPS dead reckoning and synthetic detector statistics need stated error budgets; their mere existence is not a bug. Specific violated contracts above are separately evidenced.

## Audit meta and remaining scope

Initial tracked status was clean. The complete tracked-path inventory contained 19,674 files and about 2.19 GB of file content. Directory totals are given below. Runtime/local ignored dependencies were discoverable but were not mistaken for authored source. The repository has 44 commits reachable across the inspected refs; recent commit subjects and the historical CLAUDE.md narrative were consulted, but historical patches were not comprehensively reviewed.

| Tracked group | Files | Bytes | Coverage character |
|---|---:|---:|---|
| Root files | 56 | 823,835 | Core source reviewed extensively; docs/config/source gaps specified in appendix |
| .github | 1 | 624 | Workflow read |
| .tools | 17,573 | 886,672,670 | Inventory only; bundled CAD environment not semantically reviewed |
| Root __pycache__ | 34 | 624,410 | Inventory only |
| engine | 103 | 362,995 | Core source reviewed; validation modules only partly inspected; caches inventoried |
| frontend | 1,473 | 1,259,285,331 | Selected source review, unit/browser smoke, model headers; most CSS/assets/source unreviewed |
| orekit-data | 352 | 39,725,666 | Resource inventory, selected headers/tails/hashes, runtime consumption; not coefficient-by-coefficient review |
| validation | 82 | 5,242,862 | Suite execution and selected source review; experiments/results not fully reviewed |

Large-data checks computed SHA256 for the fifteen largest Orekit resource files and inspected the headers/tails of text resources among them. That verifies the local bytes observed, **not upstream authenticity**. The four GLBs were read as binary containers, checking glTF magic/version/declared length and parsing JSON metadata. Deployed and stowed containers reported 1025 and 1017 nodes respectively. Geometry/accessor correctness, CAD dimensions/material authenticity, decoder binaries, screenshots, video, textures and result plots were not fully validated. NumPy gain arrays were consumed successfully by the runtime, but their design metadata/physical validity were not recovered.

Selected reproducibility hashes:

| Resource | SHA256 |
|---|---|
| DE-440-ephemerides/lnxp1990.440 | 00a3863ec1ee692d4779a3ba3ad10fca5c90871f5a9c6a5ba4752b8ad8a5df08 |
| Potential/eigen-6s.gfc | 4cfe6e2e0dba6297952d19b5fd43571c7fc152a4ec4625981fb17b189a05d67d |
| CSSI-Space-Weather-Data/SpaceWeather-All-v1.2.txt | 0bdd96cbcf65aa2ad5e3febcf9ac6104ad7f672f4e954fc7079f367efc7b7913 |
| Earth-Orientation-Parameters/IAU-2000/finals2000A.all | 4c54930aeb977c3010a3f04d722eb2e88057749185328049fb6c4adb942f7f04 |

The CSSI resource header says VERSION 1.2 and UPDATED 2026 Jun 04; the tail extends monthly-fit rows into 2096. A long file tail is not evidence that all later dates have observed daily weather. The YAML describes observed/predicted coverage; actual accuracy of those forecasts and upstream EOP/ephemeris provenance were not certified. IGRF failed selection for 2026 in the runtime probe and WMM succeeded. The fallback was observed; it was not assumed from the OrekitIGRF class name.

No installer, package installation, formatter, source fixer, branch, commit, dependency upgrade, hardware command session or production backend was used. Numerical harnesses ran from standard input with bytecode writing disabled. The browser fixture used a private process on a checked-free local port and was terminated after the check. The report exception in the brief authorizes this new Markdown file; it does not authorize repairs, and none were applied.

### Coverage ledger

The following appendix gives conservative explicit source-review ranges and automated-only/unreviewed categories. A range denotes source content inspected, not a proof that every behavior on those lines was exhaustively verified. Where tool output was truncated or coverage uncertain, the file is not counted as fully reviewed. Reading bytes for hashing/parsing does not count as semantic review. All remaining tracked files fall under the inventory groups above; no claim is made that they were read line by line.

F = full displayed text reviewed; P = selected displayed ranges reviewed; A = AST scan only; I = inventory only. Unit-test execution, JSON/YAML parsing and browser runtime coverage are listed separately and do not upgrade a file to F. Full means source review, not exhaustive behavioral proof. The explicitly credited review is a conservative lower bound where earlier output was truncated.

This project-text subset contains **259 files / 39,194 lines**. Credited displayed-text review covers **14,746 distinct lines**, with **81 F / 23 P / 50 A / 105 I** files. This denominator excludes the much larger bundled/data/asset categories, which remain within requested scope and are explicitly uncompleted. It must not be presented as a repository-wide coverage percentage.

| Project text file | Total lines | Review | Credited ranges |
|---|---:|---|---|
| .gitattributes | 1 | F | all |
| .github/workflows/notify_parent.yml | 21 | F | all |
| .gitignore | 28 | F | all |
| CAD_CONFIGURATION.md | 163 | P | 1-65 |
| CLAUDE.md | 386 | P | 200-386 |
| GPS_DIAGRAM_INTEGRATION.md | 49 | I | - |
| MTR_allocator.py | 19 | F | all |
| MTR_parameters_P30xl.py | 32 | F | all |
| README.md | 393 | P | 1-110 |
| Setup.bat | 29 | F | all |
| adcs_target_frame.py | 47 | F | all |
| advanced_satellite_parameters.yaml | 900 | P | 1-110 |
| app.py | 181 | F | all |
| calculate_disturbances.py | 318 | P | 180-318 |
| calculate_satellite_body_torques.py | 103 | F | all |
| compute_simulated_attitude.py | 773 | F | all |
| compute_simulated_position.py | 129 | F | all |
| control_states.py | 136 | F | all |
| cross_b_torque.py | 71 | F | all |
| dashboard_telemetry.py | 57 | F | all |
| engine/__init__.py | 0 | A | - |
| engine/astrodynamics/constants.py | 79 | F | all |
| engine/astrodynamics/orbit_display.py | 21 | F | all |
| engine/astrodynamics/orbit_factory.py | 85 | F | all |
| engine/astrodynamics/orbital_elements.py | 30 | F | all |
| engine/astrodynamics/orbital_math.py | 337 | F | all |
| engine/astrodynamics/state_vector.py | 35 | F | all |
| engine/forces/atmospheric_drag.py | 56 | F | all |
| engine/forces/base_force.py | 24 | F | all |
| engine/forces/coupled_surface_force.py | 62 | F | all |
| engine/forces/force_model.py | 36 | F | all |
| engine/forces/gravity.py | 73 | F | all |
| engine/forces/solar_radiation_pressure.py | 69 | F | all |
| engine/forces/zonal_harmonics.py | 49 | F | all |
| engine/math/vector3.py | 78 | F | all |
| engine/orekit_runtime.py | 177 | F | all |
| engine/physics/atmosphere.py | 134 | F | all |
| engine/physics/body.py | 63 | F | all |
| engine/physics/earth_rotation.py | 35 | F | all |
| engine/physics/integrator.py | 60 | F | all |
| engine/physics/magnetic_field.py | 66 | F | all |
| engine/physics/physical_properties.py | 63 | F | all |
| engine/physics/shadow.py | 59 | F | all |
| engine/physics/sun_ephemeris.py | 41 | F | all |
| engine/physics/universe.py | 251 | F | all |
| engine/simulation/clock.py | 38 | F | all |
| engine/simulation/pacing.py | 56 | F | all |
| engine/validation/comparison_report.py | 364 | P | 1-22 |
| engine/validation/orekit_adapter.py | 418 | P | 1-100 |
| engine/validation/validation_utils.py | 152 | A | - |
| engine_adcs_bridge.py | 386 | F | all |
| firmware_sitl_adapter.py | 176 | F | all |
| firmware_sitl_link.py | 239 | F | all |
| frontend/.gitignore | 6 | I | - |
| frontend/README.md | 77 | F | all |
| frontend/index.html | 19 | I | - |
| frontend/package-lock.json | 1883 | I | - |
| frontend/package.json | 26 | F | all |
| frontend/public/favicon.svg | 15 | I | - |
| frontend/src/App.css | 6 | I | - |
| frontend/src/App.jsx | 61 | F | all |
| frontend/src/assets/assetUrls.js | 13 | I | - |
| frontend/src/components/ActuatorCard/ActuatorCard.css | 6 | I | - |
| frontend/src/components/ActuatorCard/ActuatorCard.jsx | 52 | I | - |
| frontend/src/components/AngularAccelerationCard/AngularAccelerationCard.css | 6 | I | - |
| frontend/src/components/AngularAccelerationCard/AngularAccelerationCard.jsx | 27 | I | - |
| frontend/src/components/AttitudeBeliefCard/AttitudeBeliefCard.css | 24 | I | - |
| frontend/src/components/AttitudeBeliefCard/AttitudeBeliefCard.jsx | 79 | F | all |
| frontend/src/components/AttitudeCard/AttitudeCard.css | 6 | I | - |
| frontend/src/components/AttitudeCard/AttitudeCard.jsx | 71 | I | - |
| frontend/src/components/AttitudeErrorCard/AttitudeErrorCard.css | 7 | I | - |
| frontend/src/components/AttitudeErrorCard/AttitudeErrorCard.jsx | 28 | I | - |
| frontend/src/components/AttitudeTargetCard/AttitudeTargetCard.css | 6 | I | - |
| frontend/src/components/AttitudeTargetCard/AttitudeTargetCard.jsx | 127 | I | - |
| frontend/src/components/DistanceScale/DistanceScale.css | 6 | I | - |
| frontend/src/components/DistanceScale/DistanceScale.jsx | 21 | I | - |
| frontend/src/components/DisturbanceCard/DisturbanceCard.css | 6 | I | - |
| frontend/src/components/DisturbanceCard/DisturbanceCard.jsx | 140 | I | - |
| frontend/src/components/GlassSelect/GlassSelect.css | 5 | I | - |
| frontend/src/components/GlassSelect/GlassSelect.jsx | 103 | I | - |
| frontend/src/components/GpsCard/GpsCard.css | 28 | I | - |
| frontend/src/components/GpsCard/GpsCard.jsx | 156 | I | - |
| frontend/src/components/GyroscopeCard/GyroscopeCard.css | 6 | I | - |
| frontend/src/components/GyroscopeCard/GyroscopeCard.jsx | 125 | I | - |
| frontend/src/components/InstrumentBindings/InstrumentBindings.css | 9 | I | - |
| frontend/src/components/InstrumentBindings/InstrumentBindings.jsx | 225 | P | 25-225 |
| frontend/src/components/LiveChart/LiveChart.css | 9 | I | - |
| frontend/src/components/LiveChart/LiveChart.jsx | 37 | I | - |
| frontend/src/components/LiveChart/drawChart.js | 126 | I | - |
| frontend/src/components/LoadingScreen/LoadingScreen.css | 12 | I | - |
| frontend/src/components/LoadingScreen/LoadingScreen.jsx | 33 | I | - |
| frontend/src/components/MagnetometerCard/MagnetometerCard.css | 6 | I | - |
| frontend/src/components/MagnetometerCard/MagnetometerCard.jsx | 125 | I | - |
| frontend/src/components/MagnetorquersCard/MagnetorquersCard.css | 7 | I | - |
| frontend/src/components/MagnetorquersCard/MagnetorquersCard.jsx | 27 | I | - |
| frontend/src/components/ManualControls/ManualControls.css | 46 | I | - |
| frontend/src/components/ManualControls/ManualControls.jsx | 14 | I | - |
| frontend/src/components/MiniWorld/MiniWorld.css | 8 | I | - |
| frontend/src/components/MiniWorld/MiniWorld.jsx | 12 | I | - |
| frontend/src/components/MissionCard/MissionCard.css | 44 | I | - |
| frontend/src/components/MissionCard/MissionCard.jsx | 11 | I | - |
| frontend/src/components/OrbitalContextCard/OrbitalContextCard.css | 21 | I | - |
| frontend/src/components/OrbitalContextCard/OrbitalContextCard.jsx | 51 | I | - |
| frontend/src/components/OrbitalModelsCard/OrbitalModelsCard.css | 6 | I | - |
| frontend/src/components/OrbitalModelsCard/OrbitalModelsCard.jsx | 32 | I | - |
| frontend/src/components/PointingControls/PointingControls.css | 19 | I | - |
| frontend/src/components/PointingControls/PointingControls.jsx | 21 | I | - |
| frontend/src/components/PositionCard/PositionCard.css | 6 | I | - |
| frontend/src/components/PositionCard/PositionCard.jsx | 101 | I | - |
| frontend/src/components/ReactionWheelsCard/ReactionWheelsCard.css | 6 | I | - |
| frontend/src/components/ReactionWheelsCard/ReactionWheelsCard.jsx | 31 | I | - |
| frontend/src/components/SensorHealthCard/SensorHealthCard.css | 6 | I | - |
| frontend/src/components/SensorHealthCard/SensorHealthCard.jsx | 33 | F | all |
| frontend/src/components/SettingsPanel/SettingsPanel.css | 62 | I | - |
| frontend/src/components/SettingsPanel/SettingsPanel.jsx | 324 | I | - |
| frontend/src/components/SolarPlan/SolarPlan.css | 10 | I | - |
| frontend/src/components/SolarPlan/SolarPlan.jsx | 24 | I | - |
| frontend/src/components/SolarPlan/drawSolarPlan.js | 68 | I | - |
| frontend/src/components/SpacecraftCard/SpacecraftCard.css | 6 | I | - |
| frontend/src/components/SpacecraftCard/SpacecraftCard.jsx | 90 | I | - |
| frontend/src/components/StarTrackerCard/StarTrackerCard.css | 69 | I | - |
| frontend/src/components/StarTrackerCard/StarTrackerCard.jsx | 378 | I | - |
| frontend/src/components/SunSensorsCard/SunSensorsCard.css | 8 | I | - |
| frontend/src/components/SunSensorsCard/SunSensorsCard.jsx | 108 | I | - |
| frontend/src/components/TelemetryBindings/TelemetryBindings.css | 9 | I | - |
| frontend/src/components/TelemetryBindings/TelemetryBindings.jsx | 194 | P | 1-45 |
| frontend/src/components/TelemetryRows/TelemetryRows.css | 18 | I | - |
| frontend/src/components/TelemetryRows/TelemetryRows.jsx | 32 | I | - |
| frontend/src/hooks/useTelemetry.js | 18 | F | all |
| frontend/src/index.css | 183 | I | - |
| frontend/src/layouts/DashboardLayout/DashboardLayout.css | 332 | I | - |
| frontend/src/layouts/DashboardLayout/DashboardLayout.glass.css | 103 | I | - |
| frontend/src/layouts/DashboardLayout/DashboardLayout.jsx | 91 | I | - |
| frontend/src/layouts/DashboardLayout/DashboardLayout.layout.css | 305 | I | - |
| frontend/src/layouts/ViewerLayout/ViewerLayout.css | 149 | I | - |
| frontend/src/layouts/ViewerLayout/ViewerLayout.jsx | 9 | I | - |
| frontend/src/layouts/header/MissionHeader.css | 39 | I | - |
| frontend/src/layouts/header/MissionHeader.jsx | 60 | I | - |
| frontend/src/main.jsx | 10 | F | all |
| frontend/src/pages/overview/OverviewPage.css | 23 | I | - |
| frontend/src/pages/overview/OverviewPage.jsx | 34 | I | - |
| frontend/src/pages/pointing/PointingPage.css | 22 | I | - |
| frontend/src/pages/pointing/PointingPage.jsx | 39 | I | - |
| frontend/src/pages/sensors/SensorsPage.css | 22 | I | - |
| frontend/src/pages/sensors/SensorsPage.jsx | 34 | I | - |
| frontend/src/routes/WorkspacePages.css | 16 | I | - |
| frontend/src/routes/WorkspacePages.jsx | 36 | I | - |
| frontend/src/services/TelemetryFeed.js | 28 | F | all |
| frontend/src/services/dashboardData.js | 82 | F | all |
| frontend/src/services/formatTelemetry.js | 63 | F | all |
| frontend/src/services/lifecycle.js | 58 | F | all |
| frontend/src/services/loadingProgress.js | 9 | F | all |
| frontend/src/services/settingsPanel.js | 93 | F | all |
| frontend/src/services/startupFullscreen.js | 37 | I | - |
| frontend/src/services/telemetryStore.js | 32 | F | all |
| frontend/src/viewer/SimulationEngine.js | 1957 | P | 1-160, 980-1068, 1260-1325, 1490-1710, 1820-1840, 1910-1957 |
| frontend/src/viewer/config.js | 70 | I | - |
| frontend/src/viewer/coordinates.js | 67 | F | all |
| frontend/src/viewer/cosmos/CosmicExplorer.js | 510 | I | - |
| frontend/src/viewer/cosmos/SpaceBackground.js | 143 | I | - |
| frontend/src/viewer/cosmos/referenceCalibration.js | 38 | I | - |
| frontend/src/viewer/cosmos/referenceStarfield.js | 137 | I | - |
| frontend/src/viewer/diagrams/DiagramRenderer.js | 724 | I | - |
| frontend/src/viewer/earth/EarthScene.js | 294 | I | - |
| frontend/src/viewer/earth/aurora.js | 93 | I | - |
| frontend/src/viewer/imagery/ImageryTiles.js | 497 | I | - |
| frontend/src/viewer/spacecraft/SensorMarkers.js | 136 | I | - |
| frontend/src/viewer/spacecraft/SpacecraftLoader.js | 114 | F | all |
| frontend/src/viewer/spacecraft/cadBatch.worker.js | 103 | I | - |
| frontend/src/viewer/spacecraft/cadBatches.js | 197 | I | - |
| frontend/tests/startupFullscreen.test.js | 38 | I | - |
| frontend/tests/telemetry.test.js | 142 | P | 1-35 |
| frontend/tests/viewer.browser.js | 289 | P | 1-70, 260-289 |
| frontend/vite.config.js | 37 | F | all |
| imu_README.md | 176 | I | - |
| kinematic_robustness_pointing.py | 93 | F | all |
| launcher.py | 7 | A | - |
| main.py | 398 | F | all |
| moon_pointing.py | 443 | A | - |
| nadir_pointing.py | 104 | F | all |
| nominal_in_orbit_pointing.py | 71 | F | all |
| periodic_gain_sun_pointing.py | 194 | F | all |
| pointing_client.py | 13 | A | - |
| quat2eul.py | 126 | F | all |
| requirements.txt | 16 | F | all |
| run_simulator.py | 167 | F | all |
| satellite_flight_visualisation.py | 1179 | P | 1-314, 315-500, 560-592, 820-848, 1086-1179 |
| satellite_parameters.py | 1389 | P | 1-242, 1104-1389 |
| satellite_parameters.yaml | 658 | P | 1-430, 449-564, 565-586, 615-658 |
| satellite_params.py | 146 | F | all |
| satellite_rotational_dynamics_var_mag_field.py | 1023 | P | 1-195, 249-665, 681-1023 |
| sensor_link.py | 274 | P | 1-269 |
| setup.ps1 | 934 | P | 1-170, 375-450, 510-629, 630-680, 702-725, 757-772, 800-895 |
| simulate_gps.py | 1076 | P | 377-605, 640-740 |
| simulate_gyroscope.py | 324 | F | all |
| simulate_magnetometer.py | 329 | P | 85-329 |
| simulate_startracker.py | 703 | P | 1-369 |
| simulate_sunsensor.py | 1058 | P | 135-295, 476-580, 610-820 |
| spacecraft_surface_physics.py | 113 | F | all |
| store.py | 28 | F | all |
| sun_pointing_rw.py | 79 | F | all |
| sun_pointing_rw_z.py | 91 | F | all |
| sun_vector_eci.py | 75 | F | all |
| telemetry.py | 33 | F | all |
| telemetry_transport.py | 60 | F | all |
| torque_distribution.py | 314 | F | all |
| validation/DASHBOARD.md | 43 | I | - |
| validation/IMU_SENSOR_NOTES.md | 133 | I | - |
| validation/README.md | 19 | I | - |
| validation/VIEWER_GRAPHICS.md | 15 | I | - |
| validation/__init__.py | 0 | A | - |
| validation/bdot_realistic_detumbling.py | 183 | A | - |
| validation/experiments/handoff_sweep_v2.py | 99 | A | - |
| validation/experiments/max_absorbable_tumble_rate.py | 111 | A | - |
| validation/experiments/r1_load_balanced_alloc.py | 119 | A | - |
| validation/experiments/r1_minimax_alloc.py | 112 | A | - |
| validation/experiments/r1_rate_governed.py | 138 | A | - |
| validation/experiments/r1_realistic_wheel_cap.py | 114 | A | - |
| validation/experiments/r1_short_pause_desat.py | 157 | A | - |
| validation/experiments/r1_staged_hops.py | 203 | A | - |
| validation/experiments/r1_vector_pointing.py | 127 | A | - |
| validation/experiments/reaction_wheel_model.py | 96 | A | - |
| validation/experiments/rg_mtr_best_strategy.py | 169 | A | - |
| validation/experiments/run_real_c_detumbling.py | 241 | A | - |
| validation/experiments/run_real_c_rg_with_desat.py | 153 | A | - |
| validation/experiments/run_real_c_sunpointing_r1.py | 183 | A | - |
| validation/legacy_srp/__init__.py | 1 | A | - |
| validation/legacy_srp/eclipse_model.py | 80 | A | - |
| validation/legacy_srp/solar_radiation_pressure.py | 105 | A | - |
| validation/legacy_srp/solar_surface_properties.py | 80 | A | - |
| validation/legacy_srp/srp_demo.py | 48 | A | - |
| validation/legacy_srp/test_solar_radiation_pressure.py | 121 | A | - |
| validation/mtr_only_sunpointing_accuracy.py | 133 | A | - |
| validation/mtr_rw_detumble_comparison.py | 260 | A | - |
| validation/plot_mtr_detumbling_tipoff.py | 230 | A | - |
| validation/plot_mtr_rw_comparison.py | 30 | A | - |
| validation/plot_rw_sunpointing.py | 99 | A | - |
| validation/plot_saturation_results.py | 44 | A | - |
| validation/python_sim_existing_baseline.py | 139 | A | - |
| validation/real_igrf_field.py | 69 | A | - |
| validation/satellite_footprint.py | 95 | A | - |
| validation/sun_pointing_rw_saturation_analysis.py | 334 | A | - |
| validation/test_dashboard_telemetry.py | 76 | A | - |
| validation/test_firmware_sitl.py | 76 | F | all |
| validation/test_frontend_serving.py | 58 | F | all |
| validation/test_hardware_sensor_outputs.py | 164 | A | - |
| validation/test_pointing_inputs.py | 183 | A | - |
| validation/test_sensor_link.py | 290 | A | - |
| validation/test_sensor_navigation.py | 202 | A | - |
| validation/test_simulated_sensor_models.py | 520 | A | - |
| validation/test_simulation_pacing.py | 60 | A | - |
| validation/test_spacecraft_configurations.py | 171 | P | 1-30 |
| validation/test_startracker.py | 121 | A | - |
| validation/test_surface_visibility.py | 47 | A | - |
| validation/tools/build_cad_configurations.py | 167 | A | - |
| validation/tools/check_orbit_dense.py | 26 | A | - |
| validation/tools/export_satellite_cad.py | 136 | A | - |
| validation/tools/verify_cad_physics.py | 89 | A | - |
| validation/tools/viewer_test_server.py | 45 | F | all |

### Scope not credited as semantic review

All tracked .tools files; all tracked bytecode; all remaining orekit-data resources and the unread contents of inspected large resources; frontend/assets media, textures, SVGs, decoder source/WASM/executables, inventories and reference frames beyond the stated container/metadata checks; validation/results binaries/figures; and non-text root arrays are inventory/data-consumption coverage only. All A/I files above and all lines outside P ranges remain unreviewed semantically. The installed ignored .venv, frontend/node_modules, tools/node and other local dependency/build trees were not exhaustively read; ignored boot/setup logs were not audited for secrets. The local tools/set-display-scaling.ps1 (59 lines) was read and setup was observed to invoke it, but it was not executed. Git history coverage was contextual subjects/narrative, not all patches, deleted files or historical secret scans.

The final report is the only new repository path permitted to remain. Final tracked-diff and untracked-path checks are recorded below after cleanup.

### Final cleanup and repository state

The first pytest run created pytest-9 under the user temporary pytest directory; that exact audit-created directory was removed after resolving and checking containment under the temporary root. The second run used a TemporaryDirectory and cleaned its pytest tree automatically. The temporary Vite build was removed automatically. The browser fixture process was terminated, and port5057 had no remaining audit listener. No standalone repro, profiler dump, screenshot, downloaded package or persistent log was created by the audit.

Final git diff --exit-code returned success with no tracked changes. Git status --short listed exactly the new ADCS_AUDIT_REPORT_2026-10-29.md report. Existing ignored files were not intentionally edited or removed. This status evidence covers repository-tracked content and new visible paths; it is not a full before/after cryptographic snapshot of all ignored dependency files.
