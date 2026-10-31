"""PAD-571 (a Mac user): "Missing tool: debugfs / Install in WSL" on every CGC
extract.  Three things stood between a Mac and a CGC extract:

* Homebrew keeps e2fsprogs keg-only, so debugfs/e2fsck/dumpe2fs were on no
  PATH the Mac executor looked along;
* the pipeline's shell spoke GNU: ``dd iflag=skip_bytes,count_bytes``,
  ``stat -c%s`` and ``find -printf``, none of which a Mac has;
* the prerequisite rows were WSL-only ("n/a" on a Mac) and the error said
  "Install in WSL" on a machine with no WSL.

The round trip at the bottom builds a real (tiny) CGC installer with
e2fsprogs and runs Extract, Write and Extract again through the real
executor: on the macOS CI runner that is the Mac's own dd/wc/find/xxd and
the e2fsprogs the macOS app now ships itself.

PAD-573: the same Mac, on the fixed release, still got "Missing tool:
debugfs" - now with "brew install e2fsprogs", which a Mac without Homebrew
cannot do.  So the macOS app carries its own e2fsprogs
(installer/build_mac_e2fsprogs.sh), the executor and the prerequisite rows
look there first, and the macOS CI run builds those exact tools and runs the
round trip on them with no Homebrew copy installed (PAD_E2FSPROGS_DIR).
"""

import os
import random
import shlex
import shutil
import struct
import subprocess
import sys

import pytest

from pinball_decryptor.core import executor as EX
from pinball_decryptor.core import ext4_grow as EG
from pinball_decryptor.plugins.cgc import pipeline as P
from pinball_decryptor.plugins.cgc.manufacturer import CGCManufacturer


# --- dd byte ranges ---------------------------------------------------------

def _apply_dd(cmd, files):
    """Run a `_dd_range` command against in-memory files, the way POSIX dd
    reads its operands (bs, skip, seek and count are all in blocks)."""
    for one in cmd.split(" && "):
        toks = shlex.split(one)
        assert toks[0] == "dd", one
        ops = dict(t.split("=", 1) for t in toks[1:])
        assert set(ops) <= {"if", "of", "bs", "skip", "seek", "count",
                            "conv"}, f"non-POSIX dd operand in {one}"
        assert ops.get("conv") == "notrunc"
        bs = int(ops["bs"])
        src = files[ops["if"]]
        chunk = src[int(ops["skip"]) * bs:(int(ops["skip"]) + int(ops["count"])) * bs]
        assert len(chunk) == int(ops["count"]) * bs, "read past the source"
        dst = files.setdefault(ops["of"], bytearray())
        at = int(ops["seek"]) * bs
        if len(dst) < at:
            dst.extend(b"\0" * (at - len(dst)))
        dst[at:at + len(chunk)] = chunk


@pytest.mark.parametrize("start,size,seek", [
    (3645 * 2 ** 20, 3702 * 2 ** 20, 0),        # whole MiB
    (2048 * 512, 9437180 * 512, 0),              # Pulp Fiction: 4607.998 MiB
    (2055 * 512, 16387 * 512, 0),                # odd sector start
    (0, 16387 * 512, 2055 * 512),                # write back at an odd sector
    (7, 1000, 13),                               # not even sector-sized
])
def test_dd_range_copies_exactly_those_bytes(start, size, seek):
    rnd = random.Random(start ^ size ^ seek)
    scale = 1 if start + size < 2 ** 26 else 0
    if not scale:
        # Too big to hold; check the arithmetic instead of the bytes.
        cmd = P._dd_range("a", "b", start, size, seek)
        covered = 0
        for one in cmd.split(" && "):
            ops = dict(t.split("=", 1) for t in shlex.split(one)[1:])
            bs = int(ops["bs"])
            assert int(ops["skip"]) * bs == start + covered
            assert int(ops["seek"]) * bs == seek + covered
            covered += int(ops["count"]) * bs
        assert covered == size
        assert len(cmd.split(" && ")) <= 2
        return
    src = bytearray(rnd.getrandbits(8) for _ in range(start + size + 4096))
    dst = bytearray(rnd.getrandbits(8) for _ in range(seek + size + 4096))
    files = {"a": src, "b": bytearray(dst)}
    _apply_dd(P._dd_range("a", "b", start, size, seek), files)
    want = bytearray(dst)
    want[seek:seek + size] = src[start:start + size]
    assert files["b"] == want


def test_dd_range_bulk_moves_in_big_blocks():
    """Pulp Fiction's 4.5 GiB P3 must not be copied 512 bytes at a time."""
    cmd = P._dd_range("in.img", "p3.img", 2048 * 512, 9437180 * 512)
    first = dict(t.split("=", 1) for t in shlex.split(cmd.split(" && ")[0])[1:])
    assert first["bs"] == str(1 << 20)


def test_dd_range_quotes_spaced_paths():
    cmd = P._dd_range("/x/AFMr Decryptor/in.img", "/s/p3.img", 0, 4096)
    assert "if=/x/AFMr Decryptor/in.img" in shlex.split(cmd)


def test_no_gnu_only_commands_left_in_the_cgc_pipeline():
    src = open(P.__file__, encoding="utf-8").read()
    for gnu in ("iflag=", "oflag=", '"stat -c', "-printf '", "status=none"):
        assert gnu not in src, f"GNU-only {gnu!r} in cgc/pipeline.py"


def test_staged_sizes_read_wc_lines_with_spaces_and_total():
    class Ex:
        def run(self, cmd, timeout=0):
            if cmd.startswith("debugfs"):
                return ("  12  100644 (1)   0   0   5 1-Jan-2024 00:00 a b.wav\n"
                        "  13  100644 (1)   0   0   9 1-Jan-2024 00:00 c.bnk\n")
            assert "-exec wc -c {} +" in cmd, cmd
            return ("  5 /s/d/a b.wav\n  7 /s/d/c.bnk\n  3 /s/d/x y.txt\n"
                    " 15 total\n")
    assert P._verify_staged_sizes(Ex(), "/i", "/home/d", "/s/d") == [
        ("c.bnk", 9, 7)]


# --- where the tools are found, and what a missing one says ------------------

def test_mac_executor_finds_keg_only_e2fsprogs_after_the_system_path(
        monkeypatch):
    # with no copy of its own (a source run; the macOS CI run sets this)
    monkeypatch.delenv("PAD_E2FSPROGS_DIR", raising=False)
    ex = EX.MacExecutor()
    for d in ("/opt/homebrew/opt/e2fsprogs/sbin",
              "/usr/local/opt/e2fsprogs/sbin"):
        assert d in ex._SBIN_PATH.split(":")
    path = ex._env()["PATH"]
    assert path.startswith(ex._EXTRA_PATH + os.pathsep)
    assert path.endswith(os.pathsep + ex._SBIN_PATH)
    wrapped = ex._wrap("command -v debugfs")
    assert ":$PATH:" + ex._SBIN_PATH in wrapped


def test_native_linux_executor_looks_in_sbin():
    path = EX.NativeExecutor._env()["PATH"].split(os.pathsep)
    assert "/usr/sbin" in path and "/sbin" in path


@pytest.mark.parametrize("plat,says,never", [
    ("darwin", "brew install e2fsprogs", "WSL"),
    ("linux", "apt install e2fsprogs", "WSL"),
    ("win32", "Install in WSL", "brew"),
])
def test_missing_tool_hint_names_this_machines_installer(plat, says, never):
    hint = P._missing_tool_hint(plat)
    assert says in hint and never not in hint


def test_missing_tool_error_on_a_mac_says_brew(monkeypatch):
    monkeypatch.setattr(P.sys, "platform", "darwin")

    class NoDebugfs:
        def check_available(self):
            return True, "macOS native"

        def run(self, cmd, timeout=0):
            if "debugfs" in cmd:
                raise EX.CommandError(cmd, 1, "")
            return ""
    with pytest.raises(P.PipelineError) as e:
        P._verify_executor_tools(NoDebugfs())
    assert "Missing tool: debugfs" in str(e.value)
    assert "brew install e2fsprogs" in str(e.value)
    assert "WSL" not in str(e.value)


def test_cgc_prereqs_are_probed_on_the_mac_and_installable():
    rows = {p.name: p for p in CGCManufacturer.prerequisites}
    assert rows["debugfs"].where == "native"
    assert rows["xxd"].where == "native"
    assert rows["debugfs"].mac_pkg == "e2fsprogs"
    assert "/opt/homebrew/opt/e2fsprogs/sbin/debugfs" in rows["debugfs"].probe


# --- the e2fsprogs the macOS app ships (PAD-573) ------------------------------

def _fake_tools(d):
    d.mkdir(parents=True)
    for t in ("debugfs", "e2fsck", "dumpe2fs", "mke2fs"):
        (d / t).write_text("")
    return str(d)


def test_no_bundled_e2fsprogs_outside_an_app(monkeypatch):
    monkeypatch.delenv("PAD_E2FSPROGS_DIR", raising=False)
    monkeypatch.delattr(EX.sys, "frozen", raising=False)
    assert EX.bundled_e2fsprogs_dir() is None


def test_bundled_e2fsprogs_found_in_the_frozen_app(tmp_path, monkeypatch):
    """PyInstaller's .app: the executable in Contents/MacOS, sys._MEIPASS =
    Contents/Frameworks, where --add-binary puts the tools."""
    monkeypatch.delenv("PAD_E2FSPROGS_DIR", raising=False)
    contents = tmp_path / "Pinball Asset Decryptor.app" / "Contents"
    want = _fake_tools(contents / "Frameworks" / "e2fsprogs")
    (contents / "MacOS").mkdir()
    exe = contents / "MacOS" / "Pinball Asset Decryptor"
    exe.write_text("")
    monkeypatch.setattr(EX.sys, "frozen", True, raising=False)
    monkeypatch.setattr(EX.sys, "executable", str(exe))
    monkeypatch.setattr(EX.sys, "_MEIPASS", str(contents / "Frameworks"),
                        raising=False)
    assert EX.bundled_e2fsprogs_dir() == want
    # ... and from the executable's place alone (no _MEIPASS)
    monkeypatch.delattr(EX.sys, "_MEIPASS")
    assert os.path.samefile(EX.bundled_e2fsprogs_dir(), want)


def test_bundled_e2fsprogs_dir_override_must_hold_debugfs(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("PAD_E2FSPROGS_DIR", str(tmp_path))
    assert EX.bundled_e2fsprogs_dir() is None
    want = _fake_tools(tmp_path / "e2fs")
    monkeypatch.setenv("PAD_E2FSPROGS_DIR", want)
    assert EX.bundled_e2fsprogs_dir() == want


def test_mac_executor_puts_the_apps_own_e2fsprogs_ahead_of_homebrews(
        tmp_path, monkeypatch):
    own = _fake_tools(tmp_path / "Pin Ball $x" / "e2fsprogs")
    monkeypatch.setenv("PAD_E2FSPROGS_DIR", own)
    ex = EX.MacExecutor()
    path = ex._env()["PATH"]
    assert path.endswith(os.pathsep + own + ":" + ex._SBIN_PATH)
    # in the shell line, quoted so the space and the $ survive bash
    quoted = own.replace("\\", "\\\\").replace("$", "\\$")
    assert ":$PATH:" + quoted + ":" + ex._SBIN_PATH in ex._wrap("true")


def test_prereq_probes_pass_on_the_apps_own_debugfs(tmp_path, monkeypatch):
    own = _fake_tools(tmp_path / "with space" / "e2fsprogs")
    monkeypatch.setenv("PAD_E2FSPROGS_DIR", own)
    probe = EG.with_bundled_debugfs("command -v debugfs")
    assert probe == "test -x %s || command -v debugfs" % shlex.quote(
        os.path.join(own, "debugfs"))
    assert EG.e2fsprogs_dirs()[0] == own
    monkeypatch.delenv("PAD_E2FSPROGS_DIR")
    assert EG.with_bundled_debugfs("command -v debugfs") == "command -v debugfs"


@pytest.mark.skipif(not os.environ.get("PAD_E2FSPROGS_DIR"),
                    reason="the macOS CI run sets PAD_E2FSPROGS_DIR to the "
                           "tools build_mac_e2fsprogs.sh built")
def test_ci_round_trip_runs_on_the_apps_own_e2fsprogs():
    """Guards the round trip below: on the macOS CI run it must find the
    tools the app ships, not some other copy, or it proves nothing."""
    own = EX.bundled_e2fsprogs_dir()
    assert own, "PAD_E2FSPROGS_DIR does not hold a debugfs"
    assert _HAVE
    ex = EX.create_executor()
    for t in ("debugfs", "e2fsck", "dumpe2fs"):
        assert ex.run("command -v %s" % t).strip() == os.path.join(own, t)
    assert _tool("mke2fs") == os.path.join(own, "mke2fs")


# --- the real thing: Extract -> Write -> Extract on a built installer --------

def _tool(name):
    for d in EG.e2fsprogs_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


_HAVE = (sys.platform != "win32" and _tool("mke2fs") and _tool("debugfs")
         and shutil.which("xxd"))


def _mbr(parts):
    mbr = bytearray(512)
    for i, (ptype, start, sectors) in enumerate(parts):
        mbr[0x1BE + 16 * i:0x1BE + 16 * (i + 1)] = struct.pack(
            "<BBBBBBBBII", 0, 0, 0, 0, ptype, 0, 0, 0, start, sectors)
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


def _ext4(path, size, root):
    with open(path, "wb") as f:
        f.truncate(size)
    subprocess.run([_tool("mke2fs"), "-q", "-F", "-t", "ext4", "-b", "1024",
                    "-d", str(root), str(path)], check=True,
                   capture_output=True)


def _disk(path, parts):
    """*parts*: (type, start sector, partition image or None, sectors)."""
    end = max(s + n for _t, s, _f, n in parts)
    with open(path, "wb") as out:
        out.truncate((end + 7) * 512)   # a few spare sectors past the end
        out.write(_mbr([(t, s, n) for t, s, _f, n in parts]))
        for _t, s, f, _n in parts:
            if f:
                out.seek(s * 512)
                out.write(open(f, "rb").read())


def _build_installer(tmp, assets):
    """A miniature AFM remake installer: MBR P3 (odd sector, odd size) ext4
    holding /emmc.img, whose MBR P2 (odd again) ext4 holds the game tree."""
    root = tmp / "inner_root" / "home" / "debian" / "emumm"
    for rel, data in assets.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    inner_sectors = 16387                         # 8 MiB + 1.5 KiB
    _ext4(tmp / "inner.raw", inner_sectors * 512, tmp / "inner_root")
    (tmp / "p3_root").mkdir()
    _disk(tmp / "p3_root" / "emmc.img",
          [(0x0C, 9, None, 2000), (0x83, 2055, tmp / "inner.raw", inner_sectors)])
    p3_sectors = 26627
    _ext4(tmp / "p3.raw", p3_sectors * 512, tmp / "p3_root")
    img = tmp / "in put" / "AttackFromMars test Installer.img"
    img.parent.mkdir()
    _disk(img, [(0x0C, 1, None, 100), (0x83, 101, None, 300),
                (0x83, 4099, tmp / "p3.raw", p3_sectors)])
    return img


def _run(pipe):
    done = {}
    pipe._done = lambda ok, msg: done.update(ok=ok, msg=msg)
    pipe.run()
    assert done.get("ok") is True, done.get("msg")


def _extract(img, out):
    _run(P.ExtractPipeline(str(img), str(out), lambda *a, **k: None,
                           lambda *a, **k: None, lambda *a, **k: None, None))


@pytest.mark.skipif(not _HAVE, reason="needs e2fsprogs (mke2fs, debugfs) and "
                                      "xxd on a Linux or Mac host")
def test_extract_write_extract_round_trip_on_this_host(tmp_path, monkeypatch):
    rnd = random.Random(571)
    assets = {
        "afmdata/sound one.wav": bytes(rnd.getrandbits(8) for _ in range(70001)),
        "afmdata/music.bin": bytes(rnd.getrandbits(8) for _ in range(5000)),
        "afmdata/sub/deep.dat": b"deep" * 333,
        "emumm.cfg": b"cfg=1\n",
    }
    img = _build_installer(tmp_path, assets)

    out = tmp_path / "out dir"
    _extract(img, out)
    for rel, data in assets.items():
        assert (out / rel).read_bytes() == data, rel

    # Write a changed sound back into a new installer, then read that back.
    new_wav = bytes(rnd.getrandbits(8) for _ in range(91234))
    (out / "afmdata" / "sound one.wav").write_bytes(new_wav)
    monkeypatch.setattr(P.WritePipeline, "_MIN_PLAUSIBLE_EMMC", 1)
    built = tmp_path / "built" / "AttackFromMars test Installer.img"
    _run(P.WritePipeline(str(img), str(out), str(built), lambda *a, **k: None,
                         lambda *a, **k: None, lambda *a, **k: None, None))

    again = tmp_path / "again"
    _extract(built, again)
    assert (again / "afmdata" / "sound one.wav").read_bytes() == new_wav
    for rel in ("afmdata/music.bin", "afmdata/sub/deep.dat", "emumm.cfg"):
        assert (again / rel).read_bytes() == assets[rel], rel
    # The partition table and everything outside P3 came through untouched.
    a, b = img.read_bytes(), built.read_bytes()
    assert len(a) == len(b) and a[:4099 * 512] == b[:4099 * 512]


def _built_inner_stat(tmp, built, path):
    """debugfs ``stat`` of *path* inside the inner game ext4 of *built*."""
    data = built.read_bytes()
    (tmp / "b_p3.raw").write_bytes(data[4099 * 512:(4099 + 26627) * 512])
    subprocess.run([_tool("debugfs"), "-R",
                    f"dump /emmc.img {tmp / 'b_emmc.img'}", str(tmp / "b_p3.raw")],
                   check=True, capture_output=True)
    emmc = (tmp / "b_emmc.img").read_bytes()
    (tmp / "b_inner.raw").write_bytes(emmc[2055 * 512:(2055 + 16387) * 512])
    return subprocess.run([_tool("debugfs"), "-R", f'stat "{path}"',
                           str(tmp / "b_inner.raw")], check=True,
                          capture_output=True, text=True).stdout


def _arm_elf(body):
    """A bare 32-bit hard-float ARM ELF header, enough for the Write's
    will-it-run check."""
    return (b"\x7fELF\x01\x01\x01" + b"\0" * 9
            + struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, 0, 0, 0, 0x05000400,
                          52, 0, 0, 0, 0, 0) + body)


@pytest.mark.skipif(not _HAVE, reason="needs e2fsprogs (mke2fs, debugfs) and "
                                      "xxd on a Linux or Mac host")
def test_written_programs_keep_their_mode(tmp_path, monkeypatch):
    """PAD-886: debugfs ``dump`` hands PAD a 0664 copy of the card's 0755
    ``service.sh``/``pin``, and ``write`` used to put that 0664 on the card:
    init.sh (PID 1) could not run them, exited, and the machine kernel
    panicked in a boot loop.  An edited file keeps the mode of the one it
    replaces; a new program arrives executable, a new data file does not."""
    assets = {"service.sh": b"#!/bin/sh\n./pin\n", "pin": _arm_elf(b"\0"),
              "afmdata/data.bin": b"d" * 100}
    img_root = tmp_path / "inner_root" / "home" / "debian" / "emumm"
    (img_root / "afmdata").mkdir(parents=True)
    for rel, mode in (("service.sh", 0o755), ("pin", 0o755),
                      ("afmdata/data.bin", 0o664)):
        (img_root / rel).write_bytes(assets[rel])
        (img_root / rel).chmod(mode)             # mke2fs -d copies the mode
    img = _build_installer(tmp_path, assets)

    out = tmp_path / "out dir"
    _extract(img, out)
    (out / "service.sh").write_bytes(b"#!/bin/sh\necho hi\n./pin\n")
    (out / "pin").write_bytes(_arm_elf(b"\1" * 80))
    (out / "afmdata" / "new.sh").write_bytes(b"#!/bin/sh\n")
    (out / "afmdata" / "new.dat").write_bytes(b"new")
    for rel in ("service.sh", "pin", "afmdata/new.sh", "afmdata/new.dat"):
        (out / rel).chmod(0o664)                   # what dump leaves on the host
    monkeypatch.setattr(P.WritePipeline, "_MIN_PLAUSIBLE_EMMC", 1)
    built = tmp_path / "built" / "AttackFromMars test Installer.img"
    _run(P.WritePipeline(str(img), str(out), str(built), lambda *a, **k: None,
                         lambda *a, **k: None, lambda *a, **k: None, None))

    want = {"service.sh": 0o755, "pin": 0o755, "afmdata/data.bin": 0o664,
            "afmdata/new.sh": 0o755, "afmdata/new.dat": 0o644}
    for rel, mode in want.items():
        meta = P._parse_inode_meta(_built_inner_stat(
            tmp_path, built, f"/home/debian/emumm/{rel}"))
        assert meta and meta[0] == mode, (rel, meta and oct(meta[0]))
