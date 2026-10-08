"""Which sounds the game plays with each in-game clip (plugins.stern.clip_sounds, PAD-455).

Checked on a synthetic game program built here with the shapes MODE_API.md and the PAD-455
emulator census read off Godzilla: a sound worker that bounds-checks the request against the
request table's registry, a leaf ``sound_request_play`` that tail-calls it, a ``callout`` that
makes a register before its push, swaps a request for its Japanese sibling on one path and then
tail-calls ``sound_request_play``, game code that names clips (a ``movw``/``movt`` pair, a
literal, a pointer in a table) and asks for sounds by a constant, records of a clip and its
sound, and display-effect classes whose virtuals answer a clip and its sound. The real cards
are checked where they are on this machine (skipped elsewhere, as on CI)."""

import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import clip_sounds as CS
from pinball_decryptor.plugins.stern import stock_scan as S

BASE = 0x10000
SIZE = 0x2000
TEXT_END = 0x800          # file offset where .text stops: data follows
COUNT = 10                # sound requests
FRAGMENTS = 11            # image.bin's fragment count (the sid ceiling)

W, P, C, G, H, T, X, FLAG, LOOKUP, CLIP = (0x100, 0x140, 0x180, 0x200, 0x280, 0x300, 0x340,
                                          0x3c0, 0x3d0, 0x3e0)
STR, TBL, REQ, REC, FLAGS, VTBL = 0x900, 0xa00, 0xb00, 0xd00, 0xe00, 0xe80
GET = 0x700               # the display-effect classes' getters
CLIPS = ("clipA", "clipB", "clipC", "clipD", "lonely", "clipE", "clipF", "fxOne", "fxTwo",
         "fxThree")
FX_SOUNDS = (4, 1, 9)     # what fxOne..fxThree's sound getters answer


def va(off):
    return BASE + off


def movw(rd, imm):
    return 0xE3000000 | (rd << 12) | ((imm >> 12) & 0xF) << 16 | (imm & 0xFFF)


def movt(rd, imm):
    return 0xE3400000 | (rd << 12) | ((imm >> 12) & 0xF) << 16 | (imm & 0xFFF)


def mov(rd, imm8):
    return 0xE3A00000 | (rd << 12) | imm8


def bl(src, dst):
    return 0xEB000000 | (((dst - src - 8) >> 2) & 0xFFFFFF)


def b(src, dst, cond=0xE):
    return (cond << 28) | 0x0A000000 | (((dst - src - 8) >> 2) & 0xFFFFFF)


PUSH, POP_PC, POP_LR, BX_LR = 0xE92D4010, 0xE8BD8010, 0xE8BD4010, 0xE12FFF1E


def _code(raw, off, words):
    for i, w in enumerate(words):
        struct.pack_into("<I", raw, off + 4 * i, w)


def _names():
    out, at = {}, STR
    for n in CLIPS:
        out[n] = va(at + 1)
        at += len(n) + 2
    return out


def program(table_field=2):
    """The synthetic game program and the VA of each clip's name."""
    raw = bytearray(SIZE)
    raw[0:4] = b"\x7fELF"
    raw[4], raw[5], raw[6] = 1, 1, 1
    shoff = 0x1f00
    struct.pack_into("<HHIIIIIHHHHHH", raw, 0x10, 2, 40, 1, va(0), 0x34, shoff, 0, 0x34, 32, 1,
                     40, 3, 2)
    struct.pack_into("<8I", raw, 0x34, 1, 0, va(0), 0, SIZE, SIZE, 7, 0x1000)
    # sections: null, .text (the code), .shstrtab
    names = b"\0.text\0.shstrtab\0"
    raw[0x1e00:0x1e00 + len(names)] = names
    struct.pack_into("<10I", raw, shoff + 40, 1, 1, 6, va(0x100), 0x100, TEXT_END - 0x100,
                     0, 0, 4, 0)
    struct.pack_into("<10I", raw, shoff + 80, 7, 3, 0, 0, 0x1e00, len(names), 0, 0, 1, 0)

    clip = _names()
    at = STR
    for n in CLIPS:
        raw[at + 1:at + 1 + len(n)] = n.encode()
        at += len(n) + 2

    # the request table: COUNT 20-byte records, each pointing at its sid list; the lists follow
    # the array, record 0's last (sound_requests.py), and the registry triple names the table
    lists = [[FRAGMENTS - 1 - r] for r in range(COUNT)]
    end = REQ + COUNT * 20
    starts, at = [], end
    for lst in reversed(lists):
        starts.append(at)
        for k, s in enumerate(lst):
            struct.pack_into("<I", raw, at + 4 * k, s)
        at += 4 * len(lst) + 4
    starts.reverse()
    for r in range(COUNT):
        struct.pack_into("<I", raw, REQ + r * 20 + 4 * table_field, va(starts[r]))
    reg = (at + 15) & ~15
    struct.pack_into("<III", raw, reg, va(REQ), COUNT, 20)
    count_va = va(reg + 4)

    # the sound worker: bounds-checks the request (r0) against the registry's count
    _code(raw, W, [PUSH, 0xE2504000, movw(1, count_va & 0xFFFF), movt(1, count_va >> 16),
                   0xE5911000, 0xE1540001, POP_PC])
    # sound_request_play: a leaf that bumps a serial and tail-calls the worker
    _code(raw, P, [mov(3, 0), 0xE2833001, b(P + 8, W)])
    # callout: makes a register BEFORE its push (Godzilla's reads a global there), keeps the
    # request in r4, swaps it on one path (the Japanese sibling), plays it
    _code(raw, C, [movw(3, 0x1234), PUSH, 0xE1A04000, bl(C + 12, FLAG), 0xE3500000,
                   b(C + 20, C + 32, cond=0), bl(C + 24, LOOKUP), 0xE1D040B2, 0xE1A00004,
                   POP_LR, b(C + 40, P)])
    # game code: clip A, callout 3, clip B, sound 5
    _code(raw, G, [PUSH, movw(0, clip["clipA"] & 0xFFFF), movt(0, clip["clipA"] >> 16),
                   bl(G + 12, CLIP), mov(0, 3), bl(G + 20, C),
                   movw(0, clip["clipB"] & 0xFFFF), movt(0, clip["clipB"] >> 16),
                   bl(G + 32, CLIP), movw(0, 5), bl(G + 40, P), POP_PC])
    # clip C named by a literal, then callout 7
    _code(raw, H, [PUSH, 0xE59F0014, bl(H + 8, CLIP), mov(0, 7), bl(H + 16, C), POP_PC,
                   0, 0, clip["clipC"]])
    # clip D is a pointer in a table; the code that loads the table plays sound 6
    struct.pack_into("<II", raw, TBL, clip["clipD"], 0)
    # records of a clip and the sound played with it (Godzilla's {name, request}: rampage1 -> 675)
    struct.pack_into("<4I", raw, REC, clip["clipE"], 8, clip["clipF"], 2)
    # a table of a clip and a FLAG: two clips hold the same number, so it is no sound column
    struct.pack_into("<4I", raw, FLAGS, clip["clipA"], 1, clip["clipB"], 1)
    # display effects: name() { return "fxOne"; }, flag() { return 1; }, sound() { return 4; },
    # each class's vtable [name, other, flag, sound]: the sound three slots past the name
    for k, (n, snd) in enumerate(zip(("fxOne", "fxTwo", "fxThree"), FX_SOUNDS)):
        at = GET + 0x20 * k
        _code(raw, at, [movw(0, clip[n] & 0xFFFF), movt(0, clip[n] >> 16), BX_LR,
                        mov(0, 1), BX_LR, mov(0, snd), BX_LR])
        struct.pack_into("<4I", raw, VTBL + 0x10 * k, va(at), 0, va(at + 12), va(at + 20))
    _code(raw, T, [PUSH, movw(0, va(TBL) & 0xFFFF), movt(0, va(TBL) >> 16), bl(T + 12, CLIP),
                   mov(0, 6), bl(T + 20, P), POP_PC])
    # a function that plays a fixed sound itself: an entry's caller, not an entry
    _code(raw, X, [PUSH, mov(0, 9), POP_LR, b(X + 12, P)])
    _code(raw, FLAG, [mov(0, 0), BX_LR])
    _code(raw, LOOKUP, [movw(0, va(0xc00) & 0xFFFF), movt(0, va(0xc00) >> 16), BX_LR])
    _code(raw, CLIP, [BX_LR])
    return bytes(raw), clip


def _prog():
    raw, _clip = program()
    return raw, S.Program(raw)


# ---- the request table -----------------------------------------------------------------------
def test_the_request_table_and_its_registry_are_read():
    raw, _p = _prog()
    count, lists, tva, reg = CS.request_table(raw, FRAGMENTS)
    assert count == COUNT
    assert lists == [[FRAGMENTS - 1 - r] for r in range(COUNT)]
    assert tva == va(REQ)
    assert struct.unpack_from("<III", raw, reg - BASE) == (va(REQ), COUNT, 20)


def test_no_fragment_count_reads_nothing():
    raw, _clip = program()
    out = CS.analyse(raw, CLIPS, None)
    assert out.note and not out.pairs


# ---- the sound functions -----------------------------------------------------------------------
def test_the_worker_is_found_by_the_request_table_and_its_wrappers_by_what_they_hand_on():
    raw, prog = _prog()
    count, _lists, tva, reg = CS.request_table(raw, FRAGMENTS)
    seeds = CS.table_readers(prog, tva, reg)
    assert seeds == {va(W): "request table"}
    entries = CS.sound_entries(prog, seeds, count, depth=CS.DEPTH_LOCATED, trust=False)
    # sound_request_play passes r0 straight on; callout hands it on on the path that does not
    # swap it; the function playing a fixed 9 is no wrapper
    assert set(entries) == {va(W), va(P), va(C)}
    assert all(e.reg == 0 for e in entries.values())
    assert entries[va(P)].requests == entries[va(P)].const == 3      # 5, 6 and 9
    assert entries[va(C)].requests == 2                               # 3 and 7


def test_a_function_that_overwrites_its_argument_hands_nothing_on():
    raw, prog = _prog()
    flow = CS._flow(prog, va(X))
    assert flow[va(X + 12)][0] == frozenset()         # mov r0, #9: not X's argument any more
    flow = CS._flow(prog, va(C))
    assert flow[va(C + 40)][0] == frozenset((0,))     # r4 is the request on the unswapped path
    assert flow[va(C + 12)][0] == frozenset((0,))     # before the flag call too


def test_a_function_starts_at_its_callers_target_when_a_register_is_made_before_its_push():
    raw, prog = _prog()
    assert prog.func_start(va(C + 40)) == va(C + 4)                 # the push
    assert CS._start_of(prog, va(C + 40)) == va(C)                  # what callers call
    assert CS._extent(prog, va(C))[0] > va(C + 40)


def test_every_constant_request_is_a_call():
    raw, prog = _prog()
    count, _l, tva, reg = CS.request_table(raw, FRAGMENTS)
    entries = CS.sound_entries(prog, CS.table_readers(prog, tva, reg), count,
                               depth=CS.DEPTH_LOCATED, trust=False)
    calls = CS.sound_calls(prog, entries, count)
    assert [(c.at - BASE, c.request) for c in calls] == [
        (G + 20, 3), (G + 40, 5), (H + 16, 7), (T + 20, 6), (X + 12, 9)]
    assert {c.fn - BASE for c in calls} == {G, H, T, X}


def test_a_request_table_reader_that_game_code_hands_a_request_is_a_query_not_a_seed():
    raw, prog = _prog()
    count, _l, tva, reg = CS.request_table(raw, FRAGMENTS)
    seeds = dict(CS.table_readers(prog, tva, reg))
    seeds[va(P)] = "request table"         # as if it read the table: game code hands it 5, 6
    entries = CS.sound_entries(prog, seeds, count, depth=0, trust=False)
    assert set(entries) == {va(W)}


def test_a_ports_sound_sites_seed_the_entries_when_their_words_are_this_programs(tmp_path,
                                                                                 monkeypatch):
    raw, prog = _prog()
    from pinball_decryptor.plugins.stern import mode_runtime as MR
    port = tmp_path / "synth-1.00.port"
    w = lambda o: struct.unpack_from("<I", raw, o)[0]               # noqa: E731
    port.write_text("game synth\nversion 1.00\n"
                    "site sound_worker 0x%08x 0x%08x 0x%08x\n" % (va(W), w(W), w(W + 4)) +
                    "site callout 0x%08x 0x%08x 0x%08x\n" % (va(C), w(C), w(C + 4)) +
                    "site sound_play 0x%08x 0x%08x 0x%08x\n" % (va(P), 0x12345678, w(P + 4)) +
                    "site tick 0x%08x 0x%08x 0x%08x\n" % (va(G), w(G), w(G + 4)))
    monkeypatch.setattr(MR, "port_file", lambda game, version: str(port))
    seeds, path = CS.port_seeds(prog, "synth", "1.00")
    # sound_play's words are another build's; tick is not a sound site
    assert seeds == {va(W): "sound_worker", va(C): "callout"} and path == str(port)
    out = CS.analyse(raw, CLIPS, FRAGMENTS, game="synth", version="1.00")
    assert out.origin == "port" and out.port == str(port)
    assert {k - BASE for k in out.entries} == {W, P, C}


# ---- each clip's sounds ------------------------------------------------------------------------
def test_each_clip_gets_the_sounds_its_code_asks_for_best_first():
    raw, _clip = program()
    out = CS.analyse(raw, CLIPS, FRAGMENTS)
    assert out.origin == "located" and out.count == COUNT and out.calls == 5
    got = {clip: [(p[0], p[1]) for p in ps] for clip, ps in out.pairs.items()}
    # 3 follows clip A's name; clip B's name is nearer it but comes after it
    assert got["clipA"] == [(3, "next"), (5, "function")]
    assert got["clipB"] == [(5, "next"), (3, "function")]
    assert got["clipC"] == [(7, "next")]
    # the code that only loads clip D's table is no lead (1 in 23 in the emulator)
    assert "clipD" not in got and "lonely" not in got
    assert got["clipE"] == [(8, "record")] and got["clipF"] == [(2, "record")]
    assert [got[n] for n in ("fxOne", "fxTwo", "fxThree")] == [
        [(4, "record")], [(1, "record")], [(9, "record")]]
    assert out.sids == {1: [9], 2: [8], 3: [7], 4: [6], 5: [5], 7: [3], 8: [2], 9: [1]}
    a = out.sounds_of("clipA")[0]
    assert a["request"] == 3 and a["how"] == "next" and a["gap"] == 4 and a["sids"] == [7]


def test_a_display_effects_sound_getter_is_found_three_slots_past_its_name_getter():
    raw, prog = _prog()
    refs = CM.clip_refs(prog, raw, CLIPS)
    got = CS.getters(prog, raw, refs, COUNT)
    # slot +2 answers 1 for all three classes: a flag, not their sounds
    assert {c: [v for v, _f in fs] for c, fs in got.items()} == {
        "fxOne": [4], "fxTwo": [1], "fxThree": [9]}
    assert got["fxOne"][0][1] == va(GET + 20)
    # fewer than three classes say nothing
    two = {c: rs for c, rs in refs.items() if c != "fxThree"}
    assert CS.getters(prog, raw, two, COUNT) == {}


def test_a_sound_named_after_a_clip_is_its_sound():
    menu = {12: "SE GZ FX DE BRIDGEATTACK 1", 13: "SE GZ VO GAME BRIDGEATTACK 1",
            14: "SE GZ FX DE BRIDGEATTACK 10", 15: "SE GZ FX MATCH",
            16: "SE JAWS BOUNTYHUNT LOOP 1"}
    # "match" is too short to trust; "attack_1" is no whole word of "BRIDGEATTACK 1"
    assert CS.named(["BridgeAttack_1", "match", "bountyhunt_loop_1", "attack_1"], menu) == {
        "BridgeAttack_1": [12, 13], "bountyhunt_loop_1": [16]}


def test_a_clips_record_names_the_sound_played_with_it_and_a_flag_column_names_none():
    raw, prog = _prog()
    refs = CM.clip_refs(prog, raw, CLIPS)
    assert CS.records(prog, refs, COUNT) == {"clipE": [(8, va(REC))], "clipF": [(2, va(REC + 8))]}
    # a pointer beside the name is no request
    raw2 = bytearray(raw)
    struct.pack_into("<I", raw2, REC + 4, va(STR))
    prog2 = S.Program(bytes(raw2))
    assert CS.records(prog2, CM.clip_refs(prog2, bytes(raw2), CLIPS), COUNT) == {
        "clipF": [(2, va(REC + 8))]}


def test_the_nearest_clip_before_a_call_wins_over_a_nearer_one_after_it():
    places = [(0x100, "A"), (0x120, "B")]
    assert CS._nearest(0x114, places) == "A"
    assert CS._nearest(0x0f0, places) == "A"                 # nothing before: the first after
    assert CS._nearest(0x100 + 4 * (CS.NEAR + 1), [(0x100, "A")]) is None


def test_a_reading_survives_its_cache():
    raw, _clip = program()
    out = CS.analyse(raw, CLIPS, FRAGMENTS)
    back = CS.SoundReading.from_json(out.to_json())
    assert back == out


# ---- a request's sounds ------------------------------------------------------------------------
def test_the_request_sidecar_round_trips_and_names_the_projects_files(tmp_path):
    lists = [[3], [4, 5], []]
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), lists, {0: [12], 1: [13, 14]},
                      {1: "SE FX ROAR"})
    assert CS.read_requests(str(tmp_path)) == {0: {"idx": [12], "name": ""},
                                               1: {"idx": [13, 14], "name": "SE FX ROAR"},
                                               2: {"idx": [], "name": ""}}
    audio = tmp_path / "audio"
    audio.mkdir()
    for n in ("idx0012.wav", "idx0013 - SE FX ROAR.wav", "00m01s200 - idx0014.wav", "notes.txt"):
        (audio / n).write_bytes(b"")
    assert CS.audio_files(str(tmp_path)) == {12: "audio/idx0012.wav",
                                             13: "audio/idx0013 - SE FX ROAR.wav",
                                             14: "audio/00m01s200 - idx0014.wav"}


def test_requests_resolve_to_the_records_their_sound_ids_name(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN
    monkeypatch.setattr(SN, "_find_resolver", lambda emu, fw=None: (0x1000, 0x2000))
    monkeypatch.setattr(SN, "_try_resolve", lambda emu, addr, out, sid: b"d%d" % sid)
    monkeypatch.setattr(SN, "_primary_idx", lambda desc, key0: {b"d7": 70, b"d8": 80}.get(desc))
    params = [{"idx": 70, "key0": 1}]
    assert CS.resolve_requests(None, params, [[7], [8, 7, 9], [9]]) == {0: [70], 1: [80, 70]}
    assert CS.resolve_requests(None, [{"idx": 1}], [[7]]) == {}


def test_the_fragment_count_is_read_off_the_cards_image_bin_header():
    head = bytearray(0x100)
    struct.pack_into("<III", head, 0, 0xb0, 0, 0)
    struct.pack_into("<II", head, 0x5c, 578, 549)

    class Reader:
        def read_range(self, node, off, n):
            assert node == {"size": 1 << 20} and off == 0
            return bytes(head[:n])

    class Img:
        def _reader(self, part):
            return Reader()

        def _resolve(self, reader, path):
            return (12, {"size": 1 << 20}) if path == "/led_zeppelin_le/image.bin" else None

    assert CS.card_fragments(Img(), 2, "led_zeppelin_le") == 578
    assert CS.card_fragments(Img(), 2, "other") is None


# ---- the Video tab ---------------------------------------------------------------------------
INTRO, BOSS = "video/intro.mp4", "video/boss.mp4"
GIGAN = "cmode_battle_vs_gigan"


def test_the_video_tab_names_the_sounds_a_clips_code_plays(tmp_path, monkeypatch):
    from pinball_decryptor.webui import video_modes as VM
    from tests.test_webui_video import _project, _scan, _wait
    from tests.webui_harness import web_app
    proj = _project(tmp_path, names=(INTRO, BOSS))
    card = tmp_path / "godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw"
    card.write_bytes(b"\0" * 16)
    (proj / ".extract_source.json").write_text(json.dumps(
        {"input_path": str(card), "input_name": card.name}), encoding="utf-8")
    sounds = CS.SoundReading(
        origin="port", count=10, calls=3,
        pairs={"intro": [[5, "record", -1, 0x1010], [3, "next", 4, 0x1000],
                         [8, "name", -1, 0], [7, "function", 90, 0x2000]],
               "boss": [[9, "function", 50, 0x3000]]},
        names={3: "SE GZ VO ROAR", 7: "MUSIC: BATTLE", 8: "SE GZ FX DE INTRO"},
        sids={3: [30], 5: [50], 7: [70], 8: [80], 9: [90]})
    reading = CM.Reading(labels={GIGAN: "Battle vs Gigan"},
                         refs={"intro": [CM.Ref("movw_a32", [1, 2], 1, GIGAN, "own")]})

    def fake(card_path, rows, cancel=None):
        return CM.CardClips(card=card_path, game="godzilla_pro", version="1.16.0",
                            reading=reading, name_of={INTRO: "intro", BOSS: "boss"},
                            bank_of={"intro": ["/g/b", "2.asset/0.asset"],
                                     "boss": ["/g/b", "2.asset/1.asset"]},
                            sounds=sounds.to_json())
    monkeypatch.setattr(CM, "read_card", fake)

    def shown(w, rel):
        w.call("video.select", rel)
        return _wait(w, lambda st: st["modes"]["ready"] and (st.get("preview") or {}).get(
            "rel") == rel and ((st["preview"].get("sounds") or {}).get("rel") == rel
                               or rel == BOSS))["preview"]["sounds"]

    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        snd = shown(w, INTRO)
        assert snd["head"] == VM.SOUNDS_HEAD
        # the kinds the emulator proved, best first; "function" (7 in 29) is not shown
        assert [(i["text"], i["how"]) for i in snd["items"]] == [
            ("sound request 5", "kept with the clip"), ("SE GZ VO ROAR", "asked for right after it"),
            ("SE GZ FX DE INTRO", "named after it")]
        assert snd["items"][1]["tip"]["lines"] == ["Sound request 3", "Sound Test: SE GZ VO ROAR"]
        assert snd["more"] == ""
        assert snd["foot"] == VM.SOUNDS_FOOT              # no request map from the extract yet
        assert shown(w, BOSS) is None                      # only a "function" lead
        # an extract that wrote the request map: the files themselves
        CS.write_requests(str(proj / CS.REQUESTS_TSV), [[]] * 10, {3: [12], 5: [13, 14]},
                          {3: "SE GZ VO ROAR"})
        (proj / "audio").mkdir()
        for n in ("idx0012 - SE GZ VO ROAR.wav", "idx0013.wav", "idx0014.wav"):
            (proj / "audio" / n).write_bytes(b"")
        _scan(w, proj)
        snd = shown(w, INTRO)
        assert [i["text"] for i in snd["items"]] == ["idx0013.wav (+1)",
                                                     "idx0012 - SE GZ VO ROAR.wav",
                                                     "SE GZ FX DE INTRO"]
        assert snd["items"][0]["tip"]["lines"] == ["Sound request 5", "idx0013.wav",
                                                   "idx0014.wav"]
        assert snd["foot"] == ""


def test_the_page_draws_the_sounds_part_of_the_callout():
    js = open(os.path.join(os.path.dirname(__file__), os.pardir, "pinball_decryptor", "webui",
                           "static", "js", "tabs", "video.js"), encoding="utf-8").read()
    for bit in ("pv.sounds.rel === currentRel", "vid-sound-list", "pv.sounds.more",
                "pv.sounds.foot"):
        assert bit in js, bit


def test_a_card_reading_keeps_its_sounds_in_its_cache():
    clips = CM.CardClips(card="c", sounds=CS.SoundReading(origin="located", count=3,
                                                          pairs={"a": [[1, "next", 2, 3]]})
                         .to_json())
    back = CM.CardClips.from_json(json.loads(json.dumps(clips.to_json())))
    assert back.sound_reading.pairs == {"a": [[1, "next", 2, 3]]}
    assert back.sound_reading.origin == "located"


def test_a_sound_reading_that_fails_never_takes_the_modes_with_it(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad program")
    monkeypatch.setattr(CS, "analyse", boom)
    got = CM._sounds(b"", [], 1, CM.CardClips(), {})
    assert got["note"] == "the sounds could not be read (bad program)"


# ---- the real cards (David's machine) ----------------------------------------------------------
CARDS = os.environ.get("PAD444_CARDS", r"D:\Pinball\images\Stern\spike2")
REAL = [os.path.join(CARDS, n) for n in ("godzilla_pro-1_16_0_spike2.Release.8G.sdcard.raw",
                                         "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")]


def _real(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern import video_bank as VB
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, version, part = card_title(card)
    with CardImage(card) as img:
        elf = img.preview(part, "/%s/game" % game, cap=256 << 20)
        bank = img.preview(part, "/%s/assets/lcd/auto_loaded/%s/scene.radium"
                           % (game, VB.GODZILLA_PRO_BANK), cap=64 << 20)
        fragments = CS.card_fragments(img, part, game)
    return elf, [c.name for c in VB.parse(bank).library.entries], fragments, game, version


@pytest.mark.slow
@pytest.mark.parametrize("card", REAL, ids=["pro116", "le116"])
def test_a_real_godzilla_program_pairs_clips_with_sounds(card):
    """The request table alone finds every sound function the build's port names (callout
    makes a register before its push) and the same calls, and the clips get the kinds the
    emulator census proved on these builds (docs/architecture/stern.md)."""
    elf, names, fragments, game, version = _real(card)
    port = CS.analyse(elf, names, fragments, game=game, version=version)
    assert port.origin == "port", port.note
    assert port.count > 1000 and port.calls > 100
    located = CS.analyse(elf, names, fragments)
    assert located.origin == "located", located.note
    named = {va: e[0] for va, e in port.entries.items() if " > " not in e[0]}   # the port's
    missed = {"0x%x" % va: n for va, n in named.items() if va not in located.entries}
    assert not missed, "the request table did not lead to %r" % missed
    assert located.calls == port.calls and located.pairs == port.pairs
    got = {how: {c for c, ps in port.pairs.items() for p in ps if p[1] == how}
           for how in CS.HOWS}
    # census-proven pairs (emulator, Premium/LE 1.16; the Pro build's in-game bank names them too)
    assert ("rampage1", 675) in {(c, p[0]) for c, ps in port.pairs.items() for p in ps}
    assert [p[:2] for p in port.pairs["adv_fighter2"]][0] == [538, "record"]   # its sound getter
    assert [p[:2] for p in port.pairs["BridgeAttack_1"]] == [[785, "name"]]
    assert len(got["record"]) > 100 and len(got["next"]) > 25 and len(got["name"]) > 150
