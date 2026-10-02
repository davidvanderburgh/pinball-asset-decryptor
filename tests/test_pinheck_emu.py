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

    def watch(self, ports, f):
        self.on_lat.append(lambda port, old, new: port in ports and f(port, old, new))

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
    card = _card_with_vid(tmp_path, "ZMA")
    jet = Av(card)
    jet.packet(bytes([3]) + b"ZMA" + bytes(3) + b"\xff" + bytes(6) + b"\x01\x02", 8100)
    assert jet.layout == "jetsons" and 3 in jet.layers
    av = Av(card)
    av.packet(b"ZMA\x81\x00\xff" + bytes(9) + b"\x02", 9000)
    av.packet(b"\xff" + bytes(14) + b"\x02", 9500)            # videoPriority(0)
    av.packet(b"AT0\x80\x00\xff" + bytes(9) + b"\x02", 9600)  # not on the card
    av.packet(bytes(15) + b"\x01", 9700)                      # a sound: ignored
    assert av.layout == "amh" and av.layers[0][2] is True     # attribute bit 7 = loop
    assert [(ms, n) for ms, n, _ in av.played] == [
        (9000, "ZMA"), (9500, "priority"), (9600, "AT0 (not on card)")]
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

    def watch(self, ports, f):
        self.on_lat.append(lambda port, old, new: port in ports and f(port, old, new))

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


def test_balls_follow_the_load_and_plunger_coils():
    from tools.pinheck_emu.board import Balls, Board
    from tools.pinheck_emu.games import GAMES, coil_pins
    pic = PinPic()
    pic.on_ms = []
    b = Board(pic)
    balls = Balls(b, GAMES["JET"])
    assert b.matrix == {34, 35} and 10 in b.cabinet       # full trough, ball at the eject point
    tick = lambda ms: [f(ms) for f in pic.on_ms]
    pulse = lambda name: (pic.write(coil_pins(GAMES["JET"])[name][0], coil_pins(GAMES["JET"])[name][1]),
                          pic.write(coil_pins(GAMES["JET"])[name][0], 0))
    pulse("LOAD COIL")
    assert b.matrix == {35} and 32 not in b.matrix         # rolling
    tick(Balls.ROLL_MS)
    assert b.matrix == {35, 32}
    pulse("LOAD COIL")                                     # lane taken: nothing moves
    assert balls.in_trough == 1
    pulse("PLUNGER")
    assert 32 not in b.matrix and balls.in_play == 1
    assert balls.drain() and not balls.drain()
    tick(2 * Balls.ROLL_MS)
    assert b.matrix == {34, 35} and balls.in_trough == 2
    b.set("launch")
    assert 2 in b.cabinet                                  # Jetsons' launch button


def _vid(tmp_path, name, frames, colour):
    """A 128x32 8bpp VID whose frame n is all ``colour[n]``."""
    d = tmp_path / "DMD" / ("_D" + name[0])
    d.mkdir(parents=True, exist_ok=True)
    header = bytes([128, 32, 128, 32, 8, frames, 15]) + bytes(505)
    (d / (name + ".VID")).write_bytes(header + b"".join(bytes([c]) * 4096 for c in colour))


def test_screen_plays_loops_and_queues(tmp_path):
    from tools.pinheck_emu.av import FPS, Av
    _vid(tmp_path, "AAA", 3, (0xE0, 0x1C, 0x03))          # red, green, blue
    _vid(tmp_path, "BBB", 1, (0xFF,))
    av = Av(str(tmp_path))
    frame_ms = 1000 // FPS + 1
    av.packet(b"AAA\x00\x00\x01" + bytes(9) + b"\x02", 0)    # play once
    av.packet(b"BBB\x80\x00\x01" + bytes(9) + b"\x06", 10)   # then BBB, looping
    px = lambda ms: av.frame(ms).getpixel((5, 5))
    assert px(0)[0] > 200 and px(frame_ms)[1] > 200 and px(2 * frame_ms)[2] > 200
    assert px(10 * frame_ms) == (255, 255, 255)              # queued BBB took over
    assert px(500 * frame_ms) == (255, 255, 255)             # and loops
    av.packet(b"AAA\x80\x00\x01" + bytes(9) + b"\x02", 1000)
    assert px(1000 + 3 * frame_ms)[0] > 200                  # looped back to frame 0


def test_screen_draws_text_until_the_next_video(tmp_path):
    from tools.pinheck_emu.av import Av
    _vid(tmp_path, "AAA", 1, (0,))
    av = Av(str(tmp_path))
    av.packet(b"AAA\x00\x00\x01" + bytes(9) + b"\x02", 0)
    av.packet(bytes([0x11]) + b"HI" + bytes(12) + b"\x12", 5)    # column 1, row 1
    lit = [(x, y) for x in range(128) for y in range(32) if av.frame(10).getpixel((x, y)) != (0, 0, 0)]
    assert lit and all(8 <= x < 24 and 8 <= y < 16 for x, y in lit)
    av.packet(b"AAA\x00\x00\x01" + bytes(9) + b"\x02", 20)
    assert av.frame(30).getbbox() is None


def test_screen_uses_the_cards_font_sprite(tmp_path):
    from tools.pinheck_emu.av import Av
    _vid(tmp_path, "AAA", 1, (0,))
    z = tmp_path / "DMD" / "_DZ"
    z.mkdir(parents=True)
    sheet = bytearray(2048)
    for row in range(8):                     # glyph A (ASCII 65 -> cell 33 = row 2, col 1): solid
        for col in range(4):
            sheet[(16 + row) * 64 + 4 + col] = 0xFF
    (z / "ZMF.spr").write_bytes(bytes(512) + bytes(sheet))
    av = Av(str(tmp_path))
    av.packet(b"AAA\x00\x00\x01" + bytes(9) + b"\x02", 0)
    av.packet(bytes([0x00]) + b"A" + bytes(13) + b"\x12", 5)
    img = av.frame(10)
    assert all(img.getpixel((x, y)) != (0, 0, 0) for x in range(8) for y in range(8))
    assert img.getpixel((8, 0)) == (0, 0, 0)


def test_screen_layers_jetsons_videos(tmp_path):
    from tools.pinheck_emu.av import Av
    _vid(tmp_path, "AAA", 1, (0xE0,))
    d = tmp_path / "DMD" / "_DB"
    d.mkdir(parents=True)
    half = bytes(64) + bytes([0x03]) * 64            # one row: left half black, right blue
    (d / "BBB.VID").write_bytes(bytes([128, 32, 128, 32, 8, 1, 15]) + bytes(505) + half * 32)
    av = Av(str(tmp_path))
    av.packet(bytes([3]) + b"AAA" + bytes(11) + b"\x02", 0)
    av.packet(bytes([4]) + b"BBB" + bytes(11) + b"\x02", 0)
    img = av.frame(5)
    assert img.getpixel((10, 5))[0] > 200          # black is see-through: red below
    assert img.getpixel((100, 5))[2] > 200         # blue on top


# --- sound -----------------------------------------------------------------

def _wav(path, seconds, rate=22050, level=8000):
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", level) * 2 * n)


def test_sound_plays_queues_and_stops_music(tmp_path):
    from tools.pinheck_emu.audio import RATE, Sound
    _wav(tmp_path / "SFX" / "_FC" / "C01.wav", 0.1)
    _wav(tmp_path / "SFX" / "_FZ" / "ZBB.wav", 0.05, level=1000)
    s = Sound(str(tmp_path))
    s.packet(b"\x00C01\xff" + bytes(10) + b"\x01", 1000)           # ch 0, C01
    s.packet(b"ZBB" + bytes(12) + b"\x09", 1000)                    # music by name
    assert [t for _, t in s.levels] == ["ch0 C01", "music ZBB"]
    a = s.mix(RATE // 20)                                           # 50 ms
    assert abs(int(a[0, 0]) - 9000) < 50                           # both, summed
    s.mix(RATE // 10)                                               # C01 has ended
    assert 0 not in s.channels and 3 in s.channels                  # music repeats
    s.packet(b"z" + bytes(14) + b"\x10", 2000)                      # fade 0 0 = stop
    assert 3 not in s.channels
    s.packet(b"\x00C99\xff" + bytes(10) + b"\x01", 3000)
    assert s.levels[-1] == (3000, "missing C99")


def test_sound_priority_and_master_volume(tmp_path):
    from tools.pinheck_emu.audio import Sound
    _wav(tmp_path / "SFX" / "_FC" / "C01.wav", 0.5)
    _wav(tmp_path / "SFX" / "_FC" / "C02.wav", 0.5, level=100)
    s = Sound(str(tmp_path))
    s.packet(b"\x00C01\xc8" + bytes(10) + b"\x01", 0)
    s.packet(b"\x00C02\x10" + bytes(10) + b"\x01", 0)               # lower: ignored
    assert s.channels[0].name == "C01"
    s.master = 0.0
    assert not s.mix(512).any()                                     # muted


def test_machine_unpacks_an_update_zip(tmp_path):
    import zipfile
    from tools.pinheck_emu.machine import unpack
    z = tmp_path / "Game_Code.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Game/JET_V004.PRG", b"\0" * 64)
        f.writestr("Game/DMD/_DA/AAA.VID", b"")
    prg, card = unpack(str(z), str(tmp_path / "cache"))
    assert prg.endswith("JET_V004.PRG") and card.endswith("Game")
    assert unpack(str(z), str(tmp_path / "cache")) == (prg, card)      # once
    with pytest.raises(ValueError):
        empty = tmp_path / "e.zip"
        zipfile.ZipFile(empty, "w").close()
        unpack(str(empty), str(tmp_path / "cache"))


def test_screen_keeps_the_players_scores(tmp_path):
    from tools.pinheck_emu.av import Av
    av = Av(str(tmp_path))
    av.packet(bytes([1]) + (4851).to_bytes(4, "little") + bytes(10) + b"\x03", 0)
    av.packet(bytes([7]) + (99).to_bytes(4, "little") + bytes(10) + b"\x03", 0)   # not a player
    assert av.scores == {1: 4851}


def test_lamps_follow_the_multiplexed_port_b():
    from tools.pinheck_emu.board import Lamps
    pic = PinPic()
    lamps = Lamps(pic)
    for _ in range(40):
        pic.write("B", (0b00000101 << 8) | (1 << 2))   # column 2: rows 0 and 2 lit
        pic.write("B", 0)                                # blanking: ignored
        pic.write("B", (0 << 8) | (1 << 3))              # column 3: nothing lit
    lv = lamps.levels()
    assert lv[2 * 8 + 0] > 0.9 and lv[2 * 8 + 2] > 0.9
    assert lv[2 * 8 + 1] == 0 and lv[3 * 8 + 0] == 0


def test_jetsons_text_layer_rules(tmp_path):
    """Jetsons: a video keeps the text; 06 n ff.. clears line n; 13 03 00
    hides it all. Lines are 8 pixels, columns 8, glyphs 4 wide (tinyfont)."""
    from tools.pinheck_emu.av import Av
    _vid(tmp_path, "AAA", 1, (0,))
    av = Av(str(tmp_path))
    av.packet(bytes([1]) + b"AAA" + bytes(11) + b"\x02", 0)        # Jetsons layout
    av.packet(bytes([0x13]) + b"1 - COW" + bytes(7) + b"\x12", 1)  # column 1, line 3
    av.packet(bytes([0x28]) + b"TOP" + bytes(11) + b"\x12", 1)     # line 0, flag bit 3
    av.packet(bytes([3, 1]) + bytes(13) + b"\x13", 2)
    av.packet(bytes([1]) + b"AAA" + bytes(11) + b"\x02", 3)        # a new video
    assert set(av.texts) == {(8, 24), (16, 0)}
    lit = lambda img: {(x // 8, y // 8) for x in range(128) for y in range(32)
                       if img.getpixel((x, y)) != (0, 0, 0)}
    assert (1, 3) in lit(av.frame(4)) and (2, 0) in lit(av.frame(4))
    av.packet(bytes([3]) + b"\xff" * 7 + bytes(7) + b"\x06", 5)    # clear line 3
    assert set(av.texts) == {(16, 0)}
    av.packet(bytes([3, 0]) + bytes(13) + b"\x13", 6)              # text off
    assert not av.texts and av.frame(7).getbbox() is None


def test_tiny_font_covers_the_games_screens():
    from PIL import Image
    from tools.pinheck_emu import tinyfont
    for text in ("TOP 5", "HIGH SCORES", "1 - COW", "20,000,000", "PLAYER:1 BALL:1", "<L -EXIT- R>"):
        assert all(ch in tinyfont.GLYPHS for ch in text.upper()), text
    img = Image.new("RGB", (16, 8))
    tinyfont.draw(img, 0, 0, "11", (255, 0, 0))
    assert img.getpixel((1, 1)) == (255, 0, 0) and img.getpixel((5, 1)) == (255, 0, 0)
    assert all(len(r) == 3 for g in tinyfont.GLYPHS.values() for r in g)
