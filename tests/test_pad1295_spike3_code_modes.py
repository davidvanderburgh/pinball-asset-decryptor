"""PAD-1295: code modes on Spike 3 - compiled for its 64-bit ARM with the pinned aarch64 kit.

The Spike 3 rig proof (Star Wars ELG 1.10, a code mode built through spike3_modes.plan) is in
docs/plans/spike3_modes.md; these pin the pieces that make it.
"""
import os
import platform
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_write as MW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINS = os.path.join(ROOT, "tools", "spike3_emu", "xgcc.pins")


class _Ex:
    def to_exec_path(self, p):
        return p.replace("\\", "/")


def test_the_spike2_compile_command_is_the_one_it_always_was(tmp_path):
    cmd = MW.compile_command(_Ex(), str(tmp_path / "mode.so"), [str(tmp_path / "m.c")])
    assert cmd.startswith("bash ") and " -a " not in cmd and "xgcc" not in cmd
    assert MW.compile_command(_Ex(), str(tmp_path / "mode.so"), [str(tmp_path / "m.c")], "arm") == cmd


def test_a_spike3_compile_builds_for_a64(tmp_path):
    cmd = MW.compile_command(_Ex(), str(tmp_path / "mode.so"), [str(tmp_path / "m.c")], "a64")
    assert re.search(r"build_mode\.sh'? -a a64 -o ", cmd)
    assert cmd.rstrip("'").endswith("mode_file.c")


def test_the_kept_object_is_per_machine_and_per_pinned_compiler(tmp_path, monkeypatch):
    src = tmp_path / "m" / "m.c"
    src.parent.mkdir()
    src.write_text("/* a mode */\n")
    arm, a64 = MW.code_object_key([str(src)]), MW.code_object_key([str(src)], "a64")
    assert arm != a64
    assert MW.code_object_key([str(src)], "arm") == arm
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "xgcc.pins").write_text("snapshot x\n")
    monkeypatch.setattr(MR, "xgcc_script", lambda: str(kit / "xgcc.sh"))
    one = MW.code_object_key([str(src)], "a64")
    (kit / "xgcc.pins").write_text("snapshot y\n")
    assert MW.code_object_key([str(src)], "a64") != one
    assert MW.code_object_key([str(src)]) == arm            # Spike 2's key never reads the pins


def test_the_kit_script_is_beside_the_sdk():
    assert os.path.isfile(MR.xgcc_script())
    assert os.path.isfile(os.path.join(os.path.dirname(MR.xgcc_script()), "xgcc.pins"))


def test_a_spike3_payload_carries_the_compiled_object(tmp_path):
    obj = tmp_path / "compiled.so"
    obj.write_bytes(b"\x7fELF\x02compiled")
    cfg, port = tmp_path / "mode.cfg", tmp_path / "game.port"
    cfg.write_text("x")
    port.write_text("p")
    result = SimpleNamespace(object=str(obj), mode_files=[("mode.cfg", str(cfg))], port=str(port),
                             asset_files=[], extras=[])
    p = MW.p2_payload(result, str(tmp_path / "out"), arch="a64")
    with open(p["so"], "rb") as f:
        assert f.read() == b"\x7fELF\x02compiled"
    result.object = ""
    p = MW.p2_payload(result, str(tmp_path / "out2"), arch="a64")
    with open(p["so"], "rb") as f, open(MR.prebuilt_object("a64"), "rb") as g:
        assert f.read() == g.read()                         # no code modes: the pinned mode64.so


def _pins():
    snap, rows = "", []
    with open(PINS, encoding="utf-8") as f:
        for line in f:
            w = line.split()
            if not w or w[0].startswith("#"):
                continue
            if w[0] == "snapshot":
                snap = w[1]
                continue
            rows.append(w)
    return snap, rows


def test_the_pins_are_whole_and_from_the_runtimes_snapshot():
    snap, rows = _pins()
    with open(os.path.join(ROOT, "tools", "runtime", "Dockerfile"), encoding="utf-8") as f:
        m = re.search(r"^ARG SNAPSHOT=(\S+)", f.read(), re.M)
    assert m and snap == "https://snapshot.ubuntu.com/ubuntu/" + m.group(1)
    names = set()
    for sha, size, path in rows:
        assert re.fullmatch(r"[0-9a-f]{64}", sha) and int(size) > 0 and path.endswith(".deb")
        names.add(os.path.basename(path).split("_")[0])
    assert {"binutils-aarch64-linux-gnu", "gcc-13-aarch64-linux-gnu", "cpp-13-aarch64-linux-gnu",
            "libgcc-13-dev-arm64-cross", "libc6-dev-arm64-cross"} <= names
    # PAD-1345: the host libraries its programs load, which Ubuntu 26.04 (CI) lacks: as/ld need libsframe.so.1,
    # gold libjansson.so.4, cc1 libisl.so.23/libmpc.so.3/libmpfr.so.6
    assert {"libsframe1", "libjansson4", "libisl23", "libmpc3", "libmpfr6"} <= names
    # the runtime's own toolchain versions (its arm cross gcc and binutils): their libraries are there
    assert any("_2.42-4ubuntu2.10_" in p for _s, _z, p in rows)
    assert any("_13.3.0-6ubuntu2~24.04.1cross1_" in p for _s, _z, p in rows)


def test_code_mode_sounds_find_a_spike3_builds_carriers(tmp_path):
    """choose_code_sounds asked Spike 2's carrier table, so a Spike 3 profile had none."""
    folder = tmp_path / "modes" / "bh"
    folder.mkdir(parents=True)
    spec = CM.CodeAssets(name="BH", music="music.wav", calls={"start": "s.wav"})
    prof = SimpleNamespace(key="star_wars_elg_1_10_spike3", label="Star Wars ELG 1.10 (Spike 3)")
    said = []
    got = MW.choose_code_sounds(str(tmp_path), [("bh", spec)], (True, ""), prof,
                                log=lambda m, *a: said.append(m))
    assert {g["key"] for g in got} == {"music", "call:start"}, said
    assert all(g.get("swap") for g in got)
    assert all(g.get("candidates") or g.get("request") for g in got)


def test_a_swapped_music_is_described_without_a_bed():
    spec = CM.CodeAssets(name="BH", music="music.wav")
    words = CM.describe("bh", spec, carried=[{"slug": "bh", "key": "music", "request": 70}])
    assert "its own music music.wav (request 70)" in words and "sound id" not in words


def _sh():
    sh = shutil.which("bash")
    if sh is None or sys.platform == "win32":
        return None
    return sh


def _kit_runs_here():
    """The pinned kit is amd64 programs; off x86-64 xgcc.sh takes a system aarch64 gcc or refuses
    (an arm64 Mac runner has none)."""
    if platform.machine() in ("x86_64", "AMD64"):
        return True
    if any(shutil.which(c) for c in ("aarch64-linux-gnu-gcc", "aarch64-linux-gnu-gcc-13", "aarch64-linux-gnu-gcc-12")):
        return True
    return platform.machine() in ("aarch64", "arm64") and sys.platform.startswith("linux") and bool(shutil.which("gcc"))


def test_the_kits_binutils_load_the_kits_own_libraries():
    """PAD-1343: the kit's as/ld/nm need libopcodes/libbfd-2.42-arm64.so, unpacked under the kit's
    usr/lib/x86_64-linux-gnu; without the wrappers pointing the loader there, only a machine that also had
    the system's binutils-aarch64-linux-gnu could build (CI and the shipped runtime could not)."""
    with open(MR.xgcc_script(), encoding="utf-8") as f:
        src = f.read()
    lib = "LD_LIBRARY_PATH=$P/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; export LD_LIBRARY_PATH"
    assert src.count(lib) == 2                                  # s3cc and s3nm
    assert 'grep -qs "own libs" "$W" || ! grep -qs "own libs" "$P/s3nm"' in src   # an older kit's wrappers are rewritten


@pytest.mark.skipif(_sh() is None, reason="needs a POSIX shell over this machine's paths")
@pytest.mark.skipif(not _kit_runs_here(), reason="no aarch64 gcc can run on this machine (xgcc.sh refuses)")
def test_the_kit_builds_a_code_mode_and_keeps_the_rule_on_its_own_code(tmp_path):
    """build_mode.sh -a a64 with no CC unpacks the pinned kit (xgcc.sh) and builds; the runtime's own
    allocation (its std::string objects) passes, a mode's malloc is refused - the a64 nm check had
    never run before (its nm name was derived from s3cc)."""
    sdk = MR.sdk_dir()
    env = dict(os.environ, PAD_S3_XGCC=os.environ.get("PAD_S3_XGCC", "/tmp/pad-xgcc-tests"))
    env.pop("CC", None)
    good = tmp_path / "good.c"
    good.write_text('#include "pad_mode.h"\nstatic void t(void) { pm_log("hi"); }\n'
                    'static const struct pm_mode m = { .name = "G", .tick = t };\nPM_REGISTER(m);\n')
    out = tmp_path / "good.so"
    r = subprocess.run(["bash", os.path.join(sdk, "build_mode.sh"), "-a", "a64", "-o", str(out), str(good),
                        os.path.join(sdk, "mode_file.c")], env=env, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    with open(out, "rb") as f:
        head = f.read(20)
    assert head[:5] == b"\x7fELF\x02" and head[18] == 0xB7             # ELF64, EM_AARCH64
    assert "libc calls it will resolve" in r.stdout                     # the nm check ran
    bad = tmp_path / "bad.c"
    bad.write_text('#include "pad_mode.h"\nextern void *malloc(unsigned long);\n'
                   'static void t(void) { if (malloc(4)) pm_log("x"); }\n'
                   'static const struct pm_mode m = { .name = "B", .tick = t };\nPM_REGISTER(m);\n')
    r = subprocess.run(["bash", os.path.join(sdk, "build_mode.sh"), "-a", "a64", "-o", str(tmp_path / "bad.so"),
                        str(bad)], env=env, capture_output=True, text=True, timeout=900)
    assert r.returncode != 0 and "malloc" in r.stderr
