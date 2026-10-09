/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
export function createLifecycle() {
  let disposed = false;
  const cleanups = [];
  const intervals = new Set(),
    timeouts = new Set(),
    frames = new Set();
  const controller = new AbortController();
  const listen = (target, type, callback, options) => {
    target.addEventListener(type, callback, options);
    cleanups.push(() => target.removeEventListener(type, callback, options));
  };
  return {
    listen,
    get disposed() { return disposed; },
    setInterval(callback, ms) {
      if (disposed) return 0;
      const id = window.setInterval(() => {
        if (!disposed) callback();
      }, ms);
      intervals.add(id);
      return id;
    },
    setTimeout(callback, ms) {
      if (disposed) return 0;
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      const id = window.setTimeout(() => {
        timeouts.delete(id);
        if (!disposed) callback();
      }, ms);
      timeouts.add(id);
      return id;
    },
    clearTimeout(id) { timeouts.delete(id); window.clearTimeout(id); },
    requestAnimationFrame(callback) {
      if (disposed) return 0;
      const id = window.requestAnimationFrame(time => {
        frames.delete(id);
        if (!disposed) callback(time);
      });
      frames.add(id);
      return id;
    },
    fetch: (url, options = {}) => window.fetch(url, {
      ...options,
      signal: options.signal || controller.signal
    }),
    dispose() {
      if (disposed) return;
      disposed = true;
      controller.abort();
      cleanups.reverse().forEach(cleanup => cleanup());
      intervals.forEach(window.clearInterval);
      timeouts.forEach(window.clearTimeout);
      frames.forEach(window.cancelAnimationFrame);
    }
  };
}
