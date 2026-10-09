const assert = require('assert');
(async () => {
const { TelemetryFeed: Feed } = await import('../frontend/src/services/TelemetryFeed.js');
const feed = new Feed();
const data = {telemetry_session_id:'A',telemetry_sequence:1};
assert(feed.processed(data,0));
assert.equal(feed.rate(500),1);
assert.equal(feed.rate(1100),0);
assert(!feed.processed(data,1200));
assert.equal(feed.total,1);
assert(feed.processed({...data,telemetry_sequence:2},1300));
assert(feed.processed({...data,telemetry_session_id:'B'},1400));
assert.equal(feed.total,3);
assert.equal(feed.rate(1500),2);
console.log('Viewer feed: unique processing, window expiry, restart PASS');

})().catch(error => { console.error(error); process.exitCode = 1; });
