"""PAD-1486: "Co op mode not showing under network tab": with a Spike 2 card picked but its project not extracted
yet, the Score feed and Online co-op boxes just vanished. The Network tab now says why in their place."""
from pinball_decryptor.webui.tabs.network import NetworkTab as NS


def test_the_network_tab_says_why_online_coop_is_not_shown(tmp_path):
    from tests.test_webui_modes import _card_project, _project
    from tests.webui_harness import web_app
    proj = _card_project(tmp_path / "le", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        missing = str(tmp_path / "not extracted yet")       # named on the Extract tab, not extracted into yet
        w.run(lambda: w.window.write_assets_var.set(missing))
        w.drain()
        w.call("ui.select_tab", "network")
        n = w.state("network")
        assert n["online"] is None and n["online_missing"] == NS.MISSING_NOT_MADE
        _project(w, proj)                                   # extracted: the boxes show, no note
        w.call("ui.select_tab", "extract")
        w.call("ui.select_tab", "network")
        n = w.state("network")
        assert n["online"] is not None and n["online_missing"] == ""


def test_the_note_names_each_reason(tmp_path):
    class Mfr:
        key, _era = "stern", "spike2"

    class Fake:
        mfr = Mfr()
        _online_missing = NS._online_missing
        MISSING_NO_PROJECT, MISSING_NOT_MADE, MISSING_TITLE = NS.MISSING_NO_PROJECT, NS.MISSING_NOT_MADE, NS.MISSING_TITLE

    f = Fake()
    assert f._online_missing("") == NS.MISSING_NO_PROJECT
    assert f._online_missing(str(tmp_path / "nope")) == NS.MISSING_NOT_MADE
    assert "cannot tell which game" in f._online_missing(str(tmp_path))          # a folder with no card behind it
    Mfr._era = "spike3"
    assert f._online_missing("") == ""                                           # not offered: no note
    Mfr.key = "spooky"
    assert f._online_missing("") == ""
