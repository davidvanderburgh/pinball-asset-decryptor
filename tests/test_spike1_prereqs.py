"""The Spike 1 rig's build preflight (tools/spike1_emu/prereqs.sh).

Background: a user's first Start on 2026-09-08 died in qemu's configure with
"Python's ensurepip module is not found", under a fixed sentence that named
seven packages and not that one.  The preflight asks for every build tool at
once, before either build starts, and names what THIS machine is missing in
its own package manager's spelling.  These tests hold the two halves of that
promise: the table is the app's own Debian-to-Arch table (no Python needed),
and the script really answers what it says it answers (bash needed).
"""
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.core import pkgnames

REPO = pathlib.Path(__file__).resolve().parent.parent
RIG = REPO / "tools" / "spike1_emu"
PREREQS = RIG / "prereqs.sh"


def _rows():
    """The preflight's table, parsed out of the shell array."""
    src = PREREQS.read_text(encoding="utf-8")
    body = src.split("_S1_PREREQS=(", 1)[1].split("\n)", 1)[0]
    rows = []
    for line in re.findall(r'^\s*"([^"]*)"', body, re.M):
        key, groups, probe, apt, pac, why = line.split("|")
        rows.append({"key": key, "groups": groups.split(), "probe": probe,
                     "apt": apt, "pacman": pac, "why": why})
    assert rows, "the prereq table moved or changed shape"
    return rows


def _bash_runs_scripts():
    """A bash that can run a script fed on stdin - the same guard the
    installer and pkgnames tests use, and for the same reason: a Windows
    `bash` is git-bash on one host and the WSL launcher on the next, and the
    launcher on a runner with no distro answers in UTF-16 and exits 1.  That
    is what yanked v0.187.0."""
    try:
        r = subprocess.run(["bash", "-c", 'echo "${BASH_VERSINFO[0]}"'],
                           capture_output=True, timeout=30)
        return int(r.stdout.decode().strip()) >= 4
    except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired):
        return False


HAS_BASH4 = _bash_runs_scripts()


def _run(script, env=None, timeout=60):
    """Run `script` with the preflight's own text in front of it.

    The file's CONTENT is fed to bash rather than its path, because a Windows
    `bash` is as likely to be WSL's as git-bash's, and WSL's has never heard
    of `C:/Users/...` - `. "<path>"` there is "No such file or directory" and
    every assertion below it fails for a reason that has nothing to do with
    what it was testing.  (The same class of Windows-path break yanked
    v0.184.0.)

    And it goes in on STDIN, not as `-c <script>`: the WSL launcher re-parses
    its command line and expands `$name` itself, so a script handed over as an
    argument arrives with every one of its variables emptied - `case  in`,
    a syntax error in a line that is fine on disk.  The rig has been bitten by
    that launcher before (the JJP executor, which lost `$var` the same way).

    In BYTES, for the last turn of the same screw: text mode on Windows
    rewrites every \\n on the way into the pipe as \\r\\n, and bash reads the
    CR as part of the next word - "$'\\r': command not found", and a function
    body that ends mid-definition."""
    body = PREREQS.read_text(encoding="utf-8") + "\n" + script
    r = subprocess.run(["bash", "-s"], input=body.encode("utf-8"),
                       capture_output=True, timeout=timeout, env=env)
    return subprocess.CompletedProcess(
        r.args, r.returncode,
        r.stdout.decode("utf-8", "replace"),
        r.stderr.decode("utf-8", "replace"))


#: The pkg-config probes are the machine's own, so a test that wants a KNOWN
#: answer says so rather than inheriting whichever of git-bash, WSL or a Linux
#: runner it landed on - one of them has fuse3's headers and the others do not.
_ANSWER = {
    "found": '_s1_have_venv(){ return 0; }\n_s1_have_glib(){ return 0; }\n'
             '_s1_have_fuse3(){ return 0; }\n_s1_have_fetch(){ return 0; }\n'
             'command(){ return 0; }\n',
    "gone": '_s1_have_venv(){ return 1; }\n_s1_have_glib(){ return 1; }\n'
            '_s1_have_fuse3(){ return 1; }\n_s1_have_fetch(){ return 1; }\n'
            'command(){ return 1; }\n',
}


def _bash_has_python3():
    if not HAS_BASH4:
        return False
    r = _run('command -v python3 >/dev/null 2>&1 && echo yes')
    return "yes" in r.stdout


HAS_PY3 = _bash_has_python3()


# --------------------------------------------------------------- the table --

def test_the_pacman_column_is_the_apps_own_translation():
    """Two spellings of one list.  The preflight carries both because it runs
    without Python; core/pkgnames.py is what the app translates with, and a
    row whose pacman name is invented here rather than taken from there is
    how the installer's table and the rig's advice come to disagree."""
    for row in _rows():
        want, aur = pkgnames.to_pacman([row["apt"]])
        assert not aur, f"{row['key']}: {row['apt']} is an AUR package here"
        assert " ".join(want) == row["pacman"], (
            f"{row['key']}: the table says pacman calls {row['apt']} "
            f"'{row['pacman']}', pkgnames says '{' '.join(want)}'")


def test_meson_is_not_asked_for_and_the_venv_is():
    """The two facts the old advice had backwards, kept from coming back.
    qemu 8.2 installs meson itself from a wheel it ships (python/wheels/), so
    a system meson was never the missing piece; the venv it installs that
    wheel INTO is, and on Debian that venv is a separate package."""
    keys = {r["key"] for r in _rows()}
    apt = {r["apt"] for r in _rows()}
    assert "meson" not in apt
    assert "venv" in keys
    assert "python3-venv" in apt


def test_every_row_belongs_to_a_step_that_exists():
    """`qemu` and `shim` are start.sh's two build steps, and nothing else is
    a group: a row filed under a third name would be probed by nobody."""
    for row in _rows():
        assert row["groups"], row["key"]
        assert set(row["groups"]) <= {"qemu", "shim"}, row


def test_the_rig_scripts_read_this_list_rather_than_their_own():
    """One list.  Both build steps go through the preflight, and neither
    carries a package list of its own any more - the sentence that named
    seven packages from memory is what this replaced."""
    start = (RIG / "start.sh").read_text(encoding="utf-8")
    build = (RIG / "build_qemu.sh").read_text(encoding="utf-8")
    assert "prereqs.sh" in start and "s1_prereq_report" in start
    assert "prereqs.sh" in build and "s1_prereq_report" in build
    for src in (start, build):
        assert "libglib2.0-dev pkg-config" not in src, (
            "a hand-written package list is back")


def test_fail_prints_the_message_without_the_exit_code():
    """`fail "..." 2` logged every argument, so the qemu failure reached the
    user ending in a stray "2" that read as part of the package list."""
    start = (RIG / "start.sh").read_text(encoding="utf-8")
    assert 'fail(){ log "ERROR: $1"; exit "${2:-1}"; }' in start


# ------------------------------------------------------------- the script --

@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_a_complete_machine_is_told_nothing():
    """It only speaks when something is missing: a machine that can build
    must not be given a package list to read."""
    r = _run(_ANSWER["found"] + 's1_prereq_report qemu shim; echo "rc=$?"')
    assert "rc=0" in r.stdout, r.stdout
    assert "missing" not in r.stdout


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_the_missing_venv_is_named_with_the_command_that_installs_it():
    """The user's actual failure: everything present except ensurepip."""
    r = _run('_S1_PREREQS=("venv|qemu|@_s1_have_venv|python3-venv||the venv")\n'
             '_s1_have_venv(){ return 1; }\n'
             '_s1_pkg_manager(){ echo apt; }\n'
             '_s1_venv_pkg_alt(){ echo python3.14-venv; }\n'
             'id(){ echo 1000; }\n'
             's1_prereq_report qemu; echo "rc=$?"')
    assert "rc=1" in r.stdout, r.stdout
    assert "python3-venv" in r.stdout
    assert "apt-get install -y python3-venv" in r.stdout
    # The versioned name, for a python that did not come from the distro.
    assert "python3.14-venv" in r.stdout


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_root_is_not_told_to_sudo():
    """start.sh runs as root under WSL, where sudo need not even exist."""
    r = _run('_S1_PREREQS=("ninja|qemu|ninja|ninja-build|ninja|the builder")\n'
             + _ANSWER["gone"] +
             '_s1_pkg_manager(){ echo apt; }\n'
             'id(){ echo 0; }\n'
             's1_prereq_report qemu')
    assert "apt-get install -y ninja-build" in r.stdout
    assert "sudo" not in r.stdout


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_an_arch_machine_is_told_pacmans_names():
    """And the row Arch needs nothing for prints its purpose and no package,
    rather than an empty pair of brackets or - the bug this shape had at
    first - the purpose text read into the package field."""
    r = _run('_S1_PREREQS=("venv|qemu|@_s1_have_venv|python3-venv||the venv"\n'
             '             "glib|qemu|@_s1_have_glib|libglib2.0-dev|glib2|the library")\n'
             '_s1_have_venv(){ return 1; }\n'
             '_s1_have_glib(){ return 1; }\n'
             '_s1_pkg_manager(){ echo pacman; }\n'
             'id(){ echo 1000; }\n'
             's1_prereq_report qemu')
    assert "sudo pacman -S --needed glib2" in r.stdout
    assert "libglib2.0-dev" not in r.stdout
    venv_line = [l for l in r.stdout.splitlines() if l.strip().startswith("venv")]
    assert venv_line, r.stdout
    assert venv_line[0].strip().endswith("the venv"), venv_line
    assert "(" not in venv_line[0], venv_line


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_only_the_step_that_will_run_is_asked_about():
    """A machine with a built emulator and a stale device model is asked
    about the compiler, not about qemu's lexer generator."""
    r = _run(_ANSWER["gone"] + 's1_prereq_missing shim')
    keys = {l.split("|")[0] for l in r.stdout.splitlines() if l}
    assert keys == {"python", "cc", "pkgconfig", "fuse3"}, r.stdout


@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_the_interpreter_chosen_is_one_that_can_build():
    """--python= for qemu's configure: the first interpreter that can make
    the venv, which on a distro that stripped ensurepip out of its newest
    python is the older one beside it."""
    r = _run('_s1_python_candidates(){ printf "%s\\n" python3 python3.12; }\n'
             '_s1_python_can_venv(){ [ "$1" = python3.12 ]; }\n'
             's1_python; echo "rc=$?"')
    assert r.stdout.split()[0] == "python3.12", r.stdout
    assert "rc=0" in r.stdout
    # None of them can: a name that runs is still printed, and the status
    # says so, which is what makes the report speak before configure does.
    r = _run('_s1_python_candidates(){ printf "%s\\n" python3; }\n'
             '_s1_python_can_venv(){ return 1; }\n'
             's1_python; echo "rc=$?"')
    assert r.stdout.split()[0] == "python3"
    assert "rc=1" in r.stdout


@pytest.mark.skipif(not HAS_PY3, reason="no python3 on this bash's PATH")
def test_the_venv_probe_asks_what_qemus_own_mkvenv_asks():
    """ensurepip OR (pip AND setuptools), plus pyexpat - mkvenv.py's own two
    checks.  Asked of a REAL interpreter, this one, so the probe cannot drift
    into testing something python does not have."""
    r = _run('_s1_python_can_venv python3; echo "rc=$?"')
    assert "rc=0" in r.stdout, "this python can make a venv, the probe says no"
    r = _run('_s1_python_can_venv /nonexistent/python3; echo "rc=$?"')
    assert "rc=1" in r.stdout
    r = _run('_s1_python_can_venv ""; echo "rc=$?"')
    assert "rc=1" in r.stdout


# ------------------------------------------------- the shipped binary's stamp --

@pytest.mark.skipif(not HAS_BASH4, reason="no bash 4+ to run the preflight with")
def test_a_sources_hash_does_not_depend_on_who_checked_it_out():
    """★ The first end-to-end install of a real payload failed on this.

    The rig runs out of the app's own directory, which on Windows came from a
    checkout with CRLF line endings, while the CI machine that built and hashed
    the binary had LF.  Same source, different bytes, different sha256 - so the
    stamp said "this binary was built from other sources", and a machine that
    had just downloaded a working device model was asked for a compiler.  Both
    sides strip the CR, so the hash is about the source and not about the
    operating system that checked it out."""
    r = _run(
        'lf=$(mktemp); crlf=$(mktemp)\n'
        'printf "int main(void)\n{\n\treturn 0;\n}\n" > "$lf"\n'
        'sed "s/$/\r/" "$lf" > "$crlf"\n'
        'a=$(s1_source_hash "$lf"); b=$(s1_source_hash "$crlf")\n'
        'raw_a=$(sha256sum "$lf" | cut -d" " -f1)\n'
        'raw_b=$(sha256sum "$crlf" | cut -d" " -f1)\n'
        '[ "$a" = "$b" ] && echo SAME || echo DIFFERENT\n'
        '[ "$raw_a" = "$raw_b" ] && echo RAW-SAME || echo RAW-DIFFERENT\n'
        'rm -f "$lf" "$crlf"')
    assert "SAME" in r.stdout and "DIFFERENT" not in r.stdout.split("SAME")[0], r.stdout
    # And the guard is meaningful: the raw hashes really do differ, so this
    # test would pass for the wrong reason if the fixture stopped making CRLF.
    assert "RAW-DIFFERENT" in r.stdout, r.stdout


def test_the_workflow_hashes_the_source_the_same_way_the_rig_does():
    """The two halves of one comparison, written in different files weeks
    apart: CI computes the stamp, the rig checks it."""
    wf = (REPO / ".github" / "workflows" / "payloads.yml").read_text(encoding="utf-8")
    line = [l for l in wf.splitlines() if "source_sha256 :" in l]
    assert line, "the workflow no longer prints a source hash"
    assert r"sed 's/\r$//'" in line[0], (
        "payloads.yml must normalise line endings before hashing the source, "
        "the same way prereqs.sh's s1_source_hash does: %s" % line[0])


# ------------------------------------------------- one fact, one place ------

#: Scripts allowed to name a rig path without asking prereqs.sh, and why.
#: Nothing is on it: the list exists so that adding one is a decision somebody
#: writes down rather than a line that slips in.
MAY_INVENT_PATHS = {}


def test_no_rig_script_invents_its_own_path_table():
    """Every script that needs to know where the rig lives must ask
    prereqs.sh, not carry a default of its own.

    THIS IS NOT STYLE.  status.sh carried three lines of "where the rig
    lives" and they were right until the user's WORK moved onto its own disk
    (core/rigdata.py) while the binaries the app installs stayed in the home.
    After that it looked for the device model under the work dir, did not find
    it, and reported hwshim_built=0 to the control panel over a RUNNING GAME
    that was using that very shim.  Nothing failed, nothing was logged, and
    the only symptom was a panel quietly describing a rig that was not there.

    A `:?` (require it, fail loudly if absent) is fine and is not a default -
    what this refuses is a script inventing a plausible-looking answer.
    """
    offenders = []
    for script in sorted(RIG.glob("*.sh")):
        if script.name in ("prereqs.sh",) or script.name in MAY_INVENT_PATHS:
            continue
        text = script.read_text(encoding="utf-8", errors="replace")
        for var in ("S1_WORK", "S1_QEMU", "S1_SHIM_DIR", "QEMU_WORK", "S1_HOME"):
            # `: "${VAR:=something}"` is a default; `${VAR:?...}` is a demand.
            if re.search(r':\s*"\$\{%s:=' % var, text):
                if not re.search(r'\.\s+[^\n]*prereqs\.sh', text):
                    offenders.append("%s defaults %s itself" % (script.name, var))
    assert not offenders, (
        "these scripts answer 'where does the rig live' without asking "
        "prereqs.sh, so they will disagree with it the next time a path "
        "moves: %s" % "; ".join(offenders))


def test_the_status_panel_looks_for_the_shim_where_the_app_installs_it():
    """The regression itself, pinned: the device model is OURS and lives in
    the home; the work dir is the USER'S and lives on its own disk.  A status
    line that conflates them reports a rig that is not built while it runs."""
    text = (RIG / "status.sh").read_text(encoding="utf-8")
    assert "$S1_SHIM_DIR/s1hwshim" in text
    assert "$S1_WORK/s1hwshim" not in text
