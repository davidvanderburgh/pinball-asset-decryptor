"""The game's own modes a mode of ours may keep from starting (PAD-363), read from the game program.

A rule of the game's starts one of its modes by calling the mode's START: a virtual of the mode object at
the title's start slot (Godzilla 8, Deadpool 13; the vptr is the vtable + 8). The app's stock scanner
(:mod:`.stock_scan_cpp`) already finds the slot, every mode's id, class, readable name, static object and
vtable. From that, each mode gets one veto site in the title's port:

    site block_start_<id>   <the mode's start>  <its two entry words>
    data block_obj_<id>     <the mode's object>
    text block_name_<id>    <its name>

The runtime hooks each named start and refuses it, while a mode of ours that asked runs, for the objects
that mode listed (`pm_block_list`, a mode file's `block_modes`) or the port's checked defaults (`value
block_default`). A MULTIBALL is never written: balls sit in a lock or on a magnet while it starts (PAD-353),
so a refused one could strand them. Ids from 128 up are left out (the runtime's masks are 128 bits), and so is a
start whose first two words cannot be moved into the veto's trampoline (:func:`movable`).
"""

from dataclasses import dataclass

#: the game's mode ids the runtime can hold off (pad_mode_runtime.c BLOCK_IDS)
MAX_ID = 128


def movable(words):
    """The veto moves a start's first two words into its trampoline and runs them there: neither may read or
    write the pc (a branch, a literal load, an add from pc, a pop into pc), and the first may not end the
    function (the second would be the next function's)."""
    if len(words) != 2 or any(w is None for w in words):
        return False
    for i, w in enumerate(words):
        cond, cls = w >> 28, (w >> 25) & 7
        if i == 1 and w & 0xFF000000 == 0xEB000000 and words[0] & 0xFFFF4000 == 0xE92D4000:
            continue                                      # `push {.., lr}; bl check`: the runtime calls it (hook_veto_bl)
        if cond == 0xF or cls == 5:                       # unconditional space; b / bl
            return False
        if w & 0x0FFFFFF0 == 0x012FFF10 or w & 0x0FFFFFF0 == 0x012FFF30:   # bx / blx register
            if i == 0 or w & 0x20:
                return False
            continue                                      # a bx lr as the second word: a two-word function
        if w & 0x0FFF0000 == 0x03200000:                  # nop and the other hints
            continue
        if cls in (0, 1, 2, 3):                           # data processing, load / store
            rn, rd = (w >> 16) & 0xF, (w >> 12) & 0xF
            if w & 0x0FB00000 == 0x03000000:              # movw / movt: bits 16-19 are the immediate's
                rn = 0
            if rn == 15 or rd == 15:
                return False
            if cls == 0 and (w & 0xF) == 15:
                return False
        if cls == 4 and ((w >> 16) & 0xF == 15 or (w & 0x00108000) == 0x00108000):   # ldm into pc / from pc
            return False
    return True


@dataclass
class GameMode:
    id: int
    cls: str
    name: str
    obj: int
    vtable: int
    start: int
    words: tuple
    multiball: bool

    @property
    def blockable(self):
        return not self.multiball and 0 <= self.id < MAX_ID and bool(self.start) and movable(self.words)


def read_modes(elf):
    """[:class:`GameMode`] of a C++ rule title's program (bytes), in id order. Raises
    :class:`.stock_scan.ScanError` when the program has no C++ mode manager."""
    from . import stock_scan as S
    from . import stock_scan_cpp as C
    prog = S.Program(elf)
    model = S.class_model(prog)
    if not C.family(model):
        raise S.ScanError("no C++ rule manager in this game program")
    reading = C.read(prog, model)
    slot = reading.engine.get("start_slot")
    if slot is None:
        raise S.ScanError("the scanner found no start slot in this game program")
    out = []
    for m in sorted(reading.modes, key=lambda m: m.id):
        start = _word(prog, m.vtable + 8 + 4 * int(slot)) if m.vtable else None
        words = (_word(prog, start), _word(prog, start + 4)) if start else (None, None)
        out.append(GameMode(m.id, m.cls, m.name, m.obj or 0, m.vtable or 0, start or 0, words,
                            bool(S.derives(model, m.cls, "cmode_mball"))))
    # a mode outside the game's own table gets the scanner's stand-in id (1000 up: Deadpool's Battle
    # Juggernaut, Jaws's Jaws and Encounter); in the port an id is only a label, so it takes the highest
    # one free, in the stand-ins' order (the same on every run of the same program)
    used = {m.id for m in out if 0 <= m.id < MAX_ID}
    free = [i for i in range(MAX_ID - 1, -1, -1) if i not in used]
    for m in sorted((m for m in out if m.id >= MAX_ID), key=lambda m: m.id):
        if free:
            m.id = free.pop(0)
    return sorted(out, key=lambda m: m.id)


def _word(prog, va):
    try:
        return prog.word(va)
    except Exception:                                    # noqa: BLE001 - outside the program's loads
        return None


def port_lines(modes, defaults=(), header=None):
    """The port's block section (lines) for *modes*; *defaults* = the ids a mode blocks when it lists none
    (only modes checked on that title), as `text block_default <ids>`."""
    out = ["# PAD-363: the game's own modes a mode of ours may keep from starting (game_mode_blocks.py, from the",
           "# game program: each mode's start = its vtable + 8 + 4 * the title's start slot). Never a multiball."]
    if header:
        out += ["# " + h for h in header]
    on = []
    for m in modes:
        if not m.blockable:
            continue
        out.append("site block_start_%-6d 0x%08x 0x%08x 0x%08x" % (m.id, m.start, m.words[0], m.words[1]))
        if m.obj:
            out.append("data block_obj_%-8d 0x%08x" % (m.id, m.obj))
        out.append("text block_name_%-7d %s" % (m.id, m.name))
        if m.id in defaults:
            on.append(m.id)
    if on:
        out.append("text block_default          %s" % " ".join(str(i) for i in on))
    return out


# ---- PAD-398: the game's RULES, which see no shots while a mode of ours runs -----------------------------------
#: David, 2026-10-05: "when our custom modes start, we should ONLY be in those modes unless explicitly noted."
#: A C++ rule title's rules (Godzilla's Destruction Jackpot, building locks, bridge, cities...) are singletons of
#: one rule base (`Rule`; `crule` on Venom, Mandalorian, D&D, John Wick...); each reads a shot in one virtual of
#: that base, the shot mask in r2:r3, which the runtime hooks and clears while a mode of ours blocks, unless the
#: mode keeps that rule counting (pm_block_rules_keep). The virtual's slot is the title's own (PAD-400: Godzilla
#: 25, Avengers 28, Deadpool 31 / 32, Jaws and King Kong 27...): :func:`shot_slot` reads it from the program.
#: the battle rule is the port's `site block_battle_shots` already (two hooks on one entry are not possible)
RULE_SKIP = ("RuleBattle",)
#: written first, at number 0, where PAD-363 put it
RULE_FIRST = ("RuleSaucerAttack",)
#: the most the runtime hooks (pad_mode_runtime.c BLOCK_RULES)
MAX_RULES = 32
#: `mov r0, #0; bx lr`: a handler that reads nothing
_NO_OP = (0xE3A00000, 0xE12FFF1E)
_BX_LR = 0xE12FFF1E
#: how far into a function :func:`reads_mask` looks
_MASK_WORDS = 24


@dataclass
class GameRule:
    cls: str            # RuleDestructionJackpot
    name: str           # Destruction Jackpot: what the port and the Modes tab call it
    v25: int            # its shot handler (Godzilla's v[25]; the title's own slot elsewhere)
    words: tuple        # the handler's first two words
    slot: int = 25      # the virtual it is


def rule_name(cls, whole=False):
    """A rule class's readable name: RuleKingOfTheMonsters -> King of the Monsters, AtticAttackMultiballRule ->
    Attic Attack Multiball, GargoylesGoneWild_Rule -> Gargoyles Gone Wild, cdragon_rule -> Dragon,
    ctinys_dice_game_rule -> Tinys Dice Game, rule_drop_targets -> Drop Targets. *whole* keeps a trailing
    "Rule" (chost_combo_rule -> Host Combo Rule, beside chost_combo's Host Combo)."""
    import re
    n = cls
    if re.match(r"c[a-z0-9]+(_[A-Za-z0-9]+)*$", n):       # the crule family: c<words>_rule
        n = n[1:]
    n = re.sub(r"^(Rule_?|rule_)(?=[A-Za-z0-9])", "", n)
    if not whole:
        n = re.sub(r"(?<=[A-Za-z0-9])_?(Rule|rule)$", "", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Z])(?=[A-Z][a-z])", " ", n.replace("_", " "))
    out = []
    for i, w in enumerate(n.split()):
        if i and w.lower() in ("of", "the", "and", "a", "in", "on", "to"):
            out.append(w.lower())
        elif w.islower():
            out.append(w[0].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out) or cls


def hookable(words):
    """The runtime's plain hook (pad_mode_runtime.c hook) moves a handler's first two words into its trampoline
    and runs them there, relocating a literal load: neither may otherwise read or write the pc (a branch, a
    bl, an add from pc, a pop into pc), and the first may not end the function."""
    if len(words) != 2 or any(w is None for w in words):
        return False
    if words[0] & 0x0FFFFFF0 == 0x012FFF10:                # bx as the first word
        return False
    if words[1] & 0xFF000000 == 0xEB000000:              # a bl is copied as it is, so it would land wrong
        return False
    lit = [w & 0xFF7F0000 == 0xE51F0000 and (w >> 12) & 0xF != 15 for w in words]
    return movable(tuple(0xE320F000 if lit[i] else w for i, w in enumerate(words)))


def reads_mask(prog, fn):
    """Does the function at *fn* read both r2 and r3 before writing either (a 64-bit argument: the shot mask)?
    Straight-line, from its entry to its first call, branch or return."""
    from . import stock_scan as S
    seen, wrote = set(), set()
    va = fn
    for _ in range(_MASK_WORDS):
        w = _word(prog, va)
        regs = S._regs_at(prog, va) if w is not None else None
        if regs is None:
            return False
        r, wr = regs
        seen |= {x for x in (2, 3) if x in r and x not in wrote}
        if seen == {2, 3}:
            return True
        wrote |= set(wr)
        if wrote >= {2, 3} or w & 0x0E000000 == 0x0A000000 or w & 0x0FFFFFF0 in (0x012FFF10, 0x012FFF30):
            return False
        va += 4
    return False


def rule_family(model):
    """(root, [classes]): the program's rule base - the rule-named class most rule-named classes derive from
    (`Rule`, `crule`; never a per-player `...RuleState`) - and every class with a vtable that derives from it,
    less its managers, its null twin and the game's MODES (on the crule titles a `cmode` is a crule too; a mode's
    start is refused already, `block_start_<id>`)."""
    from collections import Counter
    from . import stock_scan as S

    def ruleish(c):
        return "rule" in c.lower() and not c.startswith("Singleton<") and not c.lower().endswith("state")
    roots = Counter()
    for c in model:
        if ruleish(c):
            tops = [b for b in S.chain_of(model, c) if ruleish(b)]
            if tops:
                roots[tops[-1]] += 1
    if not roots:
        return None, []
    root = roots.most_common(1)[0][0]
    out = [c for c in sorted(model) if c != root and model[c].get("vtable") and S.derives(model, c, root)
           and not c.lower().endswith(("manager", "_null"))
           and not any(b == "cmode" for b in [c] + S.chain_of(model, c))]
    return root, out


def shot_slot(prog, model, root, classes):
    """The rule base's shot handler: the virtual of the base the most rule classes override with a function that
    reads the shot mask (:func:`reads_mask`). None unless three or more do, a fifth of the rules, and more than
    for any other slot. (A title whose base has none - Iron Maiden, Jurassic Park, Elvira: their rules hear
    shots as switch hooks - has a slot only a sub-family adds, past the base's own; that is not it.)"""
    from collections import Counter
    from . import stock_scan as S
    bound = (model.get(root) or {}).get("nvirt") or 0
    votes = Counter()
    for c in classes:
        for k, f in S.own_slots(prog, model, c)[1]:
            if k < bound and reads_mask(prog, f):
                votes[k] += 1
    best = votes.most_common(2)
    if not best or best[0][1] < max(3, len(classes) // 5) or (len(best) > 1 and best[1][1] >= best[0][1]):
        return None                                      # TMNT: 2 of 23, chance
    return best[0][0]


def read_rules(elf):
    """[:class:`GameRule`] of a C++ rule title's program (bytes): every rule class whose shot handler (the
    title's :func:`shot_slot`) is its own, the battle rule left out, Saucer Attack first, then by class name; a
    handler rules share is listed once, named for the class that defines it. [] when it has none."""
    from . import stock_scan as S
    prog = S.Program(elf)
    model = S.class_model(prog)
    root, classes = rule_family(model)
    slot = shot_slot(prog, model, root, classes) if classes else None
    if slot is None:
        return []
    base = model.get(root, {}).get("vtable")
    base_fn = _word(prog, base + 8 + 4 * slot) if base else None
    singles = {c[len("Singleton<"):-1] for c in model if c.startswith("Singleton<")}
    out, seen, names = [], set(), set()
    for cls in sorted(classes, key=lambda c: (c not in singles, c)):
        if cls in RULE_SKIP:
            continue
        fn = _word(prog, model[cls]["vtable"] + 8 + 4 * slot)
        if not fn or fn == base_fn or fn in seen or not prog.in_text(fn):
            continue
        words = (_word(prog, fn), _word(prog, fn + 4))
        if words[0] == _BX_LR or words == _NO_OP or not hookable(words):
            continue
        seen.add(fn)
        # a handler rules inherit is the class's that defines it (Deadpool's four team-ups: RuleTeamUpShot)
        # (an abstract one - no vtable - when every rule under it shares the handler)
        for b in S.chain_of(model, cls):
            if b == root:
                break
            if (model.get(b) or {}).get("vtable"):
                if _word(prog, model[b]["vtable"] + 8 + 4 * slot) != fn:
                    break
            elif any(_word(prog, model[c]["vtable"] + 8 + 4 * slot) != fn
                     for c in classes if c != b and S.derives(model, c, b)):
                break
            cls = b
        name = rule_name(cls)
        if name.lower() in names:                          # Venom's chost_combo and chost_combo_rule
            name = rule_name(cls, whole=True)
        n = 2
        while name.lower() in names:
            name, n = "%s %d" % (rule_name(cls), n), n + 1
        names.add(name.lower())
        out.append(GameRule(cls, name, fn, words, slot))
    out.sort(key=lambda r: (r.cls not in RULE_FIRST, r.cls))
    return out[:MAX_RULES]


def rule_lines(rules):
    """The port's rule lines for *rules*: `site block_rule_<n>` and `text block_rule_name_<n>` (no lo/hi mask
    lines: every bit is hidden)."""
    if not rules:
        return []
    out = ["# PAD-398: every rule of the game's that reads shots (game_mode_blocks.read_rules, from the game",
           "# program): while a mode of ours runs, each sees none of its shots unless the mode keeps it (no",
           "# block_rule_lo/hi lines: every bit); the battle rule is block_battle_shots. `text block_rule_name_<n>`",
           "# is what the Modes tab lists."]
    for n, r in enumerate(rules):
        out.append("site block_rule_%-10d 0x%08x 0x%08x 0x%08x  # %s::v[%d]"
                   % (n, r.v25, r.words[0], r.words[1], r.cls, r.slot))
        out.append("text block_rule_name_%-5d %s" % (n, r.name))
    return out
