import numpy as np 

r = 6.5                                                #Radius of the Wire (mm) 
V_bus = 5                                              #Volts
N = 1900                                               #No of Turns 
Resistance_per_length = 0.28                           #Ohms per m 
wire_length = 65                                       #m
R = Resistance_per_length * wire_length                #Ohms 
winding_length = 80 # - (3/100 * 80)                                    #mm 
relative_permeability = 20000 

I = V_bus/R                                             #Amperes  
P = I * V_bus                                           #Watts 
core_volume = np.pi * r**2/1000000*150/1000             #m cube
density_hymu = 8747                                     #Kg/m3
core_weight = density_hymu * core_volume * 1000         #grams 
wire_volume = 0.0804/10**6*wire_length                  #m3 
density_copper = 8960                                   #kg/m3 
wire_weight =  wire_volume * density_copper * 1000      #grams

#excitation_dipole_moment = np.pi*r**2*10**-6*N*I  
Nd =  4*(np.log(winding_length/r)-1)/((winding_length/r)**2-4*np.log(winding_length/r))
gain_ratio = (relative_permeability-1)/(1+(relative_permeability-1)*Nd)
#total_dipole_moment = excitation_dipole_moment*(1+gain_ratio)

'''
print(f"Winding Length:{winding_length}\n")
print(f"Excitation Dipole moment: {excitation_dipole_moment}\n")
print(f"Nd : {Nd}\n")
print(f"Gain Ratio :{gain_ratio}\n")
print(f"Total Dipole Moment : {total_dipole_moment}\n")
'''
