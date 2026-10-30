package leap.physics;

/** Exact ray/AABB test for configured facet quadrature points. SI units. */
public final class FacetVisibility {
    private final double[][] positions, lo, hi;
    public FacetVisibility(double[][] positions, double[][] lo, double[][] hi) {
        this.positions = positions; this.lo = lo; this.hi = hi;
    }
    public boolean[] visible(double[] direction, boolean[] active) {
        boolean[] result = new boolean[positions.length];
        for (int i = 0; i < positions.length; i++) {
            if (!active[i]) continue;
            result[i] = true;
            for (int b = 0; b < lo.length; b++) {
                double near = Double.NEGATIVE_INFINITY, far = Double.POSITIVE_INFINITY;
                boolean outside = false;
                for (int a = 0; a < 3; a++) {
                    double origin = positions[i][a] + direction[a]*1e-6;
                    if (Math.abs(direction[a]) < 1e-12) {
                        if (origin < lo[b][a] || origin > hi[b][a]) { outside = true; break; }
                    } else {
                        double t1 = (lo[b][a]-origin)/direction[a];
                        double t2 = (hi[b][a]-origin)/direction[a];
                        near = Math.max(near, Math.min(t1,t2));
                        far = Math.min(far, Math.max(t1,t2));
                    }
                }
                if (!outside && far >= Math.max(near,0) && far > 1e-7) {
                    result[i] = false; break;
                }
            }
        }
        return result;
    }
}
