"""Port lines for a Spike 2 build's named Player Challenge picks, read from the game's own code (PAD-615;
MODE_SDK.md "A mode in the game's Challenge list"; tools/spike2_emu/modes/sdk/challenge_lines.py is the command line).

Stern's framework has a Player Challenge game on every Spike 2 title: the player picks it as the game starts and it
is a one-ball game (the game ends at the first ball's end). Some builds name the challenges a player can pick, one
game flag each, set as the game starts from the pick: James Bond LE and Pro 1.06 (FG_CHAOS_AT_CRAB_KEY_CHALLENGE ...
FG_HER_MAJESTYS_SECRET_SERVICE_CHALLENGE) and Stranger Things 1.13 / LE 1.12 / LE 1.13 (FG_DEMOGORGON_CHALLENGE ...
FG_FINAL_SHOWDOWN_CHALLENGE). Every challenge's module there has one handler on the ball's start event, of the same
shape:

    push {r3, lr}
    bl   <challenge game?>        mov r0, #<FG_PLAYER_CHALLENGE_MODE_ACTIVE>; b <flag get>
    cmp r0, #0 ; bne +8 ; mov r0, #1 ; pop {r3, pc}
    mov r0, #<its flag> ; bl <flag get> ; cmp r0, #0 ; beq (the return above)
    ... bl <its start>  (Ahoy Mr. Bond with 1: as a challenge)
    mov r0, #1 ; pop {r3, pc}

Those handlers are the sites a mode of ours takes a challenge's place at (`site challenge_go_<n>`, refused with 1
when a mode holds it, so the game's own never starts). The lines, in flag order (the order of the game's menu):

  site  challenge_go_<n>    the handler
  value challenge_flag_<n>  its flag
  text  challenge_name_<n>  its name, from the flag's ("Chaos at Crab Key")
  value challenge_on_flag   FG_PLAYER_CHALLENGE_MODE_ACTIVE

Other titles' challenges are other things (Godzilla's King of the Monsters, Venom's Knull levels, Rush's 2112, a
timed whole game on Bond 60th): no FG_<name>_CHALLENGE flag with a handler of this shape, so no lines.
Read-only (bytes in, lines out).
"""
import re
import struct

PUSH_R3_LR = 0xE92D4008
#: the flag names that name ONE challenge (not FG_..._CHALLENGE_ACTIVE, _COMPLETED...)
CHALLENGE_FLAG = re.compile(r"^FG_([A-Z0-9_]+?)_CHALLENGE$")
#: words the names keep as written
SMALL = {"AT", "THE", "ON", "OF", "AND", "A", "IN", "TO"}
NAME_FIX = {"MR": "Mr.", "HER MAJESTYS": "Her Majesty's", "GOLDFINGERS": "Goldfinger's"}


class Elf:
    def __init__(self, data):
        self.d = data if isinstance(data, (bytes, bytearray)) else open(data, "rb").read()
        d = self.d
        phoff, = struct.unpack_from("<I", d, 0x1c)
        phentsize, phnum = struct.unpack_from("<HH", d, 0x2a)
        self.segs = []
        for i in range(phnum):
            t, off, va, _pa, fsz, _msz, fl, _al = struct.unpack_from("<8I", d, phoff + i * phentsize)
            if t == 1:
                self.segs.append((off, va, fsz, fl))
        o, v, n = next((o, v, n) for o, v, n, f in self.segs if f & 1)
        self.text_va = v
        self.words = struct.unpack_from("<%dI" % (n // 4), d, o)

    def off(self, va):
        for o, v, n, _f in self.segs:
            if v <= va < v + n:
                return o + va - v
        return None

    def va(self, off):
        for o, v, n, _f in self.segs:
            if o <= off < o + n:
                return v + off - o
        return None

    def word(self, va):
        return struct.unpack_from("<I", self.d, self.off(va))[0]

    def cstr(self, va):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + 200)
        s = self.d[o:e] if e >= 0 else b""
        return s.decode() if s and all(32 <= c < 127 for c in s) else None


def flag_names(e):
    """The game's flag names, by id (the FG_ table: FG_INVALID at 0), or []."""
    m = re.search(rb"(?<=\0)FG_INVALID\0", e.d)
    if not m:
        return []
    want = struct.pack("<I", e.va(m.start()))
    i = 0
    while True:
        i = e.d.find(want, i)
        if i < 0:
            return []
        if i % 4 == 0:
            names, at = [], e.va(i)
            while True:
                s = e.cstr(e.word(at + 4 * len(names))) if e.off(at + 4 * len(names)) is not None else None
                if not s or not s.startswith("FG_"):
                    break
                names.append(s)
            if len(names) > 8:
                return names
        i += 1


def mov_r0(imm):
    """The words `mov r0, #imm` assembles to (the plain form for 0-255, else movw)."""
    out = {0xE3A00000 | imm} if imm < 256 else set()
    if imm < 0x10000:
        out.add(0xE3000000 | (imm >> 12) << 16 | imm & 0xFFF)
    return out


def bl_target(va, w):
    if w & 0xFF000000 != 0xEB000000:
        return None
    return (va + 8 + (((w & 0xFFFFFF) << 8 & 0xFFFFFFFF) - ((w & 0x800000) << 9) >> 6)) & 0xFFFFFFFF


def pretty(stem):
    words = stem.replace("_", " ")
    for k, v in NAME_FIX.items():
        words = re.sub(r"\b%s\b" % k, v.upper(), words)
    out = []
    for i, w in enumerate(words.split()):
        fixed = next((v for v in NAME_FIX.values() if v.upper() == w), None)
        out.append(fixed or (w.lower() if i and w in SMALL else w.capitalize()))
    return " ".join(out)


def find(elf):
    """(lines, notes): the port lines of `elf` (the game program's bytes or its path), and what was not found."""
    e = Elf(elf)
    names = flag_names(e)
    if not names:
        return [], ["no FG_ flag name table"]
    try:
        on_flag = names.index("FG_PLAYER_CHALLENGE_MODE_ACTIVE")
    except ValueError:
        return [], ["no FG_PLAYER_CHALLENGE_MODE_ACTIVE flag"]
    picks = [(i, CHALLENGE_FLAG.match(n).group(1)) for i, n in enumerate(names) if CHALLENGE_FLAG.match(n)]
    if not picks:
        return [], ["the build names no challenge (no FG_<name>_CHALLENGE flag)"]
    w, base = e.words, e.text_va
    # the "a challenge game?" predicates: mov r0, #on_flag ; b <flag get>
    on = mov_r0(on_flag)
    preds = {base + 4 * k for k in range(len(w) - 1) if w[k] in on and w[k + 1] & 0xFF000000 == 0xEA000000}
    found = {}
    n = len(w)
    for k in range(n - 1):
        if w[k] != PUSH_R3_LR or bl_target(base + 4 * k + 4, w[k + 1]) not in preds:
            continue
        for j in range(k + 2, min(k + 10, n - 1)):
            hit = next((f for f, _s in picks if w[j] in mov_r0(f)), None)
            if hit is None or bl_target(base + 4 * j + 4, w[j + 1]) is None:
                continue
            start = next((bl_target(base + 4 * q, w[q]) for q in range(j + 2, min(j + 10, n))
                          if bl_target(base + 4 * q, w[q]) is not None), None)
            found.setdefault(hit, []).append((base + 4 * k, start))
            break
    lines, notes = ["value challenge_on_flag   %d" % on_flag], []
    for n, (f, stem) in enumerate(picks):
        at = found.get(f, [])
        if len(at) != 1:
            notes.append("%s (flag %d): %d handlers of the shape" % (names[f], f, len(at)))
            continue
        va, start = at[0]
        lines += ["# %s: its handler starts 0x%x" % (pretty(stem), start or 0),
                  "site  challenge_go_%d    0x%08x 0x%08x 0x%08x" % (n, va, e.word(va), e.word(va + 4)),
                  "value challenge_flag_%d  %d" % (n, f),
                  "text  challenge_name_%d  %s" % (n, pretty(stem))]
    if notes:
        return [], notes
    return lines + menu_lines(e), notes


def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


#: PAD-615 round 2: the game's own start menu (CHOOSE YOUR MODE OF PLAY, both flipper buttons held in attract), Bond
#: LE/Pro 1.06. One function builds the menu's list on its stack - 12-byte entries {kind, caption message id, name}
#: from sp+<list_at>, their count at sp+<count_at> - and, as the player selects, jumps on the entry's kind (3..7: the
#: five challenges). Its two hook points, each two plain words the runtime moves:
#:   after the list is built:  sub r0, r0, #1 ; cmp r0, #5 ; movwls r3, ... ; movhi r4, #0   (the Default Game Mode read)
#:   at the pick:              ldr r3, [r3, #-n] ; sub r3, r3, #1 ; cmp r3, #7 ; ldrls pc, [pc, r3, lsl #2]
MENU_AT = (0xE2400001, 0xE3500005)
PICK_AT = (0xE2433001, 0xE3530007, 0x979FF103)


def menu_lines(e):
    """The start menu's port lines (empty when the build has no such menu code): its two sites, where the list and
    its count are on the menu function's stack, how many entries fit before the next local, the first challenge's
    kind and the caption message the game gives a challenge entry."""
    w, base = e.words, e.text_va
    n = len(w)
    menu = [k for k in range(n - 4) if (w[k], w[k + 1]) == MENU_AT and (w[k + 2] & 0xFFF0F000) == 0x93003000
            and w[k + 3] == 0x83A04000]
    pick = [k for k in range(1, n - 3) if tuple(w[k:k + 3]) == PICK_AT and (w[k - 1] & 0xFFFFF000) == 0xE5133000]
    caption = [k for k in range(n - 2) if w[k] == 0xE3A0C003 and (w[k + 1] & 0xFFF0F000) == 0xE3002000
               and (w[k + 2] & 0xFFF0F000) == 0xE3000000]
    if len(menu) != 1 or len(pick) != 1 or len(caption) != 1:
        return []
    m, k = menu[0], pick[0]
    back = w[k - 1] & 0xFFF                                   # ldr r3, [r3, #-back]: the entry's kind
    top = next((rot_imm(w[q] & 0xFFF) for q in range(k - 2, k - 8, -1) if (w[q] & 0xFFFFF000) == 0xE28D2000), None)
    count = next((w[q] & 0xFFF for q in range(m + 4, m + 24) if (w[q] & 0xFFFFF000) == 0xE59D1000), None)
    after = [rot_imm(w[q] & 0xFFF) for q in range(k - 24, k) if (w[q] & 0xFFFFF000) == 0xE28D0000]
    if top is None or count is None:
        return []
    list_at = top - back
    ends = [a for a in after if a > list_at]
    if not ends:
        return []
    cap = (min(ends) - list_at) // 12
    cw = w[caption[0] + 1]
    menu_va, pick_va = base + 4 * m, base + 4 * k
    return ["# the start menu (CHOOSE YOUR MODE OF PLAY): our names on the challenges modes take, and challenges of "
            "their own",
            "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (menu_va, w[m], w[m + 1]),
            "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (pick_va, w[k], w[k + 1]),
            "value challenge_menu_list_at   %d" % list_at,
            "value challenge_menu_count_at  %d" % count,
            "value challenge_menu_cap       %d" % cap,
            "value challenge_menu_kind      3",
            "value challenge_menu_caption   %d" % ((cw >> 4 & 0xF000) | (cw & 0xFFF))]


def missing_from(lines, port_text):
    have = {tuple(l.split()[:2]): l for l in port_text.splitlines() if l.strip() and not l.startswith("#")}
    out = []
    for l in lines:
        if l.startswith("#"):
            continue
        key = tuple(l.split()[:2])
        if key not in have:
            out.append(l)
        elif have[key].split() != l.split():
            out.append("# DIFFERS in the port: " + l)
    return out

