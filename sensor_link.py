"""
sensor_link.py

Sends the simulated sensors' raw outputs to the SITL ADS process, as the exact
bytes of the firmware struct that crosses each sensor's real interface.
Firmware side: sensor_link.c (receive) -> sitl_task_defs.c (flight-equivalent
processing).

Wire format (UDP to 127.0.0.1:5010, little-endian, no padding):
    uint8 sensorId | payload

    SENSOR_ID_GPS = 1 : AdsGpsData (base_shared.h, #pragma pack(1)), 134 bytes
    SENSOR_ID_FSS = 2 : uint8 slaveId + the 25 data bytes of the FSS GETTLM
                        reply (FSS.c frame offsets 5..29), one packet per head

The payloads come from the current sensor models unchanged:
  - GPS: simulategps get_raw_data() -> RawGpsSample.data, the ORION receiver's
    scaled integers. The real OBC decodes those before forwarding AdsGpsData
    (UpdateGpsData), so this file does the same decode, with the same scale
    factors as gps_navigation.decode_orion_fields().
  - FSS: simulatesunsensor get_raw_data() -> RawSunSample.sensors, one
    RawFineSunSensor per head whose .data already holds the GETTLM fields.
    Packed as is. Slave 0x11 + k is cell k of the sun array, so the cell
    order and sensor_roll_rad in the yaml MUST match the firmware's
    AdsConfigStruct.RelDCM (main.c): FSS1..FSS6 = -Z, -X, +Y(15 deg to +Z),
    +X, -Y(15 deg to +Z), +Z.

UDP, fire-and-forget: only the latest sample matters, exactly as on the bus.
"""

import struct

import numpy as np

ADS_HOST = "127.0.0.1"
ADS_SENSOR_PORT = 5010   # matches main.c's ADS_SENSOR_UDP_PORT

SENSOR_ID_GPS = 1
SENSOR_ID_FSS = 2

# AdsGpsData, field for field:
#   B fix_mode, B num_SV, H GNSS_Week, d GNSS_TOW,
#   d Latitude, c Lat (N/S), d Longitude, c Long (E/W),
#   d Ellipsoid_altitude, d Mean_Sea_Level_Altitude,
#   d GDOP, d PDOP, d HDOP, d VDOP, d TDOP,
#   d ECEF_X, d ECEF_Y, d ECEF_Z, d ECEF_VX, d ECEF_VY, d ECEF_VZ
GPS_PAYLOAD_FORMAT = "<BBHddcdc13d"
GPS_PACKET_FORMAT = "<B" + GPS_PAYLOAD_FORMAT[1:]
assert struct.calcsize(GPS_PAYLOAD_FORMAT) == 134, "must match sizeof(AdsGpsData)"

# id, slaveId, Q1..Q4, Temp, Eclipse, CrdX, CrdY, VecX..Z, Alpha, Beta
FSS_PACKET_FORMAT = "<BB5HB7h"
assert struct.calcsize(FSS_PACKET_FORMAT) == 2 + 25
FSS_FIELDS = ("Q1", "Q2", "Q3", "Q4", "Temp", "Eclipse",
              "CrdX", "CrdY", "VecX", "VecY", "VecZ", "Alpha", "Beta")

# Firmware thresholds the dashboard state below mirrors (control_defaults.h,
# sitl_task_defs.c).
FSS_Q_MAX_VALID = 10000              # FSS.c zeroes any quadrant above this
FSS_ECLIPSE_QSUM_THRESH = 400        # Q1+Q2+Q3+Q4 below this -> head in eclipse
FSS_VIEW_ANGLE_MAX_CDEG = 3500       # |Alpha|, |Beta| within this -> vector usable

# Per-head state of the last send_fss() call, for the dashboard. Each entry is
# what the firmware's fssTask will conclude from the packet just sent.
last_fss_heads = []


def ads_gps_data(raw):
    """AdsGpsData field values from one RawGpsSample (OBC-side decode).

    ORION integers -> degrees, seconds, metres, m/s. Latitude/longitude are
    sent signed (the firmware copies GPS_Latitude straight into
    AdsHk.PosVector.lat) with the hemisphere characters set to match.
    GNSS_Week is the full week number (utils.c GPS_WEEK_ROLLOVER_OFFSET_WK = 0).
    """
    d = raw.data
    lat = d['Latitude'] * 1e-7
    lon = d['Longitude'] * 1e-7
    return (
        d['fix_mode'], d['num_SV'], d['GNSS_Week'], d['GNSS_TOW'] * .01,
        lat, b"N" if lat >= 0.0 else b"S",
        lon, b"E" if lon >= 0.0 else b"W",
        d['Ellipsoid_altitude'] * .01, d['Mean_Sea_Level_Altitude'] * .01,
        d['GDOP'] * .01, d['PDOP'] * .01, d['HDOP'] * .01, d['VDOP'] * .01, d['TDOP'] * .01,
        d['ECEF_X'] * .01, d['ECEF_Y'] * .01, d['ECEF_Z'] * .01,
        d['ECEF_VX'] * .01, d['ECEF_VY'] * .01, d['ECEF_VZ'] * .01,
    )


def send_gps(sock, raw):
    """Send one RawGpsSample as an AdsGpsData packet. Call once per fix;
    a dropout second (no sample) sends nothing, like the OBC."""
    sock.sendto(struct.pack(GPS_PACKET_FORMAT, SENSOR_ID_GPS, *ads_gps_data(raw)),
                (ADS_HOST, ADS_SENSOR_PORT))


def send_fss(sock, raw, cells=()):
    """Send one GETTLM reply per head of a RawSunSample.

    A dropped receipt (raw.valid False) sends nothing: the firmware then sees
    no reply, as for an unanswered poll. cells: the sun-array cell configs,
    used only to place the dashboard's per-head state.

    Also sets last_fss_heads (and returns it): per head, the ADCS firmware's
    view of the packet just sent -- lit (Q sum >= FSS_ECLIPSE_QSUM_THRESH,
    after FSS.c zeroes out-of-range quadrants), inside the +/-35 deg window,
    and used (both, i.e. folded into sunVectorB).
    """
    global last_fss_heads
    if not raw.valid:
        return last_fss_heads
    heads = []
    for k, sensor in enumerate(raw.sensors):
        r = sensor.data
        sock.sendto(struct.pack(FSS_PACKET_FORMAT, SENSOR_ID_FSS, sensor.slave_id,
                                *(r[name] for name in FSS_FIELDS)),
                    (ADS_HOST, ADS_SENSOR_PORT))

        q_sum = sum(q if q <= FSS_Q_MAX_VALID else 0 for q in (r["Q1"], r["Q2"], r["Q3"], r["Q4"]))
        lit = q_sum >= FSS_ECLIPSE_QSUM_THRESH
        in_window = (abs(r["Alpha"]) <= FSS_VIEW_ANGLE_MAX_CDEG and
                     abs(r["Beta"]) <= FSS_VIEW_ANGLE_MAX_CDEG)
        head = {
            "name": f"FSS{sensor.slave_id - 0x10}",
            "cell": sensor.name,
            "slave": sensor.slave_id,
            "q_sum": int(q_sum),
            "alpha_deg": r["Alpha"] / 100.0,
            "beta_deg": r["Beta"] / 100.0,
            "sensor_eclipse": bool(r["Eclipse"]),    # the FSS's own flag
            "lit": bool(lit),
            "in_window": bool(in_window),
            "used": bool(in_window and lit),
        }
        if k < len(cells):
            normal = np.asarray(cells[k].normal_body, dtype=float)
            head["boresight_body"] = (normal / np.linalg.norm(normal)).tolist()
            head["position"] = list(cells[k].position_body_m)
        heads.append(head)

    last_fss_heads = heads
    return heads
