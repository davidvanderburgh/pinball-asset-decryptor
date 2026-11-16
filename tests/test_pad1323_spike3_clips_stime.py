"""PAD-1323: random clips and screen times on a Stern Spike 3 card.

PAD-1297's census left both out of a Spike 3 build: the clip v2 route asked for a ``string_new`` site (a 64-bit
program imports none: the runtime builds the std::string), the runtime read the clip's name as a 4-byte pointer and
compared surfaces cut to 32 bits, and the screen times read and wrote a 4-byte vtable slot, from vtables
screen_time.py read off 32-bit code only. Now the 64-bit runtime does both (pad_mode_runtime.c), screen_time.py reads
a 64-bit program's screens (:func:`screen_time.screens_a64`: Fallout LE and Pokemon LE carry Godzilla's screen
framework), and spike3_modes.plan carries the random clips and the screen times like the score feed.

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder holding `fallout_le.game` (sha1
19081048...) and `pokemon_le.game` (sha1 36560010...), each a card's games/<game>/game.
"""
import hashlib
import os
import re
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import screen_time as ST
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from tests._ext4_fake import FakeExt4Reader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
SHA = {"fallout_le": "19081048c0b2427efca8c05775efb109e13689da",
       "pokemon_le": "36560010984f742b74fb8e582f7465c76e852e3d"}

RET = 0xD65F03C0


# ---- a small 64-bit program laid out as Fallout's screens are ------------------------------------
class _Prog:
    """A position-independent AArch64 ELF: one PT_LOAD at 0 (va == file offset), .text, .rela.dyn of
    R_AARCH64_RELATIVE entries (the vtables' and typeinfos' words are 0 in the file, as in a PIE)."""

    def __init__(self):
        self.text, self.data, self.relocs = [], bytearray(), []
        self.TEXT = 0x1000
        self.DATA = 0x8000

    def fn(self, *words):
        va = self.TEXT + 4 * len(self.text)
        self.text.extend(words)
        return va

    def string(self, s):
        va = self.DATA + len(self.data)
        self.data += s.encode() + b"\0"
        while len(self.data) % 8:
            self.data += b"\0"
        return va

    def words(self, values):
        """8-byte words at the data's end: an int is put in the file, ("p", addr) a relocated pointer."""
        va = self.DATA + len(self.data)
        for k, v in enumerate(values):
            if isinstance(v, tuple):
                self.relocs.append((va + 8 * k, v[1]))
                self.data += b"\0" * 8
            else:
                self.data += struct.pack("<Q", v)
        return va

    def getter(self, s):
        """adrp x0 / add x0, x0, #lo / ret for the string *s*."""
        at = self.TEXT + 4 * len(self.text)
        target = self.string(s)
        pages = ((target & ~0xFFF) - (at & ~0xFFF)) >> 12
        adrp = 0x90000000 | ((pages & 3) << 29) | (((pages >> 2) & 0x7FFFF) << 5)
        return self.fn(adrp, 0x91000000 | ((target & 0xFFF) << 10), RET)

    def build(self):
        text = b"".join(struct.pack("<I", w) for w in self.text)
        rela = b"".join(struct.pack("<QQq", o, 1027, a) for o, a in self.relocs)
        shstr = b"\0.text\0.rela.dyn\0.shstrtab\0"
        body = bytearray(0x10000)
        body[self.TEXT:self.TEXT + len(text)] = text
        body[self.DATA:self.DATA + len(self.data)] = self.data
        rela_off = len(body)
        body += rela
        shstr_off = len(body)
        body += shstr
        while len(body) % 8:
            body += b"\0"
        sh_off = len(body)

        def sh(name, typ, flags, addr, off, size):
            return struct.pack("<IIQQQQIIQQ", name, typ, flags, addr, off, size, 0, 0, 8, 0)
        body += sh(0, 0, 0, 0, 0, 0)
        body += sh(1, 1, 6, self.TEXT, self.TEXT, len(text))
        body += sh(7, 4, 2, rela_off, rela_off, len(rela))
        body += sh(17, 3, 0, 0, shstr_off, len(shstr))
        hdr = bytearray(b"\x7fELF\x02\x01\x01" + b"\0" * 9)
        hdr += struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, sh_off, 0, 64, 56, 1, 64, 4, 3)
        ph = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, len(body), len(body), 0x10000)
        body[0:64] = hdr
        body[64:64 + 56] = ph
        return bytes(body)


def _fmov(imm8):
    return 0x1E201000 | (imm8 << 13)


def _program():
    """Three screens of one framework: clip in slot 17, crop 18, loop flag 19, "done" check 16, time 28. The
    base's start code loads slot 28 (`ldr x1, [x2, #0xe0]`), compares it with the base's own 3.0 s getter and
    stores the answer at +0xe0, which the time check compares with the clock beside it."""
    p = _Prog()
    zero = p.fn(0x52800000, RET)                         # mov w0, #0 ; ret
    one = p.fn(0x52800020, RET)                          # mov w0, #1 ; ret
    base_time = p.fn(_fmov(0x08), RET)                   # 3.0
    own_time = p.fn(_fmov(0x10), RET)                    # 4.0
    on_time = p.fn(0x2D400000 | (56 << 15) | (1 << 10), 0x1E202030, 0x1A9FD7E0, RET)   # ldp/fcmpe/cset gt
    on_clip = p.fn(0xF9404400, RET)                      # ldr x0, [x0, #0x88] ; ret - asks the video surface
    p.fn(0xF9400000 | (28 << 10) | (2 << 5) | 1,         # ldr x1, [x2, #0xe0]  (slot 28)
         0xEB00003F,                                     # cmp x1, x0
         0xBD000000 | (56 << 10) | (20 << 5),            # str s0, [x20, #0xe0]
         RET)
    crop = p.getter("Normal")
    screens = [("16BDLSecretAward", "secret_combo", on_time, own_time, zero),
               ("13BDLExtraBall", "extra_ball", on_clip, base_time, zero),
               ("12BDLSpinLoop", "spin_loop", on_time, base_time, one)]
    vts = {}
    for cls, clip, done, tm, loop in screens:
        name = p.string(cls)
        ti = p.words([("p", 0x10), ("p", name)])
        get = p.getter(clip)
        slots = [zero] * 30
        slots[16], slots[17], slots[18], slots[19], slots[28] = done, get, crop, loop, tm
        vt = p.words([0, ("p", ti)] + [("p", f) for f in slots])
        vts[clip] = (vt + 16, vt + 16 + 8 * 28, tm)
    return p.build(), vts


def test_the_64_bit_reader_finds_each_screen_its_clip_and_time():
    elf, vts = _program()
    got = {s.clip: s for s in ST.screens(elf)}
    assert set(got) == {"secret_combo", "extra_ball", "spin_loop"}
    s = got["secret_combo"]
    assert (s.cls, s.crop, s.seconds, s.timed, s.loops) == ("BDLSecretAward", "Normal", 4.0, True, False)
    assert (s.vt, s.slot, s.old) == vts["secret_combo"]        # link-time: the runtime adds the load address
    assert got["extra_ball"].timed is False and got["extra_ball"].seconds == 3.0   # ends with its clip
    assert got["spin_loop"].loops is True


def test_a_stime_line_is_written_for_a_timed_screen_only():
    elf, vts = _program()
    lines = ST.cfg_lines(ST.screens(elf), {"secret_combo": 6.5, "extra_ball": 9.0, "spin_loop": 1.0})
    vt, slot, old = vts["secret_combo"]
    assert lines == ["stime\t0x%08x\t0x%08x\t0x%08x\t6500\tsecret_combo" % (vt, slot, old)]


def test_a_program_without_the_framework_has_no_screens():
    p = _Prog()
    p.fn(_fmov(0x08), RET)
    p.getter("lonely")
    assert ST.screens(p.build()) == []
    assert ST.screens(b"\x7fELF\x02" + b"\0" * 58) == []      # cut off: none, never an error


def test_the_fmov_immediates_decode_as_the_cpu_expands_them():
    assert [ST._a64_fmov_imm(i) for i in (0x08, 0x10, 0x14, 0x78, 0x70, 0x00, 0x88)] == \
        [3.0, 4.0, 5.0, 1.5, 1.0, 2.0, -3.0]


def _real(game):
    if not PROGS:
        pytest.skip("PAD_S3_PROGRAMS is not set")
    path = os.path.join(PROGS, game + ".game")
    if not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    b = open(path, "rb").read()
    if hashlib.sha1(b).hexdigest() != SHA[game]:
        pytest.skip("%s.game is another build" % game)
    return b


def test_fallout_le_0_82_screens():
    found = ST.screens(_real("fallout_le"))
    timed = [s for s in found if s.timed and not s.loops]
    once = {s.clip: s for s in timed}
    assert len(found) == 25 and len(timed) == 14 and len(once) == 13   # two screens show one clip
    assert {(s.cls, s.seconds, s.old) for s in timed if s.clip == "Radiation_RadawayHurryUp_Award"} == {
        ("BDLModeRadawayHurryUpAward", 3.0, 0x4524E0), ("BDLRadawayJackpotCountdown", 3.0, 0x4524E0)}
    assert once["Vault111_BackgroundLoop"].seconds == 5.0
    assert {s.clip for s in found if s.loops} == {"mindcontrol_loop2", "CapStash_Spinner"}


def test_pokemon_le_0_82_screens_have_no_crop():
    found = ST.screens(_real("pokemon_le"))
    assert len(found) == 12
    once = [s for s in found if s.timed and not s.loops]
    assert len(once) == 5 and all(s.crop == "" and s.seconds == 3.0 for s in once)
    assert "PK_EB_ExtraBall" in {s.clip for s in once}


# ---- the clip route on a 64-bit port ---------------------------------------------------------------
def test_star_wars_elgs_spike3_port_has_the_surface_route_without_string_new():
    prof = MP.profiles().get("star_wars_elg_1_10_spike3")
    assert prof is not None and prof.arch == "a64"
    assert "site string_new" not in open(MP.port_path(prof), encoding="utf-8").read().replace(
        "# site string_new", "")
    assert CV.route_of(prof) == "surface" and CV.title_refusal(prof) == ""


def test_a_spike2_port_still_needs_string_new(tmp_path):
    src = open(os.path.join(SDK, "ports", "star_wars_elg-1.10.port"), encoding="utf-8").read()
    p = tmp_path / "x.port"
    p.write_text(re.sub(r"(?m)^site string_new .*$", "", src), encoding="utf-8")
    assert CV.hook_route(str(p)) == ""


# ---- the Spike 3 build carries them ------------------------------------------------------------------
class _Reader(FakeExt4Reader):
    def read_symlink(self, node):
        return bytes(node["i_block"][:node["size"]]).decode()


BANK = "star_wars_elg/assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97/scene.radium"


def _tree(link="star_wars_elg/game"):
    return {"game": ("symlink", link),
            "star_wars_elg": {"game": b"\x7fELF\x02" + b"\0" * 64,
                              "assets": {"lcd": {"auto_loaded": {
                                  "60ed7e5036b8ce09d35a3e101ea6fc1380b37d97": {"scene.radium": b"BANK"}}}}}}


class _Prof:
    game_dir = "star_wars_elg"
    label = "Star Wars ELG 1.10 (Spike 3)"


@pytest.fixture
def build(monkeypatch):
    seen = {}
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(MW, "project_modes", lambda p: [])
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [])
    monkeypatch.setattr(S3M, "feed_wanted", lambda p, real_card=True: ("", None))
    monkeypatch.setattr(S3M, "variants_wanted", lambda p, real_card=True: ({"video/a.mov": ["x.mp4"]}, _Prof))
    monkeypatch.setattr(S3M, "_changed_videos", lambda p: [])
    monkeypatch.setattr(MW, "scene_rels", lambda prof: ("", BANK))
    monkeypatch.setattr(MP, "project_profile", lambda p, probe=False: (None, None))

    def plan(project, hud, bank, elf, scratch, **kw):
        seen.update(kw, elf=elf, hud=hud, bank=bank)
        r = type("R", (), {})()
        r.replaced, r.new, r.mode_names = [], [], []
        r.lines = (["random clips: video/a.mov plays one of 2 clips at random"] if kw.get("variants") else []) + \
            ["screen times: the %s screen lasts as long as its clip, 6.50 s" % l.split("\t")[5]
             for l in kw.get("screen_times") or ()]
        return r

    def payload(result, out_dir, project=None, arch="arm"):
        seen["arch"] = arch
        return {"so": "/o/mode.so", "cfgs": [], "port": "/o/game.port", "assets": [],
                "extras": ["/o/clips.cfg"], "bundle": ""}
    monkeypatch.setattr(MW, "plan", plan)
    monkeypatch.setattr(MW, "p2_payload", payload)
    return seen


def test_a_card_of_random_clips_alone_gets_its_bank_and_clips_cfg(build, tmp_path):
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path))
    assert mp is not None and mp.names == []
    assert build["variants"] is True and build["variants_prof"] is _Prof and build["modes_on"] is False
    assert build["bank"] == b"BANK" and build["arch"] == "a64"   # the title's video bank, off the card
    assert build["read_card"](BANK) == b"BANK" and build["read_card"]("nope/scene.radium") is None
    assert [n for n, _p, _m in mp.files()] == ["mode.so", "clips.cfg", "game.port"]
    assert mp.lines == ["Random clips: video/a.mov plays one of 2 clips at random"]


def test_screen_times_ride_the_cards_own_program(build, monkeypatch, tmp_path):
    monkeypatch.setattr(S3M, "variants_wanted", lambda p, real_card=True: ({}, None))
    monkeypatch.setattr(S3M, "_changed_videos", lambda p: [("Secret.mp4", "/c", "/s")])
    line = "stime\t0x018fecb8\t0x018fed98\t0x004524e0\t6500\tSecret"
    got = {}

    def wanted(project, game_raw, log, real_card=True):
        got["elf"] = game_raw
        return [line], _Prof
    monkeypatch.setattr(S3M, "screen_times_wanted", wanted)
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path))
    assert got["elf"].startswith(b"\x7fELF\x02")
    assert build["screen_times"] == [line] and build["screen_prof"] is _Prof and build["variants"] is False
    assert mp.lines == ["Screen times: the Secret screen lasts as long as its clip, 6.50 s"]


def test_no_replaced_clip_reads_no_screens(build, monkeypatch, tmp_path):
    monkeypatch.setattr(S3M, "variants_wanted", lambda p, real_card=True: ({}, None))
    monkeypatch.setattr(S3M, "screen_times_wanted", lambda *a, **k: pytest.fail("read without a replaced clip"))
    assert S3M.plan("proj", _Reader(_tree()), str(tmp_path)) is None


def test_a_multiboot_card_takes_no_random_clips_and_says_so(build, tmp_path):
    said = []
    assert S3M.plan("proj", _Reader(_tree(S3M.MULTIBOOT_LINK)), str(tmp_path),
                    log=lambda m, kind="info": said.append((kind, m))) is None
    assert any(k == "warning" and m.startswith("Random clips: left out of this build: this is a multi-boot card")
               for k, m in said)


def test_screen_times_wanted_reads_the_64_bit_program(monkeypatch, tmp_path):
    elf, vts = _program()
    monkeypatch.setattr(S3M, "_changed_videos", lambda p: [("secret_combo.mp4", "/c", "/s")])
    from pinball_decryptor.core import video as V
    monkeypatch.setattr(V, "detect_video_info", lambda path: type("I", (), {"duration": 6.5})())
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(CV, "project_title", lambda p, probe=False: _Prof)
    said = []
    lines, prof = S3M.screen_times_wanted("proj", elf, lambda m, kind="info": said.append(m), real_card=False)
    vt, slot, old = vts["secret_combo"]
    assert lines == ["stime\t0x%08x\t0x%08x\t0x%08x\t6500\tsecret_combo" % (vt, slot, old)] and prof is _Prof
    assert any("the screen showing secret_combo lasts 6.50 s" in m for m in said)


def test_the_engine_no_longer_leaves_them_out():
    assert "random clips" not in S3M.FAMILY_LEFT_OUT and "screen times" not in S3M.FAMILY_LEFT_OUT
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "engine.py"), encoding="utf-8").read()
    i = src.index("from . import spike3_modes as _S3M")
    block = src[i:src.index("variant_slots, variant_prof, sound_modes", i)]
    assert '"random clips"' not in block and '"screen times"' not in block


def test_the_write_logs_them_under_their_own_names():
    src = open(os.path.join(ROOT, "pinball_decryptor", "plugins", "stern", "spike3_write.py"),
               encoding="utf-8").read()
    assert '("Score feed:", "Random clips:", "Screen times:", "Co-op play:", "Handicap",' in src   # PAD-1326
    assert '"Prolonged Competition:", "Records on the high scores:"))   # PAD-1327' in src


# ---- the 64-bit runtime ------------------------------------------------------------------------------
def _runtime():
    return open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()


def test_the_runtime_asks_no_string_new_for_the_clip_v2_route():
    src = _runtime()
    i = src.index("static void clipv_arm(void)")
    arm = src[i:src.index("\n}\n", i)]
    assert '"surface_set_video", "surface_state", PM_STRING_SITE' in arm
    assert 'site(PM_STRING_SITE)' in arm and '"string_new"' not in arm
    assert src.index("#define PM_STRING_SITE") < i


def test_the_runtime_reads_the_name_and_surfaces_at_full_width():
    src = _runtime()
    for fn in ("static void on_clipv_set_video(pm_reg *r)\n{", "static void on_clipv_layer(pm_reg *r)\n{"):
        i = src.index(fn)
        body = src[i:src.index("\n}\n", i)]
        assert "const pm_addr *s = (const pm_addr *)" in body
        assert "(unsigned)(unsigned long)" not in body


def test_the_runtime_relocates_and_writes_8_byte_screen_time_slots():
    src = _runtime()
    assert "struct stime_ent { pm_addr vt, slot, old; unsigned ms, calls;" in src
    i = src.index("static void stime_line(char **f, unsigned n)\n{")
    line = src[i:src.index("\n}\n", i)]
    assert all("e->%s += (pm_addr)game_base;" % f in line for f in ("vt", "slot", "old"))
    i = src.index("static void stime_arm(void)")
    arm = src[i:src.index("\n}\n", i)]
    assert "pm_addr *w = (pm_addr *)" in arm and "*w = (pm_addr)(unsigned long)stime_get;" in arm
    assert "(sizeof(pm_addr) - 1)" in arm
