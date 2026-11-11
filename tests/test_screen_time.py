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
    a["s_clip4"] = put_str(0x2b0, "shark_swim_loop")
    a["s_cls4"] = put_str(0x2c8, "13BDLSharkSwim")
    fns = [("clip", "s_clip"), ("crop", "s_crop"), ("clip2", "s_clip2"), ("crop2", "s_crop2"),
           ("clip3", "s_clip3"), ("clip4", "s_clip4")]
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
    off += 0x10
    a["once"] = BASE + off                       # the play-it-looped flag: mov r0, #0 / bx lr
    put_words(off, [0xE3A00000, 0xE12FFF1E])
    off += 0x10
    a["looped"] = BASE + off                     # mov r0, #1 / bx lr
    put_words(off, [0xE3A00001, 0xE12FFF1E])
    # "done" checks (the slot before the clip's name): on its time (elapsed > length, the length field +0x78) ...
    a["done_time"] = BASE + 0x800
    put_words(0x800, [0xED907A1F, 0xEDD07A1E, 0xEEB47AE7, 0xEEF1FA10, 0xC3A00001, 0xD3A00000, 0xE12FFF1E])
    # ... or on its clip's end (it asks the video surface, Godzilla's other 25 screens)
    a["done_clip"] = BASE + 0x820
    put_words(0x820, [0xE5900058, 0xE2500002, 0x13A00001, 0xE12FFF1E])
    # the base class: its "done" check (elapsed +0x7c > length +0x78) and the start code that stores the
    # length from vtable slot 20 (0x50) after comparing it with its own function
    put_words(0x1c0, [0xED907A1F, 0xEDD07A1E, 0xEEB47AE7, 0xEEF1FA10, 0xE12FFF1E])
    put_words(0x1e0, [0xE5922050, 0xE1520003, 0x0D9F0A00, 0xED840A1E, 0xE12FFF1E])
    for k, (ti_off, cls, vt_off, clip, crop, tm, lp, done) in enumerate((
            (0x300, "s_cls", 0x400, "clip", "crop", "own_time", "once", "done_time"),
            (0x310, "s_cls2", 0x500, "clip2", "crop2", "base_time", "once", "done_clip"),
            (0x320, "s_cls3", 0x600, "clip3", "crop", "other", "once", "done_time"),
            (0x330, "s_cls4", 0x700, "clip4", "crop", "base_time", "looped", "done_time"))):
        put_words(ti_off, [0x12345678, a[cls]])
        words = ([0, BASE + ti_off] + [a["other"]] * 14 + [a[done], a[clip], a[crop], a[lp]] + [a["other"]] * 2
                 + [a[tm]])
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
    from pinball_decryptor.plugins.stern.portgen import Elf
    assert ST.time_slot(Elf(elf)) == 20
    found = ST.screens(elf)
    assert [(s.clip, s.crop, s.cls, s.seconds, s.loops, s.timed) for s in found] == [
        ("secret_combo", "Normal", "BDLSecretComboAward", 4.0, False, True),
        ("big_loop_award_threshold", "ScoreFrame", "BDLBigLoopAward", 3.0, False, False),   # ends with its clip
        ("shark_swim_loop", "Normal", "BDLSharkSwim", 3.0, True, True)]
    sc = found[0]
    assert sc.vt == a["vt0"]
    assert sc.slot == a["vt0"] + 4 * 20          # the time virtual: five entries after the clip's (15)
    assert sc.old == a["own_time"]
    assert found[1].old == a["base_time"]


def test_cfg_lines_only_for_a_different_length():
    elf, a = _program()
    found = ST.screens(elf)
    lines = ST.cfg_lines(found, {"secret_combo": 8.0, "big_loop_award_threshold": 9.0,   # follows its clip: no line
                                 "not_a_screen": 9.0, "shark_swim_loop": 9.0})   # a looping screen: left alone
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
    # no base-class code to read the time slot from: nothing, whatever the vtables look like
    assert ST.screens(elf[:0x1c0] + bytes(0x40) + elf[0x200:]) == []


def test_unknown_loop_flag_layout_leaves_the_program_alone():
    elf, a = _program()
    b = bytearray(elf)
    struct.pack_into("<I", b, a["once"] - BASE, 0xE30001B1)     # movw r0, #0x1b1: an id, not a flag (Avengers)
    assert ST.screens(bytes(b)) == []


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
    # only Secret Combo's screen ends on its time: the other 25 end when their clip does
    assert [s.clip for s in found if s.timed] == ["secret_combo"]


def _scr(sec, loops=False, clip="secret_combo", timed=True):
    return ST.Screen(clip=clip, crop="Normal", cls="BDLX", vt=0x1000, slot=0x1050, old=0x2000, seconds=sec,
                     loops=loops, timed=timed)


def test_flag_words_for_the_video_tab():
    tag, cls, head, lines = ST.flag([_scr(4.0)], 2.866667, False)
    assert (tag, cls, head) == ("4 s", "warn", "The game shows this clip for 4 s")
    assert "last frame stays on screen for 1.13 s" in lines[0]
    tag, cls, _h, lines = ST.flag([_scr(3.0)], 5.0, False)
    assert cls == "warn" and "cuts it off after 3 s" in lines[0]
    _t, cls, _h, lines = ST.flag([_scr(3.0)], 3.01, False)
    assert cls == "" and "screen's own time" in lines[0]
    # a replacement on the slot: no warning, the build gives the screen its length
    _t, cls, _h, lines = ST.flag([_scr(4.0)], 8.0, True)
    assert cls == "" and "lasts 8.00 s too" in lines[0]
    # picked but not yet measured: the general words only
    _t, cls, _h, lines = ST.flag([_scr(4.0)], 0, True)
    assert cls == "" and len(lines) == 1
    # a screen that plays its clip over and over: no tag at all
    assert ST.flag([_scr(3.0, loops=True)], 9.0, False) is None
    # a screen that ends with its clip: no freeze and no cut, so no tag
    assert ST.flag([_scr(3.0, timed=False)], 9.0, False) is None
    assert ST.flag([], 9.0, False) is None


FLEET = r"C:\tmp\PAD-1115\elves"


@pytest.mark.skipif(not os.path.isdir(FLEET), reason="the fleet's game programs are not on this PC")
def test_fleet_jaws_and_king_kong_read_by_the_same_rules():
    def read(name):
        path = os.path.join(FLEET, name)
        if not os.path.isfile(path):
            pytest.skip("%s is not on this PC" % name)
        return ST.screens(open(path, "rb").read())
    jaws = read("jaws_le-1_02_0.Release.16G.elf")
    kk = read("king_kong_le-0_97_0.Release.16G.elf")
    assert (len(jaws), sum(s.loops for s in jaws)) == (23, 4)
    # Jaws times only its looping screens; King Kong's all end with their clip
    assert [s.clip for s in jaws if s.timed and not s.loops] == []
    assert not any(s.timed for s in kk)
    assert [s.clip for s in kk] == ["Kong_ExtraBall", "ExtraBall_Lit_Alt", "Kong_Replay", "Kong_GongHit2"]
    assert {s.seconds for s in kk} == {3.0}
    replay = [s for s in kk if s.clip == "Kong_Replay"][0]
    assert (replay.vt, replay.slot, replay.old) == (0x6F7220, 0x6F7288, 0x46F7C)   # slot 26: 0x68 past the vtable
    venom = os.path.join(FLEET, "venom_le-1_07_0.Release.8G.elf")
    if os.path.isfile(venom):
        assert ST.screens(open(venom, "rb").read()) == []
