"""PAD-798 (an owner asked for TMNT's scoring "with an extra 0"): Game points on the Write tab.

The project's factor (game_points) goes on the card as ``points.cfg`` beside the mode runtime, which
wraps the game's score function (pad_mode_runtime.c "game points") behind the Insider Connected score
gate. These tests pin the setting, the file, the delivery (mode_write, mode_install, the rig's
scripts), the Write tab's choice and the runtime's parser and multiplication (lifted verbatim and
compiled where a host C toolchain is). The emulator proof is the ticket's (TMNT LE 1.59 x10)."""

import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.core import staged_changes
from pinball_decryptor.plugins.stern import game_points as GP
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EMU = os.path.join(REPO, "tools", "spike2_emu")
SDK = os.path.join(EMU, "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---- the project's setting ----------------------------------------------------------------------
def test_normal_is_no_setting_and_a_factor_is_kept_beside_the_other_edits(tmp_path):
    p = str(tmp_path)
    assert GP.load(p) == 1
    staged_changes.save(p, {"audio": {"x": "y"}})
    assert GP.save(p, 10) == 1
    data = staged_changes.load(p)
    assert data[GP.STAGED_KEY] == {"times": 10} and data["audio"] == {"x": "y"}
    assert GP.load(p) == 10
    assert GP.save(p, 1) == 10
    assert GP.STAGED_KEY not in staged_changes.load(p) and GP.load(p) == 1
    with pytest.raises(ValueError):
        GP.save(p, 0)


@pytest.mark.parametrize("raw", [{"times": "lots"}, {"times": 0}, {"times": GP.MAX_TIMES + 1}, "x10", None])
def test_a_sidecar_value_the_runtime_would_refuse_is_normal(tmp_path, raw):
    staged_changes.save(str(tmp_path), {GP.STAGED_KEY: raw})
    assert GP.load(str(tmp_path)) == 1


def test_points_cfg_is_the_line_the_runtime_reads():
    assert GP.cfg_text(10).splitlines()[-1] == "times\t10"
    for bad in (1, GP.MAX_TIMES + 1):
        with pytest.raises(ValueError):
            GP.cfg_text(bad)
    assert GP.label(1) == "Normal" and GP.label(10) == "x10"
    assert 10 in GP.CHOICES and GP.CHOICES[0] == 1


def test_every_title_with_a_port_can_have_it():
    """Each port names the score function the runtime wraps and the Insider Connected gate."""
    keys = list(MP.profiles())
    assert keys
    assert [k for k in keys if GP.title_refusal(MP.profile(k))] == []
    assert any(k.startswith("turtles_") for k in keys)
    assert GP.title_refusal(None) == GP.NO_TITLE


def test_a_port_without_the_gate_is_refused(tmp_path, monkeypatch):
    port = tmp_path / "g.port"
    port.write_text("game g\nversion 1\nsite score_add 0x1000 0 0\n")
    monkeypatch.setattr(MP, "PORTS_DIR", str(tmp_path))

    class Prof:
        label = "Some Game 1.00"
        port = "g.port"
    assert GP.title_refusal(Prof()) == GP.NO_PORT % "Some Game 1.00"
    port.write_text("game g\nversion 1\nsite score_add32 0x1000 0 0\nsite agent_header 0x2000 0 0\n"
                    "site agent_begin 0x3000 0 0\n")
    assert GP.title_refusal(Prof()) == ""


# ---- the delivery -------------------------------------------------------------------------------
def test_a_card_of_game_points_only_carries_points_cfg_beside_the_runtime(tmp_path, monkeypatch):
    prof = MP.profile(next(k for k in MP.profiles() if k.startswith("turtles_le")))
    port = MP.port_path(prof)
    monkeypatch.setattr(MW, "_plan", lambda *a, **k: None)
    monkeypatch.setattr(MW, "find_port", lambda p, elf: port)
    cfg = tmp_path / GP.CFG_NAME
    cfg.write_text(GP.cfg_text(10))
    plan = MW.plan(str(tmp_path), b"", b"", b"", str(tmp_path / "scratch"), modes_on=False,
                   points=str(cfg), points_prof=prof)
    assert plan is not None and plan.points_file == str(cfg) and plan.mode_files == []
    out = MW.p2_payload(plan, str(tmp_path / "p2"))
    assert [os.path.basename(e) for e in out["extras"]] == [GP.CFG_NAME]
    assert _read(out["extras"][0]) == GP.cfg_text(10)


def test_game_points_ride_along_with_modes(tmp_path, monkeypatch):
    class Plan:
        points_file = ""
    monkeypatch.setattr(MW, "_plan", lambda *a, **k: Plan())
    plan = MW.plan(str(tmp_path), b"", b"", b"", str(tmp_path), points="x.cfg")
    assert plan.points_file == "x.cfg"


def test_the_card_install_and_the_emulator_carry_points_cfg():
    install = _read(os.path.join(EMU, "mode_install.py"))
    assert '("points.cfg", 0o100644)' in install
    assert re.search(r'STANDALONE_FILES = \([^)]*"points\.cfg"', install)
    tryit = _read(os.path.join(EMU, "modes", "tryit.sh"))
    assert 'put "$S/points.cfg" "$DUMP/points.cfg"' in tryit
    assert tryit.count('"$DUMP"/points.cfg') == 2                     # removed before, given back after
    card = _read(os.path.join(EMU, "modes", "cardmodes.sh"))
    assert '[ "$POINTS" = 0 ]; }; then' in card                     # a reason of its own to run the object
    assert card.count("points.cfg") >= 3


def test_the_runtime_reads_the_file_and_takes_the_whole_gate():
    src = _read(RUNTIME)
    m = re.search(r'PTS_FILES\[\]\s*=\s*\{([^}]*)\}', src)
    assert m and "/usr/local/padmode/%s" % GP.CFG_NAME in m.group(1) and "/dump/%s" % GP.CFG_NAME in m.group(1)
    assert int(re.search(r"#define PTS_TIMES_MAX\s+(\d+)", src).group(1)) == GP.MAX_TIMES
    start = src.index("static void pad_mode_start(void)")
    body = src[start:]
    # after the Insider Connected gate, never before it; and a card of game points is not an "only" card
    assert body.index("if (!insider_arm()) return;") < body.index("points_arm();")
    assert "!attract_wanted() && !points_wanted()" in body


# ---- the Write tab ------------------------------------------------------------------------------
def test_the_write_tab_choice_saves_the_factor_and_says_what_it_does(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import write as W

    class Mfr:
        key = "stern"
        current_era = "spike2"

    class Win:
        _running = False
        cb = {}

    monkeypatch.setattr(W.WriteTab, "mfr", property(lambda self: Mfr()))
    svc = W.WriteTab.__new__(W.WriteTab)
    svc.window = Win()
    state, logs = {}, []
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "_is_direct", lambda: False, raising=False)
    monkeypatch.setattr(svc, "_editions_applies", lambda: True, raising=False)
    monkeypatch.setattr(svc, "_info_assets_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "log", lambda text, *a, **k: logs.append(text), raising=False)
    monkeypatch.setattr(GP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(GP, "title_refusal", lambda prof: "")
    svc._publish_points()
    assert state["points_cap"] is True and state["points_shown"] == "1" and state["points_note"] == ""
    assert [o["label"] for o in state["points_options"]] == [GP.label(t) for t in GP.CHOICES]
    assert svc.set_points(10) is True
    assert staged_changes.load(str(tmp_path))[GP.STAGED_KEY] == {"times": 10}
    assert state["points_shown"] == "10" and state["points_note_kind"] == ""
    assert "x10" in state["points_note"] and "Insider Connected" in state["points_note"]
    assert logs[-1] == "Game points: every point the game adds is x10 on the card."
    monkeypatch.setattr(GP, "title_refusal", lambda prof: "not this one")
    svc._publish_points()
    assert (state["points_note"], state["points_note_kind"]) == ("not this one", "err")
    assert svc.set_points("1") is True and GP.load(str(tmp_path)) == 1
    assert state["points_shown"] == "1" and state["points_note"] == ""
    assert svc.set_points(0) is False and svc.set_points("ten") is False


def test_the_write_tab_shows_it_only_for_a_spike2_image_build(monkeypatch):
    from pinball_decryptor.webui.tabs import write as W
    svc = W.WriteTab.__new__(W.WriteTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "_editions_applies", lambda: False, raising=False)
    svc._publish_points()
    assert state == {"points_cap": False}
    js = _read(os.path.join(REPO, "pinball_decryptor", "webui", "static", "js", "tabs", "write.js"))
    assert 'call("write.set_points", Number(v))' in js and "s.points_cap && !direct" in js


def test_a_new_version_carries_the_factor():
    from pinball_decryptor.core import mod_transfer
    assert GP.STAGED_KEY in mod_transfer._TOGGLE_KEYS


# ---- the runtime's parser and multiplication, compiled ------------------------------------------
_HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
static unsigned pts_times;
@HELPERS@
@SECTION@
int main(void)
{
    char a[] = "times\t10", b[] = "times\t1001", c[] = "# times\t5", d[] = "times 7", e[] = "times\t0x64";
    pts_line(a); printf("%u ", pts_times);
    pts_line(b); printf("%u ", pts_times);
    pts_line(c); printf("%u ", pts_times);
    pts_line(d); printf("%u ", pts_times);
    pts_line(e); printf("%u ", pts_times);
    printf("%llu %llu %llu %llu\n", (unsigned long long)pts_scale(1230, 10), (unsigned long long)pts_scale(5, 1),
           (unsigned long long)pts_scale(~(uint64_t)0 / 3, 10), (unsigned long long)pts_scale(0, 100));
    return 0;
}
"""


def _c_function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


def test_the_runtime_parses_the_line_and_multiplies_saturating(tmp_path):
    if os.name == "nt" or sys.platform == "darwin":
        pytest.skip("the harness needs a host ELF C toolchain")
    cc = next((c for c in ("gcc", "cc", "clang") if shutil.which(c)), None)
    if not cc:
        pytest.skip("no host C compiler")
    src = _read(RUNTIME)
    helpers = "\n".join(_c_function(src, r) for r in (r"static int hexval\(", r"static uint64_t number\("))
    section = "#define PTS_TIMES_MAX %s\n" % re.search(r"#define PTS_TIMES_MAX\s+(\d+)", src).group(1)
    section += "\n".join(_c_function(src, r) for r in (r"static void pts_line\(", r"static uint64_t pts_scale\("))
    c = tmp_path / "pts.c"
    c.write_text(_HARNESS.replace("@HELPERS@", helpers).replace("@SECTION@", section))
    exe = tmp_path / "pts"
    r = subprocess.run([cc, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", "-o", str(exe), str(c)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split()
    # 10; 1001 is past the ceiling and 'times 7' has no TAB, a comment is a comment: each keeps 10; hex reads
    assert out[:5] == ["10", "10", "10", "10", "100"]
    assert out[5:] == ["12300", "5", str(2 ** 64 - 1), "0"]
