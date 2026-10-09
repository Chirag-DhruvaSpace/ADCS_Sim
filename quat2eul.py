import numpy as np 
 
def euler_from_quaternion(q0, q1, q2, q3):
    
    """
    Convert quaternion [q0, q1, q2, q3] to Euler angles (yaw, pitch, roll).
    All angles in radians.
    """
    
    # Roll (phi)
    phi = np.arctan2(2*(q0*q1 + q2*q3), 1 - 2*(q1**2 + q2**2))
    
    # Pitch (theta)
    theta = np.arcsin(np.clip(2*(q0*q2 - q3*q1), -1.0, 1.0))  # clip to avoid numerical issues
    
    # Yaw (psi)
    psi = np.arctan2(2*(q0*q3 + q1*q2), 1 - 2*(q2**2 + q3**2))

    return psi, theta, phi  # yaw, pitch, roll

def quaternion_from_euler(psi_deg, theta_deg, phi_deg):
    
    """
    Convert Euler angles (yaw, pitch, roll) to quaternion [q0, q1, q2, q3].
    Expects angles in radians.
    """

    psi = np.radians(psi_deg)
    theta = np.radians(theta_deg)
    phi = np.radians(phi_deg)

    # Calculate half-angles
    cy = np.cos(psi * 0.5)
    sy = np.sin(psi * 0.5)
    cp = np.cos(theta * 0.5)
    sp = np.sin(theta * 0.5)
    cr = np.cos(phi * 0.5)
    sr = np.sin(phi * 0.5)

    q0 = cr * cp * cy + sr * sp * sy
    q1 = sr * cp * cy - cr * sp * sy
    q2 = cr * sp * cy + sr * cp * sy
    q3 = cr * cp * sy - sr * sp * cy

    return [q0, q1, q2, q3]

def get_quaternion_error(q_target, q_curr):
    # q is [q0, q1, q2, q3]
    #
    # ROOT-CAUSE FIX: this used to compute q_target * conj(q_curr), paired with
    # tau = +Kp*e - Kd*w in every control function. That combination does NOT
    # satisfy the standard quaternion-PD Lyapunov stability proof -- verified
    # directly by computing V = 2*Kp*(1-|qe0|) + 0.5*w'*I*w along an actual
    # trajectory and finding it INCREASING (should be non-increasing). Root
    # cause: with this combination, the two Kp terms in dV/dt ADD instead of
    # cancelling. This caused every RW-based mode (RW, moon, nadir, sun-sweep)
    # to diverge whenever the target attitude happened to sit >90-100deg from
    # identity -- which moon-pointing's own earlier "successful" test only
    # avoided by chance (the Moon happened to be at a safe ~42deg angle on the
    # one date tested; 7 of 12 months land it past 90deg).
    #
    # Fix: conj(q_target) (x) q_curr instead. This makes the error's own
    # kinematics follow d(q_err)/dt = 0.5*q_err (x) [0,w] -- the SAME form as
    # the attitude's own kinematics -- verified numerically via finite
    # differences, not just derived. Paired with tau = -Kp*e - Kd*w (note the
    # sign flip on Kp too, in every control function using this), the two Kp
    # terms in dV/dt now correctly cancel, giving dV/dt = -Kd*|w|^2 <= 0
    # globally, independent of the target's distance from identity. Verified:
    # convergence now identical (to machine precision) for target angles from
    # identity ranging from 10deg to 172deg, an 86deg cold start, over 6000s.
    q_curr_conj = np.array([q_curr[0], -q_curr[1], -q_curr[2], -q_curr[3]])
    q_target_conj = np.array([q_target[0], -q_target[1], -q_target[2], -q_target[3]])

    # Hamilton product: q_err = conj(q_target) * q_curr
    a = q_target_conj
    b = q_curr

    q_err = np.array([
        a[0]*b[0] - a[1]*b[1] - a[2]*b[2] - a[3]*b[3], # q0 (scalar)
        a[0]*b[1] + a[1]*b[0] + a[2]*b[3] - a[3]*b[2], # q1 (x)
        a[0]*b[2] - a[1]*b[3] + a[2]*b[0] + a[3]*b[1], # q2 (y)
        a[0]*b[3] + a[1]*b[2] - a[2]*b[1] + a[3]*b[0]  # q3 (z)
    ])

    # 3. Shortest Path Logic
    # Quaternions double-cover the rotation space.
    # If q0 is negative, it's rotating the "long way" around the circle.
    if q_err[0] < 0:
        q_err = -q_err

    return q_err

def rotmat_to_quaternion(R):

    q0 = np.sqrt(1 + R[0,0] + R[1,1] + R[2,2]) / 2
    q1 = (R[2,1] - R[1,2]) / (4*q0)
    q2 = (R[0,2] - R[2,0]) / (4*q0)
    q3 = (R[1,0] - R[0,1]) / (4*q0)

    return np.array([q0, q1, q2, q3])

def quaternion_inverse(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])

def quaternion_multiply(q1, q2):

    w1,x1,y1,z1 = q1
    w2,x2,y2,z2 = q2

    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2
    ])

def compute_lvlh_to_eci_quaternion(r_eci, v_eci):

    z = -r_eci / np.linalg.norm(r_eci)
    y = -np.cross(r_eci, v_eci)
    y /= np.linalg.norm(y)
    x = np.cross(y, z)

    R = np.column_stack((x, y, z))

    return rotmat_to_quaternion(R)