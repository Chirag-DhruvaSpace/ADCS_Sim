"""
sim_state_sender.py

Sends the dynamics/orbital-motion simulator's current "ideal" state to the
SITL ADS C process over UDP, matching sim_link.c's SimStatePacket layout
exactly: 13 doubles, little-endian, no padding.

    pos_eci[3], vel_eci[3], quat[4] (w,x,y,z), body_rate[3]  = 104 bytes

UDP, not TCP -- deliberately -- since only the LATEST state matters each
cycle; no need for guaranteed delivery/ordering the way a command channel
would need.
"""

import struct

ADS_HOST = "127.0.0.1"
ADS_SIM_PORT = 5002   # separate from the ChangeMode/GetTlm TCP port (5001)

PACKET_FORMAT = "<13d"  # little-endian, 13 doubles


def send_state(sock, pos_eci, vel_eci, quat, body_rate, unix_time, mag_body):
    payload = struct.pack(
        "<17d",  # was <13d
        pos_eci[0], pos_eci[1], pos_eci[2],
        vel_eci[0], vel_eci[1], vel_eci[2],
        quat[0], quat[1], quat[2], quat[3],
        body_rate[0], body_rate[1], body_rate[2],
        unix_time,
        mag_body[0], mag_body[1], mag_body[2],
    )
    sock.sendto(payload, (ADS_HOST, ADS_SIM_PORT))
