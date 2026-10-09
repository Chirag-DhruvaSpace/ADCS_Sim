import numpy as np 

"""Selected-spacecraft disturbance budget and live body-frame moments.

Budget density/optics remain estimates; live drag and SRP come from the shared
Orekit environment/facet evaluator. Gravity gradient uses the full COM tensor.
"""
import satellite_params as sp
import satellite_parameters as config
from engine.astrodynamics.constants import EARTH_RADIUS, EARTH_MU

R_Earth = EARTH_RADIUS
mu_earth = EARTH_MU
orbit_altitude = config.ORBIT.altitude_m / 1000
positions = np.array([f.center_of_pressure_body_m for f in config.GEOMETRY.surfaces])
envelope = positions.max(axis=0)-positions.min(axis=0)
L, W = float(envelope.max()), float(np.sort(envelope)[-2])
A = config.SPACECRAFT.drag_reference_area_m2
sat_Ix, sat_Iy, sat_Iz = np.diag(config.SPACECRAFT.inertia_matrix)
Volume = float(np.prod(envelope))
_MAX_ARM = float(np.max(np.linalg.norm(positions-config.GEOMETRY.center_of_mass_body_m,axis=1)))

# --- Shared disturbance parameters -------------------------------------------
# Single source of truth for BOTH the budget functions above/below and the
# live vector torques at the bottom of this file (values identical to the
# literals the original functions used -- they now reference these).
RHO_ATMOS = config.DISTURBANCES.drag_density_kg_m3
CD_DRAG = config.DISTURBANCES.drag_coefficient
DRAG_MOMENT_ARM_M = _MAX_ARM
BR_RESIDUAL_UT = 0.3          # [ASSUMPTION: legacy budget-only residual magnetisation value]
MU_0 = 1.26e-6                # H/m (permeability)

def moi():

    results = {

        "Ixx (kg m2)" : sat_Ix,
        "Iyy (kg m2)" : sat_Iy,
        "Izz (kg m2)" : sat_Iz 
    }
    return results 

def orbit_parameters(): #Enter Orbit altitude in kilometers 
    
    orbit_altitude_meters = orbit_altitude * 1000               #Convert Orbit Altitude from km to m
    orbit_radius = R_Earth + orbit_altitude_meters              #Meters 
    V_circ = np.sqrt(mu_earth/orbit_radius)                     #Circular Veocity m/s
    period = 2 * np.pi * np.sqrt(orbit_radius**3/mu_earth)      #Seconds
    period_minutes = period/60                                  #Period in Minutes 
    mean_motion = 24*60/period_minutes

    #print("Orbit Altitude (m):", orbit_altitude_meters, "\nOrbit Radius (m):", orbit_radius, "\nMu Earth", mu_earth, "\nOrbital Velocit (m/s):", V_circ, "\nPeriod:", period,"\nPeriod (min)", period_minutes, "\nMean Motion", mean_motion)
    #return orbit_altitude_meters, orbit_radius, V_circ, period, period_minutes, mean_motion

    results = {
        "Orbit Altitude (m)": orbit_altitude_meters,
        "Orbit Radius (m)": orbit_radius,
        "Mu Earth (m^3/s^2)": mu_earth,
        "Circular Velocity (m/s)": V_circ,
        "Orbital Period (s)": period,
        "Orbital Period (min)": period_minutes,
        "Mean Motion (rev/day)": mean_motion
    }
    return results

def solar_radiation_pressure_Drag():

    phi = 1367                  #Solar constant (W/m2)
    c = 3.00e+08                #Speed of Light m/s
    q = 1                       #reflectance. 1 for refleting surface 
    srp_centre = _MAX_ARM            #cp-cm, centre of srp from CM (m) 
    sun_angle_of_incidence = 0  #angle of incidence of sun 
    
    srp_force = (phi/c) * A * (1+q) * np.cos(np.radians(sun_angle_of_incidence))
    srp_torque = srp_force * srp_centre 

    #print("\n\nSRP Force:", srp_force, "SRP Torque:", srp_torque)
    #return srp_force, srp_torque

    results = {
        "phi (W/m2)": phi,
        "c (m/s)": c,
        "q": q,
        "srp_centre (m)": srp_centre,
        "sun_angle_of_incidence (deg)": sun_angle_of_incidence,
        "Area A (m2)": A,
        "Length L (m)": L,
        "SRP Force (N)": srp_force,
        "SRP Torque (Nm)": srp_torque
    }
    return results

def atmospheric_drag(): 
    
    rho = RHO_ATMOS                 #Air density kg/m3 (hoisted -- shared with the live drag torque below)
    Cd = CD_DRAG                    #Drag Coefficient (hoisted)  
    V = orbit_parameters()["Circular Velocity (m/s)"]
    moment_Arm = DRAG_MOMENT_ARM_M  #(hoisted -- shared with the live drag torque below)

    Atmosphere_force = 0.5 * rho * Cd * A * V**2 
    Atmosphere_Torque = Atmosphere_force * moment_Arm

    #print("\n\nAtmospheric Force:", Atmosphere_force, "Atmospheric Torque:", Atmosphere_Torque)
    #return Atmosphere_force, Atmosphere_Torque

    results = {
        "rho (kg/m3)": rho,
        "Cd": Cd,
        "Velocity (m/s)": V,
        "Moment Arm (m)": moment_Arm,
        "Atmospheric Force (N)": Atmosphere_force,
        "Atmospheric Torque (Nm)": Atmosphere_Torque
    }
    return results

def magnetic_moment():

    Br = BR_RESIDUAL_UT                                                       #micro Tesla (hoisted)
    V = Volume                                                                #Volume of P-30 (module constant -- sdp.Volume when available)
    u_0 = MU_0                                                                #Permeability, 4*pi*10e-7 (hoisted)
    D = float(np.linalg.norm(config.DISTURBANCES.residual_dipole_Am2))                                                       #Assumed SC residual dipole moment (Am2)
    lambda_lat = 1.6                                                         #Unitless function of lat, 2 at poles, 1 at eq
    M = 7.80e15                                                              #Magnetic const (Tm3)    
    B = lambda_lat*M/(orbit_parameters()["Orbit Radius (m)"] ** 3)           #Magnetic Field Strength (T) 
    
    magnetic_torque = D*B 

    #print("\n\nMagnetic Torque:", magnetic_torque)
    #return magnetic_torque, B

    results = {
        "Br (µT)": Br,
        "Volume (m^3)": V,
        "µ0 (H/m)": u_0,
        "Residual Dipole Moment (Am^2)": D,
        "λ_lat": lambda_lat,
        "Magnetic Const (Tm^3)": M,
        "Magnetic Field Strength (T)": B,
        "Magnetic Torque (Nm)": magnetic_torque
    }
    return results


def gravity_gradient():

    theta = 45                                              #Assumed difference between geometric and principal axis 
    #gg_torque = (3 * mu_earth / (2 * orbit_parameters()["Orbit Radius (m)"]**3)) * np.abs(sat_Iz - sat_Iy) * np.sin(np.radians(2 * theta))

    principal = np.linalg.eigvalsh(config.SPACECRAFT.inertia_matrix)
    gg_torque = (3 * mu_earth / (2 * orbit_parameters()["Orbit Radius (m)"]**3)) * (principal[-1]-principal[0]) * np.sin(np.radians(2 * theta))

    #print("\n\nGravty Gradient Torque:", gg_torque)
    #return gg_torque

    results = {
        "Theta (deg)": theta,
        "Gravity Gradient Torque (Nm)": gg_torque
    }
    return results

net_disturbance_torque = {"Net Disturbance Torque (Nm)" : solar_radiation_pressure_Drag()["SRP Torque (Nm)"] 
                          + atmospheric_drag()["Atmospheric Torque (Nm)"] 
                          + magnetic_moment()["Magnetic Torque (Nm)"] 
                          + gravity_gradient()["Gravity Gradient Torque (Nm)"]}


# ============================================================================
# LIVE SIMULATION INTEGRATION
# ============================================================================
# Called once per RHS evaluation from rotational_equations_of_motion
# (satellite_rotational_dynamics_var_mag_field.py) as:
#
#     tau_dist, parts = cd.disturbance_torque_body(q, r_eci, v_eci, B_eci)
#
# ...and the returned torque is added to the Euler equation in EVERY mode
# (detumble, MTR sun-pointing, all RW modes) -- disturbances are environment
# physics and don't care which actuator is active. Results are mirrored into
# store.disturbance_* for the once-per-outer-step telemetry readout, and the
# worst-case budget above is printed once at sim startup next to the RW
# cluster's real torque authority.

# --- Switches ("the option") --------------------------------------------------
# All ON by default: with these true the disturbances are just part of the
# environment, like drag on the translation side. These are read at CALL time
# (not frozen at import), so flipping one takes effect on the next solver
# step. NOTE: the Flask app (app.py) runs in a SEPARATE process from the
# propagator, so a dashboard toggle would have to go through whatever
# cross-process mechanism control_states.py uses for the mode/slider
# commands -- flipping these constants inside the Flask process will NOT
# reach the simulator.
DISTURBANCES_ENABLED = config.DISTURBANCES.enabled
ENABLE_GRAVITY_GRADIENT = config.DISTURBANCES.gravity_gradient_enabled
ENABLE_RESIDUAL_DIPOLE = config.DISTURBANCES.residual_dipole_enabled
ENABLE_ATMOSPHERIC_DRAG = config.DISTURBANCES.atmospheric_drag_enabled
# SRP enters the Euler equation separately through the shared facet callback.

# --- Live parameters -----------------------------------------------------------
OMEGA_EARTH_RAD_S = 7.2921150e-5   # rad/s -- same value calculate_drag_acceleration.py uses

# Inertia of the SIMULATED body (must match the I the dynamics integrates --
# sp.sat_Ixx/yy/zz -- so the GG torque is consistent with the rigid body it
# perturbs; NOT the design-file inertias, see gravity_gradient_torque_body).
I_BODY = config.SPACECRAFT.inertia_matrix

# Residual dipole: FIXED in the body frame (it's bolted to the spacecraft and
# rotates with it). Magnitude = the same Br*V/mu_0 estimate magnetic_moment()
# above uses; direction defaults to body +X -- change this to wherever your
# real residual dipole actually points. The budget's worst case |m||B| is
# only reached when m is perpendicular to B, so live telemetry will
# typically read somewhat below the budget figure -- which is realistic.
RESIDUAL_DIPOLE_MAGNITUDE_AM2 = magnetic_moment()["Residual Dipole Moment (Am^2)"]
RESIDUAL_DIPOLE_BODY = np.asarray(config.DISTURBANCES.residual_dipole_Am2, dtype=float)

# Center-of-pressure offset from the center of mass, body frame (m). Magnitude
# matches the budget's 0.15 m moment arm; direction defaults to body +X.
DRAG_CP_ARM_BODY = np.asarray(config.DISTURBANCES.center_of_pressure_arm_body_m, dtype=float)


def _dcm_bi_from_q(q):
    """body->ECI DCM from a scalar-first [q0,q1,q2,q3] quaternion -- the exact
    same formula rotational_equations_of_motion uses everywhere, duplicated
    here so this module is self-contained (importing the dynamics from here
    would create a circular import). Normalises defensively, since the ODE
    state's quaternion can drift slightly off unit between RK stages."""
    q = np.asarray(q, dtype=float).reshape(4)
    q = q / np.linalg.norm(q)
    q0, q1, q2, q3 = q
    return np.array([
        [1 - 2*(q2**2 + q3**2),     2*(q1*q2 + q0*q3),     2*(q1*q3 - q0*q2)],
        [2*(q1*q2 - q0*q3),         1 - 2*(q1**2 + q3**2), 2*(q2*q3 + q0*q1)],
        [2*(q1*q3 + q0*q2),         2*(q2*q3 - q0*q1),     1 - 2*(q1**2 + q2**2)]
    ])   # v_eci = C_bi @ v_body


def gravity_gradient_torque_body(q, r_eci):
    """Live gravity-gradient torque, body frame (N*m):

        tau = (3*mu/r^3) * (u x I u)

    with u = local vertical (unit vector from Earth's center to the
    spacecraft) expressed in the BODY frame. This is the standard textbook
    vector form (Wertz / Wie) -- and the budget function gravity_gradient()
    above is exactly this physics reduced to a worst-case scalar: tilt the
    body 45deg about the worst axis and you get (3*mu/2r^3)|Iz-Iy|*sin(90deg),
    his number. (The sign of u doesn't matter: (-u) x I(-u) = u x I u.)

    Uses I_BODY built from satellite_params -- the SAME inertia the dynamics
    integrates -- so the disturbance is consistent with the body it perturbs.
    The budget's hardcoded 0.7157/0.3981 come from the design file; if those
    differ from sp's values, budget and live will disagree -- worth
    reconciling the two parameter sets at some point.
    """
    r_eci = np.asarray(r_eci, dtype=float)
    r_mag = np.linalg.norm(r_eci)
    if r_mag == 0.0:
        return np.zeros(3)
    C_bi = _dcm_bi_from_q(q)
    u_body = C_bi.T @ (r_eci / r_mag)          # local vertical, body frame
    return (3.0 * mu_earth / r_mag**3) * np.cross(u_body, I_BODY @ u_body)


def residual_dipole_torque_body(q, B_eci):
    """Live residual magnetic-dipole torque, body frame (N*m): tau = m x B.

    B is the SAME IGRF B_eci the dynamics already receives (frozen at
    outer-step resolution, same as every other B consumer in this sim --
    detumbling, MTR sun-pointing), converted to body via C_bi.T. Because m is
    fixed in the body frame while B sweeps through the body frame as the
    orbit/attitude evolve, this torque is near-zero-mean over an orbit --
    realistic behaviour, not a constant bias.
    """
    if B_eci is None:
        return np.zeros(3)
    C_bi = _dcm_bi_from_q(q)
    B_body = C_bi.T @ np.asarray(B_eci, dtype=float)
    return np.cross(RESIDUAL_DIPOLE_BODY, B_body)      # tau = m x B


def atmospheric_drag_torque_body(surface_result):
    """Return the shared facet drag moment; no independent density model."""
    return np.asarray(surface_result.drag_torque_body_nm, dtype=float)


def disturbance_torque_body(q, r_eci, v_eci, B_eci, *, drag_torque_body=None):
    """Total live environmental disturbance torque, body frame.

    Returns (tau_net, parts) where parts is a dict with keys
    "gravity_gradient", "residual_dipole", "atmospheric_drag" (each a 3-vector
    in N*m, zeros when that source is switched off).

    PURE function of its arguments: nothing is written, no state is advanced,
    so it is safe to call from inside solve_ivp's right-hand-side no matter
    how many times the integrator evaluates it per real step (unlike the
    wheel-momentum integration, which must stay once-per-outer-step). All
    switches are read at call time, so toggling them takes effect on the next
    solver step.
    """
    parts = {
        "gravity_gradient": np.zeros(3),
        "residual_dipole": np.zeros(3),
        "atmospheric_drag": np.zeros(3),
    }
    if not DISTURBANCES_ENABLED:
        return np.zeros(3), parts

    if ENABLE_GRAVITY_GRADIENT:
        parts["gravity_gradient"] = gravity_gradient_torque_body(q, r_eci)
    if ENABLE_RESIDUAL_DIPOLE:
        parts["residual_dipole"] = residual_dipole_torque_body(q, B_eci)
    if ENABLE_ATMOSPHERIC_DRAG:
        if drag_torque_body is None:
            # Runtime must supply the same NRLMSISE/facet result as orbit drag.
            # The constant-density legacy budget is not flight dynamics.
            raise ValueError('Live drag torque requires the shared orbit environment result')
        parts["atmospheric_drag"] = np.asarray(drag_torque_body, dtype=float)

    tau_net = parts["gravity_gradient"] + parts["residual_dipole"] + parts["atmospheric_drag"]
    return tau_net, parts
