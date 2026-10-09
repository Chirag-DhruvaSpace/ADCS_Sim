/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { useSyncExternalStore } from 'react';
import { telemetryStore } from '../services/telemetryStore.js';
const idle = {
  data: {},
  derived: {},
  samples: [],
  receivedAt: 0
};
/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
const noSubscribe = () => () => {};
export function useTelemetry(active = true) {
  return useSyncExternalStore(active ? telemetryStore.subscribe : noSubscribe, active ? telemetryStore.getSnapshot : () => idle);
}
