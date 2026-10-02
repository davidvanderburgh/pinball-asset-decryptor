"""I2C devices on the pinHeck game CPU's bus (PAD-320).

The colour games (Jetsons, Domino's) talk to two chips on I2C1 besides the
Propeller link:
* 0x50, a 24LC256-style serial EEPROM (32 KB, 16-bit word address, then
  data; reads run on from the address). The game reads longs from it with
  ``Wire.requestFrom(0x50, 4)`` and waits forever if it does not answer.
* 0x68, a DS1307-style real-time clock (register pointer, then BCD time).
"""
import time

from tools.pinheck_emu.pic32 import I2CDevice


class Eeprom24(I2CDevice):
    def __init__(self, data=None, size=0x8000):
        # a blank part reads 0xFF; the game then writes its defaults
        self.data = data if data is not None else bytearray(b"\xFF" * size)
        self.addr = 0
        self._header = 0            # address bytes still to come in a write

    def start(self, read):
        self._header = 0 if read else 2
        return True

    def write(self, byte):
        if self._header:
            self.addr = byte << 8 if self._header == 2 else self.addr | byte
            self._header -= 1
        else:
            self.data[self.addr % len(self.data)] = byte
            # page writes wrap inside the 64-byte page
            self.addr = (self.addr & ~63) | ((self.addr + 1) & 63)
        return True

    def read(self):
        b = self.data[self.addr % len(self.data)]
        self.addr = (self.addr + 1) & 0xFFFF
        return b


class Rtc1307(I2CDevice):
    def __init__(self, clock=time.localtime):
        self.clock = clock
        self.ptr = 0
        self.ram = bytearray(64)
        self._first = False

    def start(self, read):
        self._first = not read
        if read:
            t = self.clock()
            bcd = lambda v: ((v // 10) << 4) | (v % 10)
            self.ram[0:7] = bytes([bcd(t.tm_sec), bcd(t.tm_min), bcd(t.tm_hour),
                                   t.tm_wday + 1, bcd(t.tm_mday), bcd(t.tm_mon),
                                   bcd(t.tm_year % 100)])
        return True

    def write(self, byte):
        if self._first:
            self.ptr, self._first = byte & 63, False
        else:
            self.ram[self.ptr] = byte
            self.ptr = (self.ptr + 1) & 63
        return True

    def read(self):
        b = self.ram[self.ptr]
        self.ptr = (self.ptr + 1) & 63
        return b
