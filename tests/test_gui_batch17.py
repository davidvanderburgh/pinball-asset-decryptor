"""Guards for feedback batch 17 (the lost-audio post-mortem batch), on the
web UI.

Covers: the Defaults tab's staged Apply-at-Next-Build flow keeping the other
tabs' sidecar sections, the staged-settings reader shrugging off garbage, and
the honest audio preview label for a slot already changed on disk.
"""

import os

from tests.test_webui_audio import _open, _project, _wait, _wav
from tests.test_webui_defaults import _load
from tests.webui_harness import web_app


# ---- Defaults tab: staged Apply-at-Next-Build flow ------------------------

def test_settings_autostage_reset_roundtrip(tmp_path):
    """Batch 21: edits auto-stage and Reset Fields is the one button: back
    to defaults, staging cleared, the Replace tabs' sidecar sections kept."""
    from pinball_decryptor.core import staged_changes

    assets = tmp_path / "extract"
    assets.mkdir()
    # Staging must not wipe the Replace tabs' sections of the sidecar.
    staged_changes.save(str(assets), {"audio": {"audio/a.wav": "C:\\rep.wav"}})
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=assets)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 40)
        w.call("defaults.commit")

        # Staged into the folder's sidecar, other keys intact.
        assert w.window.staged_default_settings(str(assets)) == {
            "AD_FREE_PLAY": 1, "AD_SOUND_MASTER_VOLUME_SETTING": 40}
        data = staged_changes.load(str(assets))
        assert data["audio"] == {"audio/a.wav": "C:\\rep.wav"}

        # A field going back to its default drops OUT of the staged set...
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 30)
        w.call("defaults.commit")
        assert w.window.staged_default_settings(str(assets)) == {
            "AD_FREE_PLAY": 1}

        # ...and Reset Fields clears the staging (other sections intact).
        w.call("defaults.reset")
        assert w.window.staged_default_settings(str(assets)) == {}
        assert staged_changes.load(str(assets))["audio"] == {
            "audio/a.wav": "C:\\rep.wav"}
        assert w.state("defaults")["values"]["AD_FREE_PLAY"] == 0


def test_staged_default_settings_ignores_garbage(tmp_path):
    from pinball_decryptor.core import staged_changes

    assets = str(tmp_path / "extract3")
    os.makedirs(assets)
    with web_app(tmp_path, mfr="stern") as w:
        staged_changes.save(assets, {"settings": {"AD_X": "12",
                                                  "AD_Y": "nope"}})
        assert w.window.staged_default_settings(assets) == {"AD_X": 12}
        staged_changes.save(assets, {"settings": ["not", "a", "dict"]})
        assert w.window.staged_default_settings(assets) == {}


# ---- honest preview labels for changed-on-disk slots ----------------------

def test_audio_pane_title_honest_without_snapshot(tmp_path):
    """A changed-on-disk slot with no .orig snapshot holds replacement bytes:
    the left pane must not call them "Original"."""
    folder = _project(tmp_path)
    rel = "audio/idx0002.wav"
    _wav(os.path.join(folder, "audio", "idx0002.wav"), seconds=0.9, amp=900)
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)

        def _row():
            return {r["k"]: r for r in w.state("audio")["rows"]}.get(rel, {})
        assert _wait(w, lambda: _row().get("t") == "ondisk"), _row()
        w.call("audio.select", [rel])
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["base"]
                     == "Current file (already modified)"), \
            w.state("audio")["panes"]

        # An unchanged slot is always plain "Original".
        w.call("audio.select", ["audio/idx0001 - Jackpot.wav"])
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["base"]
                     == "Original"), w.state("audio")["panes"]
