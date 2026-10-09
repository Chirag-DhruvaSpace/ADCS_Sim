/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import * as THREE from 'three';

// Elevated curtains, rather than a green texture painted onto the surface.
// Coordinates are ECEF, with the north magnetic pole near 81 N, 73 W.
export function createEarthAurora(radius, sunDirection) {
  const columns = 192,
    rows = 10,
    positions = [],
    uvs = [],
    indices = [],
    curtains = [];
  for (let layer = 0; layer < 2; layer++) for (let y = 0; y <= rows; y++) for (let x = 0; x <= columns; x++) {
    positions.push(0, 0, 0);
    uvs.push(x / columns, y / rows);
    curtains.push(layer);
    if (x < columns && y < rows) {
      const a = layer * (columns + 1) * (rows + 1) + y * (columns + 1) + x,
        b = a + columns + 1;
      indices.push(a, b, a + 1, a + 1, b, b + 1);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setAttribute('curtain', new THREE.Float32BufferAttribute(curtains, 1));
  geometry.setIndex(indices);
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  const material = new THREE.ShaderMaterial({
    uniforms: {
      radius: {
        value: radius
      },
      time: {
        value: 0
      },
      sunDir: {
        value: sunDirection
      },
      intensity: {
        value: 1.4
      }
    },
    vertexShader: `
      #include <common>
      #include <logdepthbuf_pars_vertex>
      uniform float radius,time;attribute float curtain;varying float vLayer;varying vec2 vUv;varying vec3 vN;
      float hash(float n){return fract(sin(n*127.1+311.7)*43758.5453);}
      float noise(float p){float i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(hash(i),hash(i+1.),f);}
      float periodicNoise(float p,float period){float q=mod(p,period),i=floor(q),f=fract(q);f=f*f*(3.-2.*f);return mix(hash(i),hash(mod(i+1.,period)),f);}
      void main(){
        vUv=uv;vLayer=curtain;float hemisphere=curtain<1.?1.:-1.;float longitude=uv.x*6.283185307+time*.006;float layer=0.;
        float latitude=radians(66.+(periodicNoise(uv.x*8.,8.)-.5)*1.5+(periodicNoise(uv.x*12.+time*.065,12.)-.5)*2.+(periodicNoise(uv.x*38.-time*.09,38.)-.5)*.8+uv.y*.35);
        vec3 axis=normalize(vec3(.042,-.155,.987))*hemisphere;
        vec3 east=normalize(cross(vec3(0.,0.,1.),axis));vec3 north=cross(axis,east);
        vec3 direction=axis*sin(latitude)+(east*cos(longitude)+north*sin(longitude))*cos(latitude);
        float height=85000.+uv.y*(110000.+30000.*periodicNoise(uv.x*19.+time*.09,19.));
        vec4 p=modelMatrix*vec4(direction*(radius+height),1.);
        vN=normalize(mat3(modelMatrix)*direction);gl_Position=projectionMatrix*viewMatrix*p;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `
      #include <common>
      #include <logdepthbuf_pars_fragment>
      uniform float time,intensity;uniform vec3 sunDir;varying float vLayer;varying vec2 vUv;varying vec3 vN;
      float hash(float n){return fract(sin(n*127.1+311.7)*43758.5453);}
      float noise(float p){float i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(hash(i),hash(i+1.),f);}
      float periodicNoise(float p,float period){float q=mod(p,period),i=floor(q),f=fract(q);f=f*f*(3.-2.*f);return mix(hash(i),hash(mod(i+1.,period)),f);}
      void main(){
        #include <logdepthbuf_fragment>
        float longitude=vUv.x*6.283185307;
        float drift=vUv.x*180.+periodicNoise(vUv.x*25.-time*.10+vLayer*.6,25.)*7.+time*.20;
        float folds=pow(periodicNoise(drift+vUv.y*.4,180.),2.)*.7+periodicNoise(drift*2.7,486.)*.3;
        float arcs=smoothstep(.40,.72,periodicNoise(vUv.x*9.+time*.06+vLayer*2.,9.));
        float bottom=smoothstep(0.,.1,vUv.y),top=1.-smoothstep(.45,1.,vUv.y);
        float night=mix(.05,1.,1.-smoothstep(-.25,.2,dot(normalize(vN),normalize(sunDir))));
        float alpha=bottom*top*(.005+.6*folds)*arcs*night*intensity*.65;
        vec3 color=mix(vec3(.025,.55,.16),vec3(.24,.035,.065),smoothstep(.45,.9,vUv.y));
        gl_FragColor=vec4(color,alpha);
        #include <colorspace_fragment>
      }`,
    transparent: true,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = 'earth-auroral-curtains';
  mesh.frustumCulled = false;
  mesh.renderOrder = 210;
  return mesh;
}
