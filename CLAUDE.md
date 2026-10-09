# P-30XL ADCS — Magnetorquer Sun-Pointing Control: Project Context

This document is a complete technical record of an ADCS (Attitude Determination and Control
System) design study for the P-30XL satellite, covering the problem diagnosis, the redesign,
every bug found and fixed, all validation results, and the current state of both project
folders. Written so a new session (human or Claude) can pick up the work without re-deriving
any of it.

## Mission context

- Sun-synchronous orbit, inclination i = 97°, altitude ≈ 500 km.
- Actuation: magnetorquers (MTR) as the primary/only actuator for sun-pointing; a tetrahedral
  4-reaction-wheel array exists in hardware (wedge angle 55°, ~4 mN·m torque/wheel, ~0.04–0.05
  N·m·s momentum capacity/wheel) but is NOT used in the final adopted design (see §4).
- Sun-pointing boresight: **body -Z axis** points at the sun (changed from an earlier body -X
  convention partway through this project — see §9). 2 DOF target (rotation about the sun line
  is not controlled/penalized).
- Real MTR hardware constraints incorporated into validation: dipole-moment quantization step
  of 0.1 A·m², and a 2 Hz (0.5 s) control loop with zero-order hold.

## 1. The core problem

The original control pipeline used a **fixed-gain PD + B-cross magnetorquer allocator**.
Testing showed this can go unstable even while tracking a near-frozen target attitude — not
from bad instantaneous field geometry, but because the closed loop is a genuine **linear
time-periodic (LTP) system**: the magnetic field in the body frame varies periodically over
the orbit (as the vehicle's position and, more importantly, its orientation relative to the
rotating-in-inertial-space field vector change), so a *constant* gain can drive a parametric
resonance — the same mathematical mechanism as a Mathieu equation — even though every
"frozen-instant" LTI snapshot of the system is individually stable.

This was confirmed three independent ways:
1. Closed-form derivation of the B-cross MTR allocator's achievable-torque projection,
   `M = (B × τ_des)/|B|²`, `τ_actual = M × B`, which reduces (via the BAC-CAB identity
   `(A×B)×C = B(A·C) − A(B·C)`) to `τ_actual = P(t)·u` with `P(t) = I − B̂(t)B̂(t)ᵀ` — a
   rank-2, time-varying projection, not a fixed linear map.
2. Floquet multiplier analysis of the discretized closed-loop recursion over one orbital
   period.
3. Full nonlinear nonlinear simulation against the real, orbit-propagated rotating field.

**Conclusion:** the fix is not more PD gain tuning around one operating point. The gain must
be *scheduled against the known, predictable periodic pattern of B(t) over the orbit* — this
is a standard periodic-LQR / Floquet-theory problem (cf. Wisniewski & Blanke's periodic
magnetic-attitude-control literature, Psiaki's work), not a geometric-achievability problem.

## 2. The fix: periodic-gain LQR

Design pipeline (implemented in `periodic_lqr_design.py`):

1. **`build_target_frame()`** — defines the target attitude: a right-handed body frame whose
   -Z axis (originally -X, see §9) points at the sun, with the other two axes completed via
   cross products (free/uncontrolled about the sun line). Returns `C_target` (columns = body
   axes expressed in ECI at the target attitude) and `sun0` (sun unit vector in ECI at epoch).
2. **`dipole_field_eci(r_eci, t)`** — a tilted-dipole approximation of Earth's field using the
   leading IGRF-2020 Gauss coefficients (`G10=-29404.8, G11=-1450.9, H11=4652.5`), rotated by
   GMST. Used as a fast, dependency-free stand-in for the real field.
3. **`real_field_eci(r_eci, t)`** — the "real" field path, via `pymap3d.eci2geodetic` +
   `calculate_eci_position_and_velocity.magnetic_field_eci` (pyIGRF-based). This is what the
   *live* `attitude_slider_control_MTR_Modes` copy of this file actually calls for the design
   (an upgrade made independently of this conversation's earlier dipole-only version). **This
   path is broken in the current sandbox** — see §10.
4. **`sample_B_body_over_orbit(N=60)`** — propagates one orbit (Keplerian + J2 + drag), samples
   B in the body-at-target-attitude frame at N=60 evenly spaced points.
5. **`build_discrete_LTP(N=60)`** — builds the discretized LTP state-space matrices `A_d`,
   `B_d[k]` (state = [3 error angles, 3 body rates], 6-dim) at each of the N sample points.
6. **`solve_periodic_riccati(A_d, B_ds, Q, R, n_periods=150, rel_tol=1e-6)`** — backward
   Riccati recursion cycled over repeated orbital periods until `P_seq[0]` converges (relative
   tolerance, not absolute — absolute tolerance falsely flagged non-convergence at the large
   natural magnitude of P, ~4.79e6; relative tolerance correctly shows convergence in ~6
   periods). Produces the periodic gain sequence `K_seq[k]`, one 3×6 gain matrix per sample
   point, repeating every orbit.
7. **`floquet_check(A_d, B_ds, K_seq)`** — forms the one-period monodromy matrix of the closed
   loop and returns its eigenvalues (Floquet multipliers); stability requires all `|λ| < 1`.

**Final tuned weights:** `qe = 50` (attitude error), `qw = 5` (body rate), `R = 1e10` (control
effort — chosen so peak demanded torque, ~2.4e-5 N·m for representative small-angle states,
sits comfortably under the MTR's real deliverable budget of ~5e-5–9.5e-5 N·m). Swept
`r ∈ {1, 1e3, 1e6, 1e9, 1e10, 1e12}` before settling here; smaller r saturated/oscillated.

`K_seq.npy` and `t_grid.npy` are the design artifacts consumed at runtime by
`periodic_gain_sun_pointing.py`'s `K_of_t(t)` (looks up the nearest sample by orbital phase).

## 3. Large-angle recovery: achievability-gated reference governor

The periodic gain alone is only validated for small errors around the target equilibrium —
it is a *linearized* design. For genuine large-angle recovery (180°, arbitrary attitude at
power-on, etc.) a **SLERP-paced reference governor** sits in front of it:

- Instead of commanding the fixed final target directly, the controller tracks a *moving*
  reference `q_ref = slerp(q_ref_start, Q_TARGET, s)`, where `s` advances from 0 to 1.
- `s` advances at `BASE_RATE_DEG_S * gate / total_angle_deg` per second, where the gate is the
  product of two factors:
  - **`achievability`** = `|τ_actual| / |τ_ideal|` — how much of the *ideal, pre-quantization*
    demanded torque the MTR can actually deliver given the current field geometry. **Must be
    computed from the ideal torque, not the post-quantization delivered torque** — see the
    bug in §8.
  - **`rate_slack`** = `clip(1 − |ω|_deg / RATE_CAP_DEGS, 0, 1)` — throttles pacing if the body
    is still rotating too fast.
- If either factor drops to zero, the reference simply stops advancing until conditions
  improve — this prevents the controller from chasing an unreachable command and diverging or
  oscillating.
- Governor state (`reset_governor`, `mark_inactive`, `step_governor`) is intentionally
  **module-level persistent state** in `periodic_gain_sun_pointing.py`, not something rebuilt
  each control call:
  - `mark_inactive()` must be called whenever the vehicle leaves POINTING mode (e.g. enters
    DETUMBLE or RW mode), so that the next time POINTING is entered, the governor correctly
    restarts its pacing from wherever the vehicle *actually is* at that moment, not from a
    stale start point.
  - `step_governor(dt)` must be called exactly **once per outer simulation time step**, not
    inside the ODE right-hand-side function (which may be evaluated multiple times per step by
    an adaptive integrator) — calling it inside the RHS was found to over-advance the pacing.

### 180° worst-case recovery timing (single-axis tip, standalone test, base rate 0.05°/s)

| Threshold | Time |
|---|---|
| 90° | ~1464 s |
| 40° | ~1829 s |
| 20° | ~2111 s |
| Full settle | ~2600 s (≈45 min) |

Pushing the base pacing rate to 0.2°/s achieved meaningfully faster capture while remaining
stable; this became the adopted default rate used in later live-pipeline work.

### Genuinely compound 3-axis recovery

Repeated with a true diagonal-axis rotation (axis [1,1,1]/√3, 180° total — engaging all three
axes simultaneously, not a single-axis tip decomposed via Euler angles, which hits a ±90°
pitch singularity in the standard 3-2-1 sequence). The same controller, unmodified, handled it
without issue.

### Polar regions

Because the periodic gain is scheduled against the field's variation over a *full orbit*
(which already includes the fast field-direction changes near the poles — sun-synchronous
orbits reach max latitude = 180° − i ≈ 83° here), pointing does **not** break down at high
latitude. The polar field behavior is already part of the periodic design, not a separate
regime requiring special handling.

## 4. Hybrid reaction-wheel + MTR — explored and explicitly abandoned

Investigated whether 1 or 2 wheels (from the 4-wheel tetrahedral array) could replace the
full 4-wheel set for pointing, to save power. Built:
- `hybrid_wheel_mtr_sun_pointing.py` — 1-wheel + MTR hybrid (whichever single wheel needs
  least torque for the along-B torque component, MTR handles the rest).
- `hybrid_2wheel_mtr_sun_pointing.py` — generalized N-wheel minimum-norm allocation.

**Result: both undersized.** Momentum storage (0.04–0.05 N·m·s per wheel) is too small
relative to vehicle inertia (~1.4 kg·m²) to sustain multi-axis correction from large initial
errors — confirmed by direct simulation, not just an analytical estimate.

**Decision (user's, confirmed by these results): abandon wheel-based pointing.** Use the
MTR-only periodic-gain design for pointing; if reaction wheels are used at all, use the full
traditional 4-wheel pointing architecture with MTR reserved for wheel desaturation, not as a
partial substitute for MTR pointing.

## 5. Sun vector, eclipse, sun search

- `sun_vector_eci.py` — implements Vallado's low-precision solar ephemeris:
  `sun_vector_eci(utc_dt)` and `sun_ra_dec_deg`. Validated against known equinox/solstice
  solar declinations. **The sun vector can be computed purely from UTC time — no sun sensor
  needed** for this purpose, and combined with the satellite's ECI position and attitude, this
  is sufficient to compute the body-frame sun-pointing error used throughout this design.
- **Eclipse detection is likewise possible without a sun sensor** — geometrically, from the
  satellite's ECI position relative to Earth's shadow cylinder/cone, using the same computed
  sun vector.
- **A sun-search maneuver is unnecessary** given a known sun vector — the satellite can slew
  directly toward the computed direction rather than scanning for it.

## 6. B-dot detumbling review (original algorithm)

Reviewed the original bang-bang B-dot law in `satellite_rotational_dynamics_fixed_mag_field.py`
(`detumbling_torque(q, w)`): `Ḃ_body ≈ −ω × B_body` (valid when the field is quasi-fixed
relative to the fast tumble rate), `M = −M_max · sign(Ḃ_body)`, `τ = M × B_body`. **The
algorithm itself is standard and correct.** Two real implementation bugs were found:

1. The DETUMBLE branch computed `tau = detumbling_torque(q, omega)` but never assigned the
   `M` / `tau_actual` variables that are referenced unconditionally immediately afterward
   (`store.mtr_dipole[:] = M`, `w_dot = ...(tau_actual − ...)`) — causes an `UnboundLocalError`
   at runtime whenever the DETUMBLE branch is taken.
2. The magnetic field used inside detumbling was a **hardcoded fictitious constant**
   (`B_eci = [3.75e-5, 3.75e-5, 3.75e-5]`), disconnected from the real, time-varying `B_eci`
   parameter passed into `rotational_equations_of_motion(t, y, B_eci)` and used everywhere
   else in the same function.

Both flagged ahead of hardware/firmware implementation — not yet patched in that specific
legacy file at time of writing (the fix described in §7 was applied to the separate, live
`satellite_rotational_dynamics_var_mag_field.py`, which is architecturally different).

## 7. Production bug found and fixed: the "see-saw" effect

Independently observed in the live pipeline: sun-pointing error see-sawing up to 50° on either
side instead of converging. Root-caused by directly inspecting
`satellite_rotational_dynamics_var_mag_field.py`: the live DETUMBLE/RW/SUN_POINTING
mode-switching dynamics called `periodic_gain_sun_pointing.control_torque()` straight against
the fixed final `Q_TARGET`, with **no achievability-gated governor wired in at all**. Since the
vehicle's actual flight initial condition starts at identity attitude (~171° from the old -X
target), this is exactly the large-initial-error failure mode the periodic gain alone was never
validated to handle unassisted.

**Fix**, applied directly to the live files:
- Added the full governor (`reset_governor` / `mark_inactive` / `step_governor` / `slerp`) as
  persistent module state inside `periodic_gain_sun_pointing.py`.
- Added `sun_pointing.mark_inactive()` calls in `satellite_rotational_dynamics_var_mag_field.py`
  inside both the DETUMBLE branch and the RW branch (right after `store.mode = "DETUMBLE"` /
  `"RW"`), so the governor resets correctly on re-entry to pointing mode.
- Added `srd.sun_pointing.step_governor(dt)` in `satellite_flight_visualisation.py`'s per-second
  outer loop (immediately after quaternion renormalization), specifically **not** inside the
  ODE RHS.

**Verified** via `reproduce_seesaw.py` (a faithful standalone reproduction of the live wiring:
real orbit, dipole-field stand-in for the sandbox-broken real IGRF call, exact hysteresis
thresholds, exact `control_torque` call, exact `y0`): went from a wild oscillation
(171° → 7.6° → 39° → 2.4° → 48° → 174° → 12° → 26°…) to smooth, monotonic convergence from
171° to under 1° by t ≈ 6400 s.

## 8. Real hardware constraints: quantized dipole + finite control loop

Tested against actual MTR hardware limits: **0.1 A·m² dipole-moment step size**, **2 Hz control
loop** (0.5 s zero-order hold on the commanded dipole while physics/B(t) evolve continuously
in between). Implemented in `test_hw_realistic.py`.

| Threshold | Continuous baseline | 0.1 A·m² @ 2 Hz |
|---|---|---|
| 90° | 1464 s | 1447 s |
| 40° | 1829 s | 1800 s |
| 20° | 2111 s | 2089 s |

**Result: pointing still works, with negligible timing impact** at these real hardware limits
(a few seconds faster, within simulation noise — not a meaningful degradation).

**Bug found and fixed during this test — important, generalizable lesson for the flight
firmware:** initially computed `achievability` (used to gate the governor, §3) from the
*post-quantization, actually-delivered* torque. This caused a **permanent governor deadlock**:
quantization error alone was enough to make the delivered torque look "unachievable" forever,
so the gate stuck at zero and the vehicle stayed frozen at 180° for the entire test. **Fixed**
by computing achievability from the *pre-quantization ideal* torque (`tau_ideal`, before
`quantize()` is applied) while still applying the quantized `M_used` for the actual physical
torque delivered to the dynamics. **Carry this into the C/flight implementation**: gate any
adaptive-pacing logic on the ideal/commanded torque, not the quantized/delivered one.

## 9. Boresight change: body -X → body -Z

Mission requirement changed mid-project from pointing body **-X** at the sun to pointing body
**-Z**. Changes made (in the live `attitude_slider_control_MTR_Modes` folder):

- `build_target_frame()` in `periodic_lqr_design.py`: `z_ax = -sun0` (was `x_ax = -sun0`),
  with `helper`/`x_ax`/`y_ax` re-derived to complete a right-handed frame with -Z as the fixed
  boresight axis.
- Regenerated `K_seq.npy` / `t_grid.npy` for the new target frame (the LTP linearization is
  taken *around the target attitude*, so the periodic gain schedule is frame-dependent and
  must be regenerated, not just the target quaternion). Regeneration used the dipole-field
  approximation as a stand-in for the live file's real-IGRF call, which fails in this sandbox
  (§10) — **recommend re-running `periodic_lqr_design.py` unmodified once on a machine with
  working `pyIGRF` before final flight sign-off**, to get flight-accurate gains from the real
  field rather than the dipole approximation.
- Re-verified Floquet stability for the new design: `|λ|max ≈ 0.0042` — even more strongly
  damped than the earlier -X design.
- Updated `satellite_flight_visualisation.py`'s telemetry pointing-error axis from
  `[-1, 0, 0]` to `[0, 0, -1]`.

**Timing result**, starting from the actual flight initial condition (identity attitude, zero
body rate — matches `satellite_flight_visualisation.py`'s `y0`), full nonlinear sim including
real orbit propagation, DETUMBLE↔POINTING mode-switching hysteresis, and the governor:

Initial pointing error at t=0: **86.4°** (smaller than the old -X case's 171°, simply because
of the new axis's geometry relative to the sun at this test epoch — not a controller change).

| Threshold | Time |
|---|---|
| ≤ 90° | 1 s |
| ≤ 40° | 620 s |
| ≤ 20° | 1535 s |
| ≤ 5° | 1831 s |
| ≤ 1° | 2077 s |

Verified stable and settled (residual under ~1.3°, no reappearance of oscillation) through
t = 3600 s of continued simulation.

**Important caveat on these numbers — asked and answered directly:** because the tested
initial body rate is exactly zero (matching the real `y0`), the DETUMBLE→POINTING hysteresis
(`DETUMBLE_OFF_DEG_S = 0.5°/s`) is satisfied at t=0, so **the sim enters POINTING mode
immediately and spends no time in DETUMBLE.** These are pure **pointing-only** times. If the
real deployment has nonzero post-separation tumble rates, actual time-to-sun-pointing would be
these numbers **plus** whatever B-dot detumble time is needed to first bring the rate below
0.5°/s (typically fast — order of tens to a few hundred seconds for a few °/s tip-off rate with
this MTR's authority — but not yet explicitly simulated end-to-end with a nonzero initial rate;
flagged as a good follow-up test before flight).

## 10. Known sandbox limitation (environment issue, not a design bug)

`pyIGRF`'s bundled magnetic-coefficient data is broken in this development sandbox — every
call into it throws `IndexError: list index out of range` deep inside
`pyIGRF/loadCoeffs.py`, regardless of the calling code. Confirmed multiple times across this
project, including one attempt to substitute real IGRF-13 coefficients fetched from GitHub
(failed on a column-format mismatch). **This is an environment/packaging issue, not a bug in
this project's own code.** Everywhere the "real field" path (`real_field_eci` /
`magnetic_field_eci`) needed to be exercised in this sandbox, the tilted-dipole approximation
(`dipole_field_eci`) was substituted *only for that specific run*, without permanently altering
the live files (which correctly call the real-field path and should be re-run once on a
machine where `pyIGRF` works to get flight-accurate final numbers).

## Quaternion and geometry conventions (verified empirically — non-obvious, error-prone)

- **Fixed, load-bearing convention used everywhere:** `B_body = C_bi.T @ B_eci`.
- The quaternion→DCM construction formula used throughout this codebase, when you naively
  extract a quaternion from a target rotation matrix `R` via the standard trace formula, gives
  you the quaternion for `R.T`, not `R`. I.e. **extract from `R.T`** to get `C_bi(q) == R` as
  intended. This bit twice in this project (once in `build_target_frame()`'s original -X
  version, once again when adapting the same pattern for a new context) — always verify with
  a direct numerical check (`max abs diff C_bi(q) − R`) after any new target-frame
  construction, don't assume it's right by inspection.
- Composing "apply an extra body-frame rotation on top of an existing target quaternion" uses
  `q_new = quat_mult(q_existing, q_extra)` — existing quaternion on the **left**. The reverse
  order was tried and empirically confirmed wrong (gave a "clocking"-confounded result: e.g. a
  test built to have exactly 5° pointing error gave 0.31° instead).
- 3-2-1 Euler angle decomposition (`quaternion_from_euler`) has a hard ±90° pitch limit
  (arcsin-based) — for constructing test attitudes with compound rotations >90° per axis, use
  a diagonal-axis-angle construction instead (e.g. axis=[1,1,1]/√3, angle=180°).

## File map

### `attitude_slider_control_MTR/` — standalone reference/validation copy (-X boresight; not yet updated to -Z)

- `sun_vector_eci.py` — solar ephemeris (§5).
- `periodic_lqr_design.py` — core periodic-gain design pipeline (§2), dipole field only (no
  real-IGRF upgrade in this copy).
- `test_periodic_gain_mtr_only.py` — small-angle (5°) validation of the periodic gain alone,
  with a `USE_FIXED_GAIN` flag for side-by-side comparison against the old fixed-gain design.
- `periodic_gain_governor_180.py` — periodic gain + governor combined, 180° single-axis
  worst-case recovery test (§3's timing table source).
- `test_3axis_worst_case.py` — genuine compound 3-axis 180° recovery test, reusing
  `periodic_gain_governor_180.py`'s controller unchanged.
- `test_hw_realistic.py` — MTR quantization + 2 Hz loop realism test (§8).
- `hybrid_wheel_mtr_sun_pointing.py`, `hybrid_2wheel_mtr_sun_pointing.py` — abandoned hybrid
  wheel+MTR explorations (§4).
- `satellite_rotational_dynamics_fixed_mag_field.py` — original legacy dynamics file containing
  the reviewed-but-not-yet-patched B-dot detumbling bugs (§6).
- `MTR-Stable.zip` — packaged deliverable (sun vector, periodic LQR design, periodic-gain +
  governor tests, `K_seq.npy`/`t_grid.npy`, README with run instructions and timing table).
  **Predates the -Z change — still -X.**
- `ADCS_MTR_Study_Summary.md` — prior results-only summary document delivered earlier in this
  thread.

### `attitude_slider_control_MTR_Modes/` — live production pipeline (Flask app + 3D visualization; -Z boresight, current)

- `periodic_lqr_design.py` — design pipeline, **upgraded to call `real_field_eci` (real IGRF)**
  instead of the dipole approximation for the actual design (dipole kept in-file "for
  reference/comparison only"); `build_target_frame()` now uses -Z (§9).
- `K_seq.npy` / `t_grid.npy` — current gain schedule for the -Z target, regenerated with the
  dipole-approximation workaround (§9, §10) — **regenerate once more on a machine with working
  pyIGRF before flight sign-off.**
- `periodic_gain_sun_pointing.py` — runtime controller: `K_of_t(t)` gain lookup,
  `Q_TARGET` (derived automatically from `build_target_frame()`, so it stays in sync with
  whatever boresight that function defines), and the full achievability-gated governor
  (`reset_governor`/`mark_inactive`/`step_governor`/`control_torque`) added in §7.
- `satellite_rotational_dynamics_var_mag_field.py` — live mode-switching dynamics
  (DETUMBLE/RW/SUN_POINTING branches, `DETUMBLE_ON_DEG_S=2.0`/`DETUMBLE_OFF_DEG_S=0.5`
  hysteresis), patched with `sun_pointing.mark_inactive()` calls (§7).
- `satellite_flight_visualisation.py` — live per-second simulation loop; `y0` = identity
  attitude, zero rate; patched with `srd.sun_pointing.step_governor(dt)` (§7) and the
  `sun_pointing_axis_body` telemetry axis updated to `[0,0,-1]` (§9).
- `control_states.py` — mode state (`"SUN_POINTING"` / `"RW"`, default `"SUN_POINTING"`).
- `MTR_allocator.py` — B-cross allocator (`torque_to_dipole`), the `P(t)` projection from §1.
- `app.py`, `templates/`, `static/models/*.glb` (~365 MB), `vision_map_base.tif` (35 MB) — the
  Flask 3D-visualization front end; not modified by this work.
- `attitude_slider_control_MTR_Modes.zip` — current packaged deliverable (62 files, ~3.5 MB;
  excludes `__pycache__`, `static/`, `vision_map_base.tif` — all unchanged/large/already in the
  user's possession), rebuilt after the -Z change.
- `ADCS_MTR_Study_Summary.md` — prior results-only summary document (also copied here would be
  reasonable if not already present).

## Open items / recommended next steps

1. Re-run `periodic_lqr_design.py` **unmodified** on a machine with working `pyIGRF` to
   regenerate flight-accurate `K_seq.npy`/`t_grid.npy` against the real field (current ones use
   the dipole approximation as a sandbox workaround).
2. Simulate end-to-end detumble + pointing from a realistic nonzero initial tumble rate (e.g.
   3–5°/s), not just the zero-rate flight `y0` — current timing tables are pointing-only.
3. Patch the two confirmed B-dot bugs (§6) in `satellite_rotational_dynamics_fixed_mag_field.py`
   if that legacy file is still slated for any future use.
4. Decide whether to update `attitude_slider_control_MTR/` (the standalone copy, still -X) and
   `MTR-Stable.zip` to match the live -Z boresight, for consistency across both folders.
5. User has mentioned an eventual C/firmware port — the achievability-vs-quantization lesson
   (§8) and the governor's "gate on ideal, not delivered, torque" principle should be carried
   into that implementation explicitly.
