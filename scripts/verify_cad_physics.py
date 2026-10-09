"""Live coupled-orbit regression, selecting modes in-process without editing YAML."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from dataclasses import replace
import satellite_parameters as config

parser=argparse.ArgumentParser()
parser.add_argument('mode',choices=['deployed','stowed','legacy'])
parser.add_argument('--output',type=Path)
args=parser.parse_args()
names=('SPACECRAFT','ORBIT','ATTITUDE','MODEL_DATA','CONTROL','DISTURBANCES','GEOMETRY',
       'REACTION_WHEELS','SIMULATION','GPS_SIM','IMU_SIM','IMU_MOUNT_DEFAULTS')
for name,value in zip(names,config._load_configuration(panels_deployed=args.mode!='stowed', use_advanced_satellite_model=args.mode!='legacy')):
    setattr(config,name,value)
# Test a sunlit phase so a short regression actually exercises SRP attitude
# coupling. The persisted run starts near eclipse at its configured epoch.
config.ORBIT=replace(config.ORBIT,true_anomaly_deg=180.)
config.MASS_KG=config.SPACECRAFT.mass_kg
config.BODY_RADIUS_M=config.SPACECRAFT.body_radius_m
config.DRAG_AREA_M2=config.SPACECRAFT.drag_reference_area_m2
config.SRP_AREA_M2=config.SPACECRAFT.srp_reference_area_m2
config.IXX,config.IYY,config.IZZ=config.SPACECRAFT.inertia_kg_m2
if Path('C:/Program Files/Java/jdk-21').exists():
    os.environ['JAVA_HOME']='C:/Program Files/Java/jdk-21'
import satellite_flight_visualisation as sim

captured=[]
sim._telemetry_publisher.publish=captured.append
sim._telemetry_publish_interval_s=0
sim.run_simulation(tf=2.,dt=.1)
assert len(captured)==20
provider=sim._orbit_provider
for data in captured:
    assert data['spacecraft_configuration']==args.mode
    assert data['spacecraft_mass_kg']==config.MASS_KG
    assert data['spacecraft_model_url'].endswith('P-30XL.glb' if args.mode=='legacy' else f'{args.mode}.glb')
    q=[data['truth_att_quat_'+a] for a in ('w','x','y','z')]
    p=np.array([data['truth_pos_eci_'+a] for a in ('x','y','z')])
    v=np.array(data['satellite_velocity_eci_m_s'])
    result=provider.surface_result(data['simulation_time_s'],p,v,q)
    np.testing.assert_allclose([data['srp_acceleration_eci_'+a] for a in 'xyz'],result.srp_force_eci_n/config.MASS_KG,atol=1e-18)
    np.testing.assert_allclose([data['drag_acceleration_eci_'+a] for a in 'xyz'],result.drag_force_eci_n/config.MASS_KG,atol=1e-18)
    np.testing.assert_allclose([data['srp_torque_body_'+a] for a in 'xyz'],result.srp_torque_body_nm,atol=1e-18)
    assert data['atmospheric_density_kg_m3']>0
    json.dumps(data,allow_nan=False)

# Check the actual registered Java force callback, not a separate model.
import jpype
callback=next(f for f in provider.universe.force_model.forces if hasattr(f,'proxy'))
state=provider.universe._build_spacecraft_state(provider.spacecraft)
force=jpype.JObject(callback.proxy,jpype.JClass('org.orekit.forces.ForceModel'))
acc=force.acceleration(state,jpype.JArray(jpype.JDouble)([]))
pos,vel=provider.state_at(provider.clock.time)
result=provider.surface_result(provider.clock.time,pos,vel,provider.predicted_attitude(provider.clock.time))
np.testing.assert_allclose([acc.getX(),acc.getY(),acc.getZ()],
                          (result.srp_force_eci_n+result.drag_force_eci_n)/config.MASS_KG,atol=1e-18)
last=captured[-1]
if args.mode != 'legacy':
    assert last['disturbance_srp_unm']>0
    assert last['disturbance_atmospheric_drag_unm']>0
else:
    # The basic cube has uniform optics and centered COM: pressure produces
    # orbital force, but its opposing symmetric moment arms cancel exactly.
    np.testing.assert_allclose(result.srp_torque_body_nm, 0, atol=1e-18)
    np.testing.assert_allclose(result.drag_torque_body_nm, 0, atol=1e-18)
# Isolate each environmental moment in the actual Euler RHS. The control,
# gravity-gradient and residual-dipole terms cancel at this identical state.
sim.srd.set_imu_adcs_input(False,use_attitude=False)
q=provider.predicted_attitude(provider.clock.time)
y=np.r_[q,np.zeros(3)]
B=provider.magnetic_field_eci(provider.clock.time,pos)
def rhs(srp,drag):
    return np.asarray(sim.srd.rotational_equations_of_motion(provider.clock.time,y,B,pos,vel,
        external_torque_body=srp,aerodynamic_torque_body=drag,
        truth_field_eci=B,truth_position_eci=pos,truth_velocity_eci=vel))
base=rhs(np.zeros(3),np.zeros(3))
np.testing.assert_allclose(rhs(result.srp_torque_body_nm,np.zeros(3))[4:7]-base[4:7],
                          np.linalg.solve(config.SPACECRAFT.inertia_matrix,result.srp_torque_body_nm),atol=1e-14)
np.testing.assert_allclose(rhs(np.zeros(3),result.drag_torque_body_nm)[4:7]-base[4:7],
                          np.linalg.solve(config.SPACECRAFT.inertia_matrix,result.drag_torque_body_nm),atol=1e-14)
if args.output:
    args.output.write_text(json.dumps(captured,allow_nan=False),encoding='utf-8')
print(f'{args.mode} LIVE PASS: {len(captured)} ticks; registered orbit force equals telemetry; Euler moments consistent; all values finite')
