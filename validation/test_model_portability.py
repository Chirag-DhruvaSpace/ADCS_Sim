"""A replacement satellite uses the two YAML files and its own root GLBs."""
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import struct

import numpy as np
import pytest
import yaml

import satellite_parameters as config
from engine.physics import mesh_shadow


def write_model(path, translation=(1., 2., 3.)):
    vertices=np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],dtype='<f4')
    indices=np.array([0,1,2],dtype='<u2')
    binary=vertices.tobytes()+indices.tobytes()
    doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':len(binary)}],
        'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':vertices.nbytes},
                       {'buffer':0,'byteOffset':vertices.nbytes,'byteLength':indices.nbytes}],
        'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3'},
                     {'bufferView':1,'componentType':5123,'count':3,'type':'SCALAR'}],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0},'indices':1}]}],
        'nodes':[{'name':'new-bus','translation':translation,'rotation':[0,0,np.sqrt(.5),np.sqrt(.5)],'children':[1]},
                 {'name':'new-panel','scale':[2,2,2],'mesh':0}],
        'scenes':[{'nodes':[0]}],'scene':0}
    encoded=json.dumps(doc).encode();encoded+=b' '*((-len(encoded))%4)
    binary+=b'\0'*((-len(binary))%4)
    data=struct.pack('<III',0x46546c67,2,12+8+len(encoded)+8+len(binary))
    data+=struct.pack('<II',len(encoded),0x4e4f534a)+encoded
    data+=struct.pack('<II',len(binary),0x004e4942)+binary
    path.write_bytes(data)


def replacement_configuration(directory):
    root=Path(config.__file__).parent
    basic=yaml.safe_load((root/'satellite_parameters.yaml').read_text(encoding='utf-8'))
    advanced=yaml.safe_load((root/'advanced_satellite_parameters.yaml').read_text(encoding='utf-8'))
    basic['spacecraft']['name']='Replacement Cube'
    basic['use_advanced_satellite_model']=True
    for mode in ['stowed','deployed']:
        write_model(directory/f'{mode}.glb')
        body=advanced['configurations'][mode]
        body['spacecraft'].update(model_file=f'{mode}.glb',star_tracker_model_node='new-panel',
            mass_kg=12. if mode=='deployed' else 11., inertia_kg_m2=[.1,.2,.3],
            inertia_tensor_kg_m2=[[.1,0,0],[0,.2,0],[0,0,.3]])
        body['geometry']['blockers']=[{'name':'replacement-panel','center_body_m':[0.,3.,3.],
            'half_extents_m':[1.,1.,.001],'sensor_model_node':'new-panel'}]
    source=directory/'satellite_parameters.yaml'
    source.write_text(yaml.safe_dump(basic),encoding='utf-8')
    (directory/'advanced_satellite_parameters.yaml').write_text(yaml.safe_dump(advanced),encoding='utf-8')
    return source


@pytest.mark.parametrize('deployed',[False,True])
def test_two_yaml_and_root_glb_replace_model_and_prepare_own_cache(tmp_path,monkeypatch,deployed):
    source=replacement_configuration(tmp_path)
    monkeypatch.setattr(mesh_shadow,'CACHE_ROOT',tmp_path/'cache')
    settings=config._load_configuration(source,panels_deployed=deployed)
    craft=settings[0];blocker=settings[10].sun_array.blockers[0]
    mode='deployed' if deployed else 'stowed'
    assert craft.name=='Replacement Cube'
    assert craft.mass_kg==(12. if deployed else 11.)
    np.testing.assert_array_equal(craft.inertia_matrix,np.diag([.1,.2,.3]))
    assert craft.model_file==str(tmp_path/f'{mode}.glb')
    assert craft.model_url==f'/spacecraft-model/{mode}.glb'
    assert blocker.sensor_model_file==craft.model_file
    model=mesh_shadow.load_model_occluder(blocker.sensor_model_file,blocker.sensor_model_node,blocker.sensor_model_scale_to_m)
    # Hierarchical node rotation, translation and scale are reflected in geometry.
    assert model.intersects([.5,2.5,4.],[0.,0.,-1.])
    assert not model.intersects([3.,3.,4.],[0.,0.,-1.])
    scaled=mesh_shadow.load_model_occluder(craft.model_file,'new-panel',.001)
    assert scaled.intersects([.0005,.0025,.004],[0.,0.,-1.])
    cache,_=mesh_shadow.model_cache_path(craft.model_file,'new-panel')
    assert cache.is_file()
    with patch.object(mesh_shadow.subprocess,'check_output',side_effect=AssertionError('rebuilt warm cache')):
        assert mesh_shadow.load_model_occluder(craft.model_file,'new-panel') is model
    write_model(Path(craft.model_file),translation=(1.,2.,6.))
    changed,_=mesh_shadow.model_cache_path(craft.model_file,'new-panel')
    assert changed!=cache
    updated=mesh_shadow.load_model_occluder(craft.model_file,'new-panel')
    assert updated.intersects([.5,2.5,7.],[0.,0.,-1.])


def test_model_route_only_serves_configured_file_and_supports_ranges(tmp_path,monkeypatch):
    import app
    source=replacement_configuration(tmp_path)
    craft=config._load_configuration(source,panels_deployed=True)[0]
    monkeypatch.setattr(config,'SPACECRAFT',craft)
    client=app.app.test_client()
    with client.get(craft.model_url,headers={'Range':'bytes=0-11'}) as response:
        assert response.status_code==206
        assert response.data==Path(craft.model_file).read_bytes()[:12]
    assert client.get('/spacecraft-model/satellite_parameters.yaml').status_code==404


def test_missing_replacement_model_fails_with_configuration_error(tmp_path):
    source=replacement_configuration(tmp_path)
    (tmp_path/'deployed.glb').unlink()
    with pytest.raises(ValueError, match='model_file.*existing GLB'):
        config._load_configuration(source,panels_deployed=True)


def test_sensor_mesh_uses_model_bounds_after_a_satellite_swap(tmp_path,monkeypatch):
    from simulate_sunsensor import SimulatedSunSensorArray
    model=tmp_path/'other.glb';write_model(model)
    monkeypatch.setattr(mesh_shadow,'CACHE_ROOT',tmp_path/'cache')
    base=config.SunSensorArrayParameters.perfect()
    cells=list(base.cells)
    cells[0]=replace(cells[0],position_body_m=(.5,2.5,4.),normal_body=(0.,0.,-1.))
    blocker=config.ShadowBlockerParameters('new-panel',(50.,50.,50.),(1.,1.,1.),
        sensor_model_node='new-panel',sensor_model_file=str(model))
    cfg=replace(base,cells=tuple(cells),enable_self_shadowing=True,blockers=(blocker,))
    sensor=SimulatedSunSensorArray(cfg,record_history=False)
    sensor.get_raw_data(0.,[1.,0.,0.,0.],[0.,0.,-1.],1.,None)
    assert sensor._last_cell_diagnostics[cells[0].name].shadowed


def test_environment_cache_is_bounded_and_keys_time_position_and_velocity():
    from engine_adcs_bridge import EngineOrbitProvider
    class Vector:
        def __init__(self,*values):self.values=values
        def getX(self):return self.values[0]
        def getY(self):return self.values[1]
        def getZ(self):return self.values[2]
    calls=[]
    provider=EngineOrbitProvider.__new__(EngineOrbitProvider)
    provider._environment_cache=OrderedDict()
    provider._surface_java=(Vector,lambda *args:None,lambda *args:None,lambda *args:None)
    provider._epoch_date=SimpleNamespace(shiftedBy=lambda t:t)
    provider.inertial_frame=None
    provider.earth=SimpleNamespace(gravitational_parameter=1.)
    provider.spacecraft=SimpleNamespace(mass=1.)
    provider._surface_sun=SimpleNamespace(getPosition=lambda *args:Vector(1e11,0.,0.))
    provider._srp_model=SimpleNamespace(getLightingRatio=lambda *args:1.)
    def density(*args):calls.append(args);return 1e-12
    provider._atmosphere=SimpleNamespace(getDensity=density,getVelocity=lambda *args:Vector(0.,0.,0.))
    first=provider._surface_environment(0.,[1.,2.,3.],[4.,5.,6.])
    assert provider._surface_environment(0.,[1.,2.,3.],[4.,5.,6.]) is first
    assert len(calls)==1 and not first[0].flags.writeable
    provider._surface_environment(1.,[1.,2.,3.],[4.,5.,6.])
    provider._surface_environment(1.,[2.,2.,3.],[4.,5.,6.])
    provider._surface_environment(1.,[2.,2.,3.],[4.,5.,7.])
    assert len(calls)==4
    for t in range(20):provider._surface_environment(t,[1.,2.,3.],[4.,5.,6.])
    assert len(provider._environment_cache)==8


def test_live_gps_diagnostics_are_bounded():
    from engine_adcs_bridge import get_orbit_provider
    from simulate_gps import SimulatedGPS
    provider=get_orbit_provider(config.EPOCH_UTC)
    gps=SimulatedGPS(provider,config.GpsSimParameters.perfect(),record_history=False)
    r,v=provider.initial_state()
    for t in range(10):gps.get_raw_data(float(t),r,v)
    assert len(gps.records)==2 and gps.records.maxlen==2
