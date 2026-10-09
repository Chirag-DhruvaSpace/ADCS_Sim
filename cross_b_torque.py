import satellite_parameters as config
import numpy as np 
import satellite_params as sp 
import quat2eul as q2e

def control_torque(desired_eular, current_quaternion, omega, B_body):
    """
    Calculates the magnetically achievable torque using the B-Cross control law
    and enforces physical magnetorquer hardware limits.
    
    Parameters:
    -----------
    desired_eular : array-like (3,)
        Target Euler angles [roll, pitch, yaw] in radians.
    current_quaternion : array-like (4,)
        Current spacecraft quaternion [q0, q1, q2, q3].
    omega : array-like (3,)
        Current angular velocity vector in body frame (rad/s).
    B_body : array-like (3,)
        Local Earth magnetic field vector measured in body frame (Teslas).
        
    Returns:
    --------
    tau_actual : np.ndarray (3,)
        The true physical torque (Nm) that will act on the satellite body.
    """
    
    # 1. Tuning Parameters (PD Gains)
    w_n = config.CONTROL.magnetic_pd_natural_frequency_rad_s
    zeta = config.CONTROL.magnetic_pd_damping_ratio

    kp_x = (1 * sp.sat_Ixx * (w_n**2))
    kd_x = (2 * sp.sat_Ixx * zeta * w_n) 
    kp_y = (1 * sp.sat_Iyy * (w_n**2))
    kd_y = (2 * sp.sat_Iyy * zeta * w_n)  

    kp_z = (1 * sp.sat_Izz * (w_n**2))
    kd_z = (2 * sp.sat_Izz * zeta * w_n) 

    kp = np.array([kp_x, kp_y, kp_z])
    kd = np.array([kd_x, kd_y, kd_z])
    
    # 2. Compute Attitude Error
    desired_quaternion = q2e.quaternion_from_euler(desired_eular[0], desired_eular[1], desired_eular[2])
    desired_quaternion = desired_quaternion / np.linalg.norm(desired_quaternion)
    
    q_error = q2e.get_quaternion_error(desired_quaternion, current_quaternion)
    error_vector = q_error[1:4]

    # 3. Calculate Raw Ideal Desired Torque (Standard PD Law)
    tau_des = (kp * error_vector) - (kd * omega)

    # 4. Apply B-Cross Steering Law to Project Torque into a Dipole Moment
    B_mag_sq = np.dot(B_body, B_body)
    
    # Avoid division by zero if the magnetic field magnitude is negligible
    if B_mag_sq > 1e-12:
        # mu = (tau_des x B) / ||B||^2
        mu = np.cross(tau_des, B_body) / B_mag_sq
    else:
        mu = np.array([0.0, 0.0, 0.0])

    # 5. Enforce Physical Actuator Hardware Limits (Max 2 Am2 per MTR axis)
    # This represents the saturation block of your physical hardware coils
    mu_limited = np.clip(mu, -2.0, 2.0)

    # 6. Calculate the True Physical Torque acting on the spacecraft plant
    # tau_actual = mu_limited x B
    tau_actual = np.cross(mu_limited, B_body)

    return tau_actual