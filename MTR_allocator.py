import satellite_params as sp
import numpy as np

def torque_to_dipole(tau, B_body):

    B2 = np.dot(B_body, B_body)

    if B2 < 1e-12:
        return np.zeros(3)

    M = np.cross(B_body, tau) / B2

    # Hardware saturation
    M = np.clip(M, -sp.M_max, sp.M_max)
    
    tau_actual = np.cross(M, B_body)


    return M, tau_actual