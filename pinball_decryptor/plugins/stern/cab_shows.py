"""The cabinet's expression light shows on a Spike 2 card (PAD-1040; sdk/MODE_SDK.md "Expression light shows";
docs/plans/pad1040_expression_shows.md).

BEN (Discord): "Is there a way to read the expression lighting? Ultimately if songs are swapped out, the expression
lighting is no longer in sync with the replaced audio track. An example game would be Led Zeppelin." David: "We should
have an expression light show creator just like the playfield light show creator."

The expression lights are the blades down the cabinet's sides ("EXPRESSIVE LIGHTING L 1".."R 96": Led Zeppelin, Rush,
Foo Fighters LE, John Wick, King Kong, Metallica) and the backbox speaker lights ("SPEAKER 1".."23", nearly every
title). Led Zeppelin's own ExpressionLights picks the cabinet's show by the sound it plays, so a replaced song plays
under the old song's show. A show of the card's own (the project sidecar's ``cab_shows``) is tied to a SONG, a sound
slot of the project's: on the card, ``cabshow.cfg`` beside the mode runtime names the game's sound ids that start that
song, and the runtime (pad_mode_runtime.c "SONG SHOWS") plays the show from its first step whenever the game plays one
of them, over every cabinet light, until the song stops or the show is over. The game's own show comes back after it.

A show is two lanes of steps, one for the blades and one for the speaker lights (an empty lane leaves those lights to
the game). A step is a pattern of :data:`FX` for some ms, two colours, a pace and a blend-in from the step before. The
patterns are the runtime's own (the slice "CAB FX"), made for strips: a light is its place along its strip (0 at a
blade's bottom, 999 at its top; a speaker ring from the top round). The Modes tab's Expression lights page plays a
show on a drawing of the cabinet with the same arithmetic (webui/static/js/cabfx.js), and under the song's waveform.
"""
import json
import re

from . import lampmap as _LM

#: the project sidecar's key: ``{"shows": [...]}``
STAGED_KEY = "cab_shows"
#: the runtime's file beside it on the card
CFG_NAME = "cabshow.cfg"
#: the runtime's limits (pad_mode_runtime.c CABS_MAX, CAB_STEPS, CAB_SIDS)
SHOWS_MAX = 32
STEPS_MAX = 128
SIDS_MAX = 8
NAME_MAX = 31
#: a step's time, ms (the runtime's arithmetic holds to 1,000,000; nobody needs a step of more than ten minutes)
STEP_MS_MIN, STEP_MS_MAX = 20, 600000
RATE_MAX = 5000
LANES = ("blades", "speakers")

#: the patterns, in the runtime's order (CX_NAMES): key -> (label, group, what a/b/rate mean)
FX = {
    "solid": ("Solid", "Hold", "a"),
    "fade_in": ("Fade up", "Fades", "a"),
    "fade_out": ("Fade out", "Fades", "a"),
    "crossfade": ("Cross-fade", "Fades", "ab"),
    "pulse": ("Pulse", "Flashes", "abr"),
    "strobe": ("Strobe", "Flashes", "abr"),
    "sweep_up": ("Sweep up", "Sweeps", "ab"),
    "sweep_down": ("Sweep down", "Sweeps", "ab"),
    "fill_up": ("Fill up", "Sweeps", "ab"),
    "fill_down": ("Fill down", "Sweeps", "ab"),
    "chase_up": ("Chase up", "Chases", "abr"),
    "chase_down": ("Chase down", "Chases", "abr"),
    "bounce": ("Bounce", "Chases", "ab"),
    "center_out": ("From the middle", "Sweeps", "ab"),
    "center_in": ("To the middle", "Sweeps", "ab"),
    "alternate": ("Left / right", "Flashes", "abr"),
    "rainbow": ("Rainbow", "Color", "r"),
    "sparkle": ("Sparkle", "Color", "ab"),
    "fire": ("Fire", "Color", "ab"),
    "meter": ("Level meter", "Color", "abr"),
    # PAD-1063: the game's own show of one of its songs (cab_stock): req, set and from, no colours
    "game": ("The game's own show", "The game's", ""),
    # PAD-1516: a recording of a game's own cabinet lights (cab_rec): rec (its name) and from, no colours
    "rec": ("A recording of a game's lights", "The game's", ""),
}
GAME = "game"
REC = "rec"
#: a recording's name: what the project's cab_rec folder keeps it under
REC_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]{0,47}$")
#: where in the game's show a step may start: its longest is under nine minutes
FROM_MAX = 1200000
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
#: the page's word for a game whose cabinet has no expression lights
NO_LIGHTS = "This game's cabinet has no expression lights: no blades and no speaker lights the app can light."


def step(fx="solid", ms=1000, a="#ffffff", b="#000000", rate=0, blend=0):
    return {"fx": fx, "ms": ms, "a": a, "b": b, "rate": rate, "blend": blend}


#: ready-made shows to start from: (key, label, loop, blades, speakers)
PRESETS = (
    ("rock", "Rock pulse", True,
     [step("pulse", 4000, "#ff2000", "#200000", 250), step("strobe", 1000, "#ffffff", "#000000", 60, 0),
      step("sweep_up", 2000, "#ffb000", "#200000", 0, 200)],
     [step("pulse", 7000, "#ff2000", "#100000", 250)]),
    ("rainbow", "Rainbow roll", True,
     [step("rainbow", 8000, rate=200)], [step("rainbow", 8000, rate=150)]),
    ("fire", "Fire", True,
     [step("fire", 6000, "#ffa000", "#600000")], [step("pulse", 6000, "#ff6000", "#300000", 400)]),
    ("meter", "Level meter", True,
     [step("meter", 6000, "#00ff40", "#ff2000", 120)], [step("chase_up", 6000, "#00ff40", "#000000", 120)]),
    ("sweeps", "Sweeps up and down", True,
     [step("sweep_up", 1500, "#00a0ff", "#000020"), step("sweep_down", 1500, "#a040ff", "#100020", 0, 150)],
     [step("chase_up", 3000, "#00a0ff", "#000000", 100)]),
    ("calm", "Slow fade", True,
     [step("fade_in", 3000, "#4000ff"), step("crossfade", 3000, "#4000ff", "#ff40a0"),
      step("crossfade", 3000, "#ff40a0", "#4000ff")],
     [step("crossfade", 9000, "#4000ff", "#ff40a0")]),
    ("blank", "Blank", False, [], []),
)


def preset(key):
    """A new show from one of :data:`PRESETS` (unknown: the blank one)."""
    for k, label, loop, blades, speakers in PRESETS:
        if k == key:
            return {"name": label if k != "blank" else "New show", "slot": None, "loop": loop,
                    "blades": [dict(s) for s in blades], "speakers": [dict(s) for s in speakers]}
    return preset("blank")


def _int(v, lo, hi, dflt):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return dflt


def norm_step(st):
    st = st if isinstance(st, dict) else {}
    fx = st.get("fx") if st.get("fx") in FX else "solid"
    ms = _int(st.get("ms"), STEP_MS_MIN, STEP_MS_MAX, 1000)
    out = {"fx": fx, "ms": ms,
           "a": st.get("a") if COLOR_RE.match(str(st.get("a") or "")) else "#ffffff",
           "b": st.get("b") if COLOR_RE.match(str(st.get("b") or "")) else "#000000",
           "rate": _int(st.get("rate"), 0, RATE_MAX, 0), "blend": _int(st.get("blend"), 0, ms, 0)}
    if fx == GAME:                                      # PAD-1063: which of the game's shows, and from where in it
        out.update(req=_int(st.get("req"), 0, 65535, 0), set=st.get("set") if st.get("set") == "remix" else "original",
                   **{"from": _int(st.get("from"), 0, FROM_MAX, 0)})
    if fx == REC:                                       # PAD-1516: which recording, and from where in it
        name = str(st.get("rec") or "")
        out.update(rec=name if REC_NAME_RE.match(name) else "", **{"from": _int(st.get("from"), 0, FROM_MAX, 0)})
    return out


def recs_of(show):
    """PAD-1516: the names of the recordings *show*'s steps play."""
    return sorted({st["rec"] for lane in LANES for st in show.get(lane) or [] if st["fx"] == REC and st.get("rec")})


def game_step(req, ms, which="original", start=0):
    """PAD-1063: a step playing the game's own show of the song request *req* (``set`` *which*) from *start* ms."""
    return norm_step({"fx": GAME, "ms": ms, "req": req, "set": which, "from": start})


def uses_game(show):
    """1 when a step of *show* plays one of the game's own shows."""
    return any(st["fx"] == GAME for lane in LANES for st in show.get(lane) or [])


def norm_show(s):
    s = s if isinstance(s, dict) else {}
    slot = s.get("slot")
    # a sound-bank record's idx, or PAD-1379 a music bank's song (sound_modes.bank_slot_key: below zero)
    slot = slot if isinstance(slot, int) and not isinstance(slot, bool) and slot >= -(1 << 32) else None
    out = {"name": str(s.get("name") or "").strip()[:NAME_MAX] or "Show", "slot": slot, "loop": bool(s.get("loop"))}
    for lane in LANES:
        out[lane] = [norm_step(x) for x in (s.get(lane) if isinstance(s.get(lane), list) else [])][:STEPS_MAX]
    return out


def norm(raw):
    """The sidecar's ``cab_shows``: ``{"shows": [...]}``, each show normalized, at most :data:`SHOWS_MAX`."""
    raw = raw if isinstance(raw, dict) else {}
    shows = raw.get("shows") if isinstance(raw.get("shows"), list) else []
    out = {"shows": [norm_show(s) for s in shows[:SHOWS_MAX] if isinstance(s, dict)]}
    if isinstance(raw.get(ADDED_KEY), dict):            # PAD-1448: the cabinet lights the owner's cabinet adds
        out[ADDED_KEY] = norm_added(raw[ADDED_KEY])
    return out


# ---- PAD-1448: cabinet lights the owner's cabinet adds ---------------------------------------------------------
#: Friday (Pinside): "add speaker light effects to stern games that don't have them ... stranger things or Munsters".
#: Such a title still lists node 2, Cabinet Lights (the board Stern's Expression Lighting kit and the game-driven
#: speaker kits hang off), with nothing on it. The owner says what is on his board (speaker lights, blade pixels a
#: side); the card's addcab.cfg makes the runtime add them to the game's own lights (pad_mode_runtime.c addcab_arm),
#: and they are cabinet lights like a Led Zeppelin's: the shows light them. lampmap.added_cabinet places them.
ADDED_KEY = "added"
ADD_CFG = "addcab.cfg"
ADDED_PORT_DATA = ("addcab_light_tab", "addcab_dev_tab", "addcab_light_n", "addcab_dev_n")
ADDED_PORT_VALUES = ("addcab_lights", "addcab_devices", "addcab_clone", "addcab_slot")
NO_CAB_ADDABLE = ("%s's cabinet has no blades or speaker lights of its own. If yours has a Cabinet Lights board fitted (the "
                  "board Stern's Expression Lighting kit uses, node 2) with speaker lights or blades on it, say what "
                  "is on it and the game will light them with your shows.")


def norm_added(raw):
    """``{"on", "speakers", "blades"}``: whether the card adds cabinet lights, how many speaker lights (the two rings)
    and how many blade pixels a side."""
    raw = raw if isinstance(raw, dict) else {}
    sp = _int(raw.get("speakers"), 0, _LM.ADDCAB_SPEAKERS_MAX, _LM.ADDCAB_SPEAKERS_DEFAULT)
    bl = _int(raw.get("blades"), 0, _LM.ADDCAB_BLADES_MAX, 0)
    if not sp and not bl:
        sp = _LM.ADDCAB_SPEAKERS_DEFAULT
    return {"on": bool(raw.get("on")), "speakers": sp, "blades": bl}


def load_added(project):
    """The project's added cabinet lights (:func:`norm_added`), off when it says nothing."""
    if not project:
        return norm_added({})
    from ...core import staged_changes
    try:
        return norm_added((staged_changes.load(project).get(STAGED_KEY) or {}).get(ADDED_KEY))
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return norm_added({})


def addable(port):
    """1 when the port says where this build's light tables are (lampmap.added_cabinet_lines): it can take them."""
    return (all(n in (port.get("data") or {}) for n in ADDED_PORT_DATA)
            and all(n in (port.get("value") or {}) for n in ADDED_PORT_VALUES))


def added_lights(port, added):
    """lampmap.added_cabinet's list for *added* on this port's build; [] when off or the build cannot take them."""
    if not added or not added.get("on") or not addable(port):
        return []
    return _LM.added_cabinet(int(port["value"]["addcab_lights"]), added["speakers"], added["blades"])


def added_layout(port, added):
    """:func:`layout` for the added cabinet lights."""
    return [{"name": c["name"], "lane": 1 if c["role"] == "speaker" else 0,
             "side": -1 if c["side"] == "L" else 1 if c["side"] == "R" else 0, "u": c["u"], "x": c["x"], "y": c["y"]}
            for c in added_lights(port, added)]


def added_cfg_text(port, added):
    """addcab.cfg for the card, or "" when it adds none."""
    cab = added_lights(port, added)
    return _LM.added_cabinet_cfg(cab) if cab else ""


#: PAD-1516: the recordings a card carries at most (pad_mode_runtime.c CAB_RECS)
REC_FILES_MAX = 8

#: PAD-1516: why a show of another project's stays behind when its game is another
GAME_ONLY = "it plays %s's own show from its program, which another game does not have"


def copy_shows(shows, same_title, names, room, source_label="its game"):
    """PAD-1516 (Jim-Beam: "store/copy those animations to take it to other titles like Iron Maiden"): another
    project's *shows* made ready for this one. ``(copied, left)``: the copies, named apart from *names* (the shows
    this project has) and at most *room* of them, and ``[(name, why)]`` for those left behind. Steps are colours and
    patterns over a lane, so they play on any cabinet; a show's song is its own project's sound, so on another game
    (*same_title* false) a copy plays with no song until one is picked, and a show playing the game's own frames
    (:func:`uses_game`) cannot go to another game at all."""
    copied, left, taken = [], [], set(names)
    for s in shows:
        s = norm_show(json.loads(json.dumps(s)))
        if not same_title and uses_game(s):
            left.append((s["name"], GAME_ONLY % source_label))
            continue
        if len(copied) >= room:
            left.append((s["name"], "this project has room for %d shows" % SHOWS_MAX))
            continue
        if not same_title:
            s["slot"] = None
        base, n = s["name"], 2
        while s["name"] in taken:
            s["name"] = ("%s %d" % (base, n))[:NAME_MAX]
            n += 1
        taken.add(s["name"])
        copied.append(s)
    return copied, left


def length_ms(show):
    """The show's length: its longer lane's."""
    return max([sum(st["ms"] for st in show.get(lane) or []) for lane in LANES] + [0])


def problems(show, slots=None, requests=None):
    """What stops a show playing as the user means it, in words (``slots``: the project's song slots, or None;
    ``requests``: the song requests the game keeps shows for, or None when unknown)."""
    out = []
    if not show["blades"] and not show["speakers"]:
        out.append("It has no steps: the game's own show plays.")
    if show["slot"] is None:
        out.append("It plays with no song: pick the song it goes with.")
    elif slots is not None and show["slot"] not in slots:
        out.append("Its song is not one of this project's sounds any more.")
    if uses_game(show) and requests is not None:
        if not requests:
            out.append("A step plays the game's own show, but this game keeps none the app can read: the card "
                       "leaves the show out.")
        elif any(st["fx"] == GAME and st["req"] not in requests for lane in LANES for st in show[lane]):
            out.append("A step plays a show of the game's this game does not have: pick its song again.")
    return out


def sids_for_slot(plays, slot):
    """The game's sound ids that START the song in *slot*: those whose descriptor plays that record first
    (*plays*: engine._sound_id_plays, ``{sid: [idx, ...]}``)."""
    return sorted(sid for sid, idxs in (plays or {}).items() if idxs and idxs[0] == slot)[:SIDS_MAX]


def _hex(c):
    return "0x" + c[1:].lower()


def cfg_text(shows, sids_of, only, stock=None, recs=None):
    """``cabshow.cfg``: each show with a song this build plays (*sids_of*: ``{slot: [sid, ...]}``), its two lanes.
    *only*: the card carries no modes (the runtime arms the shows and nothing else). *stock*: the game's own shows on
    this build (:func:`.cab_stock.read`), for a step that plays one (``songs`` / ``songspk``: the runtime reads their
    frames from the game's memory); a show with such a step on a build without them is left out. PAD-1516 *recs*:
    ``{name: {file, period, frames, lights, map}}``, the recordings staged beside the file (``map``: each of this
    cabinet's lights' source light in it, -1 none); a show playing one not there is left out. Returns (text,
    [skipped names])."""
    lines = ["# PAD-1040: the card's expression light shows (pad_mode_runtime.c \"SONG SHOWS\")"]
    if only:
        lines.append("only")
    reqs = {r["request"] for r in (stock or {}).get("rows", ())}
    keep, skipped = [], []
    for s in shows:
        sids = list(sids_of.get(s["slot"], ())) if s["slot"] is not None else []
        game_ok = all(st["req"] in reqs for lane in LANES for st in s[lane] if st["fx"] == GAME)
        rec_ok = all(r in (recs or {}) for r in recs_of(s))
        if not sids or not (s["blades"] or s["speakers"]) or not game_ok or not rec_ok:
            skipped.append(s["name"])
            continue
        keep.append((s, sids))
    if any(uses_game(s) for s, _sids in keep):
        lines.append("songs 0x%x %d %d" % (stock["table"], len(stock["rows"]), stock["pixels"]))
        if stock.get("speakers"):
            lines.append("songspk %s" % " ".join(",".join(str(p) for p in g) for g in stock["speakers"]))
    used = sorted({r for s, _sids in keep for r in recs_of(s)})
    rec_ix = {r: i for i, r in enumerate(used[:REC_FILES_MAX])}
    for r, i in rec_ix.items():
        x = recs[r]
        lines.append("rec %d %d %d %d %s" % (i, x["period"], x["frames"], x["lights"], x["file"]))
        lines.append("recmap %d %s" % (i, ",".join(str(int(m)) for m in x["map"])))
    for s, sids in keep:
        if any(r not in rec_ix for r in recs_of(s)):
            skipped.append(s["name"])
            continue
        lines.append("show %s %d %s" % (",".join(str(x) for x in sids), 1 if s["loop"] else 0, s["name"]))
        for lane in LANES:
            for st in s[lane]:
                if st["fx"] == GAME:
                    lines.append("%s game %d %d %d %d %d" % (lane, st["ms"], st["req"], 1 if st["set"] == "remix"
                                                             else 0, st["from"], st["blend"]))
                    continue
                if st["fx"] == REC:
                    lines.append("%s rec %d %d 0 %d %d" % (lane, st["ms"], rec_ix[st["rec"]], st["from"],
                                                          st["blend"]))
                    continue
                lines.append("%s %s %d %s %s %d %d" % (lane, st["fx"], st["ms"], _hex(st["a"]), _hex(st["b"]),
                                                       st["rate"], st["blend"]))
    return "\n".join(lines) + "\n", skipped


def layout_from_port(port):
    """PAD-1379: :func:`layout` for a title whose port carries its cabinet's lights (a Spike 3 port's ``cablamp``
    lines, drafted off the 64-bit tables: s3port.cabinet_lines_a64), placed as the runtime places them."""
    out = []
    for c in _LM.cabinet_from_port([(name, ids) for name, ids, _u in port.get("cablamp") or ()]):
        out.append({"name": c["name"], "lane": 1 if c["role"] == "speaker" else 0,
                    "side": -1 if c["side"] == "L" else 1 if c["side"] == "R" else 0,
                    "u": c["u"], "x": c["x"], "y": c["y"]})
    return out


def layout(game_elf):
    """The cabinet drawing for the preview: ``[{name, lane, side, u, x, y}]`` of the card's expression lights (lane 0
    the blades, 1 the speakers; side -1 the left blade or speaker, 1 the right, 0 one ring alone), as the port's ``cablamp`` lines
    give the runtime; [] for a title with none."""
    elf = _LM.Elf(game_elf, "the game program") if isinstance(game_elf, (bytes, bytearray)) else game_elf
    out = []
    for c in _LM.cabinet(elf):
        lane = 1 if c["role"] == "speaker" else 0
        out.append({"name": c["name"], "lane": lane, "side": -1 if c["side"] == "L" else 1 if c["side"] == "R" else 0,
                    "u": c["u"], "x": c["x"], "y": c["y"]})
    return out


# ---- the project and the card ----------------------------------------------------------------------------------
#: what a card of these shows does on Insider Connected (the log and the tab)
INSIDER_WORDS = ("They change only the cabinet's lights, not the game or its scores: a card that carries only "
                 "these shows stays on Insider Connected.")
NO_TITLE = "The app cannot tell which game this project is for."
NO_CAB = "%s has no expression lights the app knows: its port names no blades or speaker lights."
NO_LAYER = "The app does not know how %s lights its lamps yet, so it cannot hold its cabinet's lights."
#: PAD-1328: a Spike 3 port names its cabinet's lights (cablamp lines off the 64-bit tables) and the runtime holds them
#: with a song; PAD-1370: the strips' lamp data is the netbridge's (host cmd 2f), which the rig lights; PAD-1379: the
#: Write carries cabshow.cfg (spike3_modes.cabs_wanted), each show started by its song's sound ids off image.bin's and
#: the music banks' own descriptors and locked to its song's voice. A Spike 3 title takes them as a Spike 2 one does:
#: by its port (Star Wars ELG names no cabinet lights: NO_CAB)
#: what the runtime needs of the port: the lamp layer (lamps_arm) and, for a show to start with its song, the sound
#: worker and the request table
PORT_SITES = ("lamp_group",)
PORT_DATA = ("lamp_layers", "light_count")
SONG_SITES = ("sound_worker",)
SONG_DATA = ("sound_requests", "sound_request_count")


def load(project):
    """The project's shows (the sidecar's ``cab_shows``), normalized; [] for none or an unreadable sidecar."""
    if not project:
        return []
    from ...core import staged_changes
    try:
        return norm(staged_changes.load(project).get(STAGED_KEY))["shows"]
    except Exception:                                   # noqa: BLE001 - an unreadable sidecar: none
        return []


def project_title(project, probe=False):
    """The profile of the card ``project`` was made from, or None."""
    from .clip_variants import project_title as _pt
    return _pt(project, probe=probe)


def port_refusal(port, label, added=None):
    """Why a parsed port cannot carry the shows, or ``""``. PAD-1448: a title with no cabinet lights of its own takes
    them once the owner adds some (*added*, :func:`norm_added`) and its port can (:func:`addable`)."""
    if not port.get("cablamp") and not added_lights(port, added):
        return NO_CAB_ADDABLE % label if addable(port) else NO_CAB % label
    if not all(n in port.get("site", {}) for n in PORT_SITES) or not all(n in port.get("data", {}) for n in PORT_DATA):
        return NO_LAYER % label
    return ""


def title_refusal(prof, added=None):
    """Why ``prof``'s game cannot have expression light shows of the card's, or ``""`` (*added*: the project's added
    cabinet lights, PAD-1448)."""
    if prof is None:
        return NO_TITLE
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_CAB % prof.label
    return port_refusal(port, prof.label, added)


def plays_with_songs(port):
    """1 when the port lets a show start with its song (the sound worker and the request table)."""
    return all(n in port.get("site", {}) for n in SONG_SITES) and all(n in port.get("data", {}) for n in SONG_DATA)
