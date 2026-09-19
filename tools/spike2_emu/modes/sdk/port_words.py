#!/usr/bin/env python3
"""port_words.py - fill in, or check, a port's instruction words from the game's ELF.

    port_words.py <game ELF> <port file>            check: report every site that differs
    port_words.py <game ELF> <port file> --write    rewrite each `site` line's two words

A port's `site <name> <address> <w0> <w1>` lines carry the first two instruction words
the runtime compares before it touches that function - the safety gate that makes a
port for the wrong game or version hook nothing. Those words must come from the ELF,
never from a person, so this is how a port gets them.

It also refuses a HOOKED site (tick, shot_dispatch, ball_end, sound_lookup) whose first
two instructions depend on the program counter: those cannot be moved into a
trampoline, and hooking one would crash the game. A literal load (`ldr rd, [pc, #n]`) is
the exception: the runtime copies the literal and moves it (item 137).
"""
import re
import struct
import sys

HOOKED = {"tick", "shot_dispatch", "ball_end", "sound_lookup"}
HOOKED |= {"hook_dispatch"}          # item 147: the event bus's dispatch, hooked when present


def event_problems(n, parts, sites=()):
    """item 147: `event <name> <id>` - a name the runtime keeps (39 characters) and a bus id
    (0..207) - or `event <name> site <site name>`, a site the port names. Returns the problem
    lines."""
    out = []
    if len(parts) < 3:
        return ["line %d: an event needs a name and an id" % n]
    name, rest = parts[1], parts[2].split()
    if len(name) > 39:
        out.append("line %d: the event name %r is over 39 characters" % (n, name))
    if rest and rest[0] == "site":
        if len(rest) < 2 or rest[1].startswith("#"):
            return out + ["line %d: the event %r names no site" % (n, name)]
        if rest[1] not in sites:
            out.append("line %d: the event %r names site %r, which the port has no line for" % (n, name, rest[1]))
        return out
    try:
        ident = int(rest[0], 0)
    except (ValueError, IndexError):
        return out + ["line %d: the event %r has no numeric id" % (n, name)]
    if not 0 <= ident <= 207:
        out.append("line %d: the event %r id %d is outside 0..207" % (n, name, ident))
    return out


def segments(elf):
    if elf[:4] != b"\x7fELF" or elf[4] != 1:
        raise SystemExit("not a 32-bit ELF")
    phoff, = struct.unpack_from("<I", elf, 0x1C)
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x2A)
    out = []
    for i in range(phnum):
        p_type, p_off, p_vaddr, _pa, p_filesz, _ms, flags, _al = struct.unpack_from("<8I", elf, phoff + i * phentsize)
        if p_type == 1:
            out.append((p_vaddr, p_off, p_filesz, flags))
    return out


def words_at(elf, segs, va):
    for vaddr, off, size, flags in segs:
        if vaddr <= va and va + 8 <= vaddr + size:
            if not flags & 1:
                raise ValueError("0x%x is not in executable code" % va)
            return struct.unpack_from("<II", elf, off + va - vaddr)
    raise ValueError("0x%x is not in the ELF" % va)


def pc_dependent(w):
    if (w & 0x0E000000) == 0x0A000000:                 # b / bl / blx imm
        return True
    if (w >> 26) & 3 == 1 and ((w >> 16) & 0xF) == 15:  # ldr/str based on pc
        return True
    if (w >> 26) & 3 == 0 and (((w >> 16) & 0xF) == 15 or ((w >> 12) & 0xF) == 15):
        return (w & 0x0FB00000) != 0x03000000          # movw/movt carry imm4 there
    if (w & 0x0E108000) == 0x08108000:                 # ldm ... pc
        return True
    return False


def literal_load(w):
    """`ldr rd, [pc, #+-n]` with rd not pc: pad_mode_runtime.c relocates it."""
    return (w & 0xFF7F0000) == 0xE51F0000 and ((w >> 12) & 0xF) != 15


def movable(w0, w1):
    """Can the trampoline run these two words somewhere else? A return (bx lr) can, unless it
    is the function's first and only instruction."""
    if w0 == 0xE12FFF1E:
        return False
    return not any(pc_dependent(w) and not literal_load(w) and (w & 0x0FFFFFFF) != 0x012FFF1E
                   for w in (w0, w1))


SITE = re.compile(r"^(\s*site\s+)(\S+)(\s+)(0x[0-9a-fA-F]+|\d+)(.*)$")

# item 146: the runtime hooks the battle roster's start too (pad_mode_runtime.c on_roster_start)
HOOKED = HOOKED | {"roster_start"}


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    elf = open(argv[0], "rb").read()
    segs = segments(elf)
    lines = open(argv[1], encoding="utf-8").read().splitlines()
    write = "--write" in argv
    bad = 0
    out = []
    # the runtime's fixed buffers (pad_mode_runtime.c): a longer entry would be cut short
    for n, line in enumerate(lines, 1):
        parts = line.split(None, 2)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        key = parts[0]
        if key in ("site", "data", "value", "callout", "scene", "text") and len(parts[1]) > 39:
            print("line %d: the name %r is over 39 characters" % (n, parts[1]))
            bad += 1
        if key in ("text", "scene") and len(parts) == 3 and len(parts[2].strip()) > 159:
            print("line %d: the value is over 159 characters" % n)
            bad += 1
        if key == "shot" and len(parts) == 3 and len(parts[2].strip()) > 159:
            print("line %d: the shot name is over 159 characters" % n)
            bad += 1
        if key == "event":
            for problem in event_problems(n, parts, {l.split()[1] for l in lines if l.split()[:1] == ["site"] and len(l.split()) > 1}):
                print(problem)
                bad += 1
    # item 147: a site an `event <name> site <site>` line names is hooked too
    event_sites = {l.split()[3] for l in lines if l.split()[:1] == ["event"] and len(l.split()) > 3 and l.split()[2] == "site"}
    for line in lines:
        m = SITE.match(line)
        if not m:
            out.append(line)
            continue
        name, va = m.group(2), int(m.group(4), 0)
        try:
            w0, w1 = words_at(elf, segs, va)
        except ValueError as e:
            print("%-16s %s" % (name, e))
            bad += 1
            out.append(line)
            continue
        if (name in HOOKED or name in event_sites) and not movable(w0, w1):
            print("%-16s 0x%08x starts %08x %08x - cannot be hooked (pc-relative)" % (name, va, w0, w1))
            bad += 1
        old = m.group(5).split()
        have = [int(x, 0) for x in old[:2]] if len(old) >= 2 else []
        if have != [w0, w1]:
            print("%-16s 0x%08x: port says %s, the ELF has %08x %08x"
                  % (name, va, " ".join(old[:2]) or "(nothing)", w0, w1))
            if not write:
                bad += 1
        tail = " ".join(old[2:])
        out.append("site %-16s 0x%08x 0x%08x 0x%08x%s" % (name, va, w0, w1, ("  " + tail) if tail else ""))
    if write:
        with open(argv[1], "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(out) + "\n")
        print("wrote %s" % argv[1])
    print("%d problem(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
