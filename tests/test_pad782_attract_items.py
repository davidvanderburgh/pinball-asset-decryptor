"""PAD-782: the owner's attract items between the game's own attract pages.

- portattract.find on synthetic sequencers of the three table layouts (Bond's 8-byte {test, page} ending at the
  first entry with no page; Deadpool's 12-byte and Godzilla's 16-byte entries with a fixed count), always.
- Every shipped port's attract lines are of a shape the runtime takes, and the runtime reads them.
- With the game programs present (PAD_PORT_ELFS, a folder of <port name>.elf; skipped otherwise): the finder reads
  each shipped port's table off its own program, as the port says.
"""
import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import portattract as PA
from pinball_decryptor.plugins.stern.portchallenge import Elf

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
TEXT, DATA = 0x8000, 0x100000


class FakeElf(Elf):
    """A program of one text segment (words) and one data segment (bytes)."""

    def __init__(self, words, data):          # noqa: D107 - no ELF header to read
        self.words = tuple(words)
        self.text_va = TEXT
        self.data = bytes(data)
        self.d = b""

    def off(self, va):
        if TEXT <= va < TEXT + 4 * len(self.words):
            return va - TEXT
        if DATA <= va < DATA + len(self.data):
            return 0x10000000 + va - DATA
        return None

    def word(self, va):
        if TEXT <= va < TEXT + 4 * len(self.words):
            return self.words[(va - TEXT) // 4]
        return struct.unpack_from("<I", self.data, va - DATA)[0]


def _movw(reg, v):
    return 0xE3000000 | (v >> 12 & 0xF) << 16 | reg << 12 | v & 0xFFF


def _movt(reg, v):
    return 0xE3400000 | (v >> 12 & 0xF) << 16 | reg << 12 | v & 0xFFF


def _bl(at, target):
    return 0xEB000000 | ((target - at - 8) >> 2 & 0xFFFFFF)


CREATE, SLEEP = TEXT + 0x400, TEXT + 0x500


def _sequencer(table, q, cmp_count=None):
    """A sequencer: the table's address in r8, the page read at [rE, #q], the test called through blx r3."""
    w = [0xE92D43F0, _movw(8, table), _movt(8, table >> 16), 0xE3A04000]
    if cmp_count is not None:
        w.append(0xE3540000 | (cmp_count - 1))               # cmp r4, #count - 1
    w += [0xE7983184, 0xE3530000, 0xE12FFF33,                 # ldr r3, [r8, r4, lsl #3] ; cmp r3, #0 ; blx r3
          0xE5960000 | q, 0xE3A01000]                         # ldr r0, [r6, #q] ; mov r1, #0
    w.append(_bl(TEXT + 4 * len(w), CREATE))
    w += [0xE3500000, 0x158070A0, 0xE3A00001]                 # cmp r0, #0 ; strne r7, [r0, #0xa0] ; mov r0, #1
    w.append(_bl(TEXT + 4 * len(w), SLEEP))
    w += [0xE8BD83F0]
    return w + [0xE320F000] * (0x600 // 4 - len(w))          # nops up to the create and sleep functions


def _code(k):
    return TEXT + 0x40 + 4 * (k % 32)


def test_bond_layout_ends_at_the_first_entry_with_no_page():
    data = b"".join(struct.pack("<II", _code(k) if k % 3 else 0, _code(k + 1)) for k in range(40)) + b"\0" * 16
    s = PA.find(FakeElf(_sequencer(DATA, 4), data))
    assert (s.entry, s.size, s.page_at, s.count, s.sleep) == (DATA, 8, 4, 40, SLEEP)


def test_deadpool_layout_twelve_bytes_and_a_fixed_count():
    head = b"\0" * 4
    data = head + b"".join(struct.pack("<IIf", _code(k), _code(k + 7), 3.0) for k in range(55)) + b"\0" * 24
    s = PA.find(FakeElf(_sequencer(DATA, 8, cmp_count=55), data))
    assert (s.entry, s.size, s.count) == (DATA + 4, 12, 55)


def test_godzilla_layout_sixteen_bytes_with_a_header():
    head = struct.pack("<II", 0, 1)
    data = head + b"".join(struct.pack("<IIfI", _code(k) if k % 4 else 0, _code(k + 3), 5.0, 1) for k in range(91))
    s = PA.find(FakeElf(_sequencer(DATA, 0xC, cmp_count=91), data))
    assert (s.entry, s.size, s.count) == (DATA + 8, 16, 91)
    lines = PA.lines(FakeElf(_sequencer(DATA, 0xC, cmp_count=91), data))
    assert "data  attract_table       0x%08x" % (DATA + 8) in lines and "value attract_entry_size  16" in lines


def test_no_sequencer_no_lines():
    e = FakeElf([0xE320F000] * 64, b"\0" * 64)
    assert PA.find(e) is None and PA.lines(e) == []


def _port_values(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"(data|value|site)\s+(attract_\w+)\s+(\S+)", line)
        if m:
            out[m.group(2)] = int(m.group(3), 0)
    return out


def _attract_ports():
    out = []
    for n in sorted(os.listdir(PORTS)):
        if n.endswith(".port"):
            with open(os.path.join(PORTS, n), encoding="utf-8") as f:
                v = _port_values(f.read())
            if v:
                out.append((n, v))
    return out


def test_shipped_ports_carry_a_table_the_runtime_takes():
    ports = _attract_ports()
    assert len(ports) >= 44
    for n, v in ports:
        assert {"attract_table", "attract_entry_size", "attract_page_at", "attract_count", "attract_sleep"} <= set(v), n
        if "attract_video" in v:                                 # clip v2: the attract video element, whole
            assert {"attract_video_play", "attract_video_playing", "attract_video_update", "attract_video_draw",
                    "attract_video_yield"} <= set(v), n
        assert v["attract_entry_size"] in (8, 12, 16) and v["attract_page_at"] == 4, n
        assert 2 <= v["attract_count"] <= 256, n                 # pad_mode_runtime.c attract_arm's bound
    # James Bond LE/Pro 1.06 play their attract clips through the element (the bank's surface is not on the glass)
    assert {n for n, v in ports if "attract_video" in v} >= {"james_bond_le-1.06.port", "james_bond_pro-1.06.port"}


def test_runtime_reads_the_lines_and_the_cfg():
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    for name in ("attract_table", "attract_entry_size", "attract_page_at", "attract_count", "attract_sleep"):
        assert '"%s"' % name in src
    assert '"/usr/local/padmode/attract.cfg"' in src and "ait_champions_off" in src
    assert "size != 8 && size != 12 && size != 16" in src
    assert src.count("AIT_PAGE(") == 17                         # the macro and its 16 pages


def _elf(name):
    for d in [d for v in ("PAD_PORT_ELFS", "PAD_GAME_ELFS") for d in (os.environ.get(v) or "").split(os.pathsep)
              if d]:
        for cand in (name + ".elf", name + ".0.elf"):
            p = os.path.join(d, cand)
            if os.path.isfile(p):
                return Elf(p)
    pytest.skip("game program not present (PAD_PORT_ELFS): %s.elf" % name)


@pytest.mark.parametrize("name", [n[:-len(".port")] for n, _v in _attract_ports()])
def test_the_finder_reads_each_shipped_port_off_its_program(name):
    e = _elf(name)
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        want = _port_values(f.read())
    s = PA.find(e)
    assert s is not None
    assert (s.entry, s.size, s.page_at, s.count, s.sleep) == (
        want["attract_table"], want["attract_entry_size"], want["attract_page_at"], want["attract_count"],
        want["attract_sleep"])
    el = PA.element(e)
    assert (el.pointer if el else None) == want.get("attract_video")
    if el:
        assert (el.play, el.playing, el.update, el.draw, el.yield_) == tuple(
            want["attract_video_" + k] for k in ("play", "playing", "update", "draw", "yield"))


# ---- the project's record, attract.cfg, the text card ------------------------------------------------------
from pinball_decryptor.plugins.stern import attract_items as AI   # noqa: E402


def test_the_record_keeps_only_items_it_can_show():
    rec = AI.clean({"champions": False, "items": [
        {"kind": "photo", "file": "a.jpg", "entry": 8, "seconds": 400},
        {"kind": "text", "text": "\n  Welcome  \n\n\nline3\nline4\nline5", "entry": "2", "where": "before"},
        {"kind": "text", "text": "   ", "entry": 1},
        {"kind": "clip", "file": "", "entry": 1},
        {"kind": "sound", "file": "x.wav", "entry": 1},
        {"kind": "clip", "file": "c.mp4", "entry": "x"},
    ]})
    assert not rec.champions and [i.kind for i in rec.items] == ["photo", "text"]
    assert rec.items[0].seconds == AI.MAX_SECONDS and rec.items[0].where == "after"
    assert rec.items[1].text == "Welcome\n\n\nline3" and rec.items[1].where == "before" and rec.items[1].entry == 2
    assert AI.clean(rec.as_dict()).as_dict() == rec.as_dict()
    assert AI.Record().empty() and not AI.Record(champions=False).empty()


def test_attract_cfg_is_what_the_runtime_reads():
    text = AI.cfg_text([(8, "after", "PadAttract1", 4000), (0, "before", "PadAttract2", 3000)], champions=False)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    assert lines == ["champions off", "item 8 after PadAttract1 4000", "item 0 before PadAttract2 3000"]
    assert "champions" not in AI.cfg_text([], champions=True)


def test_a_text_card_fills_the_screen(tmp_path):
    from PIL import Image
    out = AI.text_card("Welcome to Dave's basement\nFree play all night", str(tmp_path / "t.png"), 1360, 768)
    im = Image.open(out).convert("L")
    box = im.point(lambda v: 255 if v > 128 else 0).getbbox()
    assert im.size == (1360, 768) and box is not None
    assert box[2] - box[0] > 1360 * 0.5                         # the longer line runs over half the width


# ---- mod packs carry the attract items ------------------------------------------------------------------------
def test_a_mod_pack_carries_the_attract_items_and_an_import_puts_their_files_in_the_project(tmp_path):
    import json as _json
    import zipfile
    from pinball_decryptor.core import checksums, modpack, staged_changes
    from tests.test_pad494_mod_routes import _extract, _write
    photo = str(tmp_path / "mine" / "p.jpg")
    _write(photo, b"PHOTO" * 30)
    src = tmp_path / "src"
    _extract(src, {"video/attract.mov": b"ATT" * 50})
    rec = AI.Record(items=[AI.Item("photo", 3, "after", file=photo, seconds=4),
                           AI.Item("text", 3, "after", text="Hello", seconds=5),
                           AI.Item("clip", 0, "before", file=str(tmp_path / "gone.mp4"))], champions=False)
    staged_changes.save(str(src), {AI.STAGED_KEY: rec.as_dict()})
    logs = []
    zip_path = str(tmp_path / "pack.zip")
    n, _ = modpack.export_mod_pack(str(src), zip_path, log_cb=lambda t, lvl="info": logs.append(t))
    assert n == 0                                            # attract items alone are still a pack
    assert any("NOT in the pack: 1 attract item(s)" in t for t in logs)
    with zipfile.ZipFile(zip_path) as zf:
        man = _json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
    items = man["extras"][AI.STAGED_KEY]["items"]
    assert [i["kind"] for i in items] == ["photo", "text"] and items[0]["file"] == ".modpack_attract/0/p.jpg"
    dest = tmp_path / "dest"
    _extract(dest, {"video/attract.mov": b"ATT" * 50})
    plan = modpack.inspect_mod_pack(zip_path, str(dest))
    assert plan["foreign"] == []
    res = modpack.import_mod_pack(zip_path, str(dest), plan=plan)
    assert res["extras"][AI.STAGED_KEY] == 2
    got = AI.load(str(dest))
    folder = str(dest / checksums.ATTRACT_FILES_DIR)
    assert [(i.kind, i.file, i.text) for i in got.items] == [("photo", os.path.join(folder, "p.jpg"), ""),
                                                            ("text", "", "Hello")]
    assert got.champions is False
    with open(os.path.join(folder, "p.jpg"), "rb") as f:
        assert f.read() == b"PHOTO" * 30


# ---- which titles the page offers -----------------------------------------------------------------------------
@pytest.mark.parametrize("key,offered", [("godzilla_le_1_16", True), ("godzilla_pro_1_16", True),
                                         ("james_bond_le_1_06", True), ("james_bond_pro_1_06", True),
                                         ("jaws_le_1_02", True), ("king_kong_pro_0_97", True),
                                         ("aerosmith_1_16", False), ("deadpool_le_1_16", False),
                                         ("star_wars_le_1_31", False), ("venom_le_1_07", False)])
def test_items_are_offered_only_where_a_route_puts_them_on_the_glass(key, offered):
    from pinball_decryptor.plugins.stern import mode_project as MP
    why = AI.title_refusal(MP.profile(key))
    assert (why == "") is offered, (key, why)


# ---- the scene show (clip v2 titles without the attract video element) -------------------------------------------
@pytest.mark.parametrize("name", [n[:-len(".port")] for n, _v in _attract_ports()])
def test_the_scene_show_finder_agrees_with_the_ports(name):
    e = _elf(name)
    with open(os.path.join(PORTS, name + ".port"), encoding="utf-8") as f:
        text = f.read()
    found = PA.scene_show(e)
    known = re.search(r"^site\s+scene_show\s+(0x[0-9a-f]+)", text, re.M)
    if known:                                                    # the port's own (derived and checked) scene_show
        assert found == int(known.group(1), 16), name
    shown = re.search(r"^site\s+attract_show\s+(0x[0-9a-f]+)", text, re.M)
    assert shown and int(shown.group(1), 16) == found, name


def test_the_runtime_shows_the_bank_scene_from_the_page():
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    play = src[src.index("static void ait_play(unsigned i)"):]
    play = play[:play.index("\n}\n")]
    assert 'fn("player_advance")' in play and "ait_show_fn" in play and "ait_sleep(1)" in play
    assert 'fn("attract_show") ? fn("attract_show") : fn("scene_show")' in src
