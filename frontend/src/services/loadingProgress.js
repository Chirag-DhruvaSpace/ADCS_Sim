/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
let state = {progress: 0, message: 'Starting simulation', ready: false};
export const getLoadingProgress = () => state;
export function reportLoading(progress, message, ready = false) {
  if (state.ready) return;
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  state = {progress: Math.max(state.progress, progress), message, ready};
  window.dispatchEvent(new CustomEvent('viewer-loading', {detail: state}));
}
