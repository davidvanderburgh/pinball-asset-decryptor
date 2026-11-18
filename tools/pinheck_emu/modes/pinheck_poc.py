"""Proof of concept: a rule change in a pinHeck PRG by a call-site trampoline (PAD-1387).

A pinHeck game's rules are compiled C/C++ (chipKIT) in ``<GAME>_Vnnn.PRG``,
raw PIC32 program flash from 0x9D000000. There is no engine to load modes
into, so a mode runtime has to live in the free flash after the program and
be reached by re-pointing ``jal`` instructions at it.

This proof does the smallest such change on Jetsons V004: playfield switch 0
(its handler calls ``AddScore(150)`` from the ``jal`` at 0x9D01FF50) is
re-pointed at a trampoline in free flash that

  1. calls the game's own ``AddScore`` with the original arguments (the game
     plays on exactly as before),
  2. calls ``AddScore(1,000,000)`` (the game's own scoring: replay check,
     mode total, score packet 0x03 to the Propeller),
  3. calls the game's ``video()`` with ``EB0`` (DMD/_DE/EB0.VID) and
     ``playSFX()`` with ``EB0`` (SFX/_FE/EB0.wav), and returns.

Usage (writes a patched COPY; the input is never touched)::

    python -m tools.pinheck_emu.modes.pinheck_poc build <JET_V004.PRG> <out.PRG>
    python -m tools.pinheck_emu.modes.pinheck_poc prove <out.PRG> --card <card dir>
        [--nvram DIR] [--frames DIR] [--at 27,29]

``prove`` starts a game in the emulator (coin, start, launch), pulses switch
0 at the given seconds and prints the score, video and sound packets after
each pulse, plus the score the game ends up holding.

How the addresses were found (JET_V004.PRG):
  0x9D028BD8  link transfer: ``sb a1,15(dataOut)``, clocks RF5/RF12 (LATF
              SET/CLR), dataOut 0xA0002768, dataIn 0xA0002778
  wrappers    the 26 functions that tail-jump into it, by the command in a1:
              0x9D02E58C video (0x02), 0x9D02F684 playSFX (0x01),
              0x9D02EB4C SetScore (0x03), ...; ``this`` = gp-0x7BA8
  0x9D02BE84  AddScore(points, flag): every write to playerScore
              (0xA000271C + 4*player, player byte gp-0x7B1A) comes through
              its call of 0x9D02BB38; 63 call sites
  0x9D01FF50  the AddScore(150) call run when switch 0 is hit (code hook on
              AddScore's entry, $ra per switch pulsed)
"""
import argparse
import struct
import sys

FLASH = 0x9D000000
FLASH_SIZE = 0x80000            # PIC32MX795F512L: 512 KB program flash

#: per title + version: the game's functions and the bytes expected there,
#: so a different build is refused instead of patched blind.
TITLES = {
    "JET_V004": dict(
        size=0x2FF60,
        add_score=0x9D02BE84, video=0x9D02E58C, play_sfx=0x9D02F684,
        link_this_gp=-0x7BA8,
        site=0x9D01FF50,            # jal AddScore in switch 0's handler
        tramp=0x9D030000,           # first 64 KB boundary after the program
    ),
}


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x3FFFFFF)


def addiu(rt, rs, imm):
    return (9 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def sw(rt, off, base):
    return (0x2B << 26) | (base << 21) | (rt << 16) | (off & 0xFFFF)


def lw(rt, off, base):
    return (0x23 << 26) | (base << 21) | (rt << 16) | (off & 0xFFFF)


def lui(rt, imm):
    return (0x0F << 26) | (rt << 16) | (imm & 0xFFFF)


def ori(rt, rs, imm):
    return (0x0D << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


NOP, JR_RA = 0, 0x03E00008
ZERO, A0, A1, A2, A3, T0, GP, SP, RA = 0, 4, 5, 6, 7, 8, 28, 29, 31


def trampoline(t, points, video, sound, sfx_channel=1):
    """MIPS o32 code: original AddScore(a0, a1), then our points, video, sound."""
    this = t["link_this_gp"]
    v, s = video.encode(), sound.encode()
    code = [
        addiu(SP, SP, -40), sw(RA, 36, SP),
        jal(t["add_score"]), NOP,                       # the game's own call, unchanged args
        lui(A0, points >> 16), ori(A0, A0, points & 0xFFFF),
        jal(t["add_score"]), addiu(A1, ZERO, 0),        # AddScore(points, 0)
        # video(this, slot 0, n0, n1, [16] n2, [20] priority 0, [24] next 0, [28] 1)
        addiu(T0, ZERO, v[2]), sw(T0, 16, SP), sw(ZERO, 20, SP), sw(ZERO, 24, SP),
        addiu(T0, ZERO, 1), sw(T0, 28, SP),
        addiu(A0, GP, this), addiu(A1, ZERO, 0), addiu(A2, ZERO, v[0]),
        jal(t["video"]), addiu(A3, ZERO, v[1]),
        # playSFX(this, channel, folder, clip0, [16] clip1, [20] priority 255)
        addiu(T0, ZERO, s[2]), sw(T0, 16, SP), addiu(T0, ZERO, 255), sw(T0, 20, SP),
        addiu(A0, GP, this), addiu(A1, ZERO, sfx_channel), addiu(A2, ZERO, s[0]),
        jal(t["play_sfx"]), addiu(A3, ZERO, s[1]),
        lw(RA, 36, SP), JR_RA, addiu(SP, SP, 40),
    ]
    return struct.pack("<%dI" % len(code), *code)


def build(prg, name="JET_V004", points=1_000_000, video="EB0", sound="EB0"):
    t = TITLES[name]
    if len(prg) != t["size"]:
        raise ValueError("%s: expected %d bytes, got %d" % (name, t["size"], len(prg)))
    word = lambda a: struct.unpack_from("<I", prg, a - FLASH)[0]
    if word(t["site"]) != jal(t["add_score"]):
        raise ValueError("call site %x is not jal AddScore - another build?" % t["site"])
    if word(t["video"] + 0x44) >> 26 != 2 or word(t["play_sfx"] + 0x24) >> 26 != 2:
        raise ValueError("video/playSFX wrappers not where expected")
    code = trampoline(t, points, video, sound)
    off = t["tramp"] - FLASH
    if off < len(prg) or off + len(code) > FLASH_SIZE:
        raise ValueError("trampoline not in free flash")
    out = bytearray(prg) + b"\xFF" * (off - len(prg)) + code
    struct.pack_into("<I", out, t["site"] - FLASH, jal(t["tramp"]))
    return bytes(out)


def prove(path, card, nvram, frames, at, seconds_after=3.0):
    import os
    from tools.pinheck_emu import run as R
    from tools.pinheck_emu.games import game_of
    prg = open(path, "rb").read()
    state = {"ms": 0, "hit": None}
    box, saved = [], []
    hits = [int(s * 1000) for s in at]

    def on_ms(ms):
        state["ms"] = ms
        link = box[0] if box else None
        if not link:
            return
        for h in hits:
            if ms == h:
                state["hit"] = h
                link.board.set(0, True)
                print("%.2fs  switch 0 closed" % (ms / 1000))
            elif ms == h + 120:
                link.board.set(0, False)
        if frames and state["hit"] is not None and (ms - state["hit"]) in (300, 1000, 2000) and link.av:
            img = link.av.frame(ms)
            p = os.path.join(frames, "%07d.png" % ms)
            img.resize((img.width * 4, img.height * 4)).save(p)
            saved.append(p)

    def log(pkt):
        if state["hit"] is None or state["ms"] > state["hit"] + 2000 or pkt[15] not in (1, 2, 3):
            return
        if pkt[15] == 3:
            what = "score[%d] = %d" % (pkt[0], int.from_bytes(pkt[1:5], "little"))
        else:
            what = ("video " if pkt[15] == 2 else "sound ") + "".join(
                chr(b) if 32 <= b < 127 else "." for b in pkt[:5])
        print("%.2fs  PKT %s  %s" % (state["ms"] / 1000, pkt.hex(" "), what))

    if frames:
        os.makedirs(frames, exist_ok=True)
    taps = [(14, "coin"), (15, "start"), (22, "launch"), (22.4, "launch")]
    pic, link = R.boot(prg, max(at) + seconds_after, log, card, nvram, (), taps,
                       on_ms=[on_ms], link_box=box, game=game_of(path))
    player = pic.mu.mem_read(0xA00006E6 & 0x1FFFFFFF, 1)[0]
    score = struct.unpack("<I", pic.mu.mem_read((0xA000271C + 4 * player) & 0x1FFFFFFF, 4))[0]
    print("ran %.1f s; player %d score in RAM: %d" % (pic.millis / 1000, player, score))
    print("videos after the first hit:", " ".join("%s@%.2f" % (n, ms / 1000)
          for ms, n, _ in link.av.played if ms >= hits[0]) if link.av else "-")
    if saved:
        print("frames:", " ".join(saved))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("prg"); b.add_argument("out")
    b.add_argument("--points", type=int, default=1_000_000)
    b.add_argument("--video", default="EB0"); b.add_argument("--sound", default="EB0")
    p = sub.add_parser("prove")
    p.add_argument("prg"); p.add_argument("--card"); p.add_argument("--nvram")
    p.add_argument("--frames"); p.add_argument("--at", default="27,29")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        out = build(open(a.prg, "rb").read(), points=a.points, video=a.video, sound=a.sound)
        open(a.out, "wb").write(out)
        print("wrote %s (%d bytes, trampoline at %x)" % (a.out, len(out), TITLES["JET_V004"]["tramp"]))
    else:
        prove(a.prg, a.card, a.nvram, a.frames, [float(s) for s in a.at.split(",")])


if __name__ == "__main__":
    sys.exit(main())
