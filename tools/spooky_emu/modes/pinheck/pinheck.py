"""The pinHeck mode build: a stock ``<GAME>_Vnnn.PRG`` with the runtime and the modes in its
free flash (PAD-1422; hooks.py, padheck.c, docs/plans/spooky_modes.md).

  prebuilt/padheck_<STEM>.bin   the runtime linked for that build (build.sh), starting with
                                its header: magic "PADH", version, entry, data, run (5 words)
  data                          struct pad_data (padheck.c) right after the runtime: the modes
                                as the runtime reads them, packed here from the .mode files
  the one patch                 the jal at the hook table's tick_site now calls the entry

The PRG has no header or checksum; the machine flashes the card's PRG into the PIC (Service ->
UPDATE CODE), and the stock PRG on the card takes the modes out again the same way.
"""
import importlib.util
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location("pad_pinheck_" + name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


H = _load("hooks")
PREBUILT = os.path.join(HERE, "prebuilt")
MAX_MODES = 24
TITLE_MAX = 16
NAME_MAX = 12
DATA_MAGIC = 0x314D4850         # "PHM1"
HEAD_MAGIC = 0x48444150         # "PADH"
PANELS = {"none": 0, "middle": 1, "bottom": 2, "top": 3}
SOUND_KEYS = ("sound_start", "sound_shot", "sound_complete", "sound_end")
MODE_SIZE = 64


class Refused(Exception):
    pass


def runtime_path(stem):
    return os.path.join(PREBUILT, "padheck_%s.bin" % stem)


def runtime(stem):
    """(bytes, head dict) of the prebuilt runtime for a build, or Refused."""
    p = runtime_path(stem)
    if not os.path.isfile(p):
        raise Refused("no mode runtime built for %s (%s)" % (stem, p))
    with open(p, "rb") as f:
        b = f.read()
    magic, ver, entry, data, run = struct.unpack_from("<5I", b)
    t = H.HOOKS[stem]
    if magic != HEAD_MAGIC or entry < t["free_flash"] or data != t["free_flash"] + _align(len(b)):
        raise Refused("%s is not a padheck runtime for %s" % (p, stem))
    return b, dict(version=ver, entry=entry, data=data, run=run)


def _align(n, a=256):
    return (n + a - 1) // a * a


def screen_text(s):
    """What the DMD's text layer can show of ``s``: upper case, ASCII 32..95."""
    return "".join(c if 32 <= ord(c) <= 95 else "?" for c in (s or "").upper())


def title_max(stem):
    """How many characters of a mode's title the build's DMD panel shows (Jetsons 16; AMH's
    text lines on Domino's and Rob Zombie, 13)."""
    t = H.HOOKS.get(stem) or {}
    return min(TITLE_MAX, t.get("text_columns") or TITLE_MAX)


def title_problem(s, stem=None):
    t = (s or "").upper()
    limit = title_max(stem) if stem else TITLE_MAX
    if len(t) > limit:
        return "is %d characters: the DMD panel shows %d" % (len(t), limit)
    bad = sorted({c for c in t if not 32 <= ord(c) <= 95})
    if bad:
        return "has %s, which the DMD's text cannot show (letters, digits and !\"#$%%&'()*+,-./:;<=>?@[]^_)" % " ".join(bad)
    return None


def _bits(words, port, what, fn):
    ids = (port or {}).get("switch_ids") or {}
    out = bytearray(8)
    for w in words:
        n = ids.get(w)
        if n is None:
            for k, label in ((port or {}).get("switch_labels") or {}).items():
                if label.lower() == w.lower():
                    n = ids.get(k)
        if n is None or not 0 <= n < 64:
            raise Refused("%s: %s %s is not one of the game's switches" % (fn, what, w))
        out[n >> 3] |= 1 << (n & 7)
    return bytes(out)


def _int(v, default=0):
    v = (v or "").replace(",", "").replace("_", "").strip()
    return int(v) if v else default


def pack_mode(m, port):
    """One struct pad_mode (64 bytes) from a checked mode dict."""
    fn = m.get("file", "?")
    title = screen_text(m.get("title") or m.get("name") or fn[:-5])[:title_max((port or {}).get("prg") or "")]
    start = _bits((m.get("start") or "").replace(",", " ").split(), port, "start", fn)
    shots = _bits((m.get("shots") or "").replace(",", " ").split(), port, "shots", fn)
    sounds = b""
    for k in SOUND_KEYS:
        s = (m.get(k) or "").strip().upper()
        if s and (len(s) != 3 or not s.isalnum()):
            raise Refused("%s: %s %s is not a sound of this game (three letters/digits, SFX/_F?/xxx.wav)" % (fn, k, s))
        sounds += s.encode("ascii").ljust(4, b"\0")
    panel = PANELS.get((m.get("panel") or "middle").strip(), 1)
    body = struct.pack("<16s8s8sHHHBBII", title.encode("ascii"), start, shots,
                       min(_int(m.get("start_count"), 1), 0xFFFF), min(_int(m.get("seconds")), 0xFFFF),
                       min(_int(m.get("complete")), 0xFFFF), panel, 0,
                       _int(m.get("points")), _int(m.get("complete_points"))) + sounds
    assert len(body) == MODE_SIZE, len(body)
    return body


def pack_data(modes, port, off=False):
    """struct pad_data: magic, count, off, the names, the modes (padheck.c)."""
    if len(modes) > MAX_MODES:
        raise Refused("%d modes: the runtime takes %d" % (len(modes), MAX_MODES))
    names = b"".join(os.path.splitext(m.get("file", "mode"))[0].encode("ascii", "replace")[:NAME_MAX - 1].ljust(NAME_MAX, b"\0")
                     for m in modes)
    names = names.ljust(MAX_MODES * NAME_MAX, b"\0")
    body = b"".join(pack_mode(m, port) for m in modes).ljust(MAX_MODES * MODE_SIZE, b"\0")
    return struct.pack("<IBBBB", DATA_MAGIC, len(modes), 1 if off else 0, 0, 0) + names + body


def build_prg(stock, modes, port, off=False):
    """The stock PRG with the runtime, the modes and the tick patch: bytes, or Refused."""
    stem = port.get("prg") or ""
    try:
        t = H.check(stock, stem)
    except H.Refused as e:
        raise Refused(str(e))
    rt, head = runtime(stem)
    data = pack_data(modes, port, off)
    base = t["free_flash"] - H.FLASH
    end = head["data"] - H.FLASH + len(data)
    if base < len(stock) or end > H.FLASH_SIZE:
        raise Refused("the runtime does not fit in %s's free flash" % stem)
    out = bytearray(stock) + b"\xFF" * (base - len(stock))
    out += rt + b"\xFF" * (head["data"] - t["free_flash"] - len(rt)) + data
    if H.word(stock, t["tick_site"]) != H.jal(t["tick_target"]):
        raise Refused("%s: the tick site %08X is not jal %08X" % (stem, t["tick_site"], t["tick_target"]))
    struct.pack_into("<I", out, t["tick_site"] - H.FLASH, H.jal(head["entry"]))
    return bytes(out)


def is_modes_build(prg):
    """True for a PRG this module wrote (the tick site calls a padheck entry)."""
    for stem, t in H.HOOKS.items():
        off = t["free_flash"] - H.FLASH
        if len(prg) > off + 20 and struct.unpack_from("<I", prg, off)[0] == HEAD_MAGIC:
            return True
    return False


def stock_of(prg):
    """The stock PRG a modes build was made from (the runtime cut off, the tick site put back),
    so a rebuilt modes update starts from stock again; a stock PRG comes back as it is."""
    for stem, t in H.HOOKS.items():
        off = t["free_flash"] - H.FLASH
        if len(prg) > off + 20 and struct.unpack_from("<I", prg, off)[0] == HEAD_MAGIC:
            s = bytearray(prg[:t["size"]])
            struct.pack_into("<I", s, t["tick_site"] - H.FLASH, H.jal(t["tick_target"]))
            return bytes(s)
    return prg


#: switches the emulator and the game's own ball handling name (tools/pinheck_emu/games.py);
#: the games' switch tests show numbers only, so the rest are switch_<n>
KNOWN_SWITCHES = {"JET_V004": {32: ("shooter_lane", "SHOOTER LANE"), 34: ("trough_2", "TROUGH 2"),
                               35: ("trough_1", "TROUGH 1")},
                  "DOM_V006": {0: ("shooter_lane", "SHOOTER LANE"), 1: ("trough_1", "TROUGH 1"),
                               2: ("trough_2", "TROUGH 2"), 3: ("trough_3", "TROUGH 3")},
                  # Rob Zombie wants all of 1..7 closed for "no missing balls"; which of them
                  # are the trough and which hold balls elsewhere is not known
                  "RZO_V026": dict([(0, ("shooter_lane", "SHOOTER LANE"))] +
                                   [(n, ("ball_%d" % n, "BALL SWITCH %d" % n)) for n in range(1, 8)])}


def card_sounds(card):
    """The sounds on a pinHeck card: every SFX/_F?/xxx.wav, by its three-letter name."""
    out = []
    sfx = next((os.path.join(card, d) for d in os.listdir(card) if d.upper() == "SFX"), None)
    for d in sorted(os.listdir(sfx)) if sfx else ():
        p = os.path.join(sfx, d)
        if os.path.isdir(p) and len(d) == 3 and d.upper().startswith("_F"):
            for f in sorted(os.listdir(p)):
                stem, ext = os.path.splitext(f)
                if ext.lower() == ".wav" and len(stem) == 3 and stem[0].upper() == d[2].upper():
                    out.append(stem.upper())
    return out


def make_port(stem, card, game, version, defaults=None):
    """A pinHeck title's port report: its switches (numbers), its card's sounds, the hooks."""
    t = H.HOOKS[stem]
    known = KNOWN_SWITCHES.get(stem, {})
    syms = [known.get(n, ("switch_%d" % n,))[0] for n in range(64)]
    labels = {s: known.get(n, (None, "SWITCH %d" % n))[1] for n, s in enumerate(syms)}
    return dict(
        title=t["title"], game=game, version=version, update_ext=".zip", engine="pinheck", prg=stem,
        made_by="the game's code read and proven in tools/pinheck_emu (PAD-1422, PAD-1423): hooks.py; "
                "sounds from the card's SFX folders",
        runtime="1", points_scale=1, points_round=t.get("points_round", 0),
        points_note=("AddScore adds the points to the player's score rounded down to a multiple of "
                     "%d (no multiplier); the runtime calls it as the game's own switch handlers do"
                     % t["points_round"]) if t.get("points_round") else
                    "AddScore adds the points to the player's score as they are (no multiplier, no "
                    "rounding); the runtime calls it as the game's own switch handlers do",
        switches=syms, switch_ids={s: n for n, s in enumerate(syms)}, switch_labels=labels,
        lamps=[], sounds=card_sounds(card), voice_lines=0, game_modes=[], fonts=[],
        dmd=list(t["dmd"]), defaults=defaults or {},
        keys_not_here=["font_title", "font_value", "font_timer", "title_color", "value_color",
                       "timer_color", "panel_color"],
    )
