"""Check this game: the object's `check` lines read into a verdict, and the verdict kept per port."""

import pathlib

import pytest

from pinball_decryptor.plugins.stern import game_check as GC

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
SHOTS = [("Left orbit", 0x2), ("Inner loop", 0x20), ("Top target", 0x400000000000)]
EVENTS = ("game_start", "ball_start", "ball_end", "bonus_start", "bonus_end", "tilt")

#: mode.log as gamecheck.sh log hands it back (Deadpool LE 1.14, 2026-09-24, cut down)
LOG = """\
       0 [pad] port /dump/game.port: deadpool_le 1.14, 19 sites, 28 shots
       0 [pad] events: 8 of 8 named events armed, dispatch hooked
       0 [pad] armed: 1 mode(s); can callout own-sound messages
   22199 [mode] check ready on deadpool_le 1.14
   35194 [mode] check event game_start (0x4d) in_game 1
   35195 [mode] check event ball_start (0x25) in_game 1
   40000 [mode] check mark 93
   40500 [mode] check shot 0x2 in_game 1
   41600 [mode] check mark 54
   42100 [mode] check shot 0x20 in_game 1
   43200 [mode] check mark 58
   44800 [mode] check mark drain
   45300 [mode] check ball end
   45316 [mode] check event ball_end (0x34) in_game 1
   45316 [mode] check event bonus_start (0x27) in_game 1
   48500 [mode] check event bonus_end (0x28) in_game 1
"""
PLAY = """\
[check] waiting for the game to boot
[check] switch 93 LEFT ORBIT
[check] switch 54 INNER LOOP
[check] switch 58 (B)OOM
[check] a ball ended
"""


def test_a_full_check_passes_and_names_what_it_saw():
    r = GC.read(LOG, PLAY, SHOTS, EVENTS)
    assert r.ok and r.started and r.ball_end and r.pressed == 3
    assert r.armed.startswith("armed: 1 mode(s)")
    assert r.shots_seen == {"Left orbit": "LEFT ORBIT", "Inner loop": "INNER LOOP"}
    assert r.shots_unseen == ["Top target"]
    assert r.events_seen == ["game_start", "ball_start", "ball_end", "bonus_start", "bonus_end"]
    assert r.events_unseen == []                  # tilt is not one a check's game fires
    text = r.summary("Deadpool LE 1.14")
    assert text.startswith("Checked in the emulator: modes run on Deadpool LE 1.14. 2 of the 3 shots")
    assert "Not seen: Top target." in text


def test_a_shot_before_any_mark_is_nobody_s():
    log = LOG.replace("   40000 [mode] check mark 93\n", "")
    r = GC.read(log, PLAY, SHOTS, EVENTS)
    assert "Left orbit" in r.shots_unseen and r.ok


@pytest.mark.parametrize("cut, why", [
    ("check ball end", "no end of ball"),
    ("armed: ", "never hooked"),
    ("check shot", "no shot came"),
])
def test_a_check_missing_a_core_part_fails(cut, why):
    log = "\n".join(ln for ln in LOG.splitlines() if cut not in ln)
    r = GC.read(log, PLAY, SHOTS, EVENTS)
    assert not r.ok, why


def test_a_refused_port_says_so():
    log = LOG + "    100 [pad] NOT THIS GAME'S PORT: site tick words differ\n"
    r = GC.read(log, PLAY, SHOTS, EVENTS)
    assert not r.ok and "refused the port" in r.summary("X")


def test_an_expected_event_that_did_not_fire_is_named():
    log = LOG.replace("bonus_end (0x28)", "something (0x99)")
    r = GC.read(log, PLAY, SHOTS, EVENTS)
    assert r.events_unseen == ["bonus_end"] and "Events that did not fire: bonus_end." in r.summary()


def test_a_kept_check_is_tied_to_the_port_s_text(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "cache"))
    port = tmp_path / "x-1.0.port"
    port.write_text("game x\nversion 1.0\n", encoding="utf-8")
    assert GC.load(str(port)) is None and not GC.passed(str(port))
    assert GC.record(str(port), GC.read(LOG, PLAY, SHOTS, EVENTS))
    got = GC.load(str(port))
    assert got is not None and got.ok and got.shots_seen["Inner loop"] == "INNER LOOP"
    assert GC.passed(str(port))
    port.write_text("game x\nversion 1.0\nshot 0x4 New\n", encoding="utf-8")
    assert GC.load(str(port)) is None             # another port text needs another check


def test_the_object_logs_the_lines_the_reader_reads():
    """mode_file.c's check lines and gamecheck.sh's words are what read() parses."""
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    for fmt in ('"check shot 0x%llx in_game %d"', '"check event %s (0x%02x) in_game %d"',
                '"check ball end"', '"check mark %s"', '"check ready on %s %s"',
                'pm_trigger("gamecheck.on")'):
        assert fmt in src, fmt
    sh = (SDK.parent / "gamecheck.sh").read_text(encoding="utf-8")
    assert 'say "switch $id $name"' in sh and '"$DUMP/census.mark"' in sh
    tryit = (SDK.parent / "tryit.sh").read_text(encoding="utf-8")
    assert '"$S/%s"' % GC.FLAG_NAME in tryit and '"$DUMP/%s"' % GC.FLAG_NAME in tryit
