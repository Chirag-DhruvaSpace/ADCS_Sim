/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { History, derive } from './dashboardData.js';
export function createTelemetryStore() {
  const history = new History();
  const listeners = new Set();
  let snapshot = {
    data: {},
    derived: derive({}),
    samples: [],
    receivedAt: 0
  };
  return {
    subscribe(listener) {
      listeners.add(listener);
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
      return () => listeners.delete(listener);
    },
    getSnapshot: () => snapshot,
    accept(data, now = performance.now()) {
      if (!history.add(data)) return false;
      snapshot = {
        data,
        derived: derive(data),
        samples: history.samples.slice(),
        receivedAt: now
      };
      listeners.forEach(listener => listener());
      return true;
    }
  };
}
export const telemetryStore = createTelemetryStore();
