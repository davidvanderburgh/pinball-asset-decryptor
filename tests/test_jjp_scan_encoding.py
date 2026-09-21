"""JJP Write scan died on non-ASCII asset names in the baseline.

A tester's Sonic build failed at "Scanning for modified files..." with
"'charmap' codec can't decode byte 0x81".  The baseline ``.checksums.md5``
is written UTF-8, but the JJP scan and mod-pack readers opened it with the
platform default encoding — cp1252 on Windows — so any non-ASCII filename
inside the image (Sonic ships several) killed the whole Build.

The tests force cp1252 as the default text encoding so the regression
reproduces on UTF-8-locale machines too, not just stock Windows.
"""
import builtins
import hashlib
import os
import types

import pytest

from pinball_decryptor.plugins.jjp import pipeline as jjp

# "Á" is C3 81 in UTF-8; 0x81 is undefined in cp1252 — the exact crash byte.
NON_ASCII_REL = "graphics/Ánimo/FirstBall_Ácc.webm"
PLAIN_REL = "sound/vs/plain.ogg"


@pytest.fixture
def charmap_default(monkeypatch):
    """Make encoding-less text open() behave like stock Windows (cp1252)."""
    real_open = builtins.open

    def open_cp1252(file, mode="r", *args, **kwargs):
        if "b" not in mode and kwargs.get("encoding") is None:
            kwargs["encoding"] = "cp1252"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_cp1252)


def _seed_assets(assets, rels):
    """Create *rels* with known bytes and a UTF-8 md5sum-style baseline."""
    lines = []
    for rel in rels:
        path = os.path.join(assets, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"orig")
        lines.append(f"{hashlib.md5(b'orig').hexdigest()}  ./{rel}")
    with open(os.path.join(assets, ".checksums.md5"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _modify(assets, rel):
    with open(os.path.join(assets, *rel.split("/")), "wb") as f:
        f.write(b"MODIFIED")


def _run_scan(assets):
    fake = types.SimpleNamespace(
        assets_folder=str(assets),
        cancelled=False,
        log=lambda *a, **k: None,
        on_progress=lambda *a, **k: None,
    )
    jjp.ModPipeline._phase_scan(fake)
    return fake.changed_files


def test_scan_survives_non_ascii_baseline_names(tmp_path, charmap_default):
    _seed_assets(str(tmp_path), [PLAIN_REL, NON_ASCII_REL])
    _modify(str(tmp_path), NON_ASCII_REL)

    changed = _run_scan(str(tmp_path))

    assert [rel for rel, _ in changed] == [NON_ASCII_REL]


def test_export_mod_pack_survives_non_ascii_baseline_names(
        tmp_path, charmap_default):
    _seed_assets(str(tmp_path), [PLAIN_REL, NON_ASCII_REL])
    with open(tmp_path / "fl_decrypted.dat", "wb") as f:
        f.write(b"fl")
    _modify(str(tmp_path), NON_ASCII_REL)

    n, _ = jjp.export_mod_pack(str(tmp_path), str(tmp_path / "pack.zip"))

    assert n == 1


# --------------------------------------------------------------------------
# The app's own log is not one of the card's assets (PAD-192)
#
# core.session_log mirrors every line into <project>/logs/project.log while
# the build runs.  JJP walks the project folder itself instead of going
# through core.checksums, so it never applied NON_ASSET_DIRS: the log went
# into the baseline, came back "Modified" on every later run (it is appended
# to continuously), and the write stage then failed it with "not found in
# fl.dat" -- a red [ERROR] and an inflated FAILED count on every single
# build.  cooltoy's Sonic log shows "557/562 replaced and verified (5
# FAILED)" where only four were his clips.
# --------------------------------------------------------------------------

PROJECT_LOG_REL = "logs/project.log"


def test_the_apps_own_project_log_is_never_scanned_as_an_asset(tmp_path):
    """Even when a baseline written by an older version still lists it."""
    _seed_assets(str(tmp_path), [PLAIN_REL, PROJECT_LOG_REL])
    _modify(str(tmp_path), PROJECT_LOG_REL)      # the app appends as we scan
    _modify(str(tmp_path), PLAIN_REL)

    changed = _run_scan(str(tmp_path))

    assert [rel for rel, _ in changed] == [PLAIN_REL], \
        "logs/ is the app's own folder inside the project, not the card's"


def test_a_cards_own_nested_logs_folder_is_still_an_asset(tmp_path):
    """Only the TOP-LEVEL logs/ is ours.  The card's tree really does carry
    directories by that name further down, and pruning those would quietly
    drop real assets from the build."""
    nested = "system/var/logs/boot.cfg"
    _seed_assets(str(tmp_path), [PLAIN_REL, nested])
    _modify(str(tmp_path), nested)

    changed = _run_scan(str(tmp_path))

    assert [rel for rel, _ in changed] == [nested]
