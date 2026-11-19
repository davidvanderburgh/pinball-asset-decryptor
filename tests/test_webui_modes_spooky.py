"""The Modes tab on a Spooky game (PAD-1417, webui/modes_spooky.py + plugins/spooky/custom_modes.py).
Every test runs the real app in-process (tests/webui_harness.py: the settings, and so the mode
folders, are scratch).  The runtime in the game is proven on the Spooky rig; here the tab's model,
Try it's hand-over to the Emulate tab, and the Build on a small stand-in update.
"""
import io
import os
import tarfile
import time

import pytest

from tests.webui_harness import web_app
from pinball_decryptor.plugins.spooky import custom_modes as SM

LABEL = "scooby_doo-2025.12.01.09"
SWAY = "exec --no-startup-id /game/code/uptest/main.x86_64\n"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    from pinball_decryptor.core import preview
    from pinball_decryptor.webui import theme
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    monkeypatch.setattr(theme, "detect_system_theme", lambda: "light")
    monkeypatch.setenv("PAD_SPOOKY_MODES_DIR", str(tmp_path / "spooky_modes"))
    monkeypatch.setenv("PAD_SPOOKY_TRY_DIR", str(tmp_path / "try"))


def _svc(w):
    return w.window.service("modes")


def _spk(w):
    return w.state("modes").get("spk") or {}


def _spooky(w):
    if "spooky" not in {m.key for m in w.window.manufacturers}:
        pytest.skip("no spooky plugin (its crypto dependency is missing)")


def _stock(tmp_path):
    """A stand-in stock update: the launch files and a game."""
    d = tmp_path / "library"
    d.mkdir(exist_ok=True)
    p = d / "v2025.12.01.09.scooby"
    with tarfile.open(str(p), "w:gz") as t:
        for name, data in (("main.x86_64", b"ELF"), ("sway_config", SWAY.encode()), ("i3_config", SWAY.encode())):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    return str(p)


def _open(w, path):
    w.call("ui.select_tab", "modes")
    w.run(lambda: w.window.extract_input_var.set(path))
    w.drain()
    w.run(_svc(w).spk_refresh)
    return _spk(w)


def _wait(w, cond, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_the_tab_is_the_spooky_editor_on_a_spooky_update(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["modes"]["visible"]
        assert _svc(w).rail_needs() == "none"
        s = _open(w, _stock(tmp_path))
        assert s["on"] and s["ns"] == "spk" and s["label"] == LABEL and s["can_run"]
        assert not (w.state("modes").get("jjp") or {}).get("on")
        assert [m["name"] for m in s["modes"]] == ["Snack Attack", "Target Rush"]   # the starter folder
        assert s["check"]["ok"] and s["check"]["n"] == 2
        # the form is the keys the Spooky runtime runs, each once
        keys = [k for g in s["groups"] for k in g["keys"]]
        assert sorted(keys) == sorted(SM.mk().KEYS) and len(keys) == len(set(keys))
        assert s["fields"]["panel"]["choices"] == ["middle", "bottom", "top", "none"]
        assert "right_inlane" in s["names"]["switches"] and "daphne_jackpot" in s["names"]["sound"]
        assert s["points_scale"] == 10
        # the stock update is the selected one; the new one has its name in a folder of its own
        b = s["build"]
        assert b["iso"].endswith("v2025.12.01.09.scooby")
        assert os.path.basename(b["out"]) == "v2025.12.01.09.scooby" and "PAD modes" in b["out"]


def test_an_update_no_port_report_knows_says_so(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        f = tmp_path / "v2020.01.01.01.scooby"
        f.write_bytes(b"\x1f\x8b")
        s = _open(w, str(f))
        assert s["on"] and not s["label"] and "Scooby-Doo 2025.12.01.09" in [t["name"] for t in s["titles"]]


def test_editing_saves_and_checks(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _open(w, _stock(tmp_path))
        svc = _svc(w)
        w.run(lambda: svc.spk_set("points", "250030"))
        s = _spk(w)
        assert s["form"]["points"] == "250030" and not s["check"]["ok"]
        assert any("rounds every award to 100" in p for p in s["check"]["problems"])
        w.run(lambda: svc.spk_set("points", "300000"))
        assert _spk(w)["check"]["ok"]
        w.run(lambda: svc.spk_set("title:panel", "top"))
        assert _spk(w)["title_cfg"]["panel"] == "top" and _spk(w)["title_cfg"]["game"] == "scooby_doo"
        with pytest.raises(Exception):
            w.run(lambda: svc.spk_set("lamps", "shoot_again"))      # not on Spooky games yet
        fn = w.run(lambda: svc.spk_new("Ghost Chase"))
        assert _spk(w)["open"] == fn and len(_spk(w)["modes"]) == 3
        from pinball_decryptor.webui import compat
        monkeypatch.setattr(compat.messagebox, "askyesno", lambda *a, **k: True)
        w.run(svc.spk_delete)
        assert len(_spk(w)["modes"]) == 2


def test_try_it_hands_the_staged_modes_to_the_emulate_tab(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        stock = _stock(tmp_path)
        _open(w, stock)
        emu = w.window.service("emulate_spooky")
        seen = []
        monkeypatch.setattr(emu, "launch_file", lambda path, pad_overlay="": seen.append((path, pad_overlay)) or True)
        assert w.run(_svc(w).spk_try) is True
        path, pad = seen[0]
        assert path == stock
        assert pad == str(tmp_path / "try" / LABEL / "pad")
        for rel in ("padunity.so", "PadModes.dll", "modes/title.cfg", "modes/1_snack_attack.mode"):
            assert os.path.isfile(os.path.join(pad, rel)), rel
        # with a problem, nothing starts
        w.run(lambda: _svc(w).spk_set("start", "nosuch"))
        with pytest.raises(Exception):
            w.run(_svc(w).spk_try)
        assert len(seen) == 1


def test_build_writes_the_update_with_the_modes(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        _open(w, _stock(tmp_path))
        out = str(tmp_path / "out" / "v2025.12.01.09.scooby")
        w.run(lambda: _svc(w).spk_set_out(out))
        w.run(_svc(w).spk_build)
        assert _wait(w, lambda: (_spk(w).get("build") or {}).get("done"))
        b = _spk(w)["build"]
        assert b["ok"], b
        with tarfile.open(out, "r:gz") as t:
            names = t.getnames()
            sway = t.extractfile("sway_config").read()
        assert "pad/padunity.so" in names and "pad/modes/2_target_rush.mode" in names
        assert b"LD_PRELOAD=/game/code/uptest/pad/padunity.so" in sway
        # never over the stock update
        w.run(lambda: _svc(w).spk_set_out(_spk(w)["build"]["iso"]))
        with pytest.raises(Exception):
            w.run(_svc(w).spk_build)


def test_the_emulate_tab_passes_try_its_folder_to_the_rig(tmp_path, monkeypatch):
    from pinball_decryptor.webui import emulate_spooky_core as core
    monkeypatch.setattr(core, "rig_available", lambda: True)
    monkeypatch.setattr(core, "platform_ok", lambda: True)
    seen = []
    monkeypatch.setattr(core, "rig_cmd_root", lambda *a, **k: seen.append((a, k)) or ["true"])
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        emu = w.window.service("emulate_spooky")
        monkeypatch.setattr(emu, "_refuse_off", lambda: False)
        monkeypatch.setattr(emu, "_run_streaming", lambda *a, **k: 1)
        f = tmp_path / "v2025.12.01.09.scooby"
        f.write_bytes(b"x")
        pad = tmp_path / "try" / "pad"
        pad.mkdir(parents=True)
        assert emu.launch_file(str(f), pad_overlay=str(pad))
        end = time.time() + 5
        while not seen and time.time() < end:
            time.sleep(0.02)
        env = seen[0][1]["env"]
        assert any(e.startswith("SPK_PAD_OVERLAY=") and e.rstrip("/").endswith("try/pad") for e in env), env
        # the next plain Start carries none
        seen.clear()
        _wait(w, lambda: not emu._busy, 5)
        assert emu.launch_file(str(f))
        end = time.time() + 5
        while not seen and time.time() < end:
            time.sleep(0.02)
        assert not any(e.startswith("SPK_PAD_OVERLAY=") for e in seen[0][1]["env"])


def test_the_help_is_the_spooky_editors(tmp_path):
    with web_app(tmp_path, mfr="spooky") as w:
        _spooky(w)
        from pinball_decryptor.webui import help_content
        secs = help_content.sections_for("Modes", w.window.current_mfr)
        text = repr(secs)
        assert "Spooky game" in text and "Scooby-Doo 2025.12.01.09" in text and "Try it" in text


def test_the_spooky_page_calls_only_rpcs_the_spooky_tab_has():
    """The JJP page's pieces serve Spooky through R("<name>") = modes.spk_<name>: every call the
    Spooky page makes, itself or through the pieces it renders, is an RPC of SpookyModesMixin."""
    import re
    from pinball_decryptor.webui.modes_spooky import SpookyModesMixin
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "pinball_decryptor", "webui", "static", "js", "tabs", "modes_jjp.js"),
               encoding="utf-8").read()
    bodies = dict(re.findall(r"\nfunction (\w+)\((.*?)(?=\n(?:export )?function |\Z)", src, re.S))
    spk = src[src.index("// ------------------------------------------------------------------ Spooky (PAD-1417)"):]
    shared = ("Hear", "NamePick", "Colour", "Row", "ModeList", "FormGroups", "TitleSettings", "CheckCard", "SoundsRow")
    names = set(re.findall(r'\bR\("([a-z_]+)"\)', spk))
    for f in shared:
        names |= set(re.findall(r'\bR\("([a-z_]+)"\)', bodies[f]))
    names.add("set")                      # the module's set(): R("set")
    assert {"try", "build", "new", "set", "sound_path"} <= names
    for n in names:
        assert callable(getattr(SpookyModesMixin, "spk_" + n, None)), n
