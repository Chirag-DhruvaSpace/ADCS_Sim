// made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
const assert=require('assert');
(async () => {
const {derive,History,fmt}=await import('../frontend/src/services/dashboardData.js');
// made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
const base={timestamp:'2026-10-01T15:00:00Z',telemetry_session_id:'a',telemetry_sequence:1,
  mode:'POINTING',yaw_deg:179,pitch_deg:0,roll_deg:0,target_yaw_deg:-179,target_pitch_deg:0,target_roll_deg:0,
  sun_pointing_error_deg:2,imu_gyro_valid:true,imu_gyro_x_rad_s:Math.PI/180,imu_gyro_y_rad_s:0,imu_gyro_z_rad_s:0,
  body_rate_x:.5,body_rate_y:0,body_rate_z:0,gps_pos_eci_x:3,gps_pos_eci_y:4,gps_pos_eci_z:0,
  truth_pos_eci_x:0,truth_pos_eci_y:0,truth_pos_eci_z:0};
assert.equal(derive(base).gyro[0],1);
assert.equal(derive(base).gyroError[0],.5);
assert.equal(derive(base).gpsError,5);
assert.equal(derive(base).angleError[0],-2);
assert.equal(derive({...base,mode:'DETUMBLE'}).pointingError,null);
for(const [mode,prefix,error] of [
  ['MOON','moon_target','moon_pointing_error_deg'],
  ['NADIR','nadir_target','nadir_pointing_error_deg'],
  ['SUN_SWEEP','sun_sweep_target','sun_sweep_error_deg'],
  ['SUN_POINTING_RW','sun_pointing_rw_target','sun_pointing_rw_error_deg'],
  ['NOMINAL_IN_ORBIT','nominal_in_orbit_target','nominal_in_orbit_error_deg'],
  ['KINEMATIC_ROBUSTNESS','kinematic_robustness_target','kinematic_robustness_error_deg']]) {
  const sample={...base,mode,[error]:3.25,[prefix+'_yaw_deg']:42,[prefix+'_pitch_deg']:15,[prefix+'_roll_deg']:-7};
  assert.equal(derive(sample).pointingError,3.25);
  assert.deepEqual(derive(sample).targets,[42,15,-7]);
}
assert.equal(derive({...base,imu_gyro_valid:false}).gyro,null);
assert.equal(derive({...base,truth_pos_eci_x:null}).gpsError,null);
assert.equal(derive({...base,body_rate_x:undefined}).gyroError,null);
assert.equal(fmt(null),'—');assert.equal(fmt(NaN),'—');
const h=new History(4);assert(h.add(base));assert(!h.add(base));
assert(!h.add({...base,timestamp:'invalid',telemetry_sequence:2}));
for(let i=1;i<8;i++)h.add({...base,timestamp:new Date(Date.parse(base.timestamp)+i*1000).toISOString(),telemetry_sequence:i+1});
assert.equal(h.samples.length,4);
const rolling=new History();
for(let i=0;i<=90;i++)rolling.add({...base,timestamp:new Date(Date.parse(base.timestamp)+i*1000).toISOString(),telemetry_sequence:i});
assert.equal(rolling.samples.length,31);
assert.equal(rolling.samples[0].t,Date.parse(base.timestamp)+60000);
assert.equal(rolling.samples.at(-1).t-rolling.samples[0].t,30000);
h.add({...base,telemetry_session_id:'b'});assert.equal(h.samples.length,1);
h.add({...base,telemetry_session_id:'b',telemetry_sequence:2,timestamp:'2026-10-01T14:00:00Z'});assert.equal(h.samples.length,1);
console.log('Dashboard: units, missing/invalid sensors, wrapped errors, dedupe, bounded history and resets PASS');

})().catch(error => {console.error(error);process.exitCode=1;});
