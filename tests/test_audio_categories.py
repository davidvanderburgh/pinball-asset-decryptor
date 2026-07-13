"""Replace-Audio Type-filter categories (core/audio_categories.py)."""
import csv
import os

from pinball_decryptor.core import audio_categories as AC


def _write_callouts(assets, rows):
    with open(os.path.join(assets, "callouts.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "file", "seconds", "classification", "text"])
        w.writerows(rows)


def _write_music_titles(assets, rows):
    with open(os.path.join(assets, "music_titles.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relative_path", "title", "artist", "score"])
        w.writerows(rows)


def test_filename_rules_without_csvs(tmp_path):
    cats = AC.classify(str(tmp_path), [
        "audio/music_cat01_0002.wav",
        "audio/01m22s235 - music_cat01_0003.wav",
        "audio/idx0013 - SE FX SIDE RAMP EXIT.wav",
        "audio/idx0021 - music.wav",
        "audio/idx0022 - music - Led Zeppelin - Kashmir.wav",
        "audio/idx0100 - Welcome to the machine.wav",
        "audio/idx0200.wav",
        "audio/UNRELATED_NAME.wav",
    ])
    assert cats["audio/music_cat01_0002.wav"] == AC.MUSIC
    assert cats["audio/01m22s235 - music_cat01_0003.wav"] == AC.MUSIC
    assert cats["audio/idx0013 - SE FX SIDE RAMP EXIT.wav"] == AC.SFX
    assert cats["audio/idx0021 - music.wav"] == AC.MUSIC
    assert cats["audio/idx0022 - music - Led Zeppelin - Kashmir.wav"] \
        == AC.MUSIC
    # A transcript (or user) label with no CSV context reads as a callout.
    assert cats["audio/idx0100 - Welcome to the machine.wav"] == AC.CALLOUTS
    assert cats["audio/idx0200.wav"] == AC.OTHER
    assert cats["audio/UNRELATED_NAME.wav"] == AC.OTHER


def test_csv_classifications(tmp_path):
    assets = str(tmp_path)
    _write_callouts(assets, [
        ["audio", "idx0300.wav", "2.0", "speech", "Fire at will"],
        ["audio", "idx0301.wav", "1.0", "non-speech", ""],
        ["audio", "idx0302.wav", "30.0", "music", ""],
    ])
    _write_music_titles(assets, [
        ["audio/idx0303.wav", "Kashmir", "Led Zeppelin", "0.93"],
        ["audio/idx0304.wav", "", "", "0.10"],   # no confident id
    ])
    cats = AC.classify(assets, [
        "audio/idx0300.wav", "audio/idx0301.wav", "audio/idx0302.wav",
        "audio/idx0303.wav", "audio/idx0304.wav"])
    assert cats["audio/idx0300.wav"] == AC.CALLOUTS   # bare but speech
    assert cats["audio/idx0301.wav"] == AC.OTHER
    assert cats["audio/idx0302.wav"] == AC.MUSIC
    assert cats["audio/idx0303.wav"] == AC.MUSIC      # titled by AcoustID
    assert cats["audio/idx0304.wav"] == AC.OTHER


def test_sound_test_name_beats_csvs(tmp_path):
    """monkeybug's pre-fix Led Zeppelin extract: a Sound-Test-named SFX also
    matched a song in music_titles.csv (the riff inside it) — the game's own
    name wins, so the slot files under Sound FX, not Music."""
    assets = str(tmp_path)
    rel = "audio/idx0384 - SE FX ZEPPELIN AWARD - Immigrant Song.wav"
    _write_music_titles(assets, [[rel, "Immigrant Song", "Led Zeppelin",
                                  "0.91"]])
    assert AC.classify(assets, [rel])[rel] == AC.SFX


def test_name_duration_seconds():
    assert AC.name_duration_seconds("08m24s943 - idx0448 - SE FX X.wav") \
        == 8 * 60 + 24.943
    assert AC.name_duration_seconds("00m00s074 - idx0290.wav") == 0.074
    assert AC.name_duration_seconds("idx0290.wav") is None


def test_matches_filter_duration_aware_music():
    """David's LZ 1.22.0 extract: no music banks, the songs are cat-0
    sounds the Sound Test names "SE FX SEQ ..." — the Music filter must
    surface them by length, and they stay under Sound FX too."""
    long_sfx = (AC.SFX, 505.0)          # "SE FX SEQ BALL SAVE LIT", 8:24
    short_sfx = (AC.SFX, 0.074)         # spinner blip
    long_bare = (AC.OTHER, 61.8)        # bare idx0089, 1:01.795
    short_bare = (AC.OTHER, 5.0)
    long_callout = (AC.CALLOUTS, 25.0)  # long speech is never music

    assert AC.matches_filter(*long_sfx, AC.MUSIC)
    assert AC.matches_filter(*long_sfx, AC.SFX)       # both views
    assert not AC.matches_filter(*short_sfx, AC.MUSIC)
    assert AC.matches_filter(*long_bare, AC.MUSIC)
    assert not AC.matches_filter(*long_bare, AC.OTHER)  # left the junk pile
    assert AC.matches_filter(*short_bare, AC.OTHER)
    assert not AC.matches_filter(*long_callout, AC.MUSIC)
    assert AC.matches_filter(*long_callout, AC.CALLOUTS)
    # Explicit music category matches regardless of (unknown) duration.
    assert AC.matches_filter(AC.MUSIC, None, AC.MUSIC)
    # No filter = everything.
    assert AC.matches_filter(AC.OTHER, 0, None)


def test_renamed_slot_keeps_remembered_category(tmp_path, monkeypatch):
    """monkeybug: he renamed an SFX and the Type filter re-filed it as a
    callout.  The rename memory now records the bucket; the classifier
    honors it while the on-disk label still matches."""
    from pinball_decryptor.core import name_memory as NM
    monkeypatch.setattr(NM, "AUDIO_NAMES_FILE",
                        str(tmp_path / "audio_names.json"))
    assets = str(tmp_path)
    rel = "audio/idx0013 - Ramp exit swoosh.wav"
    with open(os.path.join(assets, ".checksums.md5"), "w",
              encoding="utf-8") as f:
        f.write("%s\t%s\n" % (rel, "d" * 32))
    NM.remember("d" * 32, "Ramp exit swoosh", category="sfx")
    assert AC.classify(assets, [rel])[rel] == AC.SFX
    # A different on-disk label (re-renamed by hand / re-transcribed) falls
    # back to the derived rules.
    rel2 = "audio/idx0013 - Something else.wav"
    with open(os.path.join(assets, ".checksums.md5"), "w",
              encoding="utf-8") as f:
        f.write("%s\t%s\n" % (rel2, "d" * 32))
    assert AC.classify(assets, [rel2])[rel2] == AC.CALLOUTS


def test_corrupt_csvs_are_ignored(tmp_path):
    assets = str(tmp_path)
    with open(os.path.join(assets, "callouts.csv"), "w",
              encoding="utf-8") as f:
        f.write("\x00garbage\nnot,a,csv")
    cats = AC.classify(assets, ["audio/idx0001.wav"])
    assert cats["audio/idx0001.wav"] == AC.OTHER
