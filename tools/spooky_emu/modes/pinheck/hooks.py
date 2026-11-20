"""The pinHeck games' hook tables: where the mode runtime meets each build (PAD-1422, PAD-1423;
docs/plans/spooky_modes.md).

A pinHeck game is compiled C on a PIC32MX795 (``<GAME>_Vnnn.PRG``: raw program flash from
0x9D000000).  There is no mode engine and no loader, so the runtime (``padheck.c``) is linked
into the free flash after the program, per build, and joins the game through ONE re-pointed
call: ``tick_site`` is the ``jal houseKeeping`` inside the function every one of the game's
loops (attract, play, bonus count, tilt, service) calls to wait for the next millisecond.  The
runtime's entry calls ``tick_target`` (the game's houseKeeping, unchanged) and then runs the
modes: once per millisecond, whatever the game is doing.  Everything else is read from or
called in the game as it is:

  switch_ram    8 row bytes the switch interrupt keeps: switch n is bit n & 7 of byte n >> 3,
                set while the switch is closed; the runtime sees a new closure as a bit going
                from 0 to 1 between two ticks
  game state    player / ball (0 between games), ball_active (0 from the drain to the next
                ball, through the bonus count), phase (1 serving, 2 shooter lane, 3 in play),
                tilt (set by the game's tilt routine), tilt_warnings, players (of the last game)
  add_score     AddScore(points): the game's own scoring (player score, its packet, replays)
  play_sfx      playSFX(this, channel, folder, clip0, [16] clip1, [20] priority): sound
                SFX/_F<folder>/<folder><clip0><clip1>.wav from the card
  text_str      text(this, 0, column, line, const char *, [20] colour): packet 0x12, 14
                characters a packet; column in 4-pixel steps, line 0..7 (8 pixels each)
  text_show     textLayer(this, 3, on): packet 13 03 xx shows or hides the text layer
  link_send     the link transfer: the 16-byte packet at data_out, command in a1
  coil_fire     fireCoil(this, coil, time): coil 0..23 as the game's SOLENOID TEST numbers them
  lamp_ram      64 brightness bytes the lamp interrupt multiplexes (lamp = column * 8 + row);
                the game's houseKeeping fills it every millisecond from its lamp tables, so a
                value written after houseKeeping (where the runtime runs) holds for that ms
  free_flash    where the runtime is linked (the first 64 KB boundary after the program)
  ram           the runtime's variables: RAM the game never writes (a whole game watched with
                a canary over 0xA0002F48..0xA001DF48)

Every address was read from the game's code and proven in tools/pinheck_emu (the plan's
"pinHeck" section says how).  ``sha1`` is the stock PRG's; ``sigs`` are the first 8 bytes of
each function and the tick site's word, checked again so a build that is not this one is
refused by name, never patched blind.
"""
import hashlib
import struct

FLASH = 0x9D000000
FLASH_SIZE = 0x80000            # PIC32MX795F512L

HOOKS = {
    "JET_V004": dict(
        title="Jetsons", size=0x2FF60, sha1="a70445cae2e013ac8c14dba7507657e6cf1583ca",
        gp=0xA0008200, this=0xA0000658,                 # gp - 0x7BA8: the link object
        tick_site=0x9D02EFC8, tick_target=0x9D018BB4,
        add_score=0x9D02BE84, play_sfx=0x9D02F684, video=0x9D02E58C,
        text_str=0x9D02A314, text_show=0x9D02FC3C, link_send=0x9D028BD8, data_out=0xA0002768,
        coil_fire=0x9D02CE5C, tilt_fn=0x9D01F8A4,
        switch_ram=0xA0000740, lamp_ram=0xA0002384, score_array=0xA000271C, millis=0xA000087C,
        player=0xA00006E6, ball=0xA0000720, ball_active=0xA0000690, phase=0xA00006C3,
        tilt=0xA000073C, tilt_warnings=0xA000073D, players=0xA00006EC,
        video_abi="jetsons", text_abi="jetsons",
        dmd=(128, 64), text_columns=32, text_lines=8,
        free_flash=0x9D030000, ram=(0xA0010000, 0x800),
        sigs={
            0x9D02EFC8: "ed62400f",                     # jal 0x9D018BB4
            0x9D018BB4: "ac84838fb4858297",
            0x9D02BE84: "e0828297e0ffbd27", 0x9D02F684: "00a0033c1000a993",
            0x9D02E58C: "2f8682932118a000", 0x9D02A314: "d0ffbd271400b1af",
            0x9D02FC3C: "00a0023c682745a0", 0x9D028BD8: "c0ffbd273800beaf",
            0x9D02CE5C: "e0ffbd27ff00a530", 0x9D01F8A4: "c0ffbd2758848427",
        }),
}

#: the names the runtime is linked against (padheck.c's GAME_* symbols), in the order build.sh
#: passes them; every entry must have them all
LINK_KEYS = ("gp", "this", "tick_target", "add_score", "play_sfx", "text_str", "text_show",
             "link_send", "data_out", "coil_fire", "switch_ram", "lamp_ram", "score_array",
             "millis", "player", "ball", "ball_active", "phase", "tilt", "free_flash")


class Refused(Exception):
    pass


def stem_of(name):
    """``JET_V004`` for ``.../Jetsons/JET_V004.PRG``."""
    return name.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()


def identify(prg):
    """The HOOKS key of a stock PRG (by its sha1), or None."""
    h = hashlib.sha1(prg).hexdigest()
    for stem, t in HOOKS.items():
        if t["sha1"] == h:
            return stem
    return None


def check(prg, stem):
    """Refused unless ``prg`` is the stock build ``stem`` its hook table was read from."""
    t = HOOKS.get(stem)
    if t is None:
        raise Refused("no mode runtime for %s: the builds PAD knows are %s" % (stem, ", ".join(sorted(HOOKS))))
    if len(prg) != t["size"] or hashlib.sha1(prg).hexdigest() != t["sha1"]:
        raise Refused("%s is not the stock %s PAD read its hooks from (%d bytes, sha1 %s); a modes "
                      "build starts from the stock file" % (stem, t["title"], len(prg), hashlib.sha1(prg).hexdigest()[:12]))
    for a, sig in t["sigs"].items():
        got = prg[a - FLASH:a - FLASH + len(sig) // 2].hex()
        if got != sig:
            raise Refused("%s: %08X holds %s, not %s - not the build its hooks were read from" % (stem, a, got, sig))
    return t


def jal(target):
    return 0x0C000000 | ((target >> 2) & 0x3FFFFFF)


def word(prg, a):
    return struct.unpack_from("<I", prg, a - FLASH)[0]
