"""The pinHeck game-CPU emulator's pieces (PAD-320), on synthetic input.

No game files: the real PRGs are Spooky's and never ship with PAD. A real
boot (Jetsons V004 to the attract cycle) is ``python -m
tools.pinheck_emu.run <JET_V004.PRG>``; these tests pin the machinery that
run depends on - the bit-banged Propeller link, the handshake and EEPROM
replies, the I2C devices, and interrupt delivery on a CPU emulator that has
no interrupt controller of its own.
"""
import faulthandler
import struct

import pytest

pytest.importorskip("unicorn")


@pytest.fixture(autouse=True)
def _quiet_unicorn_mips():
    # Unicorn's MIPS core raises and handles its own access violations on
    # Windows when a counted run stops (the spurious READ_UNMAPPED pic32
    # ignores); faulthandler would print each one as a "fatal exception".
    was = faulthandler.is_enabled()
    faulthandler.disable()
    yield
    if was:
        faulthandler.enable()

from tools.pinheck_emu import proplink
from tools.pinheck_emu.i2c import Eeprom24, Rtc1307
from tools.pinheck_emu.pic32 import Pic32
from tools.pinheck_emu.proplink import CLK, SDI, SDO, PropLink


class FakePic:
    """Just the pins: what PropLink needs from Pic32."""
    def __init__(self):
        self.on_lat = []
        self.pins_in = {"F": 0xFFFF}
        self.latf = 0

    def set(self, bits, on):
        old = self.latf
        self.latf = old | bits if on else old & ~bits
        for f in self.on_lat:
            f("F", old, self.latf)

    def exchange(self, out):
        """The PIC side of one packet, as exchangeData() does it."""
        back = bytearray(16)
        for i, byte in enumerate(out):
            for bit in range(8):
                self.set(SDO, (byte >> bit) & 1)
                self.set(CLK, True)
                self.set(CLK, False)
                back[i] |= (1 if self.pins_in["F"] & SDI else 0) << bit
        return bytes(back)


SYNC = bytes([0xAA]) + bytes(range(0x30, 0x3E)) + b"#"


def test_link_frames_packets_and_answers_the_handshake_on_the_next_one():
    pic = FakePic()
    link = PropLink(pic)
    first = pic.exchange(SYNC)
    assert link.packets == [SYNC]
    assert first[14:] != b"\xAA\xAA"         # nothing ready on the first packet
    second = pic.exchange(SYNC)
    # Domino's checks the echoed pattern, Jetsons only the two 0xAAs
    assert second == bytes(range(0x30, 0x3E)) + b"\xAA\xAA"


def test_link_eeprom_write_then_read_back():
    pic = FakePic()
    PropLink(pic)
    pic.exchange(struct.pack("<II", 5, 0x0400BAFA) + bytes(7) + b"\x20")
    assert pic.exchange(bytes(15) + b"\xFF")[15] == 0x42       # write done
    pic.exchange(struct.pack("<I", 5) + bytes(10) + b"\x07\x21")
    back = pic.exchange(bytes(15) + b"\xFF")
    assert struct.unpack("<I", back[:4])[0] == 0x0400BAFA
    assert back[14:] == bytes([0x87, 0xAD])                   # tag | 0x80, frame end
    pic.exchange(bytes(15) + b"\x22")
    assert pic.exchange(bytes(15) + b"\xFF") == bytes(16)      # flushed


def test_link_unread_eeprom_is_blank():
    pic = FakePic()
    PropLink(pic)
    pic.exchange(struct.pack("<I", 8191) + bytes(10) + b"\x01\x21")
    assert pic.exchange(bytes(15) + b"\xFF")[:4] == b"\xFF" * 4
    assert proplink.EEPROM_LONGS == 8192


def test_i2c_eeprom_16_bit_address_write_and_sequential_read():
    e = Eeprom24()
    e.start(False)
    for b in (0x7F, 0xD0, 0x00, 0x57, 0x4F, 0x43):
        assert e.write(b)
    e.stop()
    e.start(False)
    e.write(0x7F)
    e.write(0xD0)
    e.start(True)
    assert bytes(e.read() for _ in range(4)) == b"\x00WOC"
    assert e.data[0] == 0xFF


def test_i2c_rtc_reads_bcd_time():
    import time
    t = time.struct_time((2026, 10, 2, 12, 34, 56, 4, 275, 0))
    r = Rtc1307(clock=lambda: t)
    r.start(False)
    r.write(0)
    r.start(True)
    assert [r.read() for _ in range(7)] == [0x56, 0x34, 0x12, 5, 0x02, 0x10, 0x26]


# A bare program: enable interrupts, spin until the Timer2 handler sets a
# flag, then read CP0 Count and park. The handler sits right in vector 8's
# slot and ends in eret, as a game's does.
MAIN = [0x40806000,     # mtc0 zero, Status (clear ERL/BEV)
        0x41606020,     # ei
        0x3C08A000,     # lui t0, 0xA000
        0x8D090100,     # lw t1, 0x100(t0)       <- spin
        0x1120FFFE,     # beq t1, zero, spin
        0x00000000,
        0x400A4800,     # mfc0 t2, Count
        0xAD0A0104,     # sw t2, 0x104(t0)
        0x1000FFFF,     # b .
        0x00000000]
T2_HANDLER = [0x3C1AA000,   # lui k0, 0xA000
              0x241B0001,   # li k1, 1
              0xAF5B0100,   # sw k1, 0x100(k0)
              0x3C1ABF88,   # lui k0, 0xBF88
              0x241B0100,   # li k1, 1 << 8
              0xAF5B1034,   # sw k1, IFS0CLR
              0x42000018]   # eret


def bare_machine():
    flash = bytearray(0x1100)
    struct.pack_into("<%dI" % len(T2_HANDLER), flash, 0x300, *T2_HANDLER)
    struct.pack_into("<%dI" % len(MAIN), flash, 0x1000, *MAIN)
    return Pic32(bytes(flash), chipkit=False)


def test_timer_interrupt_runs_the_handler_and_returns_to_the_main_code():
    pic = bare_machine()
    pic.sfr[0x1F800820] = 9999          # PR2: 8 kHz, as the lamp driver runs
    pic.sfr[0x1F800800] = 0x8000        # T2 on
    pic.sfr[0x1F881060] = 1 << 8        # IEC0: T2
    pic.sfr[0x1F8810B0] = 6 << 2        # IPC2: priority 6
    pic.run_ms(2)
    ram = lambda a: struct.unpack("<I", pic.mu.mem_read(a, 4))[0]
    assert ram(0x100) == 1
    assert 8 <= pic.irq_counts[8] <= 17
    # back in the main code (parked at "b ."), and Count followed the clock
    assert pic.pc == 0x9D001020
    assert 0 < ram(0x104) <= pic.clock // 2


def test_no_interrupt_while_disabled():
    pic = bare_machine()
    pic.sfr[0x1F800820] = 9999
    pic.sfr[0x1F800800] = 0x8000
    pic.sfr[0x1F881060] = 0             # T2 not enabled in IEC0
    pic.sfr[0x1F8810B0] = 6 << 2
    pic.run_ms(1)
    assert pic.irq_counts[8] == 0
    assert struct.unpack("<I", pic.mu.mem_read(0x100, 4))[0] == 0


def test_i2c_master_reaches_the_device_and_naks_an_empty_address():
    pic = bare_machine()
    pic.i2c_devices[0x50] = dev = Eeprom24()
    w = lambda off, v: pic._write(None, 0x5300 + off, 4, v, None)
    w(0x08, 1)                  # I2C1CONSET: SEN
    w(0x50, 0x50 << 1)          # address, write
    assert not pic.sfr[0x1F805310] & (1 << 15)      # ACK
    for b in (0x00, 0x10, 0xAB):
        w(0x50, b)
    w(0x08, 4)                  # PEN
    assert dev.data[0x10] == 0xAB
    assert pic.i2c_log[-1] == (0x50, "w", b"\x00\x10\xab")
    w(0x08, 1)
    w(0x50, 0x68 << 1)          # nobody at 0x68 here
    assert pic.sfr[0x1F805310] & (1 << 15)          # NAK
