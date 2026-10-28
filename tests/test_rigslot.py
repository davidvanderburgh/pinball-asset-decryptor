"""core/rigslot.py: which emulator rig the app drives, and the board it shows.

The rig side is tests/test_spike2_rig_slots.py; this is the app's half - the
environment its rig commands carry, the board as the Emulate tab reads it,
and the rig an app launched for a triage ticket claims for itself.
"""
import json
import os
import time

import pytest

from pinball_decryptor.core import rigslot


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_BOARD_WIN", str(tmp_path))
    for k in ("PAD_SLOT", "PAD_LABEL", "PAD_TICKET"):
        monkeypatch.delenv(k, raising=False)
    for v in (rigslot._claimed, rigslot._home):
        v.clear()
    yield tmp_path
    for v in (rigslot._claimed, rigslot._home):
        v.clear()


def _put(d, name, rec, age=0):
    p = os.path.join(str(d), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    if age:
        t = time.time() - age
        os.utime(p, (t, t))


def test_an_ordinary_install_changes_nothing(board):
    assert rigslot.slot() == 0
    assert rigslot.rig_env() == []
    assert rigslot.title_tag() == ""
    rows = rigslot.board()
    assert [r["slot"] for r in rows] == list(range(rigslot.SLOTS_MAX + 1))
    assert not any(r["holder"] or r["run"] for r in rows)
    assert rows[0]["mine"] and not rows[1]["mine"]


def test_a_rig_and_a_label_ride_on_every_command(board, monkeypatch):
    monkeypatch.setenv("PAD_SLOT", "2")
    monkeypatch.setenv("PAD_TICKET", "PAD-231")
    assert rigslot.rig_env() == ["PAD_SLOT=2", "PAD_LABEL=PAD-231"]
    assert rigslot.title_tag() == "rig 2: PAD-231"
    monkeypatch.setenv("PAD_LABEL", "item/48")      # an explicit label wins
    assert rigslot.rig_env()[1] == "PAD_LABEL=item/48"


def test_the_board_reads_holders_runs_and_stale_runs(board):
    now = int(time.time())
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48", "what": "godzilla run",
                                "distro": "Ubuntu", "taken": now - 600})
    _put(board, "slot-1.run", {"slot": 1, "game": "godzilla_pro", "label": "item/48",
                               "started": now - 300})
    _put(board, "slot-3.run", {"slot": 3, "game": "turtles_pro", "started": now - 900},
         age=400)
    _put(board, "slot-2.lock", "not a record")
    rows = {r["slot"]: r for r in rigslot.board(now=now)}
    assert rows[1]["holder"] == "item/48" and rows[1]["doing"] == "godzilla run"
    assert 595 <= rows[1]["held_s"] <= 605
    assert rows[1]["run"]["game"] == "godzilla_pro" and not rows[1]["run"]["stale"]
    assert rows[3]["run"]["stale"]
    assert rows[2]["holder"] == "" and rows[2]["run"] is None    # junk ignored
    assert rows[1]["colour"] == rigslot.COLOURS[1]


def _lock(d, n):
    p = os.path.join(str(d), "slot-%d.lock" % n)
    return json.loads(open(p).read()) if os.path.exists(p) else None


def test_a_ticket_app_holds_no_rig_until_it_runs(board, monkeypatch):
    """David 2026-09-27: a rig is locked only while it is actively used. The
    window opening takes nothing; the title names the ticket."""
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    assert not os.listdir(str(board))
    assert rigslot.title_tag() == "PAD-7"
    assert rigslot.slot() == 0


def test_start_takes_a_free_rig_and_stop_gives_it_back(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48"})
    assert rigslot.claim_for_run() == 2
    assert os.environ["PAD_SLOT"] == "2"
    assert _lock(board, 2)["who"] == "PAD-7"
    rigslot.release_claimed()
    assert _lock(board, 2) is None
    assert _lock(board, 1)["who"] == "item/48"                    # not ours


def test_the_next_start_asks_for_the_same_rig_first(board, monkeypatch):
    """Its NVRAM and save states are in that rig."""
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48"})
    assert rigslot.claim_for_run() == 2
    rigslot.release_claimed()
    os.remove(os.path.join(str(board), "slot-1.lock"))            # rig 1 is free now
    assert rigslot.claim_for_run() == 2


def test_a_run_up_keeps_the_rig_through_a_release(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    assert rigslot.claim_for_run() == 1
    _put(board, "slot-1.run", {"slot": 1, "game": "godzilla_pro", "started": 1})
    rigslot.release_claimed()
    assert _lock(board, 1)["who"] == "PAD-7"


def test_release_never_removes_a_lock_someone_else_took_over(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    assert rigslot.claim_for_run() == 1
    _put(board, "slot-1.lock", {"slot": 1, "who": "item/48"})     # replaced
    rigslot.release_claimed()
    assert _lock(board, 1)["who"] == "item/48"


def test_a_lapsed_hold_is_taken_only_when_no_rig_is_free(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    old = rigslot.IDLE_S + 60
    _put(board, "slot-1.lock", {"slot": 1, "who": "PAD-3"}, age=old)     # lapsed
    assert rigslot.claim_for_run() == 2                           # free first
    rigslot.release_claimed()
    for n in range(2, rigslot.SLOTS_MAX + 1):
        _put(board, "slot-%d.lock" % n, {"slot": n, "who": "x%d" % n})  # active
    assert rigslot.claim_for_run() == 1                           # then the lapsed one
    assert _lock(board, 1)["who"] == "PAD-7"
    assert not [f for f in os.listdir(str(board)) if ".seize." in f]


def test_every_rig_in_use_refuses_the_start(board, monkeypatch):
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    for n in range(1, rigslot.SLOTS_MAX + 1):
        _put(board, "slot-%d.lock" % n, {"slot": n, "who": "x"})
    assert rigslot.claim_for_run() is None
    assert "PAD_SLOT" not in os.environ


def test_no_ticket_or_a_chosen_rig_claims_nothing(board, monkeypatch):
    assert rigslot.claim_for_run() == 0
    assert not os.listdir(str(board))
    monkeypatch.setenv("PAD_TICKET", "PAD-7")
    monkeypatch.setenv("PAD_SLOT", "3")
    assert rigslot.claim_for_run() == 3
    assert not os.listdir(str(board))


def test_the_board_says_running_and_active_and_clears_lapsed(board):
    now = time.time()
    _put(board, "slot-1.lock", {"slot": 1, "who": "a"})
    _put(board, "slot-1.run", {"slot": 1, "game": "g", "started": 1})
    _put(board, "slot-2.lock", {"slot": 2, "who": "b"}, age=60)
    _put(board, "slot-3.lock", {"slot": 3, "who": "c"}, age=rigslot.IDLE_S + 60)
    rows = {r["slot"]: r for r in rigslot.board(now=now)}
    assert [rows[n]["state"] for n in range(5)] == ["free", "running", "active",
                                                   "free", "free"]
    assert 55 <= rows[2]["idle_s"] <= 65
    # the lapsed one was CLEARED by the read, not only shown
    assert rigslot.state(3) == "free" and _lock(board, 3) is None


def test_the_colours_match_the_playfield_band():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "tools", "spike2_emu", "pfpage", "pf.css"),
              encoding="utf-8") as fh:
        css = fh.read()
    for n, c in enumerate(rigslot.COLOURS):
        assert "--rig-%d: %s" % (n, c) in css


def test_every_rig_command_carries_the_rig(board, monkeypatch):
    from pinball_decryptor.webui import emulate_core
    monkeypatch.setattr(emulate_core.runtime, "distro_for", lambda _k: None)
    assert not [e for e in emulate_core._rig_env() if e.startswith("PAD_SLOT")]
    monkeypatch.setenv("PAD_SLOT", "3")
    monkeypatch.setenv("PAD_LABEL", "item/48")
    env = emulate_core._rig_env()
    assert "PAD_SLOT=3" in env and "PAD_LABEL=item/48" in env


def test_an_installed_rig_is_told_the_apps_board(monkeypatch):
    """PAD-803: a rig under Program Files guesses the Linux home's board, so
    it is told the profile's; a checkout under the profile guesses right and
    its commands stay as they were."""
    from pinball_decryptor.webui import emulate_core
    monkeypatch.setattr(emulate_core.sys, "platform", "win32")
    monkeypatch.setattr(rigslot, "board_dir", lambda: r"C:\Users\Deistar\.pad-rig")
    monkeypatch.setenv("PAD_EMU_DIR", r"C:\Program Files\Pinball Asset Decryptor\tools\spike2_emu")
    assert emulate_core._board_env() == ["PAD_BOARD=/mnt/c/Users/Deistar/.pad-rig"]
    monkeypatch.setenv("PAD_EMU_DIR", r"C:\Users\Deistar\src\pad\tools\spike2_emu")
    assert emulate_core._board_env() == []
    monkeypatch.setattr(emulate_core.sys, "platform", "linux")
    monkeypatch.setenv("PAD_EMU_DIR", "/opt/pad/tools/spike2_emu")
    assert emulate_core._board_env() == []


def test_a_run_says_its_speed(board):
    """PAD-649: watch.sh writes the game's speed into the run record once padspeed.py's ask is taken up, and
    the Emulate tab's rig strip says "4x"; an older record has none and reads as real time."""
    now = int(time.time())
    _put(board, "slot-1.run", {"slot": 1, "game": "godzilla_pro", "started": now, "speed": 4})
    _put(board, "slot-2.run", {"slot": 2, "game": "jaws_le", "started": now, "speed": "0.5"})
    _put(board, "slot-3.run", {"slot": 3, "game": "turtles_pro", "started": now})
    rows = {r["slot"]: r for r in rigslot.board(now=now)}
    assert rows[1]["run"]["speed"] == 4.0 and rows[2]["run"]["speed"] == 0.5
    assert rows[3]["run"]["speed"] == 1.0
    assert rigslot.speed_text(4) == "4x" and rigslot.speed_text(0.5) == "0.5x"
    assert rigslot.speed_text(1) == "" and rigslot.speed_text(None) == "" and rigslot.speed_text("x") == ""


def test_the_board_says_which_card_copy_a_rig_waits_on(board):
    """PAD-649: cardmount.sh puts a card copy on the board (copy-<label>.json, every 2 s), cardstage.sh a
    "queued" one while it waits for the copy lock, and rigbatch's lock note names the card; the row carries the
    copy its rig waits on, by label first, else the holder's running copy, else its first queued one. A record
    nobody touched for 90 s is a dead copier and is ignored."""
    now = int(time.time())
    _put(board, "slot-1.lock", {"slot": 1, "who": "PAD-9",
                                "what": "rigbatch dnd_le-1.10 (waiting for its card: dnd_le-1_10_0_spike2)",
                                "taken": now})
    _put(board, "slot-2.lock", {"slot": 2, "who": "PAD-9",
                                "what": "rigbatch jaws_le-1.02 (waiting for its card: jaws_le-1_02_0)", "taken": now})
    _put(board, "slot-3.lock", {"slot": 3, "who": "PAD-7", "what": "rigbatch x (waiting for its card)", "taken": now})
    _put(board, "slot-4.lock", {"slot": 4, "who": "PAD-9", "what": "rigbatch godzilla_pro-1.16", "taken": now})
    _put(board, "copy-dnd_le-1_10_0_spike2.json",
         {"label": "dnd_le-1_10_0_spike2", "card": "dnd_le-1_10_0_spike2.Release.16G.sdcard.raw", "who": "PAD-9",
          "state": "copying", "done_mb": 2852, "total_mb": 14777, "pct": 19})
    _put(board, "copy-jaws_le-1_02_0.json",
         {"label": "jaws_le-1_02_0", "card": "jaws_le-1_02_0.Release.16G.sdcard.raw", "who": "PAD-9",
          "state": "queued", "done_mb": 0, "total_mb": 15000, "pct": 0})
    _put(board, "copy-old.json", {"label": "old", "card": "old-1_0_0.raw", "who": "PAD-7", "state": "copying",
                                  "pct": 50}, age=400)
    rows = {r["slot"]: r for r in rigslot.board(now=now)}
    assert rows[1]["copy"]["state"] == "copying" and rows[1]["copy"]["pct"] == 19
    assert rows[1]["copy"]["title"] == "Dnd LE 1.10" and rows[1]["copy"]["total_mb"] == 14777
    assert rows[2]["copy"]["state"] == "queued" and rows[2]["copy"]["title"] == "Jaws LE 1.02"
    assert rows[3]["copy"] is None                      # its only record is a dead copier's
    assert rows[4]["copy"] is None                      # not waiting for a card
    assert rigslot.card_title("dungeons_and_dragons_le-1_10_0_spike2.Release.16G.sdcard.raw") \
        == "Dungeons And Dragons LE 1.10"
    assert rigslot.card_title("godzilla_pro-1_16_0_spike2") == "Godzilla Pro 1.16"
