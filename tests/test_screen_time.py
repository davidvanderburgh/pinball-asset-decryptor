"""PAD-1115: a game screen that shows a clip for a fixed time lasts as long as the clip.

The scanner (plugins/stern/screen_time.py) is exercised on a small synthetic ARM program laid out
the way Godzilla's layered displays are (a vtable whose slot 15 names the clip, 16 the crop and 20
the time, under an RTTI header); the build's half (mode_write.screen_into, the engine's gate) on
top of it. The runtime half was proven in the emulator (Godzilla LE 1.16, layered display 53).
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import screen_time as ST

BASE = 0x8000


def _movw(imm):
    return 0xE3000000 | ((imm >> 12) << 16) | (imm & 0xFFF)


def _movt(imm):
    return 0xE3400000 | ((imm >> 12) << 16) | (imm & 0xFFF)


def _str_getter(va):
    return [_movw(va & 0xFFFF), _movt(va >> 16), 0xE12FFF1E]


def _float_getter(v):
    return [0xED9F0A00, 0xE12FFF1E, struct.unpack("<I", struct.pack("<f", v))[0]]


def _program():
    """``(elf bytes, addresses)``: two screen classes (Secret Combo with its own 4.0 s, Big Loop on the
    base class's 3.0 s) and a vtable that names a clip but has no float time (not a screen)."""
    img = bytearray(0x1000)
    a = {}

    def put_words(off, words):
        for i, w in enumerate(words):
            struct.pack_into("<I", img, off + 4 * i, w)

    def put_str(off, s):
        img[off:off + len(s) + 1] = s.encode() + b"\0"
        return BASE + off

    a["s_clip"] = put_str(0x200, "secret_combo")
    a["s_crop"] = put_str(0x210, "Normal")
    a["s_cls"] = put_str(0x220, "19BDLSecretComboAward")
    a["s_clip2"] = put_str(0x240, "big_loop_award_threshold")
    a["s_crop2"] = put_str(0x260, "ScoreFrame")
    a["s_cls2"] = put_str(0x270, "15BDLBigLoopAward")
    a["s_clip3"] = put_str(0x290, "planetXhurryup")
    a["s_cls3"] = put_str(0x2a0, "9BDLHurry")
    fns = [("clip", "s_clip"), ("crop", "s_crop"), ("clip2", "s_clip2"), ("crop2", "s_crop2"),
           ("clip3", "s_clip3")]
    off = 0x100
    for name, s in fns:
        a[name] = BASE + off
        put_words(off, _str_getter(a[s]))
        off += 0x10
    a["own_time"] = BASE + off
    put_words(off, _float_getter(4.0))
    off += 0x10
    a["base_time"] = BASE + off
    put_words(off, _float_getter(3.0))
    off += 0x10
    a["other"] = BASE + off
    put_words(off, [0xE12FFF1E])
    for k, (ti_off, cls, vt_off, clip, crop, tm) in enumerate((
            (0x300, "s_cls", 0x400, "clip", "crop", "own_time"),
            (0x310, "s_cls2", 0x500, "clip2", "crop2", "base_time"),
            (0x320, "s_cls3", 0x600, "clip3", "crop", "other"))):
        put_words(ti_off, [0x12345678, a[cls]])
        words = [0, BASE + ti_off] + [a["other"]] * 15 + [a[clip], a[crop]] + [a["other"]] * 3 + [a[tm]]
        put_words(vt_off, words)
        a["vt%d" % k] = BASE + vt_off + 8
    hdr = bytearray(0x54)
    hdr[:4] = b"\x7fELF"
    hdr[4], hdr[5], hdr[6] = 1, 1, 1
    struct.pack_into("<HHIIIIIHHHHHH", hdr, 0x10, 2, 40, 1, BASE + 0x100, 0x34, 0, 0x5000400,
                     0x34, 0x20, 1, 0x28, 0, 0)
    struct.pack_into("<8I", hdr, 0x34, 1, 0, BASE, BASE, len(img), len(img), 5, 0x1000)
    img[:len(hdr)] = hdr
    return bytes(img), a


def test_screens_read_off_the_program():
    elf, a = _program()
    found = ST.screens(elf)
    assert [(s.clip, s.crop, s.cls, s.seconds) for s in found] == [
        ("secret_combo", "Normal", "BDLSecretComboAward", 4.0),
        ("big_loop_award_threshold", "ScoreFrame", "BDLBigLoopAward", 3.0)]
    sc = found[0]
    assert sc.vt == a["vt0"]
    assert sc.slot == a["vt0"] + 4 * 20          # the time virtual: five entries after the clip's (15)
    assert sc.old == a["own_time"]
    assert found[1].old == a["base_time"]


def test_cfg_lines_only_for_a_different_length():
    elf, a = _program()
    found = ST.screens(elf)
    lines = ST.cfg_lines(found, {"secret_combo": 8.0, "big_loop_award_threshold": 3.02,
                                 "not_a_screen": 9.0})
    assert lines == ["stime\t0x%08x\t0x%08x\t0x%08x\t8000\tsecret_combo"
                     % (a["vt0"], a["vt0"] + 80, a["own_time"])]
    # a shorter clip than the screen's time: the screen ends with it (no frozen last frame)
    assert ST.cfg_lines(found, {"secret_combo": 2.866667})[0].endswith("\t2867\tsecret_combo")
    # a clip far past any screen is capped
    assert ST.cfg_lines(found, {"secret_combo": 999.0})[0].endswith("\t%d\tsecret_combo" % (ST.MAX_S * 1000))
    assert ST.cfg_lines(found, {}) == []


def test_no_screens_in_a_program_without_them():
    elf, _a = _program()
    assert ST.screens(elf[:0x100] + bytes(len(elf) - 0x100)) == []


def test_screen_into_writes_its_own_file_or_appends(tmp_path):
    from pinball_decryptor.plugins.stern import mode_write as MW
    line = "stime\t0x006478e8\t0x00647938\t0x00179f1c\t8000\tsecret_combo"

    class R:
        clips_file = ""
        lines = []
    r = R()
    r.lines = []
    MW.screen_into(r, str(tmp_path / "s"), [line], only=True)
    text = open(r.clips_file, encoding="utf-8").read().splitlines()
    assert text[1:] == ["only", line]
    assert r.lines == ["screen times: the secret_combo screen lasts as long as its clip, 8.00 s"]
    # after the random clips' lines, in the same file, without a second "only"
    cfg = tmp_path / "clips.cfg"
    cfg.write_text("# random\nonly\nclip\ta\ta__PadVar2\n", encoding="utf-8")
    r2 = R()
    r2.lines = []
    r2.clips_file = str(cfg)
    MW.screen_into(r2, str(tmp_path / "s2"), [line], only=True)
    got = cfg.read_text(encoding="utf-8").splitlines()
    assert got[:3] == ["# random", "only", "clip\ta\ta__PadVar2"]
    assert got[-1] == line and got.count("only") == 1


@pytest.fixture
def gate(monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import clip_variants as CV
    from pinball_decryptor.plugins.stern import mode_write as MW
    import pinball_decryptor.core.video as V
    elf, a = _program()

    class Reader:
        def read_file_bytes(self, node):
            return elf
    monkeypatch.setattr(E, "_open_readers", lambda f, p: [(0, Reader())])
    monkeypatch.setattr(E, "_game_program_path", lambda r, c: ("/godzilla_le/game", {"size": len(elf)}))
    lengths = {}

    class Info:
        def __init__(self, d):
            self.duration = d
    monkeypatch.setattr(V, "detect_video_info", lambda p: Info(lengths[os.path.basename(p)]))
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    prof = object()
    monkeypatch.setattr(CV, "project_title", lambda d, probe=False: prof)
    said = []
    run = lambda edits, device=False: E._screen_times_for_build(   # noqa: E731
        None, [], "proj", edits, device, lambda m, lvl="info": said.append((lvl, m)), lambda: False,
        ext4_available=lambda: (True, ""))
    return run, lengths, said, prof, a


def test_engine_gate_lines_for_replaced_screen_clips(gate):
    run, lengths, said, prof, a = gate
    lengths.update({"secret_combo.mp4": 8.0, "other.mp4": 5.0})
    lines, got_prof = run([("secret_combo.mp4", "/c/563.asset", "/p/video/secret_combo.mp4"),
                           ("other.mp4", "/c/1.asset", "/p/video/other.mp4")])
    assert got_prof is prof
    assert lines == ["stime\t0x%08x\t0x%08x\t0x%08x\t8000\tsecret_combo" % (a["vt0"], a["vt0"] + 80, a["own_time"])]
    assert any("lasts 8.00 s" in m and "own time is 4.00 s" in m for _l, m in said)


def test_engine_gate_left_out_on_a_direct_sd_write(gate):
    run, lengths, said, _prof, _a = gate
    lengths["secret_combo.mp4"] = 8.0
    lines, prof = run([("secret_combo.mp4", "/c/563.asset", "/p/video/secret_combo.mp4")], device=True)
    assert (lines, prof) == ([], None)
    assert said and said[-1][0] == "warning" and "direct-SD" in said[-1][1]


def test_engine_gate_nothing_for_a_clip_at_its_screens_time(gate):
    run, lengths, said, _prof, _a = gate
    lengths["secret_combo.mp4"] = 4.0
    assert run([("secret_combo.mp4", "/c/563.asset", "/p/video/secret_combo.mp4")]) == ([], None)
    assert said == []


def test_gate_env_off(gate, monkeypatch):
    run, lengths, _said, _prof, _a = gate
    lengths["secret_combo.mp4"] = 8.0
    monkeypatch.setenv(ST.GATE_ENV, "0")
    assert run([("secret_combo.mp4", "/c/563.asset", "/p/video/secret_combo.mp4")]) == ([], None)


GZ = r"C:\tmp\PAD-1115\gz_le116.elf"


@pytest.mark.skipif(not os.path.isfile(GZ), reason="Godzilla LE 1.16's game program is not on this PC")
def test_godzilla_le_116_secret_combo():
    found = ST.screens(open(GZ, "rb").read())
    sc = [s for s in found if s.clip == "secret_combo"]
    assert len(found) == 26
    assert [(s.cls, s.vt, s.slot, s.old, s.seconds) for s in sc] == [
        ("BDLSecretComboAward", 0x6478E8, 0x647938, 0x179F1C, 4.0)]
    assert {s.seconds for s in found if s.clip != "secret_combo"} == {3.0}
