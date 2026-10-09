"""
bdot_realistic_detumbling.py

Re-checks how long real B-dot (bdotCalcTorq(), verbatim real C function via
fw_mm_step) takes to bring a 7deg/s tumble down to 0.7deg/s -- this time
with three things every earlier test in this session simplified away:

  1. A REAL, ROTATING magnetic field instead of a fixed direction. Orbit is
     propagated from this repo's own orbit_parameters.py (500km altitude,
     97deg inclination, near-circular) via calculate_eci_position_and_
     velocity.py's convert_orbit_params_to_ECI(). The field itself uses a
     tilted-dipole model (NOT pyIGRF -- that package is still broken in
     this environment, missing its coefficient file) calibrated to the
     same ~3e-5T equatorial magnitude used throughout this session, tilted
     11.5deg from Earth's spin axis and rotating with it -- so the field
     genuinely sweeps through the body frame from both orbital motion AND
     Earth's rotation, unlike the fixed-direction simplification used
     everywhere else this session.
  2. Simulated sensor noise on BOTH inputs bdotCalcTorq() actually reads:
     magnetometer (quantized to the real ICM20948 0.15uT LSB, plus
     Gaussian noise + a small fixed bias -- representative consumer-MEMS
     magnitudes, NOT verified datasheet numbers for this specific part)
     and gyro (small representative white noise + bias -- same caveat,
     ADIS16545's exact noise spec wasn't looked up here). The CONTROL LAW
     sees the noisy values; the TRUE values drive the actual physics.
  3. Gravity-gradient disturbance torque (the dominant real environmental
     torque at this altitude/inertia -- standard formula, not an estimate)
     applied to the true dynamics throughout, on top of the real MTR
     torque. Drag and solar-radiation-pressure are NOT included (would need
     additional unmodeled assumptions about atmospheric density and
     surface optical properties this repo doesn't have established
     figures for).

Runs N random-seeded trials (noise is stochastic) and reports the spread,
not just one number.
"""
import sys
import types
import ctypes
import numpy as np

# pyIGRF is broken in this environment (missing its coefficient data file,
# igrf14coeffs.txt) and fails at IMPORT time, not call time -- stub it out
# since this script uses its own tilted-dipole model instead and never
# actually calls igrf_value(). Same workaround used earlier this session.
_pyigrf_stub = types.ModuleType("pyIGRF")
_pyigrf_stub.igrf_value = lambda *a, **kw: (0, 0, 0, 0, 0, 0, 0)
sys.modules["pyIGRF"] = _pyigrf_stub

import orbit_parameters as op
import environment_parameters as ep
from calculate_eci_position_and_velocity import convert_orbit_params_to_ECI
import run_real_c_detumbling as mm

RE = ep.Re
MU = ep.mu
B0_EQUATORIAL_T = 3.0e-5          # same magnitude used throughout this session
DIPOLE_TILT_DEG = 11.5            # real Earth dipole tilt from spin axis
EARTH_ROT_RATE = ep.omega_e       # rad/s

MAG_LSB_T = 0.15e-6               # ICM20948_MAG_SCALE, real (0.15uT/LSB)
MAG_NOISE_STD_T = 0.8e-6          # representative MEMS noise floor -- NOT a verified datasheet number
MAG_BIAS_STD_T = 1.5e-6           # representative residual calibration bias -- same caveat

GYRO_NOISE_STD_DEG_S = 0.03       # representative -- ADIS16545's real spec wasn't looked up for this test
GYRO_BIAS_STD_DEG_S = 0.02        # representative, same caveat

TUMBLE_RATE_DEG_S = 7.0
EXIT_THRESH_DEG_S = 0.7
REFERENCE_THRESH_DEG_S = 2.0
T_FINAL = 6000.0
DT = mm.DT


def mean_motion():
    return np.sqrt(MU / op.a**3)


def dipole_axis_eci(t):
    tilt = np.radians(DIPOLE_TILT_DEG)
    gmst = EARTH_ROT_RATE * t   # arbitrary reference epoch (GMST0=0) -- representative rotation, not tied to a real calendar date
    m_ecef = np.array([np.sin(tilt), 0.0, np.cos(tilt)])
    c, s = np.cos(gmst), np.sin(gmst)
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    return Rz @ m_ecef


def b_field_eci(r_eci, t):
    r = np.linalg.norm(r_eci)
    r_hat = r_eci / r
    m_hat = dipole_axis_eci(t)
    return (B0_EQUATORIAL_T * RE**3 / r**3) * (3*np.dot(m_hat, r_hat)*r_hat - m_hat)


def gravity_gradient_torque_body(Cbi, r_eci, I_diag):
    r = np.linalg.norm(r_eci)
    nadir_eci = -r_eci / r
    o3_body = Cbi.T @ nadir_eci
    return (3*MU/r**3) * np.cross(o3_body, I_diag*o3_body)


def run_trial(rng, t_final=T_FINAL):
    mm.fw.fw_init_config()
    n = mean_motion()
    e, i_deg, Omega_deg = op.e, op.i, op.Omega

    q = np.array([1.0, 0.0, 0.0, 0.0])
    omega = np.radians(TUMBLE_RATE_DEG_S) * np.array([1, 1, 1]) / np.sqrt(3)
    h = np.zeros(4)

    mag_bias = rng.normal(0, MAG_BIAS_STD_T, 3)
    gyro_bias_deg_s = rng.normal(0, GYRO_BIAS_STD_DEG_S, 3)

    n_steps = int(t_final/DT)
    t_exit = None
    t_reference = None

    for k in range(n_steps+1):
        t = k*DT
        w_deg = np.degrees(omega)
        if t_reference is None and np.all(np.abs(w_deg) < REFERENCE_THRESH_DEG_S):
            t_reference = t
        if t_exit is None and np.all(np.abs(w_deg) < EXIT_THRESH_DEG_S):
            t_exit = t
            break
        if k == n_steps:
            break

        M = n * t
        nu_deg = np.degrees(M + 2*e*np.sin(M))   # first-order equation-of-center correction
        r_eci, _ = convert_orbit_params_to_ECI(op.a, e, i_deg, Omega_deg, 0.0, nu_deg, MU)

        B_true_eci = b_field_eci(r_eci, t)
        Cbi = mm.C_bi(q)
        B_true_body = Cbi.T @ B_true_eci

        B_meas_T = B_true_body + mag_bias + rng.normal(0, MAG_NOISE_STD_T, 3)
        B_meas_T = np.round(B_meas_T / MAG_LSB_T) * MAG_LSB_T
        omega_meas_deg_s = w_deg + gyro_bias_deg_s + rng.normal(0, GYRO_NOISE_STD_DEG_S, 3)

        dipole_out = mm.c_arr([0.0, 0.0, 0.0])
        mm.fw.fw_mm_step(mm.c_arr(list(omega_meas_deg_s)), mm.c_arr(list(B_meas_T*1e6)), dipole_out)
        dipole = np.array(dipole_out)
        tau_mtr = np.cross(dipole, B_true_body)   # actuator acts on the TRUE field, not the noisy reading

        tau_gg = gravity_gradient_torque_body(Cbi, r_eci, mm.PLATFORM_MOI)
        tau_ext = tau_mtr + tau_gg

        q, omega, h = mm.rk4_gyrostat(q, omega, h, tau_ext, np.zeros(4), DT)

    return t_exit, t_reference


if __name__ == "__main__":
    print(f"Orbit: {op.altitude:.1f}km altitude, i={op.i}deg, period={2*np.pi/mean_motion()/60:.1f}min")
    print(f"Dipole field: {B0_EQUATORIAL_T*1e6:.1f}uT equatorial-surface-equivalent, {DIPOLE_TILT_DEG}deg tilt, rotating with Earth")
    print(f"Magnetometer noise: {MAG_NOISE_STD_T*1e6:.2f}uT std + {MAG_BIAS_STD_T*1e6:.2f}uT bias std (representative, not datasheet-verified)")
    print(f"Gyro noise: {GYRO_NOISE_STD_DEG_S:.3f}deg/s std + {GYRO_BIAS_STD_DEG_S:.3f}deg/s bias std (representative, not datasheet-verified)")
    print(f"Gravity-gradient disturbance: included (standard formula, stowed CAD-verified inertia)\n")

    N_TRIALS = 15
    rng_master = np.random.default_rng(20260807)
    results_exit = []
    results_ref = []
    for trial in range(N_TRIALS):
        rng = np.random.default_rng(rng_master.integers(0, 2**31))
        t_exit, t_ref = run_trial(rng)
        results_exit.append(t_exit)
        results_ref.append(t_ref)
        print(f"  trial {trial+1:2d}: <2.0deg/s at {t_ref if t_ref is None else f'{t_ref:.1f}s ({t_ref/60:.2f}min)'}, "
              f"<0.7deg/s at {t_exit if t_exit is None else f'{t_exit:.1f}s ({t_exit/60:.2f}min)'}")

    valid_exit = [t for t in results_exit if t is not None]
    valid_ref = [t for t in results_ref if t is not None]
    print(f"\n=== Summary over {N_TRIALS} noisy trials ===")
    if valid_ref:
        print(f"<2.0deg/s: mean={np.mean(valid_ref)/60:.2f}min, min={np.min(valid_ref)/60:.2f}min, "
              f"max={np.max(valid_ref)/60:.2f}min, reached in {len(valid_ref)}/{N_TRIALS} trials")
    if valid_exit:
        print(f"<0.7deg/s: mean={np.mean(valid_exit)/60:.2f}min, min={np.min(valid_exit)/60:.2f}min, "
              f"max={np.max(valid_exit)/60:.2f}min, reached in {len(valid_exit)}/{N_TRIALS} trials")
    else:
        print(f"<0.7deg/s: NEVER reached in any of {N_TRIALS} trials within {T_FINAL:.0f}s")
