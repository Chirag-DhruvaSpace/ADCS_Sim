// Request fullscreen once at startup, retrying with a gesture if required.
export function startupFullscreen(doc = document) {
  let stopped = false;
  let pending = false;
  function cleanup() {
    stopped = true;
    doc.removeEventListener('click', onGesture);
    doc.removeEventListener('keydown', onGesture);
    doc.removeEventListener('fullscreenchange', onChange);
  }
  function onChange() {
    if (doc.fullscreenElement) cleanup();
  }
  function request() {
    if (stopped || pending) return;
    if (doc.fullscreenElement) return cleanup();
    pending = true;
    try {
      Promise.resolve(doc.documentElement.requestFullscreen({navigationUI: 'hide'}))
        .then(cleanup, () => { pending = false; });
    } catch {
      pending = false;
    }
  }
  function onGesture(event) {
    // Leave the existing fullscreen button in charge of its own click.
    if (event.target?.closest?.('#fullscreen-toggle')) return;
    if (event.type === 'keydown' && (event.key === 'Escape' || event.repeat || event.ctrlKey || event.altKey || event.metaKey)) return;
    request();
  }
  if (!doc.documentElement.requestFullscreen || doc.fullscreenEnabled === false) return cleanup;
  doc.addEventListener('click', onGesture);
  doc.addEventListener('keydown', onGesture);
  doc.addEventListener('fullscreenchange', onChange);
  request();
  return cleanup;
}
