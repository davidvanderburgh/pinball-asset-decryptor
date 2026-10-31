"""The CGC Write diff must never hand the app's own project files to debugfs.

Reported against v0.152.0 by a tester whose project folder was first extracted
under v0.43: every build died in the Write phase with

    logs/project.log did not land inside the game filesystem
    (expected 13,324 bytes, got NO FILE)
    /home/ubuntu/pin/logs/project.log: File not found by ext2_lookup

``logs/project.log`` is the per-project session log the app itself writes into
the folder it is working on (``core.session_log.set_project``).  It is kept out
of the ``.checksums.md5`` baseline on purpose -- and "not in the baseline" is
precisely what made ``_diff_assets``'s brand-new-file sweep claim it as a game
asset.  debugfs ``write`` cannot create the missing ``logs/`` directory inside
the ext4, so the file never landed and the post-write verify aborted the build.

``build/`` is the same trap with worse odds: it is where Write puts its own
output, so a second build would post a multi-GB installer image into the game
partition.
"""

import os

import pytest

from pinball_decryptor.core.checksums import NON_ASSET_DIRS, md5_file
from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline


def _assets_with_baseline(tmp_path):
    """A minimal CGC extract: one real asset, baselined and then edited."""
    assets = tmp_path / "assets"
    (assets / "data").mkdir(parents=True)
    asset = assets / "data" / "audio_001.wav"
    asset.write_bytes(b"stock bytes")
    baseline = {"data/audio_001.wav": md5_file(str(asset))}
    asset.write_bytes(b"modded bytes")
    return assets, baseline


def test_project_log_is_never_written_back(tmp_path):
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "logs").mkdir()
    (assets / "logs" / "project.log").write_text("session log", encoding="utf-8")

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert "logs/project.log" not in changed
    assert sorted(changed) == ["data/audio_001.wav"]
    assert missing == []


@pytest.mark.parametrize("folder", sorted(NON_ASSET_DIRS))
def test_no_app_written_folder_reaches_the_diff(tmp_path, folder):
    """build/, .hydrate/, card_files/ and logs/ are all ours, not the card's."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / folder).mkdir()
    (assets / folder / "payload.bin").write_bytes(b"app state, not game data")

    changed, _missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert not [rel for rel in changed if rel.startswith(folder + "/")], changed


def test_stale_baseline_entry_under_build_is_ignored(tmp_path):
    """A pre-NON_ASSET_DIRS extract (v0.43 and older) can have baselined the
    build output itself; that entry must not resurrect a multi-GB write."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "build").mkdir()
    out = assets / "build" / "Installer.img"
    out.write_bytes(b"an old build")
    baseline["build/Installer.img"] = md5_file(str(out))
    out.write_bytes(b"a newer build")   # "modified" against that baseline

    changed, missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert "build/Installer.img" not in changed
    assert "build/Installer.img" not in missing


def test_new_file_in_a_folder_the_game_lacks_ships_and_is_named(tmp_path):
    """PAD-876: a mod's own file in a new folder (custom_modes/mod.c) ships --
    the Write creates the folder inside the image -- and the log names it,
    since no on-screen list shows an unbaselined folder."""
    assets, baseline = _assets_with_baseline(tmp_path)
    (assets / "custom_modes").mkdir()
    (assets / "custom_modes" / "mod.c").write_text("int x;", encoding="utf-8")
    (assets / "data" / "audio_002.wav").write_bytes(b"brand new sound")

    lines = []
    changed, _missing = cgc_pipeline._diff_assets(
        str(assets), baseline, log=lambda msg, lvl="info": lines.append(msg))

    assert "data/audio_002.wav" in changed
    assert "custom_modes/mod.c" in changed
    assert any("custom_modes/mod.c" in ln for ln in lines), lines
    assert not any("data/audio_002.wav" in ln for ln in lines), lines


def test_an_extract_inside_the_project_is_not_new_assets(tmp_path):
    """Extract Both drops whole extracts inside a project (PAD-211): another
    card's files, never new folders to create in this one's image."""
    assets, baseline = _assets_with_baseline(tmp_path)
    other = assets / "Stock 1.27"
    (other / "data").mkdir(parents=True)
    (other / "data" / "audio_001.wav").write_bytes(b"other card")
    (other / ".checksums.md5").write_text("", encoding="utf-8")

    changed, _missing = cgc_pipeline._diff_assets(str(assets), baseline)

    assert sorted(changed) == ["data/audio_001.wav"]


class _Ext4Executor:
    """A tiny debugfs stand-in over a set of directories and files."""

    def __init__(self, dirs, owner="1000"):
        self.dirs = set(dirs)
        self.files = {}
        self.owner = owner
        self.commands = []

    def to_exec_path(self, p):
        return "/mnt/c/" + p.replace(os.sep, "/")

    def run(self, bash_cmd, timeout=120):
        self.commands.append(bash_cmd)
        import re
        import shlex
        argv = shlex.split(bash_cmd)
        if argv[0] != "debugfs":
            return ""
        req = argv[argv.index("-R") + 1]
        verb, rest = req.split(" ", 1)
        paths = shlex.split(rest)
        if verb == "stat":
            p = paths[0]
            if p in self.dirs:
                return (f"Inode: 12   Type: directory    Mode:  0755\n"
                        f"User:  {self.owner}   Group:  {self.owner}   "
                        f"Size: 4096\n")
            if p in self.files:
                return (f"Inode: 20   Type: regular    Mode:  0644\n"
                        f"User:     0   Group:     0   "
                        f"Size: {self.files[p]}\n")
            return f"{p}: File not found by ext2_lookup"
        if verb == "mkdir":
            parent = paths[0].rsplit("/", 1)[0] or "/"
            if parent in self.dirs:
                self.dirs.add(paths[0])
            return ""
        if verb == "write":
            src = re.sub(r"^/mnt/c/", "", paths[0]).replace("/", os.sep)
            parent = paths[1].rsplit("/", 1)[0] or "/"
            if parent in self.dirs:
                self.files[paths[1]] = os.path.getsize(src)
            return ""
        return ""


def _write_pipeline(executor, lines=None):
    wp = cgc_pipeline.WritePipeline.__new__(cgc_pipeline.WritePipeline)
    wp.executor = executor
    wp._log = (lambda m, l="info": lines.append(m)) if lines is not None \
        else (lambda *a, **k: None)
    wp._progress = lambda *a, **k: None
    wp._check_cancel = lambda: None
    return wp


def test_write_creates_the_missing_folders(tmp_path):
    """PAD-876: debugfs `write` cannot make a folder, so the build aborted
    with "custom_modes/mod.c did not land inside the game filesystem"."""
    root = "/home/debian/pin"
    ex = _Ext4Executor({"/", "/home", "/home/debian", root, root + "/lib"})
    src = tmp_path / "mod.c"
    src.write_bytes(b"x" * 23413)
    so = tmp_path / "custom.so"
    so.write_bytes(b"y" * 500)
    deep = tmp_path / "deep.bin"
    deep.write_bytes(b"z" * 7)

    lines = []
    _write_pipeline(ex, lines)._write_modified_files(
        "/tmp/inner.img", {"custom_modes/mod.c": str(src),
                           "lib/custom.so": str(so),
                           "a b/c/it's.bin": str(deep)}, root)

    assert ex.files[root + "/custom_modes/mod.c"] == 23413
    assert ex.files[root + "/lib/custom.so"] == 500
    assert ex.files[root + "/a b/c/it's.bin"] == 7
    mkdirs = [c for c in ex.commands if "'mkdir " in c]
    # Only the missing folders, parents first; lib/ already existed.
    assert len(mkdirs) == 3, mkdirs
    assert any("+ folder /home/debian/pin/a b/c" in ln for ln in lines)
    # Each new folder takes the owner of the folder it sits in.
    sifs = [c for c in ex.commands if c.startswith("debugfs -w -R 'sif ")]
    assert len(sifs) == 6 and all(" 1000'" in c for c in sifs), sifs
    # ...and so does each new file (PAD-886), set in one debugfs run.
    owns = [c for c in ex.commands if "debugfs -w -f -" in c]
    assert len(owns) == 3, owns
    assert all("uid 1000'" in c and "gid 1000'" in c and " mode " not in c
               for c in owns), owns


def test_a_folder_debugfs_will_not_make_aborts_the_build(tmp_path):
    class _NoMkdir(_Ext4Executor):
        def run(self, bash_cmd, timeout=120):
            if "'mkdir " in bash_cmd:
                return "mkdir: Could not allocate block"
            return super().run(bash_cmd, timeout)

    root = "/home/debian/pin"
    src = tmp_path / "mod.c"
    src.write_bytes(b"x")
    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        _write_pipeline(_NoMkdir({"/", "/home", "/home/debian", root})) \
            ._write_modified_files(
                "/tmp/inner.img", {"custom_modes/mod.c": str(src)}, root)
    assert "Could not create the folder /home/debian/pin/custom_modes" \
        in str(ei.value)


def test_missing_file_error_names_the_real_cause(tmp_path):
    """The abort used to lead with "ran out of free space" for a file that was
    never in the image at all, sending users off to resize a healthy
    partition."""
    class _NoSuchFileExecutor:
        def run(self, bash_cmd, timeout=120):
            if "stat " in bash_cmd:
                return ("/home/ubuntu/pin/project.log: "
                        "File not found by ext2_lookup")
            return ""

        def to_exec_path(self, p):
            return "/mnt/c/" + p.replace(os.sep, "/")

    src = tmp_path / "project.log"
    src.write_bytes(b"x" * 13324)

    wp = cgc_pipeline.WritePipeline.__new__(cgc_pipeline.WritePipeline)
    wp.executor = _NoSuchFileExecutor()
    wp._log = lambda *a, **k: None
    wp._progress = lambda *a, **k: None
    wp._check_cancel = lambda: None

    with pytest.raises(cgc_pipeline.PipelineError) as ei:
        wp._write_modified_files(
            "/tmp/inner.img", {"project.log": str(src)},
            "/home/ubuntu/pin")

    msg = str(ei.value)
    assert "did not land inside the game filesystem" in msg
    assert "ran out of free space" not in msg
    assert "not the partition running out of space" in msg
