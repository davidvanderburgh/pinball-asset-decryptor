"""PAD-360 (DragonRR): the Color profile tab lists the profiles saved earlier, by file
name, loads the one picked, and shows which saved profile and which starting point is in
use."""

from pinball_decryptor.core import colour_profile as cp
from pinball_decryptor.webui.tabs import color as color_tab

GODZILLA = """name = My profile
gamma = 1.12 1.25 1.40
gain = 1.00 0.98 0.95
lift = 0.02 0.02 0.02
saturation = 0.92
"""


def test_saved_profiles_lists_profile_files_by_name(tmp_path):
    (tmp_path / "Godzilla LE.txt").write_text(GODZILLA, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a profile\n", encoding="utf-8")
    (tmp_path / "other.cube").write_text(GODZILLA, encoding="utf-8")
    other = tmp_path / "more"
    other.mkdir()
    cp.save(cp.Profile(name="Dark", saturation=0.5), str(other / "Dark.txt"))
    got = cp.saved_profiles([str(tmp_path), str(other), str(tmp_path)])
    assert [n for n, _p, _prof in got] == ["Godzilla LE", "Dark"]
    assert got[0][2].gamma == (1.12, 1.25, 1.40)


def test_same_numbers_ignores_names_and_file_rounding():
    a = cp.Profile(name="a", gamma=(0.905, 1.0, 1.0))
    b = cp.Profile(name="b", gamma=(0.91, 1.0, 1.0))
    assert cp.same_numbers(a, b)
    assert not cp.same_numbers(a, cp.Profile(gamma=(0.95, 1.0, 1.0)))
    assert not cp.same_numbers(a, None)


def test_pick_from_the_list_and_see_which_is_in_use(tmp_path, monkeypatch):
    from tests.webui_harness import web_app
    lib = tmp_path / "profiles"
    lib.mkdir()
    (lib / "Godzilla LE.txt").write_text(GODZILLA, encoding="utf-8")
    monkeypatch.setattr(color_tab, "default_profiles_dir", lambda: str(lib))
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "output", str(proj))
        w.call("ui.select_tab", "color")
        w.drain()
        assert w.call("color.set_mode", "display") == "display"
        w.drain()
        s = w.state("color")
        assert [o["label"] for o in s["saved"]] == ["Godzilla LE"]
        assert s["saved_on"] == "" and s["preset_on"] == "none"
        path = s["saved"][0]["value"]
        assert w.call("color.use_saved", path) is True
        w.drain()
        s = w.state("color")
        # a copy saved without a name of its own goes by its file's
        assert s["name"] == "Godzilla LE" and s["saved_on"] == path
        assert s["preset_on"] == ""
        assert cp.for_project(str(proj)).gamma == (1.12, 1.25, 1.40)
        # moved off it: the list no longer claims it
        w.call("color.set_params", {"saturation": 0.5})
        w.drain()
        assert w.state("color")["saved_on"] == ""
        w.call("color.preset", "bw")
        w.drain()
        assert w.state("color")["preset_on"] == "bw"
        # a path that is not in the list is refused
        assert w.call("color.use_saved", str(tmp_path / "x.txt")) is False
        # Save a copy lands in the list
        w.window.ask_save = lambda *a, **k: str(lib / "Mono.txt")
        assert w.call("color.save_copy") is True
        w.drain()
        s = w.state("color")
        assert [o["label"] for o in s["saved"]] == ["Godzilla LE", "Mono"]
        assert s["saved_on"].endswith("Mono.txt")
