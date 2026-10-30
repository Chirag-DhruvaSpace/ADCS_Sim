from pathlib import Path
import sys,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
parser=argparse.ArgumentParser(description='Isolated local-UDP SITL timing benchmark; does not command external firmware')
parser.add_argument('--duration',type=float,default=30.)
parser.add_argument('--unpaced',action='store_true')
args=parser.parse_args()
import os,time,socket,jdk4py,cProfile,pstats,io,numpy as np,contextlib
from unittest.mock import patch
os.environ['JAVA_HOME']=str(jdk4py.JAVA_HOME)
import satellite_parameters as settings
settings.POINTING['strategy']='firmware_sitl'
import satellite_flight_visualisation as sim, firmware_sitl_adapter as a, telemetry,sensor_link
from engine.simulation.pacing import SimulationPacer
real=socket.socket
class Redirect:
 def __init__(self,*args,**kwargs): self.sock=real(*args,**kwargs)
 def bind(self,addr): self.sock.bind(('127.0.0.1',0))
 def __getattr__(self,name): return getattr(self.sock,name)
r=real(socket.AF_INET,socket.SOCK_DGRAM);r.bind(('127.0.0.1',0));port=r.getsockname()[1]
telemetry.ADS_SIM_PORT=port;sensor_link.ADS_SENSOR_PORT=port
instances=[];samples=[];snapshots=[]
class Harness(a.FirmwareLink):
 def __init__(self):
  with patch('socket.socket',Redirect): super().__init__()
  self.link.TLM_SEND_PORT=port;instances.append(self)
 def tick(self,*args,**kwargs):
  if kwargs.get('gyro') is not None:samples.append(time.perf_counter())
  return super().tick(*args,**kwargs)
 def send_imu(self,gyro,mag):
  if gyro is not None:samples.append(time.perf_counter())
  return super().send_imu(gyro,mag)
sim.srd.y0[4:7]=np.radians([5.,-4.,3.])
sim._telemetry_publisher.publish=snapshots.append
prof=cProfile.Profile();start=time.perf_counter()
try:
 with patch.object(a,'FirmwareLink',Harness),patch.object(SimulationPacer,'wait_firmware_sample',lambda *a:0.) if args.unpaced else contextlib.nullcontext():
  sim.run_simulation(tf=args.duration)
 elapsed=time.perf_counter()-start
 print('SIM_SECONDS',len(samples)/100,'WALL_SECONDS',elapsed,'SPEED',len(samples)/100/elapsed,'IMU_SAMPLES',len(samples))
 if len(samples)>1:
  gaps=np.diff(samples)*1000;print('PACKET_GAPS_MS_MIN_MEDIAN_P99_MAX',np.min(gaps),np.median(gaps),np.percentile(gaps,99),np.max(gaps))
 print('FINAL_SPEED_TELEMETRY',snapshots[-1].get('simulation_speed_actual'))
 assert args.duration*100-1 <= len(samples) <= args.duration*100+11
 assert all(np.isfinite(v) for d in snapshots for v in d.values() if isinstance(v,float))
finally:
 sim._telemetry_publisher.close();r.close()
 for link in instances:
  for sock in [link.state_socket,link.link._cmd_sock,link.link._mode_sock,link.link._tlm_sock]:sock.close()
