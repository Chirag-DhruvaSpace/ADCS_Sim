/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { TEXTURES } from '../../assets/assetUrls.js';
import * as THREE from 'three';

// A world-space celestial sphere with a matching reference field and a
// continuous extension around the camera, plus distant star points.
export function createReferenceStarfield() {
  const group = new THREE.Group();
  group.name = 'overview-3d-starfield';
  const fade = {
      value: 1
    },
    pixelRatio = {
      value: Math.min(devicePixelRatio, 2)
    };
  const material = new THREE.ShaderMaterial({
    uniforms: {
      fade,
      pixelRatio
    },
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
    vertexShader: `
   #include <common>
   #include <logdepthbuf_pars_vertex>
   attribute vec3 tint;attribute float magnitude;varying vec3 color;varying float power;uniform float pixelRatio;void main(){color=tint;power=magnitude;vec4 p=modelViewMatrix*vec4(position,1.);gl_Position=projectionMatrix*p;gl_PointSize=max(1.,(2.+max(magnitude,0.)*7.)*pixelRatio);
   #include <logdepthbuf_vertex>
   gl_Position.z=gl_Position.w;
  }`,
    fragmentShader: `
   #include <common>
   #include <logdepthbuf_pars_fragment>
   uniform float fade;varying vec3 color;varying float power;void main(){
   #include <logdepthbuf_fragment>
   #if defined(USE_LOGDEPTHBUF) && defined(USE_LOGDEPTHBUF_EXT)
   gl_FragDepthEXT=1.;
   #endif
   if(power<0.)discard;float r=length(gl_PointCoord-.5)*2.;float glow=exp(-r*r*12.)+exp(-r*r*3.)*.1;gl_FragColor=vec4(color,glow*(.18+power*.82)*fade);
   #include <colorspace_fragment>
  }`
  });
  let seed = 7413;
  const rand = () => {
    seed = Math.imul(seed, 1664525) + 1013904223 >>> 0;
    return seed / 4294967296;
  };
  const positions = [],
    colors = [],
    magnitudes = [];
  const add = (x, y, z, r, g, b, m) => {
    const n = 60 / Math.hypot(x, y, z);
    positions.push(x * n, y * n, z * n);
    colors.push(r, g, b);
    magnitudes.push(z < 0 && Math.abs(x / -z) < 3840 / 1664 * .57735 && Math.abs(y / -z) < .57735 ? -1 : m);
  };
  for (let i = 0; i < 10000; i++) {
    const z = rand() * 2 - 1,
      a = rand() * Math.PI * 2,
      r = Math.sqrt(1 - z * z),
      x = r * Math.cos(a),
      y = r * Math.sin(a);
    // The reference sphere supplies the central field; do not double its stars.
    const central = z < 0 && Math.abs(x / -z) < 3840 / 1664 * .57735 && Math.abs(y / -z) < .57735;
    const warm = rand() < .24,
      m = central ? rand() * .035 : Math.pow(rand(), 5) * .42;
    add(x, y, z, warm ? 1 : .7, warm ? .79 : .83, warm ? .58 : 1, m);
  }
  const geometry = new THREE.BufferGeometry();
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  points.renderOrder = -900;
  group.add(points);
  const upload = () => {
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('tint', new THREE.Float32BufferAttribute(colors, 3));
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    geometry.setAttribute('magnitude', new THREE.Float32BufferAttribute(magnitudes, 1));
  };
  upload();
  group.userData.ready = Promise.resolve();
  const reference = new THREE.TextureLoader().load(TEXTURES.referenceSky);
  reference.colorSpace = THREE.SRGBColorSpace;
  const haze = new THREE.Mesh(new THREE.SphereGeometry(70, 64, 32), new THREE.ShaderMaterial({
    uniforms: {
      reference: {
        value: reference
      },
      fade
    },
    transparent: true,
    side: THREE.BackSide,
    depthWrite: false,
    depthTest: true,
    toneMapped: false,
    vertexShader: `
   #include <common>
   #include <logdepthbuf_pars_vertex>
   varying vec3 direction;void main(){direction=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);
   #include <logdepthbuf_vertex>
   gl_Position.z=gl_Position.w;
  }`,
    fragmentShader: `
   #include <common>
   #include <logdepthbuf_pars_fragment>
   varying vec3 direction;uniform sampler2D reference;uniform float fade;
   float extend(float angle,float limit){float a=abs(angle);return .5+sign(angle)*(a<=limit?tan(a)/(2.*tan(limit)):.5+(a-limit)/(1.570796327-limit)*1.5);}
   vec2 mirrored(vec2 uv){return 1.-abs(mod(uv,2.)-1.);}
   void main(){
   #include <logdepthbuf_fragment>
   #if defined(USE_LOGDEPTHBUF) && defined(USE_LOGDEPTHBUF_EXT)
   gl_FragDepthEXT=1.;
   #endif
   vec3 d=normalize(direction);float az=atan(d.x,-d.z),el=asin(clamp(d.y,-1.,1.));float limitX=atan((3840./1664.)*.577350269);
   float u=.5+sign(az)*(abs(az)<=limitX?tan(abs(az))/(2.*tan(limitX)):.5+(abs(az)-limitX)/(3.141592654-limitX)*1.5);
   float limitY=atan(.577350269*max(.4,cos(az)));vec2 uv=mirrored(vec2(u,extend(el,limitY)));
   // One continuous image-derived sphere. No rectangular patch or second map.
   // Remove the recorded tiny Earth/Moon from the sky; the live globe owns this spot.
   vec2 delta=(uv-vec2(.487109375,.498497596))*vec2(3840.,1664.);
   float hole=1.-smoothstep(23.,30.,length(delta));
   vec3 sky=texture2D(reference,uv).rgb;
   if(hole>0.){vec3 nearby=(texture2D(reference,uv+vec2(0.,.025)).rgb+texture2D(reference,uv-vec2(0.,.025)).rgb)*.5;sky=mix(sky,nearby,hole);}
   gl_FragColor=vec4(sky,fade);
   #include <colorspace_fragment>
  }`
  }));
  group.userData.haze = haze;
  haze.renderOrder = -1000;
  haze.frustumCulled = false;
  group.add(haze);
  // The front reference field already contains its stars. Additional points
  // populate the rest of the sphere without doubling those bright stars.
  group.userData.fade = fade;
  return group;
}
