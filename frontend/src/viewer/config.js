/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
export function createViewerConfig(configuration) {
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  return {
    MODEL_URL: configuration.spacecraft_model_url,
    MODEL_COM: configuration.spacecraft_com,
    MODEL_SCALE: 1.0,
    // CAD export uses SI metres
    AXIS_LEN: 1500.0,
    // was axisLength in Cesium code
    DIRLINE_LEN: 3000.0,
    // was sunLineLength
    CHASE_VIEW_FROM: [-4.8, 0.0, 1.8],
    // close enough to read the spacecraft against Earth
    PAYLOAD_OFFSET: [0.35, 0.0, 0.0],
    // metres, beyond the +X bus face
    PAYLOAD_BORESIGHT: [1.0, 0.0, 0.0],
    // same body +X axis as NADIR / NOMINAL_IN_ORBIT
    PAYLOAD_UP: [0.0, 0.0, 1.0],
    FOV_DEG: 60,
    /* performance (the ⚙ preset overrides budget/concurrent; sharpness in SETTINGS) */
    PIXEL_RATIO_CAP: 2.0,
    TILE_BUDGET: 160,
    // max visible tiles (main view)
    STREAM_TILE_BUDGET: 48,
    // max visible tiles for the payload stream view
    CREATE_BUDGET: 40,
    // new tiles created per 250ms update (main view)
    CREATE_STREAM_BUDGET: 12,
    // new tiles created per update for the payload stream
    CACHE_MAX: 320,
    // tiles kept in memory
    TARGET_PX: 170,
    // tile screen-px threshold (overridden by SETTINGS.sharp)
    MAX_Z: 19,
    MIN_TILED_Z: 3,
    // tiles always cover the globe down to this level
    MAX_CONCURRENT: 10,
    SMOOTH: 5,
    /* night side */
    NIGHT_BOOST: 1.0,
    MOONLIGHT: [0.010, 0.014, 0.022],
    /* sun / moon ("at infinity", camera-anchored) */
    CAMERA_FAR: 2.0e8,
    SUN_RENDER_DIST: 1.3e8,
    SUN_GLARE_SIZE: 6.5e6,
    MOON_RENDER_DIST: 6.0e7,
    MOON_RADIUS: 2.71e5,
    STAR_RADIUS: 1.4e8,
    HAZE_RADIUS: 1.3e8,
    /* chase camera */
    CHASE_ROT_SENS: 0.004,
    CHASE_ZOOM_SENS: 0.0012,
    CHASE_MIN_DIST: 0.05,
    CHASE_MAX_DIST: 5.0e7,
    FREE_MAX_DIST: 8.0e7,
    /* model look */
    SUN_INTENSITY: 2.8,
    MODEL_ENV: 0.45,
    MODEL_COLORIZE: true,
    CLOCK_SOURCE: 'telemetry',
    STREAM_URL: 'ws://localhost:8765',
    STREAM_MS: 1000,
    STREAM_SOURCE: 'payload',
    // 'payload' | 'fixed' (legacy static 77E/13N view)

    /* tile crossfade — fades happen OVER the parent layer, never into black */
    TILE_FADE_MS: 300
  };
}
