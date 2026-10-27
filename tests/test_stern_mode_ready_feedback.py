"""PAD-733 (David, on the machine with v32):

- "anytime a HUD mode gets to zero it's shot on the playfield needs to blink to let you know that that shot is ready to
  be starting a mode. Ideally the HUD indicator would show which shot to hit in small text where the number was":
  the progress number at 0 blinks the shots that start the mode, and the panel's badge shows their name in its place.
- (SUPER X2) "though the shots were lit I wasn't getting any feedback either visual or audio or Shaker when I was
  hitting the shots so the mode felt broken. Every single shot on our custom modes needs to have feedback": a shot
  that scores while the mode runs and brings nothing the player hears, sees or feels gets the game's rising hit sound
  and a strobe of its inserts.
- KUMONGA picked on the selection screen did not start ("a stock mode is running"): a battle picked there never waits
  for the game's own modes - the game let its own battle start.
"""
import os
import re
import subprocess

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_hud as MH

from tests.test_stern_block_modes import SDK, SHOTS, _cc, num, play, prog, var


def counting(start_at=3):
    """OXYGEN DESTROYER's shape: each Left spinner spin counts; the last one starts it; the panel shows the spins left"""
    left = {"k": "op", "op": "-", "a": num(start_at), "b": var("spins")}
    return prog([
        {"hat": {"kind": "shot", "shot": "Left spinner", "when": "idle"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("spins"), "b": num(start_at)},
             "then": [{"op": "start_mode"}],
             "else": [{"op": "change", "var": "spins", "by": num(1)},
                      {"op": "hud_progress", "value": left},
                      {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("spins"), "b": num(start_at)},
                       "then": [{"op": "start_mode"}]}]}]},
        {"hat": {"kind": "mode_start"}, "do": [{"op": "set", "var": "spins", "value": num(0)}]},
    ], vars=[{"name": "spins", "reset": "ball"}], seconds=10, wait_multiball=True,
        hud={"on": True, "line": "SPIN", "timer": {"on": False}})


def test_the_shots_that_start_it_and_their_words():
    assert BM.ready_shots(counting()) == ["Left spinner"]
    assert BM.ready_label(["Left spinner"]) == "LEFT SPINNER"
    assert BM.ready_label(["Shield target left", "Shield target center", "Shield ramp spinner"]) == "SHIELD"
    assert BM.ready_label(["Left ramp", "Big loop"]) == "LEFT RAMP"
    assert BM.hud_spec(counting(), "ox")["ready"] == "LEFT SPINNER"
    # lit at a shot: that shot, and the block lights it itself (no blink of ours)
    lit = counting()
    lit["scripts"][0]["do"] = [{"op": "hud_progress", "value": num(0)},
                               {"op": "light_mode", "shot": "Godzilla target", "color": "#ff1400", "pattern": "blink"}]
    assert BM.ready_shots(lit) == ["Godzilla target"]
    assert "N_READY" not in BM.to_c(lit, "lit")
    # a shot that starts a timer whose script starts it (KING KONG's Left ramp)
    kk = prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [
                   {"op": "timer_start", "timer": "ramp", "ms": num(300)}]},
               {"hat": {"kind": "timer_done", "timer": "ramp"}, "do": [
                   {"op": "hud_progress", "value": num(0)}, {"op": "start_mode"}]}],
              timers=[{"name": "ramp"}], hud={"on": True, "timer": {"on": False}})
    assert BM.ready_shots(kk) == ["Left ramp"]
    # no number on the panel: nothing
    assert BM.ready_shots(prog([{"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"},
                                 "do": [{"op": "start_mode"}]}])) == []


def test_the_count_done_blinks_its_shot_until_it_starts(tmp_path):
    p = counting()
    assert BM.problems(p, SHOTS) == []
    src = BM.to_c(p, "ox")
    assert "ready_set(value <= 0);" in src and "ready_tick();" in src and "ready_as[p] = 0;" in src
    assert "its count starts again with the ball" in src          # spins are kept each ball
    spins = []
    for _ in range(3):
        spins += ["shot", "Left spinner", "ms", 200]
    # a multiball of the game's runs: the last spin's start waits, the count is done
    out = play(tmp_path, p, "multiball", 1, "secs", 1, *spins, "secs", 1, "multiball", 0, "secs", 2,
               "shot", "Left spinner", "secs", 1)
    done = out.index("ready for player 1")
    assert "not started (a block): a multiball is running" in out[done:]
    blink = re.search(r"^\s*(\d+) LAMP LEFT SPINNER ffffff blink 250", out, re.M)
    assert blink and out.index(">> multiball 0") < blink.start()   # not while the multiball runs
    start = out.index("START (a block)")
    assert blink.start() < start and out.index(">> shot Left spinner", out.index(">> multiball 0")) < start
    # the badge: its READY picture in the number's place at 0
    ready = re.findall(r"SHOW \S*PadMode_Progress_S1_blk_Ready (\d)", out)
    assert ready[0] == "0" and "1" in ready                           # built visible: hidden first, shown at 0
    assert "WORDS PadMode_Progress_S1_Num: 1" in out


def test_a_new_ball_counts_again_and_the_blink_goes(tmp_path):
    spins = []
    for _ in range(3):
        spins += ["shot", "Left spinner", "ms", 200]
    out = play(tmp_path, counting(), "multiball", 1, "secs", 1, *spins, "secs", 1, "ball_end", "secs", 1,
               "multiball", 0, "secs", 2)
    assert "ready for player 1" in out and "ready no more for player 1" in out
    after = out[out.index("ready no more"):]
    assert not re.search(r"LAMP LEFT SPINNER ffffff blink 250", after)
    assert re.search(r"WORDS PadMode_Progress_S1_Num: 3", out[out.index(">> ball_end"):])


def charging():
    """SUPER X2's shape: its shots score and charge; only every third says so"""
    return prog([
        {"hat": {"kind": "shot", "shot": "Building", "when": "idle"}, "do": [{"op": "start_mode"}]},
        {"hat": {"kind": "shot", "shot": "Left ramp", "when": "running"}, "do": [
            {"op": "score", "points": num(750000)},
            {"op": "change", "var": "charge", "by": num(1)},
            {"op": "timer_start", "timer": "charge", "ms": num(1)}]},
        {"hat": {"kind": "timer_done", "timer": "charge"}, "do": [
            {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("charge"), "b": num(3)},
             "then": [{"op": "set", "var": "charge", "value": num(0)}, {"op": "sound", "sound": "up", "fallback": ""}]}]},
        {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [
            {"op": "score", "points": num(100)}, {"op": "shake", "ms": num(200), "strength": "soft"}]},
    ], vars=[{"name": "charge", "reset": "mode"}], timers=[{"name": "charge"}], seconds=30)


def test_a_scoring_shot_that_says_nothing_gets_the_hit_sound_and_a_strobe(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HITS", "1")
    p = charging()
    src = BM.to_c(p, "x2")
    assert "fb_owe();" in src and "fb_tick();" in src and src.count("fb_paid();") >= 2
    out = play(tmp_path, p, "shot", "Building", "secs", 1,
               "shot", "Left ramp", "secs", 1, "shot", "Left ramp", "secs", 1, "shot", "Left ramp", "secs", 1,
               "shot", "Right ramp", "secs", 1)
    hits = re.findall(r"HIT SOUND (\d+)", out)
    assert hits == ["1", "2"]                                    # the third charge said so itself; the shake too
    assert len(re.findall(r"STROBE 100000 ffffff 360", out)) == 2   # the Left ramp's inserts
    assert "STROBE 200000" not in out


def test_a_mode_whose_shots_never_score_while_it_runs_has_no_feedback_code():
    src = BM.to_c(counting(), "ox")
    assert "#define fb_paid() ((void)0)" in src and "fb_tick" not in src


def test_a_battle_picked_on_the_selection_screen_does_not_wait_for_the_games_modes():
    p = prog([{"hat": {"kind": "battle", "slot": 0}, "do": [{"op": "start_mode"}]}], wait_multiball=True)
    src = BM.to_c(p, "kum")
    assert "&& counted && !pick_go)" in src
    run = src[src.index("pick_go = 2;"):]          # PAD-768: 2 = a battle pick, which wins over the game's mini modes
    assert run.index('start("a block", 1);') < run.index("pick_go = 0;")


RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
PORTS = os.path.join(SDK, "ports")


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def test_a_mode_of_the_games_that_runs_beside_everything_is_not_waited_for(tmp_path):
    """the machine's log (v32): "aside: a stock mode is running" from 208 s into a ball to its drain at 854 s, through a
    multiball and a battle - Tesla Strike runs beside the game's own battles and multiballs; ours do not wait for it"""
    cc = _cc()
    src = open(RUNTIME, encoding="utf-8").read()
    code = "#include <stdio.h>\n" + _lift(src, "static int stock_beside(") + r"""
int main(void)
{
    const char *list = "Tesla Strike, Hedorah";
    printf("%d %d %d %d %d %d\n", stock_beside(list, "Tesla Strike"), stock_beside(list, "tesla strike"),
           stock_beside(list, "Hedorah"), stock_beside(list, "Tesla"), stock_beside(list, "Super Train"),
           stock_beside(0, "Tesla Strike"));
    return 0;
}
"""
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-o", str(tmp_path / "t"), str(tmp_path / "t.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout.split()
    assert out == ["1", "1", "1", "0", "0", "0"]
    q = _lift(src, "int pm_stock_mode_running(")
    assert "Q[i].kind == PM_STOCK_ANY && stock_any_weighed() == 0" in q
    assert "stock_any_what[0]" in _lift(src, "const char *pm_stock_mode_what(")
    for port in ("godzilla_le-1.16", "godzilla_pro-1.16", "godzilla_pro-1.15"):
        text = open(os.path.join(PORTS, port + ".port"), encoding="utf-8").read()
        assert re.search(r"^text stock_any_beside\s+Tesla Strike\s*$", text, re.M), port
        assert re.search(r"^rule 23\s+0x[0-9a-f]+ Tesla Strike\s*$", text, re.M), port


def test_the_badge_carries_its_ready_words_only_when_the_spec_names_them():
    import numpy as np

    class Font:
        def render(self, text, variant, px, scale=1.0, tint=(255, 255, 255)):
            return np.full((30, 14 * len(text), 4), 255, dtype=np.uint8)

    a = MH.badge_ready(Font(), "Left spinner")
    assert a.shape[1] >= MH.READY_W and a.shape[0] >= MH.READY_H and a[..., 3].any()
    one = MH.badge_ready(Font(), "Building")
    assert one[..., 3].any()
