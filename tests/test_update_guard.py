"""PAD-1585: Stern's own updater guarded on a card PAD built (core/update_guard.py, its multi-boot twin
tools/spike2_emu/updateguard.py, the build step in plugins/stern/pipeline.py)."""
import importlib.util
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import ssh_card, update_guard as U
from pinball_decryptor.core.card_extras import ExtrasError
from pinball_decryptor.plugins.stern import pipeline as P

ROOT = Path(__file__).resolve().parents[1]

#: the shape of Stern's /etc/init.d/update (the strings the guard checks for; not Stern's file)
STERN_LIKE = "\n".join([
    "#!/bin/ash",
    "PROG_NAME=UPDATE",
    "DOWNLOADED_SPK_PATH=/connectivity/update",
    "DOWNLOADED_SPK_AVAILABLE=/connectivity/update/UPDATE_REQUESTED",
    'for i in "$1"/*.[sS][pP][kK] ; do echo $i; done',
    "mount -o remount -o rw $DEST_MOUNT_POINT",
    "/etc/init.d/update_monitor $SPIKE_MENU",
    "",
])


def _twin():
    spec = importlib.util.spec_from_file_location("updateguard", ROOT / "tools" / "spike2_emu" / "updateguard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_multiboot_builders_twin_writes_the_same_block():
    twin = _twin()
    assert twin.GUARD_LINES == U.GUARD_LINES
    assert twin.guard_script(STERN_LIKE) == U.guard_script(STERN_LIKE)
    assert twin.USB_MESSAGE == U.USB_MESSAGE and twin.NET_MESSAGE == U.NET_MESSAGE


def test_guard_goes_in_after_the_shebang_once_and_comes_out_again():
    g = U.guard_script(STERN_LIKE)
    lines = g.split("\n")
    assert lines[0] == "#!/bin/ash" and lines[1] == U.GUARD_BEGIN
    assert U.has_guard(g) and not U.has_guard(STERN_LIKE)
    assert U.guard_script(g) == g                       # idempotent
    assert U.strip_guard(g) == STERN_LIKE
    assert U.stern_shaped(g)
    # Stern's own code below the block is untouched
    assert g.endswith(STERN_LIKE.split("\n", 1)[1])


def test_an_older_guard_block_is_renewed_not_doubled():
    old = U.guard_script(STERN_LIKE).replace("pad_ok() {", "pad_ok_old() {")
    assert not U.has_guard(old)
    renewed = U.guard_script(old)
    assert U.has_guard(renewed) and renewed.count(U.GUARD_BEGIN) == 1


def test_an_updater_that_is_not_sterns_is_left_alone():
    with pytest.raises(U.NotStern):
        U.guard_script("#!/bin/sh\necho someone else's updater\n")
    assert not U.stern_shaped("#!/bin/sh\nmount -o remount -o rw /games\n")


def test_the_screen_words_fit_the_cards_message_screen():
    for words in (U.USB_WORDS, U.NET_WORDS):
        assert len(words) == 4 and all(len(w) <= 16 for w in words)
    assert len(U.USB_MESSAGE) <= 64 and "REMOVE USB DRIVE" in U.USB_MESSAGE
    assert "UPDATED WITH PAD" in U.NET_MESSAGE
    # the block hands both to dprint in double quotes: nothing in them may break that
    for m in (U.USB_MESSAGE, U.NET_MESSAGE):
        assert not set(m) & set('"$`\\')


def test_the_block_hands_over_only_on_the_pass_marker_and_otherwise_ends_the_script():
    body = "\n".join(U.GUARD_LINES)
    assert U.GUARD_LINES[-2] == "if ! pad_guard; then exit 0; fi"
    # Stern's code below runs only when pad_guard returns 0: the pass marker
    assert "'^%s'" % U.PASS_MARKER in body and "grep -qi" in body
    guard = body.split("pad_guard() {", 1)[1]
    assert guard.count("return 0") == 1 and guard.index("return 0") > guard.index('if [ -n "$pad_pass" ]')
    # a refusal never remounts /games or runs Stern's installer
    assert "remount" not in guard and "update_monitor" not in guard and "spike_menu" not in guard


# ---- the build step ----------------------------------------------------------------------------------
def _pipe(tmp_path, logs):
    src = tmp_path / "stock.raw"; src.write_bytes(b"stock")
    out = tmp_path / "build.raw"; out.write_bytes(b"built")
    return SimpleNamespace(output_path=str(out), original_path=str(src), _cancelled=False,
                           _log=lambda m, level="info": logs.append((level, m)))


def test_build_step_guards_an_open_card_and_restamps_the_record(tmp_path, monkeypatch):
    logs, calls, saved = [], [], {}
    pipe = _pipe(tmp_path, logs)
    monkeypatch.setattr(U, "state", lambda p: "open")
    monkeypatch.setattr(U, "apply_to_build", lambda o, out, log=None, cancel=None: calls.append(out) or U.GUARD_TEXT)
    fake = SimpleNamespace(read_build_manifest=lambda p: {"complete": True, "output": "old"},
                           _file_stamp=lambda p: "new", _write_build_manifest=lambda p, rec: saved.update(rec))
    monkeypatch.setattr(P, "engine", fake)
    assert P._guard_updater_on(pipe) == U.GUARD_TEXT
    assert calls == [pipe.output_path] and saved["output"] == "new"
    assert not ssh_card.pending_marker(pipe.output_path).exists()


def test_build_step_failure_quarantines_the_image(tmp_path, monkeypatch):
    pipe = _pipe(tmp_path, [])
    monkeypatch.setattr(U, "state", lambda p: "open")

    def boom(*a, **kw):
        raise ExtrasError("debugfs failed")
    monkeypatch.setattr(U, "apply_to_build", boom)
    with pytest.raises(P.PipelineError):
        P._guard_updater_on(pipe)
    assert not Path(pipe.output_path).exists()
    assert Path(pipe.output_path + ".ssh-incomplete").exists()


def test_build_step_leaves_an_already_guarded_card_and_a_non_card_alone(tmp_path, monkeypatch):
    logs = []
    pipe = _pipe(tmp_path, logs)
    monkeypatch.setattr(U, "apply_to_build", lambda *a, **kw: pytest.fail("rewrote a guarded card"))
    monkeypatch.setattr(U, "state", lambda p: "guarded")
    assert P._guard_updater_on(pipe) == U.GUARD_TEXT
    # what is not a card image (a stand-in build in a test, a device) is not touched and fails nothing
    monkeypatch.undo()
    assert P._guard_updater_on(pipe) == ""
    assert logs[-1][0] == "warning"
    assert Path(pipe.output_path).read_bytes() == b"built"


# ---- the multi-boot builder (tools/spike2_emu/mkmulticard.py), on a real rootfs ----------------------
needs_e2fs = pytest.mark.skipif(
    not (shutil.which("mke2fs") and shutil.which("debugfs") and shutil.which("e2fsck")),
    reason="needs e2fsprogs (mke2fs, debugfs, e2fsck)")


@needs_e2fs
def test_the_multiboot_menu_inject_guards_the_updater_and_the_fingerprint_reads_it_as_sterns(tmp_path):
    import hashlib
    import subprocess
    import sys
    sys.path.insert(0, str(ROOT / "tools" / "spike2_emu"))
    import mkmulticard as mk
    from tests.test_pad742_linked_game_script import _inject, _rootfs
    root = tmp_path / "root" / "etc" / "init.d"
    root.mkdir(parents=True)
    (root / "update").write_text(STERN_LIKE)
    (root / "update").chmod(0o755)
    img = _rootfs(tmp_path, mk)
    _inject(mk, img, tmp_path)
    guarded = mk.debugfs_cat(img, mk.UPDATE_SCRIPT).decode()
    assert U.has_guard(guarded) and U.strip_guard(guarded) == STERN_LIKE
    assert mk.debugfs_stat(img, mk.UPDATE_SCRIPT).get("mode") == 0o755
    again = tmp_path / "again"
    again.mkdir()
    _inject(mk, img, again)                                        # a second inject writes nothing new
    assert mk.debugfs_cat(img, mk.UPDATE_SCRIPT).decode() == guarded
    assert subprocess.run(["e2fsck", "-fn", img], capture_output=True).returncode == 0
    ts = mk._treesync()
    rec = ts.FileRec(hashlib.sha256(guarded.encode()).hexdigest(), len(guarded), 0o100755, 0, 0, 0)
    plain = mk._unguarded_rec(img, 0, os.path.getsize(img), rec)
    assert plain.sha256 == hashlib.sha256(STERN_LIKE.encode()).hexdigest() and plain.size == len(STERN_LIKE)
