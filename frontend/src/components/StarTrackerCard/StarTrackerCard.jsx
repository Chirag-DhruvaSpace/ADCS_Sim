import { memo, useEffect, useRef, useState } from 'react';
import { TEXTURES } from '../../assets/assetUrls.js';
import MissionCard from '../MissionCard/MissionCard.jsx';
import './StarTrackerCard.css';

const number = (value, digits = 1, unit = '') => Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : '—';
const vector = (values, length, digits) => Array.isArray(values) && values.length === length && values.every(Number.isFinite)
  ? `[${values.map(value => value.toFixed(digits)).join(', ')}]` : '—';

const EARTH_RADIUS_M = 6378137;
const PREVIEW_SIZE = 80;
const PREVIEW_INTERVAL_MS = 250;

function loadPreviewTexture(url) {
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => {
      const surface = document.createElement('canvas');
      surface.width = Math.min(image.naturalWidth, 1024);
      surface.height = Math.round(image.naturalHeight * surface.width / image.naturalWidth);
      const context = surface.getContext('2d', { willReadFrequently: true });
      context.drawImage(image, 0, 0, surface.width, surface.height);
      try {
        resolve(context.getImageData(0, 0, surface.width, surface.height));
      } catch {
        resolve(null);
      }
    };
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

let previewTexturesPromise;
function getPreviewTextures() {
  if (!previewTexturesPromise) {
    previewTexturesPromise = Promise.all([
      loadPreviewTexture(TEXTURES.day),
      loadPreviewTexture(TEXTURES.referenceSky),
      loadPreviewTexture(TEXTURES.cloudsLow),
      loadPreviewTexture(TEXTURES.moon)
    ]);
  }
  return previewTexturesPromise;
}

function sampleTexture(texture, horizontal, vertical) {
  if (!texture) return null;
  const wrappedHorizontal = ((horizontal % 1) + 1) % 1;
  const column = Math.min(texture.width - 1, Math.floor(wrappedHorizontal * texture.width));
  const row = Math.min(texture.height - 1, Math.max(0, Math.floor(vertical * texture.height)));
  const offset = (row * texture.width + column) * 4;
  return [texture.data[offset], texture.data[offset + 1], texture.data[offset + 2]];
}

function transformDirection(matrix, direction) {
  return matrix.map(row => row[0] * direction[0] + row[1] * direction[1] + row[2] * direction[2]);
}

function dotProduct(first, second) {
  return first[0] * second[0] + first[1] * second[1] + first[2] * second[2];
}

function validVector(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function validMatrix(value) {
  return Array.isArray(value) && value.length === 3 && value.every(validVector);
}

function validView(view) {
  return view && validVector(view.position_ecef_m) && validVector(view.sun_direction_ecef)
    && validVector(view.sun_direction_eci) && validMatrix(view.tracker_to_ecef)
    && validMatrix(view.tracker_to_eci) && Number.isFinite(view.field_of_view_deg)
    && view.field_of_view_deg > 0 && view.field_of_view_deg < 180;
}

function mirroredCoordinate(value) {
  return 1 - Math.abs(((value % 2) + 2) % 2 - 1);
}

function sampleReferenceSky(texture, direction) {
  // Match the overview's image-derived celestial sphere projection. This
  // background illustrates the scene; it is not a calibrated star catalogue.
  const azimuth = Math.atan2(direction[0], -direction[2]);
  const elevation = Math.asin(Math.max(-1, Math.min(1, direction[1])));
  const horizontalLimit = Math.atan((3840 / 1664) * Math.tan(Math.PI / 6));
  const absoluteAzimuth = Math.abs(azimuth);
  let horizontalDistance;
  if (absoluteAzimuth <= horizontalLimit) {
    horizontalDistance = Math.tan(absoluteAzimuth) / (2 * Math.tan(horizontalLimit));
  } else {
    horizontalDistance = .5 + (absoluteAzimuth - horizontalLimit) / (Math.PI - horizontalLimit) * 1.5;
  }
  const verticalLimit = Math.atan(Math.tan(Math.PI / 6) * Math.max(.4, Math.cos(azimuth)));
  const absoluteElevation = Math.abs(elevation);
  let verticalDistance;
  if (absoluteElevation <= verticalLimit) {
    verticalDistance = Math.tan(absoluteElevation) / (2 * Math.tan(verticalLimit));
  } else {
    verticalDistance = .5 + (absoluteElevation - verticalLimit) / (Math.PI / 2 - verticalLimit) * 1.5;
  }
  const horizontal = mirroredCoordinate(.5 + Math.sign(azimuth) * horizontalDistance);
  let vertical = mirroredCoordinate(.5 + Math.sign(elevation) * verticalDistance);
  // Remove the small recorded planet in the reference photograph. The live
  // ray/sphere intersection below supplies Earth at its physical position.
  const imageDistance = Math.hypot((horizontal - .487109375) * 3840, (vertical - .498497596) * 1664);
  if (imageDistance < 30) vertical += .025;
  return sampleTexture(texture, horizontal, 1 - vertical);
}

function mixColor(background, foreground, amount) {
  const weight = Math.max(0, Math.min(1, amount));
  return background.map((channel, axis) => channel * (1 - weight) + foreground[axis] * weight);
}

function sphereDistance(origin, direction, radius) {
  const projection = -dotProduct(origin, direction);
  const discriminant = projection * projection - dotProduct(origin, origin) + radius * radius;
  if (discriminant < 0) return -1;
  const distance = projection - Math.sqrt(discriminant);
  return distance > 0 ? distance : -1;
}

export function renderTrackerView(context, view, earthTexture, skyTexture, cloudTexture, moonTexture) {
  const image = context.createImageData(PREVIEW_SIZE, PREVIEW_SIZE);
  const halfWidth = Math.tan(view.field_of_view_deg * Math.PI / 360);
  const position = view.position_ecef_m;
  const positionSquared = dotProduct(position, position);
  const sunRadiusRad = .2666 * Math.PI / 180;
  const pixelRadiusRad = Math.SQRT2 * halfWidth / PREVIEW_SIZE;
  const sunVisibleCosine = Math.cos(sunRadiusRad + pixelRadiusRad);
  const sunGlowCosine = Math.cos(2.5 * Math.PI / 180);
  const bodies = { earthVisible: false, atmosphereVisible: false, sunVisible: false, moonVisible: false };
  let moonOrigin = null;
  let moonRadiusM = 1737400;
  if (validVector(view.moon_position_ecef_m)) {
    moonOrigin = position.map((coordinate, axis) => coordinate - view.moon_position_ecef_m[axis]);
    // Keep unresolved disks visible at 80 pixels without adding a GPU pass.
    moonRadiusM = Math.max(moonRadiusM, Math.hypot(...moonOrigin) * pixelRadiusRad);
  }
  for (let row = 0; row < PREVIEW_SIZE; row += 1) {
    for (let column = 0; column < PREVIEW_SIZE; column += 1) {
      const cameraX = (2 * (column + .5) / PREVIEW_SIZE - 1) * halfWidth;
      const cameraY = (1 - 2 * (row + .5) / PREVIEW_SIZE) * halfWidth;
      const length = Math.hypot(cameraX, cameraY, 1);
      const cameraRay = [cameraX / length, cameraY / length, 1 / length];
      const earthFixedRay = transformDirection(view.tracker_to_ecef, cameraRay);
      const inertialRay = transformDirection(view.tracker_to_eci, cameraRay);
      let color = sampleReferenceSky(skyTexture, inertialRay) || [5, 9, 18];
      const earthDistance = sphereDistance(position, earthFixedRay, EARTH_RADIUS_M);
      const moonDistance = moonOrigin ? sphereDistance(moonOrigin, earthFixedRay, moonRadiusM) : -1;
      if (earthDistance > 0 && (moonDistance < 0 || earthDistance < moonDistance)) {
        bodies.earthVisible = true;
        const normal = position.map((coordinate, axis) =>
          (coordinate + earthDistance * earthFixedRay[axis]) / EARTH_RADIUS_M);
        const longitude = Math.atan2(normal[1], normal[0]);
        const latitude = Math.asin(Math.max(-1, Math.min(1, normal[2])));
        const horizontal = .5 + longitude / (2 * Math.PI);
        const vertical = .5 - latitude / Math.PI;
        let surface = sampleTexture(earthTexture, horizontal, vertical) || [36, 104, 156];
        const clouds = sampleTexture(cloudTexture, horizontal, vertical);
        if (clouds) surface = mixColor(surface, [235, 243, 255], Math.max(...clouds) / 255 * .65);
        const daylight = Math.max(0, dotProduct(normal, view.sun_direction_ecef));
        // Operator preview exposure deliberately preserves the unlit surface;
        // this is not detector radiometry and never changes sensor validity.
        const illumination = .38 + .62 * Math.sqrt(daylight);
        color = surface.map((channel, axis) => channel * illumination + [7, 13, 22][axis]);
        const facing = Math.max(0, -dotProduct(normal, earthFixedRay));
        const horizonHaze = .08 + .5 * Math.pow(1 - facing, 2);
        color = mixColor(color, [65, 150, 240], horizonHaze);
      } else if (moonDistance > 0) {
        bodies.moonVisible = true;
        const normal = moonOrigin.map((coordinate, axis) =>
          (coordinate + moonDistance * earthFixedRay[axis]) / moonRadiusM);
        const horizontal = .5 + Math.atan2(normal[1], normal[0]) / (2 * Math.PI);
        const vertical = .5 - Math.asin(Math.max(-1, Math.min(1, normal[2]))) / Math.PI;
        const surface = sampleTexture(moonTexture, horizontal, vertical) || [185, 182, 174];
        const illumination = .2 + .8 * Math.max(0, dotProduct(normal, view.sun_direction_ecef));
        color = surface.map(channel => channel * illumination);
      } else {
        const sunAlignment = dotProduct(inertialRay, view.sun_direction_eci);
        if (sunAlignment > sunGlowCosine) {
          const angularDistance = Math.acos(Math.max(-1, Math.min(1, sunAlignment)));
          const glow = Math.exp(-angularDistance / (.45 * Math.PI / 180));
          color = color.map((channel, axis) => channel + [255, 177, 78][axis] * glow);
        }
        if (sunAlignment >= sunVisibleCosine) {
          bodies.sunVisible = true;
          color = [255, 251, 221];
        }
      }
      // A thin atmosphere belongs to Earth, not the sky image. Its tangent
      // path gives a blue rim even where the solid globe does not intersect.
      if (earthDistance < 0) {
        const projection = -dotProduct(position, earthFixedRay);
        const impactRadius = Math.sqrt(Math.max(0, positionSquared - projection * projection));
        if (projection > 0 && impactRadius < EARTH_RADIUS_M + 100000) {
          bodies.atmosphereVisible = true;
          const altitudeM = Math.max(0, impactRadius - EARTH_RADIUS_M);
          const scattering = .85 * Math.exp(-altitudeM / 24000);
          color = mixColor(color, [67, 156, 255], scattering);
        }
      }
      const offset = (row * PREVIEW_SIZE + column) * 4;
      image.data[offset] = color[0];
      image.data[offset + 1] = color[1];
      image.data[offset + 2] = color[2];
      image.data[offset + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  context.strokeStyle = '#b2e2f680';
  context.lineWidth = 1;
  context.beginPath();
  const center = PREVIEW_SIZE / 2;
  context.moveTo(center - 3, center);
  context.lineTo(center + 3, center);
  context.moveTo(center, center - 3);
  context.lineTo(center, center + 3);
  context.stroke();
  return bodies;
}

function OpticalPreview({ view, active }) {
  const canvas = useRef(null);
  const latestView = useRef(view);
  const [textures, setTextures] = useState(null);
  const [viewDescription, setViewDescription] = useState('Awaiting view');
  const [telemetryVisible, setTelemetryVisible] = useState(() =>
    !document.body.classList.contains('mission-clear-active'));
  const [documentVisible, setDocumentVisible] = useState(() => !document.hidden);
  latestView.current = view;
  useEffect(() => {
    const updateTelemetryVisibility = event => setTelemetryVisible(event.detail === true);
    const updateDocumentVisibility = () => setDocumentVisible(!document.hidden);
    window.addEventListener('telemetry-visibility', updateTelemetryVisibility);
    document.addEventListener('visibilitychange', updateDocumentVisibility);
    return () => {
      window.removeEventListener('telemetry-visibility', updateTelemetryVisibility);
      document.removeEventListener('visibilitychange', updateDocumentVisibility);
    };
  }, []);
  const available = validView(view);
  const renderingEnabled = active && telemetryVisible && documentVisible && available;
  useEffect(() => {
    if (!renderingEnabled || textures) return;
    let subscribed = true;
    getPreviewTextures().then(loaded => {
      if (subscribed) setTextures(loaded);
    });
    return () => { subscribed = false; };
  }, [renderingEnabled, textures]);
  useEffect(() => {
    if (!renderingEnabled) return;
    const draw = () => {
      if (document.hidden || document.body.classList.contains('mission-clear-active')) return;
      if (window.missionCameraState?.().transitioning) return;
      const bounds = canvas.current?.getBoundingClientRect();
      if (!bounds || bounds.width === 0 || bounds.height === 0 || bounds.bottom < 0 || bounds.top > window.innerHeight) return;
      const currentView = latestView.current;
      if (!validView(currentView) || !canvas.current) return;
      const context = canvas.current.getContext('2d');
      if (context) {
        const bodies = renderTrackerView(context, currentView,
          textures?.[0], textures?.[1], textures?.[2], textures?.[3]);
        const visible = [];
        if (bodies.earthVisible) visible.push('Earth');
        else if (bodies.atmosphereVisible) visible.push('Earth atmosphere');
        if (bodies.sunVisible) visible.push('Sun');
        if (bodies.moonVisible) visible.push('Moon');
        let description = visible.length ? visible.join(' / ') : 'Deep space: bodies outside FOV';
        if (currentView.receipt_aligned && currentView.receipt_reason === 'EARTH_EXCLUSION') {
          const clearance = currentView.earth_limb_angle_deg;
          const limit = currentView.earth_exclusion_deg;
          const location = bodies.earthVisible ? 'Earth in view' : 'Earth outside image';
          description = `${location}; limb ${number(clearance, 1)} / ${number(limit, 1)} deg required`;
        }
        setViewDescription(previous => previous === description ? previous : description);
      }
    };
    draw();
    const timer = window.setInterval(draw, PREVIEW_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [renderingEnabled, textures]);
  return <figure className="star-tracker-optics"
    title="Live mounting and orbit geometry: Earth with atmosphere/clouds, Sun glow and lunar phase. Enhanced night-side exposure for visibility. Background sky is illustrative; this is not a detector image. Bodies only appear when inside the camera view. Earth exclusion uses limb clearance, not disk visibility: the configured 22-degree margin can exceed the image half-angle. Receipt views use the matching capture geometry.">
    {available ? <canvas ref={canvas} width={PREVIEW_SIZE} height={PREVIEW_SIZE}
      className="star-tracker-fov" role="img" aria-label="Live star tracker viewing direction, including Earth and Sun occlusion" />
      : <div className="tracker-view-unavailable">View telemetry unavailable</div>}
    <figcaption>{available ? `${view.field_of_view_deg} deg ${view.receipt_aligned ? 'capture view' : 'live geometry'}` : 'Awaiting camera geometry'}<br />{viewDescription}</figcaption>
  </figure>;
}

export default memo(function StarTrackerCard({ data, derived, active = false }) {
  const valid = data.star_tracker_valid === true;
  const used = data.star_tracker_used === true;
  const slew = derived.gyro ? Math.hypot(...derived.gyro) : null;
  return <MissionCard className={`mission-card glass star-tracker-card ${used ? 'tracker-used' : 'tracker-idle'}`}>
    <header className="card-heading">
      <h2><svg className="card-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 7h5l2-3h4l2 3h5v13H3Z" /><circle cx="12" cy="13" r="4" />
        <path d="m19 1 .6 1.5L21 3l-1.4.5L19 5l-.6-1.5L17 3l1.4-.5Z" />
      </svg>Star tracker</h2>
      <span className="card-label tracker-model" title={used ? 'Used by navigation this tick' : 'Not used by navigation this tick'}>{data.star_tracker_mode || 'STANDBY'}</span>
      <span className="card-state" data-valid={String(valid)}>{valid ? 'VALID' : 'NO DATA'}</span>
    </header>
    <div className="star-tracker-body">
      <dl className="metric-list tracker-metrics">
        <div><dt>Stars / quality</dt><dd>{number(data.star_tracker_num_stars, 0)} / {number(data.star_tracker_quality, 2)}</dd></div>
        <div><dt>Slew / limit</dt><dd>{number(data.star_tracker_rate_deg_s ?? slew, 2, ' deg/s')} / {number(data.star_tracker_rate_limit_deg_s, 2, ' deg/s')}</dd></div>
        <div><dt>Update / latency</dt><dd>{number(data.star_tracker_update_rate_hz, 0, ' Hz')} / {number(data.star_tracker_latency_ms, 0, ' ms')}</dd></div>
        <div><dt>Sun angle / min</dt><dd>{number(data.star_tracker_sun_angle_deg, 1)} / {number(data.star_tracker_sun_exclusion_deg, 1, ' deg')}</dd></div>
        <div title="Clearance from the atmospheric Earth limb. Below the configured minimum, straylight excludes the tracker even if Earth lies outside the camera image."><dt>Earth clearance / min</dt><dd>{number(data.star_tracker_earth_limb_angle_deg, 1)} / {number(data.star_tracker_earth_exclusion_deg, 1, ' deg')}</dd></div>
        <div><dt>Injected error X/Y/Z</dt><dd>{vector(data.star_tracker_noise_arcsec, 3, 1)} arcsec</dd></div>
        <div><dt>Status / trust</dt><dd>{data.star_tracker_reason || 'Unavailable'} / {data.star_tracker_trusted ? 'TRUSTED' : 'LOW'}</dd></div>
      </dl>
      <OpticalPreview view={data.star_tracker_view} active={active} />
    </div>
    <div className="tracker-output"><span>Quaternion · w, x, y, z</span><b>{valid ? vector(data.star_tracker_quaternion_eci, 4, 4) : `No valid solution: ${data.star_tracker_reason || data.star_tracker_mode || 'awaiting receipt'}`}</b></div>
  </MissionCard>;
});
