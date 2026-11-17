"""PAD-1384: the JJP Modes tab - it scrolls, and a mode is made with blocks, in C++ or with the form.

The runtime (tools/jjp_emu/jjpmodes.c) loads a mode's own C++ (`code = <name>` -> <name>.so,
modes/sdk/jjp_mode.h); the Blocks editor writes that C++ (plugins/jjp/block_modes.py).  The
emulator proof (Wonka 03.03, the app-made Blocks and C++ modes) is in the ticket; these hold the
pieces to what it proved.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest

from tests.webui_harness import web_app
from pinball_decryptor.plugins.jjp import block_modes as BM
from pinball_decryptor.plugins.jjp import custom_modes as CM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "jjp_emu", "modes", "sdk")
JS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
WONKA = os.path.join(ROOT, "tools", "jjp_emu", "modes", "ports", "Wonka-v03.03.json")
N = lambda v: {"k": "num", "v": v}          # noqa: E731


def _names():
    port = json.load(open(WONKA, encoding="utf-8"))
    return {"switches": CM.names_for(port, "switches"), "lamps": CM.names_for(port, "lamps"),
            "sound": CM.names_for(port, "sound"), "coil_pulse": CM.names_for(port, "coil_pulse")}


FULL = {"vars": [{"name": "bonus", "reset": "mode"}, {"name": "tries", "reset": "kept"}],
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": [{"op": "jjp_lamp", "lamp": "lp_gi_tv", "color": "#00ff40", "blink": 2},
                                                  {"op": "jjp_title", "text": "BLOCK \"RUSH\"", "value": None}]},
            {"hat": {"kind": "shot", "shot": "switch_ramp_left_made", "when": "running"},
             "do": [{"op": "score", "points": {"k": "op", "op": "/", "a": {"k": "total"}, "b": N(10)}},
                    {"op": "if", "cond": {"k": "cmp", "op": "=", "a": {"k": "hits", "shot": "switch_ramp_left_made"}, "b": N(3)},
                     "then": [{"op": "end_mode"}], "else": [{"op": "add_time", "seconds": N(5)}]}]},
            {"hat": {"kind": "any_shot"}, "do": [{"op": "change", "var": "bonus", "by": N(250000)},
                                                {"op": "jjp_title", "text": "BONUS", "value": {"k": "var", "name": "bonus"}}]},
            {"hat": {"kind": "every", "seconds": 2}, "do": [{"op": "jjp_sound", "sound": "se_Fanfare_Jackpot"}]},
            {"hat": {"kind": "seconds_left", "seconds": 5}, "do": [{"op": "set_time", "seconds": N(8), "at_least": True}]},
            {"hat": {"kind": "mode_end"}, "do": [{"op": "change", "var": "tries", "by": N(1)}]},
            {"hat": {"kind": "shot", "shot": "switch_target_bank_2", "when": "idle"}, "do": [{"op": "start_mode"}]},
            {"hat": {"kind": "challenge"}, "do": []},                  # a Stern hat: dropped
        ]}


# ------------------------------------------------------------------ blocks -> C++
def test_a_program_makes_one_callback_per_moment_registered_in_the_header_order():
    cpp = BM.to_cpp(FULL, "Block Rush", "block_rush")
    assert '#include "jjp_mode.h"' in cpp
    reg = re.search(r"JM_REGISTER\(\{ (.*) \}\);", cpp).group(1)
    assert reg == ".api = JM_API, .start = start, .shot = shot, .scored = scored, .tick = tick, .end = end, .idle = idle"
    header = open(os.path.join(SDK, "jjp_mode.h"), encoding="utf-8").read()
    order = re.findall(r"\(\*(\w+)\)\(", header[header.index("struct jm_mode {"):header.index("};", header.index("struct jm_mode {"))])
    assert [f.split(" = ")[0][1:] for f in reg.split(", ")[1:]] == [o for o in order if o in reg]
    assert 'jm_is(sw, "switch_ramp_left_made")' in cpp and 'jm_is(sw, "switch_target_bank_2")' in cpp
    assert "jm_start();" in cpp.split("static void idle")[1]
    assert "jb_div(jm_total(), 10LL)" in cpp and "static long long jb_div" in cpp
    assert '"BLOCK \\"RUSH\\""' in cpp                                  # a quote in the words, escaped
    assert "v0_bonus = 0;" in cpp.split("static void start")[1].split("}")[0]      # reset each time it starts
    assert "v1_tries = 0;" not in cpp                                            # kept
    assert "(jm_switch_hits(\"switch_ramp_left_made\") == 3LL)" in cpp.replace("(long long)", "")
    assert "challenge" not in cpp


def test_problems_name_what_the_game_lacks_and_misplaced_blocks():
    assert BM.problems(FULL, _names()) == []
    bad = {"vars": [], "scripts": [{"hat": {"kind": "any_shot"}, "do": [
        {"op": "start_mode"}, {"op": "set", "var": "x", "value": None}, {"op": "jjp_sound", "sound": "se_nope"},
        {"op": "jjp_coil", "coil": "coil_flipper_hold_left", "ms": 0}, {"op": "if", "cond": None, "then": []}]}]}
    p = " | ".join(BM.problems(bad, _names()))
    for want in ("Start the mode works only", "names no variable", "empty slot", "se_nope is not on this game",
                 "coil_flipper_hold_left is not on this game", "an If with an empty condition"):
        assert want in p, want
    assert BM.problems({}, {}) == ["No scripts yet: start with a When block."]


def test_the_starter_program_is_clean_and_makes_cpp():
    prog = BM.starter({"lamps": "lp_gi_tv"}, "Rush")
    assert BM.problems(prog, _names()) == []
    cpp = BM.to_cpp(prog, "Rush", "rush")
    assert "jm_score(v0_bonus);" in cpp and 'jm_lamp("lp_gi_tv"' in cpp and ".scored = scored" in cpp


# ------------------------------------------------------------------ the runtime and its API
def test_every_api_call_the_header_declares_is_exported_by_the_runtime():
    header = open(os.path.join(SDK, "jjp_mode.h"), encoding="utf-8").read()
    declared = set(re.findall(r"^\w[\w\s\*]*?\b(jm_[a-z_]+)\(", header, re.M)) - {"jm_is"}
    runtime = open(os.path.join(ROOT, "tools", "jjp_emu", "jjpmodes.c"), encoding="utf-8").read()
    defined = set(re.findall(r"^JMAPI [\w\s\*]*?\b(jm_[a-z_]+)\(", runtime, re.M))
    assert declared and declared == defined
    assert '#include "modes/sdk/jjp_mode.h"' in runtime
    for hook in ("code_started(m);", "code_tick(m);", "code_over(m,", "CODE_CALL(m, scored", "CODE_CALL(&pms[i], idle",
                 "taken = m->cm->shot(wsw[si].name) == JM_TAKEN", "code_names(m, path);"):
        assert hook in runtime, hook


def test_build_code_refuses_what_a_machine_lacks():
    sh = open(os.path.join(SDK, "build_code.sh"), encoding="utf-8").read()
    for flag in ("-nostdlib", "-fno-exceptions", "-fno-rtti", "-fno-threadsafe-statics", "-D_FORTIFY_SOURCE=0"):
        assert flag in sh
    assert "jm_mode_def" in sh and "__isoc23_" in sh


@pytest.mark.skipif(not (sys.platform.startswith("linux") and shutil.which("g++") and shutil.which("nm")),
                    reason="needs g++ (Linux)")
def test_template_and_blocks_cpp_build_and_a_std_mode_is_refused(tmp_path):
    (tmp_path / "t.cpp").write_text(CM.template_text("T", "T"))
    (tmp_path / "b.cpp").write_text(BM.to_cpp(FULL, "B", "b"))
    (tmp_path / "bad.cpp").write_text('#include "jjp_mode.h"\n#include <string>\nstatic std::string s;\n'
                                      'static void st() { s = "x"; }\nJM_REGISTER({ .api = JM_API, .start = st });\n')
    sh = os.path.join(SDK, "build_code.sh")
    for n in ("t", "b"):
        r = subprocess.run(["bash", sh, str(tmp_path / (n + ".cpp"))], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        und = subprocess.run(["nm", "-D", "--undefined-only", str(tmp_path / (n + ".so"))], capture_output=True, text=True).stdout
        assert all(re.match(r"(jm_|snprintf|__cxa_finalize|_ITM_|__gmon)", ln.split()[-1]) for ln in und.splitlines() if ln.strip())
    r = subprocess.run(["bash", sh, str(tmp_path / "bad.cpp")], capture_output=True, text=True)
    assert r.returncode == 5 and "standard library" in r.stderr and not (tmp_path / "bad.so").exists()


# ------------------------------------------------------------------ the checker and the stick
def _folder(tmp_path, code_mode=True, idle=False):
    d = tmp_path / "modes"
    d.mkdir()
    (d / "title.cfg").write_text("game = Wonka\n")
    start = "" if idle else "start = switch_target_tv\n"
    (d / "1_x.mode").write_text("name = X\n%scode = xcode\n" % start if code_mode else "name = X\n" + start)
    src = '#include "jjp_mode.h"\nstatic void i(const char *sw) { if (jm_is(sw, "switch_nope")) jm_start(); }\n' \
          'static void s() { jm_sound("se_Fanfare_Jackpot"); jm_coil("coil_flipper_hold_left", 0); }\n' \
          'JM_REGISTER({ .api = JM_API, .start = s%s });\n' % (", .idle = i" if idle else "")
    (d / "xcode.cpp").write_text(src)
    return d


def test_check_reads_the_code_names_and_wants_it_built(tmp_path):
    mk = CM.mk()
    d = _folder(tmp_path)
    port = json.load(open(WONKA, encoding="utf-8"))
    _modes, probs = mk.check_modes(str(d), port)
    text = " | ".join(probs)
    assert "xcode.cpp is not built yet" in text
    assert "names switch_nope: not in" in text and "coil_flipper_hold_left" in text and "se_Fanfare_Jackpot" not in text
    (d / "xcode.so").write_bytes(b"\x7fELF")
    os.utime(d / "xcode.cpp", (time.time() - 60, time.time() - 60))
    assert "not built" not in " | ".join(mk.check_modes(str(d), port)[1])
    files = [fn for fn, _p in mk.folder_files(str(d))]
    assert "xcode.so" in files and "xcode.cpp" not in files            # the machine gets the library, not the source
    assert mk.check_value("code", "x y", port)


def test_a_code_mode_that_starts_itself_needs_no_start_rule(tmp_path):
    mk = CM.mk()
    d = _folder(tmp_path, idle=True)
    probs = mk.check_modes(str(d), None)[1]
    assert not any("no start rule" in p for p in probs)
    (d / "xcode.cpp").write_text((d / "xcode.cpp").read_text().replace(", .idle = i", ""))
    assert any("no start rule" in p for p in mk.check_modes(str(d), None)[1])


# ------------------------------------------------------------------ the app
FAKE_CODE = r'''
import os, sys
d = sys.argv[sys.argv.index("--modes") + 1]
for f in os.listdir(d):
    if f.endswith(".cpp"):
        so = os.path.join(d, f[:-4] + ".so")
        open(so, "wb").write(b"\x7fELF" + b"\x02" * 40)
        print("built " + so, flush=True)
'''


def _fake_code(tmp_path, monkeypatch):
    fake = tmp_path / "fake_code.py"
    fake.write_text(FAKE_CODE)
    calls = []

    def argv(self, label):
        args = CM.code_args(label, lambda p: p)
        calls.append(args)
        return [sys.executable, str(fake)] + args[1:]

    from pinball_decryptor.webui import modes_jjp
    monkeypatch.setattr(modes_jjp.JjpModesMixin, "jjp_code_argv", argv)
    return calls


def _wait(w, cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


@pytest.fixture
def preview_on(monkeypatch):
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")


def test_new_mode_by_blocks_and_in_cpp_builds_and_checks_clean(tmp_path, preview_on, monkeypatch):
    calls = _fake_code(tmp_path, monkeypatch)
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", "modes")
        w.call("modes.jjp_pick_title", "Wonka-v03.03")
        fn = w.call("modes.jjp_new", "Block Rush", "blocks")
        j = w.state("modes")["jjp"]
        assert j["kind"] == "blocks" and j["form"]["code"] == "block_rush" and j["blocks"]["program"]["scripts"]
        assert j["blocks"]["choices"]["kit"] == "jjp" and "switch_target_tv" in j["blocks"]["choices"]["shots"]
        assert _wait(w, lambda: not (w.state("modes")["jjp"].get("code") or {}).get("running")
                     and not w.state("modes")["jjp"]["code"]["stale"])
        assert calls and calls[0][1] == "code"
        assert w.state("modes")["jjp"]["check"]["problems"] == []
        folder = CM.title_dir("Wonka-v03.03")
        assert {"block_rush.blocks.json", "block_rush.cpp", "block_rush.so"} <= set(os.listdir(folder))
        # a change to the blocks writes the C++ again
        prog = j["blocks"]["program"]
        prog["scripts"].append({"hat": {"kind": "every", "seconds": 3}, "do": [{"op": "log", "text": "tick tock"}]})
        w.call("modes.jjp_blocks_save", fn, prog)
        assert "tick tock" in open(os.path.join(folder, "block_rush.cpp"), encoding="utf-8").read()
        assert "tick tock" in w.state("modes")["jjp"]["blocks"]["cpp"]
        w.call("modes.jjp_blocks_save", "9_other.mode", {"scripts": []})          # a mode not open: left alone
        assert "tick tock" in open(os.path.join(folder, "block_rush.cpp"), encoding="utf-8").read()
        # C++
        w.call("modes.jjp_new", "Code Rush", "cpp")
        j = w.state("modes")["jjp"]
        assert j["kind"] == "cpp"
        t = w.call("modes.jjp_code_text")
        assert t["file"] == "code_rush.cpp" and "JM_REGISTER" in t["text"] and "MODE_NAME" not in t["text"]
        assert w.call("modes.jjp_code_save", t["text"] + "\n// mine\n")["ok"]
        assert _wait(w, lambda: not w.state("modes")["jjp"]["code"].get("running") and not w.state("modes")["jjp"]["code"]["stale"])
        kinds = {m["name"]: m["kind"] for m in w.state("modes")["jjp"]["modes"]}
        assert kinds["Block Rush"] == "blocks" and kinds["Code Rush"] == "cpp" and kinds["PAD Mode"] == "form"
        with pytest.raises(Exception):
            w.call("modes.jjp_set", "code", "other")                           # not a form field
        # duplicate carries the code under a name of its own; delete takes it away
        w.call("modes.jjp_duplicate")
        dup = w.state("modes")["jjp"]
        assert dup["form"]["code"] == "code_rush_copy" and os.path.isfile(os.path.join(folder, "code_rush_copy.cpp"))
        monkeypatch.setattr("pinball_decryptor.webui.compat.messagebox.askyesno", lambda *a, **k: True)
        w.call("modes.jjp_delete")
        assert not os.path.exists(os.path.join(folder, "code_rush_copy.cpp"))
        assert os.path.isfile(os.path.join(folder, "code_rush.cpp"))


def test_edit_as_cpp_turns_a_blocks_mode_into_cpp(tmp_path, preview_on, monkeypatch):
    _fake_code(tmp_path, monkeypatch)
    monkeypatch.setattr("pinball_decryptor.webui.compat.messagebox.askyesno", lambda *a, **k: True)
    with web_app(tmp_path, mfr="jjp") as w:
        w.call("ui.select_tab", "modes")
        w.call("modes.jjp_pick_title", "Wonka-v03.03")
        w.call("modes.jjp_new", "Blocky", "blocks")
        w.call("modes.jjp_blocks_to_cpp")
        j = w.state("modes")["jjp"]
        assert j["kind"] == "cpp" and j["blocks"] is None
        assert os.path.isfile(os.path.join(CM.title_dir("Wonka-v03.03"), "blocky.blocks.json.bak"))


def test_the_page_calls_only_rpcs_the_tab_has_and_scrolls():
    from pinball_decryptor.webui import modes_jjp
    src = open(os.path.join(JS, "modes_jjp.js"), encoding="utf-8").read()
    names = set(re.findall(r'"modes\.(jjp_[a-z_]+)"', src))
    assert {"jjp_new", "jjp_code_text", "jjp_code_save", "jjp_blocks_save", "jjp_blocks_to_cpp", "jjp_open_api"} <= names
    for n in names:
        assert callable(getattr(modes_jjp.JjpModesMixin, n, None)), n
    assert re.search(r'key: "blocks".*key: "cpp".*key: "form"', src, re.S)        # the Stern tab's order
    css = open(os.path.join(ROOT, "pinball_decryptor", "webui", "static", "css", "tabs", "modes.css"), encoding="utf-8").read()
    assert ".modes-page.jjpm-page { overflow: auto; }" in css
