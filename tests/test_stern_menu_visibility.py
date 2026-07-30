"""Which adjustments the machine's operator menu can reach
(plugins.stern.menu_visibility).

The real signal lives in ARM code, so the fixture bolts a hand-assembled
``.text`` onto the same synthetic ELF the adjustment-decoder tests use: an
accessor, a page renderer that materialises the section pointer and calls it,
and two callers describing the two pages a real title has (an explicit id list
and an id range).  Dropping either page must make the module refuse to answer
rather than condemn every setting it couldn't account for — James Bond 60th is
a real build that only exposes one of them.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, all_rows
from pinball_decryptor.plugins.stern.menu_visibility import (DEBUG, SERVICE,
                                                             VISIBLE,
                                                             MenuVisibility,
                                                             statuses,
                                                             widen_plan,
                                                             widened_bytes)

BASE = 0x10000
ELEM = 44

# name, default, min, max.  A page has to be big enough to be believable —
# the module ignores runs too short to be a real menu page — so both pages
# here are the minimum realistic size.
SPECS = [
    ("AD_INVALID", 0, 0, 0),
    ("AD_FREE_PLAY", 0, 0, 1),               # 1 \
    ("AD_BALLS_PER_GAME", 3, 1, 10),         # 2  |
    ("AD_MAX_PLAYERS_PER_GAME", 4, 1, 4),    # 3  } standard page (list)
    ("AD_TILT_WARNINGS", 2, 0, 5),           # 4  |
    ("AD_CREDIT_LIMIT", 30, 4, 50),          # 5  |
    ("AD_REPLAY_PERCENTAGE", 7, 0, 50),      # 6 /
    ("AD_SOUND_MASTER_VOLUME_SETTING", 64, 0, 64),   # 7  service elsewhere
    ("AD_TOURNAMENT_TYPE", 0, 0, 3),         # 8  service elsewhere
    ("AD_MISSION_ONE_DIFFICULTY", 1, 0, 2),  # 9  \
    ("AD_MISSION_TWO_DIFFICULTY", 1, 0, 2),  # 10 |
    ("AD_ALLOW_FLIPPER_SPEECH", 1, 0, 1),    # 11 } feature page (range)
    ("AD_ALLOW_R_RATED_SPEECH", 1, 0, 1),    # 12 |
    ("AD_TOPPER_THEME", 0, 0, 4),            # 13 /
    ("AD_TEST_THIS_IS_THE_WAY", 0, 0, 1),    # 14 hidden: past the range
    ("AD_TOPPER_CHEATS", 0, 0, 1),           # 15 hidden: past the range
]
STD_LIST = [1, 2, 3, 4, 5, 6]
FEATURE_FIRST, FEATURE_LAST = 9, 13


def _arm(words):
    return b"".join(struct.pack("<I", w) for w in words)


def _movw(rd, imm):
    return 0xE3000000 | ((imm & 0xF000) << 4) | (rd << 12) | (imm & 0xFFF)


def _movt(rd, imm):
    return 0xE3400000 | ((imm & 0xF000) << 4) | (rd << 12) | (imm & 0xFFF)


def _mov_imm(rd, imm):
    assert 0 <= imm < 256
    return 0xE3A00000 | (rd << 12) | imm


def _bl(at, target):
    off = (target - (at + 8)) >> 2
    return 0xEB000000 | (off & 0xFFFFFF)


def make_elf(pages=("list", "range"), caption=b"MENU CAPTION\x00",
             end_form="mov", ranges=1):
    """Synthetic ELF: strings, names[], descriptors, section record, an id
    list, then a .text carrying the accessor, the renderer and the callers.

    ``pages`` selects which page callers to emit, so a build that only exposes
    one of them can be exercised.  ``end_form`` picks the instruction the range
    caller sets its LAST id with (real titles use both), and ``ranges`` emits
    more than one range page — the shape that makes "which page is Feature
    Adjustments?" a guess."""
    def va(off):
        return BASE + off

    hdr_len = 52 + 32
    blob = bytearray()
    name_va = []
    for name, _d, _mn, _mx in SPECS:
        name_va.append(va(hdr_len + len(blob)))
        blob += name.encode() + b"\x00"
    node_rel = len(blob)
    blob += b"SYS\x00"
    cap_rel = len(blob)
    blob += caption
    # names[] is found as a run of 4-byte-aligned words, so the string pool it
    # follows has to end on a word boundary.
    blob += b"\x00" * (-(hdr_len + len(blob)) % 4)

    names_off = hdr_len + len(blob)
    names_arr = b"".join(struct.pack("<I", v) for v in name_va)

    desc_off = names_off + len(names_arr)
    desc = bytearray()
    for _n, d, mn, mx in SPECS:
        e = bytearray(ELEM)
        struct.pack_into("<iii", e, 0x04, d, mn, mx)
        struct.pack_into("<i", e, 0x10, 1)
        struct.pack_into("<I", e, 0x18, va(hdr_len + cap_rel))
        desc += e

    rec_off = desc_off + len(desc)
    record = struct.pack("<IIIII", 0, va(desc_off), len(SPECS), ELEM,
                         va(hdr_len + node_rel))

    list_off = rec_off + len(record)
    id_list = b"".join(struct.pack("<H", i) for i in STD_LIST) + b"\x00\x00"

    text_off = (list_off + len(id_list) + 3) & ~3
    sect = va(rec_off) + 4          # what the firmware hands the accessor
    lst = va(list_off)

    # accessor(section, id) -> table + elem*id, then the renderer that walks it
    acc = va(text_off)
    renderer = acc + 4 * 4
    body = [
        0xE5902000,                 # ldr r2, [r0]        ; table
        0xE5903008,                 # ldr r3, [r0, #8]    ; elem
        0xE0222391,                 # mla r2, r1, r3, r2  (shape only)
        0xE12FFF1E,                 # bx lr
        # --- renderer: push {r4, lr}; materialise the section; call accessor
        0xE92D4010,
        _movw(0, sect & 0xFFFF), _movt(0, sect >> 16),
        _bl(renderer + 4 * 3, acc),
        0xE8BD8010,                 # pop {r4, pc}
    ]
    callers = []
    call_base = renderer + 4 * 5
    if "range" in pages:
        for n in range(ranges):
            at = call_base + 4 * len(callers)
            end = _movw(2, FEATURE_LAST) if end_form == "movw" else \
                _mov_imm(2, FEATURE_LAST)
            callers += [
                0xE52DE004,             # str lr, [sp, #-4]!
                _mov_imm(0, 0),
                _mov_imm(1, FEATURE_FIRST - n),
                end,
                0xE58D0000,             # str r0, [sp]   (a spill, not a def)
                _bl(at + 4 * 5, renderer),
                0xE49DF004,             # pop {pc}
            ]
    if "list" in pages:
        at = call_base + 4 * len(callers)
        callers += [
            0xE52DE004,
            _movw(0, lst & 0xFFFF), _movt(0, lst >> 16),
            _mov_imm(1, 0),
            _mov_imm(2, 0),
            _bl(at + 4 * 5, renderer),
            0xE49DF004,
        ]
    text = _arm(body + callers)

    payload = bytearray()
    payload += blob
    payload += names_arr
    payload += desc
    payload += record
    payload += id_list
    payload += b"\x00" * (text_off - (list_off + len(id_list)))
    payload += text
    total = hdr_len + len(payload)

    eh = bytearray(52)
    eh[0:4] = b"\x7fELF"
    eh[4] = 1
    eh[5] = 1
    eh[6] = 1
    struct.pack_into("<H", eh, 0x10, 2)
    struct.pack_into("<H", eh, 0x12, 40)
    struct.pack_into("<I", eh, 0x14, 1)
    struct.pack_into("<I", eh, 0x1c, 52)
    struct.pack_into("<H", eh, 0x28, 52)
    struct.pack_into("<H", eh, 0x2a, 32)
    struct.pack_into("<H", eh, 0x2c, 1)
    ph = struct.pack("<IIIIIIII", 1, 0, BASE, BASE, total, total, 5, 0x1000)
    return bytes(eh + ph + payload)


def test_finds_both_pages():
    t = AdjustmentTable(make_elf())
    pages = MenuVisibility(t).pages()
    assert sorted(k for k, _ids in pages) == ["list", "range"]
    by_kind = dict(pages)
    assert by_kind["list"] == STD_LIST
    assert by_kind["range"] == list(range(FEATURE_FIRST, FEATURE_LAST + 1))


def test_statuses_split_visible_service_and_debug():
    t = AdjustmentTable(make_elf())
    st = statuses(t)
    by_name = {t.names[i]: s for i, s in st.items()}
    assert by_name["AD_FREE_PLAY"] == VISIBLE
    assert by_name["AD_ALLOW_R_RATED_SPEECH"] == VISIBLE
    assert by_name["AD_TOPPER_THEME"] == VISIBLE
    # Unreachable, but the operator still edits these elsewhere.
    assert by_name["AD_SOUND_MASTER_VOLUME_SETTING"] == SERVICE
    assert by_name["AD_TOURNAMENT_TYPE"] == SERVICE
    # a tester' two confirmed-hidden Mandalorian settings, in miniature.
    assert by_name["AD_TEST_THIS_IS_THE_WAY"] == DEBUG
    assert by_name["AD_TOPPER_CHEATS"] == DEBUG


def test_one_page_only_refuses_to_answer():
    """James Bond 60th's shape: without both pages the complement is a lie."""
    for only in (("list",), ("range",)):
        t = AdjustmentTable(make_elf(pages=only))
        assert MenuVisibility(t).visible() is None
        assert statuses(t) is None


def test_all_rows_carries_caption_and_status():
    t = AdjustmentTable(make_elf())
    rows = {r["name"]: r for r in all_rows(t, statuses(t))}
    assert "AD_INVALID" not in rows          # id 0 is not a setting
    assert rows["AD_TOPPER_CHEATS"]["status"] == DEBUG
    assert rows["AD_TOPPER_CHEATS"]["label"] == "MENU CAPTION"
    assert rows["AD_BALLS_PER_GAME"]["default"] == 3
    assert (rows["AD_BALLS_PER_GAME"]["min"],
            rows["AD_BALLS_PER_GAME"]["max"]) == (1, 10)


def test_all_rows_without_menu_leaves_status_unset():
    t = AdjustmentTable(make_elf(pages=("list",)))
    rows = all_rows(t, statuses(t))
    assert rows and all(r["status"] is None for r in rows)


def test_caption_falls_back_to_the_name():
    """A build whose caption pointer isn't a caption still gets a label."""
    t = AdjustmentTable(make_elf(caption=b"\xff\xfe\x00"))
    rows = {r["name"]: r for r in all_rows(t, None)}
    assert rows["AD_TOPPER_CHEATS"]["label"] == "Topper Cheats"


# ---------------------------------------------------------------------------
# Widening the feature page so the machine SHOWS the hidden tail (a tester).
# ---------------------------------------------------------------------------

HIDDEN = ["AD_TEST_THIS_IS_THE_WAY", "AD_TOPPER_CHEATS"]


@pytest.mark.parametrize("end_form", ["mov", "movw"])
def test_widen_plan_offers_exactly_the_hidden_tail(end_form):
    t = AdjustmentTable(make_elf(end_form=end_form))
    plan = widen_plan(t)
    assert (plan["first"], plan["last"]) == (FEATURE_FIRST, FEATURE_LAST)
    assert plan["form"] == end_form
    assert [c["name"] for c in plan["candidates"]] == HIDDEN


@pytest.mark.parametrize("end_form", ["mov", "movw"])
def test_widening_exposes_through_the_chosen_setting_only(end_form):
    """The page is a range, so a pick takes everything up to it and nothing
    beyond — and the rest of the menu must read back untouched."""
    t = AdjustmentTable(make_elf(end_form=end_form))
    before = statuses(t)
    out = widened_bytes(t, t.data, t.by_name["AD_TEST_THIS_IS_THE_WAY"])
    assert len(out) == len(t.data)
    # Size-neutral, and every changed byte inside ONE aligned instruction —
    # that is what keeps the existing exact-size ELF write applicable.
    diff = [i for i in range(len(out)) if out[i] != t.data[i]]
    assert diff and len({i // 4 for i in diff}) == 1
    after = statuses(AdjustmentTable(out))
    assert after[t.by_name["AD_TEST_THIS_IS_THE_WAY"]] == VISIBLE
    assert after[t.by_name["AD_TOPPER_CHEATS"]] == DEBUG      # not asked for
    moved = {i for i in before if before[i] != after[i]}
    assert moved == {t.by_name["AD_TEST_THIS_IS_THE_WAY"]}


def test_widening_to_the_end_exposes_the_whole_tail():
    t = AdjustmentTable(make_elf())
    after = statuses(AdjustmentTable(
        widened_bytes(t, t.data, t.by_name["AD_TOPPER_CHEATS"])))
    assert all(after[t.by_name[n]] == VISIBLE for n in HIDDEN)


@pytest.mark.parametrize("bad", ["last", "past_the_table", "narrower"])
def test_widening_refuses_anything_but_a_hidden_id(bad):
    """A no-op, an id off the end of the table, and NARROWING the menu (which
    would take working settings away from the operator) are all refused."""
    t = AdjustmentTable(make_elf())
    target = {"last": FEATURE_LAST, "past_the_table": len(SPECS) + 5,
              "narrower": FEATURE_LAST - 1}[bad]
    with pytest.raises(ValueError):
        widened_bytes(t, t.data, target)


def test_widening_refuses_a_build_whose_menu_was_not_fully_read():
    """James Bond 60th's shape: no verdict on the pages means no patch."""
    for only in (("list",), ("range",)):
        assert widen_plan(AdjustmentTable(make_elf(pages=only))) is None


def test_widening_refuses_when_the_feature_page_is_ambiguous():
    """Two range pages: widening one of them would be a guess at which."""
    t = AdjustmentTable(make_elf(ranges=2))
    assert len([k for k, _ids in MenuVisibility(t).pages() if k == "range"]) == 2
    assert widen_plan(t) is None


def test_widening_refuses_a_firmware_that_changed_size():
    """The patch is offset-based, so it may only be applied to the bytes it
    was planned against."""
    t = AdjustmentTable(make_elf())
    with pytest.raises(ValueError):
        widened_bytes(t, t.data + b"\x00", t.by_name["AD_TOPPER_CHEATS"])
