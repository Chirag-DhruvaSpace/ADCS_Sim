// Model preparation only; Python's runtime reads the generated bounding tree.
import fs from 'node:fs';
import path from 'node:path';
import { Matrix4, Quaternion, Vector3 } from 'three';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
await MeshoptDecoder.ready;
const [filename, selector] = process.argv.slice(2);
const file = fs.readFileSync(filename);
if (file.readUInt32LE(0) !== 0x46546c67 || file.readUInt32LE(4) !== 2) throw new Error('Expected glTF 2 GLB');
let data, binary;
for (let offset=12; offset<file.length;) {
  const size=file.readUInt32LE(offset), type=file.readUInt32LE(offset+4);
  const chunk=file.subarray(offset+8, offset+8+size);
  if (type===0x4e4f534a) data=JSON.parse(chunk.toString());
  if (type===0x004e4942) binary=chunk;
  offset+=8+size;
}
const buffers=new Map(), views=new Map();
function buffer(id) {
  if (buffers.has(id)) return buffers.get(id);
  const uri=data.buffers[id].uri;
  let bytes;
  if (!uri && id===0) bytes=binary;
  else if (uri?.startsWith('data:')) bytes=Buffer.from(uri.slice(uri.indexOf(',')+1), 'base64');
  else if (uri && !/^[a-z]+:/i.test(uri)) bytes=fs.readFileSync(path.resolve(path.dirname(filename), decodeURIComponent(uri)));
  else throw new Error('Geometry buffer is not embedded or local');
  buffers.set(id,bytes); return bytes;
}
function view(id) {
  if (views.has(id)) return views.get(id);
  const v=data.bufferViews[id], e=v.extensions?.EXT_meshopt_compression;
  let bytes;
  if (e) {
    bytes=new Uint8Array(v.byteLength);
    MeshoptDecoder.decodeGltfBuffer(bytes,e.count,e.byteStride,
      buffer(e.buffer).subarray(e.byteOffset||0,(e.byteOffset||0)+e.byteLength),e.mode,e.filter);
  } else bytes=buffer(v.buffer).subarray(v.byteOffset||0,(v.byteOffset||0)+v.byteLength);
  views.set(id,bytes); return bytes;
}
const component={5120:['getInt8',1,127],5121:['getUint8',1,255],5122:['getInt16',2,32767],
  5123:['getUint16',2,65535],5125:['getUint32',4,4294967295],5126:['getFloat32',4,1]};
function read(viewId,offset,type,normalized,width,count,stride) {
  const bytes=view(viewId), reader=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const [method,size,max]=component[type], result=new Float64Array(count*width);
  stride ||= size*width;
  for(let i=0;i<count;i++) for(let j=0;j<width;j++) {
    let value=reader[method](offset+i*stride+j*size,true);
    if(normalized) value=Math.max(-1,value/max);
    result[i*width+j]=value;
  }
  return result;
}
function accessor(id) {
  const a=data.accessors[id], width={SCALAR:1,VEC2:2,VEC3:3,VEC4:4}[a.type];
  if(!width || !component[a.componentType]) throw new Error('Unsupported geometry accessor');
  const result=a.bufferView===undefined ? new Float64Array(a.count*width)
    : read(a.bufferView,a.byteOffset||0,a.componentType,a.normalized,width,a.count,data.bufferViews[a.bufferView].byteStride);
  if(a.sparse) {
    const s=a.sparse, indices=read(s.indices.bufferView,s.indices.byteOffset||0,s.indices.componentType,false,1,s.count);
    const values=read(s.values.bufferView,s.values.byteOffset||0,a.componentType,a.normalized,width,s.count);
    for(let i=0;i<s.count;i++) for(let j=0;j<width;j++) result[indices[i]*width+j]=values[i*width+j];
  }
  return result;
}
const exact=data.nodes.map((node,id)=>({node,id})).filter(x=>x.node.name===selector);
const matches=exact.length ? exact : data.nodes.map((node,id)=>({node,id})).filter(x=>x.node.name?.endsWith(selector));
if(matches.length!==1) throw new Error(`CAD selector ${JSON.stringify(selector)} matched ${matches.length} nodes; use a unique name`);
const world=new Map();
function matrices(id,parent) {
  const node=data.nodes[id], local=node.matrix ? new Matrix4().fromArray(node.matrix)
    : new Matrix4().compose(new Vector3().fromArray(node.translation||[0,0,0]),
      new Quaternion().fromArray(node.rotation||[0,0,0,1]),new Vector3().fromArray(node.scale||[1,1,1]));
  const matrix=parent.clone().multiply(local);world.set(id,matrix);
  for(const child of node.children||[]) matrices(child,matrix);
}
for(const id of data.scenes[data.scene||0].nodes) matrices(id,new Matrix4());
const vertices=[],triangles=[];
function collect(id) {
  const node=data.nodes[id], matrix=world.get(id);
  if(!matrix) throw new Error('Selected CAD node is outside the active scene');
  if(node.mesh!==undefined) for(const primitive of data.meshes[node.mesh].primitives) {
    if(primitive.extensions?.KHR_draco_mesh_compression) throw new Error('Sensor CAD preparation supports uncompressed or meshopt GLB; export Draco geometry accordingly');
    const mode=primitive.mode??4;
    if(![4,5,6].includes(mode)) continue;
    const positions=accessor(primitive.attributes.POSITION), base=vertices.length/3;
    const point=new Vector3();
    for(let i=0;i<positions.length;i+=3) {point.fromArray(positions,i).applyMatrix4(matrix);vertices.push(point.x,point.y,point.z);}
    const indices=primitive.indices===undefined ? Array.from({length:positions.length/3},(_,i)=>i) : accessor(primitive.indices);
    if(mode===4) for(const index of indices) triangles.push(base+index);
    else for(let i=2;i<indices.length;i++) {
      const a=mode===6?indices[0]:indices[i-2], b=indices[i-1], c=indices[i];
      triangles.push(base+a,base+b,base+c);
    }
  }
  for(const child of node.children||[]) collect(child);
}
collect(matches[0].id);
const positions=Float64Array.from(vertices), indices=Uint32Array.from(triangles), header=Buffer.alloc(8);
header.writeUInt32LE(positions.length/3,0);header.writeUInt32LE(indices.length,4);
process.stdout.write(header);process.stdout.write(Buffer.from(positions.buffer));process.stdout.write(Buffer.from(indices.buffer));
