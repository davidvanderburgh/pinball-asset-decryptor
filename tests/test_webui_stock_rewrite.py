"""The Modes tab's "Rewrite in C" rows (item 161, webui/modes_stock_rewrite.py): one CODE row per
rule of the game's own, and the action that starts a rewrite from the SDK's template, on the
web. Runs the real app in-process (tests/webui_harness.py) against a scratch project; the preview
switch is stood in for (a real code is signed)."""
import json
import os

import pytest

from tests.webui_harness import web_app


@pytest.fixture
def preview_on(monkeypatch):
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    return True


def _svc(w):
    return w.window.service("modes")


def _project(w, path):
    os.makedirs(str(path), exist_ok=True)
    svc = _svc(w)

    def go():
        var = svc._project_var()
        try:
            var.set(str(path))
        except Exception:                           # noqa: BLE001 - another tab's trace
            pass
        svc._refresh_all()
    w.run(go)
    w.drain()


def _card_project(path, image_name):
    os.makedirs(str(path), exist_ok=True)
    with open(os.path.join(str(path), ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(str(path), image_name), "input_name": image_name}, f)
    return path


def test_the_tab_is_hidden_without_the_preview_switch_so_the_rows_are_too(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]
        assert w.state("modes")["rewrite"]["on"] is False


def test_no_project_and_a_card_without_rules_have_no_rows(tmp_path, preview_on):
    with web_app(tmp_path, mfr="stern") as w:
        st = w.state("modes")["rewrite"]
        assert st["on"] is False and st["msg"].startswith("Open or extract a card project first")
        _project(w, tmp_path / "plain")
        st = w.state("modes")["rewrite"]
        assert st["on"] is False and "names no card" in st["msg"]
        jaws = _card_project(tmp_path / "jaws", "jaws_le-1_02_0.raw")
        _project(w, jaws)
        st = w.state("modes")["rewrite"]
        assert st["on"] is False and "names none of the game's own rules" in st["msg"]
        why = w.call("modes.rewrite_new", 12)
        assert "names none" in why and not os.path.exists(os.path.join(str(jaws), "modes"))


def test_a_code_row_per_rule_and_a_rewrite_made_from_the_template(tmp_path, preview_on):
    from pinball_decryptor.plugins.stern import stock_rewrite as SW
    proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")["rewrite"]
        assert st["on"] is True and st["msg"].startswith("godzilla_le-1.16.port: 2 rule(s)")
        assert "Every rule plays its own shot logic" in st["msg"]
        assert [(r["id"], r["label"], r["slug"], r["template"]) for r in st["rows"]] == [
            (12, "Battle vs Ebirah", "", "ebirah_rewrite.c"), (4, "Tank attack multiball", "", "")]
        # the tank has no template: refused with a sentence, nothing made
        why = w.call("modes.rewrite_new", 4)
        assert "no template" in why and w.state("modes")["rewrite"]["note"] == why
        assert not os.path.exists(os.path.join(str(proj), "modes"))
        # select Ebirah, make the rewrite: a code mode of the project, listed with the modes
        assert w.call("modes.rewrite_select", 12) is True
        assert w.state("modes")["rewrite"]["sel"] == 12
        assert w.call("modes.rewrite_new") == ""
        st = w.state("modes")
        assert st["rewrite"]["rows"][0]["slug"] == "ebirah_rewrite"
        assert "1 rewritten by this project's code" in st["rewrite"]["msg"]
        assert "Made modes/ebirah_rewrite/ebirah_rewrite.c" in st["rewrite"]["note"]
        assert SW.rewrites(str(proj)) == {12: "ebirah_rewrite"}
        assert os.path.isfile(os.path.join(str(proj), "modes", "ebirah_rewrite", "ebirah_rewrite.c"))
        rows = [r for r in st["rows"] if r["kind"] == "code"]
        assert [(r["slug"], r["chip"]) for r in rows] == [("ebirah_rewrite", "rewrite")]
        assert "Battle vs Ebirah" in rows[0]["chip_tip"]
        assert st["n_code"] == 1
        # a second rewrite of the same rule is refused; the folder is untouched
        why = w.call("modes.rewrite_new", 12)
        assert why.startswith("Battle vs Ebirah is already rewritten by modes/ebirah_rewrite/ebirah_rewrite.c")
        assert SW.rewrites(str(proj)) == {12: "ebirah_rewrite"}
