"""What an ELEVATED emulator run leaves behind in a human's home, and whether
the next ordinary run can get out of it.

THE FAULT, reported 2026-09-15 against Ubuntu 26.04 (PAD-182).  Three starts,
three different deaths, all on one machine whose only real problem was files
owned by root in the reporter's own home:

    [build] .../build.sh: line 47: /home/ales/spike2root/lib/hwshim.srcs: Permission denied
    tar: ./usr/bin/fuse2fs: Cannot open: File exists        (x20, then)
    [card] could not get fuse2fs
    mkdir: Permission denied
    [card] cannot create /home/ales/card/metallica_spike-1_04_PoMC
    [watch] could not mount .../metallica_spike-1_04_PoMC.raw

Not one of those lines says the word root, so not one of them could be acted
on.  He then tried the only thing that makes it worse - ``sudo`` on the whole
AppImage - and got a fourth death:

    env: '/root/padglhost': Permission denied
    [watch] the software renderer died too, so this is not the GPU

WHERE THE ROOT-OWNED FILES CAME FROM, and it is the rig's own doing.  Three
scripts had a ``give_back()`` whose whole job is handing root's output back to
the human, and two of them asked ``stat -c %U "$HOME"``.  Under ``sudo`` $HOME
is /root, which root owns - so the hand-back returned having chowned NOTHING on
exactly the runs it exists for, while $PAD_HOME resolved to the human's home
correctly one line above and root wrote there anyway.  padpath.sh's header has
stated the rule since 2026-08-11 ("ROOT IS ELEVATION, NOT OWNERSHIP: the rig
belongs to a human's home"); only the READS had been converted to it.

SO THIS FILE HOLDS BOTH HALVES.  pad_give_back stops the trap being set;
pad_can_write gets a machine out of one that is already set, because the first
cannot help a machine that is already poisoned - which is every machine that
ran a release before this one.

RUN, NOT READ, wherever the claim is about a permission - the same rule
test_spike2_drop_target.py works to.  A grep for the right words passes on code
that asks about the wrong path, and asking about the wrong path is the entire
bug.  Ownership needs a filesystem with real modes, so those tests make one
under /tmp inside bash and skip themselves when the shell cannot (Git Bash on
the Windows runner, where the executable and write bits do not mean this).
"""
import os
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

#: The rig's run path - every script a start actually executes.  padpath.sh is
#: deliberately absent: it is where $HOME is READ to derive $PAD_HOME, which is
#: the one legitimate use of it in the rig.
_RUN_PATH = [
    "watch.sh", "killgame.sh", "alive.sh", "cardmount.sh", "runbridge.sh",
    "run_game.sh", "build.sh", "buildbridge.sh", "buildselect.sh",
    "overrides.sh", "ensurebuild.sh", "ensureselect.sh", "getboot.sh",
    "playaudio.sh", "autoattract.sh", "swexercise.sh", "restorestate.sh",
]


def _src(name):
    with open(os.path.join(RIG, name), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _sh(script, timeout=60):
    """Run `script` in bash and hand back (rc, stdout+stderr)."""
    out = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                         timeout=timeout)
    return out.returncode, out.stdout + out.stderr


#: Can this shell see real ownership and real write bits?  /mnt/c through WSL
#: and everything under Git Bash cannot, and a test that silently passes there
#: would be worse than one that says it did not run.
_MODES_PROBE = r'''
d=$(mktemp -d /tmp/pad182probe.XXXXXX) || exit 1
mkdir -p "$d/shut" && chmod 500 "$d/shut" || exit 1
if [ -w "$d/shut" ]; then rm -rf "$d"; exit 1; fi
rm -rf "$d"; exit 0
'''


def _has_modes():
    if not BASH:
        return False
    try:
        return _sh(_MODES_PROBE, timeout=30)[0] == 0
    except Exception:
        return False


needs_modes = pytest.mark.skipif(
    not _has_modes(),
    reason="this shell has no real file modes (Git Bash / drvfs)")


# --------------------------------------------------------------------------
# THE HAND-BACK ASKS THE RIG'S HOME, NOT THE PROCESS'S
# --------------------------------------------------------------------------

def _give_back_run(home_owner, home="/home/ales", pad_home=None, args=""):
    """pad_give_back as root, with `id`, `stat` and `chown` answering for us.

    Stubs as shell functions rather than executables on PATH, for the reason
    test_spike2_drop_target.py gives: the executable bit means something
    different on each shell this suite runs under.
    """
    script = "\n".join([
        "set -u",
        "HOME=%s" % home,
        "PAD_HOME=%s" % (pad_home or "/home/ales"),
        "id() { echo 0; }",
        'stat() { case "$3" in',
        "  %s) echo %s ;;" % (pad_home or "/home/ales", home_owner),
        "  /root) echo root ;;",
        "  *) echo 'stat: no such file' >&2; return 1 ;;",
        "esac; }",
        'chown() { echo "CHOWN $*"; }',
        _padpath_func("pad_owner"),
        _padpath_func("pad_give_back"),
        "pad_give_back %s" % args,
        'echo "RC $?"',
    ])
    rc, out = _sh(script)
    assert rc == 0, out
    return out


def _padpath_func(name):
    """One function lifted out of padpath.sh verbatim.

    Sourcing the whole file would drag in its WSL probes and its path
    translation; the claim here is about four lines of ownership logic, so
    those four lines are what runs.
    """
    src = _src("padpath.sh")
    i = src.index("\n%s() {" % name) + 1
    end = src.index("\n}\n", i) + 3
    body = src[i:end]
    assert body.startswith("%s() {" % name) and body.rstrip().endswith("}"), \
        "%s no longer looks like a function" % name
    return body


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_hand_back_asks_pad_home_and_not_the_process_home():
    """PAD-182 itself, and the whole ticket is in this one test.

    Root, $HOME=/root (which is how sudo arrives), a human's rig at
    /home/ales.  The old copies asked `stat -c %U "$HOME"`, got "root", and
    returned without chowning anything - so root's files stayed root's and
    every ordinary run afterwards died on a permission.
    """
    out = _give_back_run("ales", home="/root", pad_home="/home/ales",
                         args='"/home/ales/card"')
    assert "CHOWN ales /home/ales/card" in out, out
    # And the same call must have been a no-op before this fix, which is the
    # only reason the reporter's machine could get into that state at all.
    assert "stat -c %U \"$HOME\"" not in _padpath_func("pad_give_back")


@pytest.mark.skipif(not BASH, reason="no bash")
def test_a_genuinely_root_owned_home_is_still_left_alone():
    """pad_stage's reason: chowning root's own files to root is a no-op with a
    recursive walk attached, and a root-default distro is a real layout."""
    out = _give_back_run("root", home="/root", pad_home="/root",
                         args='"/root/card"')
    assert "CHOWN" not in out, out
    assert "RC 0" in out, "and it must not fail the caller - callers use set -e"


@pytest.mark.skipif(not BASH, reason="no bash")
def test_an_ordinary_run_hands_nothing_back():
    """There is nothing to hand back and no right to do it."""
    script = "\n".join([
        "set -u", "HOME=/home/ales", "PAD_HOME=/home/ales",
        "id() { echo 1000; }",
        'stat() { echo ales; }',
        'chown() { echo "CHOWN $*"; }',
        _padpath_func("pad_owner"),
        _padpath_func("pad_give_back"),
        'pad_give_back "/home/ales/card"', 'echo "RC $?"',
    ])
    rc, out = _sh(script)
    assert rc == 0 and "CHOWN" not in out, out
    assert "RC 0" in out


@pytest.mark.skipif(not BASH, reason="no bash")
def test_recursive_is_asked_for_rather_than_guessed():
    """A stamp is one file and an unpacked fuse2fs prefix is a tree; -R over a
    15 GB image cache would be a walk nobody asked for."""
    plain = _give_back_run("ales", home="/root", pad_home="/home/ales",
                           args='"/home/ales/x"')
    deep = _give_back_run("ales", home="/root", pad_home="/home/ales",
                          args='-R "/home/ales/local"')
    assert "CHOWN ales /home/ales/x" in plain, plain
    assert "CHOWN -R ales /home/ales/local" in deep, deep


@pytest.mark.skipif(not BASH, reason="no bash")
def test_no_arguments_is_not_a_chown_of_nothing():
    """`chown ales` with no path is a usage error, and this is called from
    scripts under `set -e` where that would end a build."""
    out = _give_back_run("ales", home="/root", pad_home="/home/ales", args="")
    assert "CHOWN" not in out, out
    assert "RC 0" in out, out


def test_the_ownership_questions_go_through_one_portable_helper():
    """`stat -c` is GNU-only and it burned v0.222.1 on the macOS runner.

    A lint rather than a run because it covers the case no host can test: the
    functions must not REGROW a direct `stat -c`, and the machine that would
    notice is the one CI platform this suite cannot make behave like the others.

    SCOPED TO THESE THREE ON PURPOSE, and the boundary is where a BSD host can
    actually reach the code.  The rig is a Linux program - `watch.sh` and
    `cardmount.sh` ask `stat -c` too, and they are right to: macOS runs the
    emulator only inside a Linux container (`docker/padbox.sh`), because
    qemu-user translates *Linux* syscalls.  What the macOS runner reaches is the
    handful of padpath.sh functions that tests lift and execute on the HOST, and
    these are they.  Widening this lint would flag correct code and teach the
    next reader to defang it.
    """
    src = _src("padpath.sh")
    for name in ("pad_give_back", "pad_can_write", "pad_stage"):
        body = _padpath_func(name)
        # CODE ONLY.  These functions carry paragraphs about `stat -c` being the
        # thing not to use, and a lint that reads its own warning as the fault
        # is a lint nobody can satisfy.
        code = "\n".join(ln for ln in body.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "stat -c" not in code, (
            "%s asks GNU stat directly; use pad_owner / pad_owner_ids, which "
            "fall back to BSD's spelling:\n%s" % (name, body))
    # ...and the helper really does ask both, in that order: GNU first, because
    # that is the host the rig actually runs on.
    owner = _padpath_func("pad_owner")
    assert "stat -c %U" in owner and "stat -f %Su" in owner, owner
    assert owner.index("stat -c %U") < owner.index("stat -f %Su"), owner
    ids = _padpath_func("pad_owner_ids")
    assert "stat -c '%u:%g'" in ids and "stat -f '%u:%g'" in ids, ids
    # It must FAIL rather than print an empty line when neither answers: the
    # empty string reading as an answer is the whole of what went wrong.
    assert "|| o=\"\"" not in owner, \
        "pad_owner must not swallow its own failure; its callers decide"
    assert src.count("pad_owner()") == 1


@pytest.mark.skipif(not BASH, reason="no bash")
def test_the_hand_back_survives_a_bsd_stat_too():
    """pad_give_back compares the owner with the string "root", so a BSD stat
    left it empty there as well - and an empty owner means it hands nothing
    back, which is silently the pre-PAD-182 behaviour again."""
    script = "\n".join([
        "set -u", "HOME=/root", "PAD_HOME=/home/ales",
        "id() { echo 0; }",
        # BSD: no -c, and -f is the format flag.
        'stat() {',
        '  if [ "${1:-}" = -c ]; then echo "illegal option" >&2; return 1; fi',
        '  if [ "${1:-}" = -f ]; then echo ales; return 0; fi',
        '  return 1',
        '}',
        'chown() { echo "CHOWN $*"; }',
        _padpath_func("pad_owner"),
        _padpath_func("pad_give_back"),
        'pad_give_back "/home/ales/card"',
        'echo "RC $?"',
    ])
    rc, out = _sh(script)
    assert rc == 0, out
    assert "CHOWN ales /home/ales/card" in out, \
        "a BSD stat must not silently disable the hand-back:\n" + out


def test_one_definition_of_the_hand_back_not_four():
    """The rig's own standing rule - two copies of one fact eventually
    disagree - and here they did: two of the three asked $HOME and one asked
    $PAD_HOME, so the SAME elevated run handed back the override stage and not
    the card mountpoint beside it."""
    bad = []
    for name in _RUN_PATH:
        src = _src(name)
        for n, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if 'stat -c %U "$HOME"' in line:
                bad.append("%s:%d: %s" % (name, n, line.strip()))
    assert not bad, ("a hand-back that asks the PROCESS's home instead of the "
                     "rig's: under sudo $HOME is /root and it chowns nothing\n  "
                     + "\n  ".join(bad))


# --------------------------------------------------------------------------
# AND THE RUN PATH DOES NOT BUILD PATHS OUT OF $HOME AT ALL
# --------------------------------------------------------------------------

def test_the_run_path_names_files_under_pad_home():
    """One wrong $HOME, three failures deep - padpath.sh's header, 2026-08-11.

    watch.sh CREATES every log the rest of the rig then kills tails of and
    greps, and it still had twenty-two uses of $HOME while killgame.sh and
    alive.sh had been converted to $PAD_HOME.  Under elevation the two sides
    therefore named different files: killgame.sh killed a tail of
    $PAD_HOME/padvid.log and watch.sh had started one on $HOME/padvid.log.
    """
    bad = []
    for name in _RUN_PATH:
        src = _src(name)
        for n, line in enumerate(src.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            stripped = line.replace("$PAD_HOME", "")
            if "$HOME/" in stripped or '"$HOME"' in stripped:
                bad.append("%s:%d: %s" % (name, n, line.strip()[:90]))
    assert not bad, ("a run-path file named under the PROCESS's home, which is "
                     "/root on every elevated run:\n  " + "\n  ".join(bad))


def test_the_renderer_is_built_where_the_dropped_helper_can_run_it():
    """PAD-182's sudo run: padglhost went to /root at 0700 and the helper drop
    then correctly ran it as the desktop user, who cannot read /root."""
    src = _src("padpath.sh")
    assert "PAD_GLHOST_BIN=$PAD_HOME/padglhost" in src
    assert "PAD_GLHOST_STAMP=$PAD_HOME/padglhost.srcs" in src
    assert "PAD_GLHOST_BIN=$HOME/padglhost" not in src


# --------------------------------------------------------------------------
# GETTING A POISONED MACHINE BACK
# --------------------------------------------------------------------------

def _can_write_case(paths, foreign_owner=None):
    """pad_can_write over a REAL tree, as this (unprivileged) account.

    The tree, all of it owned by whoever runs the suite:

        home/open/          writable
        home/shut/          0500 - a directory this account may not write into
        home/locked/stamp   0400 - a FILE this account may not rewrite

    `foreign_owner` makes `stat` and `id -un` answer for an account that is not
    us, which is the only way an unprivileged test can reach the branch about a
    root-owned leftover: creating one needs the root this suite does not have.
    `foreign_owner="bsd"` is the opposite trick - a stat that behaves like BSD's
    and refuses `-c` - which is how the macOS failure is reproduced anywhere.
    The write bit stays REAL in every case, which is the half a stub cannot fake
    and the half the whole function turns on.
    """
    lines = [
        'B=$(mktemp -d /tmp/pad182cw.XXXXXX)',
        'mkdir -p "$B/home/shut" "$B/home/open" "$B/home/locked"',
        ': > "$B/home/locked/stamp"',
        'chmod 400 "$B/home/locked/stamp"',
        'chmod 500 "$B/home/shut"',
    ]
    if foreign_owner == "bsd":
        # BSD stat, as macOS ships it: `-c` is not an option it has, so it
        # prints usage to stderr and exits non-zero, and `-f <fmt>` is how the
        # same question is spelled.  Everything else goes to the real binary, so
        # the OWNER this reports is the true one - and the delegation has to ask
        # the real stat in WHICHEVER spelling this host understands, or the test
        # only runs on GNU (v0.223.0 was yanked for exactly that: on the macOS
        # runner the real stat is BSD, so a `-c` delegation failed too and the
        # stub answered nothing).
        lines += [
            'stat() {',
            '  if [ "${1:-}" = -c ]; then',
            '    echo "stat: illegal option -- c" >&2; return 1',
            '  fi',
            '  if [ "${1:-}" = -f ] && [ "${2:-}" = "%Su" ]; then',
            '    command stat -c %U "$3" 2>/dev/null '
            '|| command stat -f %Su "$3"; return',
            '  fi',
            '  command stat "$@"',
            '}']
    elif foreign_owner == "none":
        # Neither form answers - the honest "no data" case the old fallback
        # silently turned into "somebody else".
        lines += ['stat() { return 1; }']
    elif foreign_owner:
        lines += ['stat() { echo %s; }' % foreign_owner,
                  'id() { echo ales; }']
    lines += [_padpath_func("pad_owner"),
              _padpath_func("pad_can_write"), 'PAD_HOME=$B/home']
    for p in paths:
        lines.append('if pad_can_write "$B/home/%s" probe; then '
                     'echo "OK %s"; else echo "REFUSED %s"; fi' % (p, p, p))
    # chmod back first: `rm -rf` cannot unlink out of a 0500 directory, and a
    # test that leaves /tmp litter on every run is its own small bug.
    lines += ['chmod 700 "$B/home/shut"', 'chmod 600 "$B/home/locked/stamp"',
              'rm -rf "$B"', 'echo "LEFT $(ls -d "$B" 2>/dev/null)"']
    rc, out = _sh("\n".join(["set -u"] + lines))
    assert rc == 0, out
    assert "LEFT \n" in out + "\n", "the fixture did not clean up: " + out
    return out


@needs_modes
def test_a_root_owned_directory_is_named_with_the_command_that_repairs_it():
    """Where the reporter's run ENDED, twice.  "mkdir: Permission denied" plus
    "[card] cannot create /home/ales/card/<title>" names the path, the syscall
    and nothing that could be acted on."""
    out = _can_write_case(["shut/newfile"], foreign_owner="root")
    assert "REFUSED shut/newfile" in out, out
    assert "belongs to root and this run is ales" in out, out
    assert "sudo chown -R ales" in out, "the repair has to be in the message"
    # ...and the one thing he did next, which made it worse, is named too.
    assert "Do NOT run the app itself with sudo" in out, out


@needs_modes
def test_an_existing_root_owned_file_is_refused_not_just_its_parent():
    """build.sh's stamp: the DIRECTORY was his, the FILE was root's, and `>`
    needs write permission on the FILE.  A parent-only test passes here and the
    build then dies on the redirect anyway - which is exactly what the
    reporter's log shows, at build.sh's last line."""
    out = _can_write_case(["locked/stamp"], foreign_owner="root")
    assert "REFUSED locked/stamp" in out, out
    assert "locked/stamp belongs to root" in out, \
        "the FILE is the thing to name, not the directory holding it"


@needs_modes
def test_a_bsd_stat_still_reads_the_owner():
    """v0.222.1 WAS YANKED FOR THIS, ~6 minutes after it went live.

    `stat -c %U` is GNU coreutils; macOS ships BSD stat, which rejects `-c` and
    spells it `stat -f %Su`.  The `2>/dev/null` and the `|| o=""` underneath it
    turned that into an EMPTY OWNER - and an empty owner is not "no answer", it
    is a different one: it fell to the "belongs to another account" branch and
    blamed a file the user owns on an elevated run, with a `sudo chown` cure.
    The exact wrong message this ticket had already removed once.

    Linux and Windows CI were green.  The macOS runner was the only thing
    running these functions on a BSD host, and `needs_modes` does not skip it.

    So the BSD stat is SIMULATED here rather than waited for: this test fails on
    every platform against the old code and passes on all of them against the
    new, which is what the release tripwire could not do.
    """
    out = _can_write_case(["locked/stamp"], foreign_owner="bsd")
    assert "REFUSED locked/stamp" in out, out
    assert "is yours, but its mode forbids it" in out, \
        "a BSD stat must still identify the owner:\n" + out
    assert "ELEVATED" not in out, \
        "an unreadable owner must not be reported as somebody else:\n" + out


@needs_modes
def test_an_owner_no_stat_can_read_gives_both_cures_not_the_wrong_one():
    """The fallback's remaining honest case.  When neither stat answers, the
    function has NO DATA about ownership - so it says that and offers both
    cures, rather than building a confident sentence on nothing, which is the
    whole shape of the fault above."""
    out = _can_write_case(["locked/stamp"], foreign_owner="none")
    assert "REFUSED locked/stamp" in out, out
    assert "cannot read who owns it" in out, out
    assert "chmod u+w" in out and "sudo chown -R" in out, out
    assert "ELEVATED RUN MADE IT" not in out, out


@needs_modes
def test_a_path_we_own_and_still_cannot_write_blames_the_mode():
    """Not elevation.  "belongs to david and this run is david" followed by "an
    elevated run made it" sends the reader after a sudo they never typed - this
    fired while the ticket was being written."""
    out = _can_write_case(["locked/stamp"])
    assert "REFUSED locked/stamp" in out, out
    assert "is yours, but its mode forbids it" in out, out
    assert "chmod u+w" in out, out
    assert "ELEVATED" not in out, out


@needs_modes
def test_a_chain_that_does_not_exist_yet_is_not_a_refusal():
    """`mkdir -p ~/card/<title>` on a clean machine makes BOTH, and reporting
    the missing parent as unwritable would refuse every first run."""
    out = _can_write_case(["open/card/some_title/deeper"])
    assert "OK open/card/some_title/deeper" in out, out


@needs_modes
def test_a_writable_target_is_silent():
    """It is asked on the happy path of three scripts, so it must not talk."""
    out = _can_write_case(["open/thing"])
    assert "OK open/thing" in out, out
    assert "cannot write" not in out, out


@pytest.mark.parametrize("script,path", [
    # The three deaths in the reporter's log, each now asked about before the
    # syscall that used to produce the bare refusal.
    ("build.sh", "$PAD_SHIM_STAMP"),
    ("build.sh", "$R/lib/hwshim.so"),
    ("cardmount.sh", "$PREFIX"),
    ("cardmount.sh", "$MNT"),
])
def test_the_three_deaths_ask_before_they_fail(script, path):
    src = _src(script)
    assert 'pad_can_write "%s"' % path in src, \
        "%s writes %s without asking whether it can" % (script, path)


def test_the_card_mountpoint_is_asked_before_mkdir_runs():
    """Order matters: after the mkdir the message is a second opinion on a run
    that has already printed the shell's."""
    src = _src("cardmount.sh")
    assert src.index('pad_can_write "$MNT"') < src.index('mkdir -p "$MNT"')


@pytest.mark.parametrize("script,path", [
    ("build.sh", '"$R/lib/hwshim.so" "$PAD_SHIM_STAMP"'),
    ("buildbridge.sh", '"$PAD_GLHOST_BIN" "$PAD_GLHOST_STAMP"'),
    ("cardmount.sh", '-R "$PREFIX"'),
])
def test_what_a_root_build_writes_is_handed_back(script, path):
    """Or the next ordinary run rebuilds for ever without succeeding: it can
    compile, and it cannot record that it did."""
    assert "pad_give_back %s" % path in _src(script)


# --------------------------------------------------------------------------
# THE DROP HAS TO REACH WHAT THE HELPERS RUN
# --------------------------------------------------------------------------

def _drop_block():
    src = _src("watch.sh")
    i = src.index('echo "[watch] running the guest as root, helpers as $PAD_USER"')
    return src[i:src.index("\nHOSTPG=", i)]


def test_the_drop_is_proved_against_the_rig_and_the_renderer():
    """PAD-182's sudo run, and the rig could not have guessed it: an AppImage
    started with sudo mounts itself with squashfuse AS ROOT, and FUSE locks that
    mount to the mounting account - so $RIG is unreadable by precisely the
    desktop user the helpers are correctly dropped to.  Three helpers died on
    Permission denied and the log's verdict was "this is not the GPU"."""
    body = _drop_block()
    assert 'for _p in "$RIG" "$PAD_GLHOST_BIN"' in body, body[:400]
    assert 'runuser -u "$PAD_USER" -- test -r "$_p"' in body
    # The AppImage case gets the only cure there is, by name.
    assert "/tmp/.mount_*" in body
    assert "sudo" in body and "Start the app NORMALLY" in body


def test_the_unreachable_drop_is_not_fatal():
    """Same trade as the black-window banner it sits under: the guest, the card
    and the switches are root's and all work, and a run with no sound beats no
    run at all."""
    body = _drop_block()
    assert "exit" not in body, \
        "naming an unreachable helper path must not end the run:\n" + body
