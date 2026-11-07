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
    "rainbow": ("Rainbow", "Colour", "r"),
    "sparkle": ("Sparkle", "Colour", "ab"),
    "fire": ("Fire", "Colour", "ab"),
    "meter": ("Level meter", "Colour", "abr"),
}
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
    return {"fx": fx, "ms": ms,
            "a": st.get("a") if COLOR_RE.match(str(st.get("a") or "")) else "#ffffff",
            "b": st.get("b") if COLOR_RE.match(str(st.get("b") or "")) else "#000000",
            "rate": _int(st.get("rate"), 0, RATE_MAX, 0), "blend": _int(st.get("blend"), 0, ms, 0)}


def norm_show(s):
    s = s if isinstance(s, dict) else {}
    slot = s.get("slot")
    slot = slot if isinstance(slot, int) and not isinstance(slot, bool) and slot >= 0 else None
    out = {"name": str(s.get("name") or "").strip()[:NAME_MAX] or "Show", "slot": slot, "loop": bool(s.get("loop"))}
    for lane in LANES:
        out[lane] = [norm_step(x) for x in (s.get(lane) if isinstance(s.get(lane), list) else [])][:STEPS_MAX]
    return out


def norm(raw):
    """The sidecar's ``cab_shows``: ``{"shows": [...]}``, each show normalized, at most :data:`SHOWS_MAX`."""
    raw = raw if isinstance(raw, dict) else {}
    shows = raw.get("shows") if isinstance(raw.get("shows"), list) else []
    return {"shows": [norm_show(s) for s in shows[:SHOWS_MAX] if isinstance(s, dict)]}


def length_ms(show):
    """The show's length: its longer lane's."""
    return max([sum(st["ms"] for st in show.get(lane) or []) for lane in LANES] + [0])


def problems(show, slots=None):
    """What stops a show playing as the user means it, in words (``slots``: the project's song slots, or None)."""
    out = []
    if not show["blades"] and not show["speakers"]:
        out.append("It has no steps: the game's own show plays.")
    if show["slot"] is None:
        out.append("It plays with no song: pick the song it goes with.")
    elif slots is not None and show["slot"] not in slots:
        out.append("Its song is not one of this project's sounds any more.")
    return out


def sids_for_slot(plays, slot):
    """The game's sound ids that START the song in *slot*: those whose descriptor plays that record first
    (*plays*: engine._sound_id_plays, ``{sid: [idx, ...]}``)."""
    return sorted(sid for sid, idxs in (plays or {}).items() if idxs and idxs[0] == slot)[:SIDS_MAX]


def _hex(c):
    return "0x" + c[1:].lower()


def cfg_text(shows, sids_of, only):
    """``cabshow.cfg``: each show with a song this build plays (*sids_of*: ``{slot: [sid, ...]}``), its two lanes.
    *only*: the card carries no modes (the runtime arms the shows and nothing else). Returns (text, [skipped names])."""
    lines = ["# PAD-1040: the card's expression light shows (pad_mode_runtime.c \"SONG SHOWS\")"]
    if only:
        lines.append("only")
    skipped = []
    for s in shows:
        sids = list(sids_of.get(s["slot"], ())) if s["slot"] is not None else []
        if not sids or not (s["blades"] or s["speakers"]):
            skipped.append(s["name"])
            continue
        lines.append("show %s %d %s" % (",".join(str(x) for x in sids), 1 if s["loop"] else 0, s["name"]))
        for lane in LANES:
            for st in s[lane]:
                lines.append("%s %s %d %s %s %d %d" % (lane, st["fx"], st["ms"], _hex(st["a"]), _hex(st["b"]),
                                                       st["rate"], st["blend"]))
    return "\n".join(lines) + "\n", skipped


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


def port_refusal(port, label):
    """Why a parsed port cannot carry the shows, or ``""``."""
    if not port.get("cablamp"):
        return NO_CAB % label
    if not all(n in port.get("site", {}) for n in PORT_SITES) or not all(n in port.get("data", {}) for n in PORT_DATA):
        return NO_LAYER % label
    return ""


def title_refusal(prof):
    """Why ``prof``'s game cannot have expression light shows of the card's, or ``""``."""
    if prof is None:
        return NO_TITLE
    from . import mode_project as MP
    try:
        port = MP.read_port(MP.port_path(prof))
    except (OSError, MP.ModeProjectError):
        return NO_CAB % prof.label
    return port_refusal(port, prof.label)


def plays_with_songs(port):
    """1 when the port lets a show start with its song (the sound worker and the request table)."""
    return all(n in port.get("site", {}) for n in SONG_SITES) and all(n in port.get("data", {}) for n in SONG_DATA)
