"""A game mode of the user's OWN, as part of a card PROJECT (item 127).

WHERE A MODE LIVES. ``<project>/modes/<slug>/mode.json``, with the mode's own art, clip
and sound files beside it (David, 2026-09-16: modes belong to the project and reach a
card through Write, like every other tab's edits). A project carries up to
:data:`MAX_MODES` of them, the slots ``mode.so`` reads (item 133).

WHY JSON AND NOT THE RUNTIME FILE. ``mode.so`` reads a key-per-line file of shot MASKS,
message ids and raw light commands, because it is built ``-nostdlib`` against fixed
buffers. Nobody should have to author that. ``mode.json`` holds what a person decides -
a shot BY NAME, a colour, a title - and :func:`runtime_cfg` turns it into the runtime
file, filling in the names of the assets the build generates (the screen node, the clip,
the sound key). The runtime file is an OUTPUT; it is never edited.

WHICH GAMES. A mode drives the game's own code at addresses measured on one build, so a
:class:`TitleProfile` holds everything per title - today Godzilla Pro 1.15 only. Its shot
names come from ``tools/spike2_emu/modes/MODE_API.md``'s measured switch -> shot table;
the spinners are left out, because each fires three bits and that reading is unproven.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field, fields, replace

FORMAT = 1
MODES_DIRNAME = "modes"
MODE_FILE = "mode.json"
#: The slots mode.so reads (sdk/mode_file.c MODES_MAX); high enough never to be the limit a
#: person meets, so the tab shows no cap.
MAX_MODES = 64


class ModeProjectError(ValueError):
    """A mode that cannot be saved, loaded or built as asked."""


# ---- what is measured, per title -------------------------------------------------
@dataclass(frozen=True)
class TitleProfile:
    key: str
    label: str
    game_dir: str
    shots: tuple                 # (name, shot mask) - what cmode_manager::v[7] is handed
    callout_countdown: int       # variant (seconds - 1) for 5 down to 1
    callout_ten_seconds: int
    callout_time_up: int
    light_owner: int
    light_lts: int
    hud_scene: str               # auto_loaded scene the mode screens are added to
    bank_scene: str              # auto_loaded video bank the clips are added to
    events: tuple = ()           # item 147: event names the title's port carries, proven in the emulator
    # ---- item 148: every ported title. Defaulted, so a profile written by hand (and
    # GODZILLA_PRO_1_15) keeps meaning "this title can do everything the tab offers".
    version: str = ""            # the game build, as its port says ("1.15")
    port: str = ""               # the port's file name in PORTS_DIR (or an absolute path)
    proven: bool = True          # False: the port was drafted and never run
    proven_note: str = ""        # why it is not proven
    example_start_shot: str = ""
    shot_mask_bits: int = 64     # the port's shot_mask_bits: how wide a mask the game sends
    runtime_can: tuple = ()      # what pad_mode_runtime.c would arm with, in its own words
    cannot: tuple = ()           # ((part, reason), ...) - PARTS this title cannot do, and why
    sound_note: str = ""         # what is not known yet about the title's callouts (never heard)
    score_bits: int = 64         # 32 for a port with the 32-bit scoring pair (score_add32 + scores32)
    switch_shots: tuple = ()     # names in ``shots`` that come from the port's `switch` lines
    switch_shots_note: str = ""  # why those are not proven yet; "" when they are (or there are none)
    stack_note: str = ""         # item 164: what ``stack no`` waits for when it is less than every mode
    lamps: int = -1              # named inserts tied to a shot the runtime can light (PM_CAN_LAMPS);
    #                              0 = none, so "Light the shots that score" lights nothing; -1 = not counted
    light_route: str = ""        # item 164: how a mode's Lights run - "language" (the game's own light
    #                              commands: Godzilla), "inserts" (every insert held in the mode's colour), ""
    bank_tree: str = "auto_loaded"   # item 164: the lcd tree the video bank is in (JP LE, Avengers,
    hud_tree: str = "auto_loaded"    # Iron Maiden keep it in demand_loaded) - and the HUD scene's

    def lcd(self, which):
        """``assets/lcd/<tree>/<scene id>`` of the title's ``"bank"`` or ``"hud"`` scene."""
        if which == "bank":
            return "assets/lcd/%s/%s" % (self.bank_tree, self.bank_scene)
        return "assets/lcd/%s/%s" % (self.hud_tree, self.hud_scene)

    def can(self, part):
        """True unless this title cannot do ``part`` (one of :data:`PARTS`)."""
        return part not in dict(self.cannot)

    def why_not(self, part):
        """Why this title cannot do ``part``, as a sentence; "" when it can."""
        return dict(self.cannot).get(part, "")

    def mask(self, names):
        """The OR of the named shots' masks. Raises on a name this title does not have."""
        table = dict(self.shots)
        out = 0
        for n in names:
            if n not in table:
                raise ModeProjectError("%s has no shot called %r" % (self.label, n))
            out |= table[n]
        return out


GODZILLA_PRO_1_15 = TitleProfile(
    key="godzilla_pro_1_15",
    label="Godzilla Pro 1.15",
    game_dir="godzilla_pro",
    shots=(
        ("Left ramp", 0x00100000),
        ("Right ramp", 0x00200000),
        ("Building", 0x00400000),
        ("Godzilla target", 0x00080000),
        ("Maser target", 0x08000000),
        ("Powerline left", 0x10000000),
        ("Powerline center", 0x20000000),
        ("Powerline right", 0x40000000),
        ("Shield target left", 0x80000000),
        ("Shield target right", 0x100000000),
        ("Skill shot", 0x400000000),
        ("Big loop", 0x1000000000),
        # item 160: the spinners' middle bits, the bits the game's own rules count (Ebirah's spins)
        ("Left spinner", 0x200),
        ("Top spinner", 0x2000),
        ("Right spinner", 0x20000),
    ),
    callout_countdown=1287,
    callout_ten_seconds=1291,
    callout_time_up=1295,
    light_owner=538,
    light_lts=224,
    hud_scene="32e6ae280ddaec08e203a02289bb39a04968e7b0",
    bank_scene="60ed7e5036b8ce09d35a3e101ea6fc1380b37d97",
    version="1.15",
    port="godzilla_pro-1.15.port",
    # item 148: what profile_from_port reads off the same port, so a caller comparing the
    # runtime's "can" line or asking for the example shot gets the port's answer here too
    example_start_shot="Maser target",
    runtime_can=("callout", "lights", "screens", "clips", "own-sound", "messages", "award-screen"),
)

# ---- item 147: the game's events a mode can start or end on ------------------------
#: A person-readable phrase for each event name a port may carry (MODE_SDK.md, "Events").
EVENT_LABELS = {
    "game_start": "a game starts",
    "ball_start": "a ball starts",
    "ball_end": "a ball ends",
    "bonus_start": "the end-of-ball bonus starts",
    "bonus_end": "the end-of-ball bonus ends",
    "tilt_warning": "a tilt warning",
    "tilt": "the player tilts",
    "game_over": "the game ends",
    "skill_shot": "the skill shot is made",
    "multiball_start": "a multiball starts",
    "multiball_end": "a multiball ends",
}

#: Godzilla Pro 1.15's events, each one proven by a marked game in the emulator
#: (item 147, event_probe.c and the runtime's own log).
GODZILLA_PRO_1_15 = replace(GODZILLA_PRO_1_15, events=(
    "ball_start", "game_start", "ball_end", "bonus_start", "bonus_end", "tilt_warning",
    "tilt", "game_over", "skill_shot", "multiball_start", "multiball_end"))

PROFILES = {p.key: p for p in (GODZILLA_PRO_1_15,)}


def profile(key):
    try:
        return PROFILES[key]
    except KeyError:
        found = profiles().get(key)          # item 148: every port in PORTS_DIR
        if found is None:
            found = _machine_profiles().get(key)   # derived on this machine, or read this session
        if found is not None:
            return found
        raise ModeProjectError("modes are not supported on %r yet" % key) from None


#: Profiles of ports a card's read found this session (title_reader: a port worked out on
#: this machine can live outside the folders :func:`profiles` scans), by key.
_REMEMBERED = {}
#: the port file's mtime when each remembered profile was read (a changed file is read again)
_REMEMBERED_AT = {}


def _listed_ports():
    """The port files every lookup may use, as normalised paths: exactly
    :func:`.mode_runtime.port_paths` (the shipped ports, then the ports derived on this machine
    that are still current). THE ONE SOURCE LIST: :func:`profiles`, :func:`profile`,
    :func:`profile_for_card`, ``mode_runtime.port_file`` and ``mode_write.find_port`` all
    answer from it, so a derived port that went stale is gone from every one of them at once."""
    from . import mode_runtime
    return {_norm_path(p) for _g, _v, p in mode_runtime.port_paths()}


def _norm_path(path):
    return os.path.normcase(os.path.abspath(path)) if path else ""


def _is_listed(p, listed):
    """Is the port behind profile ``p`` one of :func:`_listed_ports`?"""
    return _norm_path(port_path(p)) in listed


def _machine_profiles():
    """``{key: profile}`` a read found this session (:func:`remember_profile`) whose port is
    still one every lookup uses (:func:`_listed_ports`). A remembered profile whose port file
    is gone, went stale (another drafting revision, a changed reference) or changed since is
    left out: the ports derived on this machine are read by :func:`profiles` itself, from the
    same list, so a Write or a Try it in a later session finds them there."""
    listed = _listed_ports()
    out = {}
    for key, p in _REMEMBERED.items():
        if not _is_listed(p, listed):
            continue
        try:
            same = os.path.getmtime(port_path(p)) == _REMEMBERED_AT.get(key)
        except OSError:
            continue
        if same:
            out[key] = p
    return out


def remember_profile(p):
    """Make :func:`profile` answer ``p.key`` with ``p`` for the rest of this session: the
    Modes tab calls it with the profile of the port it read off a card, so validating and
    building a mode made for that card finds its title."""
    if p is not None and p.key and p.key not in PROFILES:
        _REMEMBERED[p.key] = p
        try:
            _REMEMBERED_AT[p.key] = os.path.getmtime(port_path(p))
        except OSError:
            _REMEMBERED_AT.pop(p.key, None)
    return p


# ---- every ported title: profiles from the SDK's port files (item 148) ---------------
#: One port per game build (tools/spike2_emu/modes/sdk/MODE_SDK.md, "Ports"). A port file
#: added here shows up in the Modes tab by itself.
PORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), "tools", "spike2_emu", "modes", "sdk", "ports")

#: The parts of a mode a title may be unable to do. The tab greys each one it cannot,
#: with :meth:`TitleProfile.why_not`, and :func:`runtime_cfg` leaves its lines out.
PARTS = ("countdown", "lights", "screen", "clip", "own_sound", "stack", "events")

#: What ``stack no`` (item 140) needs from a port before pad_mode_runtime.c's
#: pm_stock_mode_running can tell a battle or a multiball is on: (sites, data). Without
#: them mode_file.c logs "this game's port cannot tell" and starts the mode anyway.
STACK_NEEDS = (("stock_battle_running", "stock_multiball_running"), ("stock_mode_manager",))

#: item 164: the GENERIC route every other cmode title takes - the runtime walks the game's mode TABLE
#: itself and asks each mode its ACTIVE slot (MODE_SDK.md "The game's own modes on every title"):
#: (data, values)
STACK_TABLE_NEEDS = (("stock_mode_table", "typeinfo_cmode", "typeinfo_cmode_mball"),
                     ("stock_mode_count", "stock_slot_active"))

#: item 164: the builds where a ``stack no`` mode was seen held back in the emulator by the table
#: route (the game's own mode running, then refused; nothing running, then started)
STACK_PROVEN = frozenset({
    "jaws_le-1.02", "jurassic_park_le-1.16", "deadpool_le-1.14", "deadpool_pro-1.16",
    "avengers_infinity_le-1.09", "turtles_pro-1.59", "led_zeppelin_le-1.22", "munsters_le-1.28",
    "venom_le-1.07", "dungeons_and_dragons_le-1.00", "king_kong_le-0.97", "mando_le-1.44",
    "iron_maiden_le-1.16", "sword_of_rage_le-1.18", "rush_le-1.18", "star_wars_le-1.30",
    "john_wick_le-1.01", "led_zeppelin_pro-1.22", "foo_fighters_le-1.04", "turtles_le-1.59",
})


#: item 164: the titles with no cmode rules (plain C, Elvira's Rule classes) - the framework's own count of
#: the balls in play, called by the runtime: it sees a multiball there, not the other modes (sites)
STACK_BALLS_NEEDS = ("balls_in_play",)

#: item 164: the builds where a ``stack no`` mode was seen held back by a multiball that count showed, and
#: started again once it ended
STACK_BALLS_PROVEN = frozenset({
    "beatles-1.29", "james_bond_60th_le-1.11", "james_bond_le-1.06", "metallica_spike-1.03",
    "star_wars_elg-1.10", "stranger_things_le-1.12", "uncanny_xmen_le-0.98", "batman-1.13",
    "guardians_le-1.14", "aerosmith_le-1.15", "elvira3-1.13",
})


def _stack_balls(sites):
    return all(n in sites for n in STACK_BALLS_NEEDS)


def _stack_table(data, values):
    d, v = STACK_TABLE_NEEDS
    return all(data.get(n) for n in d) and all(n in values for n in v)

#: What pad_mode_runtime.c needs before it arms each capability (pad_mode_start):
#: (sites, data, values), copied, in the order its "armed: ... can ..." line prints them.
#: item 164: CLIP V2 - the newer builds' clips, played on the video bank's VideoSurface itself (no
#: clip_play / video_player / video_surface function to name; the game draws the surface), as
#: pad_mode_runtime.c's capability check reads it; plus the bank's scene id, or the game's own
#: ``video_surface`` getter (it loads a demand_loaded bank: JP LE)
CLIP_V2_NEEDS = (("surface_find", "surface_set_video", "surface_play", "surface_stop", "surface_state",
                  "string_new", "resource_get", "dynamic_cast"),
                 ("resource_manager", "typeinfo_resource", "typeinfo_scene_player"),
                 ("surface_playing", "scene_player_scene"))


#: item 164: CLIP LAYER - the game's full-screen video layer (Deadpool), as the runtime's clip3 check reads it
CLIP_LAYER_NEEDS = (("layer_add", "layer_remove", "layer_video", "layer_playing", "string_new"),
                    ("layer_stack", "video_layer"),
                    ("clip_layer_priority", "layer_video_at"))


def _clip_layer(sites, data, values):
    s, d, v = CLIP_LAYER_NEEDS
    return all(n in sites for n in s) and all(data.get(n) for n in d) and all(n in values for n in v)


def _clip_v2(sites, data, values, scenes):
    s, d, v = CLIP_V2_NEEDS
    return (all(n in sites for n in s) and all(data.get(n) for n in d) and all(n in values for n in v)
            and (bool(scenes.get("video_bank")) or "video_surface" in sites))


RUNTIME_NEEDS = {
    "callout": (("callout", "callout_nth"), (), ()),
    "lights": (("light_run", "lamp_group", "show_priority"), ("event_head", "event_current"),
               ("event_next", "event_flags", "event_show_flag", "event_show_id", "light_owner")),
    "screens": (("string_new", "resource_get", "dynamic_cast", "find_node", "find_text", "set_text"),
                ("resource_manager", "typeinfo_resource", "typeinfo_scene_player"),
                ("scene_player_scene", "node_visible_vfn")),
    "clips": (("clip_play", "clip_stop", "video_player", "video_surface", "surface_state",
               "player_advance", "display_draw"), ("display_holder",), ("display_at", "surface_playing")),
    "own-sound": (("sound_lookup", "callout"), (), ()),
    "messages": ((), ("message_count", "message_remap", "message_table"), ()),
    "award-screen": (("award_screen",), ("award_screen_arg",),
                     ("award_message_at", "award_value_at", "award_count_at")),
}
#: without these the runtime logs NOT THIS GAME'S PORT and hooks nothing: the reference title's
#: core. A port may name an alternative for three of them (pad_mode_runtime.c core_of_port), which
#: :func:`core_missing` applies: a switch_edge (the framework's switch drain) or switch_hit site
#: with `switch` lines for shot_dispatch, value ball_end_event with site hook_dispatch for ball_end,
#: and the 32-bit scoring pair.
RUNTIME_CORE = (("tick", "shot_dispatch", "ball_end", "score_add"), ("cur_player", "scores"))
#: the 32-bit scoring pair (The Beatles 1.29: score_add(u8 player r0, u32 points r1), u32 scores)
RUNTIME_CORE_32 = ("score_add32", "scores32")
#: ids below this are the game's event bus ids (pad_mode_runtime.c N_BUS_IDS)
BUS_IDS = 208

#: Ports whose shots from switches (`switch` lines through a switch_hit site) were seen reaching a
#: mode in the emulator, as ``<game>-<version>``. Until a port is here the tab says they are not
#: proven (:attr:`TitleProfile.switch_shots_note`).
#: beatles-1.29: emulator-proven 2026-09-23, each of 73-76 and 48-51 gave exactly one shot in play, the
#: slingshots none, and a mode file started on Target 1 and scored on Target 2-4 and the return lanes.
SWITCH_SHOTS_PROVEN = frozenset({"beatles-1.29"})
#: Builds whose shots from the framework's switch drain (site switch_edge, `switch` lines) were seen
#: reaching a mode in the emulator, each switch once, as ``<game>-<version>`` (2026-09-23: The Beatles
#: 1.29 and Star Wars ELG 1.10 of generation B, Batman 66 1.13 and Rush LE 1.18 of generation A).
SWITCH_EDGE_PROVEN = frozenset({"beatles-1.29", "star_wars_elg-1.10", "batman-1.13", "rush_le-1.18"})


def _core_names(port):
    """The core sites and data one port uses, as pad_mode_runtime.c's core_of_port picks them."""
    sites, values = port["site"], port["value"]
    s32 = RUNTIME_CORE_32[0] in sites
    shots = ("switch_edge" if "shot_dispatch" not in sites and "switch_edge" in sites and port.get("switch")
             else "switch_hit" if "shot_dispatch" not in sites and "switch_hit" in sites and port.get("switch")
             else "shot_dispatch")
    event = values.get("ball_end_event", -1)
    ball_end = "hook_dispatch" if "ball_end" not in sites and 0 <= event < BUS_IDS else "ball_end"
    return (("tick", shots, ball_end, RUNTIME_CORE_32[0] if s32 else "score_add"),
            ("cur_player", RUNTIME_CORE_32[1] if s32 else "scores"))


def core_missing(port):
    """What a port (:func:`read_port`'s dict) lacks of the runtime's core, as a list of entry
    names; [] when the runtime would hook it. The runtime's rule, pad_mode_runtime.c
    core_of_port."""
    sites, data = _core_names(port)
    return [n for n in sites if n not in port["site"]] + [n for n in data if not port["data"].get(n)]

#: The stock scene files behind each port's ``scene hud`` / ``scene video_bank``, measured
#: READ-ONLY off the card images (item 148, 2026-09-16): each file's md5, then
#: ``scene_write.profile_for`` on the HUD and a ``video_bank.parse`` + ``add_clip`` round
#: trip on the bank. A screen needs its HUD file to have a measured scene_write profile;
#: a clip needs its bank to walk AND an added clip to have been seen on the glass.
#:
#: - Godzilla Pro 1.15 and Premium/LE 1.16 carry the SAME two files: HUD f9daed5a
#:   (profiled), bank fe35b5b8 (598 clips; the added clip played, items 132 and 127).
#: - Jaws LE 1.02: its score panel 9d578751 is 11,987,106 B, md5 27142809, and has no
#:   profile; its bank walks (635 clips, add_clip round trips), and an added clip PLAYED
#:   (item 148 run2, 2026-09-17: a 6 s title card built with render_title_clip + add_clip,
#:   put on a card copy with ext4_grow's debugfs path, was on the glass at 1, 2 and 4 s
#:   and the game's own screen was back at 10 s).
#: - TMNT Pro 1.58 and 1.59 share bank cf92bc5a (344 clips), Deadpool Pro 1.16 and LE 1.14
#:   bank e0e29301 (84 clips); both walk, and neither port has clip functions.
TITLE_SCENES = {
    "godzilla_pro-1.15": dict(hud="f9daed5a19aafc807bf9eb3c2def6c27", screen_proven=True,
                              bank="fe35b5b897c2b0df6fe583b0168a6cda", clip_proven=True),
    "godzilla_le-1.16": dict(hud="f9daed5a19aafc807bf9eb3c2def6c27", screen_proven=True,
                             bank="fe35b5b897c2b0df6fe583b0168a6cda", clip_proven=True),
    "jaws_le-1.02": dict(screen_proven=True, hud="2714280910e8768b6a17dba50fb150f7", 
                         bank="908389471bb1044c57d8ad25b0471ca8", clip_proven=True),
    "turtles_pro-1.58": dict(bank="cf92bc5a7a4bb06fcd90a3bb90d55baa", clip_proven=False),
    "turtles_pro-1.59": dict(screen_proven=True, hud="e9a5916df0d6c41510453c83e1dd6fb8", bank="cf92bc5a7a4bb06fcd90a3bb90d55baa", clip_proven=True),   # item 164: our clip seen on the glass
    "deadpool_pro-1.16": dict(screen_proven=True, hud="2039fc21e598c672fa4d45df2283178b", bank="e0e293019ac1e6977049c83dc8485496", clip_proven=True),   # item 164: our clip seen on the glass
    "deadpool_le-1.14": dict(screen_proven=True, hud="2ce488d819e6f9d8b02e2e28ebc284e0", bank="e0e293019ac1e6977049c83dc8485496", clip_proven=True),   # item 164: our clip seen on the glass
    "venom_le-1.07": dict(screen_proven=True, hud="2a91907fb78f42cb8eb224ba4322548d", bank="6a9b1862ee06252a137dacc7bb099d78", clip_proven=True),   # item 164: our clip seen on the glass
    "led_zeppelin_le-1.22": dict(screen_proven=True, hud="52c8fb8417a3ee2442bc31e12563b6fa", bank="d294bdb25548df7400a740013a0bf908", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "beatles-1.29": dict(screen_proven=True, hud="fe7ab9c3143f1db4ebf9c917df8b47fe", bank="e9101ee9059414046aec49f7ccb4613c", clip_proven=True),   # item 164: our clip seen on the glass
    "dungeons_and_dragons_le-1.00": dict(screen_proven=True, hud="e8bbe9670a9a212f18408a602d7b187b", bank="62d7aa522a27805655b6819750a0df75", clip_proven=True),   # item 164: our clip seen on the glass
    "foo_fighters_le-1.04": dict(screen_proven=True, hud="3f34991c6809a039dd47b2086a12937a", bank="469deda43d1ebfe2c5d371d5a800d0a9", clip_proven=True),   # item 164: our clip seen on the glass
    "godzilla_pro-1.16": dict(screen_proven=True, hud="f9daed5a19aafc807bf9eb3c2def6c27", bank="fe35b5b897c2b0df6fe583b0168a6cda", clip_proven=True),   # item 164: our clip seen on the glass
    "james_bond_60th_le-1.11": dict(screen_proven=True, hud="37d90179d849daf5afcbe4db0cf1cf1d", bank="2883a8a9a51ec57c2b74a95d24c9f360", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "james_bond_le-1.06": dict(screen_proven=True, hud="832c77c669803d557c730a3be09fb9e5", bank="8813fb4003cef416a6a1179d9677a0b9", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "avengers_infinity_le-1.09": dict(screen_proven=True, hud="62614053077f96e15d4d3d89a88d8a20", bank="0a433b8e07933efcc8704ca469036c97", bank_tree="demand_loaded", clip_proven=True),   # item 164: our clip seen on the glass
    "jurassic_park_le-1.16": dict(screen_proven=True, hud="5a57df0fc5f2f441faf8f5a6b012c277", bank="3e222871d6c38b6b493fdfe59f788133", bank_tree="demand_loaded", clip_proven=True),   # item 164: our clip seen on the glass
    "king_kong_le-0.97": dict(screen_proven=True, hud="cf8da03fa56cd71e414702db70b6aa3d", bank="ed379c6514e73bead614fee25e93d862", clip_proven=True),   # item 164: our clip seen on the glass
    "led_zeppelin_pro-1.22": dict(screen_proven=True, hud="b8745c86480a44976d95068a7dc773f2", bank="d294bdb25548df7400a740013a0bf908", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "metallica_spike-1.03": dict(screen_proven=True, hud="809cbf843c36555ddbda41c3b4909543", bank="70fed15b5a82c83747423185ab477a20", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "turtles_le-1.59": dict(screen_proven=True, hud="a337459aee72b3ec5dc9b0a50981e16d", bank="cf92bc5a7a4bb06fcd90a3bb90d55baa", clip_proven=True),   # item 164: our clip seen on the glass
    "uncanny_xmen_le-0.98": dict(screen_proven=True, hud="0d31df0d25052d0ec251c18d5b8b33a1", bank="4c5e3bd248dc09f1373c91111543f92e", clip_proven=True),   # item 164: our clip seen on the glass
    "aerosmith_le-1.15": dict(screen_proven=True, hud="53c9a69e39abf2dbb54fd134afe68b01", bank="dab80a17b8977c603e9094be6f072a58", clip_proven=True),   # item 164: our clip seen on the glass
    "guardians_le-1.14": dict(screen_proven=True, hud="f1b87fa9a6f94cddc4aca6268dcd96ea", bank="a0683942e100705db906181685dd842e", clip_proven=True),   # item 164: our clip seen on the glass
    "mando_le-1.44": dict(screen_proven=True, hud="7b8d6f595c97a76e16bf54bee5d10007", bank="390b28f5b7ef5b5e3f49edcee3088a29", clip_proven=True),   # item 164: our clip seen on the glass
    "rush_le-1.18": dict(screen_proven=True, hud="a516ede995deda83619a4d57469a8760", bank="cbc3c53c829d671cdab994a0fa0b9ef5", clip_proven=False, clip_hidden=True),   # item 164: plays, never on the glass
    "stranger_things_le-1.12": dict(screen_proven=True, hud="315de4afdec66df3ea56cc64b5673a95", bank="a6c50224ebf14f37444b84bb632c1b68", clip_proven=True),   # item 164: our clip seen on the glass
    "sword_of_rage_le-1.18": dict(screen_proven=True, hud="ff7ed4a354fd8f5565250ea1411ef2ed", bank="ca3bab9c0f7e7f02272fddb8ac269dfb", clip_proven=True),   # item 164: our clip seen on the glass
    "iron_maiden_le-1.16": dict(screen_proven=True, hud="9b6a1b230e2dcfe050606a7d7bb4c283"),   # item 164: its in-game HUD, read statically
    "john_wick_le-1.01": dict(screen_proven=True, hud="aa4caf7b0c0a142f39d8c62388601dd1"),   # item 164: its in-game HUD, read statically
    "munsters_le-1.28": dict(screen_proven=True, hud="9869621883a18ce97bd3446d67dfbbff"),   # item 164: its in-game HUD, read statically
    "star_wars_le-1.30": dict(screen_proven=True, hud="6ad2d6fb45a03892f43675a9faf8d1ac", ),   # item 164: its in-game HUD, read statically
    "elvira3-1.13": dict(screen_proven=True, hud="fda0fad4bd0931e1412872f85a232834"),   # item 164: its in-game HUD, read statically
    "star_wars_elg-1.10": dict(hud="354935f6d901c89105d1a97edd4a559e", screen_proven=True, ),   # item 164: its in-game HUD, read statically
    "batman-1.13": dict(screen_proven=True, hud="322b14238d0351d6e6ddeb6333e07c8a"),   # item 164: its in-game HUD, read statically
}

#: Titles whose callouts ran in the emulator but were never HEARD (the rig is always
#: muted), in words the Modes tab shows under Sound; the countdown and a sound of the
#: mode's own stay live there. From the port's own comment on its callouts.
TITLE_SOUND_UNHEARD = {}      # item 163: Jaws's and The Beatles' callouts are heard now

#: The game's name for each Spike 2 game directory (the part before an edition word), as the
#: backglass says it. Every latest Spike 2 build is here; a directory not listed is written
#: out from its words (``_title_words``).
_TITLE_NAMES = {
    "aerosmith": "Aerosmith",
    "avengers_infinity": "Avengers: Infinity Quest",
    "batman": "Batman 66",
    "beatles": "The Beatles",
    "deadpool": "Deadpool",
    "dungeons_and_dragons": "Dungeons & Dragons",
    "elvira3": "Elvira",
    "foo_fighters": "Foo Fighters",
    "godzilla": "Godzilla",
    "guardians": "Guardians of the Galaxy",
    "iron_maiden": "Iron Maiden",
    "james_bond": "James Bond 007",
    "james_bond_60th": "James Bond 60th",
    "jaws": "Jaws",
    "john_wick": "John Wick",
    "jurassic_park": "Jurassic Park",
    "jurassic_park_the_pin": "Jurassic Park Pin",
    "king_kong": "King Kong",
    "led_zeppelin": "Led Zeppelin",
    "mando": "The Mandalorian",
    "metallica_spike": "Metallica Remastered",
    "munsters": "The Munsters",
    "rush": "Rush",
    "star_wars": "Star Wars",
    "star_wars_elg": "Star Wars ELG",
    "stranger_things": "Stranger Things",
    "sword_of_rage": "Sword of Rage",
    "turtles": "TMNT",
    "uncanny_xmen": "Uncanny X-Men",
    "venom": "Venom",
}
_EDITION_NAMES = {"pro": "Pro", "le": "LE", "prem": "Premium", "premium": "Premium", "se": "SE"}
#: one card image that serves two models
_SHARED_EDITIONS = {"godzilla_le": "Premium/LE"}
#: short words kept lower case inside a name written out from its directory
_SMALL_WORDS = ("of", "the", "and", "a", "in", "on")
#: a port whose opening comment says this was drafted and never run
UNPROVEN_MARK = "NOT RUN"


def _title_words(base):
    """A game directory with no entry in :data:`_TITLE_NAMES`, written out: ``x_men`` ->
    ``X Men``, ``house_of_horrors`` -> ``House of Horrors``; a word of up to three
    consonants reads as letters (``elg`` -> ``ELG``)."""
    out = []
    for i, w in enumerate(w for w in base.split("_") if w):
        if i and w in _SMALL_WORDS:
            out.append(w)
        elif len(w) <= 3 and not re.search(r"[aeiouy]", w):
            out.append(w.upper())
        elif re.match(r"^\d+(st|nd|rd|th)$", w):
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def title_label(game, version=""):
    """``godzilla_pro``, ``1.15`` -> ``Godzilla Pro 1.15``; ``beatles`` -> ``The Beatles``.

    ONE LABEL PER BUILD: the version is spelled as a port names it (``1.29.0``, ``1_29_0`` and
    ``1.29`` all read ``1.29``; a nonzero third part is kept, ``1.15.1``), so the head, the
    read panel, a game mode's page and every sentence name one card the same way."""
    version = _label_version(version)
    words = (game or "").lower().split("_")
    edition = ""
    if len(words) > 1 and words[-1] in _EDITION_NAMES:
        edition = _SHARED_EDITIONS.get(game.lower(), _EDITION_NAMES[words[-1]])
        words = words[:-1]
    base = "_".join(words)
    name = _TITLE_NAMES.get(base) or _title_words(base)
    return " ".join(x for x in (name, edition, version) if x)


def _label_version(version):
    """``1.29.0`` / ``1_29_0`` -> ``1.29``; ``1.15.1`` stays; text that is not a version is
    kept as it is."""
    text = str(version or "").strip()
    if not re.match(r"^\d+([._]\d+)*$", text):
        return text
    parts = re.split(r"[._]", text)
    while len(parts) > 2 and int(parts[-1]) == 0:
        parts.pop()
    return ".".join(parts)


def _port_number(text):
    t = text.strip().lower()
    return int(t, 16) if t.startswith("0x") else int(t, 10)


def read_port(path):
    """A port file the way pad_mode_runtime.c reads it: a dict of ``game``, ``version``,
    ``site`` {name: (addr, w0, w1)}, ``data`` / ``value`` / ``callout`` {name: number},
    ``shot`` [(name, mask)], ``scene`` / ``text`` {name: words}, and ``header`` (the
    opening comment lines). Raises OSError when it cannot be read."""
    out = dict(game="", version="", site={}, data={}, value={}, callout={}, shot=[],
               scene={}, text={}, header=[], event=[])
    out["lamp"] = []                      # item mode-leds: [(name, (r, g, b) light ids, shot mask)]
    out["switch"] = []                    # shots from switches: [(switch id, shot mask, name)]
    body = False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if not s:
                continue
            if s.startswith("#"):
                if not body:
                    out["header"].append(s[1:].strip())
                continue
            body = True
            key, _, rest = s.partition(" ")
            rest = rest.strip()
            try:
                if key in ("game", "version"):
                    out[key] = rest
                elif key == "site":
                    w = rest.split()
                    out["site"][w[0]] = tuple(_port_number(x) for x in w[1:4])
                elif key in ("data", "value", "callout"):
                    w = rest.split()
                    out[key][w[0]] = _port_number(w[1])
                elif key == "shot":
                    mask, _, name = rest.partition(" ")
                    mask, name = _port_number(mask), name.strip()
                    if mask and name:
                        out["shot"].append((name, mask))
                elif key in ("scene", "text"):
                    name, _, words = rest.partition(" ")
                    out[key][name] = words.strip()
                elif key == "event":              # item 147: `event <name> <bus id>` or `event <name> site <site>`
                    w = rest.split("#", 1)[0].split()
                    if len(w) >= 3 and w[1] == "site":
                        out["event"].append((w[0], "site", w[2]))
                    elif _port_number(w[1]) < 208:
                        out["event"].append((w[0], "bus", "hook_dispatch"))
                elif key == "lamp":               # item mode-leds: `lamp <R,G,B | one id> <shot mask> <name>`
                    lamp = _port_lamp(rest)
                    if lamp:
                        out["lamp"].append(lamp)
                elif key == "switch":             # `switch <id> <shot mask> <name>`: a switch's hit is a shot
                    sw, mask, name = rest.split(None, 2)
                    sw, mask, name = _port_number(sw), _port_number(mask), name.strip()
                    if mask and name and 0 <= sw < 256:
                        out["switch"].append((sw, mask, name))
            except (IndexError, ValueError):
                continue                  # the runtime skips a line it cannot read, too
    return out


def _port_lamp(rest):
    """A ``lamp`` line's words, read as pad_mode_runtime.c's lamp_line reads them: up to three light ids
    joined by commas (a 0 = the fixture lacks that colour; one id = a single-colour insert), the shot
    mask, then the insert's name to the end of the line, a `` #`` comment dropped. ``(name, (r, g, b),
    mask)``, or None for a line the runtime would skip."""
    m = re.match(r"(\d+(?:\s*,\s*\d+){0,2})\s+(0[xX][0-9a-fA-F]+|\d+)\s+(.*)$", rest)
    if not m:
        return None
    ids = [int(x) for x in m.group(1).split(",")]
    name = re.split(r"\s+#", m.group(3), maxsplit=1)[0].strip()
    if not name or not any(ids):
        return None
    return name, tuple(ids + [0] * (3 - len(ids))), _port_number(m.group(2))


def _hud_is_profiled(md5):
    try:
        from . import scene_write
    except ImportError:                   # pragma: no cover - numpy is a hard dependency
        return False
    return md5 in scene_write.PROFILES


def profile_from_port(path):
    """A :class:`TitleProfile` derived from one SDK port file (item 148): its shots,
    callout ids, light owner and set, scenes and example shot, what the runtime would arm
    with, and which of :data:`PARTS` the title cannot do - each with the reason. Raises
    :class:`ModeProjectError` for a file that is not a usable port."""
    try:
        port = read_port(path)
    except OSError as e:
        raise ModeProjectError("cannot read the port %s: %s" % (path, e)) from None
    base = os.path.basename(path)
    game, version = port["game"].strip(), port["version"].strip()
    if not game or not version:
        raise ModeProjectError("%s names no game and version" % base)
    sites, data, values = port["site"], port["data"], port["value"]
    missing = core_missing(port)
    if missing:
        raise ModeProjectError("%s lacks what every mode needs (%s): the runtime would hook "
                               "nothing" % (base, ", ".join(missing)))
    shots, switch_shots = _shots_with_switches(port)
    if not shots:
        raise ModeProjectError("%s names no shots" % base)
    runtime = tuple(cap for cap, (s, d, v) in RUNTIME_NEEDS.items()
                    if all(n in sites for n in s) and all(data.get(n) for n in d)
                    and all(n in values for n in v))
    if "clips" not in runtime and (_clip_layer(sites, data, values) or _clip_v2(sites, data, values, port["scene"])):
        runtime = tuple(c for c in RUNTIME_NEEDS if c in runtime or c == "clips")
    label = title_label(game, version)
    callouts, scenes = port["callout"], port["scene"]
    measured = TITLE_SCENES.get("%s-%s" % (game, version), {})
    cannot = []

    def no(part, why):
        cannot.append((part, why % dict(label=label)))

    if "callout" not in runtime:
        no("countdown", "The app has not found how %(label)s plays its callouts, so the game's "
                        "own voice cannot count down.")
    elif not callouts.get("countdown"):         # ten_seconds is optional: the count is 5..1 without it
        no("countdown", "The app does not know which of %(label)s's callouts count down, so the "
                        "game's own voice cannot count down.")
    key = "%s-%s" % (game, version)
    stack_note = ""
    inserts_ok = _lamp_route(port) and key in LAMPS_PROVEN
    light_route = ""
    if "lights" in runtime and values.get("light_lts"):
        light_route = "language"
    elif inserts_ok:
        light_route = "inserts"          # item 164: every insert in the mode's colour (light_all)
    elif _lamp_route(port):
        no("lights", "The app has found %(label)s's inserts but has not yet seen a mode light "
                     "them in the emulator, so a mode's lights stay off.")
    elif "lights" not in runtime:
        if all(n in sites for n in RUNTIME_NEEDS["lights"][0]):
            no("lights", "The app has found %(label)s's light shows but not yet which of the "
                         "game's own rules may run one, so its lights cannot be driven.")
        else:
            no("lights", "The app has not found how %(label)s runs its light shows, so a mode "
                         "cannot sweep the playfield yet.")
    elif not values.get("light_lts"):
        no("lights", "The app does not know a light show of %(label)s's to sweep a colour "
                     "with.")
    hud = scenes.get("hud", "")
    if "screens" not in runtime:
        no("screen", "The app has not found how %(label)s draws its screens, so a mode cannot "
                     "show one of its own yet.")
    elif not hud:
        no("screen", "The app does not know which of %(label)s's scenes a mode's screen goes "
                     "in, so a mode cannot show one yet.")
    elif not measured.get("hud") or not _hud_is_profiled(measured["hud"]):
        no("screen", "The scene a mode's screen goes in on %(label)s has not been measured yet, "
                     "so a screen cannot be added to it.")
    elif not measured.get("screen_proven"):
        no("screen", "A screen added to %(label)s's HUD scene has not been seen on the glass in "
                     "the emulator yet.")
    bank = scenes.get("video_bank", "")
    if measured.get("clip_hidden"):
        no("clip", "A clip added to %(label)s's video bank plays in the emulator but never "
                   "reaches the screen: the game shows another video there.")
    elif "clips" not in runtime:
        no("clip", "The app has not found where %(label)s plays its clips, so a mode cannot "
                   "add one yet.")
    elif not bank:
        no("clip", "The app does not know which of %(label)s's video banks a clip goes in, so "
                   "a mode cannot add one yet.")
    elif not measured.get("bank"):
        no("clip", "%(label)s's video bank has not been measured yet, so a clip cannot be "
                   "added to it.")
    elif not measured.get("clip_proven"):
        no("clip", "A clip added to %(label)s's video bank has not been seen on the screen in "
                   "the emulator yet.")
    if "own-sound" not in runtime:
        no("own_sound", "The app has not found how %(label)s looks up its sounds, so a sound of "
                        "the mode's own cannot play.")
    elif not callouts.get("time_up"):
        no("own_sound", "The app does not know %(label)s's time-up callout, the one a sound of "
                        "the mode's own plays in place of.")
    if all(n in sites for n in STACK_NEEDS[0]) and all(data.get(n) for n in STACK_NEEDS[1]):
        pass
    elif _stack_table(data, values) and key in STACK_PROVEN:
        pass
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN:
        stack_note = ("On %s a mode of yours waits only for the game's multiballs: the app cannot yet "
                      "see its other modes." % label)
    elif _stack_balls(sites):
        no("stack", "The app has found how %(label)s tells a multiball is running but has not yet "
                    "seen a mode of yours wait for one in the emulator, so it always runs beside them.")
    elif _stack_table(data, values):
        no("stack", "The app has found %(label)s's own modes but has not yet seen a mode of "
                    "yours wait for one in the emulator, so it always runs beside them.")
    else:
        no("stack", "The app has not found how %(label)s tells that one of its own modes is "
                    "running, so a mode of yours cannot wait for them and always runs beside "
                    "them.")
    events = tuple(name for name, _kind, needs in port["event"] if needs in sites)
    if not events:
        no("events", "The app does not know any of %(label)s's events yet (a ball starting, a "
                     "multiball), so a mode starts on its shot and ends on its clock or the "
                     "drain.")
    proven =not any(UNPROVEN_MARK in line for line in port["header"])
    switch_note = ""
    seen = SWITCH_EDGE_PROVEN if "switch_edge" in port["site"] else SWITCH_SHOTS_PROVEN
    if switch_shots and "%s-%s" % (game, version) not in seen:
        switch_note = ("%s's shots from switches (%s) have not been seen reaching a mode in the "
                       "emulator yet." % (label, ", ".join(switch_shots)))
    return TitleProfile(
        key="%s_%s" % (game, version.replace(".", "_")),
        label=label,
        game_dir=game,
        shots=shots,
        callout_countdown=callouts.get("countdown", 0),
        callout_ten_seconds=callouts.get("ten_seconds", 0),
        callout_time_up=callouts.get("time_up", 0),
        light_owner=values.get("light_owner", 0),
        light_lts=values.get("light_lts", 0),
        hud_scene=hud,
        bank_scene=bank,
        version=version,
        port=path if os.path.dirname(os.path.abspath(path)) != os.path.abspath(PORTS_DIR) else base,
        proven=proven,
        proven_note="" if proven else (
            "what the app knows of %s was drafted and has never run in the emulator, so a mode "
            "made here may not work." % label),
        example_start_shot=port["text"].get("example_start_shot", ""),
        shot_mask_bits=values.get("shot_mask_bits", 64),
        runtime_can=runtime,
        cannot=tuple(cannot),
        # item 147's events, as pad_mode_runtime.c's events_arm would arm them: a bus event
        # needs hook_dispatch, a site event its site. What each run measured is in the port.
        events=events,
        sound_note=TITLE_SOUND_UNHEARD.get("%s-%s" % (game, version), ""),
        score_bits=32 if RUNTIME_CORE_32[0] in sites else 64,
        switch_shots=switch_shots,
        switch_shots_note=switch_note,
        stack_note=stack_note,
        lamps=_lit_inserts(port) if key in LAMPS_PROVEN else 0,
        light_route=light_route,
        bank_tree=measured.get("bank_tree", "auto_loaded"),
        hud_tree=measured.get("hud_tree", "auto_loaded"),
    )


#: what pad_mode_runtime.c's lamps_arm needs besides the `lamp` lines before it lights an insert
LAMP_NEEDS = (("lamp_group",), ("lamp_layers", "light_count"),
              ("lamp_slot_size", "lamp_slot_level", "lamp_slot_alpha", "lamp_slot_fade",
               "lamp_slot_used", "lamp_group_prio", "lamp_group_next"))


#: item 164: the builds whose named inserts a mode has held in the emulator - the node bus (or the
#: shim's LED view) carried the held colour on the inserts' channels. Until a build is here its
#: inserts light nothing from the tab: Lights and "Light the shots that score" stay greyed.
LAMPS_PROVEN = frozenset((
    "godzilla_le-1.16", "godzilla_pro-1.15", "godzilla_pro-1.16",    # item mode-leds RUN 5/6
    # item 164 (2026-09-25): a mode file's light_all held every insert in magenta; the shim's LED
    # view (dump/padled) had the addressed inserts in it while the mode ran, not before or after
    "beatles-1.29", "deadpool_le-1.14", "deadpool_pro-1.16", "dungeons_and_dragons_le-1.00", "elvira3-1.13",
    "foo_fighters_le-1.04", "james_bond_60th_le-1.11", "james_bond_le-1.06", "jaws_le-1.02",
    "john_wick_le-1.01", "jurassic_park_le-1.16", "king_kong_le-0.97", "led_zeppelin_le-1.22",
    "led_zeppelin_pro-1.22", "metallica_spike-1.03", "munsters_le-1.28", "star_wars_elg-1.10",
    "star_wars_le-1.30", "turtles_le-1.59", "turtles_pro-1.59", "uncanny_xmen_le-0.98",
    "venom_le-1.07",
    # the SWELF generation: the shim reads only some of its boards (it refuses the bank form), so
    # the proof is the boards it reads - the held colour on the device table's own channels
    "aerosmith_le-1.15", "batman-1.13", "guardians_le-1.14", "mando_le-1.44", "rush_le-1.18",
))


def _lamp_route(port):
    """The port has the lamp layer and names inserts (what pm_lamp_all needs)."""
    sites, data, values = LAMP_NEEDS
    return (all(n in port["site"] for n in sites) and all(port["data"].get(n) for n in data)
            and all(n in port["value"] for n in values) and bool(port.get("lamp")))


def _lit_inserts(port):
    """How many of the port's named inserts the runtime would light for a shot that scores:
    `lamp` lines tied to a shot, when the port also has the lamp layer (LAMP_NEEDS); else 0."""
    sites, data, values = LAMP_NEEDS
    if not (all(n in port["site"] for n in sites) and all(port["data"].get(n) for n in data)
            and all(n in port["value"] for n in values)):
        return 0
    return sum(1 for _name, _ids, mask in port.get("lamp", ()) if mask)


def _shots_with_switches(port):
    """``(shots, switch_shot_names)``: the port's `shot` lines, then each `switch` line's name that
    is not a shot already, as the runtime's port reader adds them. Switch lines count only when the
    port names a switch_edge or switch_hit site (the runtime arms them only through one)."""
    shots = list(port["shot"])
    names = []
    if "switch_edge" in port["site"] or any(s.startswith("switch_hit") for s in port["site"]):
        known = {n for n, _m in shots}
        for _sw, mask, name in port.get("switch", ()):
            if name not in known:
                known.add(name)
                shots.append((name, mask))
                names.append(name)
    return tuple(shots), tuple(names)


def port_path(p):
    """The port file behind a profile, or "" when it has none."""
    return os.path.join(PORTS_DIR, p.port) if p.port else ""


_PROFILES_CACHE = {}


def profiles(ports_dir=None):
    """Every usable port in ``ports_dir`` as ``{key: profile}``, keyed ``<game>_<version>`` with
    the dots as underscores (``turtles_pro_1_59``). A file that is not a usable port is left
    out. By default every folder ports are read from: :data:`PORTS_DIR` (the shipped ports),
    then the ports derived on this machine (:func:`.mode_runtime.port_dirs`); a shipped port
    wins over a derived one of the same build, and the hand-written :data:`PROFILES` win over
    both (``GODZILLA_PRO_1_15``). Each folder is re-read when a port file in it changes.

    Only a port in :func:`_listed_ports` (``mode_runtime.port_paths``, the one list every
    lookup shares) is answered: a derived port no longer current (another drafting revision,
    a changed reference) is left out here exactly as ``port_file`` and ``find_port`` leave it
    out."""
    if ports_dir is None:
        out = {}
        from . import mode_runtime
        listed = _listed_ports()
        for d in [x for x in mode_runtime.port_dirs()[1:] if os.path.abspath(x) != os.path.abspath(PORTS_DIR)]:
            out.update({k: p for k, p in _folder_profiles(d).items() if _is_listed(p, listed)})
        out.update({k: p for k, p in _folder_profiles(PORTS_DIR).items() if _is_listed(p, listed)})
        out.update(PROFILES)
        return out
    return _folder_profiles(ports_dir)


def _folder_profiles(d):
    """{key: profile} of every usable port in one folder, cached until a file in it changes."""
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".port"))
        stamp = tuple((n, os.path.getmtime(os.path.join(d, n))) for n in names)
    except OSError:
        names, stamp = [], ()
    cached = _PROFILES_CACHE.get(d)
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    out = {}
    for n in names:
        try:
            p = profile_from_port(os.path.join(d, n))
        except ModeProjectError:
            continue
        out[p.key] = p
    _PROFILES_CACHE[d] = (stamp, out)
    return dict(out)


def version_key(version):
    """``1.16.0`` / ``1.16`` / ``1_16_0`` -> ``(1, 16)``; a patch level other than 0 is kept
    (``1.15.1`` never passes for ``1.15``). THE ONE version comparison of the mode family:
    a card's index name, a profile's port version, a port file's name and the Emulate
    card's title all go through here, so ``jaws_le`` 1.02 on the card and ``1.02`` in the
    port's name are the same build (as ints, not as strings). Empty or unreadable -> ``()``.
    """
    parts = [int(x) for x in re.findall(r"\d+", str(version or ""))]
    while len(parts) > 2 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


#: The old private name, kept for callers that still say it.
_version_key = version_key


def profile_for_card(game_dir, version, ports_dir=None):
    """The profile for a card of ``game_dir`` (``turtles_pro``) at ``version``
    (``1.59.0`` or ``1.59``), or None when no port is for that build."""
    game, want = (game_dir or "").lower(), _version_key(version)
    if not game or not want:
        return None
    for p in profiles(ports_dir).values():
        if p.game_dir == game and _version_key(p.version) == want:
            return p
    if ports_dir is None:
        # a port derived on this machine or found by a card's read: the Modes tab, Write
        # and Try it all resolve a card's port here, so they agree on it
        for p in _machine_profiles().values():
            if p.game_dir == game and _version_key(p.version) == want:
                return p
    return None


#: The tab's message for a card whose title and version have no port.
NO_PORT_HELP = ("Modes of your own can't be made for %s yet: the app has not found in its "
                "program how to run them.")
#: The details behind a no-port sentence, for a tooltip (what a person who writes C can do).
NO_PORT_DETAILS = ("A mode of your own needs to know where this game build keeps the functions "
                   "it calls (a port). tools/spike2_emu/modes/sdk/MODE_SDK.md, section "
                   "\"Making a port for another game or version\", says how to find them by "
                   "hand; a new port file shows up here by itself.")
#: What still works on a card with no port, when the game's own modes were read.
NO_PORT_STILL = "You can still change the timers and awards of its own modes (in the list)."

#: The family's one sentence for a call made with no project open: Try it, Write's set,
#: a new code mode and an example all say this, so the person reads the same fix each time.
NO_PROJECT_HELP = ("Open or extract a card project first (Extract tab). Modes are saved in "
                   "it.")

#: What each runtime name a port could not place IS, in words (:func:`no_port_words`).
_PORT_NEED_WORDS = {
    "tick": "the game's tick",
    "shot_dispatch": "where the game hands out its shots",
    "shots": "the game's shots",
    "ball_end": "the end of a ball",
    "score_add": "how the game adds points",
    "score_add32": "how the game adds points",
    "cur_player": "which player is up",
    "scores": "the players' scores",
    "scores32": "the players' scores",
    "hook_dispatch": "the game's event bus",
    # the words port_derive's PortResult.missing already uses (its _WORDS)
    "its tick": "the game's tick",
    "its shot dispatch": "where the game hands out its shots",
    "its end of ball": "the end of a ball",
    "its score function": "how the game adds points",
    "its current player": "which player is up",
    "its scores": "the players' scores",
    "its shots": "the game's shots",
    "a port that could be derived": "what a mode needs",
    "a port that passes its check": "what a mode needs",
}

#: The contract's placeholder for "nothing was tried yet" (port_derive's first version)
_NO_PORT_PLACEHOLDER = "no port for this build"


def no_port_words(label, missing=()):
    """Why modes cannot be made for the build ``label``: what its port could not place
    (``missing``, from :class:`.port_derive.PortResult`) in words, else
    :data:`NO_PORT_HELP`."""
    said = []
    for m in missing or ():
        m = str(m or "").strip()
        if not m or m == _NO_PORT_PLACEHOLDER:
            continue
        w = _PORT_NEED_WORDS.get(m, m.replace("_", " ") if re.match(r"^[a-z0-9_]+$", m) else m)
        if w.startswith("a reference port"):
            return ("Modes of your own can't be made for %s yet: the app knows no game built the "
                    "same way to work it out from." % label)
        if w not in said:
            said.append(w)
    if not said:
        return NO_PORT_HELP % label
    what = said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]
    return ("Modes of your own can't be made for %s yet: the app could not find %s in its "
            "program." % (label, what))


#: The tab's words for a project that names no card: which game a mode is for comes from
#: the card, and there is no default game.
NO_CARD_HELP = ("This project names no card, so the app does not know which game its modes "
                "are for. Extract a card into it (Extract tab), or pick the card under "
                "\"Try it on\" below.")

_CARD_NAME = re.compile(r"^([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)-(\d+)_(\d+)_(\d+)")


def file_name(path):
    """The last part of a path written on Windows or anywhere else (a project made on one
    system records its card's path in that system's form)."""
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def card_from_name(name):
    """``(game_dir, version)`` from Stern's own card or index naming
    (``godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw`` -> ``godzilla_le``, ``1.16.0``),
    else ``(None, None)``."""
    m = _CARD_NAME.match(file_name(name))
    if not m:
        return None, None
    return m.group(1).lower(), "%s.%s.%s" % (m.group(2), m.group(3), m.group(4))


@dataclass(frozen=True)
class ProjectCard:
    """Which card a project is for."""
    image: str            # the card image the project names
    game_dir: str         # "" = not known yet: a renamed card, see probe_card_title
    version: str          # "1.59.0"; "" = not known
    source: str           # where the answer came from, for the tab to say

    def label(self):
        return ("%s %s" % (self.game_dir, self.version)).strip()


_PROBED = {}


def _probe_key(image):
    st = os.stat(image)
    return os.path.normcase(os.path.abspath(image)), st.st_size, int(st.st_mtime)


def probed_card_title(image):
    """The cached :func:`probe_card_title` answer for ``image``, or None if not probed."""
    try:
        return _PROBED.get(_probe_key(image))
    except OSError:
        return None


def probe_card_title(image):
    """``(game_dir, version)`` read from the card's own ``/spk/index/<game>-<version>.sidx``
    name (it survives a renamed file), else ``(None, None)``. It OPENS THE IMAGE: call it
    off the UI thread. The answer is cached per file size and time."""
    try:
        key = _probe_key(image)
    except OSError:
        return None, None
    if key in _PROBED:
        return _PROBED[key]
    answer = (None, None)
    try:
        from .explorer import CardImage
        with CardImage(image) as card:
            parts = sorted((p for p in card.partitions() if p.browsable),
                           key=lambda p: p.size, reverse=True)
            for part in parts:
                try:
                    entries = card.list_dir(part.index, "/spk/index")
                except Exception:
                    continue
                for e in entries:
                    game, version = card_from_name(e.name)
                    if game and not e.is_dir and e.name.lower().endswith(".sidx"):
                        answer = (game, version)
                        break
                if answer[0]:
                    break
    except Exception:
        answer = (None, None)
    _PROBED[key] = answer
    return answer


def _card_by_name_or_probe(image, exact="", source_from_record=False):
    """A :class:`ProjectCard` for *image* without opening it: its Stern name, else what
    :func:`probe_card_title` has already read of it, else ``game_dir`` "" until a probe."""
    game, version = card_from_name(image)
    if game:
        if exact and source_from_record:
            return ProjectCard(image, game, exact, "the extract's record of the card")
        return ProjectCard(image, game, version, "the card's file name")
    probed = probed_card_title(image)
    if probed and probed[0]:
        return ProjectCard(image, probed[0], exact or probed[1], "the card's own index")
    return ProjectCard(image, "", exact, "")


def project_card(project):
    """Which card ``project`` was made from, or None when it names none (a bare folder:
    the tab then knows no game, :data:`NO_CARD_HELP`). Reads what the project records,
    never the image.

    THE EXTRACT'S RECORD WINS. ``.extract_source.json`` names the card every offset in the
    project was measured on (and the ``card_version`` read from that card's own index), so
    it is the answer whenever it is there - even when its file name does not parse (a
    renamed card): then ``game_dir`` is "" until :func:`probe_card_title` has read the
    card's index, off the UI thread (:func:`project_profile` with ``probe=True``). Before
    2026-09-22 a renamed record lost to the ``.pinproj`` anchor's stock image or Write
    original when one of those parsed, and a set could be prepared for a card the project
    was never measured on. The anchor's paths are read only when the record is absent."""
    if not project or not os.path.isdir(project):
        return None
    from ...core import extract_source, project_file
    rec = extract_source.read_extract_source(project) or {}
    exact = rec.get("card_version") or ""
    recorded = rec.get("input_path") or rec.get("input_name")
    if recorded:
        return _card_by_name_or_probe(str(recorded), exact, source_from_record=True)
    images = []
    if project_file.has_anchor(project):
        try:
            data = project_file.load_anchor(project)
        except (OSError, ValueError):
            data = {}
        paths = data.get("paths") or {}
        images += [data.get("stock_image") or "", paths.get("write_original") or "",
                   paths.get("extract_input") or ""]
    images = [str(i) for i in images if i]
    if not images:
        return None
    for image in images:
        game, version = card_from_name(image)
        if game:
            return ProjectCard(image, game, version, "the card's file name")
    return _card_by_name_or_probe(images[0])


def project_cards(project, try_on=None):
    """``(made_for, try_on)``: the two card ROLES of a Try it (feature/emulate-prepare).

    *made_for* is the card the project's modes and edits were measured on
    (:func:`project_card`: the extract's record first, probed when its name does not
    parse, the anchor's paths only when the record is absent) - the card a set is
    PREPARED FROM. *try_on* is the image to boot, always the path handed in (the live
    Emulate card, never the anchor's lagging copy), as a :class:`ProjectCard` with its
    game and version from its Stern name or an earlier probe, else "" until probed; None
    when no path was given. Neither opens an image, so this can run on the UI thread."""
    made_for = project_card(project)
    run = _card_by_name_or_probe(str(try_on)) if try_on else None
    return made_for, run


def project_profile(project, probe=False):
    """``(card, profile)``: the card ``project`` was made from (:func:`project_card`) and
    the profile of that build's port. ``card`` is None for a project that names no card,
    and ``card.game_dir`` is "" when which game it is cannot be read; in both cases
    ``profile`` is None and each mode keeps the title it was made for. A card whose build
    has no port also gives ``profile`` None (see :data:`NO_PORT_HELP`). ``probe=True``
    reads a renamed card's own index first: it OPENS THE IMAGE, so never on the UI
    thread (a build calls it this way)."""
    card = project_card(project)
    if (probe and card is not None and not card.game_dir and card.image
            and os.path.isfile(card.image)):
        probe_card_title(card.image)
        card = project_card(project)
    if card is None or not card.game_dir:
        return card, None
    return card, profile_for_card(card.game_dir, card.version)


# ---- a mode, as the person authors it ----------------------------------------------
CLIP_KINDS = ("none", "title", "file")
CLIP_WHEN = ("start", "end")


@dataclass
class ModeSpec:
    """Everything a person decides about a mode. Field names are the JSON keys."""
    name: str = "NEW MODE"
    # A mode.json with no "title" was saved before item 148, when Godzilla Pro 1.15 was the
    # only title, so that is what a missing title means. Never a default for a NEW mode:
    # the tab makes each one with its card's title (blank_spec / examples_for).
    title: str = GODZILLA_PRO_1_15.key
    start_shot: str = "Maser target"
    start_count: int = 3
    seconds: int = 30
    scoring_shots: list = field(default_factory=lambda: ["Left ramp", "Right ramp"])
    award: int = 1000000
    # the screen: a panel of our own over the game (item 131)
    screen: bool = True
    screen_title: str = ""               # "" = the mode's name
    screen_art: str = ""                 # a PNG in the mode folder; "" = a generated panel
    panel_color: str = "#146e28"
    title_color: str = "#ffe600"
    # the clip: played full screen on the game's video surface (item 132)
    clip: str = "none"                   # none | title | file
    clip_title: str = ""                 # "" = the mode's name
    clip_file: str = ""                  # a video in the mode folder
    clip_seconds: float = 4.0
    clip_when: str = "start"             # start | end
    # the sound
    countdown: bool = True               # the game's own voice: 10 s, then 5..1
    end_sound: str = ""                  # a WAV in the mode folder; "" = the game's time-up call
    # the lights: the game's own light runner (item 125)
    lights: bool = True
    light_color: str = "#00ff00"
    light_on_raw: str = ""               # Advanced: a whole light command instead
    light_off_raw: str = ""
    # the mode's own sounds beyond its end call (item 150): WAVs in the mode folder, each
    # carried by a stock request the game never plays (mode_sounds.py)
    sound_start: str = ""                # played when the mode starts; "" = none
    sound_shot: str = ""                 # played on scoring shots; "" = none
    sound_shot_every: int = 1            # ... on every Nth scoring shot
    music: str = ""                      # looped under the mode, stopped when it ends; "" = none
    # cut from a film (item 142): WHERE a cut came from, never the film itself. The cut is
    # the mode's clip_file / end_sound / screen_art as usual; these only name the film and
    # the span, so the tab can say what was cut from where. Never in the runtime file.
    clip_source: str = ""                # the film the clip was cut from; "" = not a film cut
    clip_from: float = 0.0               # seconds into that film
    clip_length: float = 0.0             # seconds
    sound_source: str = ""               # the film the end sound was cut from
    sound_from: float = 0.0
    sound_length: float = 0.0
    art_source: str = ""                 # the film the screen's picture is a frame of
    art_from: float = 0.0                # that frame's time, in seconds
    clip_crop: str = ""                  # letterbox | fill: how the clip was cut, so the dialog reopens on it
    art_crop: str = ""                   # letterbox | fill: how the picture was cut
    # stacking (item 140): may it start while the game's own battle or multiball runs?
    stack: bool = True
    # item 141, the Advanced section: every other parameter the runtime has
    award_ladder: str = "rising"         # rising: the Nth shot pays N x; fixed: every shot x 1
    shot_award: list = field(default_factory=list)   # [[shot name, points]]: pays instead of award
    end_shot: str = ""                   # a shot name that ends the mode; "" = the clock only
    clip_both: dict = field(default_factory=dict)    # {} = one clip; else a second clip at the
    #                                      other end: {clip: same|title|file, title, file, seconds}
    callout_at: list = field(default_factory=list)   # [[seconds left, callout id]], on top of
    #                                      the countdown's own
    restore_after: int = 6               # seconds the screen stays up after the mode ends
    # what starts and ends it (item 147): "shot" (start_shot x start_count) or "event <name>";
    # "drain" (its clock or the ball ending), "clock" (its clock only) or "event <name>"
    starts_on: str = "shot"
    ends_on: str = "drain"
    #: keys a newer editor wrote that this one does not know - kept, never dropped
    extra: dict = field(default_factory=dict)
    # how often it can start (item 139): kept PER PLAYER by mode.so
    starts: object = "unlimited"         # unlimited | once_per_game | once_per_ball | N (1..99 a game)
    cooldown: int = 0                    # seconds after it ends before it can start again; 0 = none
    # item 157: the mode on the game's DISPLAY and on the playfield's INSERTS (MODE_SDK.md
    # "Display priority", "Lights: named inserts"); both write nothing at their defaults
    priority: int = 0                    # display priority 1-255 while it runs; 0 = none (180 a mode's)
    light_shots: str = ""                # "" = off; "#rrggbb": the inserts of every shot that scores
    light_shots_pattern: str = "blink"   # solid | blink | pulse | chase

    # ---- JSON ----------------------------------------------------------------
    def to_json(self):
        out = {"format": FORMAT}
        for f in fields(self):
            if f.name != "extra":
                out[f.name] = getattr(self, f.name)
        for k, v in self.extra.items():
            out.setdefault(k, v)
        return out

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            raise ModeProjectError("a mode file holds a JSON object")
        if int(data.get("format", 1)) > FORMAT:
            raise ModeProjectError("this mode was saved by a newer version of the app")
        known = {f.name for f in fields(cls)} - {"extra"}
        spec = cls()
        for k, v in data.items():
            if k == "format":
                continue
            if k in known:
                setattr(spec, k, v)
            else:
                spec.extra[k] = v
        _normalize_starts(spec)
        return spec


# ---- the project folder ------------------------------------------------------------
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "mode"


def modes_dir(project):
    return os.path.join(project, MODES_DIRNAME)


def mode_folder(project, slug):
    return os.path.join(modes_dir(project), slug)


def list_modes(project):
    """``[(slug, ModeSpec)]`` for every mode in the project, in slug order - which is
    also the slot order a build gives them. A folder whose mode.json does not load is
    skipped, and named in the second return value rather than hidden."""
    found, broken = [], []
    d = modes_dir(project)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return found, broken
    for slug in names:
        path = os.path.join(d, slug, MODE_FILE)
        if not os.path.isfile(path):
            continue
        try:
            found.append((slug, load(path)))
        except (OSError, ValueError) as e:
            broken.append((slug, str(e)))
    return found, broken


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return ModeSpec.from_json(json.load(f))


def save(project, slug, spec):
    folder = mode_folder(project, slug)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, MODE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(spec.to_json(), f, indent=2)
        f.write("\n")
    # a reader holding mode.json open (OneDrive, antivirus, the indexer)
    # makes a bare os.replace fail on Windows, and the save is lost
    from ...core.audio_slots import replace_with_retry
    replace_with_retry(tmp, path)
    return path


def new_mode(project, name=None, spec=None):
    """Create a mode: a blank one with valid defaults, or a COPY of ``spec`` (an example).
    ``name`` overrides the spec's. Returns (slug, spec)."""
    existing = {s for s, _ in list_modes(project)[0]}
    if len(existing) >= MAX_MODES:
        raise ModeProjectError("a card holds at most %d modes" % MAX_MODES)
    spec = ModeSpec(name=name or "NEW MODE") if spec is None else ModeSpec.from_json(spec.to_json())
    if name:
        spec.name = name
    base = slugify(spec.name)
    slug, n = base, 2
    while slug in existing or os.path.exists(mode_folder(project, slug)):
        slug, n = "%s_%d" % (base, n), n + 1
    save(project, slug, spec)
    return slug, spec


# ---- the examples -------------------------------------------------------------------
def example_specs():
    """The modes the tab offers ready-made, in menu order, as ``[(name, ModeSpec)]``.

    The first is KAIJU RUSH exactly as it ran on a real Godzilla Premium 1.16
    (2026-09-16: video, audio, scenes and scoring all working) - a mode that is known to
    work, so a person can start from one. The others are variations on it that need no
    file of their own (a generated panel and a title card each), so they build as they
    are; item 143 is where footage from the films replaces the title cards."""
    def make(name, **kw):
        return name, ModeSpec(name=name, **kw)
    return [
        make("KAIJU RUSH", start_shot="Maser target", start_count=3, seconds=30,
             scoring_shots=["Powerline left", "Powerline center", "Powerline right",
                            "Left ramp", "Right ramp"],
             award=1000000, screen=True, clip="title", clip_when="start",
             countdown=True, lights=True, light_color="#00ff00"),
        make("ATOMIC BREATH", start_shot="Godzilla target", start_count=2, seconds=25,
             scoring_shots=["Building", "Left ramp", "Right ramp"], award=750000,
             panel_color="#0b3d91", title_color="#7fe7ff", clip="title", clip_when="start",
             light_color="#00c8ff"),
        make("MOTHRA'S SONG", start_shot="Big loop", start_count=2, seconds=40,
             scoring_shots=["Shield target left", "Shield target right", "Big loop"],
             award=500000, panel_color="#6b4e00", title_color="#fff1a8", clip="title",
             clip_when="end", light_color="#ffd200"),
        make("MECHAGODZILLA", start_shot="Building", start_count=3, seconds=20,
             scoring_shots=["Powerline center", "Maser target", "Godzilla target"],
             award=1500000, panel_color="#3a3a3a", title_color="#ff3b3b", clip="title",
             clip_when="start", light_color="#ff0000"),
    ]


def example(name):
    """The example called ``name``, or None."""
    for n, spec in example_specs():
        if n == name:
            return spec
    return None


# ---- modes for any ported title (item 148) --------------------------------------------
def _switch_off_what_it_cannot(spec, p):
    """Turn off the parts ``p`` cannot do, so a new mode starts buildable and honest."""
    if not p.can("screen"):
        spec.screen = False
    if not p.can("clip"):
        spec.clip = "none"
    if not p.can("lights"):
        spec.lights = False
    if not p.can("countdown"):
        spec.countdown = False
    return spec


def blank_spec(p, name="NEW MODE"):
    """A new mode for title ``p``, valid as it stands. On Godzilla Pro 1.15 it is exactly
    ``ModeSpec(name=name)``; elsewhere the port's example start shot starts it, two of its
    ramps (or its first shots) score, and the parts the title cannot do are off."""
    spec = ModeSpec(name=name, title=p.key)
    names = [n for n, _m in p.shots]
    if spec.start_shot not in names:
        spec.start_shot = p.example_start_shot if p.example_start_shot in names else names[0]
    if not all(s in names for s in spec.scoring_shots):
        ramps = [n for n in names if n.lower().endswith("ramp") and n != spec.start_shot]
        others = [n for n in names if n not in ramps and n != spec.start_shot]
        spec.scoring_shots = (ramps + others)[:2]
    return _switch_off_what_it_cannot(spec, p)


def examples_for(p):
    """The ready-made modes for title ``p``, as ``[(name, ModeSpec)]``: Godzilla's four
    (:func:`example_specs`) wherever every shot each one names exists, else one starter,
    TARGET RUSH, built from the port's example start shot."""
    names = {n for n, _m in p.shots}
    out = []
    for name, spec in example_specs():
        if spec.start_shot in names and all(s in names for s in spec.scoring_shots):
            spec.title = p.key
            out.append((name, _switch_off_what_it_cannot(spec, p)))
    if out:
        return out
    spec = blank_spec(p, "TARGET RUSH")
    return [(spec.name, spec)]


def retarget(spec, p):
    """``spec`` for title ``p``: a COPY whose shots are matched by NAME. Returns
    ``(copy, dropped)``, ``dropped`` being the shot names ``p`` does not have. A start
    shot it lacks becomes the port's example start shot; the parts the title cannot do
    are left as they are (the tab greys them and a build leaves them out)."""
    out = ModeSpec.from_json(spec.to_json())
    names = [n for n, _m in p.shots]
    dropped = []
    if out.start_shot not in names:
        if out.start_shot:
            dropped.append(out.start_shot)
        out.start_shot = p.example_start_shot if p.example_start_shot in names else names[0]
    dropped += [s for s in out.scoring_shots if s not in names]
    out.scoring_shots = [s for s in out.scoring_shots if s in names]
    _retarget_advanced(out, spec.title, p, names, dropped)
    out.title = p.key
    return out, dropped


#: how :func:`retarget` names a callout it dropped, in its ``dropped`` list
CALLOUT_DROPPED = "callout %s"


def dropped_callouts(dropped):
    """The callout entries (``"callout 1291"``) of a :func:`retarget` ``dropped`` list."""
    return [d for d in dropped if isinstance(d, str) and d.startswith(CALLOUT_DROPPED % "")]


def _retarget_advanced(out, old_key, p, names, dropped):
    """Item 141's Advanced fields for title ``p``, matched as :func:`retarget` matches the
    shots (family sweep, 2026-09-17). A per-shot award or an early-ending shot on a shot
    ``p`` lacks is dropped and its name added to ``dropped``: the form cannot show it, so
    kept it would block every build until the file was edited by hand. A callout id made
    on ANOTHER title is a number in that game's sound table, so it is kept only where it is
    a callout both titles measured under the same name (:func:`callout_choices`: Godzilla's
    "Ten seconds left" 1291 is 1387 on Jaws); any other id is dropped as ``"callout <id>"``.
    A row that is not ``[seconds, id]`` is left for :func:`validate` to name."""
    if isinstance(out.shot_award, list):
        kept = []
        for row in out.shot_award:
            shot = row[0] if isinstance(row, (list, tuple)) and len(row) == 2 else None
            if isinstance(shot, str) and shot not in names:
                if shot not in dropped:
                    dropped.append(shot)
                continue
            kept.append(row)
        out.shot_award = kept
    if isinstance(out.end_shot, str) and out.end_shot and out.end_shot not in names:
        if out.end_shot not in dropped:
            dropped.append(out.end_shot)
        out.end_shot = ""
    if old_key == p.key or not isinstance(out.callout_at, list):
        return
    try:
        old = profile(old_key)
    except ModeProjectError:
        old = None
    was = {n: label for label, n in callout_choices(old) if n} if old is not None else {}
    now = {label: n for label, n in callout_choices(p) if n}
    kept = []
    for row in out.callout_at:
        cid = _int_or_none(row[1]) if isinstance(row, (list, tuple)) and len(row) == 2 else None
        if cid is None:
            kept.append(row)
        elif was.get(cid) in now:
            new = now[was[cid]]
            kept.append(row if new == cid else [row[0], new])
        else:
            dropped.append(CALLOUT_DROPPED % cid)
    out.callout_at = kept


def retarget_refusal(spec, dropped, p):
    """Why a build refuses ``spec`` on title ``p``, given :func:`retarget`'s ``dropped``."""
    calls = dropped_callouts(dropped)
    shots = [d for d in dropped if d not in calls]
    words = []
    if shots:
        words.append("names %s, which %s does not have" % (", ".join(shots), p.label))
    if calls:
        words.append("plays %s, %s on %s" % (
            ", ".join(calls), "a sound number of another game and no callout measured"
            if len(calls) == 1 else "sound numbers of another game and no callouts measured",
            p.label))
    return "%s %s: open it in the Modes tab and pick %s for this card." % (
        spec.name, " and ".join(words), "again" if calls else "its shots")


def duplicate_mode(project, slug):
    """Copy a mode's whole folder (its art, clip and sound too) under a new name."""
    specs = dict(list_modes(project)[0])
    if slug not in specs:
        raise ModeProjectError("no mode called %r" % slug)
    if len(specs) >= MAX_MODES:
        raise ModeProjectError("a card holds at most %d modes" % MAX_MODES)
    spec = specs[slug]
    new_name = spec.name + " COPY"
    base = slugify(new_name)
    new_slug, n = base, 2
    while new_slug in specs or os.path.exists(mode_folder(project, new_slug)):
        new_slug, n = "%s_%d" % (base, n), n + 1
    shutil.copytree(mode_folder(project, slug), mode_folder(project, new_slug))
    spec.name = new_name
    save(project, new_slug, spec)
    return new_slug, spec


def delete_mode(project, slug):
    folder = mode_folder(project, slug)
    if os.path.isfile(os.path.join(folder, MODE_FILE)):
        shutil.rmtree(folder)


# ---- checking it -------------------------------------------------------------------
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate(spec, folder=None):
    """Every reason this mode cannot be built, as sentences. Empty = buildable."""
    out = []
    try:
        p = profile(spec.title)
    except ModeProjectError as e:
        return [str(e)]
    names = dict(p.shots)
    if not spec.name.strip():
        out.append("The mode needs a name.")
    if spec.start_shot not in names:
        out.append("Pick the shot that starts the mode.")
    if int(spec.start_count) < 1:
        out.append("It has to take at least one shot to start.")
    if int(spec.seconds) < 1:
        out.append("It has to run for at least a second.")
    if not spec.scoring_shots:
        out.append("Pick at least one shot that scores while it runs.")
    for s in spec.scoring_shots:
        if s not in names:
            out.append("%s has no shot called %r." % (p.label, s))
    if int(spec.award) < 1:
        out.append("The first shot has to be worth something.")
    for label, value in (("panel colour", spec.panel_color), ("title colour", spec.title_color),
                         ("light colour", spec.light_color)):
        if not _COLOR.match(value or ""):
            out.append("The %s is not a colour like #00ff00." % label)
    if spec.clip not in CLIP_KINDS:
        out.append("The clip is none, a title card, or a video file.")
    if spec.clip_when not in CLIP_WHEN:
        out.append("The clip plays at the start or at the end.")
    if spec.clip == "title" and not 1 <= float(spec.clip_seconds) <= 30:
        out.append("A title-card clip runs 1 to 30 seconds.")
    for label, name, used in (("screen art", spec.screen_art, spec.screen),
                              ("clip", spec.clip_file, spec.clip == "file"),
                              ("end sound", spec.end_sound, bool(spec.end_sound))):
        if used and folder is not None and name and not os.path.isfile(os.path.join(folder, name)):
            out.append("The %s file %s is not in the mode's folder." % (label, name))
    if spec.clip == "file" and not spec.clip_file:
        out.append("Choose the video file for the clip.")
    out += _validate_own_sounds(spec, folder)
    out += validate_starts(spec)
    out += _validate_film_cut(spec, folder)
    out += validate_parameters(spec, p, folder)
    out += _validate_starts_ends(spec, p)
    out += validate_display_lights(spec)
    return out


# ---- item 142: cuts from a film ------------------------------------------------------
FILM_CUT_MAX_SECONDS = 30


def _validate_film_cut(spec, folder=None):
    """Item 142: what is wrong with where a mode's cuts from a film came from, as
    sentences. A mode keeps the CUT and only names the film, so a film copied into the
    mode's folder is refused: a card holds seconds, not reels."""
    out, films = [], set()

    def num(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    for label, source, start, length in (
            ("clip", spec.clip_source, spec.clip_from, spec.clip_length),
            ("sound", spec.sound_source, spec.sound_from, spec.sound_length),
            ("picture", spec.art_source, spec.art_from, None)):
        if not source:
            continue
        s = num(start)
        if s is None or s < 0:
            out.append("The %s's time in the film is 0:00 or later." % label)
        if length is not None:
            n = num(length)
            if n is None or not 0 < n <= FILM_CUT_MAX_SECONDS:
                out.append("A %s cut from a film runs up to %d seconds." % (label, FILM_CUT_MAX_SECONDS))
        name = os.path.basename(str(source).replace("\\", "/"))
        if (folder is not None and name and name not in films
                and name not in (spec.clip_file, spec.end_sound, spec.screen_art)
                and os.path.isfile(os.path.join(folder, name))):
            films.add(name)
            out.append("The film %s is in the mode's folder; a mode keeps only the cut." % name)
    for label, crop in (("clip", spec.clip_crop), ("picture", spec.art_crop)):
        if crop not in ("", "letterbox", "fill"):
            out.append("The %s's crop is letterbox or fill." % label)
    return out


def starts_on_event(spec):
    """The event name a mode starts on, or None when it starts on its shot (item 147)."""
    words = (spec.starts_on or "shot").split()
    return words[1] if len(words) >= 2 and words[0] == "event" else None


def ends_on_parts(spec):
    """``("drain" | "clock" | "event", event name or None)`` (item 147)."""
    words = (spec.ends_on or "drain").split()
    if words and words[0] == "event":
        return "event", words[1] if len(words) >= 2 else None
    return (words[0] if words else "drain"), None


def _validate_starts_ends(spec, p):
    out = []
    words = (spec.starts_on or "shot").split()
    events = tuple(getattr(p, "events", ()) or ())
    if words[0] not in ("shot", "event"):
        out.append("A mode starts on a shot or on one of the game's events.")
    elif words[0] == "event":
        name = starts_on_event(spec)
        if not name:
            out.append("Pick the event that starts the mode.")
        elif name not in events:
            out.append("%s has no event %r to start on." % (p.label, name))
    kind, name = ends_on_parts(spec)
    if kind not in ("drain", "clock", "event"):
        out.append("A mode ends on the drain, on its clock only, or on one of the game's events.")
    elif kind == "event":
        if not name:
            out.append("Pick the event that ends the mode.")
        elif name not in events:
            out.append("%s has no event %r to end on." % (p.label, name))
    return out


# ---- what the build generates, and the runtime file --------------------------------
def asset_names(slug):
    """The names a build gives this mode's assets. Derived from the SLUG, not the slot,
    so reordering modes never renames anything; prefixed so they cannot collide with a
    stock node or clip."""
    stem = "PadMode_" + re.sub(r"[^A-Za-z0-9]", "_", slug)
    return {
        "screen_node": stem + "_Screen",
        "screen_text": stem + "_Screen." + stem + "_Screen_Words",
        "clip": stem + "_Clip",
    }


def light_commands(spec, p):
    """(on, off) in the game's own light language. The colour sweep and the fade are
    tesla strike's own award pair (proven on the lamps, item 125) with our colour."""
    if spec.light_on_raw.strip() or spec.light_off_raw.strip():
        return spec.light_on_raw.strip(), spec.light_off_raw.strip()
    r, g, b = (int(spec.light_color[i:i + 2], 16) for i in (1, 3, 5))
    on = ("blele --sweep 0 --lts %d --red %d --green %d --blue %d --freq 10 --use_alpha 1 --alpha 255"
          % (p.light_lts, r, g, b))
    off = "blele --sweep 1 --lts %d --fade 20 --rgb 0 --freq 10 --delay_start 15 --end 1" % p.light_lts
    return on, off


def runtime_cfg(spec, slug, sound_key=None, own_sounds=None, own_sound_ms=None):
    """The file ``mode.so`` reads, generated. ``sound_key`` is the 16-hex container key of
    the mode's own end sound once a build has appended it; without one the game's own
    time-up callout plays. ``own_sounds`` is this mode's carriers once a build has put its
    sounds in the bank (``mode_sounds.assign_specs``): ``{"sound_start": request, ...}``.
    ``own_sound_ms`` is the calls' own lengths (``mode_sounds.call_ms``), so mode.so stops a
    carrier when its sound is over instead of holding the voice bus through the silence."""
    problems = validate(spec)
    if problems:
        raise ModeProjectError(" ".join(problems))
    p = profile(spec.title)
    names = asset_names(slug)
    lines = [
        "# GENERATED by the Modes tab from modes/%s/mode.json - edit the mode there." % slug,
        "name           %s" % spec.name.strip(),
        "trigger        0x%08x %d" % (p.mask([spec.start_shot]), int(spec.start_count)),
        "seconds        %d" % int(spec.seconds),
        "shots          0x%08x" % p.mask(spec.scoring_shots),
        "award          %d" % int(spec.award),
    ]
    if spec.screen and p.can("screen"):
        lines += [
            "screen_scene   %s" % p.hud_scene,
            "screen_node    %s" % names["screen_node"],
            "screen_text    %s" % names["screen_text"],
            "restore_after  %d" % int(spec.restore_after),
        ]
    if spec.clip != "none" and p.can("clip"):
        lines.append("%-14s %s" % ("clip_start" if spec.clip_when == "start" else "clip_end", names["clip"]))
    if spec.lights and p.can("lights") and p.light_route == "inserts":
        lines.append("light_all      %s pulse" % spec.light_color.lstrip("#").lower())
    elif spec.lights and p.can("lights"):
        on, off = light_commands(spec, p)
        lines.append("light_owner    %d" % p.light_owner)
        if on:
            lines.append("light_on       %s" % on)
        if off:
            lines.append("light_off      %s" % off)
    if spec.countdown and p.can("countdown"):
        if p.callout_ten_seconds:             # a title may have the 5..1 count and no ten-seconds call
            lines.append("callout_at     10 %d" % p.callout_ten_seconds)
        lines.append("callout_count  %d" % p.callout_countdown)
    if spec.end_sound and sound_key and p.can("own_sound"):
        lines += ["sound_key      %s" % sound_key, "sound_callout  %d" % p.callout_time_up]
    elif p.callout_time_up:
        lines.append("callout_end    %d" % p.callout_time_up)
    lines += starts_cfg_lines(spec)
    lines += own_sound_lines(spec, own_sounds, own_sound_ms)
    if not spec.stack:                      # item 140: only when off, so older files are unchanged
        lines.append("stack          no")
    lines += parameter_lines(spec, slug, p)
    lines += display_light_lines(spec)
    lines = _starts_ends_lines(spec, lines)
    return "\n".join(lines) + "\n"


# ---- item 157: the display priority and the lit shots ------------------------------------
#: ``light_shots_pattern`` values: what mode_file.c's ``light_shots`` takes
LIGHT_PATTERNS = ("solid", "blink", "pulse", "chase")
#: the display priority the tab suggests: a mode's (MODE_SDK.md "Display priority")
DISPLAY_PRIORITY_MODE = 180


def _priority_value(spec):
    """``spec.priority`` as an int 0..255; None when it is not one."""
    v = spec.priority
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and 0 <= v <= 255 else None


def validate_display_lights(spec):
    """The reasons ``priority`` / ``light_shots`` cannot be built, as sentences."""
    out = []
    if _priority_value(spec) is None:
        out.append("The display priority is 0 (none) to 255; 180 puts the mode over the game's shot awards.")
    colour = spec.light_shots
    if colour and not (isinstance(colour, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", colour)):
        out.append("The colour of the lit shots is not a colour like #ff6000.")
    if spec.light_shots_pattern not in LIGHT_PATTERNS:
        out.append("The lit shots are solid, blink, pulse or chase.")
    return out


def display_light_lines(spec):
    """The mode-file lines for the display priority and the lit shots (mode_file.c's
    ``priority`` and ``light_shots``). Nothing at the defaults, so every file generated
    before item 157 stays byte-identical; an older mode.so logs the keys and skips them."""
    lines = []
    prio = _priority_value(spec)
    if prio:
        lines.append("%-14s %d" % ("priority", prio))
    if spec.light_shots:
        lines.append("%-14s %s %s" % ("light_shots", spec.light_shots.lstrip("#").lower(), spec.light_shots_pattern))
    return lines


# ---- a mode's own sounds (item 150) ---------------------------------------------------
def _validate_own_sounds(spec, folder):
    out = []
    for label, name in (("start sound", spec.sound_start), ("shot sound", spec.sound_shot),
                        ("music", spec.music)):
        if name and folder is not None and not os.path.isfile(os.path.join(folder, name)):
            out.append("The %s file %s is not in the mode's folder." % (label, name))
    try:
        every = int(spec.sound_shot_every)
    except (TypeError, ValueError):
        every = 0
    if spec.sound_shot and every < 1:
        out.append("The shot sound plays on every shot, or every 2nd, 3rd...")
    return out


def own_sound_lines(spec, own_sounds, ms=None):
    """The mode-file lines for the sounds this mode has a WAV for AND a carrier: the
    ``sound_start`` / ``sound_shot`` / ``sound_end`` / ``music`` keys mode_file.c reads. The
    end call's WAV is ``end_sound``. Older mode.so files skip these keys and play the stock
    calls, which ``callout_end`` above still names. *ms* is the calls' own lengths
    (``mode_sounds.call_ms``), written after each call's request."""
    if not own_sounds:
        return []
    from . import mode_sounds as MS
    have = {"sound_start": spec.sound_start, "sound_shot": spec.sound_shot,
            "sound_end": spec.end_sound, "music": spec.music}
    picked = {k: r for k, r in own_sounds.items() if have.get(k)}
    if "music" in picked and own_sounds.get("music_sid"):
        picked["music_sid"] = own_sounds["music_sid"]      # item 150 follow-up: its own bed
    lines = MS.cfg_lines(picked, shot_every=int(spec.sound_shot_every or 1), ms=ms)
    carried = {int(r) for k, r in picked.items() if k in MS.SOUND_KEYS}
    # item 163: the carriers whose own record key the mode swaps for its appended record's
    lines += ["swap           %d %s %s" % (int(r), stock, ours)
              for r, stock, ours in own_sounds.get("swaps") or () if int(r) in carried]
    return lines


# ---- how often a mode can start (item 139) -------------------------------------------
#: ``starts`` values other than a count. A count N (1..99) means "up to N times a game".
STARTS_POLICIES = ("unlimited", "once_per_game", "once_per_ball")
STARTS_MAX = 99
COOLDOWN_MAX = 3600


def _normalize_starts(spec):
    """A count or a cooldown typed as text ("3") becomes a number; anything else is left
    as it is, for :func:`validate_starts` to name."""
    for name in ("starts", "cooldown"):
        v = getattr(spec, name)
        if isinstance(v, str) and v.strip().isdigit():
            setattr(spec, name, int(v.strip()))
        elif isinstance(v, float) and v.is_integer():
            setattr(spec, name, int(v))


def _starts_value(spec):
    """``spec.starts`` as a policy name or an int 1..99; None when it is neither."""
    v = spec.starts
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in STARTS_POLICIES:
            return s
        if not s.isdigit():
            return None
        v = int(s)
    if isinstance(v, int) and 1 <= v <= STARTS_MAX:
        return v
    return None


def _cooldown_value(spec):
    """``spec.cooldown`` as an int 0..3600; None when it is not one."""
    v = spec.cooldown
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, int) and 0 <= v <= COOLDOWN_MAX:
        return v
    return None


def validate_starts(spec):
    """The reasons ``starts`` / ``cooldown`` cannot be built, as sentences."""
    out = []
    if _starts_value(spec) is None:
        out.append("How often it can start is once a game, once a ball, any number of times, "
                   "or up to 1 to %d times a game." % STARTS_MAX)
    if _cooldown_value(spec) is None:
        out.append("The wait after it ends is 0 to %d seconds." % COOLDOWN_MAX)
    return out


def starts_cfg_lines(spec):
    """The mode-file lines for ``starts`` and ``cooldown``. Nothing for the defaults
    (any number of times, no wait), so every file generated before item 139 - the one
    KAIJU RUSH ran on a real machine with included - stays byte-identical, and an older
    ``mode.so`` never meets a key it would skip."""
    lines = []
    starts, cooldown = _starts_value(spec), _cooldown_value(spec)
    if starts is not None and starts != "unlimited":
        lines.append("%-14s %s" % ("starts", starts))
    if cooldown:
        lines.append("%-14s %d" % ("cooldown", cooldown))
    return lines


def starts_words(spec):
    """How often the mode can start, in words - what the Modes tab shows."""
    starts, cooldown = _starts_value(spec), _cooldown_value(spec)
    if starts is None:
        words = "Can start: (choose how often)"
    elif starts == "unlimited":
        words = "Can start: any number of times"
    elif starts == "once_per_game":
        words = "Can start: once a game, for each player"
    elif starts == "once_per_ball":
        words = "Can start: once a ball, for each player"
    elif starts == 1:
        words = "Can start: once a game, for each player"
    else:
        words = "Can start: up to %d times a game, for each player" % starts
    if cooldown:
        words += "; not again until %d s after it ends" % cooldown
    return words


# ---- item 141: the Advanced section's parameters ---------------------------------------
AWARD_LADDERS = ("rising", "fixed")
SECOND_CLIP_KINDS = ("same", "title", "file")
#: the runtime's limits (sdk/mode_file.c): SHOT_AWARD_MAX, and CALLOUT_AT_MAX less the one
#: the countdown uses
SHOT_AWARD_MAX = 16
CALLOUT_AT_MAX = 8
RESTORE_AFTER_MAX = 60
#: how many sound requests (callout ids) each title's game has: read from the game ELF's
#: request table (sound_requests.locate_sound_requests; item 141 on the Pro 1.15 card, where
#: request 1295 chains to sid 1998 as item 130 found). An id at or past it is no callout.
CALLOUT_REQUESTS = {"godzilla_pro_1_15": 2030}


def second_clip_name(slug):
    """The bank name of a mode's SECOND clip (clip_both title or file)."""
    return asset_names(slug)["clip"] + "2"


def callout_choices(p):
    """``[(label, id)]``: the title's callouts a mode can play at a chosen second. Only ids
    measured to play are named (item 125 on Godzilla Pro 1.15: the ten-seconds call and the
    time-up call); any other id is typed by hand."""
    return [("Ten seconds left", p.callout_ten_seconds), ("Time is up", p.callout_time_up)]


def _int_or_none(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


#: The most one award may be on a title with 32-bit scores (TitleProfile.score_bits 32): the
#: game multiplies it by a byte multiplier and adds it with no carry check, so this is what 255x
#: still fits in 32 bits. pad_mode_runtime.c also cuts each award to the room left in the score.
SCORE32_AWARD_MAX = 0xffffffff // 255


def validate_parameters(spec, p, folder=None):
    """The Advanced section's reasons this mode cannot be built, as sentences."""
    out = []
    names = dict(p.shots)
    if getattr(p, "score_bits", 64) == 32:
        big = _int_or_none(spec.award)
        if big is not None and big > SCORE32_AWARD_MAX:
            out.append("%s keeps its scores in 32 bits, so a shot can pay at most %s points."
                       % (p.label, format(SCORE32_AWARD_MAX, ",")))
    if spec.award_ladder not in AWARD_LADDERS:
        out.append("The award ladder is rising or fixed.")
    if not isinstance(spec.shot_award, list):
        out.append("The per-shot awards are a list of [shot, points].")
    else:
        if len(spec.shot_award) > SHOT_AWARD_MAX:
            out.append("A mode can set its own points on at most %d shots." % SHOT_AWARD_MAX)
        seen = set()
        for row in spec.shot_award:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                out.append("A per-shot award is [shot, points].")
                continue
            shot, points = row
            if not isinstance(shot, str):               # hand-edited JSON: a list is no name
                out.append("A per-shot award is [shot, points].")
                continue
            if shot not in names:
                out.append("%s has no shot called %r to pay its own points." % (p.label, shot))
            elif shot in seen:
                out.append("%s has its own points twice." % shot)
            seen.add(shot)
            n = _int_or_none(points)
            if n is None or n < 1:
                out.append("%s's own points must be a whole number above 0." % shot)
            elif getattr(p, "score_bits", 64) == 32 and n > SCORE32_AWARD_MAX:
                out.append("%s's own points can be at most %s: %s keeps its scores in 32 bits."
                           % (shot, format(SCORE32_AWARD_MAX, ","), p.label))
    if spec.end_shot and (not isinstance(spec.end_shot, str) or spec.end_shot not in names):
        out.append("%s has no shot called %r to end the mode." % (p.label, spec.end_shot))
    both = spec.clip_both
    if not isinstance(both, dict):
        out.append("The second clip is not set up right.")
    elif both:
        kind = both.get("clip")
        if kind not in SECOND_CLIP_KINDS:
            out.append("The second clip is the same clip, a title card, or a video file.")
        if spec.clip == "none":
            out.append("A second clip plays at the other end from the first: choose the first clip.")
        if kind == "title":
            secs = both.get("seconds", 4.0)
            try:
                ok = 1 <= float(secs) <= 30
            except (TypeError, ValueError):
                ok = False
            if not ok:
                out.append("A title-card second clip runs 1 to 30 seconds.")
        if kind == "file":
            name = both.get("file") or ""
            if not name:
                out.append("Choose the video file for the second clip.")
            elif folder is not None and not os.path.isfile(os.path.join(folder, name)):
                out.append("The second clip file %s is not in the mode's folder." % name)
    if not isinstance(spec.callout_at, list):
        out.append("The callouts at chosen seconds are a list of [seconds left, id].")
    else:
        room = CALLOUT_AT_MAX - (1 if spec.countdown else 0)
        if len(spec.callout_at) > room:
            out.append("A mode can make at most %d callouts at chosen seconds%s." %
                       (room, " besides the countdown's" if spec.countdown else ""))
        for row in spec.callout_at:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                out.append("A callout at a chosen second is [seconds left, id].")
                continue
            secs, cid = _int_or_none(row[0]), _int_or_none(row[1])
            if secs is None or not 0 <= secs < max(1, _int_or_none(spec.seconds) or 0):
                out.append("A callout at %s seconds left must be under the mode's %s seconds."
                           % (row[0], spec.seconds))
            limit = CALLOUT_REQUESTS.get(p.key, 0x10000)
            if cid is None or not 1 <= cid < limit:
                out.append("Callout id %r is not a callout number (%s has 1 to %d)."
                           % (row[1], p.label, limit - 1))
    # restore_after is written only with the mode's own screen (runtime_cfg), so it is
    # checked only then: a value that does nothing never blocks a build
    ra = _int_or_none(spec.restore_after)
    if spec.screen and (ra is None or not 1 <= ra <= RESTORE_AFTER_MAX):
        out.append("The screen stays up 1 to %d seconds after the mode ends." % RESTORE_AFTER_MAX)
    return out


def parameter_lines(spec, slug, p):
    """The runtime lines for the Advanced section. Nothing at its defaults, so a mode that
    never opens it generates the same bytes as before item 141."""
    lines = []
    names = asset_names(slug)
    if spec.award_ladder == "fixed":
        lines.append("award_ladder   fixed")
    for shot, points in spec.shot_award:
        lines.append("shot_award     0x%08x %d" % (p.mask([shot]), _int_or_none(points)))
    if spec.end_shot:
        lines.append("end_shot       0x%08x" % p.mask([spec.end_shot]))
    if spec.clip_both and spec.clip != "none" and p.can("clip"):   # item 148 (j): no clip, no second
        other = "clip_end" if spec.clip_when == "start" else "clip_start"
        name = names["clip"] if spec.clip_both.get("clip") == "same" else second_clip_name(slug)
        lines.append("%-14s %s" % (other, name))
    for secs, cid in spec.callout_at:
        lines.append("callout_at     %d %d" % (_int_or_none(secs), _int_or_none(cid)))
    return lines


def _starts_ends_lines(spec, lines):
    """Item 147: an event start REPLACES the trigger line (so a mode.so older than events
    logs the file NOT VALID rather than starting it on a shot); a start on a shot and an
    end on the drain write exactly what they wrote before."""
    event = starts_on_event(spec)
    out = list(lines)
    if event:
        out = [line for line in out if not line.startswith("trigger ")]
        out.insert(2, "starts_on      event %s" % event)
    kind, name = ends_on_parts(spec)
    if kind == "clock":
        out.append("ends_on        clock")
    elif kind == "event" and name:
        out.append("ends_on        event %s" % name)
    return out
