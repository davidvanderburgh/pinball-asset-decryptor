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


def test_corrupt_csvs_are_ignored(tmp_path):
    assets = str(tmp_path)
    with open(os.path.join(assets, "callouts.csv"), "w",
              encoding="utf-8") as f:
        f.write("\x00garbage\nnot,a,csv")
    cats = AC.classify(assets, ["audio/idx0001.wav"])
    assert cats["audio/idx0001.wav"] == AC.OTHER
