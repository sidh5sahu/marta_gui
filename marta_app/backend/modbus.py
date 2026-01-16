import struct
import socket
import time

# Try pymodbus, fallback to minimal
_HAVE_PYMODBUS = False
try:
    from pymodbus.client import ModbusTcpClient as _PMClient
    _HAVE_PYMODBUS = True
except Exception:
    _HAVE_PYMODBUS = False

# ---------- Minimal Modbus fallback ----------
class MinimalModbusTCP:
    def __init__(self, host, port=502, unit_id=1, timeout=3.0):
        self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
        self.sock = None
        self._tx_id = 0

    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            return True
        except OSError:
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _next_tid(self):
        self._tx_id = (self._tx_id + 1) & 0xFFFF
        return self._tx_id

    def _recvn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _request(self, pdu):
        if not self.sock:
            raise RuntimeError("Not connected")
        mbap = struct.pack(">HHHB", self._next_tid(), 0, len(pdu) + 1, self.unit_id)
        self.sock.sendall(mbap + pdu)
        hdr = self._recvn(7)
        if hdr is None:
            raise RuntimeError("No response")
        _, _, length = struct.unpack(">HHH", hdr[:6])
        body = self._recvn(length - 1)
        return body

    def read_holding_registers(self, address, count=1, slave=1):
        try:
            self.unit_id = slave
            pdu = struct.pack(">BHH", 3, address, count)
            body = self._request(pdu)
            if body[0] & 0x80:
                return _MBErrorResult()
            bc = body[1]
            data = body[2:2 + bc]
            regs = list(struct.unpack(">" + "H" * (bc // 2), data))
            return _MBResult(regs)
        except Exception:
            return _MBErrorResult()

    def write_register(self, address, value=0, slave=1):
        try:
            self.unit_id = slave
            pdu = struct.pack(">BHH", 6, address, value & 0xFFFF)
            body = self._request(pdu)
            return not (body[0] & 0x80)
        except Exception:
            return False

    def write_registers(self, address, values=None, slave=1):
        if values is None: values = []
        try:
            self.unit_id = slave
            qty = len(values)
            pdu = struct.pack(">BHHB", 16, address, qty, qty * 2)
            pdu += struct.pack(">" + "H" * qty, *values)
            body = self._request(pdu)
            return not (body[0] & 0x80)
        except Exception:
            return False

class _MBResult:
    def __init__(self, regs): self.registers = regs
    def isError(self): return False

class _MBErrorResult:
    def isError(self): return True
    @property
    def registers(self): return []

def get_modbus_client(ip, port=502):
    if _HAVE_PYMODBUS:
        try:
            return _PMClient(host=ip, port=port)
        except Exception:
            return MinimalModbusTCP(ip, port=port)
    return MinimalModbusTCP(ip, port=port)

# ---------- Helpers ----------
def _float_to_u16pair(v): return struct.unpack("<HH", struct.pack("<f", v))
def _u16pair_to_float(p): return struct.unpack("<f", struct.pack("<HH", *p))[0]

def write_float(c, reg, val): 
    return c.write_registers(reg, values=_float_to_u16pair(val), slave=1)

def read_float(c, reg):
    rr = c.read_holding_registers(reg, count=2, slave=1)
    return None if rr.isError() else _u16pair_to_float(rr.registers)

def write_u16(c, reg, val): 
    return c.write_register(reg, value=(val & 0xFFFF), slave=1)

# ---------- Constants ----------
REGISTER_TT = [126, 128, 130, 132, 134, 136]      # TT01..TT06
REGISTER_TEMP_SETPOINT = 310
REGISTER_PUMP_SPEED = 312
REGISTER_CONTROL_BITS = 305
BIT_CHILLER = 0
BIT_CO2 = 1

SP_MIN = -30.0
SP_MAX = 15.0

def build_control_word(chiller, co2):
    w = 0
    if chiller: w |= (1 << BIT_CHILLER)
    if co2:     w |= (1 << BIT_CO2)
    return w

def write_control_word(c, chiller, co2):
    word_to_write = build_control_word(chiller, co2)
    ok = write_u16(c, REGISTER_CONTROL_BITS, word_to_write)
    return ok
