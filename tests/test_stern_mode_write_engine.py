"""Item 149: the engine carries a project's modes - job order, the manifest, the forced
grow of the end sound, the gates, the build record, the p2 install and Try it's payload.

The card and every emulator step are stubbed at their seams exactly as
test_stern_audio_grow does (its ``_grow_card`` sets the stubs up); the reader here also
carries the Godzilla HUD and bank scenes and a manifest in the real FI64 shape, so the
composed manifest is checked with the same verify a card build refuses on.
"""
import io
import os
import struct

import pytest

# The mode maker ships dark behind a preview switch (core/preview.py); these tests are
# about what it does when it is ON (tests/test_preview_switch.py covers it OFF).
pytestmark = pytest.mark.usefixtures("preview_modes_on")

pytest.importorskip("numpy")

from pinball_decryptor.core import ext4_grow                                  # noqa: E402
from pinball_decryptor.plugins.stern import engine, sidx, sidx_append, valpatch  # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP               # noqa: E402
from pinball_decryptor.plugins.stern import mode_write as MW                 # noqa: E402
from pinball_decryptor.plugins.stern.explorer import S_IFREG                 # noqa: E402
from tests.test_stern_audio_grow import (                                     # noqa: E402
    BLOCK, FW_PATH, IMG_PATH, SIDX_PATH, _capture, _grow_card, _params, _said, _wav)
from tests.test_stern_mode_write import _stub_build                          # noqa: E402
from tests.test_stern_sidx_append import _build as _manifest                 # noqa: E402

GZ = MP.GODZILLA_PRO_1_15
HUD_REL, BANK_REL = MW.scene_rels(GZ)
EPOCH, P2_OFF, P2_EPOCH = 1785242711, 12582912, 1662343945


class _ModeCard:
    """A card with a sound bank, a game program, the HUD and bank scenes and a real-shape
    FI64 manifest indexing all of them, each mapped 1:1 onto a flat disk."""
    base = 0
    DISK = {"img": 0x100000, "fw": 0x10000, "sidx": 0x80000, "hud": 0x200000, "bank": 0x300000}

    def __init__(self):
        self.data = {"img": b"\x00" * 0x40000, "fw": b"\x7fELF" + b"\x00" * 0x1000,
                     "hud": b"H" * 3000, "bank": b"B" * 2000}
        self.rel = {"img": IMG_PATH.lstrip("/"), "fw": FW_PATH.lstrip("/"),
                    "hud": HUD_REL, "bank": BANK_REL, "sidx": SIDX_PATH.lstrip("/")}
        self.data["sidx"] = _manifest([(self.rel[k], len(self.data[k]))
                                       for k in ("img", "fw", "hud", "bank")])
        self.nodes = {k: {"i_block": bytes([i + 1]) * 60, "size": len(self.data[k]),
                          "mode": S_IFREG, "_data": self.data[k], "_disk": self.DISK[k]}
                      for i, k in enumerate(("img", "fw", "sidx", "hud", "bank"))}
        self.img_node, self.fw_node, self.sidx_node = (self.nodes["img"], self.nodes["fw"],
                                                       self.nodes["sidx"])

    def read_file_bytes(self, node):
        return node["_data"]

    def disk_ranges(self, node, off, length):
        if off + length > node["size"]:
            raise ValueError("past the end of the file")
        return [(node["_disk"] + off, length)]

    def iter_regular_files(self, min_size=1, max_depth=20):
        for i, k in enumerate(("img", "fw", "sidx", "hud", "bank")):
            yield "/" + self.rel[k], 3 + i, self.nodes[k]

    def extract_file(self, node, out_path, progress=None):
        with open(out_path, "wb") as f:
            f.write(node["_data"])

    def lookup(self, rel):
        for k, r in self.rel.items():
            if r == rel.lstrip("/"):
                return self.nodes[k]
        return None


def _mode_card(monkeypatch, tmp_path, with_sound=True, audio_edit=False, sound_idx=0):
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[sound_idx].update(body_off=0x40000, length=3 * 44100 + BLOCK, grown=True, shadows=4)
    _r, staged = _grow_card(monkeypatch, tmp_path, params, grown_rows=grown)
    card = _ModeCard()

    def extract(disk_f, parts, work, log, prog=None):
        w_gr, w_img = os.path.join(work, "game_real"), os.path.join(work, "image.bin")
        for p, k in ((w_gr, "fw"), (w_img, "img")):
            with open(p, "wb") as f:
                f.write(card.data[k])
        return w_gr, w_img, card, card.fw_node, card.img_node

    monkeypatch.setattr(engine, "_extract_inputs", extract)
    monkeypatch.setattr(engine, "_locate", lambda f, p: (card, card.fw_node, card.img_node))
    monkeypatch.setattr(MW, "lookup", lambda reader, rel: card.lookup(rel))
    monkeypatch.setattr(MW, "epoch_at", lambda f, off: P2_EPOCH if off == P2_OFF else EPOCH)
    monkeypatch.setattr(MW, "p2_offset", lambda f: P2_OFF)
    port = tmp_path / "godzilla_pro-1.15.port"
    port.write_text("game godzilla_pro\nversion 1.15\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: str(port))
    monkeypatch.setattr(MW, "request_record", lambda *a, **k: sound_idx)
    _stub_build(monkeypatch)
    monkeypatch.setattr(valpatch, "sound_count_overlay", lambda elf, log=None: {0x40: valpatch._NOP})
    recs, _c, fmt = sidx.parse_records(card.data["sidx"])
    game_hmac_disk = card.DISK["sidx"] + recs[card.rel["fw"]] + sidx._FORMATS[fmt][0]

    def fake_compute(reader, log, fw_overlay=None):
        # the bypass's own refresh of the game record: an in-place manifest write
        return [(game_hmac_disk, b"\x11" * 20)], ("bypassed", "")
    monkeypatch.setattr(valpatch, "compute_writes", fake_compute)
    monkeypatch.delenv(MW.GATE_ENV, raising=False)
    monkeypatch.delenv(MW.SOUND_ENV, raising=False)
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    # a host that carries modes on every CI leg: on macos-latest host_refusal says no (a Mac
    # cannot deliver a mode's files), which the Mac tests below pin on purpose
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")

    project = tmp_path / "project"
    for name, spec in MP.example_specs()[:2]:
        slug, _s = MP.new_mode(str(project), spec=spec)
        if with_sound and name == "KAIJU RUSH":
            _wav(os.path.join(MP.mode_folder(str(project), slug), "end.wav"), 3.0)
            spec = MP.load(os.path.join(MP.mode_folder(str(project), slug), MP.MODE_FILE))
            spec.end_sound = "end.wav"
            MP.save(str(project), slug, spec)
    encoded = {}

    def fake_encode(gr, img, prm, ed, np, lg, pr, cx, **k):
        encoded.update(ed)
        return ({0x40000: b"\xaa" * 64} if ed else {}), []

    # item 150 follow-up: a grown (appended) sound is encoded along the firmware's chain
    def fake_chain(gr, img, prm, ed, np, lg, **k):
        encoded.update(ed)
        return ({0x40000: b"\xaa" * 64} if ed else {}), prm
    monkeypatch.setattr(engine, "_encode_cat0_sounds", fake_encode)
    monkeypatch.setattr(engine, "_chain_encode_appended", fake_chain)
    # a bed copies its carrier's descriptor; the carrier's sid comes off the (fake) ELF's table
    monkeypatch.setattr(engine, "_mode_bed_templates", lambda gr, img, used, log: {
        int(u["sid"]): 2484 for u in (used or ()) if u.get("music") and u.get("sid")})
    monkeypatch.setattr(engine, "_select_changed_idx_wavs",
                        lambda a, b: {sound_idx: "audio/idx0000.wav"} if audio_edit else {})
    return card, staged, project, encoded, game_hmac_disk


def _compute(project, log, device=False):
    return engine._compute_patches(io.BytesIO(b""), [], str(project), log=log, progress=None,
                                   cancel=lambda: False, dest_is_device=device)


def test_a_modes_only_project_builds_files_manifest_sound_and_count_patch(monkeypatch, tmp_path):
    card, staged, project, encoded, hmac_disk = _mode_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    writes, counts, plan, _mode, vp = _compute(project, log)

    auto = "godzilla_pro/assets/lcd/auto_loaded/%s/scene.assets/2.asset/" % GZ.bank_scene
    rels = [r for r, _s in plan["jobs"]]
    # the grown bank, then the rewritten scenes, the new clips, and the manifest last
    assert rels == [IMG_PATH.lstrip("/"), HUD_REL, BANK_REL, auto + "598.asset",
                    auto + "599.asset", SIDX_PATH.lstrip("/")]
    assert plan["epoch"] == EPOCH and plan["modes"]["p2_epoch"] == P2_EPOCH
    # the end sound rode in as a forced grow of the time-up record
    assert encoded and list(encoded) == [0] and encoded[0].endswith("end.wav")
    assert staged["path"] and staged["repointed"]["path"] == staged["path"]
    assert plan["modes"]["end_sound"] == {"name": "KAIJU RUSH", "request": 1295, "idx": 0}
    # the sound engine's count patch followed, in place, as for any grown bank
    assert (card.DISK["fw"] + 0x40, valpatch._NOP) in writes
    # nothing is written into the manifest in place any more
    lo = card.DISK["sidx"]
    assert not [d for d, _b in writes if lo <= d < lo + len(card.data["sidx"])]
    # the composed manifest: the bypass's refresh folded in, every record right
    man = open(plan["jobs"][-1][1], "rb").read()
    stock_recs, _c, fmt = sidx.parse_records(card.data["sidx"])
    assert hmac_disk - lo == stock_recs[card.rel["fw"]] + sidx._FORMATS[fmt][0]
    recs, _c, _f = sidx.parse_records(man)          # appended paths moved every record
    at = recs[card.rel["fw"]] + sidx._FORMATS[fmt][0]
    assert man[at:at + 20] == b"\x11" * 20
    assert sidx_append.verify(man, expect_paths=rels[:-1]) == []
    files = sidx.manifest_files(man)
    for rel, src in plan["jobs"][:-1]:
        assert files[rel] == (os.path.getsize(src), sidx.digests_file(src)[1].hex()), rel
    assert list(files)[-2:] == [auto + "598.asset", auto + "599.asset"]
    # what the log says was added
    assert _said(msgs, "Found 2 mode(s) to write")
    assert _said(msgs, "Modes: KAIJU RUSH: its own screen")
    assert _said(msgs, "gains 2 record(s)")
    assert _said(msgs, "goes on the card as a new record for request 1295")
    pay = plan["modes"]["payload"]
    assert os.path.basename(pay["so"]) == "mode.so" and len(pay["cfgs"]) == 2
    assert plan["modes"]["p2"] == ["mode.so", "mode.cfg", "mode1.cfg", "game.port"]
    assert plan["cleanup"] and pay["so"].startswith(plan["cleanup"])
    engine._rmtree_grow_plan(plan)


def test_a_code_mode_in_the_project_is_carried_to_the_card(monkeypatch, tmp_path):
    """The intricate modes' own audio and video: a CODE mode reaches the card beside the form
    modes - compiled into the card's object (the compile is stubbed here: build_mode.sh runs in the
    app's Linux) with a <slug>.assets beside it naming what the build carried."""
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    folder = os.path.join(MP.modes_dir(str(project)), "blitz")
    os.makedirs(folder)
    with open(os.path.join(folder, "blitz.c"), "w") as f:
        f.write("/* a mode */")
    built = []

    def compile_(sources, out, log=None, executor=None, timeout=600):
        built.append([os.path.basename(s) for s in sources])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"\x7fELF code modes")
        return out
    monkeypatch.setattr(MW, "compile_code_object", compile_)
    msgs, log = _capture()
    _writes, _counts, plan, _m, _v = _compute(project, log)
    assert plan["modes"]["names"] == ["ATOMIC BREATH", "KAIJU RUSH", "BLITZ"]
    assert _said(msgs, "Found 1 code mode(s) to write: BLITZ.")
    assert not _said(msgs, "are not put on the card")
    assert built == [["blitz.c"]]
    assert plan["modes"]["p2"] == ["mode.so", "mode.cfg", "mode1.cfg", "blitz.assets", "game.port"]
    assert plan["modes"]["code_object"] is True
    with open(plan["modes"]["payload"]["so"], "rb") as f:
        assert f.read() == b"\x7fELF code modes"
    assert any(ln.startswith("BLITZ (code mode): its code (blitz.c)") for ln in plan["modes"]["lines"])
    engine._rmtree_grow_plan(plan)


def test_the_end_sound_and_an_edit_of_the_same_sound_are_refused(monkeypatch, tmp_path):
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path, audio_edit=True)
    _msgs, log = _capture()
    with pytest.raises(RuntimeError, match="also replaces that sound"):
        _compute(project, log)


def test_the_sound_gate_closed_keeps_the_modes_and_the_game_call(monkeypatch, tmp_path):
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    monkeypatch.setenv(MW.SOUND_ENV, "0")
    msgs, log = _capture()
    writes, _counts, plan, _m, _v = _compute(project, log)
    assert "path" not in staged and not encoded
    rels = [r for r, _s in plan["jobs"]]
    assert IMG_PATH.lstrip("/") not in rels and rels[-1] == SIDX_PATH.lstrip("/")
    assert plan["modes"]["end_sound"] is None
    assert _said(msgs, "PAD_STERN_MODE_SOUND=0")
    assert _said(msgs, "the game's own time-up call (its own end sound is not on this card)")
    engine._rmtree_grow_plan(plan)


def test_the_build_whose_sounds_cannot_run_long_keeps_the_game_call(monkeypatch, tmp_path):
    """TMNT 1.58, the validated build: codec.extend_length is None there, so a grown sound
    could never be heard past its stock length. The mode ends with the game's own call,
    the modes still ship, and the sound bank is left alone."""
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    monkeypatch.setattr(EM, "firmware_build_supported", lambda p: True)
    msgs, log = _capture()
    _writes, _counts, plan, _m, _v = _compute(project, log)
    assert "path" not in staged and not encoded
    assert IMG_PATH.lstrip("/") not in [r for r, _s in plan["jobs"]]
    assert plan["modes"]["names"] and plan["modes"]["end_sound"] is None
    assert _said(msgs, "can't be driven past their original length")
    engine._rmtree_grow_plan(plan)


@pytest.mark.parametrize("err", [struct.error("unpack_from requires a buffer of at least 4 bytes"),
                                 IndexError("list index out of range"),
                                 ValueError("not an ELF")])
def test_an_end_sound_that_cannot_be_located_keeps_the_game_call(monkeypatch, tmp_path, err):
    """An unexpected program or a profile's request out of range is a sound that cannot be
    located: the mode ends with the game's call and the Write goes on, never a raw crash."""
    _card, staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)

    def broken(*a, **k):
        raise err
    monkeypatch.setattr(MW, "request_record", broken)
    msgs, log = _capture()
    _writes, _counts, plan, _m, _v = _compute(project, log)
    assert "path" not in staged and not encoded
    assert plan["modes"]["names"] and plan["modes"]["end_sound"] is None
    assert _said(msgs, "time-up sound could not be located")
    engine._rmtree_grow_plan(plan)


def test_a_request_the_table_does_not_have_names_no_sound(monkeypatch):
    """request_sids never reads past the game's request table."""
    from pinball_decryptor.plugins.stern import info
    from pinball_decryptor.plugins.stern.spike2 import sound_requests as SR
    monkeypatch.setattr(info, "container_counts", lambda head: (5000,))
    monkeypatch.setattr(SR, "locate_sound_requests", lambda elf, frag: (10, 0))
    elf = b"\x00" * 64                   # a 10-request table would need 200 bytes
    for request in (-1, 10, 1295):
        assert MW.request_sids(elf, b"", request) == []
    assert MW.request_sids(elf, b"", 5) == []          # in the count, past the program's end
    monkeypatch.setattr(SR, "locate_sound_requests", lambda elf, frag: (None, None))
    assert MW.request_sids(elf, b"", 1) == []


@pytest.mark.parametrize("device,env,needle", [
    (True, None, "direct-SD write cannot add files"),
    (False, "0", "PAD_STERN_MODES=0"),
])
def test_a_closed_modes_gate_leaves_them_out_and_says_why(monkeypatch, tmp_path, device, env, needle):
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    if env is not None:
        monkeypatch.setenv(MW.GATE_ENV, env)
    msgs, log = _capture()
    with pytest.raises(FileNotFoundError, match="Nothing to write") as got:
        _compute(project, log, device=device)
    assert _said(msgs, "left out of this build") and _said(msgs, needle)
    # the refusal itself names the modes and why, never only "every sound still matches"
    text = str(got.value)
    assert text.startswith("Nothing to write: the project's 2 mode(s) (")
    assert "ATOMIC BREATH" in text and "KAIJU RUSH" in text and needle in text
    assert "are left out of this write" in text and "every sound" in text


def test_a_mac_build_leaves_the_modes_out_and_says_why(monkeypatch, tmp_path):
    """The engine on a Mac (the gate's host refusal): the modes are left out with the reason,
    never a card whose mode files did not land."""
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: MW.MAC_REFUSAL)
    msgs, log = _capture()
    with pytest.raises(FileNotFoundError, match="Nothing to write") as got:
        _compute(project, log, device=False)
    assert _said(msgs, "left out of this build") and _said(msgs, "a Mac cannot put")
    assert "a Mac cannot put a mode's files on the card yet" in str(got.value)


def test_nothing_to_write_without_modes_reads_as_it_always_did():
    assert engine._modes_left_out_clause(None) == ""
    assert engine._modes_left_out_clause((["A", "B"], "why")) == \
        "the project's 2 mode(s) (A, B) are left out of this write (why), and "


def test_modes_are_built_whole_and_the_build_after_them_too(tmp_path, monkeypatch):
    from pinball_decryptor import __version__
    project = tmp_path / "p"
    project.mkdir()
    prev = {"version": engine.BUILD_MANIFEST_VERSION, "app": __version__, "complete": True,
            "modes": {"names": ["KAIJU RUSH"]}}
    monkeypatch.setattr(engine, "_stamp_matches", lambda s, p: True)
    orig, out = tmp_path / "o.raw", tmp_path / "b.raw"
    prev["stock"] = {"path": os.path.abspath(str(orig))}
    prev["assets"] = str(project)
    assert engine.build_update_reason(prev, orig, out, str(project)) == \
        "the last build here carried modes"
    prev.pop("modes")
    assert engine.build_update_reason(prev, orig, out, str(project)) is None
    MP.new_mode(str(project), "KAIJU RUSH")
    assert engine.build_update_reason(prev, orig, out, str(project)) == \
        "a build that carries modes is built whole"


def _modes_info(tmp_path):
    so, cfg, port = tmp_path / "mode.so", tmp_path / "mode.cfg", tmp_path / "game.port"
    for p in (so, cfg, port):
        p.write_bytes(p.name.encode())
    return {"names": ["KAIJU RUSH"], "added": ["g/598.asset"], "rewritten": ["g/hud", "spk/a.sidx"],
            "port": "godzilla_pro-1.15.port", "p2": ["mode.so", "mode.cfg", "game.port"],
            "payload": {"so": str(so), "cfgs": [str(cfg)], "port": str(port)},
            "end_sound": {"name": "KAIJU RUSH", "request": 1295, "idx": 1560},
            "p2_offset": P2_OFF, "p2_epoch": P2_EPOCH}


def test_the_p2_install_waits_for_every_file_and_the_log_names_each_one(tmp_path, monkeypatch):
    modes = _modes_info(tmp_path)
    ran = []
    monkeypatch.setattr(MW, "install_p2", lambda img, pay, epoch, log=None: ran.append((img, epoch)))
    msgs, log = _capture()
    rec, ok = engine._install_modes("out.raw", modes, 3, 4, log)
    assert (rec, ok) == (None, False) and not ran
    assert _said(msgs, "NOT put on the system partition")
    # a scene may already name a clip that did not land: the card is not to be used
    assert _said(msgs, "do not use this card")
    msgs.clear()
    rec, ok = engine._install_modes("out.raw", modes, 4, 4, log)
    assert ok and ran == [("out.raw", P2_EPOCH)]
    assert rec["names"] == ["KAIJU RUSH"] and "payload" not in rec
    for needle in ("added g/598.asset", "rewrote spk/a.sidx",
                   "added /usr/local/padmode/mode.so on the system partition",
                   "request 1295 (sound idx 1560) plays KAIJU RUSH's own end sound"):
        assert _said(msgs, needle), needle


def test_a_failed_p2_install_is_an_error_not_a_crash(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("debugfs said no")
    monkeypatch.setattr(MW, "install_p2", boom)
    msgs, log = _capture()
    assert engine._install_modes("out.raw", _modes_info(tmp_path), 4, 4, log) == (None, False)
    assert _said(msgs, "debugfs said no")


def test_a_mode_build_delivers_with_the_clock_pinned(monkeypatch, tmp_path):
    src = tmp_path / "f"
    src.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0: seen.setdefault("pinned", epoch) and 1)
    monkeypatch.setattr(ext4_grow, "grow_files",
                        lambda img, off, jobs, log=None, timeout=0: seen.setdefault("kernel", True) and 1)
    plan = {"offset": 0, "jobs": [("a", str(src))], "epoch": EPOCH}
    assert engine._grow_video_slots("c.raw", plan, lambda *a, **k: None) == 1
    assert seen == {"pinned": EPOCH}
    plan["epoch"] = None
    engine._grow_video_slots("c.raw", plan, lambda *a, **k: None)
    assert seen.get("kernel") is True


def test_try_it_gets_the_same_payload_beside_the_set(tmp_path):
    modes = _modes_info(tmp_path)
    out = tmp_path / "set"
    out.mkdir()
    msgs, log = _capture()
    got = engine._write_override_modes(str(out), modes, log)
    dest = str(out) + engine.OVERRIDE_MODES_SUFFIX
    # the object under the name item 127's rig stage takes (tryit.sh install <folder>)
    assert got["dir"] == dest and got["files"] == ["pad_mode.so", "mode.cfg", "game.port"]
    for name, src in zip(got["files"], ("mode.so", "mode.cfg", "game.port")):
        assert open(os.path.join(dest, name), "rb").read() == src.encode()
    assert got["end_sound"]["idx"] == 1560
    # a later set without modes takes the old payload away
    assert engine._write_override_modes(str(out), None, log) is None
    assert not os.path.exists(dest)


def test_the_emulator_override_set_is_built_by_the_same_code(monkeypatch, tmp_path):
    """Try it: write_overrides runs the same _compute_patches, so the set carries the
    rewritten scenes, the new clips, the grown bank and the composed manifest as files,
    and the modes' system-partition payload lands BESIDE the set and is named in
    overrides.json."""
    card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    original.write_bytes(b"x" * 4096)
    out = tmp_path / "overrides"
    msgs, log = _capture()
    counts, _am, _vp, written = engine.write_overrides(str(original), str(project), str(out),
                                                       log=log)
    paths = {p for p, _n in written}
    auto = "/godzilla_pro/assets/lcd/auto_loaded/%s/scene.assets/2.asset/" % GZ.bank_scene
    for rel in ("/" + HUD_REL, "/" + BANK_REL, auto + "598.asset", auto + "599.asset",
                IMG_PATH, SIDX_PATH, FW_PATH):
        assert rel in paths, rel
    man = open(os.path.join(str(out), *SIDX_PATH.strip("/").split("/")), "rb").read()
    assert sidx_append.verify(man, expect_paths=[auto.lstrip("/") + "598.asset"]) == []
    listed = engine.read_override_manifest(str(out))
    modes = listed["modes"]
    assert modes["dir"] == str(out) + engine.OVERRIDE_MODES_SUFFIX
    assert modes["files"] == [engine.OVERRIDE_MODES_OBJECT, "mode.cfg", "mode1.cfg", "game.port"]
    assert os.path.isfile(os.path.join(modes["dir"], "mode1.cfg"))
    assert modes["end_sound"]["request"] == 1295
    assert _said(msgs, "Override: the modes' runtime")
    # the log says why each file is whole: a new clip has no slot to outgrow
    assert any("598.asset" in m and "a new file the modes add" in m for _l, m in msgs)
    assert any(BANK_REL in m and "rebuilt whole for the modes" in m for _l, m in msgs)


def _delta_lines(out):
    with open(os.path.join(str(out), engine.OVERRIDE_DELTA), encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip() and not ln.startswith("#")]


def test_the_override_set_lists_the_modes_new_files_the_way_the_rig_reads_them(monkeypatch, tmp_path):
    """The clips are files a stock card lacks: the set names them in overrides.new (item
    127's name and format, which run_game.sh overlays), and the list rides the delta so a
    stage brought forward by overrides.sh never keeps an old one."""
    card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    with open(str(original), "wb") as f:     # the card's files at their disk offsets: an
        for k, at in card.DISK.items():      # update puts the stock bytes back from here
            f.seek(at)
            f.write(card.data[k])
    out = tmp_path / "overrides"
    _msgs, log = _capture()
    auto = "godzilla_pro/assets/lcd/auto_loaded/%s/scene.assets/2.asset/" % GZ.bank_scene
    engine.write_overrides(str(original), str(project), str(out), log=log)
    listed = open(os.path.join(str(out), engine.OVERRIDE_NEW), "rb").read().decode()
    assert "\r" not in listed
    rels = [ln for ln in listed.splitlines() if ln and not ln.startswith("#")]
    assert rels == [auto + "598.asset", auto + "599.asset"]
    for rel in rels:                        # every listed file is in the set, where the rig looks
        assert os.path.isfile(os.path.join(str(out), *rel.split("/")))
    assert "whole " + engine.OVERRIDE_NEW in _delta_lines(out)
    # the set is not a set file: the manifest never lists it, so it is never bound
    assert engine.OVERRIDE_NEW not in [r["path"].strip("/") for r in
                                       engine.read_override_manifest(str(out))["files"]]
    # a second build patches the first (a parent generation) and still carries the list
    first = engine.read_override_manifest(str(out))["generation"]
    engine.write_overrides(str(original), str(project), str(out), log=log)
    lines = _delta_lines(out)
    assert "parent %s" % first in lines and "whole " + engine.OVERRIDE_NEW in lines
    assert os.path.isfile(os.path.join(str(out), engine.OVERRIDE_NEW))


def test_a_set_without_new_files_carries_no_list(tmp_path):
    out = tmp_path / "set"
    out.mkdir()
    assert engine._write_override_new_list(str(out), ["/g/a/598.asset"]) == ["g/a/598.asset"]
    assert os.path.isfile(os.path.join(str(out), engine.OVERRIDE_NEW))
    assert engine._write_override_new_list(str(out), []) == []
    assert not os.path.exists(os.path.join(str(out), engine.OVERRIDE_NEW))
    msgs, log = _capture()
    engine._write_override_modes(str(out), _modes_info(tmp_path), log)
    assert open(os.path.join(str(out), engine.OVERRIDE_NEW)).read().splitlines()[1:] == ["g/598.asset"]
    engine._write_override_modes(str(out), None, log)
    assert not os.path.exists(os.path.join(str(out), engine.OVERRIDE_NEW))



# ---- write_image: the p2 install, the record, and taking every mode out ----------------------
from tests.test_stern_build_update import _build, _grow, _record, card  # noqa: E402,F401


def _mode_grow(card, tmp_path):
    g = _grow(("turtles_pro/assets/lcd/1.asset", str(card.clips / "one.mp4")))
    g["n_video"] = 0
    g["modes"] = _modes_info(tmp_path)
    g["epoch"] = EPOCH
    return g


def test_a_mode_build_installs_p2_pins_the_clock_and_records_the_modes(card, tmp_path, monkeypatch):
    pinned, installed = [], []
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0:
                        pinned.append(epoch) or len(jobs))
    monkeypatch.setattr(MW, "install_p2",
                        lambda img, pay, epoch, log=None: installed.append((img, epoch)))
    card.state["grow"] = _mode_grow(card, tmp_path)
    card.state["counts"] = (0, 0, 0, 0)
    _counts, lines = _build(card, update=False)
    assert pinned == [EPOCH] and not card.state["copies"], "a mode build must not use the kernel copy"
    assert installed == [(str(card.out), P2_EPOCH)]
    rec = _record(card)
    assert rec["complete"] and rec["modes"]["names"] == ["KAIJU RUSH"]
    assert any("2 mode(s)" in m or "1 mode(s) on the card" in m for m, _l in lines)


def test_taking_every_mode_out_writes_the_original_card(card, tmp_path, monkeypatch):
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0: len(jobs))
    monkeypatch.setattr(MW, "install_p2", lambda img, pay, epoch, log=None: None)
    card.state["grow"] = _mode_grow(card, tmp_path)
    _build(card, update=False)
    assert _record(card).get("modes")

    def nothing(*a, **k):
        raise engine.NothingToWrite("Nothing to write: ...")
    monkeypatch.setattr(engine, "_compute_patches", nothing)
    counts, lines = _build(card)
    assert counts == ((0, 0, 0, 0), None, None)
    assert open(card.out, "rb").read() == open(card.stock, "rb").read()
    rec = _record(card)
    assert rec["complete"] and "modes" not in rec
    assert any("written as the original card" in m and "this project has none" in m
               for m, _l in lines)
    # and with no modes on the card before, nothing to write is still the error it was
    with pytest.raises(FileNotFoundError):
        _build(card)
    assert open(card.out, "rb").read() == open(card.stock, "rb").read()


@pytest.mark.parametrize("why", [
    "the pinned mode runtime X/prebuilt/mode.so is missing - rebuild it with build_prebuilt.sh",
    "[Errno 2] No such file or directory: 'C:/project/audio/idx0001.wav'",
])
def test_a_missing_file_after_a_mode_build_is_an_error_not_the_original(card, tmp_path,
                                                                       monkeypatch, why):
    """Only NothingToWrite means "every mode taken out": any other missing file (the pinned
    runtime gone, a replacement sound deleted) fails the Write - it never writes the
    original card and calls that a success.  It fails before the build copied anything over
    the output (PAD-176: the copy starts once the build is measured), so the last build
    there and its record are left exactly as they were."""
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0: len(jobs))
    monkeypatch.setattr(MW, "install_p2", lambda img, pay, epoch, log=None: None)
    card.state["grow"] = _mode_grow(card, tmp_path)
    _build(card, update=False)
    assert _record(card).get("modes")

    before = (os.stat(str(card.out)).st_mtime_ns, os.path.getsize(str(card.out)),
              _record(card))

    def other_failure(*a, **k):
        raise FileNotFoundError(why)
    monkeypatch.setattr(engine, "_compute_patches", other_failure)
    lines = []
    with pytest.raises(FileNotFoundError) as got:
        engine.write_image(str(card.stock), str(card.project), str(card.out),
                           log=lambda m, l="info", *a, **k: lines.append((m, l)))
    assert not isinstance(got.value, engine.NothingToWrite)
    assert not any("written as the original card" in m for m, _l in lines)
    assert (os.stat(str(card.out)).st_mtime_ns, os.path.getsize(str(card.out)),
            _record(card)) == before, "a failed build leaves the last build as it was"


def test_a_closed_gate_after_a_mode_build_says_the_modes_were_left_out(card, tmp_path, monkeypatch):
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0: len(jobs))
    monkeypatch.setattr(MW, "install_p2", lambda img, pay, epoch, log=None: None)
    card.state["grow"] = _mode_grow(card, tmp_path)
    _build(card, update=False)
    MP.new_mode(str(card.project), "KAIJU RUSH")    # the project still has a mode ...

    def nothing(*a, **k):                           # ... the gate left it out
        raise engine.NothingToWrite("Nothing to write: ...")
    monkeypatch.setattr(engine, "_compute_patches", nothing)
    _counts, lines = _build(card)
    said = [m for m, _l in lines if "written as the original card" in m]
    assert said and "1 mode(s) are left out of this build" in said[0]


def test_the_prebuilt_runtime_missing_stops_the_mode_build_with_its_reason(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_runtime as MR

    def gone():
        raise FileNotFoundError("the pinned mode runtime is missing - rebuild it")
    monkeypatch.setattr(MR, "prebuilt_object", gone)
    port = tmp_path / "game.port"
    port.write_text("game godzilla_pro\n")
    plan = MW.ModePlan(project=str(tmp_path), profile=GZ, port=str(port), build=None)
    with pytest.raises(MW.ModeWriteError, match="pinned mode runtime is missing"):
        MW.p2_payload(plan, str(tmp_path / "p2"))


def test_a_whole_build_drops_the_last_builds_p2_checksum(card, tmp_path, monkeypatch):
    """mode_install records <out>.p2.md5; a whole build lays the ORIGINAL p2 back down, so
    the old checksum goes (a mode build's install writes a fresh one)."""
    monkeypatch.setattr(ext4_grow, "grow_files_pinned",
                        lambda img, off, jobs, epoch, log=None, timeout=0: len(jobs))
    monkeypatch.setattr(MW, "install_p2", lambda img, pay, epoch, log=None: None)
    card.state["grow"] = _mode_grow(card, tmp_path)
    _build(card, update=False)
    side = str(card.out) + engine.P2_SIDECAR_SUFFIX
    with open(side, "w") as f:
        f.write("ca61e9f7  p2\n")

    def nothing(*a, **k):
        raise engine.NothingToWrite("Nothing to write: ...")
    monkeypatch.setattr(engine, "_compute_patches", nothing)
    _build(card)
    assert not os.path.exists(side)


def test_the_copy_stage_timing_line_names_what_a_mode_build_copies():
    """The ext4 copy stage's timing line says it copies the modes' files (and the grown sound
    bank) when the build carries modes, not "the full-size (grown) videos"."""
    name = engine._grow_stage_name
    assert name(None) == "copying the files that outgrew their slots into the card"
    assert name({"jobs": [], "modes": None}) == name(None)
    # PAD-176: without modes it names what it copies, not "videos" for a grown bank alone
    two = [("a", "x"), ("b", "y")]
    assert (name({"jobs": two[:1], "n_video": 0, "audio_job": 0})
            == "copying the grown sound bank into the card")
    assert (name({"jobs": two, "n_video": 1, "audio_job": None})
            == "copying the full-size videos and the rebuilt game files into the card")
    assert (name({"jobs": two, "n_video": 1, "audio_job": 1})
            == "copying the full-size videos and the grown sound bank into the card")
    modes = {"added": ["a", "b"], "rewritten": ["c", "d", "e"], "end_sound": {"name": "KAIJU RUSH"}}
    got = name({"jobs": [], "modes": modes})
    assert "videos" not in got
    assert "the modes' files (2 added, 3 rewritten), the grown sound bank" in got
    modes["end_sound"] = None
    got = name({"jobs": [], "modes": modes})
    assert "sound bank" not in got and "(2 added, 3 rewritten)" in got


def test_the_completion_dialog_names_the_modes_and_their_end_sound():
    """A modes-only Write never reads "Wrote no changes", and a mode's own end sound is named
    with its mode rather than counted as a replaced sound."""
    from pinball_decryptor.plugins.stern.pipeline import _write_summary_with_modes as say
    two = {"names": ["ATOMIC BREATH", "KAIJU RUSH"]}
    assert say((0, 0, 0, 0), two) == "2 mode(s) (ATOMIC BREATH, KAIJU RUSH)"
    two["end_sound"] = {"name": "KAIJU RUSH", "request": 1295, "idx": 1560}
    assert say((1, 0, 0, 0), two) == \
        "2 mode(s) (ATOMIC BREATH, KAIJU RUSH; KAIJU RUSH with its own end sound)"
    assert say((3, 1, 0, 0), two) == ("2 sound(s), 1 video(s) and 2 mode(s) (ATOMIC BREATH, "
                                       "KAIJU RUSH; KAIJU RUSH with its own end sound)")
    # no modes on the card (none in the project, or the runtime never reached it): as before
    assert say((1, 0, 0, 0), None) == "1 sound(s)" and say((0, 0, 0, 0), {}) == "no changes"


@pytest.mark.parametrize("before,after,counts,expect", [
    # every mode taken out: the engine wrote the original card
    ({"complete": True, "modes": {"names": ["ATOMIC BREATH", "KAIJU RUSH"]}},
     {"complete": True}, (0, 0, 0, 0),
     "Wrote the original card with the last build's modes taken out (ATOMIC BREATH, KAIJU RUSH) "
     "to OUT"),
    # the same card written with modes again: named from the new record
    ({"complete": True, "modes": {"names": ["KAIJU RUSH"]}},
     {"complete": True, "modes": {"names": ["KAIJU RUSH"]}}, (0, 0, 0, 0),
     "Wrote 1 mode(s) (KAIJU RUSH) to OUT"),
    # no modes before or after: the summary it always was
    ({}, {"complete": True}, (0, 1, 0, 0), "Wrote 1 video(s) to OUT"),
    # the modes taken out but other edits written: the counts say what went in
    ({"complete": True, "modes": {"names": ["KAIJU RUSH"]}}, {"complete": True}, (2, 0, 0, 0),
     "Wrote 2 sound(s) to OUT"),
])
def test_the_completion_dialog_after_a_write_that_takes_the_modes_out(monkeypatch, before, after,
                                                                        counts, expect):
    """The Write tab's pipeline, engine stubbed: a Write that takes every mode out of a card
    says it wrote the original card and names the modes it took out, never "no changes"."""
    from pinball_decryptor.plugins.stern import pipeline as PL
    records = {"n": 0}

    def read(path):
        records["n"] += 1
        return dict(before if records["n"] == 1 else after)
    monkeypatch.setattr(PL, "detect_game", lambda p: "godzilla_pro")
    monkeypatch.setattr(PL, "_log_multi_image", lambda p, log: None)
    monkeypatch.setattr(engine, "AVAILABLE", True, raising=False)
    monkeypatch.setattr(engine, "read_build_manifest", read)
    monkeypatch.setattr(engine, "write_image", lambda *a, **k: (counts, None, None))
    done = []
    p = PL.SternWritePipeline("ORIG", "PROJECT", "OUT", lambda *a, **k: None,
                              lambda *a: None, lambda *a, **k: None,
                              lambda ok, summary: done.append((ok, summary)))
    p.run()
    assert done == [(True, expect)]


@pytest.mark.parametrize("env,needle", [
    (None, "a direct-SD write cannot add files to the card"),
    ("0", "PAD_STERN_MODES=0"),
])
def test_the_direct_sd_dialog_says_the_modes_were_left_out(monkeypatch, tmp_path, env, needle):
    """A Direct-SD write leaves a project's modes out (it cannot add files), and the completion
    dialog says so: "Wrote 1 sound(s) directly to the SD card." alone read as if they went."""
    from pinball_decryptor.plugins.stern import pipeline as PL
    if env is not None:
        monkeypatch.setenv(MW.GATE_ENV, env)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(PL, "is_device_path", lambda p: True)
    monkeypatch.setattr(engine, "AVAILABLE", True, raising=False)
    monkeypatch.setattr(engine, "write_device", lambda *a, **k: ((1, 0, 0, 0), None, None))

    def run():
        done = []
        PL.SternDirectSsdWritePipeline(r"\\.\PHYSICALDRIVE9", str(project), lambda *a, **k: None,
                                       lambda *a: None, lambda *a, **k: None,
                                       lambda ok, summary: done.append((ok, summary))).run()
        return done
    # no modes: the dialog it always was
    assert run() == [(True, "Wrote 1 sound(s) directly to the SD card.")]
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(str(project), spec=spec)
    [(ok, summary)] = run()
    assert ok and summary.startswith("Wrote 1 sound(s) directly to the SD card.\n\nModes: ")
    assert "the project's 2 mode(s) (ATOMIC BREATH, KAIJU RUSH) were left out: " in summary
    assert needle in summary


def test_the_image_write_dialog_says_a_mac_left_the_modes_out(monkeypatch, tmp_path):
    """An IMAGE Write whose modes a gate refused (a Mac) still writes the other edits, and the
    completion dialog says the modes were left out and why, rather than only "Wrote ..."."""
    from pinball_decryptor.plugins.stern import pipeline as PL
    project = tmp_path / "project"
    project.mkdir()
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(str(project), spec=spec)
    monkeypatch.delenv(MW.GATE_ENV, raising=False)
    monkeypatch.setattr(PL, "detect_game", lambda p: "godzilla_pro")
    monkeypatch.setattr(PL, "_log_multi_image", lambda p, log: None)
    monkeypatch.setattr(engine, "AVAILABLE", True, raising=False)
    monkeypatch.setattr(engine, "write_image", lambda *a, **k: ((1, 0, 0, 0), None, None))
    record = {"complete": True}
    monkeypatch.setattr(engine, "read_build_manifest", lambda p: dict(record))

    def run():
        done = []
        PL.SternWritePipeline("ORIG", str(project), "OUT", lambda *a, **k: None, lambda *a: None,
                              lambda *a, **k: None,
                              lambda ok, summary: done.append((ok, summary))).run()
        return done
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: MW.MAC_REFUSAL)
    [(ok, summary)] = run()
    assert ok and summary.startswith("Wrote 1 sound(s) to OUT\n\nModes: ")
    assert "the project's 2 mode(s) (ATOMIC BREATH, KAIJU RUSH) were left out: " in summary
    assert MW.MAC_REFUSAL in summary
    # the build carried them (a Windows or Linux Write): named, and no left-out sentence
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    monkeypatch.setattr(MW, "gate", lambda dev, ext4=None, platform=None: (True, ""))
    record["modes"] = {"names": ["ATOMIC BREATH", "KAIJU RUSH"]}
    [(ok, summary)] = run()
    assert summary == "Wrote 1 sound(s) and 2 mode(s) (ATOMIC BREATH, KAIJU RUSH) to OUT"


# ---- Try it: the emulator's set IS Write's code ---------------------------------------------------
def _set_bytes(set_dir):
    """{relative path: bytes} of every file an override set and its stage hold, the manifest
    and delta aside (they carry a random generation and a clock)."""
    out = {}
    for root in (set_dir, set_dir + engine.OVERRIDE_MODES_SUFFIX):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name in (engine.OVERRIDE_MANIFEST, engine.OVERRIDE_DELTA):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, os.path.dirname(set_dir)).replace("\\", "/")
                rel = rel.split("/", 1)[1] if root == set_dir else "modes/" + rel.split("/", 1)[1]
                with open(full, "rb") as f:
                    out[rel] = f.read()
    return out


def test_try_it_is_the_emulate_set_built_by_writes_code(monkeypatch, tmp_path):
    """Try it's set is engine.write_overrides' set - the rewritten scenes, the new clips, the
    composed manifest, the grown bank with the mode's end sound and the patched game program -
    with the runtime, the port and the mode files beside it, as item 127's tab reads them."""
    _card, _staged, project, encoded, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    original.write_bytes(b"x" * 4096)
    msgs, log = _capture()
    ts = MW.build_tryit_set(str(project), str(original), str(tmp_path / "tryit"), log=log)
    assert ts.set_dir == os.path.join(str(tmp_path / "tryit"), "set")
    assert ts.stage_dir == ts.set_dir + engine.OVERRIDE_MODES_SUFFIX
    auto = "godzilla_pro/assets/lcd/auto_loaded/%s/scene.assets/2.asset/" % GZ.bank_scene
    for rel in (HUD_REL, BANK_REL, auto + "598.asset", auto + "599.asset",
                IMG_PATH.lstrip("/"), SIDX_PATH.lstrip("/"), FW_PATH.lstrip("/")):
        assert rel in ts.files, rel
    assert ts.new_files == [auto + "598.asset", auto + "599.asset"]
    assert ts.mode_files == ["mode.cfg", "mode1.cfg"]
    assert [(s, n) for s, _g, n in ts.slots] == [(0, "ATOMIC BREATH"), (1, "KAIJU RUSH")]
    assert ts.end_sound == {"name": "KAIJU RUSH", "request": 1295, "idx": 0}
    assert encoded and encoded[0].endswith("end.wav"), "the end sound went into the set's bank"
    for name in (engine.OVERRIDE_MODES_OBJECT, "game.port", "mode.cfg", "mode1.cfg"):
        assert os.path.isfile(os.path.join(ts.stage_dir, name)), name
    assert ts.port == os.path.join(ts.stage_dir, "game.port") and ts.game_dir == "godzilla_pro"
    assert MW.tryit_env(r"C:\Users\x\set") == ["PAD_OVERRIDE_DIR=/mnt/c/Users/x/set",
                                               "PAD_MODE_SO=/lib/pad_mode.so"]
    # the same bytes as the Emulate tab's own set for the same project and card
    engine.write_overrides(str(original), str(project), str(tmp_path / "emulate" / "set"), log=log)
    mine, theirs = _set_bytes(ts.set_dir), _set_bytes(str(tmp_path / "emulate" / "set"))
    assert sorted(mine) == sorted(theirs) and "modes/pad_mode.so" in mine
    assert [k for k in mine if mine[k] != theirs[k]] == []


def test_try_it_says_why_it_cannot_build(monkeypatch, tmp_path):
    _card, _staged, project, _enc, _h = _mode_card(monkeypatch, tmp_path)
    original = tmp_path / "original.raw"
    original.write_bytes(b"x" * 4096)
    base = str(tmp_path / "tryit")
    (tmp_path / "empty").mkdir()
    with pytest.raises(MW.ModeWriteError, match="no modes in this project"):
        MW.build_tryit_set(str(tmp_path / "empty"), str(original), base)
    with pytest.raises(MW.ModeWriteError, match="Pick the card image"):
        MW.build_tryit_set(str(project), str(tmp_path / "nope.raw"), base)
    # the kill switch leaves the modes out of the set, and Try it refuses rather than running
    # a card with none of them
    monkeypatch.setenv(MW.GATE_ENV, "0")
    with pytest.raises(MW.ModeWriteError, match="Nothing to write"):
        MW.build_tryit_set(str(project), str(original), base, log=lambda m: None)


# ---- item 150's own sounds through Write (start, shot, music on carriers) ---------------------
def _own_sounds_card(monkeypatch, tmp_path, **kw):
    """_mode_card, with ATOMIC BREATH given a 0.5 s start sound and a 0.6 s music, and each
    carrier's request resolving to its own stock record (the time-up call to idx 0); the music's
    bed (item 150 follow-up: Pro 1.15's first bed, sid 257) resolves to idx 3."""
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    card, staged, project, encoded, hmac = _mode_card(monkeypatch, tmp_path, **kw)
    calls = list(MS.TITLES[("godzilla_pro", "1.15")].calls)
    records = {1295: 0, calls[0]: 1, 125: 3}
    monkeypatch.setattr(MW, "request_record",
                        lambda elf, head, params, sites, request, mask: records[request])
    monkeypatch.setattr(MW, "sid_record", lambda params, sites, sid, mask: {257: 3}[sid])
    slug = "atomic_breath"
    folder = MP.mode_folder(str(project), slug)
    _wav(os.path.join(folder, "go.wav"), 0.5)
    _wav(os.path.join(folder, "theme.wav"), 0.6)
    spec = MP.load(os.path.join(folder, MP.MODE_FILE))
    spec.sound_start, spec.music = "go.wav", "theme.wav"
    MP.save(str(project), slug, spec)
    return card, staged, project, encoded, calls


def test_a_modes_start_sound_and_music_go_on_the_card_on_their_carriers(monkeypatch, tmp_path):
    _card, staged, project, encoded, calls = _own_sounds_card(monkeypatch, tmp_path)
    msgs, log = _capture()
    writes, counts, plan, _mode, _vp = _compute(project, log)
    # the end sound on the time-up record, the start sound and the music on their carriers'
    assert sorted(encoded) == [0, 1, 3]
    assert encoded[0].endswith("end.wav") and encoded[1].endswith("go.wav")
    # its own bed's record (item 150 follow-up), a seamless loop on the 10 ms grid, repeated whole
    # until it outlasts the mode (so the mode never reaches the record's own loop)
    assert os.path.basename(encoded[3]) == "music_3_loop.wav"
    import wave
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    secs = MP.load(os.path.join(MP.mode_folder(str(project), "atomic_breath"), MP.MODE_FILE)).seconds
    with wave.open(engine._lp(encoded[3]), "rb") as w:
        frames = w.getnframes()
    loop = int(0.6 * 44100)
    assert frames % loop == 0 and frames % 441 == 0
    assert frames >= MS.bed_min_frames(secs) > frames - loop
    assert staged["path"]
    own = plan["modes"]["own_sounds"]
    assert own == [
        {"slug": "atomic_breath", "name": "ATOMIC BREATH", "key": "sound_start",
         "request": calls[0], "idx": 1, "ms": 500},
        {"slug": "atomic_breath", "name": "ATOMIC BREATH", "key": "music", "request": 125,
         "sid": 257, "idx": 3, "ms": None}]
    assert plan["modes"]["end_sound"] == {"name": "KAIJU RUSH", "request": 1295, "idx": 0}
    # ATOMIC BREATH is slot 0: its mode file names both carriers, KAIJU RUSH's names none
    cfgs = {os.path.basename(c): open(c, encoding="utf-8").read()
            for c in plan["modes"]["payload"]["cfgs"]}
    assert "sound_start    %d 500" % calls[0] in cfgs["mode.cfg"]
    assert "music          125 257" in cfgs["mode.cfg"]
    assert "sound_start" not in cfgs["mode1.cfg"] and "music" not in cfgs["mode1.cfg"]
    assert _said(msgs, "ATOMIC BREATH's own start sound (go.wav, 0.50 s) goes on the card as a "
                       "new record for request %d" % calls[0])
    assert _said(msgs, "is made a seamless 0.600 s loop and repeated %d time(s)" % (frames // loop))
    assert _said(msgs, "its own start sound go.wav (request %d)" % calls[0])
    engine._rmtree_grow_plan(plan)


def test_a_carrier_that_another_edit_replaces_is_refused(monkeypatch, tmp_path):
    _card, _staged, project, _enc, calls = _own_sounds_card(monkeypatch, tmp_path, audio_edit=True,
                                                             sound_idx=1)
    monkeypatch.setattr(MW, "request_record",
                        lambda elf, head, params, sites, request, mask:
                        {1295: 0, calls[0]: 1, 125: 3}[request])
    _msgs, log = _capture()
    with pytest.raises(RuntimeError, match="start sound goes in place of sound idx 1"):
        _compute(project, log)


def test_the_sound_gate_closed_leaves_the_carried_sounds_out_too(monkeypatch, tmp_path):
    _card, staged, project, encoded, _calls = _own_sounds_card(monkeypatch, tmp_path)
    monkeypatch.setenv(MW.SOUND_ENV, "0")
    msgs, log = _capture()
    _writes, _counts, plan, _m, _v = _compute(project, log)
    assert not encoded and "path" not in staged
    assert plan["modes"]["own_sounds"] == [] and plan["modes"]["end_sound"] is None
    assert _said(msgs, "the start sound, shot sound and music of ATOMIC BREATH are not put on")
    cfg = open(plan["modes"]["payload"]["cfgs"][0], encoding="utf-8").read()
    assert "sound_start" not in cfg and "music" not in cfg
    engine._rmtree_grow_plan(plan)


def test_the_completion_dialog_names_the_modes_own_sounds():
    from pinball_decryptor.plugins.stern.pipeline import _write_summary_with_modes as say
    modes = {"names": ["ATOMIC BREATH", "KAIJU RUSH"],
             "end_sound": {"name": "KAIJU RUSH", "request": 1295, "idx": 0},
             "own_sounds": [{"name": "ATOMIC BREATH", "key": "sound_start"},
                            {"name": "ATOMIC BREATH", "key": "music"}]}
    assert say((3, 0, 0, 0), modes) == (
        "2 mode(s) (ATOMIC BREATH, KAIJU RUSH; KAIJU RUSH with its own end sound, ATOMIC BREATH "
        "with its own start sound, ATOMIC BREATH with its own music)")
    assert say((4, 0, 0, 0), modes).startswith("1 sound(s) and 2 mode(s)")
    # a code mode's calls are counted once per mode, not listed one by one
    code = {"names": ["ANGUIRUS"], "own_sounds": [{"name": "ANGUIRUS", "key": "music"}] + [
        {"name": "ANGUIRUS", "key": "call:%s" % c} for c in ("spike", "roll", "won", "lost")]}
    assert say((5, 0, 0, 0), code) == ("1 mode(s) (ANGUIRUS; ANGUIRUS with its own music, ANGUIRUS with 4 "
                                       "call(s) of its own)")


def test_the_blip_free_note_is_left_out_when_every_sound_is_a_modes_own():
    from pinball_decryptor.plugins.stern.pipeline import _only_mode_sounds
    code = {"names": ["ANGUIRUS"], "own_sounds": [{"key": "music"}, {"key": "call:won"}]}
    assert _only_mode_sounds((2, 0, 0, 0), code)
    assert not _only_mode_sounds((3, 0, 0, 0), code)          # a replaced stock sound as well
    assert not _only_mode_sounds((1, 0, 0, 0), None)
    assert _only_mode_sounds((1, 0, 0, 0), {"end_sound": {"name": "K"}})
