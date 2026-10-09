'''

#Max Area Dimensions To be verified 
L = 0.3
W = 0.3
A = L * W
###########################
'''

#''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                                                                                  #P-30 XL 

#Flag to check if Solar Panels are deployed or not  
panels_deployed = 1 

# Solar-radiation-pressure configuration. These are explicit validation
# assumptions until CAD mass/optical data are supplied; they are not hidden in
# the SRP calculator. The facet normal follows this project's body -Z sun
# pointing convention.
from satellite_parameters import DISTURBANCES
ENABLE_SRP = DISTURBANCES.srp_enabled
ENABLE_SRP_TORQUE = DISTURBANCES.srp_torque_enabled
SRP_SPACECRAFT_MASS_KG = 6.0
SRP_REFERENCE_AREA_M2 = 0.3 * 0.3
SRP_REFLECTIVITY_COEFFICIENT = 1.0
SRP_SUN_DISTANCE_M = 149597870700.0

if panels_deployed == 1: 

    #Spacecraft MOI parameters P-30 XL Solar Panels Opened (08-10-2025) 
    sat_Ixx = 1.465  #1.44743131                #Kg m2                                                           
    sat_Iyy = 1.176  #1.1403465                 #Kg m2                                                          
    sat_Izz = 1.244  #1.51558101                #Kg m2 

elif panels_deployed == 0:              

    #Spacecraft MOI parameters P-30 XL Solar Panels Closed  
    sat_Ixx =    1.94212229            #Kg m2                                                           
    sat_Iyy =    1.06692234            #Kg m2                                                          
    sat_Izz =    2.0249639             #Kg m2               


#Angular Velocities during tumbling 
w_x = -5.5 #4.0      #degrees/second
w_y = 7.4 #3.0       #degrees/second  
w_z = 0.0                  #degrees/second

#Initial Position
initial_lat = 12.392822
initial_lon = 77.764449
initial_alt = 6871260 

M_max = 2 

desired_yaw = 0.0
desired_pitch = 0.0 
desired_roll = 0.0 

#'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''

#'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''LUMOS Parameters'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
'''
#Flag to check if Solar Panels are deployed or not  
panels_deployed = 1 

if panels_deployed == 1: 

    #Spacecraft MOI parameters P-30 XL Solar Panels Deployed  
    sat_Ixx =     15.62                 #Kg m2                                                           
    sat_Iyy =     15.11                 #Kg m2                                                          
    sat_Izz =     18.41                 #Kg m2 

elif panels_deployed == 0:              

    #Spacecraft MOI parameters P-30 XL Solar Panels Stowed  
    sat_Ixx =  11.84                      #Kg m2                                                           
    sat_Iyy =  14.63                      #Kg m2                                                          
    sat_Izz =  15.12                      #Kg m2               


#Angular Velocities during tumbling 
w_x = 0.0       #degrees/second
w_y = 0.0       #degrees/second  
w_z = 0.0       #degrees/second

#Initial Position
initial_lat = 12.392822
initial_lon = 77.764449
initial_alt = 6871260 

M_max = 20 

desired_yaw = -18.0
desired_pitch = -30.0 
desired_roll = 8.0 

#'''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''
'''
'''
'''
#Magnetic Torquers Parameters (May be required later for design according to dipole moment)
N_x = 21220
A_x = 7.85e-5     
I_max_x = 0.3 

N_y = 21220
A_y = 7.85e-5
I_max_y = 0.3 

N_z = 50000
A_z = 7.85e-3
I_max_z = 2 



#Maximum Dipole Moments (All the MTRs will have the same Dipole Moment for now)
Mx_max = 2  #2                                            #sp.N_x * sp.A_x * sp.I_max_x
My_max = 2  #2                                            #sp.N_y * sp.A_y * sp.I_max_y
Mz_max = 2  #2                                            #sp.N_z * sp.A_z * sp.I_max_z 
'''

# Compatibility facade: active legacy ADCS modules keep importing this module,
# but the values now come from the authoritative configuration.
import numpy as np
from satellite_parameters import (
    DRAG_AREA_M2,
    DRAG_COEFFICIENT,
    IXX,
    IYY,
    IZZ,
    MASS_KG,
    MTR_MAX_DIPOLE_AM2,
    SRP_AREA_M2,
    SRP_CR,
    initial_body_rates_rad_s,
)

sat_Ixx, sat_Iyy, sat_Izz = IXX, IYY, IZZ
w_x, w_y, w_z = np.degrees(initial_body_rates_rad_s())
M_max = MTR_MAX_DIPOLE_AM2
SRP_SPACECRAFT_MASS_KG = MASS_KG
SRP_REFERENCE_AREA_M2 = SRP_AREA_M2
SRP_REFLECTIVITY_COEFFICIENT = SRP_CR
from satellite_parameters import SPACECRAFT
panels_deployed = int(SPACECRAFT.panels_deployed)
INERTIA_MATRIX = SPACECRAFT.inertia_matrix
