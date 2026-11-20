"""PR #40 review: a project whose only change is rows ticked on the Service menu tab (placeholders, nothing behind
them yet) is a Write of its own. The Write tab lists those rows as pending, and the Write refused them with "Nothing
to write" until the gate counted them. Proven on the real Godzilla LE 1.16 card: all three rows read back from the
written program with the placeholder values."""
import os

import pytest

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")

pytestmark = pytest.mark.skipif(not os.path.isfile(LE116), reason="no %s on this machine" % os.path.basename(LE116))


def _project(tmp_path, *ticked):
    from pinball_decryptor.core.extract_source import write_extract_source
    from pinball_decryptor.plugins.stern import service_menu as SM
    project = tmp_path / "proj"
    project.mkdir()
    write_extract_source(str(project), LE116)
    if ticked:
        SM.save(str(project), {"on": list(ticked)})
    return str(project)


def _program(card):
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


def test_only_placeholder_rows_still_write(tmp_path):
    from pinball_decryptor.plugins.stern import engine, pipeline
    from pinball_decryptor.plugins.stern import service_menu as SM
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable, menu_label
    project = _project(tmp_path, *SM.OFF_KEYS)
    out = str(tmp_path / "out.raw")
    counts, _am, _vm = engine.write_image(LE116, project, out, log=lambda *_a, **_k: None, update=False)
    assert tuple(counts.menu) == (("MUSIC MODE", True), ("EDITION", True), ("IMAGE SET", True))
    assert pipeline._write_summary(counts) == (
        "3 service menu setting(s) (MUSIC MODE (placeholder), EDITION (placeholder), IMAGE SET (placeholder))")
    t = AdjustmentTable(_program(out))
    rows = {}
    for i in range(1000):
        try:
            label = menu_label(t, i)
        except Exception:                               # noqa: BLE001 - past the table
            continue
        if label in ("MUSIC MODE", "EDITION", "IMAGE SET"):
            rows[label] = t._cstr(t.word(t.field_off(i, "help")), 200)
    assert rows == {k: "1 = NULL1, 2 = NULL2" for k in ("MUSIC MODE", "EDITION", "IMAGE SET")}


def test_nothing_ticked_is_still_nothing_to_write(tmp_path):
    from pinball_decryptor.plugins.stern import engine
    project = _project(tmp_path)
    with pytest.raises(engine.NothingToWrite):
        engine.write_image(LE116, project, str(tmp_path / "out.raw"), log=lambda *_a, **_k: None, update=False)
