"""PAD-444 (DoomWalrus666): which of the game's own modes plays each clip, and a mode's own copy
of a clip it shares with another (Godzilla's battle vs Gigan and the Ghidorah and Gigan tag
team play the same two clips).

The reading and the copy are checked on synthetic bytes (the ownership rules, the program plan,
the bank, the project record) and on the real Godzilla 1.16 game programs where the cards are
on this machine (skipped elsewhere, as on CI). The Video tab's side runs in the web harness with
the card's reading stubbed."""

import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import video_bank as VB
from tests.test_stern_video_bank import synthetic
from tests.test_webui_video import _project, _row, _rels, _scan, _wait
from tests.webui_harness import web_app

GIGAN = "cmode_battle_vs_gigan"
TAG = "cmode_battle_vs_ghidorah_and_gigan"
CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
BANK_DIR = "auto_loaded/" + VB.GODZILLA_PRO_BANK


# ---- names -----------------------------------------------------------------------------------
def test_a_copy_is_named_after_its_clip_and_its_mode_and_never_twice():
    assert CM.own_name("gigan_ghidorah_vs_godzilla13", TAG) == \
        "gigan_ghidorah_vs_godzilla13_battle_vs_ghidorah_and_gigan"
    taken = {"gigan_ghidorah_vs_godzilla13_battle_vs_gigan"}
    assert CM.own_name("gigan_ghidorah_vs_godzilla13", GIGAN, taken) == \
        "gigan_ghidorah_vs_godzilla13_battle_vs_gigan_2"
    long = "TagTeamIntro_GodzillaAnguirusVsKingGhidorahGigan"
    n = CM.own_name(long, TAG)
    assert len(n) <= CM.NAME_MAX and n.startswith(long + "_battle")
    assert CM.mode_label(TAG) == "Battle vs Ghidorah and Gigan"
    assert CM.mode_label("cmode_battle_vs_megalon_and_gigan_mb") == \
        "Battle vs Megalon and Gigan Multiball"


def test_a_copy_built_into_a_card_is_known_again_by_its_name():
    names = {"clip13", "clip13_battle_vs_gigan"}
    labels = {GIGAN: "Battle vs Gigan", TAG: "Battle vs Ghidorah and Gigan"}
    assert CM.copy_of("clip13_battle_vs_gigan", names, labels) == ("clip13", GIGAN)
    assert CM.copy_of("clip13", names, labels) is None
    assert CM.copy_of("other_battle_vs_gigan", names, labels) is None


# ---- whose code ------------------------------------------------------------------------------
class _Prog:
    def __init__(self, refs=None):
        self._refs = refs or {}

    def func_start(self, va):
        return va & ~0xFF

    def references(self, va):
        return self._refs.get(va, [])


def test_a_function_is_a_modes_by_its_virtuals_its_files_initialiser_or_its_neighbours():
    anchors = {0x1000: GIGAN, 0x1400: GIGAN, 0x2000: TAG, 0x2800: TAG}
    own = CM._Owners(None, _Prog(), anchors, inits=[0x1ff0, 0x2a00])
    assert own.of_function(0x1000) == (GIGAN, "own")
    assert own.of_function(0x1200) == (GIGAN, "unit")         # between two of its own
    assert own.of_function(0x1800) == ("", "")                # between two modes' files
    assert own.of_function(0x1ff8) == (GIGAN, "init")         # a prologue before the push
    assert own.of_function(0x2a00) == (TAG, "init")           # ends the tag team's file
    assert own.of_function(0x0800) == ("", "")                # before every mode


def test_a_table_is_a_modes_when_only_its_code_loads_it():
    anchors = {0x1000: GIGAN, 0x2000: TAG}
    prog = _Prog({0x8000: [0x1010], 0x9000: [0x1010, 0x2010]})
    own = CM._Owners(None, prog, anchors, inits=[])
    assert own.of_table(0x8000 + 4 * 3) == (GIGAN, "table")   # walked back to the table's start
    assert own.of_table(0x9000 + 4) == ("", "")              # two modes read it


# ---- the program -----------------------------------------------------------------------------
BASE = 0x10000


def _movw(rd, imm):
    return 0xE3000000 | (rd << 12) | ((imm >> 12) << 16) | (imm & 0xFFF)


def _movt(rd, imm):
    return 0xE3400000 | (rd << 12) | ((imm >> 12) << 16) | (imm & 0xFFF)


def _elf():
    """A minimal ARM ELF: one PT_LOAD over the whole file at BASE, two movw/movt pairs naming
    one clip (one per mode) and a table word naming it for the second mode again."""
    raw = bytearray(0x400)
    raw[0:4] = b"\x7fELF"
    raw[4], raw[5], raw[6] = 1, 1, 1
    struct.pack_into("<HHIIIIIHHHHHH", raw, 0x10, 2, 40, 1, BASE, 0x34, 0, 0, 0x34, 32, 1,
                     40, 0, 0)
    struct.pack_into("<8I", raw, 0x34, 1, 0, BASE, 0, 0x400, 0x400, 5, 0x1000)
    raw[0x300:0x30e] = b"\0shared_clip\0\0"
    name_va = BASE + 0x301
    for off, rd in ((0x100, 2), (0x200, 3)):
        struct.pack_into("<II", raw, off, _movw(rd, name_va & 0xFFFF), _movt(rd, name_va >> 16))
    struct.pack_into("<I", raw, 0x280, name_va)
    return bytes(raw), name_va


def _reading(raw):
    return CM.Reading(sha1="x", labels={GIGAN: "Battle vs Gigan", TAG: "Battle vs Ghidorah and Gigan"},
                      refs={"shared_clip": [CM.Ref("movw_a32", [0x100, 0x104], BASE + 0x100, GIGAN, "own"),
                                            CM.Ref("movw_a32", [0x200, 0x204], BASE + 0x200, TAG, "init"),
                                            CM.Ref("lone", [0x280], BASE + 0x280, TAG, "table")]})


def _rec(state="own"):
    return {"name": "shared_clip_battle_vs_ghidorah_and_gigan", "clip": "shared_clip", "mode": TAG,
            "rel": "video/x.mp4", "of": "video/shared_clip.mp4", "state": state}


def test_only_the_modes_own_references_move_to_its_copys_new_name():
    raw, name_va = _elf()
    plan = CM.program_plan(raw, [_rec()], ["shared_clip"], 0x90000, reading=_reading(raw))
    assert plan.blob == b"shared_clip_battle_vs_ghidorah_and_gigan\0" + b"\0" * 3
    assert {r.at for r, _va in plan.moves} == {BASE + 0x200, BASE + 0x280}
    assert all(va == 0x90000 for _r, va in plan.moves)
    assert CM.check_program(raw, plan)
    buf = bytearray(raw)
    for off, b in plan.writes:
        buf[off:off + len(b)] = b
    from pinball_decryptor.plugins.stern import progreloc
    assert progreloc.reference_value(bytes(buf), {"kind": "movw_a32", "offs": [0x100, 0x104]}) == name_va
    assert progreloc.reference_value(bytes(buf), {"kind": "movw_a32", "offs": [0x200, 0x204]}) == 0x90000
    assert struct.unpack_from("<I", buf, 0x280)[0] == 0x90000
    assert plan.done == [_rec()] and "Battle vs Ghidorah and Gigan plays its own copy" in plan.lines[0]


def test_a_copy_the_program_already_names_needs_no_write_and_one_put_back_moves_back():
    raw, name_va = _elf()
    done = CM.Reading(labels=_reading(raw).labels, refs={
        "shared_clip": [CM.Ref("movw_a32", [0x100, 0x104], BASE + 0x100, GIGAN, "own")],
        "shared_clip_battle_vs_ghidorah_and_gigan": [
            CM.Ref("movw_a32", [0x200, 0x204], BASE + 0x200, TAG, "init")]})
    again = CM.program_plan(raw, [_rec()], ["shared_clip"], 0x90000, reading=done)
    assert again.writes == [] and again.blob == b"" and again.done == [_rec()]
    back = CM.program_plan(raw, [_rec("shared")], ["shared_clip"], 0x90000, reading=done)
    assert back.blob == b""                                   # the shared name is in the program
    assert [(r.at, va) for r, va in back.moves] == [(BASE + 0x200, name_va)]
    assert "plays shared_clip again" in back.lines[0]


def test_a_mode_that_never_names_the_clip_is_left_out_with_the_reason():
    raw, _va = _elf()
    rec = dict(_rec(), mode="cmode_hedorah")
    plan = CM.program_plan(raw, [rec], ["shared_clip"], 0x90000, reading=_reading(raw))
    assert plan.writes == [] and plan.done == []
    assert plan.skipped == [(rec, "the game program has no place where Hedorah plays shared_clip")]


# ---- the bank and the files ------------------------------------------------------------------
def test_the_bank_gains_each_copy_once_and_keeps_every_stock_clip():
    bank = synthetic()
    new, added = CM.bank_plan(bank, [("Gamma", 5000), ("Alpha", 9), ("Gamma", 5000)])
    assert added == [("Gamma", "2.asset/3.asset")]
    b = VB.parse(new)
    assert [c.name for c in b.library.entries] == ["Alpha", "Delta", "Gamma", "zeta"]
    assert next(c for c in b.library.entries if c.name == "Gamma").size == 5000


def _job(tmp_path, recs, data=b"copy bytes"):
    proj = tmp_path / "proj"
    (proj / "video").mkdir(parents=True)
    for r in recs:
        (proj / r["rel"]).write_bytes(data)
    rows = {"video/Alpha.mp4": "/g/%s/scene.assets/2.asset/0.asset" % BANK_DIR}
    job = CM.WriteJob(recs, rows, {"/g/" + BANK_DIR: synthetic()})
    return proj, job


def test_a_copy_becomes_a_new_clip_file_beside_its_banks_clips(tmp_path):
    rec = {"name": "Alpha_battle_vs_gigan", "clip": "Alpha", "mode": GIGAN,
           "rel": "video/Alpha_battle_vs_gigan.mp4", "of": "video/Alpha.mp4", "state": "own"}
    proj, job = _job(tmp_path, [rec])
    assert job.bank_dir(rec) == "/g/" + BANK_DIR
    job.done = [rec]
    replaced, new, lines = job.bank_files(str(proj), str(tmp_path / "scratch"))
    (rel, staged), = replaced
    assert rel == "g/%s/scene.radium" % BANK_DIR
    entry = next(c for c in VB.parse(open(staged, "rb").read()).library.entries
                 if c.name == rec["name"])
    assert entry.path == "2.asset/3.asset" and entry.size == len(b"copy bytes")
    assert new == [("g/%s/scene.assets/2.asset/3.asset" % BANK_DIR,
                    str(proj / rec["rel"]))]
    assert "Battle vs Gigan's own copy Alpha_battle_vs_gigan is a new clip" in lines[0]
    # put back, or a program part that did not happen: nothing in the bank
    job.done = [dict(rec, state="shared")]
    assert job.bank_files(str(proj), str(tmp_path / "s2")) == ([], [], [])


def test_a_copy_whose_file_is_gone_stops_the_write(tmp_path):
    rec = {"name": "Alpha_battle_vs_gigan", "clip": "Alpha", "mode": GIGAN,
           "rel": "video/Alpha_battle_vs_gigan.mp4", "of": "video/Alpha.mp4", "state": "own"}
    proj, job = _job(tmp_path, [rec])
    os.remove(proj / rec["rel"])
    job.done = [rec]
    with pytest.raises(CM.ClipModesError, match="is not in the project"):
        job.bank_files(str(proj), str(tmp_path / "scratch"))


def test_the_record_round_trips_and_revert_all_takes_the_copies_away(tmp_path):
    proj = tmp_path / "p"
    (proj / "video").mkdir(parents=True)
    (proj / "video" / "manifest.txt").write_text(
        "# output\tcard path\tbytes\non_card.mp4\t/g/x/scene.assets/1.asset\t5\n", encoding="utf-8")
    (proj / ".staged_changes.json").write_text(json.dumps({"video": {"video/a.mp4": "x"}}))
    mine = proj / "video" / "a_battle_vs_gigan.mp4"
    mine.write_bytes(b"1")
    (proj / "video" / "on_card.mp4").write_bytes(b"2")
    recs = [{"name": "a_battle_vs_gigan", "clip": "a", "mode": GIGAN, "rel": "video/a_battle_vs_gigan.mp4",
             "of": "video/a.mp4", "state": "own"},
            {"name": "on_card", "clip": "b", "mode": TAG, "rel": "video/on_card.mp4",
             "of": "video/b.mp4", "state": "shared"}]
    CM.save_records(str(proj), recs)
    assert CM.records(str(proj)) == recs and CM.pending(str(proj)) == 2
    data = json.loads((proj / ".staged_changes.json").read_text())
    assert data["video"] == {"video/a.mp4": "x"}               # the other keys are kept
    assert CM.remove_copies(str(proj)) == 1
    assert not mine.exists() and (proj / "video" / "on_card.mp4").exists()
    assert CM.records(str(proj)) == []


# ---- the real game programs (David's machine) ------------------------------------------------
def _program_and_bank(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        elf = img.preview(part, "/%s/game" % game, cap=256 << 20)
        bank = img.preview(part, "/%s/assets/lcd/%s/scene.radium" % (game, BANK_DIR), cap=64 << 20)
    return elf, [c.name for c in VB.parse(bank).library.entries]


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_godzilla_116_shares_two_gigan_clips_between_its_two_gigan_battles(card):
    pytest.importorskip("numpy")
    elf, names = _program_and_bank(card)
    r = CM.analyse(elf, names)
    shared = {n: r.modes_of(n) for n in r.refs if len(r.modes_of(n)) > 1}
    assert shared == {"gigan_ghidorah_vs_godzilla13": [TAG, GIGAN],
                      "gigan_ghidorah_vs_godzilla17": [TAG, GIGAN],
                      "PlanetX_Normal_Loop": ["cmode_o2_destroyer", "cmode_planet_x_multiball"]}
    # the Megalon and Gigan tag team shares nothing with them
    assert "cmode_battle_vs_megalon_and_gigan_mb" in r.labels
    mg = {n for n in r.refs if "cmode_battle_vs_megalon_and_gigan_mb" in r.modes_of(n)}
    assert mg and not any(len(r.modes_of(n)) > 1 for n in mg)


def test_a_copy_on_the_real_program_moves_one_battle_and_comes_back(tmp_path):
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import engine
    elf, names = _program_and_bank(PRO116)
    clip = "gigan_ghidorah_vs_godzilla13"
    rec = {"name": CM.own_name(clip, TAG, names), "clip": clip, "mode": TAG, "state": "own"}
    reloc, why = engine._text_reloc_plan(elf)
    assert reloc is not None, why
    plan = CM.program_plan(elf, [rec], names, reloc["base_va"] + reloc["used"])
    assert CM.check_program(elf, plan) and len(plan.moves) == 1
    out = str(tmp_path / "game")
    engine._grow_program_text(elf, plan.writes, plan.blob, reloc, out, str(tmp_path), None,
                              lambda *a, **k: None)
    grown = open(out, "rb").read()
    r = CM.analyse(grown, names + [rec["name"]])
    assert r.modes_of(clip) == [GIGAN] and r.modes_of(rec["name"]) == [TAG]
    reloc2, _why = engine._text_reloc_plan(grown)
    base2 = reloc2["base_va"] + reloc2["used"]
    assert CM.program_plan(grown, [rec], names, base2).writes == []      # a second build
    back = CM.program_plan(grown, [dict(rec, state="shared")], names, base2)
    buf = bytearray(grown)
    for off, b in back.writes:
        buf[off:off + len(b)] = b
    r2 = CM.analyse(bytes(buf), names + [rec["name"]])
    assert r2.modes_of(clip) == [TAG, GIGAN] and r2.modes_of(rec["name"]) == []


# ---- the Video tab ---------------------------------------------------------------------------
SHARED, SOLO, OTHER = "video/shared.mp4", "video/solo.mp4", "video/other.mp4"


def _stub_reading(monkeypatch, tmp_path, proj):
    card = tmp_path / "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
    card.write_bytes(b"\0" * 16)
    (proj / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(card), "input_name": card.name}), encoding="utf-8")
    reading = CM.Reading(labels={GIGAN: "Battle vs Gigan", TAG: "Battle vs Ghidorah and Gigan"}, refs={
        "shared": [CM.Ref("movw_a32", [1, 2], 1, GIGAN, "init"), CM.Ref("movw_a32", [3, 4], 3, TAG, "init")],
        "solo": [CM.Ref("movw_a32", [5, 6], 5, GIGAN, "own")]})
    bank = {"shared": ["/g/" + BANK_DIR, "2.asset/0.asset"], "solo": ["/g/" + BANK_DIR, "2.asset/1.asset"],
            "other": ["/g/" + BANK_DIR, "2.asset/2.asset"]}
    reads = []

    def fake(card_path, rows, cancel=None):
        reads.append(card_path)
        return CM.CardClips(card=card_path, game="godzilla_pro", version="1.16.0", reading=reading,
                            name_of={SHARED: "shared", SOLO: "solo", OTHER: "other"}, bank_of=bank)
    monkeypatch.setattr(CM, "read_card", fake)
    return reads


def test_the_tab_lists_each_clips_modes_and_filters_by_one(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER))
    reads = _stub_reading(monkeypatch, tmp_path, proj)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _wait(w, lambda st: st["modes"]["ready"])
        assert st["modes"]["list"] == [
            {"id": TAG, "label": "Battle vs Ghidorah and Gigan", "n": 1},
            {"id": GIGAN, "label": "Battle vs Gigan", "n": 2}]
        assert _row(st, SHARED)["modes"] == ["Battle vs Ghidorah and Gigan", "Battle vs Gigan"]
        assert _row(st, SHARED)["shared"] is True and _row(st, SOLO)["shared"] is False
        assert _row(st, OTHER)["modes"] == []
        assert w.call("video.set_mode_filter", TAG) is True
        assert _rels(w.state("video")) == [SHARED]
        assert w.call("video.set_mode_filter", "") is True
        assert len(_rels(w.state("video"))) == 3
        # the row menu offers each of the shared clip's modes its own copy
        info = w.call("video.row_menu", [SHARED])
        assert [m["id"] for m in info["modes"]] == [TAG, GIGAN] and info["copy"] is False
        assert w.call("video.row_menu", [SOLO])["modes"] == []
        # a second scan of the same card does not read it again
        _scan(w, proj)
        _wait(w, lambda st: st["modes"]["ready"])
        assert len(reads) == 1


def test_a_modes_own_copy_is_a_new_row_and_goes_back_to_the_shared_clip(tmp_path, monkeypatch):
    proj = _project(tmp_path, names=(SHARED, SOLO, OTHER))
    _stub_reading(monkeypatch, tmp_path, proj)
    copy = "video/shared_battle_vs_ghidorah_and_gigan.mp4"
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _wait(w, lambda st: st["modes"]["ready"])
        w.call("video.select", SHARED)
        st = _wait(w, lambda st: (st.get("preview") or {}).get("modes"))
        m = st["preview"]["modes"]
        assert [x["id"] for x in m["shared"]] == [TAG, GIGAN]
        assert m["text"].startswith("Played in Battle vs Ghidorah and Gigan and Battle vs Gigan.")
        assert w.call("video.own_copy", SOLO, GIGAN) == ""            # not shared: no copy
        w.answers.append("cancel")
        assert w.call("video.own_copy", SHARED, TAG) == ""            # cancelled: nothing made
        assert not (proj / copy).exists()
        w.answers.append("copy")
        assert w.call("video.own_copy", SHARED, TAG) == copy
        st = _wait(w, lambda st: any(r["rel"] == copy and r.get("copy") for r in st["rows"])
                   and st["modes"]["ready"] and not st.get("scanning"))
        assert (proj / copy).read_bytes() == (proj / SHARED).read_bytes()
        assert CM.records(str(proj)) == [{"name": "shared_battle_vs_ghidorah_and_gigan", "clip": "shared",
                                          "mode": TAG, "rel": copy, "of": SHARED, "state": "own"}]
        assert _row(st, copy)["copy"] == "Battle vs Ghidorah and Gigan"
        assert _row(st, copy)["rep_cls"] == ""                         # not "changed", not foreign
        assert _row(st, SHARED)["modes"] == ["Battle vs Gigan"] and _row(st, SHARED)["shared"] is False
        st = _wait(w, lambda st: (st.get("preview") or {}).get("rel") == copy
                   and (st["preview"].get("modes") or {}).get("copy"))
        assert "Battle vs Gigan keeps the shared clip" in st["preview"]["modes"]["copy"]["text"]
        assert w.call("video.row_menu", [copy])["copy"] is True
        w.answers.append("yes")
        assert w.call("video.shared_again", copy) is True
        st = _wait(w, lambda st: st["rows"] and st["modes"]["ready"] and not st.get("scanning")
                   and not any(r["rel"] == copy for r in st["rows"])
                   and _row(st, SHARED)["shared"])
        assert not (proj / copy).exists() and CM.records(str(proj)) == []
        assert _row(st, SHARED)["shared"] is True


def test_the_page_draws_played_in_the_filter_and_the_copy_buttons():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui",
                           "static", "js", "tabs", "video.js"), encoding="utf-8").read()
    for bit in ('key: "modes", label: "Played in"', 'call("video.set_mode_filter", v)',
                'call("video.own_copy", pv.modes.rel, m.id)', 'call("video.shared_again", pv.modes.rel)',
                "Give ${m.label} its own copy…", "Back to the shared clip…"):
        assert bit in js, bit
