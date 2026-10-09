"""PAD-470: which of the game's own modes shows each game-program line, and one mode's own
text for a line several modes show (plugins/stern/text_modes.py, progtext.plan_writes'
``parts``, the manifest's ``in:`` flag and ``#<mode>`` rows, the Text tab's Shown in, and
Transfer Mods keeping a mode's text on that mode's row).

The synthetic half builds a tiny ELF with two separate "KAIJU AWARD" strings (a card an
earlier build renamed two award lines on) and one "SUPER JACKPOT!" two name groups point at
(the linker's one copy of a text two lines show), and hands plan_writes a reading that says
which mode each name group is. The real half reads stock Godzilla Pro/LE 1.16 and
DoomWalrus666's Heisei V1.5 card when they are on this machine.
"""

import os
import struct

import pytest

from pinball_decryptor.core import mod_transfer, text_manifest
from pinball_decryptor.plugins.stern import progreloc, progtext, text_modes
from pinball_decryptor.webui import text_rules as R
from tests.test_stern_progtext import BODY_OFF, VBASE, _elf

GAME = "/godzilla_le/game"
A, B = "cmode_battle_vs_gigan", "cmode_battle_vs_megalon"
RELOC = {"base_va": 0x6EE000, "capacity": 0x1000, "used": 12}

CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
PRO116 = os.path.join(CARDS, "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
HEISEI15 = os.path.join(CARDS, "Godzilla Premium 1.16 Heisei Custom V1.5 Standard Edition.raw")


# ---- a synthetic program ---------------------------------------------------------------------
def _build():
    body = bytearray(b"\x00")
    offs = {}
    for key, s in (("kaiju_a", "KAIJU AWARD"), ("kaiju_b", "KAIJU AWARD"),
                   ("super", "SUPER JACKPOT!")):
        offs[key] = BODY_OFF + len(body)
        body += s.encode() + b"\x00"
    while (BODY_OFF + len(body)) % 4:
        body += b"\x00"

    def group(key, target):
        offs[key] = BODY_OFF + len(body)
        body.extend(struct.pack("<5I", *([VBASE + offs[target]] * 5)) + b"\x00" * 4)

    group("g_kaiju_a", "kaiju_a")
    group("g_kaiju_b", "kaiju_b")
    group("g_super_a", "super")
    group("g_super_b", "super")
    body.extend(b"\x00" * 16)
    return _elf(bytes(body)), offs


def _reading(raw, offs, modes):
    """A :class:`text_modes.Reading` saying which mode each name group is: *modes* maps a
    group key of :func:`_build` to a mode class."""
    ranges = progtext._load_ranges(raw)
    spans = progtext._display_spans(raw, ranges)
    census = progtext._census(raw, spans)
    by_off = {offs[k]: m for k, m in modes.items()}
    rd = text_modes.Reading()
    for off, _t in spans:
        rows = []
        for r in census.get(off, ()):
            rows.append((r, by_off.get(r["offs"][0], "")))
        rd.keys[off] = rows
        rd.shown[off] = sorted({m for _r, m in rows if m})
    rd.labels = {A: "Battle vs Gigan", B: "Battle vs Megalon"}
    return rd


@pytest.fixture()
def prog():
    raw, offs = _build()
    rd = _reading(raw, offs, {"g_kaiju_a": A, "g_kaiju_b": B,
                              "g_super_a": A, "g_super_b": B})
    return raw, offs, rd


def _log():
    msgs = []
    return msgs, (lambda m, lvl="info": msgs.append((lvl, m)))


def _apply(raw, writes):
    buf = bytearray(raw)
    for o, b in writes:
        buf[o:o + len(b)] = b
    return bytes(buf)


def _group_target(buf, offs, key):
    return struct.unpack_from("<I", buf, offs[key])[0]


def _cstr(buf, off):
    return bytes(buf[off:buf.index(b"\x00", off)]).decode()


def test_a_mode_alone_on_its_string_is_edited_in_place(prog):
    """The Heisei card's case: two strings read KAIJU AWARD, one per battle. The Gigan battle's
    own text goes over its string; the Megalon battle's string is left alone, and no new space
    is needed."""
    raw, offs, rd = prog
    msgs, log = _log()
    writes, n, blob = progtext.plan_writes(raw, {}, log, parts={("KAIJU AWARD", A): "GIGAN AWARD"},
                                           reading=rd)
    assert n == 1 and blob == b""
    buf = _apply(raw, writes)
    assert _cstr(buf, offs["kaiju_a"]) == "GIGAN AWARD"
    assert _cstr(buf, offs["kaiju_b"]) == "KAIJU AWARD"
    assert any('-> "GIGAN AWARD" in Battle vs Gigan (a string only that mode shows)' in m
               for _l, m in msgs)


def test_the_main_row_still_renames_every_line_a_mode_left_blank(prog):
    raw, offs, rd = prog
    msgs, log = _log()
    writes, n, _blob = progtext.plan_writes(
        raw, {"KAIJU AWARD": "MONSTER AWARD"}, log,
        parts={("KAIJU AWARD", B): "SPACE AWARD"}, reading=rd)
    buf = _apply(raw, writes)
    # MONSTER AWARD is longer than the slot and this write has no new space: skipped, said so
    assert _cstr(buf, offs["kaiju_a"]) == "KAIJU AWARD"
    assert any("MONSTER AWARD" in m and lvl == "warning" for lvl, m in msgs)
    assert _cstr(buf, offs["kaiju_b"]) == "SPACE AWARD"
    writes, n, _blob = progtext.plan_writes(
        raw, {"KAIJU AWARD": "BIG AWARD"}, log,
        parts={("KAIJU AWARD", B): "SPACE AWARD"}, reading=rd)
    buf = _apply(raw, writes)
    assert n == 2
    assert _cstr(buf, offs["kaiju_a"]) == "BIG AWARD"
    assert _cstr(buf, offs["kaiju_b"]) == "SPACE AWARD"


def test_a_shared_string_gives_one_mode_a_copy(prog):
    """One string, two lines: the Megalon battle's name group is pointed at a copy in new
    space and the Gigan battle's keeps the string."""
    raw, offs, rd = prog
    msgs, log = _log()
    writes, n, blob = progtext.plan_writes(
        raw, {}, log, reloc=RELOC, parts={("SUPER JACKPOT!", B): "MEGA JACKPOT!"}, reading=rd)
    assert n == 1
    copy_va = RELOC["base_va"] + RELOC["used"]
    assert blob.startswith(b"MEGA JACKPOT!\x00")
    buf = _apply(raw, writes)
    assert _group_target(buf, offs, "g_super_b") == copy_va
    assert _group_target(buf, offs, "g_super_a") == VBASE + offs["super"]
    assert _cstr(buf, offs["super"]) == "SUPER JACKPOT!"
    assert any("in Battle vs Megalon only" in m for _l, m in msgs)


def test_a_shared_string_with_a_main_edit_too(prog):
    raw, offs, rd = prog
    _msgs, log = _log()
    writes, n, blob = progtext.plan_writes(
        raw, {"SUPER JACKPOT!": "SUPER JP!"}, log, reloc=RELOC,
        parts={("SUPER JACKPOT!", B): "MEGA JP!"}, reading=rd)
    assert n == 2
    buf = _apply(raw, writes)
    assert _cstr(buf, offs["super"]) == "SUPER JP!"
    assert _group_target(buf, offs, "g_super_a") == VBASE + offs["super"]
    assert _group_target(buf, offs, "g_super_b") == RELOC["base_va"] + RELOC["used"]
    assert blob.startswith(b"MEGA JP!\x00")


def test_both_modes_given_their_own_text_on_one_string(prog):
    """The first mode gets a copy; the second is then the string's only line and takes it."""
    raw, offs, rd = prog
    _msgs, log = _log()
    writes, n, blob = progtext.plan_writes(
        raw, {}, log, reloc=RELOC,
        parts={("SUPER JACKPOT!", A): "GIGAN JP!", ("SUPER JACKPOT!", B): "MEGA JP!"},
        reading=rd)
    assert n == 2
    buf = _apply(raw, writes)
    texts = set()
    for key in ("g_super_a", "g_super_b"):
        va = _group_target(buf, offs, key)
        if va >= RELOC["base_va"]:
            o = va - RELOC["base_va"] - RELOC["used"]
            texts.add(blob[o:blob.index(b"\x00", o)].decode())
        else:
            texts.add(_cstr(buf, va - VBASE))
    assert texts == {"GIGAN JP!", "MEGA JP!"}


def test_a_copy_without_new_space_is_skipped_and_says_why(prog):
    raw, offs, rd = prog
    msgs, log = _log()
    writes, n, blob = progtext.plan_writes(
        raw, {}, log, no_grow_why="a Direct-SD write can't grow the game program",
        parts={("SUPER JACKPOT!", B): "MEGA JACKPOT!"}, reading=rd)
    assert (writes, n, blob) == ([], 0, b"")
    warn = [m for lvl, m in msgs if lvl == "warning"]
    assert len(warn) == 1
    assert "Battle vs Megalon only" in warn[0] and "Direct-SD" in warn[0]


def test_a_mode_with_no_line_of_the_text_is_reported(prog):
    raw, offs, rd = prog
    msgs, log = _log()
    writes, n, _blob = progtext.plan_writes(
        raw, {}, log, parts={("SUPER JACKPOT!", "cmode_hedorah"): "X"}, reading=rd)
    assert (writes, n) == ([], 0)
    assert any("no line of it that mode alone shows" in m for _l, m in msgs)


def test_placeholders_are_kept_for_a_mode_too(prog):
    raw, offs, rd = prog
    msgs, log = _log()
    _w, n, _b = progtext.plan_writes(raw, {}, log, reloc=RELOC,
                                     parts={("SUPER JACKPOT!", B): "%d JACKPOT!"}, reading=rd)
    assert n == 0
    assert any("%-placeholders" in m for _l, m in msgs)


def test_rows_carry_their_modes_and_a_row_per_mode(prog, monkeypatch):
    raw, offs, rd = prog
    monkeypatch.setattr(text_modes, "read", lambda *a, **k: rd)
    rows = progtext.enumerate_program_strings(raw, modes=True)
    kaiju = [r for r in rows if r["text"] == "KAIJU AWARD"]
    assert [r.get("part") for r in kaiju] == [None, A, B]
    assert kaiju[0]["modes"] == [A, B]
    assert all(r["growable"] and r["budget"] == progtext.MAX_EDIT_LEN for r in kaiju[1:])
    # without modes the rows are what they always were
    assert all("part" not in r and "modes" not in r
               for r in progtext.enumerate_program_strings(raw))


def test_one_mode_and_lines_no_mode_shows_still_split():
    rd = text_modes.Reading()
    r1 = {"kind": "group", "delta": 0, "offs": [1], "va": 1}
    r2 = {"kind": "group", "delta": 0, "offs": [2], "va": 1}
    tail = {"kind": "group", "delta": 3, "offs": [3], "va": 4}
    rd.keys = {10: [(r1, A), (r2, ""), (tail, "")]}
    rd.shown = {10: [A]}
    assert text_modes.text_modes(rd, [10]) == ([A], [A])
    rd.keys = {10: [(r1, A), (tail, "")]}
    assert text_modes.text_modes(rd, [10]) == ([A], [])        # a tail is its own row
    assert not text_modes.whole_span(rd, 10, A)
    rd.keys = {10: [(r1, A)]}
    assert text_modes.whole_span(rd, 10, A)


# ---- the manifest, the Text tab's rules, Transfer ---------------------------------------------
def test_manifest_round_trips_modes_and_a_modes_row(tmp_path):
    rows = [{"path": GAME, "original": "KAIJU AWARD", "replacement": "", "budget": 96,
             "grow": True, "modes": [A, B]},
            {"path": text_manifest.join_part(GAME, B), "original": "KAIJU AWARD",
             "replacement": "SPACEGODZILLA JACKPOT", "budget": 96, "grow": True, "modes": [B]}]
    text_manifest.save(str(tmp_path), rows)
    got = text_manifest.load(str(tmp_path))
    assert got[0]["modes"] == [A, B] and got[0]["path"] == GAME
    assert text_manifest.split_part(got[1]["path"]) == (GAME, B)
    assert got[1]["replacement"] == "SPACEGODZILLA JACKPOT"
    assert text_manifest.changed(str(tmp_path)) == {
        GAME + "#" + B: [("KAIJU AWARD", "SPACEGODZILLA JACKPOT")]}
    assert text_manifest.split_part("/a/scene.radium") == ("/a/scene.radium", "")


def test_text_rules_name_the_mode_and_keep_the_scene_column():
    main = {"path": GAME, "original": "KAIJU AWARD", "replacement": "", "modes": [A, B]}
    own = {"path": GAME + "#" + B, "original": "KAIJU AWARD", "replacement": ""}
    assert R.shown_in(main) == "Battle vs Gigan, Battle vs Megalon"
    assert R.row_part(own) == B and R.shown_in(own) == "Battle vs Megalon"
    assert R.scene_label(own["path"]) == "game program"
    assert "Battle vs Megalon's own text" in R.program_note(own)
    assert "Shown in: Battle vs Gigan, Battle vs Megalon" in R.program_note(main)
    # Replace everywhere leaves a mode's blank row following its line
    plan = R.replace_plan([main, own], "KAIJU", "MONSTER")
    assert [p["row"] for p in plan] == [main]


def _strings(root, rows):
    os.makedirs(root, exist_ok=True)
    text_manifest.save(root, rows)


def test_transfer_keeps_a_modes_text_on_that_modes_row(tmp_path):
    src, tgt = str(tmp_path / "old"), str(tmp_path / "new")
    _strings(src, [
        {"path": GAME, "original": "KAIJU AWARD", "replacement": "", "budget": 96},
        {"path": GAME + "#" + A, "original": "KAIJU AWARD", "replacement": "GIGAN AWARD",
         "budget": 96},
        {"path": GAME + "#" + B, "original": "KAIJU AWARD", "replacement": "SPACE AWARD",
         "budget": 96},
        {"path": GAME + "#cmode_hedorah", "original": "KAIJU AWARD", "replacement": "HEDO",
         "budget": 96}])
    _strings(tgt, [
        {"path": "/godzilla/game", "original": "KAIJU AWARD", "replacement": "", "budget": 96},
        {"path": "/godzilla/game#" + A, "original": "KAIJU AWARD", "replacement": "",
         "budget": 96},
        {"path": "/godzilla/game#" + B, "original": "KAIJU AWARD", "replacement": "",
         "budget": 96}])
    matched, dropped = mod_transfer._plan_text(src, tgt)
    assert sorted((m["part"], m["new"]) for m in matched) == [(A, "GIGAN AWARD"),
                                                               (B, "SPACE AWARD")]
    assert [d["part"] for d in dropped] == ["cmode_hedorah"]
    plan = mod_transfer.plan_transfer(src, tgt)
    mod_transfer.apply_transfer(src, tgt, plan)
    got = {r["path"]: r["replacement"] for r in text_manifest.load(tgt)}
    assert got == {"/godzilla/game": "", "/godzilla/game#" + A: "GIGAN AWARD",
                   "/godzilla/game#" + B: "SPACE AWARD"}


# ---- the engine: refresh and the Write's dispatch ---------------------------------------------
def test_refresh_adds_the_modes_rows_and_keeps_typed_text(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    import json
    from pinball_decryptor.plugins.stern import engine
    raw, offs, rd = (lambda r: (r[0], r[1], _reading(r[0], r[1], {
        "g_kaiju_a": A, "g_kaiju_b": B, "g_super_a": A, "g_super_b": B})))(_build())
    monkeypatch.setattr(text_modes, "read", lambda *a, **k: rd)
    assets = tmp_path / "proj"
    (assets / "text").mkdir(parents=True)
    card = tmp_path / "card.raw"
    card.write_bytes(b"\0" * 4096)
    (assets / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(card), "size": 4096}), encoding="utf-8")
    text_manifest.save(str(assets), [
        {"path": GAME, "original": "KAIJU AWARD", "replacement": "MONSTER AWARD",
         "budget": 96, "grow": True},
        {"path": GAME + "#cmode_gone", "original": "KAIJU AWARD", "replacement": "",
         "budget": 96, "grow": True}])

    class _Reader:
        def read_file_bytes(self, _node):
            return raw
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [(0, 4096)])
    monkeypatch.setattr(engine, "_locate", lambda f, parts: (_Reader(), object(), None))
    rows = text_manifest.load(str(assets))
    assert engine.program_text_needs_refresh(str(assets), rows)
    assert engine.refresh_program_text_flags(str(assets))
    got = text_manifest.load(str(assets))
    assert [(r["path"], r["replacement"], r.get("modes")) for r in got] == [
        (GAME, "MONSTER AWARD", [A, B]), (GAME + "#" + A, "", [A]), (GAME + "#" + B, "", [B])]
    assert not engine.program_text_needs_refresh(str(assets), got)
    # PAD-485: the screens each mode names are kept beside the rows; a project read before
    # they were is read once more
    assert engine.program_mode_scenes(str(assets)) == {}
    sidecar = assets / "text" / "program_modes.json"
    sidecar.write_text(json.dumps({"rev": text_modes.READ_REV}), encoding="utf-8")
    assert engine.program_text_needs_refresh(str(assets), got)
    engine._program_modes_read(str(assets), {A: ["a1/b1"], B: ["a2/b2", "a2/b3"]})
    assert engine.program_mode_scenes(str(assets)) == {A: ["a1/b1"], B: ["a2/b2", "a2/b3"]}
    assert not engine.program_text_needs_refresh(str(assets), got)


def test_write_hands_a_modes_text_to_the_game_program(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern import engine
    text_manifest.save(str(tmp_path), [
        {"path": GAME, "original": "KAIJU AWARD", "replacement": "", "budget": 96},
        {"path": GAME + "#" + B, "original": "KAIJU AWARD", "replacement": "SPACE AWARD",
         "budget": 96}])
    seen = {}

    def fake(reader, node, card_path, pairs, patched_fw, log, grow=None, shader=None,
             clips=None, parts=None):
        seen.update(path=card_path, pairs=list(pairs), parts=parts, grow=dict(grow or {}))
        return [], 1, {}, None

    class _Reader:
        def is_arm_elf(self, _node):
            return True
    monkeypatch.setattr(engine, "_program_text_writes", fake)
    monkeypatch.setattr(engine, "_resolve_card_nodes", lambda r, paths, c: {p: {} for p in paths})
    monkeypatch.setattr(engine, "_text_grow_gate", lambda dev: (False, "no WSL here"))
    engine._radium_text_writes(_Reader(), str(tmp_path), lambda *a, **k: None, lambda: False,
                               grow_dir=str(tmp_path))
    assert seen["path"] == GAME and seen["pairs"] == []
    assert seen["parts"] == {("KAIJU AWARD", B): "SPACE AWARD"}
    # a mode's own copy asks the growth gate even at the same length
    assert seen["grow"]["ok"] is False and seen["grow"]["why"] == "no WSL here"


# ---- the real game programs (David's machine) ------------------------------------------------
def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    pytest.importorskip("numpy")
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def _line_text(raw, rd, line, buf=None, blob=b"", base=0):
    from pinball_decryptor.plugins.stern import stock_scan as S
    prog = S.Program(raw)
    buf = buf or raw
    e = struct.unpack_from("<I", buf, prog.va2off(rd.table_va + 4 * line))[0]
    out = set()
    for k in range(5):
        p = struct.unpack_from("<I", buf, prog.va2off(e) + 4 * k)[0]
        if blob and base <= p < base + len(blob):
            out.add(blob[p - base:blob.index(b"\x00", p - base)].decode())
        else:
            o = prog.va2off(p)
            out.add(bytes(buf[o:buf.index(b"\x00", o)]).decode())
    return out


@pytest.mark.parametrize("card", [PRO116, LE116], ids=["pro116", "le116"])
def test_godzilla_116_award_and_jackpot_lines_are_one_battle_each(card):
    """The report said MEGALON AWARD and GIGAN AWARD show in three battles. On stock 1.16 each
    award is its battle's own line and the Megalon and Gigan multiball has two jackpot lines
    of its own; one string two modes share is SUPER JACKPOT: %,02llu."""
    raw = _program(card)
    rd = text_modes.read(raw)
    assert rd.count == 3949
    lines = {3320: "GIGAN AWARD", 3338: "MEGALON AWARD", 3371: "MEGALON JACKPOT!",
             3372: "GIGAN JACKPOT!"}
    for line, text in lines.items():
        assert _line_text(raw, rd, line) == {text}
    assert rd.line_modes[3320] == {A}
    assert rd.line_modes[3338] == {B}
    assert rd.line_modes[3371] == rd.line_modes[3372] == {"cmode_battle_vs_megalon_and_gigan_mb"}
    rows = {(r["text"], r.get("part")): r
            for r in progtext.enumerate_program_strings(raw, modes=True)}
    assert rows[("GIGAN AWARD", None)]["modes"] == [A]
    assert ("GIGAN AWARD", A) not in rows                     # one mode: no row of its own
    assert ("SUPER JACKPOT: %,02llu", "cmode_mechagodzilla_multiball") in rows


def test_heisei_kaiju_award_gives_each_battle_its_own_text():
    """DoomWalrus666's card: the Gigan and Megalon battles' awards both read KAIJU AWARD, one
    Text tab row until now. Each battle gets its own, read back through the game's table."""
    raw = _program(HEISEI15)
    rd = text_modes.read(raw)
    assert _line_text(raw, rd, 3320) == _line_text(raw, rd, 3338) == {"KAIJU AWARD"}
    rows = {(r["text"], r.get("part")) for r in progtext.enumerate_program_strings(raw, modes=True)}
    assert ("KAIJU AWARD", A) in rows and ("KAIJU AWARD", B) in rows
    from pinball_decryptor.plugins.stern import engine
    reloc = engine._text_reloc_plan(raw)[0]
    _msgs, log = _log()
    writes, n, blob = progtext.plan_writes(
        raw, {}, log, reloc=reloc, reading=rd,
        parts={("KAIJU AWARD", A): "GIGAN AWARD", ("KAIJU AWARD", B): "SPACEGODZILLA JACKPOT"})
    assert n == 2
    buf = _apply(raw, writes)
    base = reloc["base_va"] + reloc["used"]
    assert _line_text(raw, rd, 3320, buf, blob, base) == {"GIGAN AWARD"}
    assert _line_text(raw, rd, 3338, buf, blob, base) == {"SPACEGODZILLA JACKPOT"}
    assert _line_text(raw, rd, 3371, buf, blob, base) == {"KAIJU JACKPOT!"}


# ---- the Text tab ----------------------------------------------------------------------------
def test_text_tab_shows_the_modes_and_keeps_a_modes_row_to_itself(tmp_path, monkeypatch):
    """Shown in on every program row that names a mode, a mode's own row marked as one, and
    Apply to every scene never fills a mode's row (it follows the line's main row blank)."""
    from tests.test_webui_text import _open, _row_index
    from tests.webui_harness import web_app
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setattr(engine, "program_text_needs_refresh", lambda *a: False)
    folder = str(tmp_path / "proj")
    os.makedirs(folder)
    text_manifest.save(folder, [
        {"path": "/g/aaaa/scene.radium", "original": "KAIJU AWARD", "replacement": ""},
        {"path": GAME, "original": "KAIJU AWARD", "replacement": "", "budget": 96,
         "grow": True, "modes": [A, B]},
        {"path": GAME + "#" + A, "original": "KAIJU AWARD", "replacement": "", "budget": 96,
         "grow": True, "modes": [A]},
        {"path": GAME + "#" + B, "original": "KAIJU AWARD", "replacement": "", "budget": 96,
         "grow": True, "modes": [B]}])
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        rows = w.state("text")["rows"]
        main, own_b = _row_index(w, "KAIJU AWARD", "/game"), _row_index(w, "KAIJU AWARD", "#" + B)
        assert rows[main]["in"] == "Battle vs Gigan, Battle vs Megalon" and rows[main]["pa"]
        assert rows[own_b]["in"] == "Battle vs Megalon" and rows[own_b]["pt"]
        assert rows[own_b]["sc"] == "game program"
        w.call("ui.set", "text", "apply_all", True)
        w.call("text.select", main)
        assert w.call("text.apply", "MONSTER AWARD") is True
        w.call("text.select", own_b)
        assert "Battle vs Megalon's own text" in w.state("text")["scene_note"]
        assert w.call("text.apply", "SPACE AWARD") is True
        got = {r["path"]: r["replacement"] for r in text_manifest.load(folder)}
        assert got == {"/g/aaaa/scene.radium": "MONSTER AWARD", GAME: "MONSTER AWARD",
                       GAME + "#" + A: "", GAME + "#" + B: "SPACE AWARD"}


@pytest.mark.parametrize("card", [LE116, HEISEI15], ids=["le116", "heisei15"])
def test_each_battle_names_its_award_screen(card):
    """PAD-485 (DragonRR): the Heisei card's KAIJU AWARD is the battles' award line, and no
    screen's own words read like it. Each battle's code names its own award screen (an
    Award_Textbox whose words are the battle's name), which is where the line goes."""
    raw = _program(card)
    ctx = {}
    progtext.enumerate_program_strings(raw, modes=True, ctx=ctx)
    gigan = "a248977badd032e625ee2480e8cc6d0b2f645d1f/976560ae6c29b77b3a3e96f18f00dc18d1ce7e72"
    megalon = "acbfac6e7d7f808fcbc9e3e046025e4fa4950b53/3b3de067c19c3687cca71b04ca1c5c7c55cb3bdc"
    jackpots = "c65ecc5e2f5769bdc59851eb951a1c781b53deb8/619bb5b14df0d97316909daa38e67876793c1470"
    assert gigan in ctx["scenes"][A] and gigan not in ctx["scenes"][B]
    assert megalon in ctx["scenes"][B] and megalon not in ctx["scenes"][A]
    assert jackpots in ctx["scenes"]["cmode_battle_vs_megalon_and_gigan_mb"]
    # each of them three screens, in one folder of the card
    assert [k.split("/")[0] for k in ctx["scenes"][A]] == [gigan.split("/")[0]] * 3
