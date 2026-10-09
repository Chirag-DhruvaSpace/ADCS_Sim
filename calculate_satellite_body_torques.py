import satellite_parameters as config
import numpy as np 
import satellite_params as sp 
import quat2eul as q2e


#def control_torque(desired_eular, current_quaternion, omega, r_eci, v_eci):
def control_torque(desired_eular, current_quaternion, omega):

    
    
    ####################
    #Lumos
    # NOTE: w_n was 1.5 rad/s, which demands ~N-scale torque (kp*I ~ 3 Nm/rad) --
    # but M_max=2 A*m^2 against a ~3-4e-5 T field only delivers ~1e-4 Nm max.
    # That mismatch kept the controller permanently saturated (effectively relay
    # control), which is what was driving the cross-axis divergence. w_n below is
    # sized off the actual torque budget (kp <= tau_max/theta_max); re-tune as needed
    # once validated against real orbit-propagated B_eci.
    w_n = config.CONTROL.manual_rw_natural_frequency_rad_s
    zeta = config.CONTROL.manual_rw_damping_ratio

    kp_x =  (1 * sp.sat_Ixx * (w_n**2)) #*1.5
    kd_x =  (2 * sp.sat_Ixx * zeta * w_n)

    kp_y =  (1 * sp.sat_Iyy * (w_n**2)) #*1.5
    kd_y =  2 * sp.sat_Iyy * zeta * w_n

    kp_z =  1 * sp.sat_Izz * (w_n**2) #*1.5
    kd_z =  2 * sp.sat_Izz * zeta * w_n
    #####################
    
    
    '''
    #P30-XL 
    kp_x = 0.485530725
    kd_x = 1.9421229

    kp_y = 0.266730585
    kd_y = 1.06692234

    kp_z = 0.506240975
    kd_z = 2.0249639
    ''' 

    kp = np.array([kp_x, kp_y, kp_z])
    kd = np.array([kd_x, kd_y, kd_z])
    
    desired_quaternion = q2e.quaternion_from_euler(desired_eular[0], desired_eular[1], desired_eular[2])

    #q_desired_lvlh = q2e.quaternion_from_euler(desired_eular[0], desired_eular[1], desired_eular[2])
    #q_lvlh_to_eci = q2e.compute_lvlh_to_eci_quaternion(r_eci, v_eci)
    #desired_quaternion = q2e.quaternion_multiply(q_lvlh_to_eci, q_desired_lvlh)
    
    desired_quaternion = desired_quaternion / np.linalg.norm(desired_quaternion)
    
    q_error = q2e.get_quaternion_error(desired_quaternion, current_quaternion)
    
    '''
    if q_error[0] < 0:
        q_error = -q_error
    '''
    error_vector = q_error[1:4]

    tau_body = (kp * error_vector) - (kd * omega)

    return tau_body



'''
def control_torque(desired_eular, current_quaternion, w_curr):

    q_target = q2e.quaternion_from_euler(desired_eular[0], desired_eular[1], desired_eular[2])
    q_err = q2e.get_quaternion_error(q_target, current_quaternion)
    
    q_vec_err = q_err[1:4]

    wn = 0.5 
    zeta = 1.0 

    Kp = np.array([
    2 * sp.sat_Ixx * wn**2,
    2 * sp.sat_Iyy * wn**2,
    2 * sp.sat_Izz * wn**2
    ])

    Kd = np.array([
    2 * zeta * wn * sp.sat_Ixx,
    2 * zeta * wn * sp.sat_Iyy,
    2 * zeta * wn * sp.sat_Izz
    ])

    torque = -Kp * q_vec_err - Kd * w_curr
    
    return torque
'''






