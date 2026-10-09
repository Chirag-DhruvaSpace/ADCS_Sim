# made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
import socket
import struct
import time
import unittest
from unittest.mock import patch
import numpy as np

class FirmwareTests(unittest.TestCase):
    def test_real_udp_packets_drive_torque_and_status(self):
        original_socket = socket.socket
        class RedirectSocket:
            def __init__(self, *args, **kwargs): self.sock = original_socket(*args, **kwargs)
            def bind(self, address): self.sock.bind(('127.0.0.1', 0))
            def __getattr__(self, name): return getattr(self.sock, name)
        state_receiver = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
        wheel_receiver = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = original_socket(socket.AF_INET, socket.SOCK_DGRAM)
        state_receiver.bind(('127.0.0.1',0)); wheel_receiver.bind(('127.0.0.1',0))
        state_receiver.settimeout(2); wheel_receiver.settimeout(2)
        from firmware_sitl_adapter import FirmwareLink
        with patch('socket.socket', RedirectSocket):
            link = FirmwareLink()
        # made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag
        try:
            link.telemetry.ADS_SIM_PORT = state_receiver.getsockname()[1]
            link.link.TLM_SEND_PORT = wheel_receiver.getsockname()[1]
            self.assertEqual(link.metadata(0, {}, np.zeros(3))['custom_pointing_status'],'red')
            sender.sendto(struct.pack('<3d',0,0,2.5),link.link._cmd_sock.getsockname())
            sender.sendto(struct.pack('<B3f',2,.1,.2,.3),link.link._mode_sock.getsockname())
            time.sleep(.01)
            q = np.array([1.,0,0,0]); field = np.array([0.,0,2e-5])
            wheels,dipole = link.tick([7e6,0,0],[0,7500,0],q,[0,0,0],123,field)
            np.testing.assert_allclose(wheels,[.0025,0,0,0])
            np.testing.assert_allclose(dipole,[.1,.2,.3],rtol=1e-6)
            # Unsupported wheel speed, malformed packets and NaNs must not
            # change the accepted actuator state or count as fresh input.
            sender.sendto(b'invalid',link.link._cmd_sock.getsockname())
            sender.sendto(struct.pack('<3d',1,1,99),link.link._cmd_sock.getsockname())
            sender.sendto(struct.pack('<B3f',2,float('nan'),0,0),link.link._mode_sock.getsockname())
            accepted_at = link.received_at
            time.sleep(.01)
            held_wheels,held_dipole = link.tick([7e6,0,0],[0,7500,0],q,[0,0,0],123,field)
            np.testing.assert_array_equal(held_wheels,wheels)
            np.testing.assert_array_equal(held_dipole,dipole)
            self.assertEqual(link.received_at,accepted_at)
            state = struct.unpack('<17d',state_receiver.recvfrom(1024)[0])
            self.assertEqual(state[13],123)
            self.assertEqual(len(state),17)
            import satellite_rotational_dynamics_var_mag_field as dynamics
            import control_states as cs
            import torque_distribution as td
            dynamics.set_firmware_tick(wheels,dipole)
            with patch.dict(cs.mode,value='FIRMWARE_SITL'), patch.object(dynamics.cd,'DISTURBANCES_ENABLED',False):
                derivative = dynamics.rotational_equations_of_motion(0,[1,0,0,0,0,0,0],field)
            expected = dynamics.I_inv @ (td.A@wheels + np.cross(dipole,field))
            np.testing.assert_allclose(derivative[4:7],expected)
            link.received_at = link.event_at = time.monotonic()
            self.assertEqual(link.metadata(0, {'NadirPoint':0},np.zeros(3))['custom_pointing_status'],'green')
            link.event_at = time.monotonic()-3
            self.assertEqual(link.metadata(.5, {'NadirPoint':0},np.zeros(3))['custom_pointing_status'],'yellow')
            self.assertEqual(link.metadata(1.1, {'NadirPoint':0},np.zeros(3))['custom_pointing_status'],'blue')
            link.received_at = time.monotonic()-3
            self.assertEqual(link.metadata(1.2, {'NadirPoint':0},np.zeros(3))['custom_pointing_status'],'red')
            link.finish_tick(.1)
            for _ in range(4): self.assertEqual(len(wheel_receiver.recvfrom(1024)[0]),24)
        finally:
            for sock in [sender,state_receiver,wheel_receiver,link.state_socket,link.link._cmd_sock,link.link._mode_sock,link.link._tlm_sock]: sock.close()
