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


# --- the A/V side: video packets -> files on the card -> DMD frames --------

def _card_with_vid(tmp_path, name, frames=3):
    d = tmp_path / "DMD" / ("_D" + name[0])
    d.mkdir(parents=True, exist_ok=True)
    header = bytes([128, 32, 128, 32, 8, frames, 15]) + bytes(505)
    body = b"\xE0" * 4096 + bytes(4096 * (frames - 1))   # frame 0 red, others black
    (d / (name + ".VID")).write_bytes(header + body)
    return str(tmp_path)


def test_av_finds_the_video_in_either_packet_layout(tmp_path):
    from tools.pinheck_emu.av import Av
    av = Av(_card_with_vid(tmp_path, "ZMA"))
    jetsons = bytes([0]) + b"ZMA" + bytes(3) + b"\xff" + bytes(6) + b"\x01\x02"
    dominos = b"ZMA\x81\x00\xff" + bytes(9) + b"\x02"
    av.packet(jetsons, 8100)
    av.packet(dominos, 9000)
    av.packet(b"\xff" + bytes(14) + b"\x02", 9500)            # stop
    av.packet(b"AT0\x80\x00\xff" + bytes(9) + b"\x02", 9600)  # not on the card
    av.packet(bytes(15) + b"\x01", 9700)                      # a sound: ignored
    assert [(ms, n) for ms, n, _ in av.played] == [
        (8100, "ZMA"), (9000, "ZMA"), (9500, "stop"), (9600, "AT0 (not on card)")]
    v = av.played[0][2]
    assert (v.width, v.height, v.bpp, v.frames) == (128, 32, 8, 3)
    img = v.image(0, pixel_size=2)
    assert img.size == (256, 64)
    assert img.getpixel((0, 0))[0] > 200                      # RGB332 0xE0 = full red


def test_av_contact_sheet(tmp_path):
    from tools.pinheck_emu.av import Av
    av = Av(_card_with_vid(tmp_path, "ATT"))
    sheet = tmp_path / "sheet.png"
    assert not av.contact_sheet(str(sheet))                   # nothing played yet
    av.packet(b"ATT\x81\x00\xff" + bytes(9) + b"\x02", 2800)
    assert av.contact_sheet(str(sheet)) and sheet.stat().st_size > 0


def test_nvram_files_load_only_at_their_size(tmp_path):
    from tools.pinheck_emu.run import NVRAM, _load
    (tmp_path / NVRAM[0][0]).write_bytes(b"\x01" * NVRAM[0][1])
    (tmp_path / NVRAM[1][0]).write_bytes(b"\x01" * 10)          # torn: ignored
    assert _load(str(tmp_path), *NVRAM[0]) == bytearray(b"\x01" * NVRAM[0][1])
    assert _load(str(tmp_path), *NVRAM[1]) is None
    assert _load(None, *NVRAM[0]) is None


def test_idle_loops_are_found_by_their_code():
    from tools.pinheck_emu.pic32 import DELAY, WAIT, find_idle_loops, find_millis_gp_offset
    flash = bytearray(0x3000)
    # delay(): lw s1/v0,millis(gp) ... loop: jal sched; nop; lw v0,millis(gp);
    # subu; sltu; bnez v0,loop  (millis at gp-0x7984, as in Jetsons V004)
    struct.pack_into("<6I", flash, 0x1100, 0x0F400000, 0, 0x8F82867C, 0x00511023,
                     0x0050102B, 0x1440FFFA)
    # the millis getter, and a while (millis() == last); loop calling it
    struct.pack_into("<3I", flash, 0x2000, 0x8F82867C, 0x03E00008, 0)
    jal = 0x0C000000 | ((0x9D002000 >> 2) & 0x3FFFFFF)
    struct.pack_into("<5I", flash, 0x1200, jal, 0, 0x8F8384FC, 0x1043FFFC, 0)
    # the same loop on a getter of something else is not idle
    struct.pack_into("<3I", flash, 0x2100, 0x8F828600, 0x03E00008, 0)
    jal2 = 0x0C000000 | ((0x9D002100 >> 2) & 0x3FFFFFF)
    struct.pack_into("<5I", flash, 0x1300, jal2, 0, 0x8F8384FC, 0x1043FFFC, 0)
    gpoff = find_millis_gp_offset(bytes(flash))
    assert gpoff == -0x7984
    assert find_idle_loops(bytes(flash), gpoff) == {0x9D001114: DELAY, 0x9D00120C: WAIT}


# --- switches: the cabinet shift register and the playfield matrix ---------

class PinPic:
    def __init__(self):
        self.on_lat = []
        self.pins_in = {p: 0xFFFF for p in "ABCDEFG"}
        self.lat = {p: 0 for p in "ABCDEFG"}

    def write(self, port, value):
        old, self.lat[port] = self.lat[port], value
        for f in self.on_lat:
            f(port, old, value)


def read_cabinet(pic):
    """houseKeeping()'s loop: 16 x (clock E0, read F0), MSB first, inverted;
    then latch G8 low-high."""
    cab = 0
    for _ in range(16):
        pic.write("E", 1)
        pic.write("E", 0)
        cab = (cab << 1) | (0 if pic.pins_in["F"] & 1 else 1)
    pic.write("G", 0)
    pic.write("G", 1 << 8)
    return cab


def test_cabinet_switches_read_as_the_game_reads_them():
    from tools.pinheck_emu.board import Board
    pic = PinPic()
    pic.write("G", 1 << 8)
    b = Board(pic)
    assert read_cabinet(pic) == 1 << 1            # door shut
    b.set("start")
    read_cabinet(pic)                             # pressed after the last latch
    assert read_cabinet(pic) == (1 << 1) | (1 << 12)
    b.set("start", False)
    b.set("coin")
    read_cabinet(pic)
    assert read_cabinet(pic) == (1 << 1) | (1 << 7)   # the game's [E99000]: 00 82


def test_matrix_switch_shows_on_its_row_only():
    from tools.pinheck_emu.board import Board
    pic = PinPic()
    b = Board(pic)
    b.set(10)                                     # row 1, column 2
    b.set(63)
    pic.write("D", 0xFF00 & ~(1 << 9))            # row 1 driven low
    assert pic.pins_in["D"] & 0xFF == 0xFF & ~(1 << 2)
    pic.write("D", 0xFF00 & ~(1 << 8))            # row 0: nothing closed
    assert pic.pins_in["D"] & 0xFF == 0xFF
    pic.write("D", 0xFF00 & ~(1 << 15))           # row 7
    assert pic.pins_in["D"] & 0xFF == 0x7F
    b.set(63, False)
    assert pic.pins_in["D"] & 0xFF == 0xFF


def test_serial_monitor_input():
    pic = bare_machine()
    pic.sfr[0x1F881060] = 1 << 27                 # U1RX enabled (no handler: just flags)
    pic.serial_in(b"[E")
    sta = lambda: pic._read(None, 0x6010, 4, None)
    rx = lambda: pic._read(None, 0x6030, 4, None)
    assert sta() & 1                              # URXDA
    assert (rx(), rx()) == (ord("["), ord("E"))
    assert not sta() & 1
