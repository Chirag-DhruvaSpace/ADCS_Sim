# Received GNSS data in the GPS diagram

The current receiver (`simulategps.py`) generates noisy position/velocity fixes,
satellite counts and DOP. It does not propagate a GPS constellation or generate
per-satellite signals. Grey/green links are labelled illustrative. CAD antenna
placements alone cannot determine which GPS spacecraft a receiver tracks.

The existing viewer in `frontend/src/viewer/diagrams/DiagramRenderer.js` already accepts this telemetry
contract, with all coordinates at the same UTC epoch:

```json
{
  "gps_links_available": true,
  "gps_satellites": [
    {"prn": "G01", "position_ecef_m": [20000000, 10000000, 14000000], "used": true}
  ]
}
```

These numbers demonstrate the schema only. `used` means included in the receiver's
navigation solution. The viewer draws each spacecraft and labels its PRN, then
draws links for the used records. Extend the receipt and diagram with measured
fields to display what each link actually delivered.

For a simulated constellation, add these modules:

1. An ephemeris source (GPS broadcast navigation or precise orbit/clock data),
   propagated to each transmit/receive epoch. A simple synthetic constellation
   can be used for a labelled geometry experiment, but is not a real tracked list.
2. Visibility and reception: Earth occultation, spacecraft attitude, antenna
   location/pattern, receiver tracking criteria and signal strength (C/N0).
3. Receiver channels producing PRN, timestamps, pseudorange [m], Doppler [Hz],
   carrier phase [cycles], C/N0 [dB-Hz], lock status and used-in-fix status.
   Model clock bias/drift, signal travel time and Earth rotation consistently.
4. A navigation solution consuming those channel measurements, with fix status,
   covariance/accuracy and DOP derived from the same used satellites. It should
   replace the existing aggregate FakeGPS error generator rather than add a
   second, unrelated satellite list beside it.

For real hardware, decode receiver raw-observation/tracking messages and matching
ephemerides instead. Position-only NMEA GGA/RMC cannot supply the complete raw
measurement set; use the receiver's supported binary/raw protocol. Feed the same
validated telemetry contract to the viewer.

`dashboard_telemetry.enrich_dashboard` currently explicitly marks these fields
unavailable. Replace that assignment with the new receiver's validated channel
records when the integration exists. Do not infer PRNs or positions from the
synthetic satellite count. A per-link table/hover card can then show the received
measurements and tracking state alongside the already supported constellation.
