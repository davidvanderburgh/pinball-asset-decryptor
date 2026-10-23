"""PAD-635: the Audio tab says, for each sound, which of the game code's sound requests play it.

Extract's ``sound_requests.tsv`` now records the sounds a request plays as LATER parts of a
multi-part descriptor too (on Godzilla Pro 1.16 six records are only ever a later part, so the
first-part map alone called them unplayed). The Audio tab's Requests column counts them, its
tip names them, a sound no request plays reads None, and an extract made before the column
shows no Requests column rather than a wrong None."""

import os

from pinball_decryptor.plugins.stern import clip_sounds as CS
from tests.test_webui_audio import _open, _project
from tests.webui_harness import web_app

RELS = ("audio/idx0001 - Jackpot.wav", "audio/idx0002.wav", "audio/idx0003 - music loop.wav")


def _row(w, rel):
    return next(r for r in w.state("audio")["rows"] if r["k"] == rel)


# ---- the request map -------------------------------------------------------------------------
def test_a_multi_part_sound_id_plays_every_part(monkeypatch):
    from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN
    monkeypatch.setattr(SN, "_find_resolver", lambda emu, fw=None: (0x1000, 0x2000))
    monkeypatch.setattr(SN, "_try_resolve", lambda emu, addr, out, sid: b"d%d" % sid)
    parts = {b"d7": [70, 71], b"d8": [80], b"d9": [90, 70]}
    monkeypatch.setattr(SN, "_part_idxs", lambda desc, key0: parts.get(desc, []))
    params = [{"idx": 70, "key0": 1}]
    also = {}
    assert CS.resolve_requests(None, params, [[7], [8, 9], [6]], also=also) == {0: [70],
                                                                              1: [80, 90]}
    assert also == {0: [71], 1: [70]}
    # without *also* the answer is the first parts alone, as before
    assert CS.resolve_requests(None, params, [[7], [8, 9], [6]]) == {0: [70], 1: [80, 90]}


def test_part_idxs_reads_every_op11_marker():
    from pinball_decryptor.plugins.stern.spike2 import sfx_names as SN
    op = SN._OP11
    desc = (b"\x05" + b"\x00" * 9 + op + (11).to_bytes(4, "little") + b"\x00" * 4
            + b"\x01\x02" + op + (22).to_bytes(4, "little") + b"\x00" * 4
            + op + (99).to_bytes(4, "little") + b"\x00" * 4
            + op + (11).to_bytes(4, "little") + b"\x00" * 4
            # Led Zeppelin's marker with its parameter byte set
            + b"\x0b\x00\x04\x00" + (33).to_bytes(4, "little") + b"\x00" * 4
            # not a marker: the byte after the opcode is not 0
            + b"\x0b\x01\x00\x00" + (44).to_bytes(4, "little") + b"\x00" * 4)
    key0 = {11: 1, 22: 2, 33: 3, 44: 4}
    assert SN._part_idxs(desc, key0) == [1, 2, 3]
    assert SN._primary_idx(desc, key0) == 1


def test_sound_uses_counts_first_and_later_parts(tmp_path):
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), [[3], [4, 5], [6], []],
                      {0: [1], 1: [2, 1]}, {1: "SE FX ROAR"}, also={2: [3], 1: [3]})
    req = CS.read_requests(str(tmp_path))
    assert req[1] == {"idx": [2, 1], "name": "SE FX ROAR", "also": [3]}
    assert req[3] == {"idx": [], "name": "", "also": []}
    assert CS.sound_uses(str(tmp_path)) == {1: [(0, ""), (1, "SE FX ROAR")],
                                            2: [(1, "SE FX ROAR")],
                                            3: [(1, "SE FX ROAR"), (2, "")]}


def test_an_extract_before_the_later_parts_says_nothing(tmp_path):
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), [[3]], {0: [1]}, {})
    assert CS.read_requests(str(tmp_path))[0]["also"] is None
    assert CS.sound_uses(str(tmp_path)) is None
    # nor does a map the resolver filled with nothing, or no map at all
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), [[3]], {}, {}, also={})
    assert CS.sound_uses(str(tmp_path)) is None
    assert CS.sound_uses(str(tmp_path / "none")) is None


def test_the_stern_plugin_answers_for_the_decoded_sounds_only(tmp_path):
    from pinball_decryptor.core.registry import get_manufacturer
    mfr = get_manufacturer("stern")
    rels = ["audio/idx0001 - Jackpot.wav", "audio/idx0002.wav", "music/Song.wav",
            "audio/sub/idx0001.wav"]
    assert mfr.sound_request_uses(str(tmp_path), rels) is None
    CS.write_requests(str(tmp_path / CS.REQUESTS_TSV), [[3]], {0: [1]}, {}, also={})
    assert mfr.sound_request_uses(str(tmp_path), rels) == {
        "audio/idx0001 - Jackpot.wav": [(0, "")], "audio/idx0002.wav": []}


def test_every_reader_follows_a_long_list_to_its_end():
    """16 of 49 titles have a request whose list runs past 256 sids (Star Wars 1.31: 927),
    where every reader used to stop (one at 64): Deadpool read 2116 of its 8175 sounds as
    requested by nothing, and a longer replacement's bank sid missed the list's tail."""
    import struct
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    from pinball_decryptor.plugins.stern import mode_write as MW
    from tests.test_stern_sound_requests import _lists, make_elf
    frags = 2048
    lists = _lists(200, frags)
    lists[1] = list(range(1, 928))
    fw, _reg = make_elf(lists)
    head = bytearray(0x100)
    struct.pack_into("<III", head, 0, 0xb0, 0, 0)
    struct.pack_into("<II", head, 0x5c, frags, frags - 10)
    count, got, _t, _r = CS.request_table(fw, frags)
    assert count == 200 and got[1] == lists[1] and got[0] == lists[0]
    slots = BB.request_list_slots(fw, bytes(head))
    assert 927 in slots and 900 in slots
    assert MS.request_sids(fw, frags, [1])[1] == lists[1]
    assert MW.request_sids(fw, bytes(head), 1) == lists[1]


# ---- the Audio tab ---------------------------------------------------------------------------
def test_the_audio_tab_shows_which_requests_play_each_sound(tmp_path):
    proj = _project(tmp_path)
    lists = [[1]] * 20
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), lists,
                      {4: [1], 9: [1]}, {4: "SE GZ VO JACKPOT"}, also={12: [3]})
    out = str(tmp_path / "audio_slots.csv")
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        s = w.state("audio")
        assert s["req_cap"] is True and "sound requests" in s["req_tip"]
        assert s["req_note"] == ""
        jackpot, plain, loop = (_row(w, r) for r in RELS)
        assert jackpot["rq"] == 2
        assert jackpot["rq_tip"] == ["Played by 2 of the game code's sound requests:",
                                     "#4  SE GZ VO JACKPOT", "#9"]
        assert plain["rq"] == 0 and "never asks for it" in plain["rq_tip"][0]
        assert loop["rq"] == 1                            # a later part counts
        assert loop["rq_tip"] == ["Played by one of the game code's sound requests:", "#12"]
        # sorting by it: the most-played first, then the other way, None first
        w.call("audio.sort", "rq")
        assert [r["k"] for r in w.state("audio")["rows"]] == [RELS[0], RELS[2], RELS[1]]
        w.call("audio.sort", "rq")
        assert [r["k"] for r in w.state("audio")["rows"]] == [RELS[1], RELS[2], RELS[0]]
        w.answers.append(out)
        assert w.call("audio.export_csv") is True
        text = open(out, encoding="utf-8-sig").read().splitlines()
        assert text[0].endswith(",Level dB,Game Sound Requests")
        assert text[1].endswith(",#4 #9") and text[2].endswith(",none")
        assert text[3].endswith(",#12")


def test_no_request_map_no_column(tmp_path):
    proj = _project(tmp_path)
    # an extract made before the later parts were recorded
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]] * 5, {4: [1]}, {})
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        assert w.state("audio")["req_cap"] is False
        assert "rq" not in _row(w, RELS[1])
        # it says why, and what to do (PAD-635: a tester saw no column and no word)
        assert w.state("audio")["req_note"] == CS.WHY_EXTRACT_AGAIN
        # a sort on it left over falls back to the name
        w.call("audio.sort", "rq")
        w.call("audio.scan")
        _open(w, proj)
        assert w.state("audio")["sort"]["key"] == "#0"


def test_other_makers_have_no_column(tmp_path):
    proj = _project(tmp_path)
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]], {0: [1]}, {}, also={})
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, proj)
        assert w.state("audio")["req_cap"] is False
        assert w.state("audio")["req_note"] == ""


def test_why_there_is_no_column(tmp_path):
    proj = _project(tmp_path)
    # no map at all: an extract made before v1.217.0
    assert CS.sound_uses_why(proj) == CS.WHY_EXTRACT_AGAIN
    # a map without the later parts
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]], {0: [1]}, {})
    assert CS.sound_uses_why(proj) == CS.WHY_EXTRACT_AGAIN
    # a map the resolver filled with nothing
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]], {}, {}, also={})
    assert CS.sound_uses_why(proj) == CS.WHY_NOT_READ
    # a whole map: the column is there, nothing to say
    CS.write_requests(os.path.join(proj, CS.REQUESTS_TSV), [[1]], {0: [1]}, {}, also={})
    assert CS.sound_uses_why(proj) == ""
    # a folder with no decoded sounds is not one the column is for
    assert CS.sound_uses_why(str(tmp_path / "empty")) == ""
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        os.remove(os.path.join(proj, CS.REQUESTS_TSV))
        _open(w, proj)
        assert w.state("audio")["req_note"] == CS.WHY_EXTRACT_AGAIN


def test_a_map_naming_nothing_is_never_cached(tmp_path, monkeypatch):
    """Round 2: a resolve that named no sound was cached, and every later extract of the card
    reused it, so its Audio tab never had a Requests column (Star Wars 1.31, X-Men 0.98 and
    Venom 1.07 on this PC). Nothing named is not cached, and such a cache is resolved again."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import info
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(E, "_params_cache_dir", lambda: str(cache_dir))
    monkeypatch.setattr(E, "_fingerprint", lambda g, i: "a" * 32)
    monkeypatch.setattr(info, "container_counts", lambda head: (10, 10))
    monkeypatch.setattr(CS, "request_table", lambda fw, frags: (2, [[1], [2]], None, None))
    monkeypatch.setattr(CS, "menu_names", lambda fw, lists: {})
    answers = [{}, {0: [5]}]
    calls = []

    def resolve(emu, params, lists, fw, also=None, ceiling=None):
        calls.append(1)
        return answers[len(calls) - 1]
    monkeypatch.setattr(CS, "resolve_requests", resolve)
    gr, img = tmp_path / "game", tmp_path / "image.bin"
    gr.write_bytes(b"\0" * 64)
    img.write_bytes(b"\0" * 256)
    out = tmp_path / "proj"
    out.mkdir()
    cache = E._requests_cache_path("a" * 32)
    assert E._write_sound_requests(None, str(gr), str(img), [], str(out), None) == 0
    assert not os.path.exists(cache)
    # an empty map cached by an earlier version is resolved again too
    with open(cache, "w", encoding="utf-8") as f:
        f.write("{}")
    assert E._write_sound_requests(None, str(gr), str(img), [], str(out), None) == 1
    assert len(calls) == 2
    assert CS.sound_uses(str(out)) == {5: [(0, "")]}
    # and the good map is the one kept
    assert E._write_sound_requests(None, str(gr), str(img), [], str(out), None) == 1
    assert len(calls) == 2
