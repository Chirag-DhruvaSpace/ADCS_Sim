"""Nadir-pointing target quaternion, ported directly from the C firmware's
calcNadirFrame() (see nadir_and_target_pointing.c). Kept as its own module,
same pattern as moon_pointing.py, rather than folded into the dynamics file.

IMPORTANT: this intentionally does NOT reuse quat2eul.compute_lvlh_to_eci_quaternion.
That function assembles axes in a different order/sign convention than the C
firmware's calcNadirFrame (its 'y' axis corresponds to the C code's xdes, and
its 'x' axis is the negative of the C code's ydes) -- reusing it would produce
a rotated attitude relative to what actually flies, not an equivalent one.
"""
import numpy as np


def _rotmat_to_quaternion_robust(R):
    """Shepperd's method: picks the numerically best of 4 formulas based on
    the largest denominator, avoiding the sqrt(1+trace)/2 singularity that a
    naive implementation hits when trace is close to -1 (large rotation
    angles). Returns [q0,q1,q2,q3] scalar-first, matching this project's
    convention throughout."""
    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0:
        s = 0.5 / np.sqrt(trace + 1.0)
        q0 = 0.25 / s
        q1 = (R[2, 1] - R[1, 2]) * s
        q2 = (R[0, 2] - R[2, 0]) * s
        q3 = (R[1, 0] - R[0, 1]) * s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        q0 = (R[2, 1] - R[1, 2]) / s
        q1 = 0.25 * s
        q2 = (R[0, 1] + R[1, 0]) / s
        q3 = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        q0 = (R[0, 2] - R[2, 0]) / s
        q1 = (R[0, 1] + R[1, 0]) / s
        q2 = 0.25 * s
        q3 = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        q0 = (R[1, 0] - R[0, 1]) / s
        q1 = (R[0, 2] + R[2, 0]) / s
        q2 = (R[1, 2] + R[2, 1]) / s
        q3 = 0.25 * s
    q = np.array([q0, q1, q2, q3])
    if q[0] < 0:          # shortest-path convention, matches quat2eul usage elsewhere
        q = -q
    return q / np.linalg.norm(q)


def nadir_pointing_quaternion(r_eci, v_eci):
    """Direct port of calcNadirFrame(), with axes relabeled so that BODY +X
    (not the C code's literal zdes->bodyZ mapping) points at nadir, per this
    mission's actual hardware convention.

    r_eci, v_eci are the spacecraft's ECI position and velocity. Returns the
    desired body->ECI quaternion [q0,q1,q2,q3] (scalar-first), for use with
    quat2eul.get_quaternion_error the same way moon_pointing_quaternion's
    output is used.

    Axis convention:
      body X -> nadir direction (toward Earth center)   [was zdes in the C code]
      body Y -> along -r x v (roughly cross-track)       [was xdes in the C code]
      body Z -> completes the right-handed frame         [was ydes in the C code]

    The relabeling (new_X=zdes, new_Y=xdes, new_Z=ydes) is a cyclic
    permutation of the C code's own right-handed triple (ydes = zdes x xdes),
    which keeps the rotation proper (det=+1) rather than silently flipping
    into a reflection -- verified numerically, not just assumed.
    """
    r_eci = np.asarray(r_eci, dtype=float)
    v_eci = np.asarray(v_eci, dtype=float)

    r = -r_eci                      # matches nadirVars.r = -PosVectorECI
    zdes = r / np.linalg.norm(r)    # nadir direction (C code's zdes)

    crossprod = np.cross(r, v_eci)
    xdes = crossprod / np.linalg.norm(crossprod)   # C code's xdes

    crossprod = np.cross(zdes, xdes)
    ydes = crossprod / np.linalg.norm(crossprod)   # C code's ydes

    # Cyclic relabel: nadir (zdes) becomes body X, not body Z.
    rotmat = np.column_stack((zdes, xdes, ydes))

    # Columns are body axes in ECI; the Hamilton converter takes that matrix.
    return _rotmat_to_quaternion_robust(rotmat)