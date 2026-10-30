"""PAD-877: CGC code mods are built for the machine, and nothing ships that
its glibc 2.13 would refuse.

A library built with any recent gcc asks for ``dlsym@GLIBC_2.34``; the
machine's loader refuses it, and preloaded at boot that is a boot loop.  The
Write now reads every program it would ship and refuses one that asks the
card's libraries for a version they do not define, and builds the C under
``pad_mods/`` against the card's own libraries.

The ELFs are tiny fixtures (tests/fixtures/cgc_mods/make.sh); the card's
filesystem is a fake executor answering debugfs ``stat`` / ``dump``.
"""

import os
import re
import shlex
import shutil

import pytest

from pinball_decryptor.core.executor import CommandError, WslExecutor
from pinball_decryptor.core.pipeline_base import PipelineError
from pinball_decryptor.plugins.cgc import mods as M
from pinball_decryptor.plugins.cgc import pipeline as cgc_pipeline
from pinball_decryptor.plugins.cgc.pipeline import WritePipeline

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "cgc_mods")


def fix(name):
    return os.path.join(FIX, name)


# ---------------------------------------------------------------------------
# Reading an ELF
# ---------------------------------------------------------------------------

def test_modern_hook_asks_for_glibc_2_34_dlsym():
    info = M.read_elf_file(fix("modern.so"))
    assert info["machine"] == M.EM_ARM and info["bits"] == 32
    assert info["flags"] & M.EF_ARM_ABI_FLOAT_HARD
    assert "libc.so.6" in info["needed"]
    assert info["verneed"]["libc.so.6"]["GLIBC_2.34"] == ["dlsym"]


def test_card_libc_defines_its_versions():
    info = M.read_elf_file(fix("card_libc.so.6"))
    assert info["soname"] == "libc.so.6"
    assert info["verdef"] == ["GLIBC_2.4", "GLIBC_2.13"]
    assert M.newest(info["verdef"]) == "GLIBC_2.13"


def test_newest_compares_numbers_not_text():
    assert M.newest(["GLIBC_2.4", "GLIBC_2.13", "GLIBC_2.9"]) == "GLIBC_2.13"
    assert M.newest(["GCC_3.5"]) is None


def test_not_an_elf():
    with pytest.raises(M.ElfError):
        M.read_elf(b"RIFF....WAVE")
    assert not M.is_elf(__file__)


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _card():
    return {"libc.so.6": M.read_elf_file(fix("card_libc.so.6"))}


def test_check_refuses_the_reporters_hook():
    why = M.check_elf("lib/hook.so", M.read_elf_file(fix("modern.so")),
                      dict(_card(), **{"ld-linux-armhf.so.3": None}))
    assert len(why) == 1
    assert "GLIBC_2.34 (dlsym)" in why[0]
    assert "only goes up to GLIBC_2.13" in why[0]
    assert "pad_mods/" in why[0]


def test_check_passes_a_hook_built_for_the_card():
    assert M.check_elf("lib/hook.so", M.read_elf_file(fix("old.so")),
                       _card()) == []


def test_check_refuses_a_pc_build():
    why = M.check_elf("lib/hook.so", M.read_elf_file(fix("x86.so")), {})
    assert len(why) == 1 and "64-bit x86" in why[0]


def test_check_refuses_soft_float():
    data = bytearray(open(fix("old.so"), "rb").read())
    data[36:40] = (0x05000200).to_bytes(4, "little")
    why = M.check_elf("lib/hook.so", M.read_elf(bytes(data)), _card())
    assert len(why) == 1 and "soft-float" in why[0]


def test_check_skips_a_library_the_card_lacks():
    # not found on the card: named as a warning by the Write, not refused
    assert M.check_elf("lib/hook.so", M.read_elf_file(fix("modern.so")),
                       {"libc.so.6": None}) == []


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def test_mod_sources_map_to_libraries(tmp_path):
    root = tmp_path / M.MODS_DIR
    (root / "lib").mkdir(parents=True)
    (root / "lib" / "hook.c").write_text("int a;")
    (root / "lib" / "hook.h").write_text("")
    (root / "top.c").write_text("int b;")
    (root / "multi.so" / "part").mkdir(parents=True)
    (root / "multi.so" / "a.c").write_text("int c;")
    (root / "multi.so" / "part" / "b.c").write_text("int d;")
    plan = M.mod_sources(str(tmp_path))
    assert sorted(plan) == ["lib/hook.so", "multi.so", "top.so"]
    assert [os.path.basename(s) for s in plan["multi.so"]] == ["a.c", "b.c"]
    assert M.mod_sources(str(tmp_path / "nothing")) == {}


def test_compile_command_targets_the_card_abi():
    cmd = M.compile_command(M.CROSS_CC, "/o/hook.so", ["/s/hook.c"], ["/s"],
                            ["/c/libc.so.6"])
    words = shlex.split(cmd.replace(" 2>&1", ""))
    assert words[0] == "arm-linux-gnueabihf-gcc"
    # Ubuntu 24.04's armhf gcc turns 64-bit time_t / off_t on: glibc 2.34 names
    for flag in ("-U_TIME_BITS", "-U_FILE_OFFSET_BITS", "-U_FORTIFY_SOURCE",
                 "-mfloat-abi=hard", "-nodefaultlibs", "-Wl,--no-undefined"):
        assert flag in words
    assert words.index("/c/libc.so.6") > words.index("/s/hook.c")


def test_diff_never_ships_the_sources(tmp_path):
    (tmp_path / "game.wav").write_bytes(b"x")
    cgc_pipeline.generate_checksums(str(tmp_path))
    (tmp_path / M.MODS_DIR / "lib").mkdir(parents=True)
    (tmp_path / M.MODS_DIR / "lib" / "hook.c").write_text("int a;")
    changed, _missing = cgc_pipeline._diff_assets(
        str(tmp_path), cgc_pipeline.read_checksums(str(tmp_path)))
    assert changed == {}


# ---------------------------------------------------------------------------
# The Write's steps, against a fake card
# ---------------------------------------------------------------------------

class _CardExecutor(WslExecutor):
    """debugfs ``stat`` / ``dump`` answered from a dict of card paths ->
    host files (or ``"-> target"`` for a symlink)."""

    def __init__(self, card, cc=True):
        super().__init__()
        self.card, self.cc, self.commands = card, cc, []

    def run(self, bash_cmd, timeout=120):
        self.commands.append(bash_cmd)
        if bash_cmd.startswith("command -v"):
            if not self.cc:
                raise CommandError(bash_cmd, 1, "")
            return ""
        words = shlex.split(bash_cmd)
        if words[0] == "debugfs":
            req = words[words.index("-R") + 1]
            verb, _, rest = req.partition(" ")
            args = re.findall(r'"([^"]*)"', rest)
            entry = self.card.get(args[0])
            if verb == "stat":
                if entry is None:
                    return f"{args[0]}: File not found by ext2_lookup"
                if entry.startswith("-> "):
                    return (f'Inode: 9   Type: symlink    Mode:  0777\n'
                            f'Fast link dest: "{entry[3:]}"\n')
                return "Inode: 12   Type: regular    Mode:  0755\n"
            if verb == "dump" and entry and not entry.startswith("-> "):
                dest = args[1]
                shutil.copyfile(entry, dest)
            return ""
        if words[0] == M.CROSS_CC:
            out = words[words.index("-o") + 1]
            shutil.copyfile(fix("old.so"), out)
            return ""
        return ""

    def to_exec_path(self, host_path):
        return host_path                 # the fake runs on the host


CARD = {
    "/lib/arm-linux-gnueabihf/libc.so.6": "-> libc-2.13.so",
    "/lib/arm-linux-gnueabihf/libc-2.13.so": fix("card_libc.so.6"),
}


def _pipeline(tmp_path, card, **kw):
    logs = []
    p = WritePipeline("in.img", str(tmp_path), "out.img",
                      lambda m, lvl="info": logs.append((lvl, m)),
                      lambda *a: None, lambda *a: None, lambda *a: None)
    p.executor = _CardExecutor(card, **kw)
    return p, logs


def test_write_refuses_the_reporters_hook(tmp_path):
    p, logs = _pipeline(tmp_path, CARD)
    with pytest.raises(PipelineError) as e:
        p._check_programs("inner.img", {"lib/hook.so": fix("modern.so")},
                          str(tmp_path), "/home/debian/emumm")
    msg = e.value.message
    assert "lib/hook.so needs GLIBC_2.34 (dlsym) from libc.so.6" in msg
    assert "only goes up to GLIBC_2.13" in msg
    assert "Nothing was written" in msg


def test_write_passes_a_card_build_and_ignores_other_files(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    p, logs = _pipeline(tmp_path, CARD)
    p._check_programs("inner.img", {"lib/hook.so": fix("old.so"),
                                    "a.wav": str(wav)},
                      str(tmp_path), "/home/debian/emumm")
    assert ("success", "  lib/hook.so: 32-bit ARM, asks for up to GLIBC_2.4 "
            "-- the machine has it") in logs


def test_write_builds_pad_mods_against_the_card(tmp_path):
    (tmp_path / M.MODS_DIR / "lib").mkdir(parents=True)
    (tmp_path / M.MODS_DIR / "lib" / "hook.c").write_text("int a;")
    plan = M.mod_sources(str(tmp_path))
    out = str(tmp_path / "build" / M.MODS_DIR / "lib" / "hook.so")
    changed = {"lib/hook.so": out}
    libs = tmp_path / "libs"
    libs.mkdir()
    p, logs = _pipeline(tmp_path, CARD)
    p._build_mods("inner.img", plan, changed, str(libs))
    cc = [c for c in p.executor.commands if c.startswith(M.CROSS_CC)]
    assert len(cc) == 1
    # linked against the libc copied off the card, with the 2.13 shims
    assert re.search(r"libs[/\\]\d+[/\\]libc\.so\.6", cc[0])
    assert "pad_libc_compat.c" in cc[0]
    assert os.path.isfile(out)
    p._check_programs("inner.img", changed, str(libs), "/home/debian/emumm")


def test_write_says_how_to_get_the_compiler(tmp_path):
    (tmp_path / M.MODS_DIR).mkdir()
    (tmp_path / M.MODS_DIR / "hook.c").write_text("int a;")
    p, _logs = _pipeline(tmp_path, CARD, cc=False)
    with pytest.raises(PipelineError) as e:
        p._build_mods("inner.img", M.mod_sources(str(tmp_path)),
                      {"hook.so": str(tmp_path / "hook.so")}, str(tmp_path))
    assert "gcc-arm-linux-gnueabihf" in e.value.message


def test_write_without_card_libc_refuses_to_build(tmp_path):
    (tmp_path / M.MODS_DIR).mkdir()
    (tmp_path / M.MODS_DIR / "hook.c").write_text("int a;")
    libs = tmp_path / "libs"
    libs.mkdir()
    p, _logs = _pipeline(tmp_path, {})
    with pytest.raises(PipelineError) as e:
        p._build_mods("inner.img", M.mod_sources(str(tmp_path)),
                      {"hook.so": str(tmp_path / "hook.so")}, str(libs))
    assert "no libc.so.6" in e.value.message
