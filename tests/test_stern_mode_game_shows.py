"""PAD-411: a mode plays one of the game's own light shows (MODE_SDK.md "The game's own light shows").

David: "i am not seeing any fancy playfield light shows when custom modes start or end ... can we add in some
sophisticated light shows like those for our custom modes?" The game's shows are processes of its own; the runtime
starts one's body as a process of its own and stops it with the game's kill by id. Emulator-proven on the stock
Premium/LE 1.16 card, two machine tests on David's Premium.

What is worth failing on:
  * THE PORT NAMES EVERY SHOW AS A MODE ASKS FOR IT: a body, a name, a kind (flashy / subdued / accent) and a length.
  * THE EXAMPLES ASK FOR SHOWS THE PORT HAS: a flashy one at the start, a subdued one at the end.
  * THE LIMITS ARE THE RUNTIME'S: only the running mode (or its ending's 2 s), in a game, one at a time, stopped at
    its length, and none while the ball ends (the game stops every show of its own then).
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
PORT = SDK / "ports" / "godzilla_le-1.16.port"
EXAMPLES = ["biollante", "destoroyah", "final_wars", "ghidorah_heads", "godzilla_angry", "kiryu", "maser_barrage",
            "meltdown", "oxygen_destroyer", "spacegodzilla"]


def _port():
    return PORT.read_text(encoding="utf-8")


def _shows():
    """{name: (n, kind, secs)} from the port's show lines."""
    p = _port()
    out = {}
    for n in sorted(int(k) for k in re.findall(r"^site show_(\d+) ", p, re.M)):
        name = re.search(r"^text show_name_%d\s+(.+?)\s*$" % n, p, re.M).group(1)
        kind = re.search(r"^text show_kind_%d\s+(\S+)" % n, p, re.M).group(1)
        secs = int(re.search(r"^value show_secs_%d\s+(\d+)" % n, p, re.M).group(1))
        out[name] = (n, kind, secs)
    return out


def test_the_port_names_every_show_as_a_mode_asks_for_it():
    p = _port()
    assert re.search(r"^value show_proc\s+\d+", p, re.M)
    for s in ("proc_create", "proc_exists", "event_cancel"):
        assert re.search(r"^site %s\s+0x[0-9a-f]+ 0x[0-9a-f]{8} 0x[0-9a-f]{8}" % s, p, re.M), s
    shows = _shows()
    ns = sorted(n for n, _k, _s in shows.values())
    assert ns == list(range(1, len(ns) + 1)) and len(ns) >= 8          # numbered from 1, no gaps
    assert {k for _n, k, _s in shows.values()} <= {"flashy", "subdued", "accent"}
    assert all(0 < s <= 20 for _n, _k, s in shows.values())             # the runtime stops one at 20 s anyway
    # measured on the machine and in the emulator: the 2 s Colour sweep went unseen as a start
    assert shows["Colour sweep"][1] == "accent"
    assert shows["Insert chase"][1] == "flashy" and shows["Playfield wave"][1] == "flashy"


@pytest.mark.parametrize("slug", EXAMPLES)
def test_each_example_asks_for_a_flashy_start_and_a_subdued_end(slug):
    src = (SDK / "examples" / (slug + ".c")).read_text(encoding="utf-8")
    start = re.search(r'^#define GAME_SHOW_START "([^"]+)"', src, re.M).group(1)
    end = re.search(r'^#define GAME_SHOW_END\s+"([^"]+)"', src, re.M).group(1)
    shows = _shows()
    assert shows[start][1] == "flashy", (slug, start)
    assert shows[end][1] == "subdued", (slug, end)
    assert 'kit_game_show(GAME_SHOW_START, "its start")' in src and 'kit_game_show(GAME_SHOW_END, "its end")' in src


def test_the_runtime_limits():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("int pm_game_show(int n)"):]
    body = body[:body.index("\n}\n")]
    assert "pm_running()" in body and "show_ended_ms < 2000ul" in body and "!pm_in_game()" in body
    assert "ball_end_at && pm_ms() - ball_end_at < 3000ul" in body          # none while the ball ends
    assert 'show_kill("another show begins")' in body                       # one at a time
    assert 'pm_snprintf(key, sizeof key, "show_secs_%d", n);' in body       # stopped at its port length
    tick = src[src.index("static void shows_tick(void)"):]
    assert "show_now.limit" in tick[:tick.index("\n}\n")]
    kill = src[src.index("static void show_kill("):]
    assert 'fn("event_cancel")' in kill[:kill.index("\n}\n")]               # the game's own kill by id
    assert "ball_end_at = pm_ms() | 1;" in src[src.index("static void on_ball_end("):]


def test_the_docs_name_the_calls():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("pm_game_show", "pm_game_show_named", "pm_game_show_stop", "pm_game_show_playing", "pm_game_shows",
                 "PM_CAN_GAME_SHOWS"):
        assert "`%s" % name in doc, name
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "## The game's own light shows (Godzilla Premium/LE, PAD-411)" in sdk
    for name in _shows():
        assert "| %s |" % name in sdk, name


def test_the_show_reel_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(SDK / "show_reel_mode.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()
