/* Read CAD planar mounting directions from compressed or raw glTF geometry.
   Requires npm install --prefix .tools/gltf @gltf-transform/cli.
   Face geometry establishes mechanical axes; calibration remains separate. */
import {NodeIO} from '../.tools/gltf/node_modules/@gltf-transform/core/dist/index.js';
import {ALL_EXTENSIONS} from '../.tools/gltf/node_modules/@gltf-transform/extensions/dist/index.js';
import {MeshoptDecoder} from '../.tools/gltf/node_modules/meshoptimizer/index.js';
import fs from 'node:fs';
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.decoder':MeshoptDecoder});
for (const mode of ['deployed','stowed']) {
  const doc = await io.read(`frontend/assets/models/P-30XL-${mode}.glb`);
  const path = `frontend/assets/models/P-30XL-${mode}-inventory.json`;
  const inventory = JSON.parse(fs.readFileSync(path));
  for (const node of doc.getRoot().listNodes().filter(n=>/FSS|SP_RW060/.test(n.getName()))) {
    const part=inventory.parts.find(p=>p.node===node.getName());
    const size=part.bounds_body_m[1].map((v,i)=>v-part.bounds_body_m[0][i]);
    const axis=size.indexOf(Math.min(...size)),isSensor=node.getName().includes('FSS');
    const primitive=node.getMesh().listPrimitives()[0];
    const points=primitive.getAttribute('POSITION').getArray(),indices=primitive.getIndices().getArray();
    const groups=new Map();
    for(let i=0;i<indices.length;i+=3) {
      const a=indices[i]*3,b=indices[i+1]*3,c=indices[i+2]*3;
      const u=[points[b]-points[a],points[b+1]-points[a+1],points[b+2]-points[a+2]];
      const v=[points[c]-points[a],points[c+1]-points[a+1],points[c+2]-points[a+2]];
      let n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
      const area=Math.hypot(...n);if(area<1e-12)continue;
      n=n.map(x=>x/area);
      if(n[isSensor?axis:2]<0)n=n.map(x=>-x);
      const key=n.map(x=>Math.round(x*100)/100).join(',');
      const g=groups.get(key)||{area:0,normal:[0,0,0]};
      g.area+=area;g.normal=g.normal.map((x,j)=>x+n[j]*area);groups.set(key,g);
    }
    const g=[...groups.values()].sort((a,b)=>b.area-a.area)[0];
    const sign=isSensor?(part.center_body_m[axis]>[0,0,-.17][axis]?1:-1):1;
    part.mount_normal_body=g.normal.map(x=>sign*x/Math.hypot(...g.normal));
    part.mount_normal_provenance='Area-weighted dominant planar CAD face; inferred sensor boresight or wheel spindle; not sensor calibration';
    console.log(mode,part.node,part.mount_normal_body.map(x=>+x.toFixed(7)));
  }
  fs.writeFileSync(path,JSON.stringify(inventory,null,2));
}
