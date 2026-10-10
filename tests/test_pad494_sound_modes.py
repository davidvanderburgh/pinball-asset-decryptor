"""PAD-494 (a tester's request): MUSIC MODES - one card, several sets of sounds, the operator's
MUSIC MODE picks the set.

The project's record (sound_modes), the runtime's table (sounds.cfg, read by pad_mode_runtime.c
"music modes"), and the engine's pure parts: the record a mode's file goes into, the loudness it
matches, and the descriptor the runtime hands the game. The descriptor rewrite is pinned to the
bytes the emulator played (Godzilla LE 1.16, spike 1: mode 2 of sound id 2578, the 1954 main
title's loop, naming idx4's record - match 0.969 against the capture)."""

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo

BOC = "audio/idx2095 - music - Blue \u00d6yster Cult - Godzilla.wav"
MASK = 0xE0001FFF                     # Godzilla LE 1.16's key mask


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_modes_two_to_eight_and_their_names():
    m = SMo.clean({"names": ["Standard", "Orchestral", "Heisei", "Extra"] + ["n%d" % i for i in range(5, 11)],
                   "slots": {BOC: {"2": "C:/o.wav", "1": "C:/x.wav", "9": "C:/y.wav", "3": "",
                                   "8": "C:/o.wav"},
                             "audio/idx0004 - music.wav": {}, 7: {"2": "z"}}})
    assert SMo.MAX_MODES == 8 and SMo.SHOWN_MODES == 4
    assert m.names == ["Standard", "Orchestral", "Heisei", "Extra", "n5", "n6", "n7", "n8"]
    assert m.slots == {BOC: {2: "C:/o.wav", 8: "C:/o.wav"}}       # one file in two modes
    assert m.count == 8
    assert m.menu_names()[:2] == ["Standard", "Orchestral"]
    assert m.files() == [(BOC, 2, "C:/o.wav"), (BOC, 8, "C:/o.wav")]
    assert SMo.to_json(m) == {"names": ["Standard", "Orchestral", "Heisei", "Extra", "n5", "n6", "n7", "n8"],
                              "slots": {BOC: {"2": "C:/o.wav", "8": "C:/o.wav"}}}


def test_a_mode_without_a_name_is_standard_then_custom_a_b_and_no_files_is_no_modes():
    """The tester's own words: "Standard, Custom A, Custom B, etc"."""
    m = SMo.clean({"names": ["", "  Orchestral  "], "slots": {BOC: {"3": "a.wav"}}})
    assert m.count == 3
    assert m.menu_names() == ["Standard", "Orchestral", "Custom B"]
    assert [SMo.default_name(i) for i in range(1, 9)] == [
        "Standard", "Custom A", "Custom B", "Custom C", "Custom D", "Custom E", "Custom F", "Custom G"]
    assert SMo.clean({"names": ["A", "B"]}).count == 0
    assert SMo.clean(None).count == 0
    assert SMo.to_json(SMo.Modes()) is None


def test_a_slot_is_known_by_its_sound_bank_record():
    assert SMo.slot_idx(BOC) == 2095
    assert SMo.slot_idx("audio/idx0004.wav") == 4
    assert SMo.slot_idx("audio\\idx0974 - music.wav") == 974
    assert SMo.slot_idx("music_cat01_0003.wav") is None


def test_the_runtime_table_is_what_pad_mode_runtime_reads():
    text = SMo.cfg_text(0x7A4E78, 3, [(2, 2578, bytes.fromhex("0501019944")), (3, 2562, b"\x05\x01")],
                        only=True)
    lines = text.splitlines()
    assert lines[0].startswith("#")
    assert lines[1:] == ["only", "setting\t0x007a4e78\t3", "sound\t2\t2578\t0501019944",
                         "sound\t3\t2562\t0501"]
    assert "only" not in SMo.cfg_text(1, 2, [], only=False).splitlines()


def test_only_the_titles_it_was_proven_on_are_offered(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    le = MP.profile("godzilla_le_1_16")
    assert SMo.title_refusal(le) == ""
    assert SMo.title_refusal(None) == SMo.NO_TITLE
    other = MP.profile("godzilla_pro_1_15")
    assert SMo.title_refusal(other) == SMo.NOT_PROVEN % other.label
    monkeypatch.setattr(SMo, "project_title", lambda project, probe=False: le)
    why, slots = SMo.offer("proj", [BOC, "music_cat01_0003.wav"])
    assert why == "" and slots == {BOC: "", "music_cat01_0003.wav": SMo.NOT_SOUND}
    monkeypatch.setenv(SMo.GATE_ENV, "0")
    assert SMo.offer("proj", [BOC])[0].startswith("%s=0" % SMo.GATE_ENV)


# ---- the descriptor the runtime hands the game ----------------------------------------------------
D2578 = bytes.fromhex("0501016e4a050001000002000307000b0000009ef94b2c17645a7811010300096e7b6158e294bef6570e10"
                      "e21037cd2029966fd533cc2fac585ffc45be8a1800a4a343aa6cf0744564fddc3042d1364c")
#: what spike 1 put in sounds.cfg for mode 2 of sid 2578, and the game played idx4 through it
SPIKE1 = bytes.fromhex("0501019944050001000002000307000b0000006f31228f15605a1811010300096e7b6158e294bef6570e10"
                       "e21037cd2029966fd533cc2fac585ffc45be8a1800a4a343aa6cf0744564fddc3042d1364c")
D2532 = bytes.fromhex("050101d02b0f000100000200010608010000000b0000002db27ae7b75814451101080200000007000b000000"
                      "b6f2c84c0766e81f1101030066400023f4221ab23b8c03f34095588850ab547d7e2e605b")


def _key(payload_hex, sid):
    return E._play_key(bytes.fromhex(payload_hex), sid, MASK)


def test_a_one_sound_descriptor_names_the_modes_record_and_declares_its_length():
    slot, host = _key("9ef94b2c17645a78", 2578), _key("6f31228f15c03a10", 2547)
    got = E._mode_descriptor(D2578, 2578, MASK, slot, host, 0x054499, 0x054A6E)
    assert got == SPIKE1
    # the loop script and every byte after the payload are the game's own
    assert got[27:] == D2578[27:]


def test_a_sequence_moves_its_length_by_the_difference_and_keeps_its_intro():
    intro, loop = _key("2db27ae7b7581445", 2532), _key("b6f2c84c0766e81f", 2532)
    host = _key("6f31228f15c03a10", 2547)
    got = E._mode_descriptor(D2532, 2532, MASK, loop, host, 1000, 400)
    pays = E._op11_payloads(got)
    assert len(pays) == 2
    assert E._play_key(pays[0][1], 2532, MASK) == intro        # the intro still plays
    assert E._play_key(pays[1][1], 2532, MASK) == host         # the loop is the mode's
    old = int.from_bytes(D2532[3:6], "little")
    assert int.from_bytes(got[3:6], "little") == old + 600


def test_a_key_the_descriptor_cannot_carry_is_refused():
    slot = _key("9ef94b2c17645a78", 2578)
    bad = bytes.fromhex("6f31228f15c03a10")[:4] + (0x1F000000).to_bytes(4, "little")
    assert E._mode_descriptor(D2578, 2578, MASK, slot, bad, 1, 1) is None


# ---- the record a file goes into, and its loudness -------------------------------------------------
def _p(idx, length, chan=2, **kw):
    return dict({"idx": idx, "length": length, "chan": chan, "findkey": bytes([idx % 256]) * 8}, **kw)


def test_a_host_is_the_longest_free_record_of_the_slots_channels_no_longer_than_the_file():
    slot = _p(2095, 9_000_000)
    params = [slot, _p(1, 100), _p(2, 2_000_000), _p(3, 2_400_000, chan=1), _p(4, 2_300_000),
              _p(5, 2_350_000, grown=True), _p(6, 5_000_000), _p(7, 2_200_000)]
    assert E._sound_mode_host(params, slot, 2_440_000, {}, set()) == 4
    assert E._sound_mode_host(params, slot, 2_440_000, {4: "x.wav"}, set()) == 7
    assert E._sound_mode_host(params, slot, 2_440_000, {}, {4, 7, 2, 1}) == 6   # else the shortest longer
    assert E._sound_mode_host(params, slot, 50, {}, {6, 4, 7, 2}) == 1
    assert E._sound_mode_host([slot], slot, 50, {}, set()) is None        # never the slot itself


def test_a_hosted_file_from_an_older_record_takes_its_slots_offset():
    """A record from before mode files had their own loudness (``db`` None): as those builds did."""
    used = [{"host": 2225, "slot": 974, "mode": 2, "db": None},
            {"host": 285, "slot": 974, "mode": 3, "db": None}]
    assert E._sm_level_refs(used) == {2225: 974, 285: 974}
    assert E._sm_hosts(used) == {2225, 285}
    assert E._sm_gains({974: 3.0, 5: -2.0}, used) == {974: 3.0, 5: -2.0, 2225: 3.0, 285: 3.0}
    assert E._sm_gains({5: 1.0}, used) == {5: 1.0}
    assert E._sm_gains({5: 1.0}, []) == {5: 1.0}


def test_a_hosted_file_takes_its_own_offset_never_its_slots_or_its_hosts(monkeypatch):
    """"Are we able to make the individual loudness setting specific to mode files": the slot's
    offset is its own sound's; a host's own stock offset is that stock sound's."""
    monkeypatch.setattr(E, "_slot_gain_db", lambda db: 100.0 + db)       # the build-wide part
    used = [{"host": 2225, "slot": 974, "mode": 2, "db": 0},
            {"host": 285, "slot": 974, "mode": 3, "db": -4}]
    assert E._sm_gains({974: 106.0, 2225: 102.0}, used) == {974: 106.0, 285: 96.0}


def test_mode_file_levels_are_kept_per_slot_and_mode():
    m = SMo.clean({"slots": {BOC: {"2": "a.wav", "3": "b.wav"}},
                   "levels": {BOC: {"2": "4.4", "3": 0, "5": 3, "x": 2}, "audio/idx0004.wav": {"2": 1}}})
    assert m.levels == {BOC: {2: 4}}
    assert (m.level(BOC, 2), m.level(BOC, 3), m.level("audio/idx0004.wav", 2)) == (4, 0, 0)
    assert SMo.to_json(m)["levels"] == {BOC: {"2": 4}}
    assert SMo.clean({"slots": {BOC: {"2": "a.wav"}}, "levels": {BOC: {"2": 40}}}).level(BOC, 2) == 12
    older = SMo.clean({"slots": {BOC: {"2": "a.wav"}}})
    assert older.levels is None and older.level(BOC, 2) is None
    assert "levels" not in SMo.to_json(older)


def test_the_grown_cache_key_tells_a_hosted_file_by_its_slot(tmp_path):
    wav = tmp_path / "m.wav"
    wav.write_bytes(b"RIFF....WAVE")
    a = E._grown_cache_sounds(str(tmp_path), {2225: str(wav)}, {2225: (1, 2)}, {}, (),
                              [{"idx": 2225, "level_ref": 974, "mode": 2}])
    b = E._grown_cache_sounds(str(tmp_path), {2225: str(wav)}, {2225: (1, 2)}, {}, (),
                              [{"idx": 2225, "level_ref": 4, "mode": 2}])
    assert a != b and a[0][1] == ("slot", 974, 2)


@pytest.mark.parametrize("ref,expect_default", [(None, True), (12345, True)])
def test_a_sound_with_no_known_reference_matches_its_own(ref, expect_default):
    assert (E._level_ref_render(None, {}, {"chan": 2}, ref, None) is E._LEVEL_REF_UNSET) is expect_default


#: sid 2536's window as the resolver reads it: its own descriptor is 28 bytes, then sid 2537's
D2536 = bytes.fromhex("050101d557020001000002000b0b00000071f07b2ea55029511101000501016e4a05000100000200030b"
                      "0000009ef94b2c17c48075110100f629f04e6ab670321e884dc26910c21344f4ac554b766f36")


def test_a_payload_past_a_descriptors_end_is_the_next_ones():
    """The card's first build of this gave sid 2536 a mode descriptor: the main title's payload in
    its window is sid 2537's (28 bytes on), and 2536's own length would have moved."""
    slot, host = _key("9ef94b2c17645a78", 2578), _key("6f31228f15c03a10", 2547)
    assert E._mode_descriptor(D2536, 2536, MASK, slot, host, 1000, 400, extent=28) is None
    assert E._mode_descriptor(D2536, 2536, MASK, slot, host, 1000, 400) is not None
    assert E._descriptor_extents([1649592159, 1649592187, 1649593595], 0x50) == {
        1649592159: 28, 1649592187: 0x50, 1649593595: 0x50}


# ---- one file in several modes, and how long a file may play --------------------------------------
def _wav(path, seconds, rate=44100, chans=2):
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * chans * int(seconds * rate))
    return str(path)


def test_a_cut_copy_keeps_the_first_card_samples_in_the_files_own_rate(tmp_path):
    import wave
    src = _wav(tmp_path / "long.wav", 2.0, rate=48000)
    out = SMo.cut(src, 44100)                             # one second of card samples
    assert out != src and out.endswith(".cut44100.wav")
    with wave.open(out, "rb") as r:
        assert (r.getframerate(), r.getnchannels(), r.getnframes()) == (48000, 2, 48000)
    assert SMo.cut(src, 44100) == out                      # kept while it is there
    with wave.open(SMo.cut(src, 10 * 44100), "rb") as r:  # never longer than the file
        assert r.getnframes() == 96000


def _grow(tmp_path, monkeypatch, files, longer_ok=True, levels=None):
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    made = {src: _wav(tmp_path / ("conv_" + src), secs) for src, secs in files.items()}
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: made[src])
    slot_len = 44100 + BLOCK                               # the slot's own sound: 1 s
    params = [_p(2095, slot_len), _p(10, 3 * 44100 + BLOCK), _p(11, 3 * 44100 + BLOCK),
              _p(12, 3 * 44100 + BLOCK)]
    raw = {"slots": {BOC: {"2": "a.wav", "3": "b.wav", "4": "a.wav"}}}
    if levels is not None:
        raw["levels"] = {BOC: levels}
    m = SMo.clean(raw)
    logs = []
    edits, grows, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m,
                                             lambda t, lvl="info": logs.append(t),
                                             longer_ok=longer_ok, longer_why="off in Settings")
    return edits, grows, used, logs


def test_one_file_in_several_modes_goes_on_the_card_once(tmp_path, monkeypatch):
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, {"a.wav": 2.0, "b.wav": 2.5})
    by_mode = {u["mode"]: u for u in used}
    assert sorted(by_mode) == [2, 3, 4]
    assert by_mode[2]["host"] == by_mode[4]["host"] != by_mode[3]["host"]
    assert by_mode[4]["frames"] == by_mode[2]["frames"] == 88200
    assert len(edits) == len(grows) == 2                   # two records, not three
    assert any("same file as another mode" in t for t in logs)


def test_longer_files_play_whole_when_longer_replacements_are_allowed(tmp_path, monkeypatch):
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, {"a.wav": 2.0, "b.wav": 2.5})
    assert {u["mode"]: u["frames"] for u in used} == {2: 88200, 3: 110250, 4: 88200}
    assert not any(".cut" in w for w in edits.values())


def test_longer_files_are_cut_to_the_slots_length_when_they_are_not(tmp_path, monkeypatch):
    import wave
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, {"a.wav": 2.0, "b.wav": 0.5},
                                     longer_ok=False)
    frames = {u["mode"]: u["frames"] for u in used}
    assert frames == {2: 44100, 3: 22050, 4: 44100}       # a.wav cut to 1 s; b.wav already shorter
    hosts = {u["mode"]: u["host"] for u in used}
    assert hosts[2] == hosts[4]
    with wave.open(edits[hosts[2]], "rb") as r:
        assert r.getnframes() == 44100
    assert edits[hosts[3]].endswith("conv_b.wav")
    assert any("cut to its slot's" in t and "off in Settings" in t for t in logs)


def test_one_file_at_two_loudnesses_is_two_records(tmp_path, monkeypatch):
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, {"a.wav": 2.0, "b.wav": 2.5},
                                     levels={"2": 3})
    by_mode = {u["mode"]: u for u in used}
    assert {m: u["db"] for m, u in by_mode.items()} == {2: 3, 3: 0, 4: 0}
    assert len({by_mode[2]["host"], by_mode[3]["host"], by_mode[4]["host"]}) == 3
    assert len(edits) == 3
    assert any("its own loudness +3 dB" in t for t in logs)
    # at one loudness the file is one record again
    edits, grows, used, logs = _grow(tmp_path, monkeypatch, {"a.wav": 2.0, "b.wav": 2.5},
                                     levels={"2": 3, "4": 3})
    by_mode = {u["mode"]: u for u in used}
    assert by_mode[2]["host"] == by_mode[4]["host"] and len(edits) == 2
