"""PAD-437: cardmount.sh fetched fuse2fs on EVERY Start on Ubuntu 26.04.

The card mount keeps its own fuse2fs in a private prefix (~/local), fetched
with `apt-get download` the first time and offline after that - "(once)", the
log line says.  The test for "already fetched" asked for
$PREFIX/lib/x86_64-linux-gnu/libfuse.so.2 by name, which is where 22.04's and
24.04's packages put it.  26.04's put their libraries under /usr/lib, and its
fuse2fs links libfuse3 rather than libfuse.so.2, so the file never existed and
every Start went back to apt for both packages.  On a slow mirror the Emulate
log sat on the boot selector's line for 44 s, and past 100 s once, before the
card mounted.

These run the real functions, lifted out of cardmount.sh, against a scratch
prefix, with apt-get, dpkg-deb and ldd answering as each release would.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
BASH = shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present"),
    pytest.mark.skipif(not BASH, reason="no bash"),
]


def _src():
    with open(os.path.join(RIG, "cardmount.sh"), encoding="utf-8") as fh:
        return fh.read()


def _func(src, name):
    """One function lifted out of cardmount.sh verbatim (sourcing the file
    would run its top level, which mounts a card)."""
    i = src.index("\n%s() {" % name) + 1
    end = src.index("\n}\n", i) + 3
    return src[i:end]


def _line(src, pattern):
    m = re.search(pattern, src, re.M)
    assert m, pattern
    return m.group(0)


# Stubs as shell functions, for the reason test_spike2_elevated_leftovers.py
# gives: the executable bit means something different on each shell this suite
# runs under.  LIBDIR is where the simulated release's libfuse2 package puts
# libfuse.so.2; NEEDS is what the simulated fuse2fs links.
_STUBS = r'''
command() {   # the host's own fuse2fs, if it has one, must not decide this
    if [ "${1:-}" = -v ] && [ "${2:-}" = fuse2fs ]; then return 1; fi
    builtin command "$@"
}
pad_can_write() { return 0; }
pad_give_back() { :; }
apt-get() {
    [ "$1" = download ] || return 1
    echo "APT $2" >> "$LOGF"
    case " $AVAIL " in
        *" $2 "*) : > "${2}_1.0_amd64.deb"; return 0 ;;
    esac
    echo "E: Unable to locate package $2"; return 100
}
dpkg-deb() {
    [ "$1" = -x ] || return 1
    case "${2##*/}" in
        fuse2fs_*) mkdir -p "$3/usr/bin"
                   printf '#!/bin/sh\n' > "$3/usr/bin/fuse2fs"
                   chmod +x "$3/usr/bin/fuse2fs" ;;
        libfuse2*) mkdir -p "$3/$LIBDIR"; : > "$3/$LIBDIR/libfuse.so.2" ;;
    esac
}
ldd() {
    local d f="" IFS=:
    case "$NEEDS" in
        libfuse3) printf '\tlibfuse3.so.4 => /lib/x86_64-linux-gnu/libfuse3.so.4 (0x1)\n' ;;
        libfuse2)
            for d in $LD_LIBRARY_PATH; do
                [ -n "$d" ] && [ -e "$d/libfuse.so.2" ] && f="$d/libfuse.so.2"
            done
            if [ -n "$f" ]; then printf '\tlibfuse.so.2 => %s (0x1)\n' "$f"
            else printf '\tlibfuse.so.2 => not found\n'; fi ;;
    esac
}
'''


def _run(body, needs, libdir, avail="fuse2fs libfuse2t64"):
    """ensure_fuse2fs against a scratch prefix; (rc, stdout, stderr, apt log)."""
    src = _src()
    script = "\n".join([
        "set -u",
        'T=$(mktemp -d "${TMPDIR:-/tmp}/pad437.XXXXXX") || exit 9',
        'PREFIX="$T/local"; LOGF="$T/apt.log"; : > "$LOGF"',
        # the fetch's own scratch directories land here, where they can be counted
        'export TMPDIR="$T/tmp"; mkdir -p "$TMPDIR"',
        "NEEDS=%s; LIBDIR=%s; AVAIL='%s'" % (needs, libdir, avail),
        _line(src, r'^FUSE2FS="\$PREFIX/usr/bin/fuse2fs"$'),
        _line(src, r'^export LD_LIBRARY_PATH=.*$'),
        _line(src, r'^PAD_FUSE2FS_PKGS=.*$'),
        _line(src, r'^PAD_LIBFUSE2_PKGS=.*$'),
        _STUBS,
        _func(src, "_resolves"),
        _func(src, "_apt_download_first"),
        _func(src, "_unpack_debs"),
        _func(src, "_fetch_fuse2fs"),
        _func(src, "ensure_fuse2fs"),
        body,
        'ensure_fuse2fs; rc=$?',
        'echo "RC $rc"',
        'sed "s/^/LOG /" "$LOGF"',
        'echo "PKGDIRS $(ls "$TMPDIR" | grep -c "^cardpkg\\.")" >&2',
        'rm -rf "$T"',
    ])
    # On stdin rather than -c: where `bash` is WSL's launcher, a -c argument's
    # quotes do not survive the trip across.  Bytes, because text mode on
    # Windows would hand bash CRLF line ends.
    p = subprocess.run([BASH, "-s"], input=script.encode(), capture_output=True,
                       timeout=60)
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    rc = re.search(r"^RC (\d+)$", out, re.M)
    assert rc, out + err
    apt = re.findall(r"^LOG APT (\S+)$", out, re.M)
    return int(rc.group(1)), out, err, apt


#: A prefix the way 26.04's packages unpack: binary in usr/bin, libfuse.so.2
#: (fetched by the old code, used by nothing) under usr/lib - no lib/ at all.
_PREFIX_2604 = "\n".join([
    'mkdir -p "$PREFIX/usr/bin" "$PREFIX/usr/lib/x86_64-linux-gnu"',
    'printf "#!/bin/sh\\n" > "$PREFIX/usr/bin/fuse2fs"',
    'chmod +x "$PREFIX/usr/bin/fuse2fs"',
    ': > "$PREFIX/usr/lib/x86_64-linux-gnu/libfuse.so.2"',
])


def test_a_26_04_prefix_counts_as_already_fetched():
    """The ticket.  The reporter's prefix was complete and its fuse2fs ran;
    the next Start must not go to apt at all."""
    rc, out, err, apt = _run(_PREFIX_2604, needs="libfuse3", libdir="usr/lib/x86_64-linux-gnu")
    assert rc == 0, out + err
    assert apt == [], "went back to apt for a fuse2fs it already had: %s" % apt
    assert "fetching fuse2fs" not in out + err


def test_a_24_04_prefix_still_counts_as_already_fetched():
    """The layout the old by-name test was written for must not regress."""
    prefix = "\n".join([
        'mkdir -p "$PREFIX/usr/bin" "$PREFIX/lib/x86_64-linux-gnu"',
        'printf "#!/bin/sh\\n" > "$PREFIX/usr/bin/fuse2fs"',
        'chmod +x "$PREFIX/usr/bin/fuse2fs"',
        ': > "$PREFIX/lib/x86_64-linux-gnu/libfuse.so.2"',
    ])
    rc, out, err, apt = _run(prefix, needs="libfuse2", libdir="lib/x86_64-linux-gnu")
    assert rc == 0 and apt == [], out + err


def test_a_prefix_whose_library_is_gone_is_fetched_again():
    """PAD-114's upgrade case is still a re-fetch: the binary is there, the
    library it links is not."""
    prefix = "\n".join([
        'mkdir -p "$PREFIX/usr/bin"',
        'printf "#!/bin/sh\\n" > "$PREFIX/usr/bin/fuse2fs"',
        'chmod +x "$PREFIX/usr/bin/fuse2fs"',
    ])
    rc, out, err, apt = _run(prefix, needs="libfuse2", libdir="lib/x86_64-linux-gnu")
    assert rc == 0, out + err
    assert apt == ["fuse2fs", "libfuse2t64"], apt


def test_a_fresh_26_04_fetch_downloads_fuse2fs_alone():
    """26.04's fuse2fs links the system libfuse3, so the libfuse2 download
    was a second slow round trip to apt for a file nothing opens."""
    rc, out, err, apt = _run("", needs="libfuse3", libdir="usr/lib/x86_64-linux-gnu")
    assert rc == 0, out + err
    assert apt == ["fuse2fs"], apt


def test_a_fresh_26_04_fetch_is_not_repeated():
    """Fetched once, then found: the "(once)" in the log line is true."""
    body = "\n".join([
        "ensure_fuse2fs >/dev/null 2>&1 || echo FIRST-FAILED",
        ': > "$LOGF"',
    ])
    rc, out, err, apt = _run(body, needs="libfuse3", libdir="usr/lib/x86_64-linux-gnu")
    assert "FIRST-FAILED" not in out, out + err
    assert rc == 0 and apt == [], (apt, out + err)


@pytest.mark.parametrize("libdir", ["lib/x86_64-linux-gnu", "usr/lib/x86_64-linux-gnu"])
def test_a_fresh_fetch_that_needs_libfuse2_takes_both_and_finds_it(libdir):
    """22.04/24.04 (lib/) and any release that links libfuse.so.2 and puts it
    under usr/lib: the library is fetched and the binary then finds it, so the
    NEXT Start does not fetch again either."""
    body = "\n".join([
        "ensure_fuse2fs >/dev/null 2>&1 || echo FIRST-FAILED",
        'sed "s/^/FIRST /" "$LOGF"; : > "$LOGF"',
    ])
    rc, out, err, apt = _run(body, needs="libfuse2", libdir=libdir)
    assert "FIRST-FAILED" not in out, out + err
    assert re.findall(r"^FIRST APT (\S+)$", out, re.M) == ["fuse2fs", "libfuse2t64"], out
    assert rc == 0 and apt == [], (apt, out + err)


def test_the_fetching_line_is_on_stderr_so_it_shows_during_the_wait():
    """watch.sh reads cardmount's stdout through $(...) and prints it after
    the mount; stderr reaches the log as it happens."""
    rc, out, err, apt = _run("", needs="libfuse3", libdir="usr/lib/x86_64-linux-gnu")
    assert rc == 0
    assert "[card] fetching fuse2fs into" in err
    assert "fetching fuse2fs" not in out


def test_a_library_still_missing_after_the_fetch_is_named():
    """Formerly passed on to the mount as "fuse2fs refused <card>", with no
    word about what for.  (A package that puts the library where nothing
    looks stands in for any release this has not met yet.)"""
    rc, out, err, apt = _run("", needs="libfuse2", libdir="opt/elsewhere")
    assert rc == 1
    assert apt == ["fuse2fs", "libfuse2t64"], apt
    assert "[card] fuse2fs is here but cannot start; it needs:" in err, err
    assert "[card]   libfuse.so.2 => not found" in err, err


def test_a_library_apt_does_not_have_is_said_so():
    rc, out, err, apt = _run("", needs="libfuse2", libdir="lib/x86_64-linux-gnu",
                             avail="fuse2fs")
    assert rc == 1
    assert apt == ["fuse2fs", "libfuse2t64", "libfuse2"], apt
    assert "[card] could not download libfuse.so.2" in err, err


def test_each_fetch_uses_its_own_directory_and_removes_it():
    """A shared /tmp/cardpkg was left root-owned by a PAD_PIVOT fetch, and
    every stale .deb in it was unpacked again over the new one."""
    src = _func(_src(), "ensure_fuse2fs")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "/tmp/cardpkg" not in code.replace("cardpkg.XXXXXX", "")
    assert 'mktemp -d' in code and 'rm -rf "$pkgs"' in code
    rc, out, err, apt = _run("", needs="libfuse3", libdir="usr/lib/x86_64-linux-gnu")
    assert rc == 0 and apt == ["fuse2fs"], (apt, out + err)
    m = re.search(r"^PKGDIRS (\d+)$", err, re.M)
    assert m and m.group(1) == "0", "the fetch left its download directory behind: " + err
