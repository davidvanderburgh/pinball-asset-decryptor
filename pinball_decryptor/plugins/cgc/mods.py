"""CGC code mods: C built for the machine, and the check every program passes.

A CGC machine is a BeagleBone Black running Debian 7 (armhf, glibc 2.13).  A
library or program built on a modern Linux asks for symbol versions that
glibc does not have (``dlsym@GLIBC_2.34`` from any gcc of the last few
years), and the machine's loader refuses it.  Preloaded from the boot path,
that refusal is PID 1 dying: a kernel panic and a boot loop (PAD-877).

Two halves, both run by the CGC Write:

* **Build.**  C under the project's ``pad_mods/`` folder is compiled with
  the ARM cross compiler and linked against the card's OWN libraries (dumped
  from the game filesystem being written), so it can only ask for what the
  machine has: a newer symbol is a link error naming it, not a boot loop.
  ``pad_mods/<path>/<name>.c`` becomes ``<path>/<name>.so`` in the game
  folder; a folder ``pad_mods/<path>/<name>.so/`` of several ``.c`` files
  becomes one library.  The sources never ship.

* **Check.**  Every program or library the build would write (compiled here
  or dropped in by hand) is read before anything is written: it must be
  32-bit ARM, hard-float, and every ``GLIBC_x`` (any symbol version) it asks
  of a library must be one that library on the card defines.
"""

import os
import re
import struct

#: The project folder whose C is compiled for the machine.  Never shipped.
MODS_DIR = "pad_mods"

CROSS_CC = "arm-linux-gnueabihf-gcc"

#: Where the machine's loader looks for a library by name (Debian 7 armhf
#: multiarch first), as paths inside the game filesystem.
LIB_DIRS = ("/lib/arm-linux-gnueabihf", "/usr/lib/arm-linux-gnueabihf",
            "/lib", "/usr/lib", "/usr/local/lib")

#: The card's libraries a mod is linked against: glibc's own.  Linked
#: ``--as-needed``, so a mod only names the ones it uses.
LINK_LIBS = ("libdl.so.2", "libpthread.so.0", "libm.so.6", "librt.so.1",
             "libc.so.6", "ld-linux-armhf.so.3")

#: The machine is a Cortex-A8: Debian 7 armhf's baseline.  The toolchain's
#: glibc headers are newer than the card's, so fortify (whose ``__*_chk``
#: helpers grew after 2.13) and the stack protector are off, and so are the
#: 64-bit time_t and off_t Ubuntu 24.04's armhf gcc turns on by default:
#: they rename stat(), time() and the rest to glibc 2.34's ``__*_time64``
#: and change the structs the card's libc fills in.  --no-undefined makes a
#: symbol the card's glibc does not have a link error.
CFLAGS = ("-shared", "-fPIC", "-O2", "-march=armv7-a", "-mfpu=vfpv3-d16",
          "-mfloat-abi=hard", "-U_FORTIFY_SOURCE", "-U_TIME_BITS",
          "-U_FILE_OFFSET_BITS", "-fno-stack-protector",
          "-ffunction-sections", "-nodefaultlibs")
LDFLAGS = ("-Wl,--no-undefined", "-Wl,--as-needed", "-Wl,--gc-sections")

#: What glibc 2.13's libc_nonshared.a gave every program and the card has no
#: copy of: today's headers declare stat() and friends as plain functions,
#: glibc 2.13 only exports the __xstat family behind them.  Hidden, so the
#: mod's copy never stands in for the game's.
COMPAT_SOURCE = r"""/* PAD: libc_nonshared.a of glibc 2.13, for a mod linked to the card's libc */
#define _GNU_SOURCE
#include <sys/stat.h>
#include <fcntl.h>
#define PAD_HIDDEN __attribute__((visibility("hidden")))
#define PAD_STAT_VER 3
extern int __xstat(int, const char *, struct stat *);
extern int __lxstat(int, const char *, struct stat *);
extern int __fxstat(int, int, struct stat *);
extern int __fxstatat(int, int, const char *, struct stat *, int);
extern int __xstat64(int, const char *, struct stat64 *);
extern int __lxstat64(int, const char *, struct stat64 *);
extern int __fxstat64(int, int, struct stat64 *);
extern int __fxstatat64(int, int, const char *, struct stat64 *, int);
extern int __cxa_atexit(void (*)(void *), void *, void *);
extern int __register_atfork(void (*)(void), void (*)(void), void (*)(void), void *);
extern void *__dso_handle;
PAD_HIDDEN int stat(const char *p, struct stat *b) { return __xstat(PAD_STAT_VER, p, b); }
PAD_HIDDEN int lstat(const char *p, struct stat *b) { return __lxstat(PAD_STAT_VER, p, b); }
PAD_HIDDEN int fstat(int fd, struct stat *b) { return __fxstat(PAD_STAT_VER, fd, b); }
PAD_HIDDEN int fstatat(int d, const char *p, struct stat *b, int f) { return __fxstatat(PAD_STAT_VER, d, p, b, f); }
PAD_HIDDEN int stat64(const char *p, struct stat64 *b) { return __xstat64(PAD_STAT_VER, p, b); }
PAD_HIDDEN int lstat64(const char *p, struct stat64 *b) { return __lxstat64(PAD_STAT_VER, p, b); }
PAD_HIDDEN int fstat64(int fd, struct stat64 *b) { return __fxstat64(PAD_STAT_VER, fd, b); }
PAD_HIDDEN int fstatat64(int d, const char *p, struct stat64 *b, int f) { return __fxstatat64(PAD_STAT_VER, d, p, b, f); }
PAD_HIDDEN int atexit(void (*fn)(void)) { return __cxa_atexit((void (*)(void *))fn, 0, __dso_handle); }
PAD_HIDDEN int pthread_atfork(void (*a)(void), void (*b)(void), void (*c)(void)) { return __register_atfork(a, b, c, __dso_handle); }
"""


class ElfError(Exception):
    """Not an ELF this module can read."""


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def mod_sources(assets_dir):
    """``{target rel path: [source .c paths]}`` for every mod under
    ``pad_mods/``: ``<p>/<n>.c`` -> ``<p>/<n>.so``, and a folder
    ``<p>/<n>.so/`` -> ``<p>/<n>.so`` from all the ``.c`` files in it."""
    root = os.path.join(assets_dir, MODS_DIR)
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        rel_dir = "" if rel_dir == "." else rel_dir
        lib_folder = None
        parts = rel_dir.split("/") if rel_dir else []
        for i, part in enumerate(parts):
            if part.lower().endswith(".so"):
                lib_folder = "/".join(parts[:i + 1])
                break
        for fn in sorted(filenames):
            if fn.startswith(".") or not fn.lower().endswith(".c"):
                continue
            src = os.path.join(dirpath, fn)
            if lib_folder:
                out.setdefault(lib_folder, []).append(src)
            else:
                target = (rel_dir + "/" if rel_dir else "") + fn[:-2] + ".so"
                out.setdefault(target, []).append(src)
    return out


def compile_command(cc, out, sources, include_dirs, libs):
    """The shell command that builds *sources* into *out* against the card's
    *libs* (exec-side paths throughout)."""
    import shlex
    q = shlex.quote
    args = [cc, *CFLAGS]
    for d in include_dirs:
        args += ["-I", d]
    args += ["-o", out, *sources, *LDFLAGS, *libs, "-lgcc"]
    return " ".join(q(a) for a in args) + " 2>&1"


# ---------------------------------------------------------------------------
# ELF reading (32-bit little-endian in full; anything else far enough to name)
# ---------------------------------------------------------------------------

EM_ARM = 40
_MACHINES = {3: "32-bit x86", 62: "64-bit x86 (a PC)", 183: "64-bit ARM",
             40: "32-bit ARM", 8: "MIPS", 243: "RISC-V"}
EF_ARM_ABI_FLOAT_SOFT = 0x200
EF_ARM_ABI_FLOAT_HARD = 0x400

PT_LOAD, PT_DYNAMIC = 1, 2
DT_NEEDED, DT_STRTAB, DT_SYMTAB, DT_SONAME, DT_RPATH = 1, 5, 6, 14, 15
DT_RUNPATH = 29
DT_HASH = 4
DT_VERSYM, DT_VERDEF, DT_VERDEFNUM = 0x6ffffff0, 0x6ffffffc, 0x6ffffffd
DT_VERNEED, DT_VERNEEDNUM = 0x6ffffffe, 0x6fffffff
SHT_DYNSYM = 11


def is_elf(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def read_elf(data):
    """What the loader needs of an ELF: ``{"bits", "machine", "flags",
    "needed", "soname", "runpath", "verneed": {lib: {version: [symbol]}},
    "verdef": [version]}``.  Raises :class:`ElfError` on a non-ELF."""
    if data[:4] != b"\x7fELF" or len(data) < 52:
        raise ElfError("not an ELF file")
    bits = {1: 32, 2: 64}.get(data[4])
    little = data[5] == 1
    e = "<" if little else ">"
    machine = struct.unpack_from(e + "H", data, 18)[0]
    info = {"bits": bits, "little": little, "machine": machine, "flags": 0,
            "needed": [], "soname": None, "runpath": [], "verneed": {},
            "verdef": []}
    if bits != 32 or not little:
        return info                    # named by the check, never loaded
    (phoff, shoff, flags, _ehs, phes, phn, shes, shn,
     _shstr) = struct.unpack_from("<IIIHHHHHH", data, 28)
    info["flags"] = flags
    loads, dyn = [], None
    for i in range(phn):
        o = phoff + i * phes
        if o + 32 > len(data):
            break
        p_type, p_off, p_vaddr, _pa, p_filesz = struct.unpack_from("<IIIII", data, o)
        if p_type == PT_LOAD:
            loads.append((p_vaddr, p_off, p_filesz))
        elif p_type == PT_DYNAMIC:
            dyn = (p_off, p_filesz)
    if dyn is None:
        return info                    # static: asks nothing of the card

    def off(vaddr):
        for va, fo, sz in loads:
            if va <= vaddr < va + sz:
                return fo + vaddr - va
        return None

    tags = []
    for o in range(dyn[0], min(dyn[0] + dyn[1], len(data) - 7), 8):
        tag, val = struct.unpack_from("<iI", data, o)
        if tag == 0:
            break
        tags.append((tag & 0xffffffff, val))
    d = {}
    for tag, val in tags:
        d.setdefault(tag, val)
    strtab = off(d[DT_STRTAB]) if DT_STRTAB in d else None

    def s(o):
        if strtab is None:
            return ""
        a = strtab + o
        b = data.find(b"\0", a)
        return data[a:b if b >= 0 else len(data)].decode("latin-1")

    for tag, val in tags:
        if tag == DT_NEEDED:
            info["needed"].append(s(val))
        elif tag == DT_SONAME:
            info["soname"] = s(val)
        elif tag in (DT_RPATH, DT_RUNPATH):
            info["runpath"] += [p for p in s(val).split(":") if p]

    # version index -> (lib, version) of what this file asks for
    wants = {}
    if DT_VERNEED in d and off(d[DT_VERNEED]) is not None:
        o = off(d[DT_VERNEED])
        for _ in range(d.get(DT_VERNEEDNUM, 0)):
            _v, cnt, fname, aux, nxt = struct.unpack_from("<HHIII", data, o)
            lib = s(fname)
            info["verneed"].setdefault(lib, {})
            a = o + aux
            for _ in range(cnt):
                _h, _f, other, name, anext = struct.unpack_from("<IHHII", data, a)
                info["verneed"][lib].setdefault(s(name), [])
                wants[other & 0x7fff] = (lib, s(name))
                if not anext:
                    break
                a += anext
            if not nxt:
                break
            o += nxt
    if DT_VERDEF in d and off(d[DT_VERDEF]) is not None:
        o = off(d[DT_VERDEF])
        for _ in range(d.get(DT_VERDEFNUM, 0)):
            _v, vflags, _ndx, cnt, _h, aux, nxt = struct.unpack_from("<HHHHIII", data, o)
            if cnt and not vflags & 1:          # VER_FLG_BASE names the file
                name = struct.unpack_from("<I", data, o + aux)[0]
                info["verdef"].append(s(name))
            if not nxt:
                break
            o += nxt

    # which symbols ask for each version (for the words of a refusal)
    if wants and DT_VERSYM in d and DT_SYMTAB in d:
        nsyms = _dynsym_count(data, shoff, shes, shn, d, off)
        vs, st = off(d[DT_VERSYM]), off(d[DT_SYMTAB])
        if nsyms and vs is not None and st is not None:
            for i in range(1, nsyms):
                if vs + 2 * i + 2 > len(data) or st + 16 * i + 16 > len(data):
                    break
                ndx = struct.unpack_from("<H", data, vs + 2 * i)[0] & 0x7fff
                if ndx in wants:
                    shndx = struct.unpack_from("<H", data, st + 16 * i + 14)[0]
                    if shndx == 0:                 # undefined here: asked of a lib
                        lib, ver = wants[ndx]
                        name = s(struct.unpack_from("<I", data, st + 16 * i)[0])
                        info["verneed"][lib][ver].append(name)
    return info


def _dynsym_count(data, shoff, shes, shn, d, off):
    for i in range(shn if shoff else 0):
        o = shoff + i * shes
        if o + 40 > len(data):
            break
        sh_type, = struct.unpack_from("<I", data, o + 4)
        if sh_type == SHT_DYNSYM:
            size, = struct.unpack_from("<I", data, o + 20)
            return size // 16
    if DT_HASH in d and off(d[DT_HASH]) is not None:
        return struct.unpack_from("<I", data, off(d[DT_HASH]) + 4)[0]
    return 0


def read_elf_file(path):
    with open(path, "rb") as f:
        return read_elf(f.read())


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def _vkey(v):
    return tuple(int(n) for n in re.findall(r"\d+", v))


def newest(versions, prefix="GLIBC_"):
    """The newest *prefix* version in *versions* ("GLIBC_2.13"), or None."""
    got = [v for v in versions if v.startswith(prefix)]
    return max(got, key=_vkey) if got else None


def check_elf(rel, info, card_libs, machine_flags=None):
    """Why *rel* (read by :func:`read_elf`) cannot run on the machine, as a
    list of sentences ([] = fine).  *card_libs* maps each library name it
    needs to that library on the card read the same way, or None when the
    card has no library of that name PAD could find."""
    why = []
    if info["bits"] != 32 or not info["little"] or info["machine"] != EM_ARM:
        what = _MACHINES.get(info["machine"], "machine type %d" % info["machine"])
        if info["bits"] == 64 and info["machine"] == 62:
            what = "64-bit x86 (a PC)"
        why.append("%s is built for %s, not the machine's 32-bit ARM. Build it "
                   "with an arm-linux-gnueabihf compiler, or put its C under "
                   "%s/ so the Write builds it." % (rel, what, MODS_DIR))
        return why
    if info["flags"] & EF_ARM_ABI_FLOAT_SOFT and not info["flags"] & EF_ARM_ABI_FLOAT_HARD:
        why.append("%s is built soft-float (arm-linux-gnueabi); the machine's "
                   "Debian is hard-float (arm-linux-gnueabihf) and will not "
                   "load it." % rel)
    for lib, versions in sorted(info["verneed"].items()):
        have = card_libs.get(lib)
        if have is None:
            continue                         # named as a warning by the caller
        missing = [v for v in versions if v not in have["verdef"]]
        if not missing:
            continue
        top = newest(have["verdef"], missing[0].split("_")[0] + "_") \
            if "_" in missing[0] else None
        parts = []
        for v in sorted(missing, key=_vkey):
            syms = sorted(set(versions[v]))
            parts.append("%s (%s)" % (v, ", ".join(syms[:6]) + (" ..." if len(syms) > 6 else ""))
                         if syms else v)
        why.append("%s needs %s from %s, but the machine's %s %s. The machine "
                   "would refuse to load it (preloaded at boot, that is a "
                   "boot loop). Rebuild it against the machine's own "
                   "libraries: put its C under %s/ and the Write builds it."
                   % (rel, ", ".join(parts), lib, lib,
                      "only goes up to %s" % top if top else
                      "does not define %s" % ", ".join(missing),
                      MODS_DIR))
    return why
