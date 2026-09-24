"""The Modes tab's "Counts as" table (item 160, webui/modes_stock_remap.py): the rows a project
keeps for the game's own rules, on the web. Runs the real app in-process (tests/webui_harness.py)
against a scratch project; the preview switch is stood in for (a real code is signed)."""
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


def test_the_tab_is_hidden_without_the_preview_switch_so_the_table_is_too(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["modes"]["visible"]
        assert w.state("modes")["remap"]["on"] is False


def test_no_project_and_a_card_without_rules_take_no_row(tmp_path, preview_on):
    with web_app(tmp_path, mfr="stern") as w:
        st = w.state("modes")["remap"]
        assert st["on"] is False and st["msg"].startswith("Open or extract a card project first")
        _project(w, tmp_path / "plain")
        st = w.state("modes")["remap"]
        assert st["on"] is False and "names no card" in st["msg"]
        jaws = _card_project(tmp_path / "jaws", "jaws_le-1_02_0.raw")
        _project(w, jaws)
        st = w.state("modes")["remap"]
        assert st["on"] is False and "names none of the game's own rules" in st["msg"]
        why = w.call("modes.remap_add", 12, "Left ramp", "Left spinner")
        assert "names none" in why and not os.path.exists(os.path.join(str(jaws), "modes", "stock.json"))


def test_a_row_for_ebirah_is_kept_in_the_project_and_written_for_write(tmp_path, preview_on):
    from pinball_decryptor.plugins.stern import stock_remap as SR
    proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")["remap"]
        assert st["on"] is True and st["msg"].startswith("godzilla_le-1.16.port: 2 rule(s)")
        assert {r["id"]: r["label"] for r in st["rules"]} == {12: "Battle vs Ebirah", 4: "Tank attack multiball"}
        assert "Left spinner" in st["shots"] and "Left ramp" in st["shots"] and st["rows"] == []
        assert w.call("modes.remap_add", 12, "Left ramp", "Left spinner") == ""
        st = w.state("modes")["remap"]
        assert [(r["rule"], r["from"], r["to"], r["problem"]) for r in st["rows"]] == [(12, "Left ramp", "Left spinner", "")]
        assert st["rows"][0]["label"] == "Battle vs Ebirah" and st["sel"] == 0
        assert "1 row(s) go on the card with the modes as stock.cfg" in st["msg"]
        assert SR.load(str(proj)) == [{"rule": 12, "from": "Left ramp", "to": "Left spinner"}]
        # what Write renders for the card
        from pinball_decryptor.plugins.stern import mode_project as MP
        port = MP.port_path(MP.profile_for_card("godzilla_le", "1.16"))
        text = SR.render(SR.load(str(proj)), SR.port_rules(port), SR.port_shots(port))
        assert "counts_as 12 Left ramp -> Left spinner" in text
        # a bad row is refused with a sentence and nothing is saved
        why = w.call("modes.remap_add", 12, "Left ramp", "Top spinner")
        assert why.startswith('"Left ramp" already counts as something for rule 12')
        assert w.state("modes")["remap"]["note"] == why
        why = w.call("modes.remap_add", 12, "Left ramp", "0x1800")
        assert "more than one bit" in why
        assert len(SR.load(str(proj))) == 1
        # a second rule may take the same shot; select and remove
        assert w.call("modes.remap_add", 4, "Left ramp", "Godzilla target") == ""
        assert len(w.state("modes")["remap"]["rows"]) == 2
        assert w.call("modes.remap_select", 0) is True and w.state("modes")["remap"]["sel"] == 0
        assert w.call("modes.remap_delete") is True
        st = w.state("modes")["remap"]
        assert [(r["rule"], r["to"]) for r in st["rows"]] == [(4, "Godzilla target")] and st["sel"] is None
        assert w.call("modes.remap_delete", 0) is True
        assert w.state("modes")["remap"]["rows"] == [] and SR.load(str(proj)) == []
        assert not os.path.exists(SR.project_file(str(proj)))
        assert "No rows" in w.state("modes")["remap"]["msg"]


def test_a_rule_is_a_game_mode_in_the_list_and_its_page_carries_its_shots_and_its_rewrite(tmp_path, preview_on):
    """The counts-as rows and the rewrite live on the page of the game mode they change, not in
    the page head: every rule the card's port names is in the list's game group, and its page
    says it is a rule (the Shots and Advanced sections render from modes.remap / modes.rewrite)."""
    proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        st = w.state("modes")
        ids = {int(r["slug"]) for r in st["game_rows"]}
        assert {12, 4} <= ids
        assert w.call("modes.select", "12", "game") is True
        g = w.state("modes")["game_mode"]
        assert g["id"] == 12 and g["rule"] is True
        assert w.call("modes.remap_add", 12, "Left ramp", "Left spinner") == ""
        st = w.state("modes")
        assert [(r["rule"], r["from"], r["to"]) for r in st["remap"]["rows"]] == [(12, "Left ramp", "Left spinner")]
        assert [r["id"] for r in st["rewrite"]["rows"]] == [12, 4]
        assert w.call("modes.remap_delete", 0) is True
        assert w.state("modes")["remap"]["rows"] == []
