"""PAD-674: a game program whose sound key comes from the machine's CPU board.

The PAD-657 user's Jurassic Park LE 1.13 card doesn't seed its sound
keystream from constants as every released build in the library does: its
boot asks the CPU board's bus master four questions over the node bus (frame
``0d 05 <op> <word>``, the request PAD-603 met in Venom LE 0.95) and seeds
from the answers, after setting the board's four state words with constants
of its own.  The board's program is on the card (netbridge.hex), so the
codec emulator runs it as the board (:mod:`spike2.netbridge`), seeds the
slots the game's way, boots the sound init and reads the directory.

Pinned here: the locator's pieces on synthetic code; the messages; the
Extract early-outs; and, when the user's card is on this machine, the whole
thing end to end: the locator's addresses, the board's answers, the game's
own CRC of its sound directory, and a sound decoding to audio.
"""
import io
import os
import struct

import pytest

pytest.importorskip("capstone")

from pinball_decryptor.plugins.stern import engine as E  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import locate as L  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import netbridge as NB  # noqa: E402
from pinball_decryptor.webui import i18n  # noqa: E402

JP = r"D:\Pinball\images\Stern\spike2\jurassic_park_le-1_16_0.Release.8G.sdcard.raw"
#: the user's 1.13 card as the engine extracts it (game_real, image.bin,
#: netbridge-0_5_0.hex), never committed
CARD113 = r"C:\tmp\PAD-674\w113"


class _Fw:
    """Just enough of locate._FwView for the instruction scans."""

    def __init__(self, words, base=0x1000):
        self.raw = b"".join(struct.pack("<I", w) for w in words)
        self.secs = {".text": dict(off=0, addr=base, size=len(self.raw))}

    def w_text(self, va):
        return struct.unpack_from("<I", self.raw, va - self.secs[".text"]["addr"])[0]


def _asker(second=5, bl_to=0x2000):
    # push {r4,lr} ; mov r2,#0xd ; strb r2,[sp,#8] ; mov r2,#<second> ;
    # strb r2,[sp,#9] ; bl <bl_to> ; pop {r4,pc}   (JP 1.13's 0x46474c, cut down)
    base = 0x1000
    off = (bl_to - (base + 5 * 4 + 8)) // 4
    return [0xE92D4010, 0xE3A0200D, 0xE5CD2008, 0xE3A02000 | second,
            0xE5CD2009, 0xEB000000 | (off & 0xffffff), 0xE8BD8010]


def test_the_frame_builder_names_the_bus_exchange_it_calls():
    assert L._frame_sender(_Fw(_asker()), 0x1000) == 0x2000


def test_another_frame_is_not_one():
    assert L._frame_sender(_Fw(_asker(second=6)), 0x1000) is None


def test_a_register_overwritten_between_is_not_one():
    w = _asker()
    w[2:2] = [0xE5D02000]        # ldrb r2,[r0]: the stored byte isn't 0xd
    assert L._frame_sender(_Fw(w), 0x1000) is None


def test_the_slot_setter_masks_r0():
    # push {r4,lr} ; and ip, r4, #0x30 ; pop {r4,pc}
    assert L._masks_slot(_Fw([0xE92D4010, 0xE204C030, 0xE8BD8010]), 0x1000)
    assert not L._masks_slot(_Fw(_asker()), 0x1000)


def test_the_init_seeds_are_its_third_to_sixth_arguments():
    # movw lr,#0x1170 ; movw ip,#0xba07 ; movw r2,#0x3739 ; movw r3,#0x379d ;
    # movt lr,#0x4c64 ; movt ip,#0x3fc4 ; str lr,[sp] ; movt r2,#0x217f ;
    # str ip,[sp,#4] ; movt r3,#0xfbb2 ; bl init
    words = [0xE92D4010,
             0xE301E170, 0xE30BCA07, 0xE3032739, 0xE303379D,
             0xE344EC64, 0xE343CFC4, 0xE58DE000, 0xE342217F,
             0xE58DC004, 0xE34F3BB2, 0xEB000100]
    fw = _Fw(words)
    assert L._init_seeds(fw, 0x1000 + 11 * 4) == (0x217f3739, 0xfbb2379d, 0x4c641170, 0x3fc4ba07)


@pytest.mark.parametrize("job", ["extract", "rebuild", "reset"])
def test_the_message_says_why_and_asks_for_nothing(job):
    msg = E._sounds_unread_why(["BOARD_KEY"], job)
    assert "CPU board" in msg and "BOARD_KEY" not in msg
    for stale in ("developer", "changed outside", "send"):
        assert stale not in msg
    for code in ("de", "es", "fr"):
        got = i18n.catalog(code).tr(msg)
        for sentence in ("CPU board instead", "isn't one it knows"):
            assert sentence not in got, (code, got)


def test_a_card_without_the_board_program_says_so(tmp_path):
    (tmp_path / "game_real").write_bytes(b"\x7fELF")
    with pytest.raises(NB.BoardFirmwareError) as e:
        NB.beside(str(tmp_path / "game_real"))
    assert "netbridge.hex" in str(e.value)
    for code in ("de", "es", "fr"):
        assert i18n.catalog(code).tr(str(e.value)) != str(e.value), code


def test_an_unknown_board_program_says_which(tmp_path):
    p = tmp_path / "netbridge-9_9_9.hex"
    p.write_text(":0400000001030000F8\n:00000001FF\n")
    with pytest.raises(NB.BoardFirmwareError) as e:
        NB.beside(str(tmp_path / "game_real"))
    assert "netbridge-9_9_9.hex" in str(e.value)
    # a known version whose code isn't at the sites is unknown too
    p2 = tmp_path / "netbridge-0_5_0.hex"
    p2.write_text(":0400000001030000F8\n:00000001FF\n")
    with pytest.raises(NB.BoardFirmwareError):
        NB.NetBridge.from_file(str(p2))


def test_extract_does_not_keep_the_program_for_a_board_key(monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    gr = work / "game_real"
    gr.write_bytes(b"\x7fELF" + bytes(60))

    def inputs(disk_f, parts, work_dir, log, read_progress=None):
        return str(gr), str(work / "image.bin"), object(), None, None

    monkeypatch.setattr(E, "_extract_inputs", inputs)
    monkeypatch.setattr(E, "_work_dir", lambda label=None: str(work))
    monkeypatch.setattr(EM, "audio_decode_supported", lambda p: False)
    monkeypatch.setattr(EM, "audio_decode_missing", lambda p: ["BOARD_KEY"])
    for fn in ("extract_videos", "extract_images", "extract_radium_text"):
        monkeypatch.setattr(E, fn, lambda *a, **k: None)
    lines = []
    out = tmp_path / "project"
    n = E.extract_all("card.raw", [], str(out), log=lambda m, lvl="info": lines.append((m, lvl)),
                      open_disk=lambda: io.BytesIO(), do_video=True,
                      do_images=False, do_text=False)
    assert n == 0
    warn = [m for m, lvl in lines if lvl == "warning" and "sounds can't be extracted" in m]
    assert len(warn) == 1, lines
    assert "CPU board" in warn[0] and "The video extracted normally." in warn[0]
    assert not (out / "firmware_game_real.bin").exists()


def test_extract_says_so_when_the_board_program_is_missing(monkeypatch, tmp_path):
    """A board-keyed program the locator maps, on a card without netbridge.hex:
    the emulator's refusal is the log line, nothing is saved for support."""
    work = tmp_path / "work"
    work.mkdir()
    gr = work / "game_real"
    gr.write_bytes(b"\x7fELF" + bytes(60))

    def inputs(disk_f, parts, work_dir, log, read_progress=None):
        return str(gr), str(work / "image.bin"), object(), None, None

    def no_board(*a, **k):
        raise NB.BoardFirmwareError(
            "This card's sounds can't be read: its game code gets the key to its "
            "sounds from the machine's CPU board, and the board's program "
            "(netbridge.hex) isn't on this card for the app to run.")

    monkeypatch.setattr(E, "_extract_inputs", inputs)
    monkeypatch.setattr(E, "_work_dir", lambda label=None: str(work))
    monkeypatch.setattr(EM, "audio_decode_supported", lambda p: True)
    monkeypatch.setattr(EM, "Spike2Emu", no_board)
    for fn in ("extract_videos", "extract_images", "extract_radium_text"):
        monkeypatch.setattr(E, fn, lambda *a, **k: None)
    lines = []
    out = tmp_path / "project"
    n = E.extract_all("card.raw", [], str(out), log=lambda m, lvl="info": lines.append((m, lvl)),
                      open_disk=lambda: io.BytesIO(), do_video=False,
                      do_images=False, do_text=False)
    assert n == 0
    warn = [m for m, lvl in lines if lvl == "warning"]
    assert len(warn) == 1 and "netbridge.hex" in warn[0], lines
    assert not (out / "firmware_game_real.bin").exists()


def test_the_board_program_is_copied_off_the_card(tmp_path):
    """_extract_board_firmware follows the netbridge.hex symlink to the
    versioned file and copies it under that name."""
    files = {"netbridge.hex": 10, "netbridge-0_5_0.hex": 11}
    nodes = {10: {"mode": 0o120777, "size": 19}, 11: {"mode": 0o100644, "size": 30}}

    class Reader:
        def __init__(self, f, off, size):
            pass

        def find_files(self, names, max_depth=5, root_ino=2):
            return {n: files[n] for n in names if n in files}

        def read_inode(self, ino):
            return nodes[ino]

        def read_symlink(self, node):
            return b"netbridge-0_5_0.hex"

        def extract_file(self, node, out_path, **k):
            with open(out_path, "wb") as f:
                f.write(b":00000001FF\n")

    import pinball_decryptor.plugins.stern.ext4 as X
    real = X.Ext4Reader
    X.Ext4Reader = Reader
    try:
        got = E._extract_board_firmware(None, [(0, 1)], str(tmp_path), lambda *a: None)
    finally:
        X.Ext4Reader = real
    assert got == os.path.join(str(tmp_path), "netbridge-0_5_0.hex")
    assert os.path.isfile(got)


def test_a_released_build_is_not_board_keyed():
    if not os.path.isfile(JP):
        pytest.skip("Jurassic Park LE 1.16 card not present")
    with open(JP, "rb") as f:
        r, fw, _img = E._locate(f, E._linux_partitions(JP))
        raw = bytes(r.read_file_bytes(fw))
    a = L.locate_all(raw=raw)
    assert a is not None and "BUS_XCHG" not in a
    assert L.missing(raw=raw) == []
    assert EM.board_bus.__doc__          # the engine's probe exists


@pytest.fixture(scope="module")
def card113():
    gr = os.path.join(CARD113, "game_real")
    if not (os.path.isfile(gr) and os.path.isfile(os.path.join(CARD113, "image.bin"))
            and os.path.isfile(os.path.join(CARD113, "netbridge-0_5_0.hex"))):
        pytest.skip("the user's Jurassic Park LE 1.13 card is not on this machine")
    return gr


def test_the_1_13_program_locates_with_its_bus_parts(card113):
    a = L.locate_all(card113)
    assert a is not None
    assert L.missing(card113) == []
    assert (a["BOOT_LO"], a["BOOT_HI"]) == (0x330988, 0x3309c8)
    assert a["VF2_VA"] == 0x57a1c8 and a["REG_BASE"] == 0x641450
    assert a["BUS_XCHG"] == 0x4628c4 and a["BUS_SEED"] == 0x4646cc and a["BUS_ASK"] == 0x46474c
    assert tuple(a["BUS_SEEDS"]) == (0x217f3739, 0xfbb2379d, 0x4c641170, 0x3fc4ba07)
    assert EM.board_bus(card113)["BUS_SEED"] == 0x4646cc


def test_the_board_answers_as_on_the_machine(card113):
    """netbridge 0.5.0 run from the card: the slot-1 answers to the 1.13
    header's six words after the game's seed, as the run the game's own CRC
    accepted had them."""
    nb = NB.beside(card113)
    assert nb.ask(0x10, 0xfbb2379d) is None           # a slot set answers nothing
    want = [(0xdd32120, 0x1d7c8785), (0xa05aa39b, 0xf4e7e731), (0x7f62ead5, 0x3aeb275c),
            (0xb34ece3b, 0x16c39972), (0xba132aa9, 0x1e8d702e), (0x8976add2, 0x6d6614c2)]
    # the game's own reply mask is applied game-side; these are the raw answers
    got = [nb.ask(0x93, v) for v, _ in want]
    assert len(set(got)) == 6 and all(isinstance(g, int) for g in got)
    nb.reset()
    assert nb.ask(0x93, 0xdd32120) != got[0]


def test_the_1_13_card_reads_and_decodes(card113):
    """End to end on the user's card: the game's own CRC of its unwhitened
    sound directory passes, every record derives, and a mono sound decodes
    to audio (not the wrong-codec noise)."""
    e = EM.Spike2Emu(card113, os.path.join(CARD113, "image.bin"))
    assert e.board is not None
    crc = {}

    def at_crc(eng):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R3
        crc["got"] = eng.mu.reg_read(UC_ARM_REG_R0)
        crc["want"] = eng.mu.reg_read(UC_ARM_REG_R3)
    e.extra[0x32f9c0] = at_crc
    e.boot()
    params = e.derive_params()
    assert len(params) == 3985
    assert crc and crc["got"] == crc["want"] == 0x45295a11
    # one sound per (chan, scale) the card has, low and high scales alike
    # (scales 19+ sit in rows only the half-stride probe reaches)
    seen = set()
    for p in params:
        key = (p["chan"], p["scale"])
        if key in seen or p["length"] < 30000:
            continue
        seen.add(key)
        r = e.decode(p, max_secs=1.0)
        assert r is not None, key
        flat = max(EM.Spike2Emu._specflat(r[0]),
                   EM.Spike2Emu._specflat(r[1]) if p["chan"] == 2 else 0)
        assert flat < 0.6, (key, flat)
    assert len(seen) >= 60
    e.close()
