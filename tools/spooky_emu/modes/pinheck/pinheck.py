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
NAME_MAX = 20
DATA_MAGIC = 0x334D4850         # "PHM3" (PAD-1508: 352-byte modes; PHM2 was 128, PHM1 64)
HEAD_MAGIC = 0x48444150         # "PADH"
PANELS = {"none": 0, "middle": 1, "bottom": 2, "top": 3}
SOUND_KEYS = ("sound_start", "sound_shot", "sound_complete", "sound_end")
MODE_SIZE = 352
#: start_on words -> padheck.c's EV_ bits (every one the runtime reads off the game, PAD-1469)
EVENTS = {"ball_start": 1, "first_ball": 2, "last_ball": 4, "valid_playfield": 8, "ball_saved": 16,
          "extra_ball": 32, "multiball_end": 64}
#: the JJP keys a pinHeck title cannot do: its panel is the game's own DMD text (no fonts, no
#: colours), it has no mode engine to watch (start_after), and its sounds are the card's own
#: (no file of a mode's own: sound, music, picture, video)
KEYS_NOT_HERE = ["font_title", "font_value", "font_timer", "title_color", "value_color", "timer_color",
                 "panel_color", "start_after", "sound_channel", "music", "picture", "picture_at", "video",
                 "video_at", "video_loop"]


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


def _words(v):
    return (v or "").replace(",", " ").split()


def _switch_list(words, port, what, fn):
    """Switch numbers in order (start_combo)."""
    bits = []
    for w in words:
        b = _bits([w], port, what, fn)
        bits.append(next(k * 8 + j for k in range(8) for j in range(8) if b[k] & (1 << j)))
    return bits


def _lamp_bits(words, fn):
    out = bytearray(8)
    for w in words:
        n = w.lower().rsplit("_", 1)[-1]
        if not w.lower().startswith("lamp_") or not n.isdigit() or not 0 <= int(n) < 64:
            raise Refused("%s: lamps %s is not one of the game's lamps (lamp_0..lamp_63, its lamp test's numbers)" % (fn, w))
        out[int(n) >> 3] |= 1 << (int(n) & 7)
    return bytes(out)


def coil_of(port, name, fn="?"):
    """(number, own pulse ms, may hold) of a coil by its name in the port report."""
    t = H.HOOKS.get((port or {}).get("prg") or "") or {}
    for k, v in (t.get("coils") or {}).items():
        if k.lower() == (name or "").replace(" ", "_").lower():
            return v
    raise Refused("%s: %s is not one of the coils a mode may use on this game" % (fn, name))


def _scale(port):
    return (H.HOOKS.get((port or {}).get("prg") or "") or {}).get("coil_scale", 1)


def _coil_pulse(v, port, fn):
    """(coil, fireCoil time) of '<coil> [ms]'; time 0 = the coil's own pulse."""
    w = _words(v)
    if not w:
        return 0xFF, 0
    c = coil_of(port, w[0], fn)
    if len(w) < 2:
        return c[0], 0
    sc = _scale(port)
    ms = min(_int(w[1]), c[1])
    return c[0], max(1, -(-ms // sc))


def lamp_level(rgb, port=None):
    """A lamp_color as the game's lamp brightness (0..lamp_max): its brightest channel."""
    mx = (H.HOOKS.get((port or {}).get("prg") or "") or {}).get("lamp_max", 8)
    h = (rgb or "ffffff").strip().lstrip("#")[:6] or "ffffff"
    v = max(int(h[k:k + 2], 16) for k in (0, 2, 4))
    return 0 if not v else max(1, round(v * mx / 255))


def pack_mode(m, port):
    """One struct pad_mode (352 bytes) from a checked mode dict."""
    fn = m.get("file", "?")
    title = screen_text(m.get("title") or m.get("name") or fn[:-5])[:title_max((port or {}).get("prg") or "")]
    start = _bits(_words(m.get("start")), port, "start", fn)
    shots = _bits(_words(m.get("shots") or m.get("start")), port, "shots", fn)
    sounds = b""
    for k in SOUND_KEYS:
        s = (m.get(k) or "").strip().upper()
        if s and (len(s) != 3 or not s.isalnum()):
            raise Refused("%s: %s %s is not a sound of this game (three letters/digits, SFX/_F?/xxx.wav)" % (fn, k, s))
        sounds += s.encode("ascii").ljust(4, b"\0")
    panel = PANELS.get((m.get("panel") or "middle").strip(), 1)
    flags = ((1 if (m.get("start_count_reset") or "game").strip() == "ball" else 0) |
             {"ball": 2, "game": 4}.get((m.get("start_once") or "no").strip(), 0))
    body = struct.pack("<16s8s8sHHHBBII", title.encode("ascii"), start, shots,
                       min(_int(m.get("start_count"), 1), 0xFFFF), min(_int(m.get("seconds")), 0xFFFF),
                       min(_int(m.get("complete")), 0xFFFF), panel, flags,
                       _int(m.get("points")), _int(m.get("complete_points"))) + sounds
    # PAD-1469: start rules, lamps, balls, coils
    ev = 0
    for w in _words(m.get("start_on")):
        if w not in EVENTS:
            raise Refused("%s: start_on %s is not an event this game's runtime sees" % (fn, w))
        ev |= EVENTS[w]
    combo = _switch_list(_words(m.get("start_combo")), port, "start_combo", fn)
    if len(combo) > 6:
        raise Refused("%s: start_combo takes up to 6 switches here" % fn)
    mb = _words(m.get("multiball"))
    ab = _words(m.get("add_ball"))
    times = 1
    if ab and ab[-1].isdigit():
        times = int(ab[-1])
        ab = ab[:-1]
    hold_on = (m.get("coil_hold_on") or "shots").strip()
    hold_mode = {"shots": 0, "start": 1}.get(hold_on, 2)
    coils = [_coil_pulse(m.get(k), port, fn) for k in ("coil_start", "coil_shot", "coil_complete")]
    hw = _words(m.get("coil_hold"))
    if hw:
        hc = coil_of(port, hw[0], fn)
        if not hc[2]:
            raise Refused("%s: coil_hold %s is a coil a mode may pulse, not hold" % (fn, hw[0]))
        hold = (hc[0], min(_int(hw[2]), 16) if len(hw) > 2 else 8, _int(hw[1]))
    else:
        hold = (0xFF, 0, 0)
    blink = _int(m.get("lamp_blink"), 4) if (m.get("lamp_blink") or "").strip() else 4
    body += _lamp_bits(_words(m.get("lamps")), fn)
    body += _bits(_words(m.get("multiball_on")), port, "multiball_on", fn)
    body += _bits(ab, port, "add_ball", fn)
    body += _bits(_words(hold_on) if hold_mode == 2 else [], port, "coil_hold_on", fn)
    body += struct.pack("<IBBBB", _int(m.get("start_score")), ev, lamp_level(m.get("lamp_color"), port),
                        min(blink, 10), len(combo))
    body += bytes(combo).ljust(6, b"\0")
    cs = _int(m.get("combo_seconds"), 5) if (m.get("combo_seconds") or "").strip() else 5   # 0: no limit (PAD-1508)
    body += struct.pack("<BB", min(cs, 255), int(mb[0]) if mb else 0)
    body += struct.pack("<BBBB", min(int(mb[1]), 120) if len(mb) > 1 else 10, min(times, 6),
                        min(_int(m.get("ball_save")), 120), hold_mode)
    body += bytes(c for c, _t in coils) + bytes(min(t, 255) for _c, t in coils)
    body += struct.pack("<BBH", hold[0], hold[1], min(hold[2], 5000)) + b"\0\0"
    body += spike2_rules(m, port, fn)
    assert len(body) == MODE_SIZE, len(body)
    return body


def _rule_lines(m, key):
    return [ln.strip() for ln in (m.get(key) or "").split("\n") if ln.strip()]


PATTERNS = {"": 0, "solid": 1, "blink": 2, "pulse": 3, "chase": 4}


def spike2_rules(m, port, fn):
    """PAD-1508: the 224 bytes after the PAD-1469 ones (struct pad_mode in padheck.c)."""
    sp = []
    for ln in _rule_lines(m, "shot_points")[:8]:
        w = ln.split()
        sp.append(_bits(w[:-1], port, "shot_points", fn) + struct.pack("<I", _int(w[-1])))
    also = []
    for ln in _rule_lines(m, "start_also")[:3]:
        w = ln.split()
        count = 1
        if len(w) > 1 and w[-1].isdigit():
            count, w = min(int(w[-1]), 99), w[:-1]
        also.append(_bits(w, port, "start_also", fn) + struct.pack("<B", max(1, count)) + b"\0\0\0")
    at = []
    for ln in _rule_lines(m, "sound_at")[:8]:
        secs, _sp, snd = ln.partition(" ")
        snd = snd.strip().upper()
        if len(snd) != 3 or not snd.isalnum():
            raise Refused("%s: sound_at %s is not a sound of this game (three letters/digits, SFX/_F?/xxx.wav)" % (fn, snd))
        at.append(struct.pack("<H", min(_int(secs), 0xFFFF)) + snd.encode("ascii").ljust(4, b"\0") + b"\0\0")
    pat = (m.get("lamp_pattern") or "").strip().lower()
    rules = (1 if (m.get("points_ladder") or "").strip() == "rising" else 0) | \
        (2 if (m.get("start_needs") or "").split()[-1:] == ["ball"] else 0)
    out = _bits(_words(m.get("end_shots")), port, "end_shots", fn)
    out += struct.pack("<BBBB", rules, min(_int(m.get("sound_shot_every")), 255), min(_int(m.get("start_max")), 255),
                       min(_int(m.get("cooldown")), 255))
    out += struct.pack("<BBBB", PATTERNS.get(pat, 0), m.get("_needs", 0), len(sp), len(also))
    out += struct.pack("<B", len(at)) + b"\0\0\0"
    out += b"".join(sp).ljust(8 * 12, b"\0") + b"".join(also).ljust(3 * 12, b"\0") + b"".join(at).ljust(8 * 8, b"\0")
    return out + b"\0" * 8


def title_head(port):
    """What the runtime knows of the title, before the modes: the lane, the coil time unit, the
    trough, each coil's pulse/hold permission and own pulse, the lamps' full brightness."""
    t = H.HOOKS.get((port or {}).get("prg") or "") or {}
    trough = bytearray(8)
    for n in t.get("trough") or ():
        trough[n >> 3] |= 1 << (n & 7)
    ok, own = bytearray(24), bytearray(24)
    sc = t.get("coil_scale", 1)
    for _name, (c, ms, hold) in (t.get("coils") or {}).items():
        ok[c] = 1 | (2 if hold else 0)
        own[c] = max(1, min(255, ms // sc))
    return struct.pack("<BB", t.get("lane", 0xFF) if t.get("lane") is not None else 0xFF, sc) + bytes(trough) + \
        bytes(ok) + bytes(own) + struct.pack("<BBBB", t.get("lamp_max", 8), t.get("balls") or 0, 0, 0)


def pack_data(modes, port, off=False):
    """struct pad_data: magic, count, off, the title, the names, the modes (padheck.c)."""
    if len(modes) > MAX_MODES:
        raise Refused("%d modes: the runtime takes %d" % (len(modes), MAX_MODES))
    names = b"".join(os.path.splitext(m.get("file", "mode"))[0].encode("ascii", "replace")[:NAME_MAX - 1].ljust(NAME_MAX, b"\0")
                     for m in modes)
    names = names.ljust(MAX_MODES * NAME_MAX, b"\0")
    names_of = [(m.get("name") or os.path.splitext(m.get("file", ""))[0]).strip().lower() for m in modes]
    for i, m in enumerate(modes):            # start_needs (PAD-1508): 1 + the other mode's place
        w = (m.get("start_needs") or "").split()
        if w and w[-1] in ("ball", "game"):
            w = w[:-1]
        need = " ".join(w).lower()
        m["_needs"] = (names_of.index(need) + 1) if need and need in names_of and names_of.index(need) != i else 0
        if need and not m["_needs"]:
            raise Refused("%s: start_needs %s: no other mode of ours has that name" % (m.get("file", "?"), need))
    body = b"".join(pack_mode(m, port) for m in modes).ljust(MAX_MODES * MODE_SIZE, b"\0")
    return struct.pack("<IBB", DATA_MAGIC, len(modes), 1 if off else 0) + title_head(port) + names + body


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
        # PAD-1469: the lamps by the number the game's lamp test shows, the coils a mode may use
        lamps=["lamp_%d" % n for n in range(64)],
        coils=sorted(t.get("coils") or ()), coil_holds=sorted(k for k, v in (t.get("coils") or {}).items() if v[2]),
        start_events=list(EVENTS), balls=t.get("balls"),
        sounds=card_sounds(card), voice_lines=0, game_modes=[], fonts=[],
        dmd=list(t["dmd"]), defaults=defaults or {},
        keys_not_here=list(KEYS_NOT_HERE),
    )
