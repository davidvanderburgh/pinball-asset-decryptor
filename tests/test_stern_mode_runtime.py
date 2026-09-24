"""Tests for :mod:`pinball_decryptor.plugins.stern.mode_runtime` (item 127; item 149 uses it).

The app SHIPS the mode runtime as a pinned object (``sdk/prebuilt/mode.so``): no user
builds anything. These pin that the object is an ARM shared object, that it was built
from the SDK sources as they are now (a stale object fails here, naming the builder), that
every port the SDK carries is found by game and version, and - where the cross compiler
is installed - that rebuilding gives the same bytes. Desk only: no card, no rig.
"""

import os
import re
import shutil
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import mode_runtime as MR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")

PORTS = [
    ("beatles", "1.29"),
    ("deadpool_le", "1.14"),
    ("deadpool_pro", "1.16"),
    ("godzilla_le", "1.16"),
    ("godzilla_pro", "1.15"),
    ("jaws_le", "1.02"),
    ("turtles_pro", "1.58"),
    ("turtles_pro", "1.59"),
]


def test_sdk_dir_is_the_checkouts():
    assert os.path.normcase(os.path.realpath(MR.sdk_dir())) == os.path.normcase(os.path.realpath(SDK))


def test_prebuilt_object_is_an_arm_shared_object():
    path = MR.prebuilt_object()
    with open(path, "rb") as f:
        head = f.read(52)
    assert head[:4] == b"\x7fELF"
    assert head[4] == 1, "ELFCLASS32"
    assert head[5] == 1, "little endian"
    e_type, e_machine = struct.unpack_from("<HH", head, 16)
    assert e_type == 3, "ET_DYN (a shared object the game preloads)"
    assert e_machine == 40, "EM_ARM"


def test_prebuilt_object_is_current():
    reasons = MR.stale_reasons()
    assert not reasons, "the pinned mode runtime is STALE: " + "; ".join(reasons)
    assert MR.prebuilt_is_current()


def test_sources_file_lists_every_source_and_the_compiler():
    sums, compiler = MR.recorded()
    for name in MR.SOURCES + ("mode.so",):
        assert re.fullmatch(r"[0-9a-f]{64}", sums.get(name, "")), name
    assert "arm-linux-gnueabihf-gcc" in compiler


def _copy_sdk(tmp_path):
    sdk = tmp_path / "sdk"
    (sdk / "prebuilt").mkdir(parents=True)
    for name in MR.SOURCES:
        shutil.copy(os.path.join(SDK, name), sdk / name)
    for name in ("mode.so", "SOURCES.sha256"):
        shutil.copy(os.path.join(SDK, "prebuilt", name), sdk / "prebuilt" / name)
    return sdk


def test_a_changed_source_is_stale_and_names_the_builder(tmp_path, monkeypatch):
    sdk = _copy_sdk(tmp_path)
    monkeypatch.setattr(MR, "sdk_dir", lambda: str(sdk))
    assert MR.prebuilt_is_current()
    with open(sdk / "mode_file.c", "ab") as f:
        f.write(b"\n/* an edit */\n")
    reasons = MR.stale_reasons()
    assert len(reasons) == 1 and "mode_file.c" in reasons[0]
    assert "build_prebuilt.sh" in reasons[0]
    assert not MR.prebuilt_is_current()


def test_a_crlf_checkout_of_unchanged_sources_is_current(tmp_path, monkeypatch):
    sdk = _copy_sdk(tmp_path)
    monkeypatch.setattr(MR, "sdk_dir", lambda: str(sdk))
    for name in ("pad_mode.h", "pad_mode_runtime.c", "mode_file.c"):
        data = (sdk / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        (sdk / name).write_bytes(data)
    assert MR.stale_reasons() == []


def test_a_swapped_object_is_stale(tmp_path, monkeypatch):
    sdk = _copy_sdk(tmp_path)
    monkeypatch.setattr(MR, "sdk_dir", lambda: str(sdk))
    with open(sdk / "prebuilt" / "mode.so", "ab") as f:
        f.write(b"\0")
    reasons = MR.stale_reasons()
    assert reasons and "build_prebuilt.sh" in reasons[0]


def test_a_missing_object_names_the_builder(tmp_path, monkeypatch):
    sdk = _copy_sdk(tmp_path)
    os.remove(sdk / "prebuilt" / "mode.so")
    monkeypatch.setattr(MR, "sdk_dir", lambda: str(sdk))
    with pytest.raises(FileNotFoundError, match="build_prebuilt.sh"):
        MR.prebuilt_object()


@pytest.mark.parametrize("game_dir,version", PORTS)
def test_port_file_finds_every_port(game_dir, version):
    path = MR.port_file(game_dir, version)
    assert path and os.path.isfile(path)
    assert os.path.basename(path) == "%s-%s.port" % (game_dir, version)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    assert re.search(r"^game\s+%s\s*$" % re.escape(game_dir), text, re.M)
    assert re.search(r"^version\s+%s\s*$" % re.escape(version), text, re.M)


def test_port_file_reads_a_card_titles_version():
    want = MR.port_file("godzilla_pro", "1.15")
    for v in ("1_15_0", "1.15.0", "1_15"):
        assert MR.port_file("godzilla_pro", v) == want


def test_port_file_is_none_for_a_build_without_one():
    assert MR.port_file("godzilla_pro", "1.99") is None
    assert MR.port_file("no_such_game", "1.15") is None
    assert MR.port_file("godzilla_pro", "1.15.1") is None
    assert MR.port_file("", "1.15") is None
    assert MR.port_file("godzilla_pro", None) is None


def test_ports_lists_what_the_sdk_carries():
    assert MR.ports() == sorted(PORTS)


# key -> the runtime's #define that sizes its table (pad_mode_runtime.c)
_PORT_TABLES = {"site": "N_SITES", "data": "N_DATA", "value": "N_VALUES", "shot": "N_SHOTS",
                "callout": "N_ROLES", "scene": "N_ROLES", "text": "N_TEXTS", "event": "N_EVENTS",
                "lamp": "N_LAMPS", "switch": "N_SWITCHES"}


@pytest.mark.parametrize("game_dir,version", PORTS)
def test_every_port_fits_the_runtimes_tables(game_dir, version):
    """Two features merged into one port (the mode-leds lamp lines and the item 154 display lines
    went into both Godzilla ports at once) must still fit: the runtime reads up to PORT_MAX bytes
    of a port and keeps each kind of line in a fixed table, and a line past a full table is lost
    to the game (the boot log names it). A port that outgrows a table fails here, named."""
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    cap = {k: int(re.search(r"#define %s\s+(\d+)" % d, src).group(1)) for k, d in _PORT_TABLES.items()}
    port_max = int(re.search(r"#define PORT_MAX\s+(\d+)", src).group(1))
    path = MR.port_file(game_dir, version)
    with open(path, "rb") as f:
        raw = f.read()
    assert len(raw) <= port_max, "%s is %d bytes; the runtime reads %d" % (path, len(raw), port_max)
    count = {}
    for line in raw.decode("utf-8").splitlines():
        words = line.split("#", 1)[0].split()
        if words and words[0] in cap:
            count[words[0]] = count.get(words[0], 0) + 1
    for key, n in count.items():
        assert n <= cap[key], "%s has %d %s lines; the runtime keeps %d (%s)" % (
            os.path.basename(path), n, key, cap[key], _PORT_TABLES[key])


# ---- the runtime's port reader, on the host (the integration of mode-leds and item 154 display) ------
_READER = r"""
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include "pad_mode.h"
static const char *PORT_FILES[2];
static int events, lamps, rules;
static void event_line(const char *s) { events++; }
static void lamp_line(const char *s) { lamps++; }
static void rule_line(const char *s) { rules++; }      /* item 160: `rule` lines, the stock rules section */
@HELPERS@
@SECTION@
int main(int argc, char **argv)
{
    int ok;
    PORT_FILES[0] = PORT_FILES[1] = argv[1];
    ok = port_load();
    printf("ok=%d game=%s version=%s site=%d data=%d value=%d shot=%d text=%d scene=%d callout=%d "
           "event=%d lamp=%d dropped=%d too_long=%d last_site=%s\n", ok, port.game, port.version, port.n_site,
           port.n_data, port.n_value, port.n_shot, port.n_text, port.n_scene, port.n_callout, events, lamps,
           port.dropped, port.too_long, port.n_site ? port.site[port.n_site - 1].name : "-");
    return 0;
}
"""


def _c_function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


@pytest.fixture(scope="module")
def port_reader(tmp_path_factory):
    if os.name == "nt" or sys.platform == "darwin":
        pytest.skip("the harness needs a host ELF C toolchain")
    cc = next((c for c in ("gcc", "cc", "clang") if shutil.which(c)), None)
    if not cc:
        pytest.skip("no host C compiler")
    with open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8") as f:
        src = f.read()
    start = src.index("/* The port is read in PORT_CHUNK pieces")
    end = src.index("static struct site *site(const char *name)")
    helpers = "\n".join(_c_function(src, r) for r in (
        r"static int str_eq\(", r"static void str_copy\(", r"static int hexval\(", r"static uint64_t number\("))
    d = tmp_path_factory.mktemp("port_reader")
    (d / "reader.c").write_text(_READER.replace("@HELPERS@", helpers).replace("@SECTION@", src[start:end]))
    exe = d / "reader"
    r = subprocess.run([cc, "-std=gnu17", "-O1", "-Wall", "-Wno-unused-function", "-Wno-unused-parameter",
                        "-Wno-unused-variable", "-I", SDK, "-o", str(exe), str(d / "reader.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def read(path):
        out = subprocess.run([str(exe), str(path)], capture_output=True, text=True, check=True).stdout.split()
        return dict(w.split("=", 1) for w in out)
    return read


@pytest.mark.parametrize("game_dir,version", [("godzilla_le", "1.16"), ("godzilla_pro", "1.15")])
def test_the_reader_takes_every_line_of_a_merged_port(port_reader, game_dir, version):
    """Both Godzilla ports carry the display lines, 86-88 lamp lines and then the stock-rule lines past
    16 KB, in 4 KB chunks: the reader takes every line, whatever chunk boundary it straddles."""
    path = MR.port_file(game_dir, version)
    with open(path, encoding="utf-8") as f:
        lines = [l.split("#", 1)[0].split() for l in f]
    want = {k: sum(1 for w in lines if w and w[0] == k) for k in ("site", "data", "value", "event", "lamp")}
    got = port_reader(path)
    assert got["ok"] == "1" and got["game"] == game_dir and got["version"] == version
    for k, n in want.items():
        assert int(got[k]) == n, (k, got[k], n)
    assert got["dropped"] == "0" and got["too_long"] == "0"
    last = [w[1] for w in lines if w and w[0] == "site"][-1]
    assert got["last_site"] == last                        # the file's own last site line, whatever comes after the lamps


def test_the_reader_says_what_it_could_not_take(port_reader, tmp_path):
    src = os.path.join(SDK, "pad_mode_runtime.c")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    n_sites = int(re.search(r"#define N_SITES\s+(\d+)", text).group(1))
    port_max = int(re.search(r"#define PORT_MAX\s+(\d+)", text).group(1))
    full = tmp_path / "full.port"
    full.write_text("game g\nversion 1\n" + "".join("site s%d 0x%x 0 0\n" % (i, 0x1000 + 4 * i)
                                                  for i in range(n_sites + 2)) + "lamp 1 0 LAST")
    got = port_reader(full)
    assert (got["site"], got["dropped"], got["lamp"], got["too_long"]) == (str(n_sites), "2", "1", "0")
    long_ = tmp_path / "long.port"
    body = "game g\n" + "# padding\n" * (port_max // 10) + "lamp 1 0 CUT BY THE LIMIT\n"
    long_.write_text(body)
    got = port_reader(long_)
    assert got["too_long"] == "1" and got["lamp"] == "0" and got["game"] == "g"


def test_git_never_line_ending_converts_the_object():
    """The object is committed and shipped, and ``tools/spike2_emu/.gitattributes`` says
    ``* text eol=lf`` for its whole folder. A ``binary`` line in the ROOT file lost to that
    (a deeper file wins): git reported ``text: set`` for mode.so, so a rebuild whose bytes
    held a CR LF pair would have been committed with the CR taken out. Skips where this is
    not a git checkout git can read (a Windows worktree seen from WSL)."""
    git = shutil.which("git")
    if not git:
        pytest.skip("no git")
    rel = "tools/spike2_emu/modes/sdk/prebuilt/mode.so"
    try:
        r = subprocess.run([git, "-C", ROOT, "check-attr", "text", "--", rel],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        pytest.skip("git could not run: %s" % e)
    if r.returncode != 0 or rel not in r.stdout:
        pytest.skip("not a git checkout git can read here: %s" % (r.stderr or r.stdout).strip())
    assert r.stdout.strip() == rel + ": text: unset", r.stdout


def _cross_gcc():
    return shutil.which("arm-linux-gnueabihf-gcc")


@pytest.mark.skipif(sys.platform == "win32" or not _cross_gcc() or not shutil.which("bash"),
                    reason="needs arm-linux-gnueabihf-gcc (the PAD-Runtime distro has it)")
def test_rebuilding_gives_the_same_bytes(tmp_path):
    _sums, compiler = MR.recorded()
    have = subprocess.run([_cross_gcc(), "--version"], capture_output=True, text=True).stdout
    have = have.splitlines()[0] if have else ""
    if have.strip() != compiler.strip():
        pytest.skip("this compiler (%s) is not the one the object was pinned with (%s)"
                    % (have, compiler))
    out = tmp_path / "rebuilt"
    r = subprocess.run(["bash", os.path.join(SDK, "build_prebuilt.sh"), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with open(MR.prebuilt_object(), "rb") as a, open(out / "mode.so", "rb") as b:
        assert a.read() == b.read(), "a rebuild of the same sources differs from prebuilt/mode.so"
    with open(MR.sources_file(), "rb") as a, open(out / "SOURCES.sha256", "rb") as b:
        assert a.read().replace(b"\r", b"") == b.read()
