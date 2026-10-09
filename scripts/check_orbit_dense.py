# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
"""Compare bounded dense-output sampling with the original control-tick path."""
from dataclasses import replace
from pathlib import Path
import sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import satellite_parameters as config
from engine_adcs_bridge import EngineOrbitProvider
settings=config.SIMULATION
tracks=[]
for window in [.1,.5]:
    config.SIMULATION=replace(settings,orbit_output_window_s=window)
    provider=EngineOrbitProvider(config.EPOCH_UTC)
    started=time.perf_counter(); track=[]
    # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
    for t in np.arange(0,10.01,.1):
        provider.set_attitude(float(t),[1,0,0,0],[.02,-.03,.01])
        track.append(np.concatenate(provider.state_at(float(t))))
        assert abs(provider.clock.time-t)<1e-10
    tracks.append(np.array(track))
    print('WINDOW',window,'WALL',time.perf_counter()-started,flush=True)
error=np.linalg.norm(tracks[0][:,:3]-tracks[1][:,:3],axis=1)
print('MAX_POSITION_DIFFERENCE_M',error.max(),flush=True)
assert error.max()<settings.orbit_integrator_abs_tolerance
config.SIMULATION=settings
