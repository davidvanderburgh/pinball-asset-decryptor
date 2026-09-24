"""The game's own modes, edited from the app (item 145): the table, the words, the staging,
the Write.

A stock mode's timer or award is changed by rewriting the ONE instruction (or literal word)
the game loads it from, in the game ELF, with the ELF's ``.sidx`` record refreshed over the
file that ships. Item 144 writes where those words are in a table; these tests pin the app's
side on a synthetic ELF: the grammar is read as MODE_SDK.md sets it out, a value is encoded
the way its instruction can hold it (or refused with the reason), a build whose words differ
is refused, staging rides ``.staged_changes.json`` beside Defaults' settings without
disturbing anything else, the Write's overlay is folded into the validator bypass's digest,
and a row put back to stock writes the stock words back byte for byte.
"""

import hashlib
import json
import os
import struct

import pytest

# The mode maker ships dark behind a preview switch (core/preview.py); these tests are
# about what it does when it is ON (tests/test_preview_switch.py covers it OFF).
pytestmark = pytest.mark.usefixtures("preview_modes_on")

from pinball_decryptor.plugins.stern import stock_modes as S
from tests.test_stern_valpatch import (TEXT_OFF, TEXT_VADDR, VALIDATOR_STRINGS,
                                       _build_elf, _stub_sidx, _StubReader)
from pinball_decryptor.plugins.stern import valpatch

AWARD_VA, AWARD_VA2 = TEXT_VADDR + 0x140, TEXT_VADDR + 0x14C   # movw r2 / movt r2
TIMER_VA = TEXT_VADDR + 0x158                                  # mov r1, #30
LIT_VA = TEXT_VADDR + 0x160                                    # a literal word
MOVW_R2_D090, MOVT_R2_3 = 0xE30D2090, 0xE3402003               # 250,000 (tesla's words)
MOV_R1_30 = 0xE3A0101E


def _with_phdr(elf):
    """The valpatch test ELF plus a PT_LOAD over its .text (appended; the section headers
    the bypass reads are untouched)."""
    b = bytearray(elf)
    ph_off = len(b)
    text_len = 128 * 4
    b += struct.pack("<8I", 1, TEXT_OFF, TEXT_VADDR, TEXT_VADDR, text_len, text_len, 5, 0x1000)
    struct.pack_into("<I", b, 0x1C, ph_off)
    struct.pack_into("<HH", b, 0x2A, 32, 1)
    return b


def _put(b, va, w):
    struct.pack_into("<I", b, TEXT_OFF + (va - TEXT_VADDR), w)


def synthetic_elf(validator=True):
    b = _with_phdr(_build_elf(inline_crc_loops=5 if validator else 0,
                              trailer=VALIDATOR_STRINGS if validator else b""))
    _put(b, AWARD_VA, MOVW_R2_D090)
    _put(b, AWARD_VA2, MOVT_R2_3)
    _put(b, TIMER_VA, MOV_R1_30)
    _put(b, LIT_VA, 5000)
    return bytes(b)


def table_text(elf, game="synth_pro", version="1.15"):
    return """
# a synthetic title
build %s %s sha1 %s
mode 23 cmode_tesla_strike obj 0x7a2878 vtable 0x6307b8 title_msg 3242
start 23 start: a shot handler
number 23 start.caward_add 250000 movwt 0x%x 0x%x e30d2090,e3402003 word seen runA  # v[8] call
number 23 start.caward_add@2 5000 lit 0x%x 00001388 word shared 2
number 23 start.award_value ? code 0x10c1a4 - code   # 2,000,000 x level, folded into shifts
number 23 timer.ctimer_set 30 imm 0x%x e3a0101e word
number 23 shot.scene ? scene 0x11000 - scene
number 23 shot.odd 7 wibble 0x11000 0x11004 00000007 word
mode 12 cmode_battle_vs_ebirah obj 0x7a1fe0 vtable 0x6266c8 title_msg ?
number 12 timer.seconds 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # v[56]; range 30..70
number 12 timer.v57 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # range 30..70
callout 23 1234 start.callout imm 0x11000 e3a00001
""" % (game, version, hashlib.sha1(elf).hexdigest(), AWARD_VA, AWARD_VA2, LIT_VA, TIMER_VA)


@pytest.fixture
def elf():
    return synthetic_elf()


@pytest.fixture
def build(elf):
    return S.parse(table_text(elf))[0]


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / ".extract_source.json").write_text(json.dumps({
        "input_path": "D:\\x\\synth_pro-1_15_0_spike2.Release.8G.sdcard.raw",
        "input_name": "synth_pro-1_15_0_spike2.Release.8G.sdcard.raw",
        "size": 1, "mtime": 1}), encoding="utf-8")
    return str(p)


# ---- the table ---------------------------------------------------------------------------
def test_the_grammar_reads_modes_numbers_and_keys_with_a_repeat_mark(build):
    assert build.id == "synth_pro 1.15" and len(build.numbers) == 8
    assert build.modes[23].name == "Tesla Strike"
    assert build.modes[12].name == "Battle vs Ebirah" and build.modes[12].title_msg is None
    n = build.number("23.start.caward_add")
    assert n.kind == "movwt" and n.vas == (AWARD_VA, AWARD_VA2) and n.words == (MOVW_R2_D090, MOVT_R2_3)
    assert n.value == 250000 and n.seen == "runA" and n.editable and n.label == "Start award"
    lit = build.number("23.start.caward_add@2")        # a repeat in one mode
    assert lit.kind == "lit" and lit.shared == 2 and lit.label == "Start award (2)"
    adj = build.number("12.timer.seconds")
    assert adj.adj_name == "AD_BATTLE_VS_EBIRAH_TIMER" and adj.adj_range == (30, 70)
    assert adj.is_adjustment and build.row_label(adj) == "Timer"
    assert list(build.adjustment_numbers()) == ["AD_BATTLE_VS_EBIRAH_TIMER"]


def test_code_scene_and_unknown_kinds_stay_read_only_with_the_reason(build):
    code = build.number("23.start.award_value")
    assert not code.editable and "hook or a code cave" in code.why_read_only()
    assert code.value is None and code.is_player_facing
    scene = build.number("23.shot.scene")
    assert not scene.editable and "scene file" in scene.why_read_only()
    odd = build.number("23.shot.odd")                 # a kind a later format may add
    assert odd.kind == "wibble" and not odd.editable and "wibble" in odd.why_read_only()
    with pytest.raises(S.StockModeError, match="can't be changed here"):
        S.check_value(code, 5)


def test_a_repeat_marked_with_hash_in_the_first_draft_is_still_part_of_the_key():
    b = S.parse("build g 1.0 sha1 00\nmode 5 cmode_x obj 0 vtable 0 title_msg ?\n"
                "number 5 shot.caward_add#3 50000 movw 0x87e58 e30c2350 word  # a comment\n"
                "number 5 timer.seconds 20 imm 0xb75c0 e3a00014 word  # v[56] returns it\n")[0]
    n = b.number("5.shot.caward_add#3")
    assert n.label == "Shot award (3)" and n.comment == "a comment" and n.value == 50000
    assert b.number("5.timer.seconds").label == "Timer (seconds)"


def test_a_line_that_cant_be_read_names_its_line():
    with pytest.raises(S.StockModeError, match="line 3"):
        S.parse("build g 1.0 sha1 00\n\nnumber 1 k 5 movwt 0x10 e3000000 word\n")
    with pytest.raises(S.StockModeError, match="before any build"):
        S.parse("mode 1 cmode_x obj 0 vtable 0 title_msg ?\n")


def test_versions_match_without_their_trailing_zero(build):
    assert build.same_title("synth_pro", "1.15.0") and not build.same_title("synth_pro", "1.16.0")
    assert S.version_key("1.15.0") == S.version_key("1.15") == (1, 15)


# ---- the words ----------------------------------------------------------------------------
def test_encode_and_decode_each_kind():
    assert S.decode("movwt", S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), 777777)) == 777777
    assert S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), 250000) == (MOVW_R2_D090, MOVT_R2_3)
    assert S.decode("movw", S.encode("movw", (0xE30C2350,), 65535)) == 65535
    assert S.decode("imm", (MOV_R1_30,)) == 30
    assert S.encode("imm", (MOV_R1_30,), 30) == (MOV_R1_30,)
    assert S.decode("imm", S.encode("imm", (MOV_R1_30,), 0x3F000)) == 0x3F000
    mvn = 0xE3E01000                                   # mvn r1, #0 = 0xffffffff
    assert S.decode("imm", S.encode("imm", (mvn,), 0xFFFFFF00)) == 0xFFFFFF00
    assert S.decode("lit", S.encode("lit", (5000,), 123456789)) == 123456789
    # the same register is kept, and so is the condition
    lo, hi = S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), 0xDEADBEEF)
    assert (lo >> 12) & 0xF == 2 == (hi >> 12) & 0xF and lo >> 28 == 0xE


def test_a_value_the_instruction_cant_hold_is_refused_with_the_nearest_that_fits():
    with pytest.raises(S.StockModeError, match="nearest that fits is 256, 260"):
        S.encode("imm", (MOV_R1_30,), 257)
    with pytest.raises(S.StockModeError, match="at most 65,535"):
        S.encode("movw", (0xE30C2350,), 70000)
    with pytest.raises(S.StockModeError, match="negative"):
        S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), -1)
    with pytest.raises(S.StockModeError, match="too big"):
        S.encode("lit", (0,), 1 << 32)


def test_a_build_is_matched_by_its_bytes_or_by_its_instructions(build, elf):
    img = S.ElfImage(elf)
    assert S.identify(img, [build]) == (build, "sha1", "")
    # a card this app wrote before: same instructions, another value -> still this build
    ours = bytearray(elf)
    lo, hi = S.encode("movwt", build.number("23.start.caward_add").words, 777777)
    _put(ours, AWARD_VA, lo)
    _put(ours, AWARD_VA2, hi)
    _put(ours, LIT_VA, 1)
    b2, how, _why = S.identify(S.ElfImage(bytes(ours)), [build], "synth_pro", "1.15")
    assert b2 is build and how == "words"
    assert S.site_state(S.ElfImage(bytes(ours)), build.number("23.start.caward_add"))[0] == "ours"
    # another program: the instruction at the award's VA is something else -> refused
    other = bytearray(elf)
    _put(other, AWARD_VA, 0xE1A00000)
    b3, how, why = S.identify(S.ElfImage(bytes(other)), [build], "synth_pro", "1.15")
    assert b3 is None and "isn't synth_pro 1.15" in why and "e1a00000" in why


def test_the_elf_maps_a_va_only_inside_its_file_backed_load(elf):
    img = S.ElfImage(elf)
    assert img.va_to_off(AWARD_VA) == TEXT_OFF + 0x140
    assert img.va_to_off(TEXT_VADDR + 128 * 4) is None
    with pytest.raises(S.StockModeError):
        S.ElfImage(b"\x7fELF\x02\x01" + b"\0" * 64)


# ---- staging -----------------------------------------------------------------------------
def test_staging_a_word_and_an_adjustment_like_defaults(project, build, monkeypatch):
    from pinball_decryptor.core import staged_changes
    staged_changes.save(project, {"audio": {"sound/idx0001.wav": "C:/x.wav"},
                                  "settings": {"AD_BALLS_PER_GAME": 5}, "high_scores": {"a": 1}})
    monkeypatch.setattr(S, "_TABLES", [build])
    assert S.project_build(project) == ("synth_pro", "1.15.0")
    assert S.table_for_project(project) is build

    assert S.stage(project, build, build.number("23.start.caward_add"), "777,777") == 777777
    assert S.stage(project, build, build.number("12.timer.seconds"), 30) == 30
    data = staged_changes.load(project)
    assert data["stock_modes"] == {"build": "synth_pro 1.15",
                                   "values": {"23.start.caward_add": 777777},
                                   "touched": ["12.timer.seconds", "23.start.caward_add"]}
    # the adjustment is Defaults' own staged setting: one number for both tabs
    assert data["settings"] == {"AD_BALLS_PER_GAME": 5, "AD_BATTLE_VS_EBIRAH_TIMER": 30}
    assert data["audio"] == {"sound/idx0001.wav": "C:/x.wav"} and data["high_scores"] == {"a": 1}
    rows = {e["number"].row_key: (e["stock"], e["new"]) for e in S.staged_edits(project)}
    assert rows == {"23.start.caward_add": (250000, 777777), "12.timer.seconds": (60, 30)}
    assert S.pending_count(project) == 2 and len(S.pending_adjustments(project)) == 1

    # the stock value un-stages the row; the record stays, with nothing in it
    assert S.stage(project, build, build.number("23.start.caward_add"), 250000) is None
    assert staged_changes.load(project)["stock_modes"] == {
        "build": "synth_pro 1.15", "values": {},
        "touched": ["12.timer.seconds", "23.start.caward_add"]}
    assert S.manages(project)
    # All to stock: the table's adjustments leave settings, other settings stay
    S.stage(project, build, build.number("23.timer.ctimer_set"), 60)
    assert S.unstage_all(project, build) == 2
    data = staged_changes.load(project)
    assert data["settings"] == {"AD_BALLS_PER_GAME": 5}
    assert data["stock_modes"]["values"] == {} and S.pending_count(project) == 0
    assert data["stock_modes"]["touched"] == ["12.timer.seconds", "23.start.caward_add",
                                              "23.timer.ctimer_set"]


def test_staging_refuses_out_of_range_unencodable_and_no_project(project, build, tmp_path):
    with pytest.raises(S.StockModeError, match="between 30 and 70"):
        S.stage(project, build, build.number("12.timer.seconds"), 90)
    with pytest.raises(S.StockModeError, match="doesn't fit"):
        S.stage(project, build, build.number("23.timer.ctimer_set"), 257)
    with pytest.raises(S.StockModeError, match="whole number"):
        S.stage(project, build, build.number("23.start.caward_add"), "lots")
    with pytest.raises(S.StockModeError, match="Extract tab"):
        S.stage(str(tmp_path / "nope"), build, build.number("23.start.caward_add"), 5)
    assert not os.path.exists(os.path.join(project, ".staged_changes.json"))


def test_a_project_without_a_table_has_nothing_pending(tmp_path):
    assert S.project_build(str(tmp_path)) is None
    assert S.staged_edits(str(tmp_path)) == [] and S.pending_count(str(tmp_path)) == 0


# ---- the Write ------------------------------------------------------------------------------
def _stub(elf):
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    return _StubReader(elf, blob), blob


def test_compute_writes_patches_the_words_and_the_bypass_digests_them(project, build, elf):
    from pinball_decryptor.plugins.stern import sidx as _sidx
    import hmac
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    S.stage(project, build, build.number("23.timer.ctimer_set"), 60)
    rdr, blob = _stub(elf)
    msgs = []
    log = lambda m, lvl="info": msgs.append(m)  # noqa: E731
    writes, overlay, n = S.compute_writes(rdr, rdr.fw_node, project, log, builds=[build])
    assert n == 2
    lo, hi = S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), 777777)
    assert overlay == {TEXT_OFF + 0x140: struct.pack("<I", lo), TEXT_OFF + 0x14C: struct.pack("<I", hi),
                       TEXT_OFF + 0x158: struct.pack("<I", S.encode("imm", (MOV_R1_30,), 60)[0])}
    assert dict(writes) == {_StubReader.FW_DISK + o: b for o, b in overlay.items()}
    assert any("start award 250,000 -> 777,777" in m for m in msgs)

    recs, _crc, fmt = _sidx.parse_records(blob)
    if "gz/game" not in recs:
        pytest.skip("stub .sidx doesn't parse on this format revision")
    vwrites, status = valpatch.compute_writes(rdr, log, fw_overlay=overlay)
    assert status[0] == "bypassed"
    shipped = bytearray(elf)
    for o, b in overlay.items():
        shipped[o:o + len(b)] = b
    eoff = valpatch.find_validation_exec(elf)
    shipped[eoff:eoff + 4] = valpatch._BX_LR
    want_h = hmac.new(_sidx.SIDX_KEY, bytes(shipped), hashlib.sha1).digest()
    by_disk = dict(vwrites)
    for foff, b in _sidx.record_field_writes(recs["gz/game"], want_h,
                                             hashlib.md5(bytes(shipped)).digest(), fmt):
        assert by_disk[_StubReader.SIDX_DISK + foff] == b


def test_revert_writes_the_stock_words_back_over_ours(project, build, elf):
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    rdr, _blob = _stub(elf)
    _w, overlay, _n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build])
    written = bytearray(elf)
    for o, b in overlay.items():
        written[o:o + len(b)] = b
    # the card we built is the next Write's input; the row goes back to stock
    S.unstage(project, build, build.number("23.start.caward_add"))
    msgs = []
    rdr2, _ = _stub(bytes(written))
    _w, overlay2, n2 = S.compute_writes(rdr2, rdr2.fw_node, project,
                                        lambda m, lvl="info": msgs.append(m), builds=[build])
    assert n2 == 1
    for o, b in overlay2.items():
        written[o:o + len(b)] = b
    assert bytes(written) == elf                                  # byte for byte
    assert any("back to stock" in m for m in msgs)


def test_a_wrong_build_is_refused_with_a_log_line_and_writes_nothing(project, build, elf):
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    other = bytearray(elf)
    _put(other, AWARD_VA2, 0xE1A00000)                  # the movt is something else here
    rdr, _ = _stub(bytes(other))
    msgs = []
    writes, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                          lambda m, lvl="info": msgs.append((m, lvl)), builds=[build])
    assert (writes, overlay, n) == ([], {}, 0)
    assert any("NOT written" in m and lvl == "warning" for m, lvl in msgs)


def test_a_value_staged_for_another_build_is_not_written(project, build, elf):
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    other_build = S.parse(table_text(elf, game="synth_le", version="1.16"))[0]
    rdr, _ = _stub(elf)
    msgs = []
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                      lambda m, lvl="info": msgs.append(m), builds=[other_build])
    assert overlay == {} and n == 0
    assert any("staged for synth_pro 1.15" in m for m in msgs)


def test_a_staged_firmware_file_takes_the_edits_instead(project, build, elf, tmp_path):
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    staged = tmp_path / "game_real_pathA"
    staged.write_bytes(elf + b"\0" * 64)               # longer, like the cave's
    rdr, _ = _stub(elf)
    writes, overlay, n = S.compute_writes(rdr, rdr.fw_node, project, None, patched_fw=str(staged),
                                          builds=[build])
    assert (writes, overlay, n) == ([], {}, 1)
    got = staged.read_bytes()
    lo, hi = S.encode("movwt", (MOVW_R2_D090, MOVT_R2_3), 777777)
    assert struct.unpack_from("<2I", got, TEXT_OFF + 0x140)[0] == lo
    assert struct.unpack_from("<I", got, TEXT_OFF + 0x14C)[0] == hi


def test_a_project_that_never_staged_a_stock_mode_is_never_touched(project, build, elf):
    rdr, _ = _stub(elf)
    assert S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build]) == ([], {}, 0)


MASK_VA, MASK_VA2 = TEXT_VADDR + 0x168, TEXT_VADDR + 0x16C     # mov r0,#0x800 / movt r0,#0x70
ODD_ZERO_VA = TEXT_VADDR + 0x170                                # mov r1,#0 written the long way
LIAR_VA = TEXT_VADDR + 0x174                                    # mov r1,#30, the table says 999
MOV_R0_800, MOVT_R0_70 = 0xE3A00B02, 0xE3400070
MOV_R1_0_ROT1 = 0xE3A01100


def _elf_with_144_round2_shapes(elf):
    b = bytearray(elf)
    _put(b, MASK_VA, MOV_R0_800)
    _put(b, MASK_VA2, MOVT_R0_70)
    _put(b, ODD_ZERO_VA, MOV_R1_0_ROT1)
    _put(b, LIAR_VA, MOV_R1_30)
    return bytes(b)


def _table_with_144_round2_shapes(elf, base):
    return table_text(elf) + (
        "number 23 initial_mask.lo 7342080 movwt 0x%x 0x%x e3a00b02,e3400070 word  # the low word is a mov\n"
        "number 23 initial_mask.odd 0 imm 0x%x e3a01100 word\n"
        "number 23 shot.caward_add 999 imm 0x%x e3a0101e word  # a row whose words say 30\n"
        % (MASK_VA, MASK_VA2, ODD_ZERO_VA, LIAR_VA))


def test_a_movwt_pair_whose_low_word_is_a_mov_reads_and_writes_in_its_own_shape():
    # item 144 publishes these ("the low word is a mov"): mov r0,#0x800 ; movt r0,#0x70
    words = (MOV_R0_800, MOVT_R0_70)
    assert S.decode("movwt", words) == 0x700800
    assert S.encode("movwt", words, 0x700800) == words
    lo, hi = S.encode("movwt", words, 0x1230400)
    assert S._is_mov(lo) and S.decode("movwt", (lo, hi)) == 0x1230400     # still a mov, same register
    assert S.skeleton("movwt", (lo, hi)) == S.skeleton("movwt", words)
    with pytest.raises(S.StockModeError, match="low half, 4,097"):
        S.encode("movwt", words, 0x701001)
    # a movw would have been rewritten into a different instruction by the movw encoder
    assert S.encode("movwt", words, 0x700800)[0] != S._with_imm16(MOV_R0_800, 0x800)


def test_a_stock_site_nobody_staged_is_never_rewritten(project, elf):
    elf2 = _elf_with_144_round2_shapes(elf)
    build = S.parse(_table_with_144_round2_shapes(elf2, None))[0]
    # the long-way zero re-encodes to a different word; staging something else must not touch it
    assert S.encode("imm", (MOV_R1_0_ROT1,), 0) != (MOV_R1_0_ROT1,)
    S.stage(project, build, build.number("23.timer.ctimer_set"), 60)
    rdr, _ = _stub(elf2)
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build])
    assert n == 1 and set(overlay) == {TEXT_OFF + 0x158}


def test_a_row_whose_words_dont_hold_its_value_is_read_only_and_never_written(project, elf):
    from pinball_decryptor.core import staged_changes
    elf2 = _elf_with_144_round2_shapes(elf)
    build = S.parse(_table_with_144_round2_shapes(elf2, None))[0]
    liar = build.number("23.shot.caward_add")
    assert liar.is_word and not liar.words_agree and not liar.editable
    assert "don't hold 999" in liar.why_read_only()
    with pytest.raises(S.StockModeError, match="can't be changed here"):
        S.stage(project, build, liar, 500)
    # a hand-edited staging file still can't make the Write guess at the instruction
    staged_changes.save(project, {"stock_modes": {"build": build.id,
                                                  "values": {"23.shot.caward_add": 60}}})
    rdr, _ = _stub(elf2)
    msgs = []
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                      lambda m, lvl="info": msgs.append(m), builds=[build])
    assert (overlay, n) == ({}, 0) and any("don't hold 999" in m for m in msgs)


def test_the_constructor_timer_row_reads_as_a_start_value():
    b = S.parse("build g 1.0 sha1 00\nmode 22 cmode_planet_x_hurry_up obj 0 vtable 0 title_msg ?\n"
                "number 22 timer.seconds.ctor 20 imm 0xf9aa0 e3a02014 word  # the constructor\n")[0]
    n = b.number("22.timer.seconds.ctor")
    assert n.label == "Timer (start value)" and n.is_player_facing and n.editable


def test_the_engine_nothing_to_write_guard_counts_staged_stock_modes(project, build, monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setattr(S, "_TABLES", [build])
    assert engine._stock_mode_pending(project) == 0
    S.stage(project, build, build.number("12.timer.seconds"), 30)
    assert engine._stock_mode_pending(project) == 1


# ---- a word two rows share; putting the only change back (fix round 1) -------------------
def _shared_table(elf, first):
    """table_text plus a mode-12 row on Tesla's award words (``shared 2``), either ahead of
    every other row (*first*) or after them: the Write must not depend on the order."""
    extra = ("number 12 shot.caward_add 250000 movwt 0x%x 0x%x e30d2090,e3402003 word shared 2\n"
             % (AWARD_VA, AWARD_VA2))
    text = table_text(elf)
    if first:
        head, _sep, tail = text.partition("mode 23 ")
        return head + extra + "mode 23 " + tail
    return text + extra


def _apply(data, overlay):
    b = bytearray(data)
    for o, w in overlay.items():
        b[o:o + len(w)] = w
    return bytes(b)


@pytest.mark.parametrize("first", [True, False])
def test_a_shared_word_keeps_the_staged_value_on_a_second_write(project, elf, first):
    build = S.parse(_shared_table(elf, first))[0]
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    rdr, _ = _stub(elf)
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build])
    assert n == 1
    built = _apply(elf, overlay)
    # the card we built holds 777,777 at the shared words; the next Write keeps it (the
    # unstaged mode-12 row used to put the stock words back over it)
    rdr2, _ = _stub(built)
    msgs = []
    _w, overlay2, n2 = S.compute_writes(rdr2, rdr2.fw_node, project,
                                        lambda m, lvl="info": msgs.append(m), builds=[build])
    assert (overlay2, n2) == ({}, 0), msgs
    assert S.restore_count(rdr2, rdr2.fw_node, project, builds=[build]) == 0
    # and putting it back to stock still restores the stock words, once
    S.unstage(project, build, build.number("23.start.caward_add"))
    _w, overlay3, n3 = S.compute_writes(rdr2, rdr2.fw_node, project, None, builds=[build])
    assert n3 == 1 and _apply(built, overlay3) == elf


def test_two_staged_values_on_one_shared_word_keep_the_first_and_say_so(project, elf):
    build = S.parse(_shared_table(elf, False))[0]
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    S.stage(project, build, build.number("12.shot.caward_add"), 500000)
    rdr, _ = _stub(elf)
    msgs = []
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                      lambda m, lvl="info": msgs.append(m), builds=[build])
    out = _apply(elf, overlay)
    words = (struct.unpack_from("<I", out, TEXT_OFF + 0x140)[0],
             struct.unpack_from("<I", out, TEXT_OFF + 0x14C)[0])
    assert n == 1 and S.decode("movwt", words) == 777777
    assert any("same word(s)" in m and "the first is kept" in m for m in msgs)


def test_restore_count_sees_our_words_on_the_card_a_write_is_built_from(project, build, elf):
    assert S.restore_count(_stub(elf)[0], _stub(elf)[0].fw_node, project, builds=[build]) == 0
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    rdr, _ = _stub(elf)
    _w, overlay, _n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build])
    built = _apply(elf, overlay)
    S.unstage(project, build, build.number("23.start.caward_add"))
    assert S.pending_count(project) == 0 and S.manages(project)
    rdr2, _ = _stub(built)
    assert S.restore_count(rdr2, rdr2.fw_node, project, builds=[build]) == 1
    assert S.restore_count(_stub(elf)[0], _stub(elf)[0].fw_node, project, builds=[build]) == 0


def test_the_guard_counts_our_words_on_the_input_card_with_nothing_staged(project, build, elf,
                                                                            monkeypatch):
    """Nothing staged, the card being built from holds our words: the real _compute_patches
    doesn't refuse, and its writes put the stock words back."""
    import io
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setattr(S, "_TABLES", [build])
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    rdr, _ = _stub(elf)
    _w, overlay, _n = S.compute_writes(rdr, rdr.fw_node, project, None)
    built = _apply(elf, overlay)
    S.unstage(project, build, build.number("23.start.caward_add"))

    stub = {"rdr": _stub(elf)[0]}
    monkeypatch.setattr(engine, "_locate", lambda disk_f, parts: (
        stub["rdr"], stub["rdr"].fw_node, None))
    # the stock card: nothing to put back, so the usual refusal (still a FileNotFoundError)
    with pytest.raises(engine._NothingToWrite):
        engine._compute_patches(io.BytesIO(b""), [], project, log=lambda *a, **k: None,
                                progress=None, cancel=lambda: False)
    assert issubclass(engine._NothingToWrite, FileNotFoundError)
    # a card holding our words: written, and the words that land are the stock ones
    stub["rdr"] = _stub(built)[0]
    msgs = []
    writes, counts, _g, _a, _v = engine._compute_patches(
        io.BytesIO(b""), [], project, log=lambda m, lvl="info", *a, **k: msgs.append(m),
        progress=None, cancel=lambda: False)
    got = dict(writes)
    base = _StubReader.FW_DISK
    assert got[base + TEXT_OFF + 0x140] == struct.pack("<I", MOVW_R2_D090)
    assert got[base + TEXT_OFF + 0x14C] == struct.pack("<I", MOVT_R2_3)
    assert any("back to stock" in m for m in msgs)
    # the completion dialog hears about it (the four counts alone said "no changes")
    assert counts == (0, 0, 0, 0) and counts.stock_modes == 1 and not counts.restored


# The Write that puts this project's build back when nothing is staged any more: the build
# record machinery of test_stern_build_update, with the patch computation refusing the way
# the real guard does.
from tests.test_stern_build_update import (IMAGE, V1, CARD_TREE, _build,  # noqa: E402
                                           _disk, _first_build, _record, card)  # noqa: F401


def _refuse_like_the_guard(monkeypatch, exc=None):
    from pinball_decryptor.plugins.stern import engine

    def refuse(*_a, **_k):
        raise exc or engine._NothingToWrite("Nothing to write: (test)")
    monkeypatch.setattr(engine, "_compute_patches", refuse)


def _manage(card):
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(card.project), {"stock_modes": {"build": "synth_pro 1.15",
                                                            "values": {}}})


def test_putting_the_only_change_back_updates_the_build_back_to_stock(card, monkeypatch):
    import shutil
    _first_build(card)
    _manage(card)
    _refuse_like_the_guard(monkeypatch)
    card.state["copies"].clear()
    monkeypatch.setattr(shutil, "copyfile", lambda *a, **k: pytest.fail("the card was copied"))
    counts, lines = _build(card)
    assert counts[0] == (0, 0, 0, 0)
    stock = card.stock.read_bytes()
    o17 = _disk(card.reader, IMAGE, 17)
    assert card.out.read_bytes()[o17:o17 + 8] == stock[o17:o17 + 8]      # taken back
    assert card.state["copies"] == [(card.out.name, 0, [
        (V1, CARD_TREE["turtles_pro"]["assets"]["lcd"]["1.asset"])])]      # stock video back
    rec = _record(card)
    assert rec["inplace"] == {} and rec["whole"] == {} and rec["complete"] is True
    assert any("puts the card back to the original" in m for m, _l in lines)


def test_a_whole_build_with_nothing_staged_keeps_a_stock_card_at_the_output(card, monkeypatch):
    import os as _os
    _first_build(card)
    _manage(card)
    st = card.out.stat()
    _os.utime(card.out, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))     # "changed since"
    _refuse_like_the_guard(monkeypatch)
    counts, lines = _build(card)
    assert any("Building from the original" in m for m, _l in lines)
    assert counts[0] == (0, 0, 0, 0) and counts[0].restored
    assert card.out.read_bytes() == card.stock.read_bytes()   # never deleted: the original
    assert _record(card)["complete"] is True


def test_nothing_staged_without_the_games_own_modes_still_refuses(card, monkeypatch):
    _first_build(card)
    before = card.out.read_bytes()
    _refuse_like_the_guard(monkeypatch)
    with pytest.raises(FileNotFoundError, match="Nothing to write"):
        _build(card)
    assert card.out.read_bytes() == before                    # an update never started


def test_a_really_missing_file_is_never_taken_for_nothing_to_write(card, monkeypatch):
    _first_build(card)
    _manage(card)
    _refuse_like_the_guard(monkeypatch, FileNotFoundError("image.bin is gone"))
    with pytest.raises(FileNotFoundError, match="image.bin is gone"):
        _build(card)


def test_another_projects_build_at_the_output_is_not_put_back(card, monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine
    _first_build(card)
    _manage(card)
    other = tmp_path / "other_project"
    other.mkdir()
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(other), {"stock_modes": {"build": "synth_pro 1.15", "values": {}}})
    assert engine._stock_mode_restore_ok(str(card.project), str(card.out))
    assert not engine._stock_mode_restore_ok(str(other), str(card.out))
    assert not engine._stock_mode_restore_ok(str(card.project), str(tmp_path / "nothing.raw"))


# ---- a timer as the only change; Defaults' own settings; whole words; Revert all (fix 2) ----
def test_a_timer_staged_on_the_modes_tab_makes_the_project_manage_its_modes(project, build,
                                                                            monkeypatch):
    """A battle timer is an operator setting (staged in Defaults' settings), but staging it
    here still writes the stock_modes record: putting it back to Stock must be able to put
    the card back (the Write asks manages())."""
    from pinball_decryptor.core import staged_changes
    monkeypatch.setattr(S, "_TABLES", [build])
    assert not S.manages(project)
    S.stage(project, build, build.number("12.timer.seconds"), 30)
    data = staged_changes.load(project)
    assert data["stock_modes"] == {"build": "synth_pro 1.15", "values": {},
                                   "touched": ["12.timer.seconds"]}
    assert data["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}
    assert S.manages(project) and S.pending_count(project) == 1
    S.unstage(project, build, build.number("12.timer.seconds"))
    assert S.manages(project) and S.pending_count(project) == 0
    assert "settings" not in staged_changes.load(project)


def test_a_setting_staged_only_on_the_defaults_tab_stays_defaults_business(project, build,
                                                                             monkeypatch):
    """The same setting staged on the Defaults tab alone (no stock_modes record): not a
    stock-mode change, so the Write guard and the Write list behave as they did before item
    145 (Defaults applies it after the next build)."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setattr(S, "_TABLES", [build])
    staged_changes.save(project, {"settings": {"AD_BATTLE_VS_EBIRAH_TIMER": 30}})
    assert S.staged_edits(project) == [] and S.pending_count(project) == 0
    assert S.pending_adjustments(project) == [] and engine._stock_mode_pending(project) == 0
    # once the Modes tab stages anything, the table's settings are its changes too
    S.stage(project, build, build.number("23.start.caward_add"), 777777)
    assert S.pending_count(project) == 2 and len(S.pending_adjustments(project)) == 1


def test_putting_the_only_timer_back_keeps_a_stock_card_at_the_output(card, build, monkeypatch):
    """The verifier's case: only a Modes-tab timer staged, built, the post-build settings
    step changed the file, the timer put back to Stock, Write. Refused and DELETED before;
    now a whole build that leaves the original at the output."""
    import os as _os
    from pinball_decryptor.plugins.stern import engine
    S.stage(str(card.project), build, build.number("12.timer.seconds"), 30)
    card.state["counts"] = engine._with_stock_modes((0, 0, 0, 0), 1)
    counts, _lines = _build(card)
    assert counts[0].stock_modes == 1                        # carried through write_image
    st = card.out.stat()
    _os.utime(card.out, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))     # the settings step
    S.unstage(str(card.project), build, build.number("12.timer.seconds"))
    _refuse_like_the_guard(monkeypatch)
    counts, lines = _build(card)
    assert any("Building from the original" in m for m, _l in lines)
    assert counts[0] == (0, 0, 0, 0) and counts[0].restored
    assert card.out.read_bytes() == card.stock.read_bytes()   # kept, and the original


def test_the_write_summary_names_the_games_own_modes():
    from pinball_decryptor.plugins.stern import engine, pipeline
    w = engine._with_stock_modes
    assert pipeline._write_summary((0, 0, 0, 0)) == "no changes"
    assert pipeline._write_summary(w((0, 0, 0, 0), 2)) == "2 number(s) of the game's own modes"
    assert pipeline._write_summary(w((1, 0, 0, 0), 1)) == \
        "1 sound(s) and 1 number(s) of the game's own modes"
    assert "original card" in pipeline._write_summary(w((0, 0, 0, 0), 0, restored=True))
    c = w((1, 2, 3, 4), 5)
    assert c == (1, 2, 3, 4) and tuple(c) == (1, 2, 3, 4) and json.loads(json.dumps(c)) == [1, 2, 3, 4]


def test_a_whole_word_the_project_changed_goes_back_to_stock(project, build, elf):
    """A lit/data row holding another value is only rewritten when this project once changed
    it (the record's 'touched' rows); put back to Stock, the next Write built FROM that card
    restores the stock word, and restore_count sees it."""
    lit = build.number("23.start.caward_add@2")
    S.stage(project, build, lit, 9999)
    rdr, _ = _stub(elf)
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[build])
    built = _apply(elf, overlay)
    assert n == 1 and struct.unpack_from("<I", built, TEXT_OFF + (LIT_VA - TEXT_VADDR))[0] == 9999
    S.unstage(project, build, lit)
    rdr2, _ = _stub(built)
    assert S.restore_count(rdr2, rdr2.fw_node, project, builds=[build]) == 1
    _w, overlay2, n2 = S.compute_writes(rdr2, rdr2.fw_node, project, None, builds=[build])
    assert n2 == 1 and _apply(built, overlay2) == elf
    # a whole word the project never changed keeps whatever value the card has
    other = str(os.path.join(os.path.dirname(project), "other"))
    os.mkdir(other)
    S.stage(other, build, build.number("23.start.caward_add"), 777777)
    S.unstage(other, build, build.number("23.start.caward_add"))
    assert S.restore_count(rdr2, rdr2.fw_node, other, builds=[build]) == 0


def test_revert_all_clears_the_values_but_keeps_the_project_managing_its_modes():
    rec = {"audio": {"a.wav": "x"}, "settings": {"AD_X": 1},
           "stock_modes": {"build": "synth_pro 1.15", "values": {"23.start.caward_add": 7},
                           "touched": ["23.start.caward_add"]}}
    assert S.kept_by_revert_all(rec) == {"stock_modes": {
        "build": "synth_pro 1.15", "values": {}, "touched": ["23.start.caward_add"]}}
    assert S.kept_by_revert_all({"audio": {"a.wav": "x"}}) == {}
    assert S.kept_by_revert_all({}) == {}


# ---- the real game programs (skip without them) -------------------------------------------
#: the stock cards the programs are read from (read-only, through CardImage): a folder named by
#: PAD_STOCK_MODES_CARDS, the repo's images folder, or D:\Pinball\images\Stern\spike2
REAL_CARDS = {"godzilla_pro 1.15": "godzilla_pro-1_15_0_spike2.Release.8G.sdcard.raw",
              "godzilla_le 1.16": "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"}
REAL = REAL_CARDS


def _real_game_program(build_id):
    """The stock game ELF for *build_id*, or None on a machine without it (CI, WSL)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for folder in (os.environ.get("PAD_STOCK_MODES_CARDS"),
                   os.path.join(here, "images", "Stern", "spike2"),
                   r"D:\Pinball\images\Stern\spike2"):
        card_path = os.path.join(folder, REAL_CARDS[build_id]) if folder else None
        if card_path and os.path.isfile(card_path):
            from pinball_decryptor.plugins.stern.explorer import CardImage
            with CardImage(card_path) as c:
                _table, part, fw_path = c.adjustment_table()
                return bytes(c.read_firmware(part, fw_path))
    return None


@pytest.mark.parametrize("build_id", sorted(REAL))
def test_every_word_row_matches_the_real_game_program(build_id):
    data = _real_game_program(build_id)
    if data is None:
        pytest.skip("no %s game program on this machine (its stock card; "
                    "set PAD_STOCK_MODES_CARDS to a folder of cards)" % build_id)
    table = next(b for b in S.tables() if b.id == build_id)
    img = S.ElfImage(data)
    assert S.identify(img, S.tables())[0] is table
    rows = [n for n in table.numbers if n.is_word]
    assert rows
    for n in rows:
        assert S.site_state(img, n)[0] == "stock", n.row_key
        assert n.words_agree, n.row_key
        if n.kind != "insn":            # an insn row's stock word LOADS its (measured) value
            assert S.decode(n.kind, n.words) == n.value, n.row_key


def test_the_shipped_tables_parse_and_every_row_is_well_formed():
    for b in S.tables():
        assert len(b.sha1) == 40 and b.modes
        for n in b.numbers:
            assert n.mode_id in b.modes, n.row_key
            if n.is_word:
                S.encode(n.kind, n.words, n.value)
                assert n.words_agree, n.row_key
                if n.kind != "insn":
                    assert S.decode(n.kind, n.words) == n.value, n.row_key
                if n.inert:                  # item 159: read-only, and says why
                    assert not n.editable and n.why_read_only()
            if n.is_adjustment:
                assert n.adj_range, n.row_key
                if n.range_inverted:            # Stern ships a few (90..60): read-only, said why
                    assert not n.editable and "minimum is above" in n.why_read_only()


# ---- a Modes-tab timer on EVERY Write path: image, Direct SD, the override set (round 3) -----
# A battle timer is an operator setting: its number is the compiled DEFAULT in the setting's
# descriptor. It used to reach a card only through the app's post-build settings step (an
# image Write only), while the Write's count claimed it on Direct SD and in the emulator's
# override set too. Now it is in the shared patch set, beside the award words.
from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable  # noqa: E402

ADJ_VA = 0x00900000
TIMER_AD = "AD_BATTLE_VS_EBIRAH_TIMER"
ADJ_SPECS = [("AD_INVALID", 0, 0, 0), ("AD_BALLS_PER_GAME", 3, 1, 10), (TIMER_AD, 60, 30, 70)]


def synthetic_elf_with_settings(specs=ADJ_SPECS):
    """synthetic_elf() plus an operator-settings table in a second PT_LOAD, in the shapes
    AdjustmentTable reads: packed ``AD_`` names[], 44-byte descriptors (default at +4, min
    +8, max +12, step +16) and the ``{live, table, count, elem, node}`` record."""
    b = bytearray(_build_elf(inline_crc_loops=5, trailer=VALIDATOR_STRINGS))
    for va, w in ((AWARD_VA, MOVW_R2_D090), (AWARD_VA2, MOVT_R2_3), (TIMER_VA, MOV_R1_30),
                  (LIT_VA, 5000)):
        _put(b, va, w)
    b += b"\0" * (-len(b) % 4)
    base = len(b)
    blob = bytearray()
    name_va = []
    for name, *_rest in specs:
        name_va.append(ADJ_VA + len(blob))
        blob += name.encode() + b"\0"
    node_va = ADJ_VA + len(blob)
    blob += b"SYS\0"
    blob += b"\0" * (-len(blob) % 4)
    for v in name_va:
        blob += struct.pack("<I", v)
    desc_va = ADJ_VA + len(blob)
    for _name, d, mn, mx in specs:
        e = bytearray(44)
        struct.pack_into("<iiii", e, 4, d, mn, mx, 1)
        blob += e
    blob += struct.pack("<IIIII", 0, desc_va, len(specs), 44, node_va)
    b += blob
    ph_off = len(b)
    b += struct.pack("<8I", 1, TEXT_OFF, TEXT_VADDR, TEXT_VADDR, 128 * 4, 128 * 4, 5, 0x1000)
    b += struct.pack("<8I", 1, base, ADJ_VA, ADJ_VA, len(blob), len(blob), 6, 0x1000)
    struct.pack_into("<I", b, 0x1C, ph_off)
    struct.pack_into("<HH", b, 0x2A, 32, 2)
    return bytes(b)


def _timer_default(elf_bytes):
    return AdjustmentTable(elf_bytes).get(TIMER_AD)["default"]


@pytest.fixture
def self_elf():
    return synthetic_elf_with_settings()


@pytest.fixture
def sbuild(self_elf):
    return S.parse(table_text(self_elf))[0]


def test_the_synthetic_settings_table_reads_like_a_game_programs(self_elf, sbuild):
    t = AdjustmentTable(self_elf)
    e = t.get(TIMER_AD)
    assert t.sane() and (e["default"], e["min"], e["max"]) == (60, 30, 70)
    assert S.identify(S.ElfImage(self_elf), [sbuild])[0] is sbuild
    assert S.decode("movwt", S.ElfImage(self_elf).words((AWARD_VA, AWARD_VA2))) == 250000


def test_a_staged_timer_goes_into_the_write_overlay_as_its_default(project, sbuild, self_elf):
    from pinball_decryptor.plugins.stern import sidx as _sidx
    import hmac
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    rdr, blob = _stub(self_elf)
    msgs = []
    writes, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                          lambda m, lvl="info": msgs.append(m), builds=[sbuild])
    off = AdjustmentTable(self_elf).default_file_offset(TIMER_AD)
    assert n == 1 and overlay == {off: struct.pack("<i", 30)}
    assert dict(writes) == {_StubReader.FW_DISK + off: struct.pack("<i", 30)}
    assert any("Battle vs Ebirah timer 60 -> 30" in m and TIMER_AD in m for m in msgs), msgs
    assert _timer_default(_apply(self_elf, overlay)) == 30
    # the validator bypass digests the program WITH the timer in it
    recs, _crc, fmt = _sidx.parse_records(blob)
    if "gz/game" not in recs:
        pytest.skip("stub .sidx doesn't parse on this format revision")
    vlog = []
    vwrites, status = valpatch.compute_writes(rdr, lambda m, lvl="info": vlog.append(m),
                                              fw_overlay=overlay)
    assert status and status[0] == "bypassed", vlog
    shipped = bytearray(_apply(self_elf, overlay))
    eoff = valpatch.find_validation_exec(self_elf)
    shipped[eoff:eoff + 4] = valpatch._BX_LR
    roff = valpatch.find_grade_restore(self_elf)
    if roff is not None:
        shipped[roff:roff + 4] = valpatch._MOV_R0_0
    want_h = hmac.new(_sidx.SIDX_KEY, bytes(shipped), hashlib.sha1).digest()
    by_disk = dict(vwrites)
    for foff, b in _sidx.record_field_writes(recs["gz/game"], want_h,
                                             hashlib.md5(bytes(shipped)).digest(), fmt):
        assert by_disk[_StubReader.SIDX_DISK + foff] == b


def test_a_timer_back_at_stock_restores_the_default_only_where_this_project_changed_it(
        project, sbuild, self_elf):
    num = sbuild.number("12.timer.seconds")
    S.stage(project, sbuild, num, 30)
    rdr, _ = _stub(self_elf)
    _w, overlay, _n = S.compute_writes(rdr, rdr.fw_node, project, None, builds=[sbuild])
    built = _apply(self_elf, overlay)
    # the card already holds it: nothing to write, and the Write hears it is held
    rdr2, _ = _stub(built)
    stats = {}
    assert S.compute_writes(rdr2, rdr2.fw_node, project, None, builds=[sbuild],
                            stats=stats)[1:] == ({}, 0)
    assert stats == {"held": 1}
    S.unstage(project, sbuild, num)
    assert S.pending_count(project) == 0
    assert S.restore_count(rdr2, rdr2.fw_node, project, builds=[sbuild]) == 1
    msgs = []
    _w, overlay2, n2 = S.compute_writes(rdr2, rdr2.fw_node, project,
                                        lambda m, lvl="info": msgs.append(m), builds=[sbuild])
    assert n2 == 1 and _apply(built, overlay2) == self_elf              # byte for byte
    assert any("30 -> 60" in m and "back to stock" in m for m in msgs), msgs
    # a project that never changed the timer leaves another value alone
    other = os.path.join(os.path.dirname(project), "other_timer")
    os.mkdir(other)
    S.stage(other, sbuild, sbuild.number("23.start.caward_add"), 777777)
    S.unstage(other, sbuild, sbuild.number("23.start.caward_add"))
    assert S.restore_count(rdr2, rdr2.fw_node, other, builds=[sbuild]) == 0


def test_a_timer_the_program_cant_take_is_refused_with_the_reason(project, sbuild, self_elf):
    from pinball_decryptor.core import staged_changes
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    data = staged_changes.load(project)
    data["settings"][TIMER_AD] = 99                    # a hand-edited file, outside 30..70
    staged_changes.save(project, data)
    rdr, _ = _stub(self_elf)
    msgs = []
    assert S.compute_writes(rdr, rdr.fw_node, project, lambda m, lvl="info": msgs.append(
        (m, lvl)), builds=[sbuild]) == ([], {}, 0)
    assert any("outside the game's own range" in m and lvl == "warning" for m, lvl in msgs)
    # a program with no settings table: the staged timer is named as not written
    plain = synthetic_elf()
    data["settings"][TIMER_AD] = 30
    staged_changes.save(project, data)
    msgs.clear()
    rdr2, _ = _stub(plain)
    build2 = S.parse(table_text(plain))[0]
    assert S.compute_writes(rdr2, rdr2.fw_node, project, lambda m, lvl="info": msgs.append(
        (m, lvl)), builds=[build2]) == ([], {}, 0)
    assert any("1 staged setting(s) NOT written" in m for m, _l in msgs), msgs


def test_the_settings_step_leaves_out_a_timer_the_write_already_built(project, sbuild,
                                                                       self_elf, monkeypatch):
    """app._apply_staged_settings_to_build asks this: a Modes-tab timer the Write put in the
    build is not written again (that only changed the file, so the next Write built whole).
    A Defaults setting, or a timer the build doesn't hold, still is."""
    from pinball_decryptor.core import staged_changes
    monkeypatch.setattr(S, "_TABLES", [sbuild])
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    data = staged_changes.load(project)
    data["settings"]["AD_BALLS_PER_GAME"] = 5
    staged_changes.save(project, data)
    rdr, _ = _stub(self_elf)
    _w, overlay, _n = S.compute_writes(rdr, rdr.fw_node, project, None)
    built = AdjustmentTable(_apply(self_elf, overlay))
    both = {TIMER_AD: 30, "AD_BALLS_PER_GAME": 5}
    assert S.settings_already_built(project, built, both) == [TIMER_AD]
    assert S.settings_already_built(project, AdjustmentTable(self_elf), both) == []
    # a Defaults-only project (no stock_modes record) keeps the step as it was
    staged_changes.save(project, {"settings": both})
    assert S.settings_already_built(project, built, both) == []


class _CardFileReader(_StubReader):
    """_StubReader over a card image FILE: the game program and the .sidx are read from the
    file at FW_DISK / SIDX_DISK, so what one Write puts on the card the next one reads."""

    def __init__(self, path, elf_len, sidx_len):
        self.path = path
        self.fw_node = {"i_block": b"\x01" * 60, "size": elf_len}
        self.sidx_node = {"i_block": b"\x02" * 60, "size": sidx_len}

    def read_file_bytes(self, node):
        with open(self.path, "rb") as f:
            f.seek(self.FW_DISK if node is self.fw_node else self.SIDX_DISK)
            return f.read(node["size"])

    def extract_file(self, node, dest):
        with open(dest, "wb") as f:
            f.write(self.read_file_bytes(node))


@pytest.fixture
def card_file(tmp_path, project, sbuild, self_elf, monkeypatch):
    """A card image FILE holding the synthetic program and its .sidx, and the engine pointed
    at it: the partition scan and the ext4 locate are stubbed, the rest of the Write is real.
    ``card_file.reading`` is the file the locate last read (the input or the output)."""
    from pinball_decryptor.plugins.stern import engine
    blob = _stub_sidx(["gz/game", "spk/index/a.sidx"])
    path = tmp_path / "synth_pro-1_15_0.raw"
    img = bytearray(0x100000)
    img[_StubReader.FW_DISK:_StubReader.FW_DISK + len(self_elf)] = self_elf
    img[_StubReader.SIDX_DISK:_StubReader.SIDX_DISK + len(blob)] = blob
    path.write_bytes(bytes(img))

    def locate(disk_f, parts):
        name = getattr(disk_f, "name", None)
        name = name if isinstance(name, str) else str(path)
        r = _CardFileReader(name, len(self_elf), len(blob))
        return r, r.fw_node, None
    monkeypatch.setattr(S, "_TABLES", [sbuild])
    monkeypatch.setattr(engine, "_locate", locate)
    monkeypatch.setattr(engine, "device_partitions", lambda *a, **k: [])
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])
    return path


def _card_program(path, n):
    return path.read_bytes()[_StubReader.FW_DISK:_StubReader.FW_DISK + n]


def test_direct_sd_puts_a_modes_tab_timer_on_the_card(card_file, project, sbuild, self_elf):
    """The verifier's case: only the Ebirah timer staged on the Modes tab, a Direct SD Write
    (engine.write_device against a card image file). It lands, and the count is what landed."""
    from pinball_decryptor.plugins.stern import engine, pipeline
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    msgs = []
    log = lambda m, lvl="info", *a, **k: msgs.append(m)  # noqa: E731
    counts, _am, vmode = engine.write_device(str(card_file), project, log=log)
    assert _timer_default(_card_program(card_file, len(self_elf))) == 30
    assert counts == (0, 0, 0, 0) and counts.stock_modes == 1
    assert pipeline._write_summary(counts) == "1 number(s) of the game's own modes"
    assert any(m.startswith("Wrote to SD card:") and "1 number(s) of the game's own modes" in m
               for m in msgs), msgs
    assert vmode and vmode[0] == "bypassed"
    # a second Direct SD Write: the card holds it, so nothing is claimed and nothing refused
    msgs.clear()
    counts2, _am, _vm = engine.write_device(str(card_file), project, log=log)
    assert counts2.stock_modes == 0
    assert _timer_default(_card_program(card_file, len(self_elf))) == 30
    assert any("already holds the 1 staged number" in m for m in msgs), msgs
    # the timer back to Stock: the card gets 60 back
    S.unstage(project, sbuild, sbuild.number("12.timer.seconds"))
    counts3, _am, _vm = engine.write_device(str(card_file), project, log=log)
    assert counts3.stock_modes == 1
    assert _timer_default(_card_program(card_file, len(self_elf))) == 60


def test_the_emulators_override_set_carries_a_modes_tab_timer(card_file, project, sbuild,
                                                               self_elf, tmp_path):
    from pinball_decryptor.plugins.stern import engine
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    S.stage(project, sbuild, sbuild.number("23.start.caward_add"), 777777)
    out = tmp_path / "overrides"
    counts, _am, _vm, files = engine.write_overrides(str(card_file), project, str(out))
    assert counts.stock_modes == 2
    assert "/gz/game" in [p for p, _n in files]
    with open(engine._override_path(str(out), "/gz/game"), "rb") as f:
        game = f.read()
    assert _timer_default(game) == 30
    assert S.decode("movwt", S.ElfImage(game).words((AWARD_VA, AWARD_VA2))) == 777777
    assert _card_program(card_file, len(self_elf)) == self_elf     # the card itself untouched


def test_the_image_write_lands_the_timer_without_the_settings_step(card_file, project, sbuild,
                                                                    self_elf, tmp_path,
                                                                    monkeypatch):
    from pinball_decryptor.plugins.stern import engine
    monkeypatch.setattr(engine, "_open_readers", lambda disk_f, parts: [])
    S.stage(project, sbuild, sbuild.number("12.timer.seconds"), 30)
    out = tmp_path / "build" / "synth_pro-1_15_0-modified.raw"
    out.parent.mkdir()
    counts, _am, _vm = engine.write_image(str(card_file), project, str(out), update=False)
    assert counts.stock_modes == 1
    assert _timer_default(_card_program(out, len(self_elf))) == 30
    assert _timer_default(_card_program(card_file, len(self_elf))) == 60


# ---- a Mod Pack carries the game's own modes (round 3) --------------------------------------
def _pack_folder(path, staged):
    import hashlib as _h
    from pinball_decryptor.core import staged_changes
    path.mkdir()
    (path / "a.wav").write_bytes(b"orig")
    (path / ".checksums.md5").write_text("a.wav\t%s\n" % _h.md5(b"orig").hexdigest(),
                                         encoding="utf-8")
    if staged is not None:
        staged_changes.save(str(path), staged)
    return str(path)


def test_a_mod_pack_carries_the_awards_and_keeps_the_timer_the_modes_tabs(tmp_path):
    """A pack used to carry 'settings' but not 'stock_modes': an imported project lost every
    award, and its timer became a Defaults-only setting."""
    import zipfile
    from pinball_decryptor.core import modpack, staged_changes
    rec = {"build": "godzilla_pro 1.15", "values": {"12.start.caward_add": 777777},
           "touched": ["12.start.caward_add", "12.timer.seconds"]}
    src = _pack_folder(tmp_path / "src", {"settings": {"AD_BATTLE_VS_EBIRAH_TIMER": 30},
                                          "stock_modes": rec})
    (tmp_path / "src" / "a.wav").write_bytes(b"CHANGED")
    zip_path = str(tmp_path / "pack.zip")
    lines = []
    modpack.export_mod_pack(src, zip_path, log_cb=lambda m, lvl="info": lines.append(m))
    with zipfile.ZipFile(zip_path) as zf:
        man = json.loads(zf.read(modpack.MANIFEST_NAME).decode("utf-8"))
    assert man["extras"]["stock_modes"] == rec
    assert any("1 change(s) to the game's own modes" in m for m in lines), lines

    # into a project with its own staged award for the same build: merged row by row
    dest = _pack_folder(tmp_path / "dest", {"stock_modes": {
        "build": "godzilla_pro 1.15", "values": {"23.start.caward_add": 555555},
        "touched": ["23.start.caward_add"]}})
    lines.clear()
    res = modpack.import_mod_pack(zip_path, dest, log_cb=lambda m, lvl="info": lines.append(m))
    assert res["extras"]["stock_modes"] == 1
    got = staged_changes.load(dest)
    assert got["stock_modes"] == {
        "build": "godzilla_pro 1.15",
        "values": {"23.start.caward_add": 555555, "12.start.caward_add": 777777},
        "touched": ["12.start.caward_add", "12.timer.seconds", "23.start.caward_add"]}
    assert got["settings"] == {"AD_BATTLE_VS_EBIRAH_TIMER": 30}
    assert any("1 change(s) to the game's own modes" in m for m in lines), lines


def test_a_mod_pack_for_another_build_never_mixes_row_keys(tmp_path):
    from pinball_decryptor.core import modpack, staged_changes
    le = {"build": "godzilla_le 1.16", "values": {"12.start.caward_add": 1}}
    data = {"stock_modes": le}
    lines = []
    extras = {"stock_modes": {"build": "godzilla_pro 1.15",
                              "values": {"12.start.caward_add": 777777}}}
    dest = _pack_folder(tmp_path / "le", data)
    modpack.apply_extras(dest, extras, log_cb=lambda m, lvl="info": lines.append((m, lvl)))
    assert staged_changes.load(dest)["stock_modes"] == le
    assert any("were not imported" in m and lvl == "warning" for m, lvl in lines), lines
    # a record here with nothing staged in it takes the pack's
    empty = _pack_folder(tmp_path / "empty", {"stock_modes": {"build": "godzilla_le 1.16",
                                                              "values": {}}})
    modpack.apply_extras(empty, extras)
    assert staged_changes.load(empty)["stock_modes"]["build"] == "godzilla_pro 1.15"
    # and a project that never managed its modes exports nothing for them
    assert "stock_modes" not in modpack.project_extras(
        _pack_folder(tmp_path / "plain", {"settings": {"AD_FREE_PLAY": 1}}))


# ---- item 159: a stock mode's SHOTS as data (the tank path family, the spin counts) --------
# Item 158 measured that tank attack never reads its lit mask (its shots are a six-entry path
# the tanks walk) and that battle vs Ebirah rebuilds its mask from spin counts at every start.
# These tests pin the app's side on a synthetic ELF: the new kinds (path, qword, insn), the
# inert / fixed / follows marks, a position set to NONE (a copy of its neighbour away from the
# goal, the proven way) or to another shot with the counted-shots words and the spot list kept
# in step, the refusals (a duplicate, a multi-bit, a shot the switches never send alone, a
# fixed position, a family whose counted words can't encode), the revert byte for byte, a spin
# count as a mov over the load, and an inert row's stale value never written.
FAMILY_VA = TEXT_VADDR + 0x400
PATH_VA = FAMILY_VA                          # 6 x 16-byte entries
SPOT_VA = FAMILY_VA + 0x60                   # 6 x u64
CNT_LO_VA, CNT_HI_VA, CNT_LO2_VA = FAMILY_VA + 0x90, FAMILY_VA + 0x94, FAMILY_VA + 0x98
SPIN_VA = (FAMILY_VA + 0xA0, FAMILY_VA + 0xA4, FAMILY_VA + 0xA8)
PATH_STOCK = [(1 << 35, 0x0B7F0072), (0x100000, 0x0B6D0090), (0x80000, 0x0B6C0093),
              (0x800, 0x0B64009A), (0x200000, 0x0B6E00AD), (1 << 37, 0x0B80007B)]
SPOT_STOCK = [0x80000, 0x100000, 0x800, 0x200000, 1 << 35, 1 << 37]
MOVEQ_R0_800, MOVEQ_R1_28, MOVTEQ_R0_38 = 0x03A00B02, 0x03A01028, 0x03400038
LDR_LEFT, LDR_TOP, LDR_SHIELD = 0xE5905078, 0xE594607C, 0xE5945080


def _with_big_phdr(elf, text_len=0x600):
    """``_with_phdr`` with a PT_LOAD long enough to hold a data region after the code."""
    b = bytearray(elf)
    b += b"\0" * max(0, TEXT_OFF + text_len - len(b))
    ph_off = len(b)
    b += struct.pack("<8I", 1, TEXT_OFF, TEXT_VADDR, TEXT_VADDR, text_len, text_len, 5, 0x1000)
    struct.pack_into("<I", b, 0x1C, ph_off)
    struct.pack_into("<HH", b, 0x2A, 32, 1)
    return b


def family_elf():
    b = _with_big_phdr(_build_elf(inline_crc_loops=5, trailer=VALIDATOR_STRINGS))
    for va, w in ((AWARD_VA, MOVW_R2_D090), (AWARD_VA2, MOVT_R2_3), (TIMER_VA, MOV_R1_30),
                  (LIT_VA, 5000), (MASK_VA, MOV_R0_800), (MASK_VA2, MOVT_R0_70)):
        _put(b, va, w)
    for i, (mask, lamp) in enumerate(PATH_STOCK):
        _put(b, PATH_VA + 16 * i, mask & 0xFFFFFFFF)
        _put(b, PATH_VA + 16 * i + 4, mask >> 32)
        _put(b, PATH_VA + 16 * i + 8, lamp)
        _put(b, PATH_VA + 16 * i + 12, 0)
    for i, mask in enumerate(SPOT_STOCK):
        _put(b, SPOT_VA + 8 * i, mask & 0xFFFFFFFF)
        _put(b, SPOT_VA + 8 * i + 4, mask >> 32)
    _put(b, CNT_LO_VA, MOVEQ_R0_800)
    _put(b, CNT_HI_VA, MOVEQ_R1_28)
    _put(b, CNT_LO2_VA, MOVTEQ_R0_38)
    for va, w in zip(SPIN_VA, (LDR_LEFT, LDR_TOP, LDR_SHIELD)):
        _put(b, va, w)
    return bytes(b)


def family_table(elf):
    fixed = {0: " fixed seed", 2: " fixed goal", 4: " fixed seed", 5: " fixed seed"}
    lines = [table_text(elf, game="godzilla_pro", version="1.15")]
    lines.append("mode 4 cmode_tank_attack_multiball obj 0x7a1b20 vtable 0x6300f8 title_msg 3240")
    lines.append("number 4 initial_mask.lo 7342080 movwt 0x%x 0x%x e3a00b02,e3400070 word inert inline_copy"
                 % (MASK_VA, MASK_VA2))
    for i, (mask, lamp) in enumerate(PATH_STOCK):
        lines.append("number 4 path.%d 0x%x path 0x%x %08x,%08x,%08x,00000000 word%s  # TANK %d" % (
            i, mask, PATH_VA + 16 * i, mask & 0xFFFFFFFF, mask >> 32, lamp, fixed.get(i, ""), i + 1))
    lines.append("number 4 path.counted.lo 0x380800 movwt 0x%x 0x%x 03a00b02,03400038 word follows path"
                 % (CNT_LO_VA, CNT_LO2_VA))
    lines.append("number 4 path.counted.hi 0x28 imm 0x%x 03a01028 word follows path" % CNT_HI_VA)
    for i, mask in enumerate(SPOT_STOCK):
        lines.append("number 4 path.spot.%d 0x%x qword 0x%x %08x,%08x word follows path" % (
            i, mask, SPOT_VA + 8 * i, mask & 0xFFFFFFFF, mask >> 32))
    lines.append("number 12 spins.left 15 insn 0x%x e5905078 word" % SPIN_VA[0])
    lines.append("number 12 spins.top 40 insn 0x%x e594607c word" % SPIN_VA[1])
    lines.append("number 12 spins.shield 15 insn 0x%x e5945080 word" % SPIN_VA[2])
    return "\n".join(lines) + "\n"


@pytest.fixture
def felf():
    return family_elf()


@pytest.fixture
def fbuild(felf):
    return S.parse(family_table(felf))[0]


def _plan(project, build, elf):
    rdr, _ = _stub(elf)
    msgs = []
    _w, overlay, n = S.compute_writes(rdr, rdr.fw_node, project,
                                      lambda m, lvl="info": msgs.append((m, lvl)), builds=[build])
    return overlay, n, msgs


def _word(overlay, va):
    return struct.unpack("<I", overlay[TEXT_OFF + (va - TEXT_VADDR)])[0]


def test_the_shots_as_data_kinds_read_encode_and_say_what_is_read_only(fbuild):
    b = fbuild
    p3, p0, p2 = b.number("4.path.3"), b.number("4.path.0"), b.number("4.path.2")
    assert p3.kind == "path" and p3.value == 0x800 and p3.path_index == 3 and p3.editable
    assert b.row_label(p3) == "Position 4" and p3.is_player_facing
    assert "16-byte path entry" in p3.where_text()
    assert not p0.editable and "tanks appear" in p0.why_read_only()
    assert not p2.editable and "heads for" in p2.why_read_only()
    assert [n.path_index for n in S.path_rows(b, 4)] == [0, 1, 2, 3, 4, 5]
    assert S.path_none_neighbour(S.path_rows(b, 4), 3).path_index == 4     # away from the goal
    assert S.path_none_neighbour(S.path_rows(b, 4), 1).path_index == 0
    cnt = b.number("4.path.counted.lo")
    assert cnt.follows == "path" and not cnt.editable and "in step" in cnt.why_read_only()
    assert not cnt.is_player_facing and not b.number("4.path.spot.2").is_player_facing
    mask = b.number("4.initial_mask.lo")
    assert mask.inert == "inline_copy" and not mask.editable
    assert "never reads its lit shots" in mask.why_read_only() and mask.words_agree
    spins = b.number("12.spins.left")
    assert spins.kind == "insn" and spins.value == 15 and spins.editable and spins.words_agree
    assert b.row_label(spins) == "Left spinner spins" and spins.is_player_facing
    # the words
    assert S.decode("path", (0x800, 0, 0x0B64009A, 0)) == 0x800
    assert S.encode("path", (0x800, 0, 0x0B64009A, 0), 1 << 37) == (0, 0x20, 0x0B64009A, 0)
    assert S.decode("qword", (0, 8)) == 1 << 35 and S.encode("qword", (0, 8), 0x800) == (0x800, 0)
    assert S.decode("insn", (LDR_LEFT,)) is None                       # the load: measured, not held
    assert S.encode("insn", (LDR_LEFT,), 5) == (0xE3A05005,)          # mov r5, #5
    assert S.encode("insn", (LDR_TOP,), 40) == (0xE3A06028,)          # mov r6, #40: the load's register
    assert S.decode("insn", (0xE3A05005,)) == 5
    assert S.skeleton("insn", (LDR_LEFT,)) == S.skeleton("insn", (0xE3A05005,))
    with pytest.raises(S.StockModeError, match="at least 1"):
        S.encode("insn", (LDR_LEFT,), 0)
    with pytest.raises(S.StockModeError, match="nearest that fits"):
        S.encode("insn", (LDR_LEFT,), 257)
    # names: the port's shot lines, the spinner bits, else the bit number
    assert S.shot_name(b, 0x100000) == "Left ramp" and S.shot_name(b, 0x800) == "Top spinner, first bit"
    assert S.shot_name(b, 0) == "none" and S.shot_name(b, 1 << 35) == "bit 35"
    assert S.display(b, p3, 0x800) == "Top spinner, first bit" and S.display(b, spins, 15) == "15"
    choices = dict(S.path_choices(b, p3))
    assert choices[0].startswith("none") and choices[0x400000] == "Building"
    assert 0x1000000000 not in choices                                 # Big loop: never alone
    assert 0x200000 not in choices and 0x100000 not in choices         # other positions
    assert S.path_choices(b, p0) == []


def test_a_position_set_to_none_copies_its_neighbour_and_the_family_follows(project, fbuild, felf):
    from pinball_decryptor.core import staged_changes
    assert S.stage(project, fbuild, fbuild.number("4.path.3"), "none") == 0
    assert staged_changes.load(project)["stock_modes"]["values"] == {"4.path.3": 0}
    assert S.pending_count(project) == 1
    edits = S.staged_edits(project, fbuild)
    assert (edits[0]["stock_text"], edits[0]["new_text"]) == ("Top spinner, first bit", "none")
    overlay, n, msgs = _plan(project, fbuild, felf)
    assert n == 2                                            # the entry + the counted low half
    # the whole entry is position 5's (lamp and id too): the walk skips it, the proven way
    assert [_word(overlay, PATH_VA + 0x30 + 4 * k) for k in range(4)] == \
        [0x200000, 0, 0x0B6E00AD, 0]
    assert _word(overlay, CNT_LO_VA) == 0x03A00000 and _word(overlay, CNT_LO2_VA) == MOVTEQ_R0_38
    assert TEXT_OFF + (CNT_HI_VA - TEXT_VADDR) not in overlay            # bits 37, 35: unchanged
    assert not any(TEXT_OFF + (SPOT_VA + 8 * i - TEXT_VADDR) in overlay for i in range(6))
    text = " ".join(m for m, _l in msgs)
    assert "position 4: Top spinner, first bit -> none" in text and "counted shots (lo) kept in step" in text


def test_a_position_replaced_by_a_shot_moves_its_spot_entry_and_the_counted_words(project, fbuild, felf):
    assert S.stage(project, fbuild, fbuild.number("4.path.3"), "0x400000") == 0x400000
    overlay, n, _m = _plan(project, fbuild, felf)
    assert n == 3                                            # entry, counted low half, spot entry
    assert [_word(overlay, PATH_VA + 0x30 + 4 * k) for k in range(4)] == [0x400000, 0, 0x0B64009A, 0]
    assert _word(overlay, CNT_LO_VA) == 0x03A00000 and _word(overlay, CNT_LO2_VA) == 0x03400078
    assert (_word(overlay, SPOT_VA + 16), _word(overlay, SPOT_VA + 20)) == (0x400000, 0)
    # a shot above bit 31 lands in the high half of the counted words (a moveq: bits 35, 37
    # and 42 together would need an odd rotation, so that one is refused with the reason)
    with pytest.raises(S.StockModeError, match="counted-shots instruction"):
        S.stage(project, fbuild, fbuild.number("4.path.3"), str(1 << 42))
    S.stage(project, fbuild, fbuild.number("4.path.3"), str(1 << 39))
    overlay, n, _m = _plan(project, fbuild, felf)
    assert n == 4 and _word(overlay, CNT_HI_VA) == 0x03A010A8    # moveq r1, #0xa8 (bits 35, 37, 39)
    assert _word(overlay, PATH_VA + 0x34) == 0x80


def test_a_position_refuses_what_the_tanks_cannot_stand_on(project, fbuild):
    p3, p1 = fbuild.number("4.path.3"), fbuild.number("4.path.1")
    with pytest.raises(S.StockModeError, match="already position 5"):
        S.stage(project, fbuild, p3, "0x200000")
    with pytest.raises(S.StockModeError, match="ONE shot"):
        S.stage(project, fbuild, p3, "0x3")
    with pytest.raises(S.StockModeError, match="never send Big loop alone"):
        S.stage(project, fbuild, p3, str(1 << 36))
    with pytest.raises(S.StockModeError, match="tanks appear"):
        S.stage(project, fbuild, fbuild.number("4.path.0"), "none")
    with pytest.raises(S.StockModeError, match="in step"):
        S.stage(project, fbuild, fbuild.number("4.path.counted.lo"), 5)
    # two low bits far apart (the Slingshot's bit 1 beside the Top spinner's bit 11) do not
    # fit the counted-shots mov: refused with the reason; once the Top spinner is gone they do
    with pytest.raises(S.StockModeError, match="counted-shots instruction"):
        S.stage(project, fbuild, p1, "0x2")
    assert S.stage(project, fbuild, p3, "0x40") == 0x40
    assert S.stage(project, fbuild, p1, "0x2") == 0x2
    assert S.staged(project)["values"] == {"4.path.1": 2, "4.path.3": 0x40}
    assert S.stage(project, fbuild, p3, "0x800") is None
    # a NONE neighbour counts as the shot it copies (bit 35 is position 1's, and now 2's too)
    S.stage(project, fbuild, p1, "none")
    with pytest.raises(S.StockModeError, match="bit 35 is already position"):
        S.stage(project, fbuild, p3, str(1 << 35))


def test_the_family_goes_back_to_stock_byte_for_byte(project, fbuild, felf):
    S.stage(project, fbuild, fbuild.number("4.path.3"), "none")
    overlay, _n, _m = _plan(project, fbuild, felf)
    written = bytearray(felf)
    for off, b in overlay.items():
        written[off:off + 4] = b
    written = bytes(written)
    assert S.identify(S.ElfImage(written), [fbuild])[0] is fbuild        # still this build, by words
    # a second Write of the same edit: nothing to do
    overlay2, n2, _m = _plan(project, fbuild, written)
    assert (overlay2, n2) == ({}, 0)
    # back to Top spinner: the stock words, every one of them
    assert S.stage(project, fbuild, fbuild.number("4.path.3"), "0x800") is None
    assert S.pending_count(project) == 0 and S.manages(project)
    overlay3, n3, msgs = _plan(project, fbuild, written)
    assert n3 == 2 and "back to stock" in " ".join(m for m, _l in msgs)
    restored = bytearray(written)
    for off, b in overlay3.items():
        restored[off:off + 4] = b
    assert bytes(restored) == felf
    # and on a stock card with nothing staged, nothing is written at all
    assert _plan(project, fbuild, felf)[:2] == ({}, 0)
    # revert all keeps the family managed: the card that holds our words still goes back
    S.stage(project, fbuild, fbuild.number("4.path.3"), "none")
    S.unstage_all(project, fbuild)
    overlay4, n4, _m = _plan(project, fbuild, written)
    assert n4 == 2 and overlay4 == overlay3


def test_a_spin_count_is_a_mov_over_the_load_and_the_load_comes_back(project, fbuild, felf):
    left = fbuild.number("12.spins.left")
    assert S.stage(project, fbuild, left, "5") == 5
    with pytest.raises(S.StockModeError, match="at least 1"):
        S.stage(project, fbuild, left, "0")
    overlay, n, msgs = _plan(project, fbuild, felf)
    assert n == 1 and _word(overlay, SPIN_VA[0]) == 0xE3A05005
    assert "spins 15 -> 5" in " ".join(m for m, _l in msgs)
    written = bytearray(felf)
    _put(written, SPIN_VA[0], 0xE3A05005)
    written = bytes(written)
    img = S.ElfImage(written)
    assert S.site_state(img, left) == ("ours", (0xE3A05005,))
    assert S.identify(img, [fbuild])[1] == "words"
    assert S.stage(project, fbuild, left, "15") is None                # back to the load
    overlay, n, _m = _plan(project, fbuild, written)
    assert n == 1 and _word(overlay, SPIN_VA[0]) == LDR_LEFT
    # a card with a different load there is not this build's row: refused, not guessed
    other = bytearray(felf)
    _put(other, SPIN_VA[0], 0xE5905074)
    assert S.site_state(S.ElfImage(bytes(other)), left)[0] == "differs"


def test_an_inert_rows_stale_value_is_never_written_but_the_card_still_goes_back(project, fbuild, felf):
    from pinball_decryptor.core import staged_changes
    mask = fbuild.number("4.initial_mask.lo")
    with pytest.raises(S.StockModeError, match="never reads its lit shots"):
        S.stage(project, fbuild, mask, 0x700000)
    # an older project staged it before item 158 measured it
    staged_changes.save(project, {"stock_modes": {"build": fbuild.id,
                                                  "values": {"4.initial_mask.lo": 0x700000},
                                                  "touched": ["4.initial_mask.lo"]}})
    assert S.pending_count(project) == 0 and S.staged_edits(project, fbuild) == []
    overlay, n, msgs = _plan(project, fbuild, felf)
    assert (overlay, n) == ({}, 0)
    assert any("not written" in m and "never reads" in m and lvl == "warning" for m, lvl in msgs)
    # a card an older app wrote that edit onto: the stock instruction goes back
    old = bytearray(felf)
    _put(old, MASK_VA, 0xE3A00000)                                       # mov r0, #0
    overlay, n, _m = _plan(project, fbuild, bytes(old))
    assert n == 1 and _word(overlay, MASK_VA) == MOV_R0_800


@pytest.mark.parametrize("build_id", ["godzilla_pro 1.15", "godzilla_le 1.16"])
def test_the_shipped_tables_carry_the_tank_path_and_the_spin_counts(build_id):
    b = next(x for x in S.tables() if x.id == build_id)
    rows = S.path_rows(b, 4)
    assert [n.path_index for n in rows] == [0, 1, 2, 3, 4, 5]
    assert [n.value for n in rows] == [1 << 35, 0x100000, 0x80000, 0x800, 0x200000, 1 << 37]
    assert [n.path_index for n in rows if n.editable] == [1, 3]
    assert S.path_goal(rows) == 2
    follows = [n for n in b.numbers if n.mode_id == 4 and n.follows == "path"]
    assert sorted(n.key for n in follows) == sorted(
        ["path.counted.lo", "path.counted.hi"] + ["path.spot.%d" % i for i in range(6)])
    assert S.family_words(b, 4, {}) == {n.row_key: tuple(n.words) for n in rows + follows}
    words = S.family_words(b, 4, {"4.path.3": 0})
    assert words["4.path.3"] == tuple(rows[4].words)
    assert S.decode("movwt", words["4.path.counted.lo"]) == 0x380000
    choices = dict(S.path_choices(b, rows[3]))
    assert choices[0x800] == "Top spinner, first bit" and choices[0x400000] == "Building" and 0 in choices
    assert 1 << 36 not in choices and 0x100000 not in choices
    spins = {n.key: n for n in b.numbers if n.mode_id == 12 and n.kind == "insn"}
    assert sorted(spins) == ["spins.left", "spins.shield", "spins.top"]
    assert [spins[k].value for k in ("spins.left", "spins.top", "spins.shield")] == [15, 40, 15]
    assert all(n.editable and n.words_agree for n in spins.values())
    # the getter rows item 158 / 159 found inert, on both builds
    inert = sorted({n.mode_id for n in b.numbers if n.inert})
    assert inert == [1, 4, 7, 12, 13, 15, 20, 22]
    assert all(not n.editable and n.why_read_only() for n in b.numbers if n.inert)
    live = sorted({n.mode_id for n in b.numbers if n.key.startswith("initial_mask.")
                   and n.is_word and n.editable})
    assert live == [2, 5, 6, 9, 10, 11, 18, 21, 23, 24, 26]


def test_shot_labels_are_unique_on_both_builds():
    """One label, one bit: the port names the top spinner's middle bit 0x2000 "Top spinner" and the
    tank path holds its first bit 0x800, so the two must read differently in the picker, the Value
    and Stock columns and the Write log (the merge of the port's spinner shots and the path family
    once listed "Top spinner" twice)."""
    for build_id in ("godzilla_le 1.16", "godzilla_pro 1.15"):
        b = next(x for x in S.tables() if x.id == build_id)
        names = S.shot_names(b)
        labels = list(names.values())
        assert len(labels) == len(set(labels)), sorted(l for l in labels if labels.count(l) > 1)
        assert names[0x800] == "Top spinner, first bit" and names[0x2000] == "Top spinner"
        rows = S.path_rows(b, 4)
        for n in rows:
            picks = [label for _m, label in S.path_choices(b, n)]
            assert len(picks) == len(set(picks)), picks
