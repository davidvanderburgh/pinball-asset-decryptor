"""A ticked Music Mode / Edition / Image Set row with nothing behind it yet still goes on the card, with placeholder
values (Simon: "I should be able to add service menu items for these things even if they don't work because they
don't yet exist")."""
from pinball_decryptor.plugins.stern import service_menu as SM


def _tick(project, *keys):
    data = SM.load(project)
    data["on"] = list(keys)
    SM.save(project, data)


def test_unticked_rows_stay_off(tmp_path):
    assert [w[0] for w in SM.wanted(str(tmp_path))] == []


def test_ticked_rows_without_content_are_placeholders(tmp_path):
    project = str(tmp_path)
    _tick(project, "music_mode", "image_set")
    got = {w[0]: w for w in SM.wanted(project)}
    assert set(got) == {"music_mode", "image_set"}
    for key in got:
        assert got[key][1] == len(SM.PLACEHOLDER_NAMES)
        assert list(got[key][2]) == list(SM.PLACEHOLDER_NAMES)


def test_placeholder_jobs_skip_settings_the_project_has(tmp_path):
    project = str(tmp_path)
    _tick(project, "music_mode", "image_set")
    jobs = SM.placeholder_jobs(project, {"music_mode"}, lambda *a, **k: None)
    assert [j.KEY for j in jobs] == ["image_set"]
    assert all(j.placeholder for j in jobs)


def test_service_menu_tab_rows_are_always_tickable(tmp_path):
    from pinball_decryptor.webui.tabs.svcmenu import ServiceMenuTab
    project = str(tmp_path)
    _tick(project, "image_set")
    rows = {r["key"]: r for r in ServiceMenuTab._settings(object.__new__(ServiceMenuTab), project)}
    for key in SM.OFF_KEYS:
        assert rows[key]["can"] is True
    assert rows["image_set"]["on"] is True and "placeholder" in rows["image_set"]["note"]
    assert rows["music_mode"]["on"] is False and "Audio tab" in rows["music_mode"]["note"]   # where it is made
