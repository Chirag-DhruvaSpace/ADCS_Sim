/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
/* Count successful, unique browser updates; never infer unpublished physics ticks. */
export class TelemetryFeed {
  constructor() {
    this.last = null;
    this.total = 0;
    this.times = [];
  }
  key(data) {
    return `${data.telemetry_session_id || ''}:${data.telemetry_sequence ?? data.timestamp}`;
  }
  isNew(data) {
    /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    return this.key(data) !== this.last;
  }
  processed(data, now = performance.now()) {
    if (!this.isNew(data)) return false;
    this.last = this.key(data);
    this.total++;
    this.times.push(now);
    this.rate(now);
    return true;
  }
  rate(now = performance.now()) {
    while (this.times.length && this.times[0] <= now - 1000) this.times.shift();
    return this.times.length;
  }
}
