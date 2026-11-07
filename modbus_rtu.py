"""Minimal, dependency-light Modbus RTU master (only needs pyserial).

Written by hand rather than using pymodbus so that scanning gets full control
over exception codes, timeouts and raw frames.
"""
from __future__ import annotations

import struct
import time

import serial

EXCEPTION_NAMES = {
    1: "ILLEGAL_FUNCTION",
    2: "ILLEGAL_DATA_ADDRESS",
    3: "ILLEGAL_DATA_VALUE",
    4: "SLAVE_DEVICE_FAILURE",
    5: "ACKNOWLEDGE",
    6: "SLAVE_DEVICE_BUSY",
    11: "GATEWAY_TARGET_FAILED",
}

FC_READ_COILS = 0x01
FC_READ_DISCRETE_INPUTS = 0x02
FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_SINGLE_REGISTER = 0x06


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class ModbusError(Exception):
    pass


class ModbusException(ModbusError):
    """The slave answered with a Modbus exception response."""

    def __init__(self, function: int, code: int):
        self.function = function
        self.code = code
        super().__init__(f"FC{function:02d} exception {code} ({EXCEPTION_NAMES.get(code, '?')})")


class ModbusTimeout(ModbusError):
    pass


class ModbusRTU:
    def __init__(self, port: str = "/dev/ttyUSB1", baudrate: int = 9600, slave: int = 1,
                 timeout: float = 0.5, parity: str = "N", stopbits: int = 1, debug: bool = False):
        self.slave = slave
        self.timeout = timeout
        self.debug = debug
        self.ser = serial.Serial(port, baudrate=baudrate, bytesize=8, parity=parity,
                                 stopbits=stopbits, timeout=0.02)
        # 3.5 character silent interval (min 1.75 ms per spec above 19200 bps)
        char_time = 11.0 / baudrate
        self.t35 = max(3.5 * char_time, 0.00175)
        self._last = 0.0

    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ------------------------------------------------------------------ core
    def _transact(self, pdu: bytes, expected_len_fn) -> bytes:
        frame = bytes([self.slave]) + pdu
        frame += struct.pack("<H", crc16(frame))
        # respect inter-frame silence
        wait = self.t35 + 0.005 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        if self.debug:
            print("TX", frame.hex(" "))

        buf = b""
        deadline = time.monotonic() + self.timeout
        need = None
        while time.monotonic() < deadline:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                # Some RS485 adapters echo the TX frame; strip it.
                if buf.startswith(frame):
                    buf = buf[len(frame):]
                if len(buf) >= 2:
                    if buf[1] & 0x80:
                        need = 5
                    elif len(buf) >= 3:
                        need = expected_len_fn(buf)
                if need is not None and len(buf) >= need:
                    break
        self._last = time.monotonic()
        if self.debug:
            print("RX", buf.hex(" ") if buf else "<nothing>")
        if not buf:
            raise ModbusTimeout("no response")
        if need is None or len(buf) < need:
            raise ModbusTimeout(f"incomplete response: {buf.hex(' ')}")
        resp = buf[:need]
        if crc16(resp[:-2]) != struct.unpack("<H", resp[-2:])[0]:
            raise ModbusError(f"CRC error: {resp.hex(' ')}")
        if resp[0] != self.slave:
            raise ModbusError(f"wrong slave id in response: {resp.hex(' ')}")
        if resp[1] & 0x80:
            raise ModbusException(resp[1] & 0x7F, resp[2])
        return resp[1:-2]  # PDU

    # ------------------------------------------------------------- functions
    def read_registers(self, fc: int, address: int, count: int) -> list[int]:
        """FC03/FC04. `address` is the 0-based PDU address."""
        pdu = struct.pack(">BHH", fc, address, count)
        resp = self._transact(pdu, lambda b: 3 + b[2] + 2)
        n = resp[1]
        if n != 2 * count:
            raise ModbusError(f"byte count {n} != {2 * count}")
        return list(struct.unpack(f">{count}H", resp[2:2 + n]))

    def read_holding(self, address: int, count: int = 1) -> list[int]:
        return self.read_registers(FC_READ_HOLDING, address, count)

    def read_input(self, address: int, count: int = 1) -> list[int]:
        return self.read_registers(FC_READ_INPUT, address, count)

    def read_bits(self, fc: int, address: int, count: int) -> list[bool]:
        """FC01/FC02. `address` is the 0-based PDU address."""
        pdu = struct.pack(">BHH", fc, address, count)
        resp = self._transact(pdu, lambda b: 3 + b[2] + 2)
        n = resp[1]
        data = resp[2:2 + n]
        return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]

    def read_discrete(self, address: int, count: int = 1) -> list[bool]:
        return self.read_bits(FC_READ_DISCRETE_INPUTS, address, count)

    def read_coils(self, address: int, count: int = 1) -> list[bool]:
        return self.read_bits(FC_READ_COILS, address, count)

    def write_register(self, address: int, value: int) -> None:
        pdu = struct.pack(">BHH", FC_WRITE_SINGLE_REGISTER, address, value & 0xFFFF)
        self._transact(pdu, lambda b: 8)


def to_signed(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def regs_to_string(regs: list[int]) -> str:
    raw = b"".join(struct.pack(">H", r) for r in regs)
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
