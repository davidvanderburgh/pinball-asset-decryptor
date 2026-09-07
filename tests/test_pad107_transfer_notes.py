"""PAD-107 — the no-baseline Mod Transfer says its limits in the LOG.

A user moved his modded Beatles v1.27 card onto stock v1.29 with field 3
("Stock extract of the OLD version") left empty, and mailed in: "It also did
not recognize any audio or text changes."  It never can on that route — but
the only place that said so was a modal he had already answered, so the
finished transfer's "0 audio, ..., 0 text" read as a failure.  The log is what
he still had (and what he attached), so the reason goes there too.
"""

from types import SimpleNamespace

from pinball_decryptor import app as app_mod


def _fake_app(logs):
    """An App stand-in with just what _direct_diff_ready touches."""
    return SimpleNamespace(
        window=SimpleNamespace(
            append_log=lambda text, level="info": logs.append((text, level))),
        _confirm_apply_transfer=lambda *a, **k: logs.append(("CONFIRM", "x")))


def _plan(n_img=2, n_vid=1, **notes):
    base = {"video_old_only": 0, "image_old_only": 0, "audio_unmatched": 0,
            "text_unmatched": 0, "image_rebake_skipped": 0}
    base.update(notes)
    return {"video": {"matched": [{"rel": "video/i%d.mov" % i}
                                  for i in range(n_vid)]},
            "image": {"matched": [{"rel": "images/i%d.png" % i}
                                  for i in range(n_img)]},
            "totals": {"transfer": n_img + n_vid, "flagged": 0, "dropped": 0},
            "notes": base}


def test_direct_diff_logs_the_route_limit(monkeypatch):
    logs = []
    me = _fake_app(logs)
    app_mod.App._direct_diff_ready(me, "old", "new", _plan())

    warnings = [t for t, lv in logs if lv == "warning"]
    assert len(warnings) == 1
    assert "audio and text will transfer as 0" in warnings[0]
    assert "field 3" in warnings[0]
    # And it lands BEFORE the confirm dialog, so answering that can't hide it.
    assert logs[-1][0] == "CONFIRM"


def test_direct_diff_logs_the_unmatched_caveats(monkeypatch):
    logs = []
    me = _fake_app(logs)
    app_mod.App._direct_diff_ready(
        me, "old", "new",
        _plan(audio_unmatched=311, text_unmatched=42, video_old_only=3))

    warnings = [t for t, lv in logs if lv == "warning"]
    assert len(warnings) == 4          # route limit + the three caveats
    joined = "\n".join(warnings)
    assert "311 old sound(s)" in joined
    assert "42 old text string(s)" in joined
    assert "3 old video(s)" in joined


def test_direct_diff_logs_the_limit_even_with_nothing_to_transfer(monkeypatch):
    seen = []
    monkeypatch.setattr(app_mod.messagebox, "showinfo",
                        lambda *a, **k: seen.append(a))
    logs = []
    app_mod.App._direct_diff_ready(_fake_app(logs), "old", "new",
                                   _plan(n_img=0, n_vid=0))

    assert seen                        # the "no differences" dialog still runs
    assert any(lv == "warning" and "field 3" in t for t, lv in logs)
