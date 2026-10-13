"""Hardware-style sensor interfaces, independent of navigation and firmware.

These are generic digital sensors, not emulations of a named manufacturer's
SPI/UART protocol. Integer counts are in sensor axes. to_bytes/from_bytes use
explicit little-endian layouts without native C padding. Simulation timestamps
are transport metadata, not truth values or sensor error diagnostics.
"""
from dataclasses import dataclass, asdict
import struct


@dataclass(frozen=True)
class RawVectorSample:
    kind: str                         # 'gyro' or 'mag'
    t_meas_s: float
    t_arrival_s: float
    counts: tuple                     # signed sensor-axis X/Y/Z registers
    valid: bool
    saturated: bool
    FORMAT = '<BBdd3iBB'

    def to_bytes(self):
        return struct.pack(self.FORMAT, 1, {'gyro': 1, 'mag': 2}[self.kind],
                           self.t_meas_s, self.t_arrival_s, *self.counts,
                           self.valid, self.saturated)

    @classmethod
    def from_bytes(cls, data):
        version, kind, tm, ta, x, y, z, valid, saturated = struct.unpack(cls.FORMAT, data)
        if version != 1 or kind not in (1, 2) or valid not in (0, 1) or saturated not in (0, 1):
            raise ValueError('Invalid vector sensor packet')
        return cls({1: 'gyro', 2: 'mag'}[kind], tm, ta, (x, y, z), bool(valid), bool(saturated))


@dataclass(frozen=True)
class RawSunCell:
    name: str
    adc_counts: int
    saturated: bool


@dataclass(frozen=True)
class RawSunSample:
    t_meas_s: float
    t_arrival_s: float
    valid: bool
    adc_bits: int
    cells: tuple

    def to_bytes(self):
        data = struct.pack('<BddBBH', 1, self.t_meas_s, self.t_arrival_s,
                           self.valid, self.adc_bits, len(self.cells))
        for cell in self.cells:
            name = cell.name.encode('utf-8')
            data += struct.pack('<H', len(name)) + name
            data += struct.pack('<HB', cell.adc_counts, cell.saturated)
        return data

    @classmethod
    def from_bytes(cls, data):
        header = struct.Struct('<BddBBH')
        version, tm, ta, valid, bits, size = header.unpack_from(data)
        if version != 1 or valid not in (0, 1) or not 2 <= bits <= 16:
            raise ValueError('Invalid sun sensor packet')
        offset, cells = header.size, []
        for _ in range(size):
            length, = struct.unpack_from('<H', data, offset)
            offset += 2
            name = data[offset:offset+length].decode('utf-8')
            offset += length
            counts, saturated = struct.unpack_from('<HB', data, offset)
            offset += 3
            if counts >= 2**bits or saturated not in (0, 1):
                raise ValueError('Invalid photocell register')
            cells.append(RawSunCell(name, counts, bool(saturated)))
        if offset != len(data):
            raise ValueError('Unexpected sun packet length')
        return cls(tm, ta, bool(valid), bits, tuple(cells))


@dataclass(frozen=True)
class RawGpsSample:
    week: int
    tow: float
    t_meas_s: float
    t_arrival_s: float
    fix_type: int
    num_sv: int
    pdop: float
    lat_deg: float
    lon_deg: float
    alt_ell_m: float
    pos_ecef_m: tuple
    vel_ecef_m_s: tuple
    vel_enu_m_s: tuple
    h_acc_m: float
    v_acc_m: float
    latency_s: float
    FORMAT = '<BIdddBB16d'

    def to_bytes(self):
        return struct.pack(self.FORMAT, 1, self.week, self.tow,
            self.t_meas_s, self.t_arrival_s, self.fix_type, self.num_sv,
            self.pdop, self.lat_deg, self.lon_deg, self.alt_ell_m,
            *self.pos_ecef_m, *self.vel_ecef_m_s, *self.vel_enu_m_s,
            self.h_acc_m, self.v_acc_m, self.latency_s)

    @classmethod
    def from_bytes(cls, data):
        v = struct.unpack(cls.FORMAT, data)
        if v[0] != 1:
            raise ValueError('Unsupported GPS packet version')
        return cls(v[1], v[2], v[3], v[4], v[5], v[6], *v[7:11],
                   tuple(v[11:14]), tuple(v[14:17]), tuple(v[17:20]), *v[20:23])


def packet_dict(packet):
    """JSON/debug representation of only the public sensor interface."""
    return None if packet is None else asdict(packet)
