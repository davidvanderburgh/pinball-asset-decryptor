"""Per-game scripted "play-through" sequences for the PinMAME capture
pipeline.

Architecture
------------

Each registered :class:`GameScript` owns:

  * The switch numbers for the cabinet/trough/shooter-lane on that
    title.  These come from :mod:`.wpc_profiles`, which is auto-
    generated from PinMAME's ``src/wpc/sims/wpc/{full,prelim}/<rom>.c``
    source files (the authoritative per-game switch matrix).
  * An ordered list of :class:`GameMoment` s describing the "tour"
    through gameplay we want to capture.  Each moment is a deliberate
    sequence of switch actions that the rules say will trigger a
    specific cinematic (skill shot, mode start, lock, multiball, etc.).

Each :class:`GameMoment` is a list of :class:`SwitchEvent` s — either
a momentary press (``hold_ms`` set, ``state`` left ``None``) or a
sustained set/clear (``state`` 0/1, ``hold_ms`` 0).

The capture runner (:func:`run_script`) walks the moments in order,
calling ``PinmameSetSwitch`` with the appropriate timing, recording
start/end timestamps so the pipeline can emit one named MP4 per
scene.

How to add / improve a game
---------------------------

1. The switch map should already exist in :mod:`.wpc_profiles`.  If
   not, run ``tools/refresh_wpc_profiles.py`` (or re-run the gh-api
   fetch used to build that module).
2. Register a per-game moments factory in :data:`_MOMENTS_FACTORIES`
   keyed by the ``GAME_DB`` key (e.g. ``"attack_from_mars"``).  The
   factory receives the script (so it can read the profile) and
   returns ``list[GameMoment]``.
3. Untouched games auto-register with the profile-driven generic
   playthrough below.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .games import GAME_DB
from .wpc_profiles import WPC_GAME_PROFILES


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

@dataclass
class MomentClip:
    """A scripted scene with known capture-relative timestamps.

    Timestamps are in milliseconds since the capture's frame-timeline
    origin (same clock as :class:`CaptureFrame.timestamp_ms`).  The
    pipeline uses these to slice frames + audio into a per-scene MP4
    named after :attr:`name`.
    """
    name: str
    start_ms: int
    end_ms: int
    description: str = ""


@dataclass
class SwitchEvent:
    """One switch action.

    Two flavors:
      * **Momentary** (``state=None``): set sw→1, hold ``hold_ms``,
        then sw→0.  Use for buttons, targets, ramps.
      * **Sustained** (``state in (0,1)``, ``hold_ms=0``): set sw to
        the given state and leave it.  Use for stateful sensors
        (trough switches, shooter-lane proximity, coin door).

    ``delay_after_ms`` paces animations between presses.  ``sw=-1`` is
    a sentinel pure-wait (no switch action).
    """
    sw: int
    state: Optional[int] = None
    hold_ms: int = 80
    delay_after_ms: int = 200
    note: str = ""


@dataclass
class GameMoment:
    """A named in-game event we want to drive the ROM into."""
    name: str
    events: List[SwitchEvent]
    wait_before_ms: int = 0
    description: str = ""


def _press(sw, hold_ms=80, delay=180, note=""):
    return SwitchEvent(sw=sw, state=None, hold_ms=hold_ms,
                       delay_after_ms=delay, note=note)


def _set(sw, state, delay=120, note=""):
    return SwitchEvent(sw=sw, state=state, hold_ms=0,
                       delay_after_ms=delay, note=note)


def _wait(ms, note=""):
    return SwitchEvent(sw=-1, state=None, hold_ms=0,
                       delay_after_ms=ms, note=note or f"wait {ms}ms")


# ---------------------------------------------------------------------------
# GameScript — profile-backed
# ---------------------------------------------------------------------------

# Standard WPC defaults — apply when a profile field is missing.
_DEFAULTS = {
    "start": 13,
    "coin_door": 22,
    "tilt": 14,
    "slam_tilt": 21,
    "coin_left": 1,
    "launch": 11,
}


class GameScript:
    """Per-game switch map + ordered list of moments.

    Constructed from a ``WPC_GAME_PROFILES`` entry: the profile holds
    the authoritative switch numbers (trough range, shooter-lane,
    launch button, etc.) sourced from PinMAME upstream, and the
    moments are built by a per-game factory or the generic factory.
    """

    def __init__(self, game_key: str, title: str,
                 rom_names: Tuple[str, ...],
                 profile: dict,
                 moments_factory: Optional[Callable] = None):
        self.game_key = game_key
        self.title = title
        self.rom_names = tuple(rom_names)
        self.profile = dict(profile)

        # Cabinet / ball-flow switches.  Profile values win over
        # standard defaults.
        self.sw_start = self.profile.get("start") or _DEFAULTS["start"]
        self.sw_coin_door = (self.profile.get("coin_door")
                             or _DEFAULTS["coin_door"])
        self.sw_coin_left = _DEFAULTS["coin_left"]
        self.sw_launch = self.profile.get("launch")  # may be None
        trough = self.profile.get("trough") or ()
        # Many older 3-ball games list trough in (L, C, R) order with
        # the *first ejected* ball at swLTrough.  Some new games list
        # in numeric (32,33,34,35) order with swTrough1 = first
        # ejected.  We normalize: position [0] = first-to-be-ejected.
        # The order in the profile already reflects this (e.g. AFM's
        # swTrough1=32 is first, white_water's swLTrough=78 is first
        # because the profile preserves source ordering).
        self.sw_trough: Tuple[int, ...] = tuple(trough)
        self.sw_shooter_lane = self.profile.get("shooter_lane")
        self.sw_eject = self.profile.get("eject")

        # Build moments using the per-game factory or the generic.
        factory = moments_factory or _generic_moments
        self.moments: List[GameMoment] = factory(self)

    # ---- Convenience for moment factories ----

    def raw(self, *names: str) -> Optional[int]:
        """Return the first switch number found in the profile's raw map."""
        raw = self.profile.get("raw", {})
        for n in names:
            if n in raw:
                return int(raw[n])
        return None

    def find_all_matching(self, *substrings: str) -> List[int]:
        """Return all switch numbers whose name contains any substring."""
        raw = self.profile.get("raw", {})
        keys = [k for k in raw if any(s.lower() in k.lower()
                                       for s in substrings)]
        return [int(raw[k]) for k in sorted(keys, key=lambda k: int(raw[k]))]


# ---------------------------------------------------------------------------
# Generic profile-driven playthrough
# ---------------------------------------------------------------------------

def _end_of_ball_moment(s: "GameScript") -> GameMoment:
    """A drain-the-ball moment that captures the end-of-ball bonus
    cinematic.

    Simulates ball return to trough position 0 by closing
    ``sw_trough[0]``.  The ROM reads this as "ball drained, time
    for end-of-ball bonus".  We hold the state for ~6s so the full
    bonus cinematic + match-style score chase has time to render.
    """
    if not s.sw_trough:
        # Fallback for profiles with no trough info — just a wait.
        return GameMoment(
            name="end_of_ball",
            description="(no trough switches known — idle wait)",
            wait_before_ms=200,
            events=[_wait(5000, note="post-script idle")],
        )
    return GameMoment(
        name="end_of_ball",
        description="Simulate ball drain — captures EOB bonus cinematic.",
        wait_before_ms=500,
        events=[
            _set(s.sw_trough[0], 1, delay=200,
                 note=f"trough[0] sw#{s.sw_trough[0]} CLOSED = ball drained"),
            _wait(6000, note="end-of-ball bonus animation"),
        ],
    )


# ---------------------------------------------------------------------------
# Switch-map pattern matching (used by the smart generic factory)
# ---------------------------------------------------------------------------

def _detect_side(name: str) -> Optional[str]:
    """Return 'L' / 'C' / 'R' for left/center/right switch names."""
    nl = name.lower()
    if any(t in nl for t in ("left", "lramp", "lloop", "enterl")):
        return "L"
    if any(t in nl for t in ("center", "cramp", "cloop", "enterc")):
        return "C"
    if any(t in nl for t in ("right", "rramp", "rloop", "enterr")):
        return "R"
    return None


def _is_entry_sensor(name: str) -> bool:
    nl = name.lower()
    return ("ent" in nl or "enter" in nl) and "centre" not in nl


def _is_made_sensor(name: str) -> bool:
    nl = name.lower()
    return any(t in nl for t in
               ("made", "ramptop", "rampex", "rampexit",
                "rampexit2", "ramp2"))


def _identify_ramp_pairs(raw):
    """Return [(label, entry_sw, made_sw_or_None), ...] for each side."""
    entries: dict = {}
    mades: dict = {}
    for name, sw in raw.items():
        if "ramp" not in name.lower():
            continue
        side = _detect_side(name)
        if side is None:
            continue
        if _is_entry_sensor(name):
            entries.setdefault(side, int(sw))
        elif _is_made_sensor(name):
            mades.setdefault(side, int(sw))
        elif side not in entries:
            entries[side] = int(sw)
    label_for = {"L": "left_ramp", "C": "center_ramp", "R": "right_ramp"}
    out = []
    for side in ("L", "C", "R"):
        if side in entries:
            out.append((label_for[side], entries[side], mades.get(side)))
    return out


def _identify_loop_pairs(raw):
    """Return [(label, lo_sw, hi_sw), ...].  Single-sensor loops use the
    same switch for both positions (one press counts)."""
    los: dict = {}
    his: dict = {}
    singles: dict = {}
    for name, sw in raw.items():
        nl = name.lower()
        if "loop" not in nl and "orbit" not in nl:
            continue
        side = _detect_side(name)
        if side is None:
            continue
        # Tokens after stripping loop/orbit/side qualifiers
        tail = (nl.replace("loop", "").replace("orbit", "")
                 .replace("left", "").replace("right", "")
                 .replace("l", "", 1) if side == "L" else
                 nl.replace("loop", "").replace("orbit", "")
                 .replace("left", "").replace("right", "")
                 .replace("r", "", 1) if side == "R" else nl)
        if "hi" in tail or "top" in tail or "upper" in tail:
            his[side] = int(sw)
        elif "lo" in tail or "low" in tail or "bot" in tail or "lower" in tail:
            los[side] = int(sw)
        else:
            singles.setdefault(side, int(sw))
    out = []
    for side in ("L", "R"):
        label = "left_loop" if side == "L" else "right_loop"
        if side in los and side in his:
            out.append((label, los[side], his[side]))
        elif side in singles:
            out.append((label, singles[side], singles[side]))
        elif side in los:
            out.append((label, los[side], los[side]))
        elif side in his:
            out.append((label, his[side], his[side]))
    return out


def _identify_saucers(raw):
    """Lock saucers, scoops, poppers, kicker holes — anything that
    captures a ball briefly.  Excludes trough / outhole."""
    seen = set()
    out = []
    for name, sw in raw.items():
        nl = name.lower()
        if "trough" in nl or "outhole" in nl or "shooter" in nl:
            continue
        if any(t in nl for t in ("saucer", "scoop", "popper",
                                  "lockup", "lock", "kicker", "hole",
                                  "vuk", "captive")):
            if sw in seen:
                continue
            seen.add(int(sw))
            out.append((name.lower().replace("sw", "").strip("_"),
                        int(sw)))
    return out[:4]


def _identify_drop_targets(raw):
    out = []
    seen = set()
    for name, sw in raw.items():
        nl = name.lower()
        if "drop" in nl or "dtarget" in nl or nl.startswith("swdt"):
            if int(sw) in seen:
                continue
            seen.add(int(sw))
            out.append(int(sw))
    return out


def _identify_jets(raw):
    out = []
    seen = set()
    for name, sw in raw.items():
        nl = name.lower()
        if "jet" in nl and "reject" not in nl:
            if int(sw) in seen:
                continue
            seen.add(int(sw))
            out.append(int(sw))
    return out


def _identify_slings(raw):
    out = []
    seen = set()
    for name, sw in raw.items():
        if "sling" not in name.lower():
            continue
        if int(sw) in seen:
            continue
        seen.add(int(sw))
        out.append(int(sw))
    return out


def _identify_singletons(raw):
    """Single-press named features worth a clip: spinners, captive,
    cameras, mystery scoops, etc."""
    out = []
    seen = set()
    interesting = ("spinner", "camera", "piano", "captive",
                   "mystery", "magnet", "slot", "gum", "drop_target")
    for name, sw in raw.items():
        nl = name.lower()
        for tag in interesting:
            if tag in nl:
                if int(sw) in seen:
                    break
                seen.add(int(sw))
                label = nl.replace("sw", "").strip("_")
                out.append((label, int(sw)))
                break
    return out[:4]


# ---------------------------------------------------------------------------
# Smart generic factory
#
# Applies the AFM-derived pattern to ANY WPC game using only the
# per-game switch profile (no rule-sheet knowledge required):
#
#   Phase A — Light each ramp + loop with 3 made shots (no mode start).
#   Phase B — Normal play: saucers, target sweeps, drops, jets, etc.
#   Phase C — Cluster all mode-starts at the end (each kills previous).
#   Phase D — End-of-ball drain (auto-appended).
#
# Why this shape: as soon as you START all the mode-light shots in
# a typical WPC game, the ROM auto-triggers its wizard-mode multiball
# (e.g. AFM's Total Annihilation) which then dominates every
# subsequent clip with the JACKPOT-ticker display.  Deferring the
# mode-starts until after all the "normal play" moments have been
# captured lets each cinematic land cleanly in its own clip.
# ---------------------------------------------------------------------------

def _generic_moments(s: "GameScript") -> List[GameMoment]:
    moments: List[GameMoment] = []
    raw = s.profile.get("raw", {})

    # ---- Skill shot ----
    if s.sw_launch:
        skill_events = [_press(s.sw_launch, hold_ms=180, delay=2000,
                               note=f"plunge sw#{s.sw_launch}")]
    else:
        skill_events = [_wait(2500, note="skill window (no launch button)")]
    moments.append(GameMoment(
        name="skill_shot",
        description="Plunge the ball into the playfield.",
        events=skill_events,
    ))

    ramps = _identify_ramp_pairs(raw)
    loops = _identify_loop_pairs(raw)

    # ---- Phase A: LIGHT each ramp (3 made shots) ----
    for label, enter_sw, made_sw in ramps:
        evts = []
        for _ in range(3):
            evts.append(_press(enter_sw, hold_ms=80, delay=350))
            if made_sw is not None and made_sw != enter_sw:
                evts.append(_press(made_sw, hold_ms=80, delay=1200))
            else:
                evts.append(_wait(1200))
        moments.append(GameMoment(
            name=f"{label}_light",
            description=f"3 made {label.replace('_', ' ')} shots.",
            wait_before_ms=400,
            events=evts,
        ))

    # ---- Phase A (cont.): LIGHT each loop (3 made loops) ----
    for label, lo_sw, hi_sw in loops:
        evts = []
        for _ in range(3):
            evts.append(_press(lo_sw, hold_ms=70, delay=300))
            if hi_sw != lo_sw:
                evts.append(_press(hi_sw, hold_ms=70, delay=1200))
            else:
                evts.append(_wait(1000))
        moments.append(GameMoment(
            name=f"{label}_light",
            description=f"3 made {label.replace('_', ' ')} completions.",
            wait_before_ms=400,
            events=evts,
        ))

    # ---- Phase B: Normal play ----
    # Saucers / scoops / locks.
    for i, (label, sw) in enumerate(_identify_saucers(raw)[:3], 1):
        moments.append(GameMoment(
            name=f"saucer_{i}",
            description=f"Hit saucer / scoop ({label}).",
            wait_before_ms=400,
            events=[_press(sw, hold_ms=120, delay=3000)],
        ))

    # Drop targets.
    drops = _identify_drop_targets(raw)
    if drops:
        moments.append(GameMoment(
            name="drop_targets",
            description="Knock down all drop targets.",
            wait_before_ms=400,
            events=[_press(sw, hold_ms=70, delay=250) for sw in drops[:6]]
                   + [_wait(2000)],
        ))

    # Jets.
    jets = _identify_jets(raw)
    if jets:
        evts = []
        for sw in jets * 2:
            evts.append(_press(sw, hold_ms=50, delay=90))
        evts.append(_wait(1500))
        moments.append(GameMoment(
            name="jet_bumpers",
            description="Cluster of jet-bumper hits.",
            wait_before_ms=300,
            events=evts,
        ))

    # Slings.
    slings = _identify_slings(raw)
    if slings:
        evts = []
        for sw in slings * 2:
            evts.append(_press(sw, hold_ms=40, delay=70))
        evts.append(_wait(1000))
        moments.append(GameMoment(
            name="slings",
            description="Slingshot scoring.",
            wait_before_ms=300,
            events=evts,
        ))

    # Singletons (mystery, captive ball, spinner, etc.)
    for label, sw in _identify_singletons(raw):
        moments.append(GameMoment(
            name=f"feature_{label}",
            description=f"Hit named feature ({label}).",
            wait_before_ms=300,
            events=[_press(sw, hold_ms=80, delay=2500)],
        ))

    # ---- Phase C: MODE STARTS clustered at the end ----
    # Each fires the made-shot trigger one more time, which (on most
    # WPC games) starts that mode's cinematic.  Each mode_start
    # naturally kills the previous mode, so 4 in a row gives us 4
    # mode-intro clips.  AFTER the final mode start, the wizard
    # multiball typically auto-triggers — which is fine because the
    # next moment is the end-of-ball drain.
    for label, enter_sw, made_sw in ramps:
        evts = [_press(enter_sw, hold_ms=80, delay=350)]
        if made_sw is not None and made_sw != enter_sw:
            evts.append(_press(made_sw, hold_ms=80, delay=5500,
                               note=f"{label} mode cinematic"))
        else:
            evts.append(_wait(5500, note=f"{label} mode cinematic"))
        moments.append(GameMoment(
            name=f"{label}_mode_start",
            description=f"4th made {label.replace('_', ' ')} starts the mode.",
            wait_before_ms=400,
            events=evts,
        ))
    for label, lo_sw, hi_sw in loops:
        evts = [_press(lo_sw, hold_ms=70, delay=300)]
        if hi_sw != lo_sw:
            evts.append(_press(hi_sw, hold_ms=70, delay=5500,
                               note=f"{label} mode cinematic"))
        else:
            evts.append(_wait(5500, note=f"{label} mode cinematic"))
        moments.append(GameMoment(
            name=f"{label}_mode_start",
            description=f"4th made {label.replace('_', ' ')} starts the mode.",
            wait_before_ms=400,
            events=evts,
        ))

    # ---- Sparse-data fallback ----
    # When the per-game PinMAME sim is too thin to yield decent
    # ramps/loops (typical of "prelim" sims which only define
    # trough + cabinet + inlanes/outlanes), build two safety-net
    # moments using whatever IS defined in the raw map:
    #
    #   1. "explore_known_playfield" — fire every defined playfield
    #      switch in the raw map (inlanes, outlanes, slings, etc.),
    #      skipping the seed switches we manage explicitly (trough,
    #      shooter lane, coin door, tilt).  These are real switches
    #      so the game gets real activity = no ball-search timeout.
    #
    #   2. "explore_standard_wpc" — fire the conventional WPC switch
    #      ranges (41-77) as a wishful-thinking pass.  PinMAME
    #      ignores undefined numbers so it's a no-op on games where
    #      the prelim sim didn't declare them, but on games that
    #      follow the convention this catches ramps + saucers the
    #      sim source never bothered to define.
    if len(ramps) + len(loops) < 2:
        # Block the seed switches the run loop manages itself.
        seed_blocked = set()
        if s.sw_trough:
            seed_blocked.update(s.sw_trough)
        if s.sw_shooter_lane is not None:
            seed_blocked.add(s.sw_shooter_lane)
        if s.sw_eject is not None:
            seed_blocked.add(s.sw_eject)
        seed_blocked.update({s.sw_coin_door, s.sw_coin_left,
                              s.sw_launch, s.sw_start, 14, 21})  # tilt, slamtilt
        # Outlanes drain the ball — skip them so we don't end the
        # ball before the script finishes.
        known_playfield = []
        for name, sw in sorted(raw.items(), key=lambda kv: int(kv[1])):
            sw_n = int(sw)
            if sw_n in seed_blocked:
                continue
            nl = name.lower()
            if "outlane" in nl or "trough" in nl or "shooter" in nl:
                continue
            if "tilt" in nl or "slam" in nl or "coindoor" in nl:
                continue
            known_playfield.append((sw_n, name))
        if known_playfield:
            evts = []
            # Fire each known switch twice so the game sees sustained
            # activity (one fire might be filtered as bounce).
            for cycle in range(2):
                for sw_n, _ in known_playfield:
                    evts.append(_press(sw_n, hold_ms=60, delay=300))
            evts.append(_wait(2000))
            moments.append(GameMoment(
                name="explore_known_playfield",
                description=(
                    f"Fire every defined playfield switch in the "
                    f"profile ({len(known_playfield)} switches) — "
                    "keeps the ball-search timer from ending the "
                    "ball when the sim is too sparse for a rich "
                    "playthrough."),
                wait_before_ms=400,
                events=evts,
            ))
        # Best-effort standard-positions pass too.
        evts = []
        for sw in (62, 63, 61, 65, 64,        # ramps
                   71, 72, 73, 74, 75, 76,    # loops + saucers
                   41, 42, 43, 44, 45,        # target bank
                   53, 54, 55,                # jets
                   77):                        # drop target
            evts.append(_press(sw, hold_ms=60, delay=300))
        evts.append(_wait(2000))
        moments.append(GameMoment(
            name="explore_standard_wpc",
            description=(
                "Fire conventional WPC playfield switch numbers; "
                "no-op on games where the sim file didn't declare "
                "them at standard positions."),
            wait_before_ms=400,
            events=evts,
        ))

    # ---- Phase D: end-of-ball drain (auto-appended by registry) ----
    moments.append(_end_of_ball_moment(s))
    return moments


# ---------------------------------------------------------------------------
# Per-game rich moment factories
#
# These are hand-tuned against the rule sheet of each title — they
# fire the SPECIFIC shot sequences known to trigger named cinematics
# (mode starts, multiball locks, jackpot animations, etc.) rather
# than just touring playfield areas the way the generic factory does.
# ---------------------------------------------------------------------------

def _afm_moments(s: GameScript) -> List[GameMoment]:
    """Attack From Mars rule references:
        * Left ramp x3   → Big-O-Beam lit  (4th = MODE START)
        * Right ramp x3  → Tractor Beam lit (4th = MODE START)
        * Right loop x3  → Atomic Blaster lit (4th = MODE START)
        * Left loop x3   → Capture lit (4th = MODE START)
        * All 4 modes started + countdown shot = TOTAL ANNIHILATION
        * 7 MARTIAN tgts → Stroke of Luck lit (at R saucer)
        * R saucer hit   → MARTIAN ATTACK / mystery cinematic
        * Center ramp x3 → Lock lit at L saucer
        * 3 locks        → MULTIBALL
        * 5 named shots in a row = 5-WAY COMBO
        * Replay-set score hit = REPLAY cinematic
    """
    return [
        GameMoment(
            name="skill_shot",
            description="Plunge — skill-shot DMD shows arrow awards.",
            events=[_press(s.sw_launch, hold_ms=200, delay=1500)],
        ),
        # A "made ramp/loop shot" on WPC requires the ENTRY sensor
        # and the MADE sensor to both fire within the timeout window
        # (~1-2s).  My earlier script was firing only the entry —
        # the ball "passed through" but never "made the shot", so
        # the score went up from incidental switches but the lit
        # award never advanced.  Per PinMAME afm.c:
        #   L ramp:   sw 61 (swLRampEnt) → sw 64 (swLRampTop)
        #   R ramp:   sw 63 (swRRampEnt) → sw 65 (swRRampEx)
        #   R loop:   sw 72 (swRLoopLo)  → sw 71 (swRLoopHi)
        #   L loop:   sw 74 (swLLoopLo)  → sw 73 (swLLoopHi)
        # Loops fire lo first (ball entering from below) then hi
        # (ball reaching the top — registers as "made orbit").
        # Light all 4 Attack Wave awards (3 made shots each).  We do
        # NOT start the modes yet — starting all 4 modes triggers
        # Total Annihilation, which then dominates every subsequent
        # clip with the JACKPOT ticker.  Mode-start moments are
        # clustered at the END (just before TA + EOB).
        GameMoment(
            name="big_o_beam_light",
            description="3 made left-ramp shots light Big-O-Beam.",
            wait_before_ms=500,
            events=[
                _press(61, hold_ms=80, delay=350, note="L ramp #1 enter"),
                _press(64, hold_ms=80, delay=1200, note="L ramp #1 top (MADE)"),
                _press(61, hold_ms=80, delay=350, note="L ramp #2 enter"),
                _press(64, hold_ms=80, delay=1200, note="L ramp #2 top"),
                _press(61, hold_ms=80, delay=350, note="L ramp #3 enter"),
                _press(64, hold_ms=80, delay=1500, note="L ramp #3 top"),
            ],
        ),
        GameMoment(
            name="tractor_beam_light",
            description="3 made right-ramp shots light Tractor Beam.",
            wait_before_ms=500,
            events=[
                _press(63, hold_ms=80, delay=350, note="R ramp #1 enter"),
                _press(65, hold_ms=80, delay=1200, note="R ramp #1 exit (MADE)"),
                _press(63, hold_ms=80, delay=350),
                _press(65, hold_ms=80, delay=1200),
                _press(63, hold_ms=80, delay=350),
                _press(65, hold_ms=80, delay=1500),
            ],
        ),
        GameMoment(
            name="atomic_blaster_light",
            description="3 made right-loop shots light Atomic Blaster.",
            wait_before_ms=500,
            events=[
                _press(72, hold_ms=70, delay=300, note="R loop #1 lo (entry)"),
                _press(71, hold_ms=70, delay=1200, note="R loop #1 hi (MADE)"),
                _press(72, hold_ms=70, delay=300),
                _press(71, hold_ms=70, delay=1200),
                _press(72, hold_ms=70, delay=300),
                _press(71, hold_ms=70, delay=1500),
            ],
        ),
        GameMoment(
            name="capture_light",
            description="3 made left-loop shots light Capture.",
            wait_before_ms=500,
            events=[
                _press(74, hold_ms=70, delay=300, note="L loop #1 lo (entry)"),
                _press(73, hold_ms=70, delay=1200, note="L loop #1 hi (MADE)"),
                _press(74, hold_ms=70, delay=300),
                _press(73, hold_ms=70, delay=1200),
                _press(74, hold_ms=70, delay=300),
                _press(73, hold_ms=70, delay=1500),
            ],
        ),
        GameMoment(
            name="five_way_combo",
            description="5 made shots back-to-back = 5-WAY COMBO.",
            wait_before_ms=400,
            events=[
                _press(61, hold_ms=60, delay=150),
                _press(64, hold_ms=60, delay=250, note="L ramp"),
                _press(62, hold_ms=60, delay=400, note="C ramp"),
                _press(63, hold_ms=60, delay=150),
                _press(65, hold_ms=60, delay=250, note="R ramp"),
                _press(72, hold_ms=60, delay=150),
                _press(71, hold_ms=60, delay=250, note="R loop"),
                _press(74, hold_ms=60, delay=150),
                _press(73, hold_ms=60, delay=2500,
                       note="5-WAY COMBO cinematic"),
            ],
        ),
        GameMoment(
            name="martian_attack_letters",
            description="Hit all 7 Martian targets (M-A-R-T-I-A-N).",
            wait_before_ms=600,
            events=[
                _press(41, hold_ms=80, delay=300, note="M"),
                _press(42, hold_ms=80, delay=300, note="A"),
                _press(43, hold_ms=80, delay=300, note="R"),
                _press(44, hold_ms=80, delay=300, note="T"),
                _press(56, hold_ms=80, delay=300, note="I"),
                _press(57, hold_ms=80, delay=300, note="A"),
                _press(58, hold_ms=80, delay=2500, note="N"),
            ],
        ),
        GameMoment(
            name="stroke_of_luck",
            description="R-saucer mystery roulette cinematic.",
            wait_before_ms=400,
            events=[_press(76, hold_ms=120, delay=4500)],
        ),
        GameMoment(
            name="center_ramp_lock_progress",
            description="3 center-ramp shots light Lock at L-saucer.",
            wait_before_ms=400,
            events=[
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
            ],
        ),
        GameMoment(
            name="lock_1",
            description="L-saucer captures ball — LOCK 1 splash.",
            wait_before_ms=400,
            events=[_press(75, hold_ms=120, delay=3500)],
        ),
        GameMoment(
            name="lock_2",
            description="Repeat center ramp×3 + L-saucer → LOCK 2.",
            wait_before_ms=400,
            events=[
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
                _press(75, hold_ms=120, delay=3500),
            ],
        ),
        GameMoment(
            name="multiball_start",
            description="3rd lock kicks all balls — MULTIBALL splash.",
            wait_before_ms=400,
            events=[
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
                _press(62, hold_ms=80, delay=1500),
                _press(75, hold_ms=150, delay=5500),
            ],
        ),
        GameMoment(
            name="multiball_jackpot",
            description="R-ramp during multiball = JACKPOT splash.",
            wait_before_ms=400,
            events=[
                _press(63, hold_ms=80, delay=300),
                _press(65, hold_ms=80, delay=3500),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            description="Pop bumpers cluster — score animation.",
            wait_before_ms=300,
            events=[
                _press(53, hold_ms=50, delay=120),
                _press(54, hold_ms=50, delay=120),
                _press(55, hold_ms=50, delay=120),
                _press(53, hold_ms=50, delay=120),
                _press(54, hold_ms=50, delay=120),
                _press(55, hold_ms=50, delay=1500),
            ],
        ),
        GameMoment(
            name="drop_target",
            description="Drop-target hit — bonus award splash.",
            wait_before_ms=300,
            events=[_press(77, hold_ms=80, delay=2000)],
        ),
        # All four Attack Wave mode-start moments clustered at the
        # END of the script.  Why here and not after each ``*_light``?
        # Once all 4 modes have been started, AFM auto-triggers Total
        # Annihilation — and TA's JACKPOT-ticker DMD overrides every
        # subsequent clip's display.  By deferring all mode-starts
        # until after the lock / multiball / mystery / etc. moments
        # have already played, those earlier moments capture their
        # own distinct cinematics in normal gameplay.  Each mode_start
        # kills the previous mode and plays its own intro animation.
        GameMoment(
            name="big_o_beam_mode_start",
            description="Start Big-O-Beam mode (L-ramp).",
            wait_before_ms=400,
            events=[
                _press(61, hold_ms=80, delay=350),
                _press(64, hold_ms=80, delay=5500,
                       note="BIG-O-BEAM cinematic"),
            ],
        ),
        GameMoment(
            name="tractor_beam_mode_start",
            description="Start Tractor Beam mode (R-ramp).",
            wait_before_ms=400,
            events=[
                _press(63, hold_ms=80, delay=350),
                _press(65, hold_ms=80, delay=5500,
                       note="TRACTOR BEAM cinematic"),
            ],
        ),
        GameMoment(
            name="atomic_blaster_mode_start",
            description="Start Atomic Blaster mode (R-loop).",
            wait_before_ms=400,
            events=[
                _press(72, hold_ms=70, delay=300),
                _press(71, hold_ms=70, delay=5500,
                       note="ATOMIC BLASTER cinematic"),
            ],
        ),
        GameMoment(
            name="capture_mode_start",
            description="Start Capture mode (L-loop).",
            wait_before_ms=400,
            events=[
                _press(74, hold_ms=70, delay=300),
                _press(73, hold_ms=70, delay=5500,
                       note="CAPTURE cinematic"),
            ],
        ),
        # Total Annihilation: 4-ball wizard multiball that locks the
        # DMD into the JACKPOT-ticker display.  Auto-triggers after
        # the 4 mode-starts above; the explicit setup events here
        # collect a couple of TA jackpots for cinematic flair.
        GameMoment(
            name="total_annihilation_setup",
            description="All 4 modes → Total Annihilation wizard.",
            wait_before_ms=400,
            events=[
                _press(61, hold_ms=70, delay=300),
                _press(64, hold_ms=70, delay=600, note="L ramp made"),
                _press(63, hold_ms=70, delay=300),
                _press(65, hold_ms=70, delay=600, note="R ramp made"),
                _press(72, hold_ms=70, delay=300),
                _press(71, hold_ms=70, delay=600, note="R loop made"),
                _press(74, hold_ms=70, delay=300),
                _press(73, hold_ms=70, delay=6500,
                       note="TOTAL ANNIHILATION cinematic + jackpots"),
            ],
        ),
    ]


def _mm_moments(s: GameScript) -> List[GameMoment]:
    """Medieval Madness rule references (PinMAME mm.c):
        Castle: swCastleLock=44, gates 37/38
        Catapult: swCatapult=38
        Trolls: swLTrollTgt=15, swRTrollTgt=25, swLTrollUPF=45, swRTrollUPF=46
        L ramp: swEnterLRamp=61, swLRampMade=62 (Damsel)
        R ramp: swEnterRRamp=63, swRRampMade=64 (Joust)
        L loop: swLLoopHi=66, swLLoopLo=65
        R loop: swRLoopHi=68, swRLoopLo=67
        R bank drops: 71, 72, 73 (Peasant Targets)
        Jets: 53, 54, 55  Slings: 51, 52
    """
    return [
        GameMoment(
            name="skill_shot",
            events=[_press(s.sw_launch, hold_ms=180, delay=1500)],
        ),
        GameMoment(
            name="left_ramp_damsel",
            description="Left ramp = Damsel In Distress shot.",
            wait_before_ms=500,
            events=[
                _press(61, hold_ms=80, delay=300),
                _press(62, hold_ms=80, delay=2500, note="L ramp made"),
            ],
        ),
        GameMoment(
            name="damsel_in_distress_mode",
            description="3 left ramps → SAVE THE DAMSEL mode start.",
            wait_before_ms=400,
            events=[
                _press(61, hold_ms=80, delay=300),
                _press(62, hold_ms=80, delay=900),
                _press(61, hold_ms=80, delay=300),
                _press(62, hold_ms=80, delay=900),
                _press(61, hold_ms=80, delay=300),
                _press(62, hold_ms=80, delay=4000,
                       note="DAMSEL mode cinematic"),
            ],
        ),
        GameMoment(
            name="right_ramp_joust",
            description="Right ramp = Joust mode-light shot.",
            wait_before_ms=400,
            events=[
                _press(63, hold_ms=80, delay=300),
                _press(64, hold_ms=80, delay=2500, note="R ramp made"),
            ],
        ),
        GameMoment(
            name="joust_mode_start",
            description="3 right ramps → JOUST mode start.",
            wait_before_ms=400,
            events=[
                _press(63, hold_ms=80, delay=300),
                _press(64, hold_ms=80, delay=900),
                _press(63, hold_ms=80, delay=300),
                _press(64, hold_ms=80, delay=900),
                _press(63, hold_ms=80, delay=300),
                _press(64, hold_ms=80, delay=4000,
                       note="JOUST mode cinematic"),
            ],
        ),
        GameMoment(
            name="trolls",
            description="Whack the trolls — TROLL BASH.",
            wait_before_ms=400,
            events=[
                _press(15, hold_ms=80, delay=400, note="L troll target"),
                _press(45, hold_ms=80, delay=400, note="L troll UPF"),
                _press(25, hold_ms=80, delay=400, note="R troll target"),
                _press(46, hold_ms=80, delay=2000, note="R troll UPF"),
            ],
        ),
        GameMoment(
            name="peasant_targets",
            description="3-bank Peasant drop targets.",
            wait_before_ms=400,
            events=[
                _press(71, hold_ms=80, delay=250),
                _press(72, hold_ms=80, delay=250),
                _press(73, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="peasant_revolt_mode",
            description="Drop all 3 peasants twice → PEASANT REVOLT.",
            wait_before_ms=400,
            events=[
                _press(71, hold_ms=80, delay=200),
                _press(72, hold_ms=80, delay=200),
                _press(73, hold_ms=80, delay=800),
                _press(71, hold_ms=80, delay=200),
                _press(72, hold_ms=80, delay=200),
                _press(73, hold_ms=80, delay=4000,
                       note="PEASANT REVOLT cinematic"),
            ],
        ),
        GameMoment(
            name="troll_bash_mode",
            description="Whack 5+ trolls → TROLL BASH mode cinematic.",
            wait_before_ms=400,
            events=[
                _press(45, hold_ms=80, delay=300),
                _press(46, hold_ms=80, delay=300),
                _press(45, hold_ms=80, delay=300),
                _press(46, hold_ms=80, delay=300),
                _press(45, hold_ms=80, delay=4000,
                       note="TROLL BASH cinematic"),
            ],
        ),
        GameMoment(
            name="castle_gate",
            description="Castle Gate shot — knock down the castle.",
            wait_before_ms=400,
            events=[
                _press(37, hold_ms=80, delay=400, note="Castle gate"),
                _press(44, hold_ms=120, delay=3000, note="Castle lock"),
            ],
        ),
        GameMoment(
            name="merlins_magic",
            description="Catapult x3 with castle up = MERLIN'S MAGIC.",
            wait_before_ms=400,
            events=[
                _press(38, hold_ms=80, delay=600, note="catapult #1"),
                _press(38, hold_ms=80, delay=600, note="catapult #2"),
                _press(38, hold_ms=80, delay=3500,
                       note="MERLIN'S MAGIC cinematic"),
            ],
        ),
        GameMoment(
            name="castle_multiball",
            description="Castle Multiball after lock saturation.",
            wait_before_ms=400,
            events=[
                _press(37, hold_ms=80, delay=400),
                _press(44, hold_ms=150, delay=5000,
                       note="MULTIBALL splash"),
            ],
        ),
        GameMoment(
            name="royal_madness_setup",
            description="All castles destroyed → ROYAL MADNESS wizard.",
            wait_before_ms=400,
            events=[
                # Pretend we've smashed all six castles by hitting
                # the castle lock repeatedly with delays.
                _press(44, hold_ms=120, delay=800),
                _press(37, hold_ms=80, delay=400),
                _press(44, hold_ms=120, delay=800),
                _press(37, hold_ms=80, delay=400),
                _press(44, hold_ms=150, delay=5500,
                       note="ROYAL MADNESS / wizard cinematic"),
            ],
        ),
        GameMoment(
            name="catapult",
            description="Catapult hit — knock castle wall.",
            wait_before_ms=300,
            events=[_press(38, hold_ms=80, delay=2000)],
        ),
        GameMoment(
            name="left_loop",
            wait_before_ms=300,
            events=[
                _press(66, hold_ms=70, delay=200),
                _press(65, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="right_loop",
            wait_before_ms=300,
            events=[
                _press(68, hold_ms=70, delay=200),
                _press(67, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            wait_before_ms=300,
            events=[
                _press(53, hold_ms=50, delay=120),
                _press(54, hold_ms=50, delay=120),
                _press(55, hold_ms=50, delay=120),
                _press(53, hold_ms=50, delay=120),
                _press(54, hold_ms=50, delay=120),
                _press(55, hold_ms=50, delay=1500),
            ],
        ),
    ]


def _tom_moments(s: GameScript) -> List[GameMoment]:
    """Theatre of Magic rule references (PinMAME tom.c):
        Shooter: 15
        Locks at trunk: swLock1=41, swLock2=42, swLock3=43
        Vanish locks: swVanishLock1=83, swVanishLock2=84
        Trunk: swTrunkHit=85
        Center ramp: swCRampEnter=75, swCRampExit=71
        Right ramp: swRRampEnter=76, swRRampExit=73
        Left lane: swLLaneEnter=54
        Right lane: swRLaneEnter=53
        L loop: swLLoop=78  R loop: swRLoop=81
        Cube positions: 55, 56, 57, 58 (4-position cube)
        Captive ball: swCapTop=77
        Sub: swSubwayOpto=36
        Drains: swLDrain=45, swRDrain=48
        Jets: 63, 64, 65
    """
    return [
        GameMoment(
            name="skill_shot",
            description="Plunger — ToM has no auto-launch button.",
            events=[_wait(2500, note="skill-shot window")],
        ),
        GameMoment(
            name="center_ramp_magic",
            description="Center ramp = magic mode-progress shot.",
            wait_before_ms=400,
            events=[
                _press(75, hold_ms=80, delay=300, note="C ramp enter"),
                _press(71, hold_ms=80, delay=2500, note="C ramp exit"),
            ],
        ),
        GameMoment(
            name="right_ramp",
            wait_before_ms=400,
            events=[
                _press(76, hold_ms=80, delay=300),
                _press(73, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="trunk_lock",
            description="Trunk hit / lock 1 — illusion progression.",
            wait_before_ms=400,
            events=[
                _press(85, hold_ms=80, delay=400, note="Trunk hit"),
                _press(41, hold_ms=120, delay=3000, note="Lock 1"),
            ],
        ),
        GameMoment(
            name="lock_2",
            wait_before_ms=400,
            events=[
                _press(85, hold_ms=80, delay=400),
                _press(42, hold_ms=120, delay=3000),
            ],
        ),
        GameMoment(
            name="theatre_multiball",
            description="3rd lock = Theatre Multiball.",
            wait_before_ms=400,
            events=[
                _press(85, hold_ms=80, delay=400),
                _press(43, hold_ms=150, delay=5000),
            ],
        ),
        GameMoment(
            name="illusion_hat_trick",
            description="HAT TRICK illusion mode — multiple trunk + ramp hits.",
            wait_before_ms=400,
            events=[
                _press(85, hold_ms=80, delay=400, note="trunk"),
                _press(75, hold_ms=80, delay=300, note="C ramp enter"),
                _press(71, hold_ms=80, delay=4000,
                       note="HAT TRICK cinematic"),
            ],
        ),
        GameMoment(
            name="illusion_magic_mirror",
            description="MAGIC MIRROR illusion — vanish locks hit.",
            wait_before_ms=400,
            events=[
                _press(83, hold_ms=100, delay=400),
                _press(84, hold_ms=100, delay=4000,
                       note="MAGIC MIRROR cinematic"),
            ],
        ),
        GameMoment(
            name="cube_rotation",
            description="Magic cube rotates through 4 positions.",
            wait_before_ms=400,
            events=[
                _press(56, hold_ms=80, delay=400, note="cube pos 1"),
                _press(57, hold_ms=80, delay=400, note="cube pos 2"),
                _press(58, hold_ms=80, delay=400, note="cube pos 3"),
                _press(55, hold_ms=80, delay=2500, note="cube pos 4"),
            ],
        ),
        GameMoment(
            name="grand_finale_setup",
            description="All illusions complete → GRAND FINALE wizard.",
            wait_before_ms=400,
            events=[
                _press(85, hold_ms=80, delay=400),
                _press(85, hold_ms=80, delay=400),
                _press(43, hold_ms=120, delay=5500,
                       note="GRAND FINALE cinematic"),
            ],
        ),
        GameMoment(
            name="vanish",
            description="Vanish trick lock cinematic.",
            wait_before_ms=400,
            events=[
                _press(83, hold_ms=120, delay=300),
                _press(84, hold_ms=120, delay=3000),
            ],
        ),
        GameMoment(
            name="captive_ball",
            description="Captive ball hit.",
            wait_before_ms=300,
            events=[_press(77, hold_ms=80, delay=2000)],
        ),
        GameMoment(
            name="loops",
            wait_before_ms=300,
            events=[
                _press(78, hold_ms=70, delay=1500),
                _press(81, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            wait_before_ms=300,
            events=[
                _press(63, hold_ms=50, delay=120),
                _press(64, hold_ms=50, delay=120),
                _press(65, hold_ms=50, delay=120),
                _press(63, hold_ms=50, delay=120),
                _press(64, hold_ms=50, delay=120),
                _press(65, hold_ms=50, delay=1500),
            ],
        ),
    ]


def _ft_moments(s: GameScript) -> List[GameMoment]:
    """Fish Tales (PinMAME ft.c).  Older WPC — no auto-launch button.
        L boat ramp: enter 43, exit 32  (Catch a Fish)
        R boat ramp: enter 42, exit 33
        Captive: swCaptiveBall=41
        Top eject: swTopEject=63
        L drop targets: swLDT1=27, swLDT2=28
        R drop targets: swRDT1=54, swRDT2=55
        L-I-E spell: swLIE_L=46, swLIE_I=45, swLIE_E=44 (LIE lanes)
        Spinner: swSpinner=34
        Cast: swCast=31  Catapult: swCatapult=36
        Reels: swReel1Opto=37, swReel2Opto=38, swReelEntry=35
        Ball popper: swBallPopper=47
        Drop target: swDropTarget=48
        Jets: 51, 52, 53
        Loops: swTLLoop=64, swTRLoop=62
        Extra Ball: swExtraBall=61
    """
    return [
        GameMoment(
            name="skill_shot",
            events=[_wait(2500, note="skill-shot window (manual plunger)")],
        ),
        GameMoment(
            name="left_boat_ramp",
            description="Catch a Fish — left ramp.",
            wait_before_ms=400,
            events=[
                _press(43, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="right_boat_ramp",
            description="Right boat ramp.",
            wait_before_ms=400,
            events=[
                _press(42, hold_ms=80, delay=300),
                _press(33, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="lie_lanes",
            description="Spell L-I-E in the top lanes.",
            wait_before_ms=400,
            events=[
                _press(46, hold_ms=70, delay=250),
                _press(45, hold_ms=70, delay=250),
                _press(44, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="spinner",
            description="Spinner shot.",
            wait_before_ms=300,
            events=[_press(34, hold_ms=80, delay=2000)],
        ),
        GameMoment(
            name="captive_ball",
            wait_before_ms=300,
            events=[_press(41, hold_ms=80, delay=2000)],
        ),
        GameMoment(
            name="drop_targets",
            wait_before_ms=300,
            events=[
                _press(27, hold_ms=70, delay=250),
                _press(28, hold_ms=70, delay=250),
                _press(54, hold_ms=70, delay=250),
                _press(55, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="ball_popper",
            description="Multiball lock — Ball Popper hole.",
            wait_before_ms=300,
            events=[_press(47, hold_ms=120, delay=3500)],
        ),
        GameMoment(
            name="catch_a_fish",
            description="Both boat ramps + popper = CATCH A FISH mode.",
            wait_before_ms=400,
            events=[
                _press(43, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=600),
                _press(42, hold_ms=80, delay=300),
                _press(33, hold_ms=80, delay=600),
                _press(47, hold_ms=120, delay=4500,
                       note="CATCH A FISH cinematic"),
            ],
        ),
        GameMoment(
            name="fish_finder_multiball",
            description="Lock 3 fish + popper = FISH FINDER MULTIBALL.",
            wait_before_ms=400,
            events=[
                _press(43, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=900, note="L boat lock #1"),
                _press(43, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=900, note="L boat lock #2"),
                _press(43, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=400),
                _press(47, hold_ms=120, delay=5500,
                       note="MULTIBALL START cinematic"),
            ],
        ),
        GameMoment(
            name="extra_ball_lit",
            description="Hit Extra Ball target sw#61.",
            wait_before_ms=300,
            events=[_press(61, hold_ms=80, delay=4000,
                           note="EXTRA BALL animation")],
        ),
        GameMoment(
            name="loops",
            wait_before_ms=300,
            events=[
                _press(62, hold_ms=70, delay=1500),
                _press(64, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            wait_before_ms=300,
            events=[
                _press(51, hold_ms=50, delay=120),
                _press(52, hold_ms=50, delay=120),
                _press(53, hold_ms=50, delay=120),
                _press(51, hold_ms=50, delay=120),
                _press(52, hold_ms=50, delay=120),
                _press(53, hold_ms=50, delay=1500),
            ],
        ),
    ]


def _ww_moments(s: GameScript) -> List[GameMoment]:
    """White Water (PinMAME ww.c).  3-ball trough at 76/77/78.
        Bigfoot: swBigFoot1=86, swBigFoot2=87, swBigFootCave=58
        Whirlpool: swWpoolPopper=61, swWpoolMade=62
        D-Drop: swDDropMade=75, swEnterDDrop=68
        L ramp: swEnterLRamp=46, swLRampMade=66
        Rapids: swEnterRapids=47, swRapidsMade=71
        Canyon: swEnterCanyon=48, swCanyonMade=57
        Secret passage: swSecretPassage=45
        Lockup posts: swLockupL=65, swLockupC=64, swLockupR=63
        Light: swLite=41  Lock: swLock=42
        Hot Foot: swUHotFoot=73, swLHotFoot=74
        L/R loops: swLeftLoop=43, swRightLoop=44
        riveR letters: swR=35, swr=34, swrI=33, swriV=32, swrivE=31
        3-bank: sw3BankT=36, sw3BankM=37, sw3BankB=38
        Jets: 16/17/18, slings 51/52
    """
    return [
        GameMoment(
            name="skill_shot",
            events=[_wait(2500, note="skill shot window")],
        ),
        GameMoment(
            name="river_letters",
            description="Spell R-I-V-E-R in the river lanes.",
            wait_before_ms=400,
            events=[
                _press(35, hold_ms=80, delay=300),
                _press(34, hold_ms=80, delay=300),
                _press(33, hold_ms=80, delay=300),
                _press(32, hold_ms=80, delay=300),
                _press(31, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="left_ramp",
            wait_before_ms=400,
            events=[
                _press(46, hold_ms=80, delay=300),
                _press(66, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="rapids_ramp",
            description="Rapids ramp = mode advance.",
            wait_before_ms=400,
            events=[
                _press(47, hold_ms=80, delay=300),
                _press(71, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="canyon_ramp",
            wait_before_ms=400,
            events=[
                _press(48, hold_ms=80, delay=300),
                _press(57, hold_ms=80, delay=2500),
            ],
        ),
        GameMoment(
            name="whirlpool",
            description="Whirlpool — multiball lock progress.",
            wait_before_ms=400,
            events=[
                _press(62, hold_ms=80, delay=400),
                _press(61, hold_ms=120, delay=3500),
            ],
        ),
        GameMoment(
            name="bigfoot_cave",
            description="Bigfoot Cave — Bigfoot Multiball.",
            wait_before_ms=400,
            events=[
                _press(58, hold_ms=120, delay=400),
                _press(86, hold_ms=80, delay=300),
                _press(87, hold_ms=80, delay=4000),
            ],
        ),
        GameMoment(
            name="disaster_drop",
            description="D-Drop = Disaster Drop hurry-up.",
            wait_before_ms=400,
            events=[
                _press(68, hold_ms=80, delay=400),
                _press(75, hold_ms=120, delay=3000),
            ],
        ),
        GameMoment(
            name="insanity_falls",
            description="Hard ramp + cycle = INSANITY FALLS mode.",
            wait_before_ms=400,
            events=[
                _press(46, hold_ms=80, delay=300),
                _press(66, hold_ms=80, delay=600),
                _press(47, hold_ms=80, delay=300),
                _press(71, hold_ms=80, delay=600),
                _press(48, hold_ms=80, delay=4500,
                       note="INSANITY FALLS cinematic"),
            ],
        ),
        GameMoment(
            name="lite_a_river_complete",
            description="Spell R-I-V-E-R fully + bonus = RIVER ANIM.",
            wait_before_ms=400,
            events=[
                _press(41, hold_ms=80, delay=300, note="Lite"),
                _press(35, hold_ms=80, delay=300, note="r"),
                _press(34, hold_ms=80, delay=300, note="i"),
                _press(33, hold_ms=80, delay=300, note="v"),
                _press(32, hold_ms=80, delay=300, note="e"),
                _press(31, hold_ms=80, delay=4000,
                       note="RIVER REWARD cinematic"),
            ],
        ),
        GameMoment(
            name="bigfoot_attack",
            description="Hit Bigfoot Cave + targets = BIGFOOT animation.",
            wait_before_ms=400,
            events=[
                _press(58, hold_ms=100, delay=400),
                _press(86, hold_ms=80, delay=300),
                _press(87, hold_ms=80, delay=400),
                _press(86, hold_ms=80, delay=300),
                _press(87, hold_ms=80, delay=4500,
                       note="BIGFOOT MULTIBALL cinematic"),
            ],
        ),
        GameMoment(
            name="wet_willie_mode",
            description="Secret passage hits = WET WILLIE.",
            wait_before_ms=400,
            events=[
                _press(45, hold_ms=80, delay=400),
                _press(45, hold_ms=80, delay=400),
                _press(45, hold_ms=80, delay=4000,
                       note="WET WILLIE cinematic"),
            ],
        ),
        GameMoment(
            name="secret_passage",
            wait_before_ms=300,
            events=[_press(45, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="3bank",
            description="3-bank top targets.",
            wait_before_ms=300,
            events=[
                _press(36, hold_ms=70, delay=250),
                _press(37, hold_ms=70, delay=250),
                _press(38, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="loops",
            wait_before_ms=300,
            events=[
                _press(43, hold_ms=70, delay=1500),
                _press(44, hold_ms=70, delay=2000),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            wait_before_ms=300,
            events=[
                _press(16, hold_ms=50, delay=120),
                _press(17, hold_ms=50, delay=120),
                _press(18, hold_ms=50, delay=120),
                _press(16, hold_ms=50, delay=120),
                _press(17, hold_ms=50, delay=120),
                _press(18, hold_ms=50, delay=1500),
            ],
        ),
    ]


def _tz_moments(s: GameScript) -> List[GameMoment]:
    """Twilight Zone (PinMAME tz.c).  Loaded with cinematic moments.
        Clock: swClockM=47  (clock millions)
        Piano: swPiano=43
        Camera: swCamera=42
        Dead End: swDeadEnd=41
        Slot Machine: swSlot=58
        Gumball: swGumLane=51, swGumEnter=87, swGumExit=56, swGumPop=74
        Rocket: swRocket=28
        Power: swPowerPay=65
        Hitch Hiker: swHitchH=52
        L ramp: swLRampEnt=53, swLRamp=54
        R ramp: swRRampEnt=73
        Geneva (clock): swGeneva=55
        Greed targets: 48, 64, 66, 67, 68, 77, 78
        Skill targets: swSkillR=61, swSkillO=62, swSkillY=63
        Lock: swLLock=88, swCLock=84, swULock=85
        MPF (mini-playfield): 44/45/46, 75 (top), 76 (exit)
        Magnets: 81/82/83
        BigKick: swBigKick=71
        AutoFire: swAutoFire=72
        Jets: 31/32/33  Slings: 34/35
    """
    return [
        GameMoment(
            name="skill_shot",
            description="Spell R-O-Y skill-shot lanes.",
            events=[
                _wait(2000, note="skill shot window"),
                _press(61, hold_ms=70, delay=300, note="R"),
                _press(62, hold_ms=70, delay=300, note="O"),
                _press(63, hold_ms=70, delay=2000, note="Y"),
            ],
        ),
        GameMoment(
            name="piano",
            description="Piano shot — sets up jackpot.",
            wait_before_ms=400,
            events=[_press(43, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="camera",
            description="Camera shot — collect awards.",
            wait_before_ms=400,
            events=[_press(42, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="dead_end",
            wait_before_ms=400,
            events=[_press(41, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="left_ramp",
            wait_before_ms=300,
            events=[
                _press(53, hold_ms=80, delay=300),
                _press(54, hold_ms=80, delay=2000),
            ],
        ),
        GameMoment(
            name="right_ramp",
            wait_before_ms=300,
            events=[_press(73, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="clock_millions",
            description="Clock target — clock millions hurry-up.",
            wait_before_ms=400,
            events=[
                _press(47, hold_ms=80, delay=400),
                _press(55, hold_ms=80, delay=2500, note="Geneva"),
            ],
        ),
        GameMoment(
            name="slot_machine",
            description="Slot machine cinematic — random award.",
            wait_before_ms=400,
            events=[_press(58, hold_ms=120, delay=4500)],
        ),
        GameMoment(
            name="gumball",
            description="Gumball machine multiball setup.",
            wait_before_ms=400,
            events=[
                _press(51, hold_ms=80, delay=300, note="Gum lane"),
                _press(87, hold_ms=80, delay=2500, note="Gum enter"),
            ],
        ),
        GameMoment(
            name="power_payoff",
            wait_before_ms=400,
            events=[_press(65, hold_ms=80, delay=2500)],
        ),
        GameMoment(
            name="hitch_hiker",
            wait_before_ms=300,
            events=[_press(52, hold_ms=80, delay=2000)],
        ),
        GameMoment(
            name="mini_playfield",
            description="Mini-playfield activated.",
            wait_before_ms=400,
            events=[
                _press(44, hold_ms=80, delay=300, note="MPF enter"),
                _press(75, hold_ms=80, delay=300, note="MPF top"),
                _press(76, hold_ms=80, delay=2500, note="MPF exit"),
            ],
        ),
        GameMoment(
            name="multiball_locks",
            description="Lock 3 balls for multiball.",
            wait_before_ms=400,
            events=[
                _press(88, hold_ms=120, delay=2000, note="L Lock"),
                _press(84, hold_ms=120, delay=2000, note="C Lock"),
                _press(85, hold_ms=120, delay=4500, note="U Lock"),
            ],
        ),
        GameMoment(
            name="greed_mode",
            description="Hit all Greed targets = GREED mode.",
            wait_before_ms=400,
            events=[
                _press(48, hold_ms=70, delay=250, note="Greed 1"),
                _press(64, hold_ms=70, delay=250, note="Greed 4"),
                _press(65, hold_ms=70, delay=250, note="PowerPay"),
                _press(66, hold_ms=70, delay=250, note="Greed 5"),
                _press(67, hold_ms=70, delay=4000,
                       note="GREED cinematic"),
            ],
        ),
        GameMoment(
            name="lost_in_zone_setup",
            description="All 4 modes started → LOST IN THE ZONE wizard.",
            wait_before_ms=400,
            events=[
                _press(47, hold_ms=80, delay=400, note="Clock M"),
                _press(43, hold_ms=80, delay=400, note="Piano"),
                _press(42, hold_ms=80, delay=400, note="Camera"),
                _press(58, hold_ms=120, delay=5500,
                       note="LITZ wizard cinematic"),
            ],
        ),
        GameMoment(
            name="town_square_madness",
            description="Spell TOWN via skill lanes — TSM mode.",
            wait_before_ms=400,
            events=[
                _press(61, hold_ms=70, delay=300),
                _press(62, hold_ms=70, delay=300),
                _press(63, hold_ms=70, delay=300),
                _press(47, hold_ms=80, delay=4000,
                       note="TOWN SQUARE MADNESS cinematic"),
            ],
        ),
        GameMoment(
            name="jet_bumpers",
            wait_before_ms=300,
            events=[
                _press(31, hold_ms=50, delay=120),
                _press(32, hold_ms=50, delay=120),
                _press(33, hold_ms=50, delay=120),
                _press(31, hold_ms=50, delay=120),
                _press(32, hold_ms=50, delay=120),
                _press(33, hold_ms=50, delay=1500),
            ],
        ),
    ]


def _taf_moments(s: GameScript) -> List[GameMoment]:
    """Addams Family (PinMAME taf.c) — best-selling pinball ever.
    Switch map: L ramp 61/66, R ramp 64/65, train 62, chair 43,
    swamp 45/47/48, graves 41/42, vault 68 (multiball lock),
    mansion locks U/C/L 71/72/73, BOOK targets 53-56, jets 31-35.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   description="3 made L-ramp shots.",
                   events=[_press(61, 80, 300), _press(66, 80, 1300),
                           _press(61, 80, 300), _press(66, 80, 1300),
                           _press(61, 80, 300), _press(66, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(64, 80, 300), _press(65, 80, 1300),
                           _press(64, 80, 300), _press(65, 80, 1300),
                           _press(64, 80, 300), _press(65, 80, 1500)]),
        GameMoment(name="bookcase_letters", wait_before_ms=400,
                   description="Spell B-O-O-K on the target bank.",
                   events=[_press(53, 80, 300), _press(54, 80, 300),
                           _press(55, 80, 300), _press(56, 80, 3000,
                           note="BOOKCASE OPEN cinematic")]),
        GameMoment(name="chair_thing", wait_before_ms=400,
                   description="Chair target — Thing's hand reaches.",
                   events=[_press(43, 100, 3500)]),
        GameMoment(name="swamp_targets", wait_before_ms=400,
                   events=[_press(45, 80, 400), _press(47, 80, 400),
                           _press(48, 80, 3000)]),
        GameMoment(name="train_chase", wait_before_ms=400,
                   description="Train shot — chase cinematic.",
                   events=[_press(62, 100, 4500)]),
        GameMoment(name="graveyard", wait_before_ms=400,
                   events=[_press(41, 80, 400), _press(42, 80, 2500)]),
        GameMoment(name="vault_lock_1", wait_before_ms=400,
                   description="Vault saucer = LOCK 1.",
                   events=[_press(68, 120, 3500)]),
        GameMoment(name="vault_multiball", wait_before_ms=400,
                   description="2 more vaults → THING MULTIBALL.",
                   events=[_press(68, 120, 3000),
                           _press(68, 150, 5500,
                                  note="THING MULTIBALL cinematic")]),
        GameMoment(name="mansion_locks", wait_before_ms=400,
                   description="Locks U / C / L (tour the mansion).",
                   events=[_press(71, 120, 2500), _press(72, 120, 2500),
                           _press(73, 120, 3000)]),
        GameMoment(name="jets_mamushka", wait_before_ms=300,
                   description="Jets — Mamushka dance.",
                   events=[_press(31, 50, 100), _press(32, 50, 100),
                           _press(33, 50, 100), _press(34, 50, 100),
                           _press(35, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(61, 80, 300), _press(66, 80, 5000,
                           note="L-ramp mode cinematic")]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(64, 80, 300), _press(65, 80, 5000,
                           note="R-ramp mode cinematic")]),
    ]


def _sttng_moments(s: GameScript) -> List[GameMoment]:
    """Star Trek: The Next Generation (PinMAME sttng.c).
    Borg cube lock at 31, upper-left locks 35/41/42/43, outer loops
    44/58, ramps L 88/83, R 25/87, C ramp exit 23, Borg entry/hole
    47/48, drop target 57, jets 71-73.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(88, 80, 300), _press(83, 80, 1300),
                           _press(88, 80, 300), _press(83, 80, 1300),
                           _press(88, 80, 300), _press(83, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(25, 80, 300), _press(87, 80, 1300),
                           _press(25, 80, 300), _press(87, 80, 1300),
                           _press(25, 80, 300), _press(87, 80, 1500)]),
        GameMoment(name="left_outer_loop", wait_before_ms=400,
                   events=[_press(44, 70, 1500),
                           _press(44, 70, 1500),
                           _press(44, 70, 2000)]),
        GameMoment(name="right_outer_loop", wait_before_ms=400,
                   events=[_press(58, 70, 1500),
                           _press(58, 70, 1500),
                           _press(58, 70, 2000)]),
        GameMoment(name="borg_lock_1", wait_before_ms=400,
                   description="Borg cube lock 1.",
                   events=[_press(48, 80, 400),
                           _press(31, 120, 3500,
                                  note="LOCK 1 splash")]),
        GameMoment(name="borg_locks_multiball", wait_before_ms=400,
                   description="2 more Borg locks → BORG MULTIBALL.",
                   events=[_press(31, 120, 2500),
                           _press(31, 150, 5500,
                                  note="BORG MULTIBALL cinematic")]),
        GameMoment(name="ul_locks", wait_before_ms=400,
                   description="Upper-left ball locks.",
                   events=[_press(41, 120, 2500), _press(35, 120, 2500),
                           _press(42, 120, 2500), _press(43, 120, 3000)]),
        GameMoment(name="borg_hole", wait_before_ms=400,
                   description="Upper Borg hole shot.",
                   events=[_press(47, 100, 4000)]),
        GameMoment(name="drop_target", wait_before_ms=300,
                   events=[_press(57, 80, 2500)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(71, 50, 100), _press(72, 50, 100),
                           _press(73, 50, 100), _press(71, 50, 100),
                           _press(72, 50, 100), _press(73, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(88, 80, 300), _press(83, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(25, 80, 300), _press(87, 80, 5000)]),
    ]


def _ij_moments(s: GameScript) -> List[GameMoment]:
    """Indiana Jones (PinMAME ij.c).
    L ramp 41/118 (sw#118 unusual — extended matrix), R ramp 42/74,
    idol 43 enter / 32 exit, loops 54/55 (L T/B), 56/57 (R T/B),
    R popper 44, jets 35/36/37, slings 33/48.  IJ has a tiered
    upper playfield with the idol and loops.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(41, 80, 300), _press(118, 80, 1300),
                           _press(41, 80, 300), _press(118, 80, 1300),
                           _press(41, 80, 300), _press(118, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(42, 80, 300), _press(74, 80, 1300),
                           _press(42, 80, 300), _press(74, 80, 1300),
                           _press(42, 80, 300), _press(74, 80, 1500)]),
        GameMoment(name="left_loop", wait_before_ms=400,
                   events=[_press(55, 70, 300), _press(54, 70, 1300),
                           _press(55, 70, 300), _press(54, 70, 1300),
                           _press(55, 70, 300), _press(54, 70, 1500)]),
        GameMoment(name="right_loop", wait_before_ms=400,
                   events=[_press(57, 70, 300), _press(56, 70, 1300),
                           _press(57, 70, 300), _press(56, 70, 1500)]),
        GameMoment(name="idol_shot", wait_before_ms=400,
                   description="Idol shot — chase the idol cinematic.",
                   events=[_press(43, 80, 400),
                           _press(32, 80, 4000,
                                  note="IDOL CHASE cinematic")]),
        GameMoment(name="r_popper_mb", wait_before_ms=400,
                   description="Right popper — multiball setup.",
                   events=[_press(44, 120, 2500),
                           _press(44, 120, 5000,
                                  note="multiball splash")]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(35, 50, 100), _press(36, 50, 100),
                           _press(37, 50, 100), _press(35, 50, 100),
                           _press(36, 50, 100), _press(37, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(41, 80, 300), _press(118, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(42, 80, 300), _press(74, 80, 5000)]),
    ]


def _jd_moments(s: GameScript) -> List[GameMoment]:
    """Judge Dredd (PinMAME jd.c).
    L ramp 67/64 (also 63=LRampToLock for the lock kicker),
    C ramp exit 66, R ramp 75/76, S loop center 35, L popper 73,
    R popper 74, target 27, slings 51/52.  JD has the iconic
    Crimescenes / Pursuit / Manhunt modes.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(67, 80, 300), _press(64, 80, 1300),
                           _press(67, 80, 300), _press(64, 80, 1300),
                           _press(67, 80, 300), _press(64, 80, 1500)]),
        GameMoment(name="center_ramp", wait_before_ms=400,
                   events=[_press(66, 80, 2000),
                           _press(66, 80, 2000)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(75, 80, 1300),
                           _press(76, 80, 1300),
                           _press(75, 80, 1300),
                           _press(76, 80, 1500)]),
        GameMoment(name="s_loop", wait_before_ms=400,
                   events=[_press(35, 80, 1500), _press(35, 80, 2000)]),
        GameMoment(name="l_ramp_lock", wait_before_ms=400,
                   description="L ramp to lock kicker — LOCK 1.",
                   events=[_press(67, 80, 300),
                           _press(63, 120, 3500,
                                  note="LOCK 1 splash")]),
        GameMoment(name="multiball", wait_before_ms=400,
                   description="Successive locks → MULTIBALL.",
                   events=[_press(67, 80, 300), _press(63, 120, 2500),
                           _press(67, 80, 300),
                           _press(63, 150, 5500,
                                  note="MULTIBALL cinematic")]),
        GameMoment(name="poppers", wait_before_ms=400,
                   description="L + R poppers (mode targets).",
                   events=[_press(73, 120, 3000),
                           _press(74, 120, 3000)]),
        GameMoment(name="lltarget", wait_before_ms=300,
                   events=[_press(27, 80, 2500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(67, 80, 300), _press(64, 80, 5000,
                           note="L-ramp mode cinematic")]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(75, 80, 300), _press(76, 80, 5000)]),
    ]


def _ngg_moments(s: GameScript) -> List[GameMoment]:
    """No Good Gofers (PinMAME ngg.c).
    L ramp made 12, C ramp 15, R ramp 73, ramp downs 47/48,
    L spinner 61, R spinner 62, jets 53/54/55, R popper 46, jet
    popper 38, golf cart 74, sand trap 78, captive 86.  Iconic:
    Bud + Buzz gophers popping up out of holes.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(12, 80, 1500), _press(12, 80, 1500),
                           _press(12, 80, 1500)]),
        GameMoment(name="center_ramp_light", wait_before_ms=400,
                   events=[_press(15, 80, 1500), _press(15, 80, 1500),
                           _press(15, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(73, 80, 1500), _press(73, 80, 1500),
                           _press(73, 80, 1500)]),
        GameMoment(name="left_spinner", wait_before_ms=400,
                   events=[_press(61, 60, 100), _press(61, 60, 100),
                           _press(61, 60, 100), _press(61, 60, 2000)]),
        GameMoment(name="right_spinner", wait_before_ms=400,
                   events=[_press(62, 60, 100), _press(62, 60, 100),
                           _press(62, 60, 100), _press(62, 60, 2000)]),
        GameMoment(name="golf_cart", wait_before_ms=400,
                   description="Golf cart shot — Bud/Buzz cinematic.",
                   events=[_press(74, 120, 3500)]),
        GameMoment(name="sand_trap", wait_before_ms=400,
                   events=[_press(78, 120, 3000)]),
        GameMoment(name="r_popper_lock", wait_before_ms=400,
                   description="R popper = lock for multiball.",
                   events=[_press(46, 120, 2500),
                           _press(46, 120, 5500,
                                  note="multiball cinematic")]),
        GameMoment(name="captive_ball", wait_before_ms=300,
                   events=[_press(86, 100, 2500)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(53, 50, 100), _press(54, 50, 100),
                           _press(55, 50, 100), _press(53, 50, 100),
                           _press(54, 50, 100), _press(55, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(12, 80, 5500)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(73, 80, 5500)]),
    ]


def _t2_moments(s: GameScript) -> List[GameMoment]:
    """Terminator 2: Judgment Day (PinMAME t2.c).
    L ramp 61/62, R ramp 63/64, loops L 65, H 66, locks L 51, T 55,
    ball popper 76, drop target 77, 5-target bank 71-75, jets 41/42/43,
    slings 44/45.  Iconic: Skull Multiball, Hurry-Up, Video Mode.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(61, 80, 300), _press(62, 80, 1300),
                           _press(61, 80, 300), _press(62, 80, 1300),
                           _press(61, 80, 300), _press(62, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(63, 80, 300), _press(64, 80, 1300),
                           _press(63, 80, 300), _press(64, 80, 1300),
                           _press(63, 80, 300), _press(64, 80, 1500)]),
        GameMoment(name="loops", wait_before_ms=400,
                   events=[_press(65, 70, 1500), _press(66, 70, 1500),
                           _press(65, 70, 1500), _press(66, 70, 2000)]),
        GameMoment(name="target_bank", wait_before_ms=400,
                   description="5-target T-2 letters.",
                   events=[_press(71, 80, 300), _press(72, 80, 300),
                           _press(73, 80, 300), _press(74, 80, 300),
                           _press(75, 80, 3000)]),
        GameMoment(name="ball_popper", wait_before_ms=400,
                   events=[_press(76, 120, 2500),
                           _press(76, 120, 4000,
                                  note="multiball cinematic")]),
        GameMoment(name="skull_locks", wait_before_ms=400,
                   description="Skull-lock left + top.",
                   events=[_press(51, 120, 2500), _press(55, 120, 3500)]),
        GameMoment(name="drop_target", wait_before_ms=300,
                   events=[_press(77, 80, 2500)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(41, 50, 100), _press(42, 50, 100),
                           _press(43, 50, 100), _press(41, 50, 100),
                           _press(42, 50, 100), _press(43, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(61, 80, 300), _press(62, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(63, 80, 300), _press(64, 80, 5000)]),
    ]


def _dm_moments(s: GameScript) -> List[GameMoment]:
    """Demolition Man (PinMAME dm.c).
    L ramp 51/52, R ramp 46/47, C ramp 53, S(uper) ramp 61/62,
    loops left 86 / center 55 / right 48, car chase 71/72/87,
    top popper 73, bottom popper 76, elevator 67/74/75, claw 82,
    slings 41/42, top sling 44, jets 43/45.  Iconic: Cryoclaw,
    Car Chase, Demolition Time wizard mode.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(51, 80, 300), _press(52, 80, 1300),
                           _press(51, 80, 300), _press(52, 80, 1300),
                           _press(51, 80, 300), _press(52, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(46, 80, 300), _press(47, 80, 1300),
                           _press(46, 80, 300), _press(47, 80, 1300),
                           _press(46, 80, 300), _press(47, 80, 1500)]),
        GameMoment(name="center_ramp", wait_before_ms=400,
                   events=[_press(53, 80, 1500), _press(53, 80, 2000)]),
        GameMoment(name="super_ramp", wait_before_ms=400,
                   description="Super ramp (Demolition Time setup).",
                   events=[_press(61, 80, 300), _press(62, 80, 2000)]),
        GameMoment(name="loops", wait_before_ms=400,
                   events=[_press(86, 70, 1500), _press(55, 70, 1500),
                           _press(48, 70, 2000)]),
        GameMoment(name="car_chase", wait_before_ms=400,
                   description="Car Chase mode (3 switches).",
                   events=[_press(71, 80, 300), _press(72, 80, 300),
                           _press(87, 80, 4000,
                                  note="CAR CHASE cinematic")]),
        GameMoment(name="elevator", wait_before_ms=400,
                   description="Elevator hold/ramp/index.",
                   events=[_press(67, 80, 400), _press(74, 80, 400),
                           _press(75, 80, 3000)]),
        GameMoment(name="poppers_multiball", wait_before_ms=400,
                   events=[_press(73, 120, 2500),
                           _press(76, 120, 4000,
                                  note="multiball cinematic")]),
        GameMoment(name="claw", wait_before_ms=400,
                   description="Cryoclaw mech.",
                   events=[_press(82, 120, 4000)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(43, 50, 100), _press(45, 50, 100),
                           _press(43, 50, 100), _press(45, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(51, 80, 300), _press(52, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(46, 80, 300), _press(47, 80, 5000)]),
    ]


def _rs_moments(s: GameScript) -> List[GameMoment]:
    """Red & Ted's Road Show (PinMAME rs.c).
    L ramp 57/56, R ramp 71/55 + 72 (exit C), Rt loop 46/38,
    spinner 51, lockup 52/53, lock kickout 54, jets 63/64/65,
    slings 61/62.  Iconic: Drilling cinematics, Red + Ted talking
    heads, City modes.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(57, 80, 300), _press(56, 80, 1300),
                           _press(57, 80, 300), _press(56, 80, 1300),
                           _press(57, 80, 300), _press(56, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(71, 80, 300), _press(55, 80, 1300),
                           _press(71, 80, 300), _press(55, 80, 1300),
                           _press(71, 80, 300), _press(55, 80, 1500)]),
        GameMoment(name="right_loop", wait_before_ms=400,
                   events=[_press(46, 70, 300), _press(38, 70, 1500),
                           _press(46, 70, 300), _press(38, 70, 2000)]),
        GameMoment(name="spinner", wait_before_ms=400,
                   events=[_press(51, 60, 100), _press(51, 60, 100),
                           _press(51, 60, 100), _press(51, 60, 2000)]),
        GameMoment(name="locks_multiball", wait_before_ms=400,
                   description="Lockups → Drilling multiball.",
                   events=[_press(52, 120, 2500), _press(53, 120, 2500),
                           _press(54, 120, 4500,
                                  note="MULTIBALL cinematic")]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(63, 50, 100), _press(64, 50, 100),
                           _press(65, 50, 100), _press(63, 50, 100),
                           _press(64, 50, 100), _press(65, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(57, 80, 300), _press(56, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(71, 80, 300), _press(55, 80, 5000)]),
    ]


def _ss_moments(s: GameScript) -> List[GameMoment]:
    """Scared Stiff (PinMAME ss.c).
    L ramp 44/46, R ramp 45/47 + 67 (10pt), coffin 41/42/43/48,
    crate 38, R popper 36, loops L 58 / R 68, slings 51/52, upper
    sling 56, jets 53/54/55.  Iconic: Spider Multiball, Crate
    Multiball, Coffin lock.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(44, 80, 300), _press(46, 80, 1300),
                           _press(44, 80, 300), _press(46, 80, 1300),
                           _press(44, 80, 300), _press(46, 80, 1500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(45, 80, 300), _press(47, 80, 1300),
                           _press(45, 80, 300), _press(47, 80, 1300),
                           _press(45, 80, 300), _press(47, 80, 1500)]),
        GameMoment(name="loops", wait_before_ms=400,
                   events=[_press(58, 70, 1500), _press(68, 70, 1500),
                           _press(58, 70, 1500), _press(68, 70, 2000)]),
        GameMoment(name="coffin_letters", wait_before_ms=400,
                   description="Coffin targets (L/C/R + entrance).",
                   events=[_press(41, 80, 300), _press(42, 80, 300),
                           _press(43, 80, 300),
                           _press(48, 120, 4000,
                                  note="COFFIN MB / mode cinematic")]),
        GameMoment(name="crate_lock", wait_before_ms=400,
                   description="Crate — Spider Multiball lock.",
                   events=[_press(38, 100, 2500),
                           _press(38, 120, 5500,
                                  note="SPIDER MB cinematic")]),
        GameMoment(name="r_popper", wait_before_ms=400,
                   events=[_press(36, 120, 3000)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(53, 50, 100), _press(54, 50, 100),
                           _press(55, 50, 100), _press(53, 50, 100),
                           _press(54, 50, 100), _press(55, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(44, 80, 300), _press(46, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(45, 80, 300), _press(47, 80, 5000)]),
    ]


def _drac_moments(s: GameScript) -> List[GameMoment]:
    """Bram Stoker's Dracula (PinMAME drac.c).
    L ramp 73/84/85, R ramp 28/77, BL popper 55, TL popper 56,
    mystery 58, coffin pop 72, jets 61/62/63, slings 64/65.
    Iconic: Mist Multiball (turn into bats), Coffin lock,
    Holy Water hurry-up.
    """
    return [
        GameMoment(name="skill_shot",
                   events=[_wait(2500, note="skill shot window")]),
        GameMoment(name="left_ramp_light", wait_before_ms=400,
                   events=[_press(73, 80, 300), _press(84, 80, 1300),
                           _press(73, 80, 300), _press(84, 80, 1300),
                           _press(73, 80, 300), _press(84, 80, 1500)]),
        GameMoment(name="left_ramp_div", wait_before_ms=400,
                   description="L ramp diverter — alternate path.",
                   events=[_press(73, 80, 300), _press(85, 80, 2500)]),
        GameMoment(name="right_ramp_light", wait_before_ms=400,
                   events=[_press(77, 80, 300), _press(28, 80, 1300),
                           _press(77, 80, 300), _press(28, 80, 1300),
                           _press(77, 80, 300), _press(28, 80, 1500)]),
        GameMoment(name="mystery_scoop", wait_before_ms=400,
                   description="Mystery scoop — random award.",
                   events=[_press(58, 120, 4000)]),
        GameMoment(name="coffin_pop", wait_before_ms=400,
                   description="Coffin pop — Mist Multiball setup.",
                   events=[_press(72, 120, 2500),
                           _press(72, 120, 5500,
                                  note="MIST MULTIBALL cinematic")]),
        GameMoment(name="poppers", wait_before_ms=400,
                   events=[_press(55, 120, 2500), _press(56, 120, 3000)]),
        GameMoment(name="jets", wait_before_ms=300,
                   events=[_press(61, 50, 100), _press(62, 50, 100),
                           _press(63, 50, 100), _press(61, 50, 100),
                           _press(62, 50, 100), _press(63, 50, 1500)]),
        GameMoment(name="left_ramp_mode_start", wait_before_ms=400,
                   events=[_press(73, 80, 300), _press(84, 80, 5000)]),
        GameMoment(name="right_ramp_mode_start", wait_before_ms=400,
                   events=[_press(77, 80, 300), _press(28, 80, 5000)]),
    ]


# Per-game key -> moments factory.  Games not listed fall through to
# the profile-driven generic factory.
_MOMENTS_FACTORIES: Dict[str, Callable[[GameScript], List[GameMoment]]] = {
    "attack_from_mars": _afm_moments,
    "medieval_madness": _mm_moments,
    "theatre_of_magic": _tom_moments,
    "fish_tales": _ft_moments,
    "white_water": _ww_moments,
    "twilight_zone": _tz_moments,
    "addams_family": _taf_moments,
    "star_trek_tng": _sttng_moments,
    "indiana_jones": _ij_moments,
    "judge_dredd": _jd_moments,
    "no_good_gofers": _ngg_moments,
    "terminator_2": _t2_moments,
    "demolition_man": _dm_moments,
    "roadshow": _rs_moments,
    "scared_stiff": _ss_moments,
    "bram_stokers_dracula": _drac_moments,
}


# ---------------------------------------------------------------------------
# Registry: build one GameScript per known game key, deriving rom names
# from GAME_DB
# ---------------------------------------------------------------------------

def _rom_names_for(game_key: str) -> Tuple[str, ...]:
    """Return all plausible PinMAME ROM short names for *game_key*.

    GAME_DB stores ROM *file* patterns like ``"afm_113b.bin"``; the
    PinMAME short name is the basename minus extension (``"afm_113b"``).
    """
    info = GAME_DB.get(game_key, {})
    out = []
    for fn in info.get("game_roms", []):
        base = fn.rsplit(".", 1)[0]
        if base and base not in out:
            out.append(base)
    return tuple(out)


def _with_end_of_ball(factory):
    """Decorate a moments factory so it always finishes with the
    end-of-ball drain moment.  Captures the EOB bonus cinematic and
    signals the main capture loop that the script is fully done so it
    can shut down early instead of recording 60s of idle ball search.
    """
    def wrapped(s):
        moments = list(factory(s))
        # The generic factory already appends end_of_ball itself, so
        # don't double-stamp.
        if not moments or moments[-1].name != "end_of_ball":
            moments.append(_end_of_ball_moment(s))
        return moments
    return wrapped


def _build_registry() -> Tuple[GameScript, ...]:
    """Build one GameScript per profile/game-key pair we have."""
    scripts = []
    for game_key, profile in WPC_GAME_PROFILES.items():
        info = GAME_DB.get(game_key, {})
        title = info.get("display", game_key.replace("_", " ").title())
        rom_names = _rom_names_for(game_key)
        if not rom_names:
            continue
        factory = _MOMENTS_FACTORIES.get(game_key)
        # Auto-append end_of_ball so every script — generic or rich
        # — finishes with the drain cinematic + early-stop signal.
        if factory is not None:
            factory = _with_end_of_ball(factory)
        scripts.append(GameScript(
            game_key=game_key, title=title,
            rom_names=rom_names, profile=profile,
            moments_factory=factory,
        ))
    return tuple(scripts)


SCRIPTS: Tuple[GameScript, ...] = _build_registry()


# Fallback for un-mapped ROMs: minimal profile, generic moments.
_FALLBACK_PROFILE = {
    "trough": (32, 33, 34, 35),
    "shooter_lane": 18,
    "launch": 11,
    "raw": {},
}
_FALLBACK = GameScript(
    game_key="generic", title="Generic WPC",
    rom_names=(), profile=_FALLBACK_PROFILE,
    moments_factory=_generic_moments,
)


def get_script_for_rom(rom_name: str) -> GameScript:
    """Return the registered script for *rom_name*, or a generic
    fallback if none match.

    Match precedence:
      1. Exact ``rom_name`` against a registered script's ``rom_names``.
      2. Prefix match on the short-name root (e.g. ``afm_anything`` →
         AFM script, since AFM's rom_names share the ``afm_`` prefix).
    """
    if not rom_name:
        return _FALLBACK
    name = rom_name.lower()
    for script in SCRIPTS:
        for claimed in script.rom_names:
            if claimed.lower() == name:
                return script
    # Prefix fallback — handles minor revision suffixes.
    for script in SCRIPTS:
        for claimed in script.rom_names:
            base = claimed.split("_")[0].lower()
            if name.startswith(base + "_") or name == base:
                return script
    return _FALLBACK


# ---------------------------------------------------------------------------
# Driver — runs a script against a libpinmame set-switch function
# ---------------------------------------------------------------------------

SwitchSetter = Callable[[int, int], None]
LogFn = Callable[[str, str], None]
StopCheck = Callable[[], bool]
NowMs = Callable[[], int]


def run_script(
    script: GameScript,
    set_switch: SwitchSetter,
    log: LogFn,
    stop_check: StopCheck,
    now_ms: NowMs,
    after_each_moment_delay_s: float = 1.0,
) -> List[MomentClip]:
    """Drive *script.moments* against PinMAME, recording per-moment clips.

    Returns a list of :class:`MomentClip` whose timestamps come from
    *now_ms* — the caller must make that the same clock as
    ``CaptureFrame.timestamp_ms`` so the pipeline can slice frames +
    audio per scene.
    """
    log(f"Running script: {script.title} ({len(script.moments)} moments)",
        "info")
    clips: List[MomentClip] = []
    for moment in script.moments:
        if stop_check():
            log("Script aborted (stop_check).", "info")
            return clips
        if moment.wait_before_ms:
            time.sleep(moment.wait_before_ms / 1000.0)
            if stop_check():
                return clips
        start_ms = now_ms()
        log(f"  >>> {moment.name}: {moment.description or ''}", "info")
        for ev in moment.events:
            if stop_check():
                clips.append(MomentClip(
                    name=moment.name, start_ms=start_ms,
                    end_ms=now_ms(), description=moment.description))
                return clips
            if ev.sw < 0:
                if ev.delay_after_ms:
                    time.sleep(ev.delay_after_ms / 1000.0)
                continue
            if ev.state is None:
                try:
                    set_switch(ev.sw, 1)
                    time.sleep(ev.hold_ms / 1000.0)
                    set_switch(ev.sw, 0)
                except Exception as e:
                    log(f"set_switch({ev.sw}) failed: {e}", "warning")
            else:
                try:
                    set_switch(ev.sw, 1 if ev.state else 0)
                except Exception as e:
                    log(f"set_switch({ev.sw},{ev.state}) failed: {e}",
                        "warning")
            if ev.delay_after_ms:
                time.sleep(ev.delay_after_ms / 1000.0)
        time.sleep(after_each_moment_delay_s)
        end_ms = now_ms()
        clips.append(MomentClip(
            name=moment.name, start_ms=start_ms, end_ms=end_ms,
            description=moment.description))
        log(f"      ({moment.name}: {end_ms - start_ms} ms)", "info")
    log(f"Script complete: {len(clips)} clips recorded.", "info")
    return clips
