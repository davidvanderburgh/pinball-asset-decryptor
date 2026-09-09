"""The image must carry what the pipelines ask for.

The app now runs EVERY WSL path in the PAD Runtime, not only the two emulator
rigs.  That is only safe while the image actually contains the tools those
paths shell out to - otherwise installing our Linux takes a working machine
backwards, and does it silently, halfway through a Write.

There are two lists of those tools and they were written years apart:

  * installer/install_prerequisites.ps1 - the WslPackages table per
    manufacturer, which is what the app installs into a user's own distro;
  * tools/runtime/Dockerfile - what we bake into ours.

Nothing but this file makes them agree.  A package added to a manufacturer and
forgotten in the image would pass every other test, build a perfectly good
image, and fail on the machine of whoever first opened that manufacturer.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
PS1 = REPO / "installer" / "install_prerequisites.ps1"
DOCKERFILE = REPO / "tools" / "runtime" / "Dockerfile"
GDRE = REPO / "installer" / "install_gdre.sh"

#: ALREADY IN THE BASE IMAGE, so the Dockerfile never names them.  Both are
#: Priority: required in Ubuntu - a rootfs without them would not boot - and
#: both are checked by the image's own selftest in runtime.yml rather than
#: taken on trust here.  Anything NOT on this list has to be installed.
FROM_THE_BASE_IMAGE = {"tar", "mount"}


def _installer_wsl_packages():
    """Every apt package name the installer would put into a user's distro.

    Read out of the PowerShell rather than restated, because a list restated
    is a list that drifts.  Entries look like::

        @{ probe="xorriso"; pkg="xorriso"; label="xorriso"; reason="..." }

    and a `pkg` may name several packages at once ("gcc libc6-dev"), which is
    why this splits on whitespace.  Only the WslPackages tables are wanted:
    HostPackages are winget names and PipPackages are pip names, neither of
    which apt has ever heard of.
    """
    text = PS1.read_text(encoding="utf-8", errors="replace")
    names = set()
    for block in re.findall(r"WslPackages\s*=\s*@\((.*?)\n        \)",
                            text, re.S):
        for pkg in re.findall(r'pkg="([^"]+)"', block):
            names.update(pkg.split())
    return names


def test_the_installer_tables_are_readable():
    """A guard on the guard: if the PowerShell is reshaped so the regex above
    matches nothing, every other test in this file passes vacuously."""
    names = _installer_wsl_packages()
    assert len(names) >= 15, (
        "only %d WSL packages parsed out of install_prerequisites.ps1 - the "
        "table's shape changed and this file is now checking nothing"
        % len(names))
    # Spot-check one from each end of the file, so a partial match is caught.
    assert {"e2fsprogs", "busybox-static"} <= names


def _image_installs():
    """Every word the Dockerfile actually runs, comments removed.

    The comments are removed on purpose and it is not tidiness: this file's
    header explains at length WHY each package is there, so a package deleted
    from the install list while its paragraph stayed would otherwise still
    look present.  Package names appear one per line and several per line
    (`make patch zstd xxd file`), so this tokenises rather than matching
    line starts - which is what the first version of this test did, and it
    reported gcc's own libc6-dev missing from an image that installs it."""
    lines = [ln for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith("#")]
    return set(" ".join(lines).replace("\\", " ").split())


def test_the_image_carries_every_package_the_installer_would_install():
    missing = sorted(_installer_wsl_packages() - FROM_THE_BASE_IMAGE
                     - _image_installs())
    assert not missing, (
        "install_prerequisites.ps1 installs these into a user's own distro, "
        "and tools/runtime/Dockerfile does not put them in ours: %s.\n"
        "The app routes every WSL path into the runtime, so a user who "
        "installs it would lose these.  Add them to the Dockerfile, cut a new "
        "runtime-N, and bump RUNTIME_VERSION." % ", ".join(missing))


def test_the_image_installs_gdre_tools_by_running_the_apps_own_script():
    """Not by a copy of it.  The version, URL and SHA-256 live in one file;
    a Dockerfile that repeated them would drift the first time one changed,
    and the drift would be a DIFFERENT TOOL on the runtime than on a user's
    own distro - which is the whole failure this runtime exists to end."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "install_gdre.sh" in dockerfile
    assert "GDRETools/gdsdecomp" not in dockerfile, (
        "the Dockerfile has grown its own copy of the GDRE download - it must "
        "run installer/install_gdre.sh instead")
    # And the script it runs still verifies what it downloaded.
    gdre = GDRE.read_text(encoding="utf-8")
    assert re.search(r'^SHA256="[0-9a-f]{64}"', gdre, re.M)
    assert "sha256sum" in gdre


def test_the_workflow_stages_that_script_into_the_build_context():
    """The Dockerfile COPYs payload/install_gdre.sh, and docker's build
    context is tools/runtime - so a COPY of a file nobody put there fails the
    build.  Cheap to assert, and the failure it prevents costs a CI run."""
    workflow = (REPO / ".github" / "workflows" / "runtime.yml").read_text(
        encoding="utf-8")
    assert "installer/install_gdre.sh tools/runtime/payload/" in workflow
    assert "COPY payload/install_gdre.sh" in DOCKERFILE.read_text(
        encoding="utf-8")


# ------------------------------------------- and what the CODE actually runs --
#
# The tables above are what the app INSTALLS.  They are not what it RUNS: half
# the commands the pipelines shell out to were never in any prerequisite table,
# because every desktop Linux has them and nobody had to think about it.  That
# assumption stopped being safe the moment the app stopped using the user's
# Linux and started shipping its own - and it was not safe: reading every
# command the pipelines hand to the executor turned up rsync and partprobe
# missing from the image.  rsync is the one that mattered: it is how the JJP
# extract moves the FINISHED game image to the output folder, and that step
# logs a warning rather than failing, so a twenty-minute extract would have
# reported success over an empty folder.

#: command -> the apt package that provides it, for everything NOT in the base
#: image.  A command in neither this table nor FROM_THE_BASE_IMAGE_COMMANDS
#: fails the test on purpose: somebody has to say where it comes from.
COMMAND_PACKAGE = {
    "cwebp": "webp",
    "debugfs": "e2fsprogs", "dumpe2fs": "e2fsprogs", "e2fsck": "e2fsprogs",
    "ffprobe": "ffmpeg", "ffmpeg": "ffmpeg",
    "gcc": "gcc",
    "gpg": "gnupg",
    "killall": "psmisc", "fuser": "psmisc",
    "partprobe": "parted",
    "python3": "python3",
    "rsync": "rsync",
    "xorriso": "xorriso",
    "xxd": "xxd",
    "zstd": "zstd",
    "pigz": "pigz",
    "curl": "curl", "unzip": "unzip",
    "partclone.ext4": "partclone",
    "nm": "gcc",              # binutils, pulled in by gcc
}

#: In the base image, so the Dockerfile never names them: coreutils,
#: util-linux, debianutils, procps, bash, mount, sed, grep, tar, findutils.
#: Checked for real by the image's own selftest in runtime.yml, not assumed.
FROM_THE_BASE_IMAGE_COMMANDS = {
    "base64", "bash", "cat", "cd", "chroot", "command", "cp", "cut", "dd",
    "df", "du", "echo", "find", "findmnt", "grep", "head", "ls", "lsblk",
    "md5sum", "mkdir", "mount", "mountpoint", "mv", "pgrep", "rm", "rmdir",
    "sed", "sort", "stat", "sync", "tail", "test", "true", "truncate",
    "umount", "wc", "which", "losetup", "apt-get", "tar",
}

#: Words the scan picks up that are NOT commands: shell variables holding a
#: path (`$img_exec`), and the two package managers named only in a macOS or
#: Alpine branch that never runs in this image.
NOT_COMMANDS = {"apk", "dest", "emmc_exec", "image_exec", "img_exec",
                "inner_exec", "out_exec", "p3_exec"}


def _commands_the_pipelines_run():
    """Every word sitting where a COMMAND would in the shell strings handed to
    the executor: the start of the string, or after ``|``, ``&&``, ``;``.

    Read out of the source rather than listed, for the same reason the
    installer's table is: a list of what the code runs, maintained by hand
    beside the code that runs it, is a list that goes stale silently."""
    found = set()
    roots = [REPO / "pinball_decryptor" / "plugins",
             REPO / "pinball_decryptor" / "core"]
    files = [f for r in roots for f in r.rglob("*.py")]
    call = re.compile(
        r'(?:self\.)?executor\.(?:run|stream|popen_binary)\(\s*(?:f?["\'])(.*?)["\']',
        re.S)
    for f in files:
        for m in call.finditer(f.read_text(encoding="utf-8", errors="replace")):
            for tok in re.split(r'\|\||&&|[|;&\n(]', m.group(1)):
                tok = re.sub(
                    r'^(?:sudo\s+|env\s+|[A-Z_][A-Z0-9_]*=\S*\s+)+', '',
                    tok.strip())
                word = re.match(r'^([a-z][a-z0-9_.+-]{1,24})\b', tok)
                if word:
                    found.add(word.group(1))
    return found - NOT_COMMANDS


def test_the_scan_still_finds_the_commands():
    """A guard on the guard: a refactor that changes how pipelines call the
    executor would leave this whole check matching nothing."""
    cmds = _commands_the_pipelines_run()
    assert len(cmds) >= 40, "only %d commands found - the scan is broken" % len(cmds)
    assert {"debugfs", "rsync", "losetup"} <= cmds


def test_the_image_can_run_every_command_the_pipelines_call():
    installed = _image_installs()
    unknown, missing = [], []
    for cmd in sorted(_commands_the_pipelines_run()):
        if cmd in FROM_THE_BASE_IMAGE_COMMANDS:
            continue
        pkg = COMMAND_PACKAGE.get(cmd)
        if pkg is None:
            unknown.append(cmd)
        elif pkg not in installed:
            missing.append("%s (needs %s)" % (cmd, pkg))
    assert not unknown, (
        "the pipelines run these and nothing says where they come from: %s.\n"
        "Add each to COMMAND_PACKAGE with its apt package, or to "
        "FROM_THE_BASE_IMAGE_COMMANDS if Ubuntu's base image carries it."
        % ", ".join(unknown))
    assert not missing, (
        "the pipelines run these and the runtime image cannot: %s.\n"
        "The app sends every WSL command into that image, so this is a "
        "pipeline that fails on a user's machine - and some of these steps "
        "only log a warning, which is worse. Add them to "
        "tools/runtime/Dockerfile, cut a new runtime-N, bump RUNTIME_VERSION."
        % ", ".join(missing))
