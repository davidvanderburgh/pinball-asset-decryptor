"""Service menu rows count as a change (Simon: with only Service menu rows ticked the Write tab's change scan said
"0 total change(s)" and the finished Write "Wrote no changes", though the Write had put the rows on the card)."""
from types import SimpleNamespace

from pinball_decryptor.plugins.stern import engine, menu_settings, pipeline
from pinball_decryptor.plugins.stern import service_menu as SM
from pinball_decryptor.webui import write_scan

STERN = SimpleNamespace(key="stern")


def _tick(project, *keys):
    data = SM.load(project)
    data["on"] = list(keys)
    SM.save(project, data)


def test_ticked_rows_are_pending_changes(tmp_path):
    project = str(tmp_path)
    assert write_scan.service_menu_rows(STERN, project) == []
    _tick(project, "music_mode", "image_set")
    rows = write_scan.service_menu_rows(STERN, project)
    assert [r[2] for r in rows] == [write_scan.PENDING_SERVICE_MENU] * 2
    assert all("placeholder (NULL1, NULL2)" in r[0] for r in rows)
    assert any("MUSIC MODE" in r[0] for r in rows) and any("IMAGE SET" in r[0] for r in rows)


def test_rows_are_stern_only(tmp_path):
    project = str(tmp_path)
    _tick(project, "music_mode")
    assert write_scan.service_menu_rows(SimpleNamespace(key="jjp"), project) == []
    assert write_scan.service_menu_rows(None, project) == []


def test_ticking_a_row_changes_the_fingerprint(tmp_path):
    project = str(tmp_path)
    window = SimpleNamespace()
    before = write_scan.fingerprint(window, project, 0, False)
    _tick(project, "edition", "image_set")
    assert write_scan.fingerprint(window, project, 0, False) != before


def test_counts_carry_the_menu_through_a_rebuild():
    counts = engine._with_stock_modes((0, 0, 0, 0), 0, menu=[("IMAGE SET", True)])
    assert engine._with_stock_modes(counts, 0).menu == (("IMAGE SET", True),)
    assert engine._with_stock_modes((0, 0, 0, 0)).menu == ()


def test_menu_done_names_the_rows_that_went_on():
    log = lambda *a, **k: None                                  # noqa: E731
    went, refused, ph = engine._CoopMenu(log), engine._HandicapMenu(log), engine._ImageSetMenu(["N1", "N2"], log)
    went.ok, refused.ok, ph.ok, ph.placeholder = True, False, True, True
    assert engine._menu_done(engine._MenuJobs(went, refused, ph)) == [("CO-OP PLAY", False), ("IMAGE SET", True)]
    assert engine._menu_done(None) == []


def test_summary_names_the_menu_rows():
    counts = engine._with_stock_modes((0, 0, 0, 0), 0, menu=[("MUSIC MODE", True), ("CO-OP PLAY", False)])
    got = pipeline._write_summary_with_modes(counts, None)
    assert got != "no changes"
    assert got == "2 service menu setting(s) (MUSIC MODE (placeholder), CO-OP PLAY)"
    with_modes = pipeline._write_summary_with_modes(counts, {"names": ["Kaiju"]})
    assert with_modes.endswith("and 2 service menu setting(s) (MUSIC MODE (placeholder), CO-OP PLAY)")
    assert pipeline._write_summary(engine._with_stock_modes((0, 0, 0, 0))) == "no changes"


def test_caption_of():
    assert menu_settings.caption_of("coop_play") == "CO-OP PLAY"
    assert menu_settings.caption_of("something_new") == "SOMETHING NEW"
