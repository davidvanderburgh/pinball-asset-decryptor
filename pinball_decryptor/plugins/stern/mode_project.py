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
    insider_gate: bool = False   # item 166: the port names agent_header + agent_begin, so the runtime
    #                              keeps every score report off Insider Connected (a must for a card)
    switch_shots: tuple = ()     # names in ``shots`` that come from the port's `switch` lines
    switch_shots_note: str = ""  # why those are not proven yet; "" when they are (or there are none)
    stack_note: str = ""         # item 164: what ``stack no`` waits for when it is less than every mode
    game_modes: tuple = ()       # PAD-363: ((id, name, held off by default), ...) the game's own modes a
    #                              mode can keep from starting (the port's block_start_<id> lines)
    game_rules: tuple = ()       # PAD-398: ((n, name), ...) the game's rules (its features) that see no
    #                              shots while a mode blocks, unless it keeps them (block_rule_<n> lines)
    lamps: int = -1              # named inserts tied to a shot the runtime can light (PM_CAN_LAMPS);
    #                              0 = none, so "Light the shots that score" lights nothing; -1 = not counted
    light_route: str = ""        # item 164: how a mode's Lights run - "language" (the game's own light
    #                              commands: Godzilla), "inserts" (every insert held in the mode's colour), ""
    bank_tree: str = "auto_loaded"   # item 164: the lcd tree the video bank is in (JP LE, Avengers,
    hud_tree: str = "auto_loaded"    # Iron Maiden keep it in demand_loaded) - and the HUD scene's
    magnet_shot: str = ""            # PAD-381: the shot whose hit is the ball over the magnet; "" = no magnet
    held_coils: tuple = ()           # PAD-381: ((name, label), ...) the other coils a mode may hold, proven ones only
    coil_caps: tuple = ()            # PAD-420: ((name, ms), ...) a held coil's longest hold where the game's own
    #                                  longest command on it is shorter than COIL_MAX_MS (its `_drive` line's last word)
    shield_rule: str = ""            # PAD-392: the game's own shield feature (the port's `text shield_rule`, one of
    #                                  game_rules): it turns the platform back while it counts shots
    game_shows: tuple = ()           # PAD-418: ((name, kind, secs), ...) the game's own light shows a mode can play
    #                                  (the port's show_<n> lines, in number order; kind flashy / subdued / accent)
    absent: tuple = ()               # PAD-420: HARDWARE_PARTS this machine does not have (machine_absent): the tab
    #                                  leaves their sections out rather than saying why they cannot be used

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
        # PAD-228: the cabinet buttons, from the framework's switch drain (the port's `switch` lines)
        ("Action button", 0x1000000000000000),
        ("Left flipper button", 0x2000000000000000),
        ("Right flipper button", 0x4000000000000000),
    ),
    switch_shots=("Action button", "Left flipper button", "Right flipper button"),
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
    insider_gate=True,
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
PARTS = ("countdown", "lights", "screen", "clip", "own_sound", "stack", "events", "multiball", "ball_save",
         "magnet", "scoop", "coils", "shield", "shows")

#: PAD-420: the parts that are a piece of the machine. A machine without one has no section for it on the tab.
HARDWARE_PARTS = ("magnet", "scoop", "coils", "shield", "shaker")

#: PAD-420: which of HARDWARE_PARTS each model's machine has, by its game directory (the same machine on every
#: version), from the coil names in each newest build's device table: a magnet that catches the ball (not
#: Metallica's grave marker or electric chair, which fling it), a scoop / VUK / eject the ball settles in, another
#: mechanism a mode may hold (a second magnet, a diverter, a gate, an up post; not a lock post), the shield
#: platform's motor, the shaker motor. Foo Fighters' parts were first read off its adjustments (the Overlord magnet,
#: the upper playfield diverter, the outlane up post); its device tables name them now, and the Pro's has only the
#: van up post of them. Venom's scoops are named
#: by its switches and adjustments (the center and 180 scoops), not by a coil. A game directory not listed here
#: shows every section.
MACHINE_HARDWARE = {
    "aerosmith": ("magnet", "scoop", "shaker"),
    "aerosmith_le": ("magnet", "scoop", "coils", "shaker"),
    "avengers_infinity_le": ("magnet", "scoop", "coils"),
    "avengers_infinity_pro": ("magnet", "coils"),
    "batman": ("magnet", "scoop", "coils"),
    "beatles": ("magnet", "coils"),
    "deadpool_le": ("scoop", "coils"),
    "deadpool_pro": ("scoop", "coils"),
    "dungeons_and_dragons_le": ("magnet", "scoop", "coils"),
    "dungeons_and_dragons_pro": ("magnet", "scoop", "coils"),
    "elvira3": ("scoop", "coils", "shaker"),
    "foo_fighters_le": ("magnet", "coils"),
    "foo_fighters_pro": ("coils",),       # run 21: its device table (the names resolve now) has no OVERLORD MAGNET - the LE's only
    "godzilla_le": ("magnet", "scoop", "coils", "shield"),
    "godzilla_pro": ("magnet", "scoop"),
    "guardians": ("magnet", "scoop", "coils", "shaker"),
    "guardians_le": ("magnet", "scoop", "coils", "shaker"),
    "iron_maiden_le": ("scoop", "coils"),
    "iron_maiden_pro": ("coils",),
    "james_bond_60th_le": ("scoop", "coils"),
    "james_bond_le": ("magnet", "scoop", "coils"),
    "james_bond_pro": ("scoop", "coils"),
    "jaws_le": ("coils",),
    "jaws_pro": ("coils",),
    "john_wick_le": ("scoop", "coils"),
    "john_wick_pro": ("scoop",),
    "jurassic_park_le": ("magnet", "coils"),
    "jurassic_park_pro": ("coils",),
    "jurassic_park_the_pin": ("coils",),
    "king_kong_le": ("magnet", "scoop", "coils"),
    "king_kong_pro": ("magnet", "scoop", "coils"),
    "led_zeppelin_le": ("magnet", "scoop", "coils", "shaker"),
    "led_zeppelin_pro": ("scoop", "coils", "shaker"),
    "mando_le": ("magnet", "scoop", "coils", "shaker"),
    "mando_pro": ("scoop", "coils", "shaker"),
    "metallica_spike": ("magnet", "scoop", "coils"),
    "munsters_le": ("magnet", "scoop", "coils", "shaker"),
    "munsters_pro": ("magnet", "scoop", "coils", "shaker"),
    "rush_le": ("magnet", "scoop", "coils", "shaker"),
    "rush_pro": ("magnet", "scoop", "coils", "shaker"),
    "star_wars_elg": ("coils",),
    "star_wars_le": ("scoop", "coils"),
    "star_wars_pro": ("scoop", "coils"),
    "stranger_things": ("scoop", "coils"),
    "stranger_things_le": ("scoop", "coils"),
    "sword_of_rage_le": ("magnet", "scoop", "coils", "shaker"),
    "sword_of_rage_pro": ("magnet", "scoop", "coils", "shaker"),
    "turtles_le": ("magnet", "coils", "shaker"),
    "turtles_pro": ("magnet", "coils", "shaker"),
    "uncanny_xmen_le": ("magnet", "coils"),
    "uncanny_xmen_pro": ("magnet", "coils"),
    "venom_le": ("scoop", "coils", "shaker"),
    "venom_pro": ("scoop", "coils", "shaker"),
}


def machine_absent(game_dir):
    """PAD-420: the HARDWARE_PARTS game ``game_dir``'s machine does not have, as a tuple; () for a machine not in
    MACHINE_HARDWARE (every section shows)."""
    has = MACHINE_HARDWARE.get(game_dir)
    if has is None:
        return ()
    return tuple(p for p in HARDWARE_PARTS if p not in has)


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
    "deadpool_le-1.16",                  # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's battles started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Battle Mystique: the runtime says one of the game's modes (cbattle_mystique) is running | WAITER not started (trigger file): one of the game's modes (cbattle_mystique) is running
    "dungeons_and_dragons_le-1.10",      # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's battles started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Mimic Hurry Up: the runtime says one of the game's modes (cmimic_hurry_up) is running | WAITER not started (trigger file): one of the game's modes (cmimic_hurry_up) is running
    "foo_fighters_pro-1.04",             # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's battles started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Super Skill Shot: the runtime says one of the game's modes (csuper_skill_shot) is running | WAITER not started (trigger file): one of the game's modes (csuper_skill_shot) is running
    "iron_maiden_le-1.18",               # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's battles started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Soul Shard Hurry Up: the runtime says one of the game's modes (cmode_soul_shard_hurry_up) is running | WAITER not started (trigger file): one of the game's modes (cmode_soul_shard_hurry_up) is running
    "iron_maiden_pro-1.18",              # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's battles started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Soul Shard Hurry Up: the runtime says one of the game's modes (cmode_soul_shard_hurry_up) is running | WAITER not started (trigger file): one of the game's modes (cmode_soul_shard_hurry_up) is running
    "john_wick_pro-1.02",                # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Tick Tock: the runtime says one of the game's modes (cmode_tick_tock) is running | WAITER not started (trigger file): one of the game's modes (cmode_tick_tock) is running
                                         # re-run 2026-10-08 with its locations base play (440aecb0): the same, Tick Tock refused it
    "munsters_pro-1.28",                 # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Lily Mode: the runtime says one of the game's modes (clily_mode) is running | WAITER not started (trigger file): one of the game's modes (clily_mode) is running
    "rush_le-1.19",                      # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started La Villa Strangiato: the runtime says one of the game's modes (cmode_la_villa_strangiato) is running | WAITER not started (trigger file): one of the game's modes (cmode_la_villa_strangiato) is running
    "sword_of_rage_le-1.19",             # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Sand Worm: the runtime says one of the game's modes (cmode_sand_worm) is running | WAITER not started (trigger file): one of the game's modes (cmode_sand_worm) is running
    "sword_of_rage_pro-1.19",            # PAD-420 2026-10-07 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Sand Worm: the runtime says one of the game's modes (cmode_sand_worm) is running | WAITER not started (trigger file): one of the game's modes (cmode_sand_worm) is running
    "avengers_infinity_le-1.10",         # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Soul Gem: the runtime says one of the game's modes (cmode_soul_gem) is running | WAITER not started (trigger file): one of the game's modes (cmode_soul_gem) is running
    "avengers_infinity_pro-1.10",        # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Soul Gem: the runtime says one of the game's modes (cmode_soul_gem) is running | WAITER not started (trigger file): one of the game's modes (cmode_soul_gem) is running
    "dungeons_and_dragons_pro-1.10",     # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Mimic Hurry Up: the runtime says one of the game's modes (cmimic_hurry_up) is running | WAITER not started (trigger file): one of the game's modes (cmimic_hurry_up) is running
    "jurassic_park_pro-1.16",            # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Trex Chase: the runtime says one of the game's modes (cmode_trex_chase) is running | WAITER not started (trigger file): one of the game's modes (cmode_trex_chase) is running
    "rush_pro-1.19",                     # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started La Villa Strangiato: the runtime says one of the game's modes (cmode_la_villa_strangiato) is running | WAITER not started (trigger file): one of the game's modes (cmode_la_villa_strangiato) is running
    "star_wars_le-1.31",                 # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Hoth I: the runtime says one of the game's modes (choth_i) is running | WAITER not started (trigger file): one of the game's modes (choth_i) is running
    "star_wars_pro-1.31",                # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Hoth I: the runtime says one of the game's modes (choth_i) is running | WAITER not started (trigger file): one of the game's modes (choth_i) is running
    "venom_pro-1.07",                    # PAD-420 2026-10-08 st3_job (stock card, hidden, muted; re-run on the direct harness): a stack no mode started with nothing of the game's running; one of the game's modes started through its own start (the port's block start) and the mode, asked for at once, was refused while it ran: stackgo: started Riot Mode: the runtime says one of the game's modes (criot_mode) is running | WAITER not started (trigger file): one of the game's modes (criot_mode) is running
    "king_kong_pro-0.97",                # PAD-420 2026-10-08 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running (WAITER asked right after the plunge): stackgo: started Island Scene Escape the Swamp: the runtime says one of the game's modes (cmode_island_scene_escape_the_swamp) is running | WAITER not started (trigger file): one of the game's modes (cmode_island_scene_escape_the_swamp) is running
    "mando_le-1.45",                     # PAD-420 2026-10-08 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running (WAITER asked right after the plunge, before the bounty's first shot): stackgo: started Super Skill Shot: the runtime says one of the game's modes (csuper_skill_shot) is running | WAITER not started (trigger file): one of the game's modes (csuper_skill_shot) is running
    "mando_pro-1.45",                    # PAD-420 2026-10-08 st3_job (stock card, hidden, muted): a stack no mode started with nothing of the game's running (WAITER asked right after the plunge, before the bounty's first shot): stackgo: started Super Skill Shot: the runtime says one of the game's modes (csuper_skill_shot) is running | WAITER not started (trigger file): one of the game's modes (csuper_skill_shot) is running
    "john_wick_le-1.02",                 # PAD-420 2026-10-08 st3_job (stock card, fresh NVRAM, hidden, muted; its locations base play, 440aecb0): a stack no mode started with nothing of the game's running: stackgo: started Tick Tock: the runtime says one of the game's modes (cmode_tick_tock) is running | WAITER not started (trigger file): one of the game's modes (cmode_tick_tock) is running
    "jaws_pro-1.02",                     # PAD-420 2026-10-08 st3_job (stock card, past Guided Setup, hidden, muted): a stack no mode started with nothing of the game's running; stackgo: started Cast N Catch 1, the runtime said cmode_cast_n_catch_1 is running and WAITER was refused
})


#: item 164: the titles with no cmode rules (plain C, Elvira's Rule classes) - the framework's own count of
#: the balls in play, called by the runtime: it sees a multiball there, not the other modes (sites)
STACK_BALLS_NEEDS = ("balls_in_play",)

#: item 167: a multiball of the mode's own needs the framework's start-a-multiball (`site
#: multiball_serve`: serve balls until N are in play, with a ball save) and its count of the balls in
#: play, as pad_mode_runtime.c multiball_arm checks them.
MULTIBALL_NEEDS = ("multiball_serve", "balls_in_play")
#: item 167: the builds where a mode file's `multiball` line was seen served in the emulator: the
#: framework's count rose to the balls asked for while the mode ran, and the mode ended on "one ball
#: left" once they drained. Until a build is here the tab greys Multiball and says so.
MULTIBALL_PROVEN = frozenset({
    "turtles_le-1.59",                 # 2026-09-26 mb_batch.sh (on the rig's van): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "foo_fighters_le-1.04",            # 2026-09-26 mb_batch.sh (the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "venom_le-1.07",                   # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "uncanny_xmen_le-0.98",            # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "turtles_pro-1.59",                # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "turtles_pro-1.58",                # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "star_wars_le-1.30",               # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "star_wars_elg-1.10",              # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "munsters_le-1.28",                # 2026-09-26 mb_batch.sh (a switch pressed between drains): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "metallica_spike-1.03",            # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "metallica_spike-1.04",            # 2026-10-01 PAD-306 mb_e2e flow (rig 3, stock card): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left), then the game's own ball end
    "led_zeppelin_pro-1.22",           # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "led_zeppelin_le-1.22",            # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "king_kong_le-0.97",               # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "jurassic_park_the_pin-1.05",      # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "jurassic_park_le-1.16",           # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "john_wick_le-1.01",               # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "jaws_le-1.02",                    # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "james_bond_le-1.06",              # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "james_bond_60th_le-1.11",         # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "godzilla_pro-1.16",               # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "elvira3-1.13",                    # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "dungeons_and_dragons_le-1.00",     # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "deadpool_pro-1.16",               # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "deadpool_le-1.14",                # 2026-09-26 mb_batch.sh: served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "sword_of_rage_le-1.18",           # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "rush_le-1.18",                    # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "mando_le-1.44",                   # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "iron_maiden_le-1.16",             # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "guardians_le-1.14",               # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "avengers_infinity_le-1.09",       # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "stranger_things_le-1.12",         # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "batman-1.13",                     # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "aerosmith_le-1.15",               # 2026-09-26 mb_batch.sh (SWELF: the rig's device table got its coils): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left)
    "godzilla_le-1.16",                # 2026-09-26 mb_e2e.sh: the same on the Premium (David's card): served 3, jackpots, add-a-ball to 4, drains to 1, END (one ball left)
    "beatles-1.29",                    # 2026-09-26 mb_e2e.sh: the same on its switch shots (Target 1-4): served 3, jackpots, add-a-ball to 4, drains to 1, END (one ball left)
    "godzilla_pro-1.15",               # 2026-09-26 mb_e2e.sh: served 3 on the start, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left), then the game's own ball end
    "aerosmith-1.16",                    # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "aerosmith_le-1.16",                 # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "avengers_infinity_le-1.10",         # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "avengers_infinity_pro-1.10",        # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "deadpool_le-1.16",                  # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "dungeons_and_dragons_le-1.10",      # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "foo_fighters_pro-1.04",             # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "dungeons_and_dragons_pro-1.10",     # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "guardians_le-1.15",                 # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "guardians-1.15",                    # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "iron_maiden_le-1.18",               # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "iron_maiden_pro-1.18",              # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "james_bond_pro-1.06",               # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "jaws_pro-1.02",                     # PAD-420 2026-10-08 mb_job3 (stock card, hidden, muted; past Guided Setup, coins one at a time after the tech alerts): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "john_wick_le-1.02",                 # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "john_wick_pro-1.02",                # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "jurassic_park_pro-1.16",            # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "king_kong_pro-0.97",                # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "mando_le-1.45",                     # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "mando_pro-1.45",                    # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "rush_le-1.19",                      # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "rush_pro-1.19",                     # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "star_wars_pro-1.31",                # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "stranger_things_le-1.13",           # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "sword_of_rage_le-1.19",             # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "sword_of_rage_pro-1.19",            # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "uncanny_xmen_pro-0.98",             # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "stranger_things-1.13",              # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "star_wars_le-1.31",                 # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "venom_pro-1.07",                    # PAD-420 2026-10-07 mb_job (stock card, hidden, muted): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
    "batman-1.14",                       # PAD-420 2026-10-08 mb_job (stock card, hidden, muted; the port's 22 block lines in): served 3, jackpots, add-a-ball to 4, drains 4-3-2-1, END (one ball left): counts [3, 4, 3, 2, 1]
})


def _multiball_route(sites):
    return all(n in sites for n in MULTIBALL_NEEDS)


def _multiball_cannot(key, label, sites=None):
    """The ``cannot`` entry for a multiball of the mode's own on build ``key`` (``<game>-<version>``),
    or () when it can: the port has the two sites and the build is proven."""
    if sites is not None and not _multiball_route(sites):
        return (("multiball", "The app has not found how %s serves extra balls, so a mode of yours "
                              "cannot be a multiball on it yet." % label),)
    if key in MULTIBALL_PROVEN:
        return ()
    return (("multiball", "The app has found how %s serves the balls of a multiball but has not yet "
                          "seen a mode of yours start one in the emulator, so a mode cannot be a "
                          "multiball here yet." % label),)


#: PAD-225: a ball save when a mode starts, with no multiball. The game's own one-ball saves (Godzilla's
#: Planet X hurry-up, its adjustment-timed mode-start save) go through the same framework call as its
#: multiballs, asking for no more balls than are in play (pad_mode_runtime.c pm_ball_save), so it needs
#: what a multiball needs. The builds where a mode file's `ball_save` line was seen in the emulator: the
#: game took the save, a drain inside it was served back with no end of ball, the mode scored on the
#: saved ball, and a drain after it ended the ball. Until a build is here the tab greys Ball save.
BALL_SAVE_PROVEN = frozenset({
    "aerosmith_le-1.15",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "avengers_infinity_le-1.09",        # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "batman-1.13",                      # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "beatles-1.29",                     # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "deadpool_pro-1.16",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "dungeons_and_dragons_le-1.00",     # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "foo_fighters_le-1.04",             # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "godzilla_pro-1.15",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "godzilla_pro-1.16",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "guardians_le-1.14",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "james_bond_60th_le-1.11",          # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "james_bond_le-1.06",               # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "jaws_le-1.02",                     # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "john_wick_le-1.01",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "jurassic_park_le-1.16",            # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "jurassic_park_the_pin-1.05",       # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "king_kong_le-0.97",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "led_zeppelin_le-1.22",             # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "led_zeppelin_pro-1.22",            # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "mando_le-1.44",                    # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "metallica_spike-1.03",             # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "metallica_spike-1.04",             # 2026-10-01 PAD-306 bs_job flow (rig 3, stock card): saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "munsters_le-1.28",                 # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "rush_le-1.18",                     # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "star_wars_elg-1.10",               # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "star_wars_le-1.30",                # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "stranger_things_le-1.12",          # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "sword_of_rage_le-1.18",            # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "turtles_pro-1.58",                 # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "turtles_pro-1.59",                 # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "uncanny_xmen_le-0.98",             # 2026-09-27 rigbatch bs_job.sh: saved drain served back, shots scored on it, next drain ended the ball; control without it ended on the first drain
    "aerosmith_le-1.16",                 # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 8 shots, awarded 36000000
    "avengers_infinity_le-1.10",         # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 3 shots, awarded 6000000
    "avengers_infinity_pro-1.10",        # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "iron_maiden_le-1.18",               # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "james_bond_pro-1.06",               # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "iron_maiden_pro-1.18",              # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "john_wick_le-1.02",                 # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "john_wick_pro-1.02",                # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "jurassic_park_pro-1.16",            # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "mando_le-1.45",                     # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 30000000
    "mando_pro-1.45",                    # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 30000000
    "munsters_pro-1.28",                 # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "rush_le-1.19",                      # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "rush_pro-1.19",                     # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "star_wars_le-1.31",                 # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "star_wars_pro-1.31",                # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "stranger_things-1.13",              # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "stranger_things_le-1.13",           # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "sword_of_rage_le-1.19",             # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "uncanny_xmen_pro-0.98",             # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "sword_of_rage_pro-1.19",            # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "aerosmith-1.16",                    # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "deadpool_le-1.16",                  # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 2 shots, awarded 3000000
    "dungeons_and_dragons_le-1.10",      # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "foo_fighters_pro-1.04",             # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "guardians-1.15",                    # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "king_kong_pro-0.97",                # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "venom_pro-1.07",                    # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 8 shots, awarded 36000000
    "dungeons_and_dragons_pro-1.10",     # PAD-420 2026-10-07 bs_job (stock card, hidden, muted): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "godzilla_le-1.16",                  # PAD-420 2026-10-07 bs_job (stock card, hidden, muted; jackpots from its own check): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 3 shots, awarded 6000000
    "guardians_le-1.15",                 # PAD-420 2026-10-07 bs_job (stock card, hidden, muted; orbit jackpots, not drop targets): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 2 shots, awarded 3000000
    "venom_le-1.07",                     # PAD-420 2026-10-07 bs_job (stock card, hidden, muted; jackpots from its own check, NOPF: pressing every switch starts its own multiball): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 8 shots, awarded 36000000
    "batman-1.14",                       # PAD-420 2026-10-08 bs_job (stock card, hidden, muted; jackpot presses only, NOPF - its VUK and eject switches left alone): the save taken, the drain inside it served back (auto-launched), shots scored on it, the next drain ended the ball: END (ball ended): 14 shots, awarded 105000000
    "elvira3-1.13",                      # PAD-420 2026-10-08 bs_job (stock card, hidden, muted; fresh NVRAM, coins one at a time): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 4 shots, awarded 10000000
    "jaws_pro-1.02",                     # PAD-420 2026-10-08 bs_job2 (stock card, hidden, muted; past Guided Setup, coins one at a time after the tech alerts): the save taken, the drain inside it served back, the next drain ended the ball; no control run: END (ball ended): 3 shots, awarded 6000000
})


def _ball_save_cannot(key, label, sites=None):
    """The ``cannot`` entry for a mode's own ball save on build ``key``, or () when it can."""
    if sites is not None and not _multiball_route(sites):
        return (("ball_save", "The app has not found how %s saves a ball, so a mode of yours "
                              "cannot give a ball save on it yet." % label),)
    if key in BALL_SAVE_PROVEN:
        return ()
    return (("ball_save", "The app has found how %s saves a ball but has not yet seen a mode of "
                          "yours give a ball save in the emulator, so it cannot here yet." % label),)


#: PAD-381: holding the ball on the playfield magnet. What pad_mode_runtime.c's coils_arm needs from a port
#: before it arms pm_magnet_grab - (sites, values, texts) - with ``value magnet_shot``, the shot whose hit is the
#: ball over the magnet, which mode_file.c's ``magnet`` line grabs on. A mode only asks for a time: the runtime
#: clamps it to MAGNET_MIN_MS..MAGNET_MAX_MS, takes the powers from the operator's magnet settings, and holds
#: its own limits (MODE_SDK.md "The magnet").
MAGNET_NEEDS = (("coil_fire", "adjustment", "proc_exists", "magnet_get"), ("magnet_dev", "magnet_shot"),
                ("magnet_procs",))
MAGNET_MIN_MS = 100                    # pad_mode_runtime.c MAGNET_MIN_MS / MAGNET_MAX_MS (a test holds them equal)
MAGNET_MAX_MS = 5000
#: The builds where a mode file's ``magnet`` line was seen hold the ball in the emulator: the Godzilla target's
#: hit while the mode ran gave ONE magnet command of the operator's powers ([coildrive] on the magnet), and it
#: ended at its time. Until a build is here the tab greys Magnet.
MAGNET_PROVEN = frozenset({
    "godzilla_pro-1.16",               # 2026-10-05 rig 1, the stock card: the starting hit grabbed 2000 ms (255 for 350, then 50 for 1650, [coildrive] node 9 coil 6, held to its end), a hit mid-grab refused with no OFF from the game, a grab 6 s later held to its end, a mode stop let go 565 ms early, a drain mid-grab: the game ended the grab's process and the magnet went off 798 ms early, no abort
    "godzilla_le-1.16",                # 2026-10-05 rig 1, the stock Premium/LE card: the same (held 2000 to its end, mode stop 584 ms early, drain 782 ms early, no abort); and the first hit started a magnet process of the game's, which the grab stood aside for
    "godzilla_pro-1.15",               # PAD-394 2026-10-05 rig 2, the stock card: two grabs held to their end (255 for 350, then 50 for 1650, [coildrive] node 9 coil 6, the game's OFF 2017 / 2000 ms on), a hit 1 s in refused with no OFF from the game, a mode stop let go 115 ms early, no abort
    "jurassic_park_le-1.16",           # PAD-420 2026-10-08 magnet_job (stock card on its slot's own NVRAM, hidden, muted): the T-Rex mouth magnet (held coil trex_magnet, text magnet_coil); the Left ramp enter opto's hit started the mode and grabbed 2000 ms (255 for 300, then 128 for 1700, [coildrive] node 9 coil 7, the game's OFF 2010 ms on), a hit 6 s later grabbed again and a mode stop 1.4 s in let go (OFF, 635 ms of the command left); nothing else of the game's on the coil while it held; no abort
    "james_bond_le-1.06",              # PAD-420 2026-10-08 magnet_job (stock card on its slot's own NVRAM, hidden, muted): the jet pack magnet (held coil jet_pack_magnet, text magnet_coil); the Tank hood target's hit started the mode and grabbed 2000 ms (255 for 1000, then 15 for 1000, [coildrive] node 9 coil 0, ended by the board), a hit 6 s later grabbed again and a mode stop 1.3 s in let go (OFF, 734 ms of the command left); nothing else of the game's on the coil while it held; no abort
    "dungeons_and_dragons_pro-1.10",   # PAD-420 2026-10-08 magnet_job (stock card on its slot's own NVRAM, hidden, muted): the magnet (held coil magnet_hold, its cmagnet's grab: 255 for 64 ms then 128, at most 864 ms) on the bottom right orbit opto, 24.5 px away: two hits, two grabs, each ONE command of ours on node 9 coil 2 and nothing of the game's on it while it held; both ran their 864 ms (the second ended before the mode stop 1 s in); no abort
    "dungeons_and_dragons_le-1.10",    # PAD-420 2026-10-08 magnet_job (stock card on its slot's own NVRAM, hidden, muted): the magnet (held coil magnet_hold, its cmagnet's grab: 255 for 64 ms then 128, at most 864 ms) on the bottom right orbit opto, 24.5 px away: two hits, two grabs, each ONE command of ours on node 9 coil 2 and nothing of the game's on it while it held; both ran their 864 ms (the second ended before the mode stop 1 s in); no abort
    "mando_le-1.45",                   # PAD-420 2026-10-08 magnet_job (stock card on its slot's own NVRAM, hidden, muted): the Child magnet (held coil magnet_hold, its cthe_child_magnet grab: 255 for 800 ms then 20) on the Child opto (the switch named for it): the hit started the mode and grabbed 2000 ms (ONE command of ours on node 9 coil 7, ended by the board), a hit 6 s later grabbed again and a mode stop 1.4 s in let go; nothing of the game's on the coil while it held; no abort
    "uncanny_xmen_le-0.98",            # PAD-420 2026-10-08 magnet_job2 (stock card, fresh NVRAM, hidden, muted): the magnet (held coil magnet_hold) on the Right ramp tgt (the switch nearest it on the playfield picture, 67 px): the hit started the mode and grabbed 2000 ms (ONE command of ours on node 9 coil 0, 255 for 1000 ms then 82, ended by the board), a hit 6 s later grabbed again and a mode stop 1.4 s in let go; nothing of the game's on the coil while it held; no abort
    "uncanny_xmen_pro-0.98",           # PAD-420 2026-10-08 magnet_job2 (stock card, hidden, muted): the magnet (held coil magnet_hold) on the Right ramp tgt, as the LE: the hit started the mode and grabbed its own longest 1200 ms (ONE command of ours on node 9 coil 0, ended by the board), a hit 6 s later grabbed again and a mode stop 1.0 s in (STOP_IN 0.4: its 1200 ms ends before the 1 s stop of the first run) let go; nothing of the game's on the coil while it held; no abort
    "beatles-1.29",                    # PAD-420 2026-10-08 magnet_job2 (stock card, hidden, muted; SETTLE 25 s past the game's ball-start magnet release): the top magnet (held coil magnet_top) on the Top magnet opto (25 px from it; its own switch line, flags 0x1400 as the standups'): the hit started the mode and grabbed 2000 ms (ONE command of ours on node 9 coil 6, 190 for 1000 ms then 22, ended by the board), a hit 6 s later grabbed again and a mode stop 1.5 s in let go; nothing of the game's on the coil while it held; no abort
    "rush_le-1.19",                    # PAD-420 2026-10-08 magnet_job2 (stock card, hidden, muted): the Time Machine magnet (held coil magnet_hold, the game's own grab 255/80 then 100) on the Lift ramp opto (the shot the game's own magnet answers, seen in the magnet census): the hit started the mode and grabbed 2000 ms (ONE command of ours on node 9 coil 7, ended by the board), a hit 6 s later grabbed again and a mode stop 1.5 s in let go; nothing of the game's on the coil while it held; no abort
})


def _magnet_shot_name(port):
    """The name of the port's shot the magnet sits at (``value magnet_shot``), or "" when it has none."""
    mask = port["value"].get("magnet_shot", 0) if port else 0
    if not mask:
        return ""
    return next((name for name, m in port["shot"] if m == mask), "") or next(   # PAD-420: shots from switches
        (name for _sw, m, name in port.get("switch", ()) if m == mask), "")


#: PAD-420: a coil held by its BOARD ADDRESS (pad_mode_runtime.c "held coils on every generation"): the framework's
#: coil call and its coil table, the process calls, and per coil `text <name>_drive <node> <coil> <pulse power>
#: <pulse ms> <hold power> [<longest ms>]` (the game's own hold command for that coil; an `a<id>` is the operator's
#: adjustment; the last, when there, the longest ONE command of the game's own on it, which a hold never exceeds).
COIL_ROUTE_NEEDS = (("coil_fire", "proc_exists", "proc_create", "proc_sleep"), ("coil_table", "coil_count"),
                    ("magnet_proc",))


def _drive_ok(port, name):
    """Does the port hold coil `name` by its board address: a parseable `<name>_drive` line and the calls and the
    coil table the runtime needs for it?"""
    if not port:
        return False
    sites, data, values = COIL_ROUTE_NEEDS
    words = port["text"].get("%s_drive" % name, "").split("#")[0].split()
    if len(words) not in (5, 6) or not all(re.fullmatch(r"a?\d+", w) for w in words[:5]) \
            or any(w.startswith("a") for w in words[:2]) \
            or (len(words) == 6 and not (words[5].isdigit() and int(words[5]) >= COIL_MIN_MS)):
        return False
    return (all(n in port["site"] for n in sites) and all(port["data"].get(n) for n in data)
            and all(n in port["value"] for n in values))


def _magnet_ports(port):
    """Does the port name the magnet the runtime can hold: Godzilla's ControlCoil route, or by its board address
    (PAD-420), or (PAD-420) one of its held coils, `text magnet_coil <name>` (King Kong's spider_magnet: one coil,
    one set of limits, for Magnet and Mechanisms alike)?"""
    if not port:
        return False
    alias = port["text"].get("magnet_coil", "").split("#")[0].strip()
    if alias:
        return any(name == alias for name, _l in _held_coils(port))
    sites, values, texts = MAGNET_NEEDS
    route0 = (all(n in port["site"] for n in sites) and all(n in port["value"] for n in values)
              and all(port["text"].get(n) for n in texts))
    return route0 or _drive_ok(port, "magnet")


def _magnet_cannot(key, label, port=None):
    """The ``cannot`` entry for holding the ball on the magnet on build ``key``, or () when it can: the port
    names the magnet's calls, its device or its board address, and its shot, and the build is proven."""
    if not port or not (_magnet_ports(port) and _magnet_shot_name(port)):
        return (("magnet", "The app has not found how %s drives its magnet, so a mode of yours cannot "
                           "hold the ball on it." % label),)
    if key in MAGNET_PROVEN:
        return ()
    return (("magnet", "The app has found how %s drives its magnet but has not yet seen a mode of yours "
                       "hold the ball on it in the emulator, so it cannot here yet." % label),)


#: PAD-381: a ball held in the scoop for the mode, then kicked out by the game as always. What
#: pad_mode_runtime.c's scoop_arm needs - (sites, data, values): the game's handler for the scoop's ball
#: device, the pointer to it in the device's record (swapped for a wrapper), and the event a settled ball
#: is held in. The kick-out is never the mode's: nothing here fires a coil (MODE_SDK.md "The scoop").
SCOOP_NEEDS = (("scoop_handler", "proc_sleep"), ("scoop_slot",), ("scoop_event",))
SCOOP_MIN_MS = 100                     # pad_mode_runtime.c SCOOP_MIN_MS / SCOOP_MAX_MS (a test holds them equal)
SCOOP_MAX_MS = 10000
#: The builds where a mode file's ``scoop_hold`` line was seen in the emulator: a ball that settled while the
#: mode ran was held its time and then kicked out by the game (its own 64 ms kick), the same landing with no
#: mode was kicked at the game's own time, and the mode ending let it go at once.
SCOOP_PROVEN = frozenset({
    "godzilla_pro-1.16",               # 2026-10-05 rig 1, the stock card: no mode, kicked 1782 ms after landing; scoop_hold 4000, 5776 ms (held 4016); the mode stopped 1.5 s in, let go then (2998 ms); no abort
    "godzilla_le-1.16",                # 2026-10-05 rig 1, the stock Premium/LE card: 1785 / 5770 (held 4016) / let go at the mode's end (2591 ms); a TILT during a 10 s hold ended the ball, the hold let go and the game kicked the ball out, no abort
    "godzilla_pro-1.15",               # PAD-394 2026-10-05 rig 2, the stock card: no mode, kicked 1829 ms after landing; scoop_hold 4000, 5850 ms (held 4016); the mode stopped 3 s into a hold, let go then (the kick 912 ms later); after the mode ended, 1832 ms; no abort
    "avengers_infinity_le-1.10",       # PAD-420 2026-10-07 the mechanisms helper's run (stock card, hidden, muted): no mode, kicked 1988 ms after landing; scoop_hold 4000, 6003 ms (held 4016); the mode stopped 2.5 s into a hold, kicked 1149 ms later; after the mode, 1986 ms ([coildrive] node 8 coil 7, 200 for 60 ms); no abort
    "dungeons_and_dragons_le-1.10",    # PAD-420 2026-10-07 the mechanisms helper's run (stock card, hidden, muted): its handler takes the event in its second argument (value scoop_event_arg 1): no mode, 1674 ms; scoop_hold 4000, 5698 ms (held 4016); a mode stop 2.5 s in, kicked 996 ms later; after, 1677 ms ([coildrive] node 8 coil 8, 140 for 60 ms); no abort
    "guardians_le-1.15",               # PAD-420 2026-10-07 the mechanisms helper's run (stock card, hidden, muted): no mode, 6326 ms (the game's own first landing); scoop_hold 4000, 5701 ms (held 4000); a mode stop 2.5 s in, kicked 1402 ms later; after, 1713 ms ([coildrive] node 8 coil 8, 255 for 30 ms); no abort
    "iron_maiden_le-1.18",             # PAD-420 2026-10-07 the mechanisms helper's run (stock card, hidden, muted): no mode, 2924 ms; scoop_hold 4000, 6958 ms (held 4000); a mode stop 2.5 s in, kicked 2089 ms later; after, 2928 ms ([coildrive] node 9 coil 8, 255 for 60 ms); no abort
    "aerosmith_le-1.16",               # PAD-420 2026-10-07 the mechanisms helper's run (stock card, hidden, muted): the game's own first landings settle slowly (5776 ms with no mode); scoop_hold 4000: settled, held 4000, then kicked; a mode stop 2.5 s in, kicked 1311 ms later; after, 1728 ms ([coildrive] node 8 coil 8, 255 for 30 ms); no abort
    "john_wick_le-1.02",               # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 787 ms after landing; scoop_hold 4000, 4789 ms (held 4000); a mode stop 2.5 s into a hold, kicked 158 ms later; after the mode, 781 ms ([coildrive] node 8 coil 8, 200 for 60 ms); no abort
    "king_kong_le-0.97",               # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 777 ms after landing; scoop_hold 4000, 4813 ms (held 4000); a mode stop 2.5 s into a hold, kicked 107 ms later; after the mode, 831 ms ([coildrive] node 8 coil 8, 150 for 60 ms); no abort
    "mando_le-1.45",                   # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1715 ms after landing; scoop_hold 4000, 5708 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1195 ms later; after the mode, 1715 ms ([coildrive] node 9 coil 1, 200 for 30 ms); no abort
    "mando_pro-1.45",                  # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1711 ms after landing; scoop_hold 4000, 5700 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1039 ms later; after the mode, 1712 ms ([coildrive] node 9 coil 1, 200 for 30 ms); no abort
    "munsters_le-1.28",                # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1868 ms after landing; scoop_hold 4000, 5700 ms (held 4000); a mode stop 2.5 s into a hold, kicked 1090 ms later; after the mode, 1715 ms ([coildrive] node 9 coil 1, 196 for 40 ms); no abort
    "munsters_pro-1.28",               # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 13993 ms after landing; scoop_hold 4000, 5709 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1195 ms later; after the mode, 1714 ms ([coildrive] node 9 coil 1, 196 for 40 ms); no abort
    "rush_le-1.19",                    # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1453 ms after landing; scoop_hold 4000, 5336 ms (held 4000); a mode stop 2.5 s into a hold, kicked 834 ms later; after the mode, 1297 ms ([coildrive] node 9 coil 5, 185 for 60 ms); no abort
    "rush_pro-1.19",                   # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1458 ms after landing; scoop_hold 4000, 5335 ms (held 4000); a mode stop 2.5 s into a hold, kicked 779 ms later; after the mode, 1295 ms ([coildrive] node 9 coil 5, 185 for 60 ms); no abort
    "stranger_things-1.13",            # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 5225 ms after landing; scoop_hold 4000, 5695 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1244 ms later; after the mode, 1710 ms ([coildrive] node 8 coil 8, 255 for 10 ms); no abort
    "stranger_things_le-1.13",         # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 5334 ms after landing; scoop_hold 4000, 5703 ms (held 4000); a mode stop 2.5 s into a hold, kicked 988 ms later; after the mode, 1713 ms ([coildrive] node 8 coil 8, 255 for 10 ms); no abort
    "sword_of_rage_le-1.19",           # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1348 ms after landing; scoop_hold 4000, 5336 ms (held 4016); a mode stop 2.5 s into a hold, kicked 830 ms later; after the mode, 1298 ms ([coildrive] node 9 coil 1, 200 for 60 ms); no abort
    "sword_of_rage_pro-1.19",          # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1299 ms after landing; scoop_hold 4000, 5342 ms (held 4016); a mode stop 2.5 s into a hold, kicked 735 ms later; after the mode, 1298 ms ([coildrive] node 9 coil 1, 128 for 60 ms); no abort
    "venom_le-1.07",                   # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 830 ms after landing; scoop_hold 4000, 5695 ms (held 4000); a mode stop 2.5 s into a hold, kicked 1038 ms later; after the mode, 1710 ms ([coildrive] node 9 coil 4, 225 for 30 ms); no abort
    "venom_pro-1.07",                  # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1709 ms after landing; scoop_hold 4000, 5694 ms (held 4000); a mode stop 2.5 s into a hold, kicked 934 ms later; after the mode, 1710 ms ([coildrive] node 9 coil 4, 225 for 30 ms); no abort
    "dungeons_and_dragons_pro-1.10",   # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1713 ms after landing; scoop_hold 4000, 5700 ms (held 4000); a mode stop 2.5 s into a hold, kicked 935 ms later; after the mode, 1712 ms ([coildrive] node 8 coil 8, 140 for 60 ms); no abort
    "guardians-1.15",                  # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 4299 ms after landing; scoop_hold 4000, 5694 ms (held 4000); a mode stop 2.5 s into a hold, kicked 1040 ms later; after the mode, 1709 ms ([coildrive] node 8 coil 8, 255 for 30 ms); no abort
    "john_wick_pro-1.02",              # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1451 ms after landing; scoop_hold 4000, 5336 ms (held 4000); a mode stop 2.5 s into a hold, kicked 623 ms later; after the mode, 1296 ms ([coildrive] node 8 coil 8, 200 for 60 ms); no abort
    "led_zeppelin_le-1.22",            # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 14070 ms after landing; scoop_hold 4000, 5349 ms (held 4016); a mode stop 2.5 s into a hold, kicked 884 ms later; after the mode, 1298 ms ([coildrive] node 8 coil 8, 100 for 60 ms); no abort
    "led_zeppelin_pro-1.22",           # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 14072 ms after landing; scoop_hold 4000, 5302 ms (held 4000); a mode stop 2.5 s into a hold, kicked 732 ms later; after the mode, 1300 ms ([coildrive] node 8 coil 8, 100 for 60 ms); no abort
    "star_wars_le-1.31",               # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1713 ms after landing; scoop_hold 4000, 5698 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1041 ms later; after the mode, 15546 ms ([coildrive] node 13 coil 7, 93 for 500 ms) (the game kept that ball itself - its own mode at the scoop; the runtime held nothing once the mode had ended); no abort
    "star_wars_pro-1.31",              # PAD-420 2026-10-08 scoop_job (stock card, hidden, muted): no mode, kicked 1716 ms after landing; scoop_hold 4000, 5688 ms (held 4000); a mode stop 2.5 s into a hold, kicked 1193 ms later; after the mode, 12739 ms ([coildrive] node 8 coil 6, 128 for 40 ms) (the game kept that ball itself - its own mode at the scoop; the runtime held nothing once the mode had ended); no abort
    "james_bond_le-1.06",              # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted): its game reports a landed ball settled ~3 s in and then keeps it ~5 s itself (no mode: kicked 8169 ms after landing); scoop_hold 10000: settled, held 10000, let go, kicked 0.9 s later (13942 ms after landing - the hold in place of the game's own keep, so a hold under ~5 s shows nothing here); a mode stop 4.1 s into a hold let go at once, kicked 993 ms later; after the mode 15451 ms (the game kept it, nothing of ours); [coildrive] node 8 coil 8, 255 for 10 ms; no abort
    "james_bond_pro-1.06",             # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; James Bond LE's handler found on the Pro by its code): no mode, the game kept a landed ball and kicked it 8825 ms after landing; scoop_hold 10000: settled, held 10002 ms, let go, kicked 14002 ms after landing (the hold in place of the game's own keep, as on the LE); a mode stop 4.0 s into a hold let go at once, kicked 1023 ms later; after the mode 15597 ms (the game kept it, nothing of ours); [coildrive] node 8 coil 8, 255 for 10 ms; no abort
    "aerosmith-1.16",                  # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; Aerosmith LE's handler found on the Pro by its code): no mode, kicked 4336 ms after landing; scoop_hold 4000, 5735 ms (held 4016); a mode stop 2.5 s into a hold, kicked 1273 ms later; after the mode, 1700 ms ([coildrive] node 8 coil 8, 255 for 30 ms); no abort
    "batman-1.14",                     # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; the Penguin VUK): no mode, kicked 785 ms after landing; scoop_hold 4000, 4840 ms (held 4017); a mode stop 2.5 s into a hold, kicked 262 ms later; after the mode, 782 ms ([coildrive] node 8 coil 6, 255 for 60 ms); no abort
    "deadpool_le-1.16",                # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; the Hellhouse eject - the game keeps its first landing ~7.7 s itself): no mode, kicked 7716 ms after landing; scoop_hold 4000, 5293 ms (held 4000); a mode stop 2.5 s into a hold, kicked 781 ms later; after the mode, 1299 ms ([coildrive] node 8 coil 6, 255 for 60 ms); no abort
    "deadpool_pro-1.16",               # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; the Hellhouse eject - the game keeps its first landing ~7.7 s itself): no mode, kicked 7737 ms after landing; scoop_hold 4000, 5337 ms (held 4000); a mode stop 2.5 s into a hold, kicked 935 ms later; after the mode, 1298 ms ([coildrive] node 8 coil 6, 255 for 60 ms); no abort
    "elvira3-1.13",                    # PAD-420 2026-10-08 scoop_job6 (stock card, hidden, muted; the Crypt VUK; coins one at a time after the tech alerts): no mode, kicked 1667 ms after landing; scoop_hold 4000, 5550 ms (held 4000); a mode stop 2.5 s into a hold, let go at once (held 1834), kicked 885 ms after the stop; after the mode, 1558 ms ([coildrive] node 9 coil 1, 255 for 60 ms); no abort
    "metallica_spike-1.04",            # PAD-420 2026-10-08 scoop_job6 (stock card, hidden, muted; the RT EJECT; coins one at a time after the tech alerts - its earlier run had no game): no mode, the game kept its first landing and kicked 7690 ms after; scoop_hold 4000, 5557 ms (held 4000); a mode stop 2.5 s into a hold, let go at once (held 1967), kicked 1041 ms after the stop; after the mode, 1558 ms ([coildrive] node 8 coil 8, 255 for 30 ms); no abort
    "james_bond_60th_le-1.11",         # PAD-420 2026-10-08 scoop_job4 (stock card, hidden, muted; the TOP LEFT SCOOP): no mode, kicked 3312 ms after landing; scoop_hold 4000: settled 0.8 s after landing, held 4000 ms, the game's kick 344 ms after the let-go (5130 ms after landing - its own kick, 2.5 s after the settle, waited for the hold); a mode stop 2.5 s into a hold let go at once (held 1917), kicked 623 ms after the stop; after the mode, 3162 ms ([coildrive] node 9 coil 1, 125 for 90 ms); no abort
    "king_kong_pro-0.97",              # PAD-420 2026-10-08 scoop_job6 (stock card staged on the NVMe, hidden, muted; the KONG CAVE VUK, King Kong LE's twin handler - its run-18 segvs were the D: card stall): no mode, kicked 1723 ms after landing; scoop_hold 4000, 5724 ms (held 4016); a mode stop 2.5 s into a hold, let go at once (held 2050), kicked 1253 ms after the stop; after the mode, 1718 ms ([coildrive] node 8 coil 8, 150 for 60 ms); no abort
})


#: PAD-392: the shield targets on a platform a motor turns (Godzilla Premium/LE; a Pro's are fixed). What
#: pad_mode_runtime.c's shield_arm needs - (sites, data, values): the motor's own go-to, its object, the object's
#: vtable word, where it keeps the switch it stopped on and the one it is going to, and the two position switches.
SHIELD_NEEDS = (("shield_move",), ("shield_motor",),
                ("shield_motor_vptr", "shield_pos_at", "shield_target_at", "shield_away", "shield_toward"))
#: The builds where a mode file's ``shield toward`` line was seen in the emulator: the platform turned toward the
#: player as the mode started, was kept there through the game's ball search and the shield targets' hits, and
#: turned back when the mode ended.
SHIELD_PROVEN = frozenset({
    "godzilla_le-1.16",                # PAD-392 2026-10-06 rig 1, the stock Premium/LE card: turned 1.5 s after the start, kept toward 18.5 s through six shield-target hits (all scored), put back AWAY at the mode's end; a blocks mode's turn, keep after the ball search and put-back the same run; no abort
})


def _shield_cannot(key, label, port=None):
    """The ``cannot`` entry for turning the shield targets on build ``key``, or () when it can."""
    sites, data, values = SHIELD_NEEDS
    if not port or not (all(n in port["site"] for n in sites) and all(port["data"].get(n) for n in data)
                        and all(n in port["value"] for n in values)):
        return (("shield", "The app has not found a shield platform on %s, so a mode of yours cannot turn its "
                           "shield targets." % label),)
    if key in SHIELD_PROVEN:
        return ()
    return (("shield", "The app has found how %s turns its shield platform but has not yet seen a mode of yours "
                       "turn it in the emulator, so it cannot here yet." % label),)


#: PAD-418: the game's own light shows (PAD-411, MODE_SDK.md "The game's own light shows"). What pad_mode_runtime.c's
#: shows_arm needs besides the `site show_<n>` lines before it plays one - (sites, values) - and the kinds a show is.
SHOWS_NEEDS = (("proc_create", "proc_exists", "event_cancel"), ("show_proc",))
SHOW_KINDS = ("flashy", "subdued", "accent")
#: mode_file.c's show_start / show_end hold this many bytes, the end included
SHOW_NAME_MAX = 40


def _game_shows(port):
    """PAD-418: ``((name, kind, secs), ...)`` in number order: the port's shows as the runtime arms them - `site
    show_<n>` numbered from 1 with no gaps, each named by `text show_name_<n>` (a show with no name is one a mode
    file cannot ask for, so it is left out), its kind `text show_kind_<n>`, its length `value show_secs_<n>`. ()
    when the port lacks the process lines the runtime needs."""
    if not port:
        return ()
    sites, values = SHOWS_NEEDS
    if not (all(n in port["site"] for n in sites) and all(n in port["value"] for n in values)):
        return ()
    out, n = [], 1
    while "show_%d" % n in port["site"]:
        name = port["text"].get("show_name_%d" % n, "").strip()
        kind = port["text"].get("show_kind_%d" % n, "").strip().lower()
        if name and len(name) < SHOW_NAME_MAX:
            out.append((name, kind if kind in SHOW_KINDS else "accent", port["value"].get("show_secs_%d" % n, 0)))
        n += 1
    return tuple(out)


def _shows_cannot(label, port=None):
    """The ``cannot`` entry for the game's own light shows, or () when the port names at least one."""
    if _game_shows(port):
        return ()
    return (("shows", "The app has not found %s's own light shows, so a mode of yours cannot play one at its "
                      "start or end." % label),)


#: PAD-381: the port's other HELD COILS (`text held_coils`, besides "magnet", which has its own part): each held
#: like the magnet - one command at the coil's own powers from a process of the runtime's that controls it, at
#: most COIL_MAX_MS - by a mode file's ``coil_hold <name> <ms> [mask]``. The (build, coil) pairs seen held in
#: the emulator; a coil not here is not offered.
COIL_MIN_MS = 100
COIL_MAX_MS = 5000                     # pad_mode_runtime.c MAGNET_MAX_MS: every held coil's cap
HELD_COILS_PROVEN = frozenset({
    ("godzilla_le-1.16", "mg_magnet"),  # 2026-10-05 rig 1, the stock Premium/LE card: held 2000 ms as the mode started (255 for 250, then 80 for 1750: its own adjustments), OFF at its end
    ("godzilla_le-1.16", "bridge"),     # the same run: held 2000 ms on the left ramp (255 for 300, then 25 for 1700), a hit mid-hold refused, held again, a mode stop let go 617 ms early; no abort
    # PAD-394 2026-10-05 rig 2, the stock King Kong LE 0.97 card, the three held 2000 ms as the mode started, each
    # ONE command at the object's own powers and the game's OFF 2016 ms on ([coildrive] node 9 coils 0, 1, 7), then
    # a mode stop 1.5 s into a second hold let all three go with 490-500 ms of it left; no abort
    ("king_kong_le-0.97", "spider_magnet"),   # 255 for 500 ms, then 30
    ("king_kong_le-0.97", "log_diverter"),    # 180 for 200 ms, then 48
    ("king_kong_le-0.97", "ramp_diverter"),   # 255 for 64 ms, then 48
    # PAD-394 2026-10-05 rig 2, the stock Jaws LE 1.02 card: both posts up 2000 ms as the mode started (255 for 128 ms,
    # then 51; [coildrive] node 9 coils 6 and 7, the game's OFF 2015 ms on), a mode stop 1.5 s into a second hold let
    # both down with 489 ms left; no abort
    ("jaws_le-1.02", "left_post"),
    ("jaws_le-1.02", "right_post"),
    # PAD-420 2026-10-08 coil_job_g (stock Jaws Pro 1.02 card, hidden, muted; Jaws LE's getters found by their code):
    # both posts up 2000 ms as the mode started (255 for 128 ms, then 51; [coildrive] node 9 coils 6 and 7, the game's
    # OFF 2016 ms on), a mode stop 1.5 s into a second hold let both down with 490 ms left; no abort
    ("jaws_pro-1.02", "left_post"),
    ("jaws_pro-1.02", "right_post"),
    ("led_zeppelin_pro-1.22", "control_gates"),  # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 255 for 60 ms then 96 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("star_wars_elg-1.10", "right_gate"),        # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 8 coil 2, 255 for 60 ms then 128 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("sword_of_rage_le-1.19", "control_gates"),  # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 0, 255 for 60 ms then 96 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("sword_of_rage_pro-1.19", "control_gates"), # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 0, 255 for 60 ms then 96 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("deadpool_le-1.16", "control_gates"),       # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 6, 255 for 60 ms then 96 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("deadpool_pro-1.16", "control_gate"),       # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 6, 255 for 60 ms then 96 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1501 ms on; no abort
    ("led_zeppelin_le-1.22", "control_gates"),   # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 255 for 60 ms then 96 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("jurassic_park_le-1.16", "trex_magnet"),    # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 7, 255 for 300 ms then 128 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("jurassic_park_le-1.16", "raptor_post"),    # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 255 for 120 ms then 64 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("jurassic_park_le-1.16", "orbit_post"),     # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 8, 255 for 60 ms then 64 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("jurassic_park_le-1.16", "room_post"),      # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 6, 255 for 60 ms then 64 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("iron_maiden_le-1.18", "left_post"),        # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 200 for 60 ms then 64 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1501 ms on; no abort
    ("iron_maiden_le-1.18", "right_post"),       # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 0, 200 for 60 ms then 64 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1501 ms on; no abort
    ("iron_maiden_pro-1.18", "left_post"),       # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 200 for 60 ms then 64 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1499 ms on; no abort
    ("iron_maiden_pro-1.18", "right_post"),      # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 0, 200 for 60 ms then 64 (its own); OFF 2015 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("avengers_infinity_le-1.10", "tower_magnet"), # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 0, 255 for 300 ms then 100 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("avengers_infinity_le-1.10", "tower_post"), # PAD-420 2026-10-07 coil_job (stock card, hidden, muted): node 9 coil 5, 255 for 120 ms then 64 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("guardians_le-1.15", "orbit_gates"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; when the game raised it mid-hold, let go with no OFF of its own; no abort
    ("mando_le-1.45", "center_ramp_gat"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 5, 255 for 64 ms then 128 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_le-1.45", "diverter_mini_p"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 64 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_le-1.45", "top_up_post"),            # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 8, 255 for 64 ms then 128 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_pro-1.45", "center_ramp_gat"),       # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 5, 255 for 64 ms then 128 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_pro-1.45", "diverter_mini_p"),       # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 64 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_pro-1.45", "top_up_post"),           # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 8, 255 for 64 ms then 128 (the game's own), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("munsters_le-1.28", "up_post"),             # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 150 ms then 64 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("munsters_le-1.28", "magnet_hold"),         # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 1200 ms then 18 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("avengers_infinity_pro-1.10", "tower_magnet"), # PAD-420 2026-10-08 coil_job (re-run 3) (stock card, hidden, muted): node 9 coil 0, 255 for 300 ms then 100 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1501 ms on; no abort
    ("avengers_infinity_pro-1.10", "tower_post"), # PAD-420 2026-10-08 coil_job (re-run 3) (stock card, hidden, muted): node 9 coil 5, 255 for 120 ms then 64 (its own); OFF 2014 ms on; a mode stop 1.5 s in let go 1501 ms on; no abort
    ("munsters_pro-1.28", "up_post"),            # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 150 ms then 64 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("munsters_pro-1.28", "magnet_hold"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 1200 ms then 18 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("jurassic_park_pro-1.16", "orbit_post"),    # PAD-420 2026-10-08 coil_job (re-run 3) (stock card, hidden, muted): node 9 coil 8, 255 for 60 ms then 64 (its own); OFF 2016 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("jurassic_park_pro-1.16", "room_post"),     # PAD-420 2026-10-08 coil_job (re-run 3) (stock card, hidden, muted): node 9 coil 6, 255 for 60 ms then 64 (its own); OFF 2016 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("jurassic_park_pro-1.16", "inlane_post"),   # PAD-420 2026-10-08 coil_job (re-run 3) (stock card, hidden, muted): node 8 coil 6, 255 for 120 ms then 64 (its own); OFF 2016 ms on; a mode stop 1.5 s in let go 1500 ms on; no abort
    ("king_kong_pro-0.97", "spider_magnet"),  # PAD-420 2026-10-08 coil_job_k0 (stock card on its slot's own NVRAM, hidden, muted): node 9 coil 0, 255 for 500 ms then 30 (the object's own); held 2000 ms as the mode started, the game's OFF 2016 ms on; a mode stop 0.7 s into a second hold let go; no abort
    ("king_kong_pro-0.97", "river_diverter"), # PAD-420 2026-10-08 coil_job_k0 (stock card on its slot's own NVRAM, hidden, muted): node 9 coil 1, 180 for 200 ms then 48 (the object's own); held 2000 ms as the mode started, the game's OFF 2016 ms on; a mode stop 0.7 s into a second hold let go; no abort
    ("star_wars_le-1.31", "gates"),              # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 5, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("star_wars_le-1.31", "outlane_gate"),       # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 8, 255 for 500 ms then 56 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("star_wars_pro-1.31", "gates"),             # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 5, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("stranger_things-1.13", "left_down_post"),  # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 6, 255 for 16 ms then 95 (the game's own), at most 416 ms; held 410 ms to its end (the game's own longest, 416 ms, ends before a stop could); no abort
    ("stranger_things_le-1.13", "left_down_post"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 6, 255 for 16 ms then 95 (the game's own), at most 416 ms; held 410 ms to its end; the game's own longest ends before a mode stop could; no abort
    ("venom_le-1.07", "up_post"),                # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 1, 255 for 32 ms then 48 (the game's own), at most 1032 ms; held 1030 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("james_bond_le-1.06", "jet_pack_magnet"),   # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 1000 ms then 15 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("james_bond_le-1.06", "gate"),              # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 96 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("james_bond_pro-1.06", "gate"),             # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 96 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("elvira3-1.13", "gate"),                    # PAD-420 2026-10-08 coil_job_c2 (stock card, hidden, muted; coins one at a time): node 9 coil 5, 255 for 64 ms then 96 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("aerosmith_le-1.16", "upper_gate"),         # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 10 coil 0, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; when the game raised it mid-hold, let go with no OFF of its own; no abort
    ("aerosmith_le-1.16", "toy_box_magnet"),     # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 1000 ms then 16 (the game's own, its ToyBoxMagnet's grab - device 17 by its static object; its hold runs 5 s, so the runtime's 5 s cap); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("guardians-1.15", "orbit_gates"),           # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("foo_fighters_le-1.04", "outlane_up_post"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 8, 255 for 64 ms then 64 (the game's own), at most 2064 ms; held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("foo_fighters_le-1.04", "up_pf_diverter"),  # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 32 ms then 64 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("foo_fighters_le-1.04", "van_up_post"),     # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 32 ms then 128 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("foo_fighters_pro-1.04", "van_up_post"),    # PAD-420 2026-10-08 coil_job_c3 (stock card, hidden, muted; coins one at a time): node 9 coil 7 (device 12), 255 for 32 ms then 128 (the game's own); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("beatles-1.29", "magnet_top"),             # PAD-420 2026-10-08 coil_job_c3 (stock card, hidden, muted; the holds 25 s into the game - run 18's 8 s met the game's own ball-start OFF): node 9 coil 6 (device 15), 190 for 1000 ms then 22 (its TopMagnet's own hold); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("jurassic_park_the_pin-1.05", "gate"),      # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 7, 255 for 250 ms then 255 (the game's own), at most 1488 ms; held 1480 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("turtles_pro-1.59", "pizza_magnet"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 1200 ms then 128 (the game's own); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("james_bond_60th_le-1.11", "left_gate"),    # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 40 ms then 96 (the game's own), at most 940 ms; held 940 ms to its end; the game's own longest ends before a mode stop could; no abort
    ("james_bond_60th_le-1.11", "right_gate"),   # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 5, 255 for 40 ms then 96 (the game's own), at most 940 ms; held 940 ms to its end; the game's own longest ends before a mode stop could; no abort
    ("john_wick_le-1.02", "diverter"),           # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, a209 for 150 ms then a210 (the game's own, its RampDiverter's; 150 and 16 on the stock card); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("rush_le-1.19", "up_post"),                 # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 6, a171 for 64 ms then a172 (the game's own, its DoubleUpPost's; 255 and 64 on the stock card); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("rush_le-1.19", "magnet_hold"),             # PAD-420 2026-10-08 coil_job_c3 (stock card, hidden, muted): node 9 coil 7 (device 19, its TimeMachineMagnet), 255 for 80 ms then 100 (the game's own grab, seen in the magnet census on the Lift ramp opto); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("rush_pro-1.19", "magnet_hold"),            # PAD-420 2026-10-08 coil_job_c3 (stock card, hidden, muted): node 9 coil 7 (device 15, its TimeMachineMagnet), 255 for 80 ms then 100 (the game's own grab, seen in the magnet census on the Center ramp opto); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("batman-1.14", "diverter_power"),           # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 16 (the game's own, its TurntableDiverter's - device 13 by its constructor); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("batman-1.14", "gate"),                     # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 64 ms then 96 (the game's own, its LeftControlGate's - device 16 by its constructor); held 1990 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("batman-1.14", "magnet_hold"),              # PAD-420 2026-10-08 coil_job_c3 (stock card, hidden, muted): node 9 coil 0 (device 14, its TurntableMagnet), 255 for 1000 ms then 16 (the game's own grab, seen in the magnet census on the Bat Phone Target); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("uncanny_xmen_pro-0.98", "right_return_up"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 7, a169 for 0 ms then a169 (the game's own hold-only command - 0 for 0, then adj 169: 82 on the stock card), at most 1250 ms; held 1250 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("uncanny_xmen_pro-0.98", "magnet_hold"),    # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for a182 ms then 82 (the game's own, its magnet's - device 13 by its constructor; 1000 ms on the stock card), at most 1200 ms; held 1200 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("uncanny_xmen_le-0.98", "right_return_up"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 8 coil 7, a169 for 0 ms then a169 (the game's own hold-only command: 82 on the stock card), at most 1250 ms; held 1250 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("uncanny_xmen_le-0.98", "magnet_hold"),     # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for a196 ms then 82 (the game's own; 1000 ms on the stock card), at most 2500 ms; held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("uncanny_xmen_le-0.98", "diverter"),        # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 1, a163 for a164 ms then a165 (the game's own; 180 for 60 ms then 64 on the stock card), at most 1250 ms; held 1240 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("dungeons_and_dragons_pro-1.10", "up_post"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 128 (the game's own, its cup_post's - device 11 by its constructor), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("dungeons_and_dragons_pro-1.10", "magnet_hold"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 2, 255 for 64 ms then 128 (the game's own, its cmagnet's grab - device 13 by its constructor), at most 864 ms; held 860 ms to its end; the game's own longest ends before a mode stop could; no abort
    ("dungeons_and_dragons_le-1.10", "diverter"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 0, 255 for 64 ms then 128 (the game's own, its cdiverter's - device 14 by its constructor), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("dungeons_and_dragons_le-1.10", "up_post"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 64 ms then 128 (the game's own, its cup_post's - device 11 by its constructor), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("dungeons_and_dragons_le-1.10", "magnet_hold"), # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 2, 255 for 64 ms then 128 (the game's own, its cmagnet's grab - device 13 by its constructor), at most 864 ms; held 860 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("venom_pro-1.07", "top_post"),              # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 64 ms then 128 (the game's own, its ctop_post_device's - device 13 by its constructor), at most 1564 ms; held 1560 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("led_zeppelin_le-1.22", "electric_magic"),  # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 2000 ms then 64 (the game's own, its ElectricMagicMagnet's grab - device 17 by its static object), at most 2500 ms; held 2000 ms to its end (the draw alone: the board's hold phase empty); a mode stop 0.7 s in sent the game's OFF; no abort
    ("mando_le-1.45", "magnet_hold"),            # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 7, 255 for 800 ms then 20 (the game's own, its cthe_child_magnet's grab - device 14 by its constructor; its hold runs 10 s, so the runtime's 5 s cap); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("metallica_spike-1.04", "loop_up_post"),    # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 11 coil 2, 170 for 32 ms then 68 (the game's own, its cdevice_loop_diverter's - device 22; the coins dropped one at a time, 1 s apart - Metallica counted 3 of 8 dropped 0.7 s apart), at most 1032 ms; held 1030 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
    ("turtles_le-1.59", "pizza_magnet"),         # PAD-420 2026-10-08 coil_job_c (stock card, hidden, muted): node 9 coil 6, 255 for 1200 ms then 128 (the game's own; the coins dropped one at a time and the title's NVRAM fresh - its earlier runs on the slot's own NVRAM never got a second game); held 2000 ms to its end; a mode stop 0.7 s in sent the game's OFF; no abort
})


def _held_coils(port):
    """The port's held coils besides the magnet, ``((name, label), ...)``: each with its getter and device, or
    (PAD-420) its board address and the game's own hold command."""
    out = []
    for name in (port["text"].get("held_coils", "") if port else "").split():
        if name == "magnet":
            continue
        if _drive_ok(port, name) or (("%s_get" % name) in port["site"] and port["value"].get("%s_dev" % name)):
            out.append((name, port["text"].get("%s_label" % name, name)))
    return tuple(out)


def _coil_caps(port, names):
    """PAD-420: ``((name, ms), ...)`` for the held coils whose `_drive` line names the game's own longest command
    on the coil, where that is shorter than COIL_MAX_MS: a hold of it is never longer (pad_mode_runtime.c)."""
    out = []
    for name in names:
        words = port["text"].get("%s_drive" % name, "").split("#")[0].split() if port else []
        if len(words) == 6 and words[5].isdigit() and int(words[5]) < COIL_MAX_MS:
            out.append((name, int(words[5])))
    return tuple(out)


def _coils_cannot(key, label, port=None):
    """The ``cannot`` entry for the other held coils on build ``key``, or () when at least one is proven."""
    held = _held_coils(port)
    if not held:
        return (("coils", "The app has not found any other mechanism of %s's a mode can hold." % label),)
    if any((key, name) in HELD_COILS_PROVEN for name, _l in held):
        return ()
    return (("coils", "The app has found %s on %s but has not yet seen a mode of yours hold it in the emulator, "
                      "so it cannot here yet." % (", ".join(lab for _n, lab in held), label)),)


def _scoop_cannot(key, label, port=None):
    """The ``cannot`` entry for holding a ball in the scoop on build ``key``, or () when it can."""
    sites, data, values = SCOOP_NEEDS
    if not port or not (all(n in port["site"] for n in sites) and all(port["data"].get(n) for n in data)
                        and all(n in port["value"] for n in values)):
        return (("scoop", "The app has not found how %s runs its scoop, so a mode of yours cannot hold a "
                          "ball in it." % label),)
    if key in SCOOP_PROVEN:
        return ()
    return (("scoop", "The app has found how %s runs its scoop but has not yet seen a mode of yours hold a "
                      "ball in it in the emulator, so it cannot here yet." % label),)


#: item 167: the hand-written profile carries the same verdict as its port (its port names the
#: framework's serve call; the tab offers Multiball once the build is in MULTIBALL_PROVEN). PAD-381's magnet,
#: scoop and held coils are judged from its port once that is read (PAD-394, below).
GODZILLA_PRO_1_15 = replace(GODZILLA_PRO_1_15, cannot=_multiball_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _ball_save_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _magnet_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _scoop_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _coils_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _shield_cannot("godzilla_pro-1.15", "Godzilla Pro 1.15")
                            + _shows_cannot("Godzilla Pro 1.15"))
PROFILES = {p.key: p for p in (GODZILLA_PRO_1_15,)}

#: item 164: the builds where a ``stack no`` mode was seen held back by a multiball that count showed, and
#: started again once it ended
STACK_BALLS_PROVEN = frozenset({
    "beatles-1.29", "james_bond_60th_le-1.11", "james_bond_le-1.06", "metallica_spike-1.03",
    "star_wars_elg-1.10", "stranger_things_le-1.12", "uncanny_xmen_le-0.98", "batman-1.13",
    "guardians_le-1.14", "aerosmith_le-1.15", "elvira3-1.13", "jurassic_park_the_pin-1.05",
    "metallica_spike-1.04",           # PAD-306 2026-10-01: the framework's serve asked for two (0x3e3008), the
                                      # stack no mode refused ("a multiball"); one drained, started
    "aerosmith_le-1.16",                 # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "guardians-1.15",                    # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "guardians_le-1.15",                 # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "james_bond_pro-1.06",               # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "stranger_things-1.13",              # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "stranger_things_le-1.13",           # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "uncanny_xmen_pro-0.98",             # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "aerosmith-1.16",                    # PAD-420 2026-10-07 st_job (stock card, hidden, muted): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
    "batman-1.14",                       # PAD-420 2026-10-08 st_job (stock card, hidden, muted; the port's 22 block lines in): our own multiball stopped with its three balls in play, a stack no mode refused (a multiball is running), then started at one ball: WAITER not started (trigger file): a multiball is running
})


def end_sound_carried(game, version):
    """item 164: a title whose time-up callout is not known can still end a mode with a sound
    of its own - on a CARRIER, swapped in while the mode plays (item 163's key swap, the route
    its start and shot sounds take); mode_file.c's ``sound_end`` plays it when time runs out.
    True when the title has swap carriers measured (mode_sounds)."""
    from . import mode_sounds as MS
    c = MS.carriers(game, version)
    return bool(c and c.swap and c.calls)


#: item 164: the plain-C titles whose OTHER modes a ``stack no`` mode was seen wait for in the emulator:
#: the framework's game flags (``data game_flags``) and each mode's own flag (``value mode_flag_1`` ..),
#: set by the mode's start function. Until a build is here its note says multiballs only.
STACK_FLAGS_PROVEN = frozenset({
    "jurassic_park_the_pin-1.05",     # 2026-09-25: Stegosaurus (flag 40) held a stack no mode back
    "star_wars_elg-1.10",             # Inner loop (flag 86)
    "stranger_things_le-1.12",        # Bust out (flag 78)
    "james_bond_le-1.06",             # Bust out (flag 102), and the flag cleared when it ended
    "batman-1.13",                    # Shame (flag 71, its start takes one argument), cleared when it ended
    "james_bond_pro-1.06",            # PAD-420 2026-10-08 st3_job16 (stock card, hidden, muted; James Bond LE 1.06's mode flags, the same version): Bullshit Scoring started through its block start set flag 141 and a stack no mode was refused for it; with nothing running it had started
    "stranger_things-1.13",           # PAD-420 2026-10-08 st3_job18 (stock card, hidden, muted; Stranger Things LE 1.12's flags + 5, each read off its start here): with nothing running a stack no mode started; Bullshit Scoring's block start set flags 116 and 136 and the mode was refused (flag 136)
    "stranger_things_le-1.13",        # PAD-420 2026-10-08 st3_job18 (stock card, hidden, muted; Stranger Things LE 1.12's flags + 5, each read off its start here): with nothing running a stack no mode started; Bullshit Scoring's block start set flags 116 and 136 and the mode was refused (flag 136)
    "batman-1.14",                    # PAD-420 2026-10-08 st3_job18 (stock card, hidden, muted; its own flags, 1.13's + 5 and the episodes', each read off its start here - the draft's 86 / 88 were not modes'): with nothing running a stack no mode started; Catwoman (episodes 19-20)'s start set flag 51 and the mode was refused
})


def _stack_flags(data, values):
    return bool(data.get("game_flags")) and "mode_flag_1" in values


#: item 165: the plain-C titles whose TIMED modes a ``stack no`` mode was seen wait for in the emulator: the
#: framework's live records (``site live_records``, the check every timed mode's start begins with) asked
#: about each mode's own record ids (``value mode_records_1`` ..). Until a build is here its note says
#: multiballs only.
STACK_RECORDS_PROVEN = frozenset({
    "aerosmith_le-1.15",              # 2026-09-26: Double Scoring (ids 237..238) held a stack no mode back, and
                                      # 60 s later its records were gone and the mode started
    "guardians_le-1.14",              # the same with its Double Scoring (ids 232..233)
    # later the same day: each title's Headphone Hurryup (its start creates the record without asking first;
    # Aerosmith 235..236, Guardians 230..231) was named and held the mode back, and was gone after its kill
    "metallica_spike-1.03",           # a song mode (Battery's first start 0xc5248 creates 182): named and
                                      # refused; the framework's kill 182..184 -> nothing, started
    "metallica_spike-1.04",           # PAD-306 2026-10-01: Battery's first start 0xc5718 creates 182 (and 0xc7d4c
                                      # 187): named and refused; the framework's kill 0x1fd9bc 182..184 (187..189)
                                      # -> nothing, started
    "james_bond_60th_le-1.11",        # a Villain Mode (its start 0x9bb10 runs game timer 2, records 137..138):
                                      # named and refused; the framework's kill 137..138 -> nothing, started
    "aerosmith-1.16",                 # PAD-420 2026-10-08 st3_job16 (stock card, hidden, muted; Aerosmith LE 1.15's record ids + 4, read off each start's mov r0): with nothing running a stack no mode started; Super Scoring's block start (ids 243..245) was named running and the mode refused
    "aerosmith_le-1.16",              # PAD-420 2026-10-08 st3_job16 (stock card, hidden, muted; Aerosmith LE 1.15's record ids + 4, read off each start's mov r0): with nothing running a stack no mode started; Super Scoring's block start (ids 243..245) was named running and the mode refused
    "guardians_le-1.15",              # PAD-420 2026-10-08 st3_job16 (stock card, hidden, muted; Guardians LE 1.14's record ids + 4, read off each start's mov r0): with nothing running a stack no mode started; Super Scoring's block start (ids 238..240) was named running and the mode refused
    "guardians-1.15",                 # PAD-420 2026-10-08 st3_job18 (stock card, hidden, muted; Guardians LE 1.14's record ids + 4, read off each start's mov r0): with nothing running a stack no mode started; Super Scoring's block start (ids 238..240) was named running and the mode refused
})


def _stack_records(sites, values):
    return "live_records" in sites and "mode_records_1" in values


#: item 165: the titles whose modes are C++ singletons with a RUNNING byte of their own (``data mode_running_1``
#: .., set by the mode's start, cleared by its stop): the builds where a ``stack no`` mode was seen held back by
#: one of them in the emulator, and started again once it stopped
STACK_BYTES_PROVEN = frozenset({
    "uncanny_xmen_le-0.98",           # 2026-09-26: nothing running -> started; A Fiery Assault's start called ->
                                      # "one of the game's modes (A Fiery Assault)", refused; its own stop called
                                      # -> nothing, started (the score shows Fiery Assault's 500,000 had paid)
    "uncanny_xmen_pro-0.98",          # PAD-420 2026-10-08 st3_job16 (stock card, hidden, muted; each battle's object through its own class's constructor, as on X-Men LE 0.98): with nothing running a stack no mode started; A Fiery Assault's start, called with its object, was named running from its byte (object + 0x74) and the mode refused
})


def _stack_bytes(data):
    return bool(data.get("mode_running_1"))


#: item 165: the titles whose modes are C++ RULE OBJECTS that answer for themselves (``data mode_rule_1`` .. and
#: ``value mode_rule_slot``: the runtime calls each object's own running test, as the game does): the builds where
#: a ``stack no`` mode was seen held back by one of them in the emulator, and started again once it ended
STACK_OBJECTS_PROVEN = frozenset({
    "elvira3-1.13",                   # 2026-09-26: nothing running -> started; a House started (0xdd12c) ->
                                      # "one of the game's modes (The Werewolf of Washington)", refused; the ball's
                                      # end closed the House -> nothing, started
})


def _stack_objects(data, values):
    return bool(data.get("mode_rule_1")) and bool(values.get("mode_rule_slot"))


#: item 165: a multiballs-only title where the app DOES see the other modes but waiting for them would keep a
#: mode from ever starting - the note says why instead of "cannot yet see" (``%s`` is the title's label)
STACK_NOTE_WHY = {
    # measured 2026-09-26: a song's framework record is alive from the ball's start (It Won't Be Long in one
    # game, Ticket to Ride in another), each song start adds its own, and all of them clear at the ball's end
    "beatles-1.29": ("On %s a mode of yours waits only for the game's multiballs: one of its songs is always "
                     "running, so waiting for the songs too would keep it from ever starting."),
}


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
#: item 166: the Insider Connected score gate - the request header constructor and the message-begin
#: thunk (pad_mode_runtime.c insider_arm). A port without both arms nothing, and no mode goes on a card
#: whose port lacks them: a mode scores through the game's own scoring, and the card grades itself
#: valid, so Insider Connected would take a mode's points as real scores.
INSIDER_GATE_SITES = ("agent_header", "agent_begin")
#: what the Modes page and a Write say about a card that carries modes
INSIDER_NOTE = ("Insider Connected: players still log in on a card with modes, but the machine "
                "sends no game, score, high-score or achievement report to Insider Connected. A "
                "mode's points are not the game's stock scoring, so they stay on the machine.")


def insider_gate_words(label):
    """Why modes cannot go on *label*'s card: its port lacks the score gate."""
    return ("%s's port has no Insider Connected score gate (agent_header and agent_begin), so "
            "modes cannot be put on its card: a mode's points would reach Insider Connected as "
            "real scores. Work the port out again (MODE_SDK.md, \"Insider Connected\")." % label)
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
#: PAD-228 (2026-09-27, rig 2): the Godzilla builds' cabinet buttons - Action 34, left flipper 60, right
#: flipper 59 - one hit per press on the press edge (the game's mode mask is 0 in play), a mode scored the
#: flipper buttons +1M and +2M and served its multiball on the Action button, and the shim's LED view had
#: the Action button solid red for the whole run of the mode (the game's own animation before it).
#: PAD-306 (2026-10-01, rig 3): Metallica Remastered 1.04, the stock card, the Modes tab's Check this game
#: (modes/gamecheck.sh play) and the switches it leaves out pressed after it: 37 of its 40 switch lines gave exactly
#: one shot per press, in play, each on its own bit (the outlanes 59 and 62 too); Coffin lock 1-3 (89-91) gave none,
#: even held 2.5 s - their descriptor flags are 0x0020 (the playfield's 0x0003), which the drain does not pass in
#: play, the same switch table as 1.03's.
SWITCH_EDGE_PROVEN = frozenset({"beatles-1.29", "star_wars_elg-1.10", "batman-1.13", "rush_le-1.18",
                                "godzilla_pro-1.15", "godzilla_pro-1.16", "godzilla_le-1.16",
                                "metallica_spike-1.04"})


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
#: item 164: titles whose voice never says a lone number - every callout on the card transcribed
#: (t2/numscan.py, 2026-09-26) - so no countdown can be made of the game's own voice
#: PAD-420: Aerosmith Pro and LE 1.16 and John Wick Pro and LE 1.02 - every short mono clip their requests name
#: (<= 1.3 s, the ones numscan.py transcribed) is one of 1.15's / 1.01's, length for length (174 and 131 of them,
#: none new), so their voices say no lone number either
COUNTDOWN_NO_NUMBERS = frozenset({"aerosmith_le-1.15", "john_wick_le-1.01", "elvira3-1.13",
                                  "aerosmith-1.16", "aerosmith_le-1.16", "john_wick_le-1.02", "john_wick_pro-1.02"})

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
    "led_zeppelin_le-1.22": dict(screen_proven=True, hud="52c8fb8417a3ee2442bc31e12563b6fa", bank="549616e1c38dbf636eae575c75f376ff", clip_proven=True),   # item 164: our clip seen on the glass, on the background bank 914f6bd9
    "beatles-1.29": dict(screen_proven=True, hud="fe7ab9c3143f1db4ebf9c917df8b47fe", bank="e9101ee9059414046aec49f7ccb4613c", clip_proven=True),   # item 164: our clip seen on the glass
    "dungeons_and_dragons_le-1.00": dict(screen_proven=True, hud="e8bbe9670a9a212f18408a602d7b187b", bank="62d7aa522a27805655b6819750a0df75", clip_proven=True),   # item 164: our clip seen on the glass
    "foo_fighters_le-1.04": dict(screen_proven=True, hud="3f34991c6809a039dd47b2086a12937a", bank="469deda43d1ebfe2c5d371d5a800d0a9", clip_proven=True),   # item 164: our clip seen on the glass
    "godzilla_pro-1.16": dict(screen_proven=True, hud="f9daed5a19aafc807bf9eb3c2def6c27", bank="fe35b5b897c2b0df6fe583b0168a6cda", clip_proven=True),   # item 164: our clip seen on the glass
    "james_bond_60th_le-1.11": dict(screen_proven=True, hud="37d90179d849daf5afcbe4db0cf1cf1d", bank="37d90179d849daf5afcbe4db0cf1cf1d", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "james_bond_le-1.06": dict(screen_proven=True, hud="832c77c669803d557c730a3be09fb9e5", bank="63f6bc13a70ee6f16f24fa6ab6e908fa", clip_proven=True),   # item 164: our clip seen on the glass, on the nested bank 6fb39344/60ed7e50
    "avengers_infinity_le-1.09": dict(screen_proven=True, hud="62614053077f96e15d4d3d89a88d8a20", bank="0a433b8e07933efcc8704ca469036c97", bank_tree="demand_loaded", clip_proven=True),   # item 164: our clip seen on the glass
    "jurassic_park_le-1.16": dict(screen_proven=True, hud="5a57df0fc5f2f441faf8f5a6b012c277", bank="3e222871d6c38b6b493fdfe59f788133", bank_tree="demand_loaded", clip_proven=True),   # item 164: our clip seen on the glass
    "king_kong_le-0.97": dict(screen_proven=True, hud="cf8da03fa56cd71e414702db70b6aa3d", bank="ed379c6514e73bead614fee25e93d862", clip_proven=True),   # item 164: our clip seen on the glass
    "led_zeppelin_pro-1.22": dict(screen_proven=True, hud="b8745c86480a44976d95068a7dc773f2", bank="549616e1c38dbf636eae575c75f376ff", clip_proven=True),   # item 164: our clip seen on the glass, on the background bank 914f6bd9
    "metallica_spike-1.03": dict(screen_proven=True, hud="809cbf843c36555ddbda41c3b4909543", bank="809cbf843c36555ddbda41c3b4909543", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "metallica_spike-1.04": dict(screen_proven=True, hud="5fa968f413d7e188cac4045da9e76781", bank="5fa968f413d7e188cac4045da9e76781", clip_proven=True),   # PAD-306: screen and clip seen on the glass, in a Video grafted into the HUD
    "turtles_le-1.59": dict(screen_proven=True, hud="a337459aee72b3ec5dc9b0a50981e16d", bank="cf92bc5a7a4bb06fcd90a3bb90d55baa", clip_proven=True),   # item 164: our clip seen on the glass
    "uncanny_xmen_le-0.98": dict(screen_proven=True, hud="0d31df0d25052d0ec251c18d5b8b33a1", bank="4c5e3bd248dc09f1373c91111543f92e", clip_proven=True),   # item 164: our clip seen on the glass
    "aerosmith_le-1.15": dict(screen_proven=True, hud="53c9a69e39abf2dbb54fd134afe68b01", bank="dab80a17b8977c603e9094be6f072a58", clip_proven=True),   # item 164: our clip seen on the glass
    "guardians_le-1.14": dict(screen_proven=True, hud="f1b87fa9a6f94cddc4aca6268dcd96ea", bank="a0683942e100705db906181685dd842e", clip_proven=True),   # item 164: our clip seen on the glass
    "mando_le-1.44": dict(screen_proven=True, hud="7b8d6f595c97a76e16bf54bee5d10007", bank="390b28f5b7ef5b5e3f49edcee3088a29", clip_proven=True),   # item 164: our clip seen on the glass
    "rush_le-1.18": dict(screen_proven=True, hud="a516ede995deda83619a4d57469a8760", bank="99a73567ccfa371c44c861579d8362d4", clip_proven=True),   # item 164: our clip seen on the glass, on the background bank 914f6bd9
    "stranger_things_le-1.12": dict(screen_proven=True, hud="315de4afdec66df3ea56cc64b5673a95", bank="a6c50224ebf14f37444b84bb632c1b68", clip_proven=True),   # item 164: our clip seen on the glass
    "sword_of_rage_le-1.18": dict(screen_proven=True, hud="ff7ed4a354fd8f5565250ea1411ef2ed", bank="ca3bab9c0f7e7f02272fddb8ac269dfb", clip_proven=True),   # item 164: our clip seen on the glass
    "iron_maiden_le-1.16": dict(screen_proven=True, hud="9b6a1b230e2dcfe050606a7d7bb4c283", bank="9b6a1b230e2dcfe050606a7d7bb4c283", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "john_wick_le-1.01": dict(screen_proven=True, hud="aa4caf7b0c0a142f39d8c62388601dd1", bank="e9fee788468383dacf1ad315b89bfdb8", clip_proven=True),   # item 164: our clip seen on the glass, on the bank it draws in play (08a4e1ca)
    "munsters_le-1.28": dict(screen_proven=True, hud="9869621883a18ce97bd3446d67dfbbff", bank="9869621883a18ce97bd3446d67dfbbff", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "star_wars_le-1.30": dict(screen_proven=True, hud="6ad2d6fb45a03892f43675a9faf8d1ac", bank="8d984a6a6e50a1d50241c80c0edab0b5", clip_proven=True),   # item 164: our clip seen on the glass (its bank read with the marked-clips list)
    "elvira3-1.13": dict(screen_proven=True, hud="fda0fad4bd0931e1412872f85a232834", bank="fda0fad4bd0931e1412872f85a232834", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "star_wars_elg-1.10": dict(hud="354935f6d901c89105d1a97edd4a559e", screen_proven=True, bank="895f74e53622cf5acfa55a1df89a8fc8", clip_proven=True),   # item 164: our clip seen on the glass (its bank read with the marked-clips list)
    "batman-1.13": dict(screen_proven=True, hud="322b14238d0351d6e6ddeb6333e07c8a", bank="322b14238d0351d6e6ddeb6333e07c8a", clip_proven=True),   # item 164: our clip seen on the glass, in a Video grafted into the HUD
    "jurassic_park_the_pin-1.05": dict(screen_proven=True, hud="6f3c2dbd6a176794ca54794f41f699fd", bank="6f3c2dbd6a176794ca54794f41f699fd", clip_proven=True),   # item 164: our clip and screen seen on the glass, one scene is both its HUD and its video bank
    "aerosmith-1.16": dict(screen_proven=True, hud="025316286cba4a960ef130421f7dacdd", bank="dab80a17b8977c603e9094be6f072a58", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 48% clip, 47.7% screen, 0.0% before)
    "aerosmith_le-1.16": dict(screen_proven=True, hud="19d3c55effef1206080481e7e7faa16c", bank="dab80a17b8977c603e9094be6f072a58", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 48% clip, 47.4% screen, 0.0% before)
    "avengers_infinity_le-1.10": dict(screen_proven=True, hud="72bb8788254c99a686700ace0c6e2084", bank="0a433b8e07933efcc8704ca469036c97", bank_tree="demand_loaded", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 55% clip, 6.5% screen, 0.0% before)
    "avengers_infinity_pro-1.10": dict(screen_proven=True, hud="72bb8788254c99a686700ace0c6e2084", bank="0a433b8e07933efcc8704ca469036c97", bank_tree="demand_loaded", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 50% clip, 6.5% screen, 0.0% before)
    "batman-1.14": dict(screen_proven=True, hud="e16ea0837bc81a0381884c70d0c29d2e", bank="e16ea0837bc81a0381884c70d0c29d2e", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 6: straight to the mode game - its census game ended at the first drain and no second game started) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 70% clip, 6.5% screen, 0.0% before), the clip in a Video grafted into the HUD
    "deadpool_le-1.16": dict(screen_proven=True, hud="93e0751c2a35c8c46fc31dba43ed5eae", bank="e0e293019ac1e6977049c83dc8485496", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 65% clip, 6.5% screen, 0.0% before)
    "dungeons_and_dragons_le-1.10": dict(screen_proven=True, hud="e8bbe9670a9a212f18408a602d7b187b", bank="046915f6ff0a53b5608c8e7c4c2a976f", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 41% clip, 41.7% screen, 0.0% before)
    "dungeons_and_dragons_pro-1.10": dict(screen_proven=True, hud="76ac5e79ac7d5f8f3b916d925041f266", bank="046915f6ff0a53b5608c8e7c4c2a976f", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 43% clip, 42.7% screen, 0.0% before)
    "foo_fighters_pro-1.04": dict(screen_proven=True, hud="3f34991c6809a039dd47b2086a12937a", bank="469deda43d1ebfe2c5d371d5a800d0a9", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 52% clip, 54.2% screen, 0.0% before)
    "guardians-1.15": dict(screen_proven=True, hud="987ea6e129780ab93e8c704ac7ac3d1b", bank="a0683942e100705db906181685dd842e", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 47% clip, 47.0% screen, 0.0% before)
    "guardians_le-1.15": dict(screen_proven=True, hud="a252085d6b75ad25f754abda30430f6d", bank="a0683942e100705db906181685dd842e", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 47% clip, 47.3% screen, 0.0% before)
    "iron_maiden_le-1.18": dict(screen_proven=True, hud="efbfca7eef8fac5676abf224aa407d30", bank="efbfca7eef8fac5676abf224aa407d30", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 88% clip, 6.5% screen, 0.0% before)
    "iron_maiden_pro-1.18": dict(screen_proven=True, hud="dd66e6b1892401e2f70c79cfd3372965", bank="dd66e6b1892401e2f70c79cfd3372965", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 85% clip, 6.5% screen, 0.0% before)
    "james_bond_pro-1.06": dict(screen_proven=True, hud="832c77c669803d557c730a3be09fb9e5", bank="63f6bc13a70ee6f16f24fa6ab6e908fa", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 32% clip, 31.8% screen, 0.0% before)
    "jaws_pro-1.02": dict(screen_proven=True, hud="ca1567f39874d2cc3496216d132a4645", bank="908389471bb1044c57d8ad25b0471ca8", clip_proven=True),   # PAD-420 2026-10-08 media proof (stock card, hidden, muted, past Guided Setup): our screen and clip seen on the glass (magenta 62% clip, 6.5% screen, 0.0% before)
    "john_wick_le-1.02": dict(screen_proven=True, hud="3987a174e6faee23ca3cc20f1be66a70", bank="89fb64f9687944a2fd1eaeea22acfe01", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 74% clip, 73.9% screen, 0.0% before)
    "john_wick_pro-1.02": dict(screen_proven=True, hud="b61de78dc2e3379ec56f4922d55b1fc6", bank="89fb64f9687944a2fd1eaeea22acfe01", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 74% clip, 73.9% screen, 0.0% before)
    "jurassic_park_pro-1.16": dict(screen_proven=True, hud="40102c9e31901712d3534f1389c7666e", bank="3e222871d6c38b6b493fdfe59f788133", bank_tree="demand_loaded", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 53% clip, 53.2% screen, 0.0% before)
    "king_kong_pro-0.97": dict(screen_proven=True, hud="729b8fa01c630d32c25eecb7d9cf074a", bank="ed379c6514e73bead614fee25e93d862", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 56% clip, 74.9% screen, 0.0% before)
    "mando_le-1.45": dict(screen_proven=True, hud="35ae0bc3d1a5b4decda4c3717a7c0774", bank="390b28f5b7ef5b5e3f49edcee3088a29", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 40% clip, 39.5% screen, 0.0% before)
    "mando_pro-1.45": dict(screen_proven=True, hud="987328afe511ff4e5c7030d194ddc806", bank="390b28f5b7ef5b5e3f49edcee3088a29", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 40% clip, 39.5% screen, 0.0% before)
    "munsters_pro-1.28": dict(screen_proven=True, hud="056ab46ff95f247af8217f23eae382df", bank="056ab46ff95f247af8217f23eae382df", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 87% clip, 6.5% screen, 0.0% before)
    "rush_le-1.19": dict(screen_proven=True, hud="85f8f187e7bffe0d434076d406d7366c", bank="85f8f187e7bffe0d434076d406d7366c", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen seen on the glass (magenta 6.5% screen, 0.0% before); the clip not yet; PAD-420 2026-10-08 media proof (round 7, no census): the clip seen on the glass over the song video (magenta 73%) in a Video grafted into the HUD
    "rush_pro-1.19": dict(screen_proven=True, hud="4509258cd7d67da57a14d337ae421721", bank="4509258cd7d67da57a14d337ae421721", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen seen on the glass (magenta 6.5% screen, 0.0% before); the clip not yet; PAD-420 2026-10-08 media proof (round 7, no census): the clip seen on the glass over the song video (magenta 73%) in a Video grafted into the HUD
    "star_wars_le-1.31": dict(screen_proven=True, hud="9183de0da4e6ed603f16064ec7a8493b", bank="8d984a6a6e50a1d50241c80c0edab0b5", clip_proven=True),   # PAD-420 2026-10-08 media proof (stock card, hidden, muted; the ball-start hero / path choice confirmed with the Action Button first): our screen and clip seen on the glass (magenta 44% clip, 45% screen, 0.0% before)
    "star_wars_pro-1.31": dict(screen_proven=True, hud="101c344663e5acdcf0e9e5d42ef0f2ae", bank="8d984a6a6e50a1d50241c80c0edab0b5", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 4: two playfield switches first, its ball-start path/hero choice off the glass) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 44% clip, 45.1% screen, 0.0% before)
    "stranger_things-1.13": dict(screen_proven=True, hud="e3bb429535838471027451e9f6f86950", bank="e3bb429535838471027451e9f6f86950", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen seen on the glass (magenta 6.5% screen, 0.0% before); the clip not yet; PAD-420 2026-10-08 media proof (round 7, no census): the clip seen on the glass (magenta 75%) in a Video grafted into the HUD - its HUD draws no video bank in play
    "stranger_things_le-1.13": dict(screen_proven=True, hud="667b28929132f94722c28268ce559de8", bank="a6c50224ebf14f37444b84bb632c1b68", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 70% clip, 69.5% screen, 0.0% before)
    "sword_of_rage_le-1.19": dict(screen_proven=True, hud="20774409779b6a580c751be1b10f1767", bank="ca3bab9c0f7e7f02272fddb8ac269dfb", clip_proven=True),   # PAD-420 2026-10-08 media proof (round 3) (stock card, hidden, muted): our screen and clip seen on the glass (magenta 65% clip, 66.2% screen, 0.0% before)
    "sword_of_rage_pro-1.19": dict(screen_proven=True, hud="d21160f53c007b8147a3d1961efc498d", bank="ca3bab9c0f7e7f02272fddb8ac269dfb", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 66% clip, 66.2% screen, 0.0% before)
    "uncanny_xmen_pro-0.98": dict(screen_proven=True, hud="9d96a539bb3e5fda93d0429f3c7845ad", bank="4c5e3bd248dc09f1373c91111543f92e", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen and clip seen on the glass (magenta 44% clip, 44.0% screen, 0.0% before)
    "venom_pro-1.07": dict(screen_proven=True, hud="a9f8dc36cc2d7f144dcb00bd3e1adf71", bank="a9f8dc36cc2d7f144dcb00bd3e1adf71", clip_proven=True),   # PAD-420 2026-10-07 media proof (stock card, hidden, muted): our screen seen on the glass (magenta 6.5% screen, 0.0% before); the clip not yet; PAD-420 2026-10-08 media proof (round 7, no census): the clip seen on the glass (magenta 84%) in a Video grafted into the HUD - its HUD draws no video bank in play
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
    elif not callouts.get("countdown") and "%s-%s" % (game, version) in COUNTDOWN_NO_NUMBERS:
        no("countdown", "%(label)s's voice never says a number on its own (every callout on the "
                        "card was checked), so the game's own voice cannot count down.")
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
    elif not callouts.get("time_up") and not end_sound_carried(game, version):
        no("own_sound", "The app does not know %(label)s's time-up callout, the one a sound of "
                        "the mode's own plays in place of.")
    if all(n in sites for n in STACK_NEEDS[0]) and all(data.get(n) for n in STACK_NEEDS[1]):
        pass
    elif _stack_table(data, values) and key in STACK_PROVEN:
        pass
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN and _stack_flags(data, values)             and key in STACK_FLAGS_PROVEN:
        pass                                  # item 164: its other modes too, from their flags
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN and _stack_records(sites, values) \
            and key in STACK_RECORDS_PROVEN:
        pass                                  # item 165: its timed modes too, from the framework's live records
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN and _stack_bytes(data) and key in STACK_BYTES_PROVEN:
        pass                                  # item 165: its modes too, from their own running bytes
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN and _stack_objects(data, values)             and key in STACK_OBJECTS_PROVEN:
        pass                                  # item 165: its modes too, from their own rule objects
    elif _stack_balls(sites) and key in STACK_BALLS_PROVEN:
        stack_note = (STACK_NOTE_WHY.get(key) or
                      "On %s a mode of yours waits only for the game's multiballs: the app cannot yet "
                      "see its other modes.") % label
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
    cannot += list(_multiball_cannot(key, label, sites))     # item 167
    cannot += list(_ball_save_cannot(key, label, sites))     # PAD-225
    cannot += list(_magnet_cannot(key, label, port))         # PAD-381
    cannot += list(_scoop_cannot(key, label, port))          # PAD-381
    cannot += list(_coils_cannot(key, label, port))          # PAD-381
    cannot += list(_shield_cannot(key, label, port))         # PAD-392
    cannot += list(_shows_cannot(label, port))               # PAD-418
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
        insider_gate=all(n in sites for n in INSIDER_GATE_SITES),
        # item 147's events, as pad_mode_runtime.c's events_arm would arm them: a bus event
        # needs hook_dispatch, a site event its site. What each run measured is in the port.
        events=events,
        sound_note=TITLE_SOUND_UNHEARD.get("%s-%s" % (game, version), ""),
        score_bits=32 if RUNTIME_CORE_32[0] in sites else 64,
        switch_shots=switch_shots,
        switch_shots_note=switch_note,
        stack_note=stack_note,
        game_modes=_game_modes(port),
        game_rules=_game_rules(port),                        # PAD-398
        lamps=_lit_inserts(port) if key in LAMPS_PROVEN else 0,
        light_route=light_route,
        bank_tree=measured.get("bank_tree", "auto_loaded"),
        hud_tree=measured.get("hud_tree", "auto_loaded"),
        magnet_shot=_magnet_shot_name(port),                 # PAD-381
        held_coils=tuple((n, lab) for n, lab in _held_coils(port) if (key, n) in HELD_COILS_PROVEN),
        coil_caps=_coil_caps(port, [n for n, _l in _held_coils(port) if (key, n) in HELD_COILS_PROVEN]),   # PAD-420
        shield_rule=port["text"].get("shield_rule", "").strip(),             # PAD-392
        game_shows=_game_shows(port),                        # PAD-418
        absent=machine_absent(game),                         # PAD-420
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
    "john_wick_le-1.01", "jurassic_park_le-1.16", "jurassic_park_the_pin-1.05", "king_kong_le-0.97",
    "led_zeppelin_le-1.22", "led_zeppelin_pro-1.22", "metallica_spike-1.03", "munsters_le-1.28",
    "star_wars_elg-1.10", "star_wars_le-1.30", "turtles_le-1.59", "turtles_pro-1.59",
    "uncanny_xmen_le-0.98", "venom_le-1.07",
    # PAD-306 (2026-10-01, rig 3): the stock Metallica 1.04 card - light_all ff00ff held its 200 named inserts (1.03's
    # 198 and 1.04's two sling skulls, whose lights it names -R/-G/-B), and the shim's LED view had every playfield RGB
    # insert magenta while the mode ran (18 of 18 with the skulls), none before or after, and 85 of 85 single-colour
    # inserts lit (18-20 before and after); the expressive-lighting strip (node 2) took no colour, another output path
    "metallica_spike-1.04",
    # the SWELF generation, item 165 (2026-09-26): the lamp lines are LIGHT-table ids now (the earlier
    # device indices lit the wrong inserts, and the topper), and the proof is id-exact - light_all held
    # every insert in magenta AND light_insert held three named ones in grey, and the shim's LED view
    # (its enumeration gate gone, its 0x84/0x85 single-lamp writes read) had exactly that on the boards
    # it reads while the mode ran, not before or after: Aerosmith 104/104, Avengers 121/121, Guardians
    # 112/112, Iron Maiden 112/114, Mando 92/92, Rush 151/151 (its expressive-lighting strip past bank 0
    # is not in the plane), Stranger Things 92/92, Sword of Rage, and Batman 121/125 once the runtime dropped
    # the four ids past its 179 counted lights instead of every lamp - each with three named inserts at grey
    "aerosmith_le-1.15", "batman-1.13", "guardians_le-1.14", "mando_le-1.44", "rush_le-1.18",
    "avengers_infinity_le-1.09", "sword_of_rage_le-1.18", "iron_maiden_le-1.16",
    "stranger_things_le-1.12",
    # PAD-420 2026-10-07 (lights/lights_job.sh, stock card, hidden, muted): a mode file's light_all ff00ff held every
    # insert the port names; the shim's LED view had every addressed insert magenta while it ran and none before:
    #   aerosmith-1.16: 12/12 RGB, 68/68 single
    #   aerosmith_le-1.16: 18/18 RGB, 74/74 single
    #   deadpool_le-1.16: 7/7 RGB, 80/80 single
    #   dungeons_and_dragons_le-1.10: 36/36 RGB, 54/54 single
    #   dungeons_and_dragons_pro-1.10: 36/36 RGB, 54/54 single
    #   guardians-1.15: 10/10 RGB, 75/75 single
    #   iron_maiden_le-1.18: 42/42 RGB, 150/150 single
    "aerosmith-1.16",
    "aerosmith_le-1.16",
    "deadpool_le-1.16",
    "dungeons_and_dragons_le-1.10",
    "dungeons_and_dragons_pro-1.10",
    "guardians-1.15",
    "iron_maiden_le-1.18",
    # PAD-420 2026-10-07 (lights/lights_job.sh, stock card, hidden, muted): a mode file's light_all ff00ff held every
    # insert the port names; the shim's LED view had every addressed insert magenta while it ran and none before:
    #   guardians_le-1.15: 76/76 RGB, 39/39 single
    #   iron_maiden_pro-1.18: 16/16 RGB, 138/138 single
    #   james_bond_pro-1.06: 10/10 RGB, 78/78 single
    #   jurassic_park_pro-1.16: 9/9 RGB, 76/76 single
    #   star_wars_le-1.31: 15/15 RGB, 85/85 single
    "guardians_le-1.15",
    "iron_maiden_pro-1.18",
    "james_bond_pro-1.06",
    "jurassic_park_pro-1.16",
    "star_wars_le-1.31",
    # PAD-420 2026-10-07 (lights/lights_job.sh, stock card, hidden, muted): a mode file's light_all ff00ff held every
    # insert the port names; the shim's LED view had every addressed insert magenta while it ran and none before:
    #   star_wars_pro-1.31: 15/15 RGB, 82/82 single
    #   stranger_things-1.13: 8/8 RGB, 78/78 single
    #   stranger_things_le-1.13: 8/8 RGB, 78/78 single
    #   sword_of_rage_le-1.19: 48/48 RGB, 102/102 single
    #   sword_of_rage_pro-1.19: 44/44 RGB, 84/84 single
    #   uncanny_xmen_pro-0.98: 15/15 RGB, 70/70 single
    #   venom_pro-1.07: 57/57 RGB, 70/70 single
    "star_wars_pro-1.31",
    "stranger_things-1.13",
    "stranger_things_le-1.13",
    "sword_of_rage_le-1.19",
    "sword_of_rage_pro-1.19",
    "uncanny_xmen_pro-0.98",
    "venom_pro-1.07",
    # PAD-420 2026-10-08, the same proof on Batman 66 1.14's new port (its 22 block lines in): 6/6 RGB, 82/82 single
    # (8 and 7 single lit before and after: the game's own)
    "batman-1.14",
    # PAD-420 2026-10-08 run 16, the ball launched and 15 s settled first: Munsters Pro 1.28 5/5 RGB, 60/60 single
    # (9 lit before and after: the game's own); light_shots lit its 4 tied RGB and 10 tied single inserts
    "munsters_pro-1.28",
    # PAD-420 2026-10-08 (lights/lights_job2.sh + judge2.py, stock card, hidden, muted): a mode file's light_all ff00ff held
    # every insert the port names; the shim's LED view had every readable playfield insert magenta while it ran and
    # none before, and light_shots held every tied insert cyan. The cabinet's own lighting (the expressive-lighting
    # strip on node 2, the speaker lights on node 7) took no colour of ours - only the game's own shows; they are
    # not inserts, as Rush 1.18's proof counted:
    #   rush_le-1.19: 17/17 RGB, 79/79 single; shots 16/16
    #   rush_pro-1.19: 17/17 RGB, 64/64 single; shots 14/14
    "rush_le-1.19",
    "rush_pro-1.19",
    # PAD-420 2026-10-08 (lights/lights_job3.sh with PAD_NB_TRACE=1, lights/busjudge.py; stock card, hidden, muted) -
    # judged on the NODE BUS, the observable item mode-leds proved Godzilla's lights on: the shim's LED view misses
    # the bulk frames these games send when a mode holds every insert (it showed King Kong Pro's shot inserts in
    # the game's blue while the wire had them in ours). Each frame to the insert boards decoded with leddecode;
    # light_all ff00ff held every playfield insert in magenta (single-colour ones lit) while it ran, not before
    # nor 1.5 s after; light_shots held every tied insert cyan and no untied one. The cabinet's own lighting
    # (expressive strip, speaker, topper) is no insert, as above:
    #   avengers_infinity_le-1.10: 50/50 RGB, 132/132 single; shots 18/18
    #   avengers_infinity_pro-1.10: 44/44 RGB, 132/132 single; shots 18/18
    #   foo_fighters_pro-1.04: 24/24 RGB, 64/64 single; shots 8/8
    #   john_wick_le-1.02: 8/8 RGB, 98/98 single; shots 8/8
    #   john_wick_pro-1.02: 8/8 RGB, 97/97 single; shots 7/7
    #   king_kong_pro-0.97: 9/9 RGB, 100/100 single; shots 9/9
    #   mando_le-1.45: 15/15 RGB, 65/65 single; shots 11/11
    #   mando_pro-1.45: 13/13 RGB, 56/56 single; shots 9/9
    "avengers_infinity_le-1.10",
    "avengers_infinity_pro-1.10",
    "foo_fighters_pro-1.04",
    "john_wick_le-1.02",
    "john_wick_pro-1.02",
    "king_kong_pro-0.97",
    "mando_le-1.45",
    "mando_pro-1.45",
    # PAD-420 2026-10-08 (lights/lights_job4.sh with PAD_NB_TRACE=1, past Guided Setup; stock card, hidden, muted): light_all
    # in the LED view AND on the node bus - 13/13 RGB magenta, 94/94 single lit, none before or after; light_shots on
    # the bus only (the LED view showed none: the bulk frames it misses), 6/6 tied RGB inserts cyan, no untied one
    "jaws_pro-1.02",
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


def _game_modes(port):
    """PAD-363: ``((id, name, held off by default), ...)``, in id order: the game's own modes the port lets
    a mode keep from starting - a `site block_start_<id>` (with its `data block_obj_<id>` on a C++ title; a
    plain-C title's start is the mode's own), as pad_mode_runtime.c's block_arm hooks them, named by `text
    block_name_<id>`. PAD-398 (David, 2026-10-05: "when our custom modes start, we should ONLY be in those
    modes"): every one is held off by default, as the runtime does with a mode that lists none."""
    text = port["text"]
    out = []
    for site in port["site"]:
        tail = site[len("block_start_"):] if site.startswith("block_start_") else ""
        if tail.isdigit() and int(tail) < 128:
            i = int(tail)
            out.append((i, text.get("block_name_" + tail, "").strip() or "mode %d" % i, True))
    return tuple(sorted(out))


def _game_rules(port):
    """PAD-398: ``((n, name), ...)``, in number order: the game's rules - its features (Godzilla's Destruction
    Jackpot, building locks, bridge, cities...) - the port names (`site block_rule_<n>`, `text
    block_rule_name_<n>`, sdk/rule_lines.py). While a mode of ours blocks, each sees no shots, so nothing of
    the game's lights, locks, counts or awards, unless the mode keeps it counting (``keep_rules``)."""
    text = port["text"]
    out = []
    for site in port["site"]:
        tail = site[len("block_rule_"):] if site.startswith("block_rule_") else ""
        if tail.isdigit() and int(tail) < 32:
            out.append((int(tail), text.get("block_rule_name_" + tail, "").strip() or "rule %s" % tail))
    return tuple(sorted(out))


def _shots_with_switches(port):
    """``(shots, switch_shot_names)``: the port's `shot` lines, then each `switch` line's name that
    is not a shot already, as the runtime's port reader adds them. Switch lines count only when the
    port names a switch_edge or switch_hit site (the runtime arms them only through one)."""
    shots = list(port["shot"])
    names = []
    # PAD-416: `text internal_shots` names switch shots for code only (Godzilla Premium/LE's "Trough": a drain, the
    # moment it happens) - a mode's code asks for them by name; the tab does not offer them
    internal = {n.strip() for n in port.get("text", {}).get("internal_shots", "").split(",") if n.strip()}
    if "switch_edge" in port["site"] or any(s.startswith("switch_hit") for s in port["site"]):
        known = {n for n, _m in shots} | internal
        for _sw, mask, name in port.get("switch", ()):
            if name not in known:
                known.add(name)
                shots.append((name, mask))
                names.append(name)
    return tuple(shots), tuple(names)


def port_path(p):
    """The port file behind a profile, or "" when it has none."""
    return os.path.join(PORTS_DIR, p.port) if p.port else ""


#: PAD-363: the hand-written profile offers the game's modes its port lets a mode hold off, as a read port does
#: PAD-394: and its magnet, scoop and held coils, judged from the port as a read port's are
try:
    _port_115 = read_port(port_path(GODZILLA_PRO_1_15))
    _key_115, _label_115 = "godzilla_pro-1.15", "Godzilla Pro 1.15"
    GODZILLA_PRO_1_15 = replace(
        GODZILLA_PRO_1_15, game_modes=_game_modes(_port_115), game_rules=_game_rules(_port_115),
        magnet_shot=_magnet_shot_name(_port_115),
        held_coils=tuple((n, lab) for n, lab in _held_coils(_port_115) if (_key_115, n) in HELD_COILS_PROVEN),
        game_shows=_game_shows(_port_115),
        absent=machine_absent("godzilla_pro"),
        cannot=tuple(c for c in GODZILLA_PRO_1_15.cannot
                     if c[0] not in ("magnet", "scoop", "coils", "shield", "shows"))
        + _magnet_cannot(_key_115, _label_115, _port_115) + _scoop_cannot(_key_115, _label_115, _port_115)
        + _coils_cannot(_key_115, _label_115, _port_115) + _shield_cannot(_key_115, _label_115, _port_115)
        + _shows_cannot(_label_115, _port_115))
except OSError:
    pass
PROFILES = {p.key: p for p in (GODZILLA_PRO_1_15,)}


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
#: PAD-314: a mode started by shots made in ORDER (``starts_on "sequence"``): how many at least and
#: at most (mode_file.c's SEQ_MAX)
SEQUENCE_MIN, SEQUENCE_MAX = 2, 8
#: PAD-314: ``end_shot`` meaning every playfield shot that is not one of the mode's own (the shots
#: that score, and in a multiball the shot that adds a ball and the one the balls come on); the
#: cabinet buttons are never "other". Bracketed so it can never be a port's shot name.
END_SHOT_OTHERS = "(any shot that does not score)"


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
    # PAD-323: where the screen goes, as laid out in the Scenes editor ({} = placed automatically;
    # mode_assets.LAYOUT_KEYS: x, y, scale, words_x, words_y, words_scale, order)
    screen_layout: dict = field(default_factory=dict)
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
    # PAD-363: what it does about the game's own modes. "stack": runs beside them (its screen steps aside);
    # "give_way": starts only while none runs, and one beginning ends it; "block": as give_way, and while it
    # runs the game's modes in block_modes (the title's game_modes ids; [] = every one the port names)
    # cannot start. Never a multiball (game_mode_blocks.py). PAD-398 (David, 2026-10-05: "when our custom
    # modes start, we should ONLY be in those modes unless explicitly noted"): "block" is the default, and
    # while it blocks every rule of the game's (its features: game_rules) sees no shots but the ones named in
    # keep_rules, so none of the game's jackpots, locks or multiballs light or count
    game_modes: str = "block"
    block_modes: list = field(default_factory=list)
    keep_rules: list = field(default_factory=list)   # PAD-398: names from the title's game_rules
    # item 141, the Advanced section: every other parameter the runtime has
    award_ladder: str = "rising"         # rising: the Nth shot pays N x; fixed: every shot x 1
    shot_award: list = field(default_factory=list)   # [[shot name, points]]: pays instead of award
    end_shot: object = ""                # what ends the mode early: "" = nothing; a shot name; PAD-314: a
    #                                      LIST of shot names (any of them), or END_SHOT_OTHERS (any
    #                                      playfield shot that is not the mode's own)
    clip_both: dict = field(default_factory=dict)    # {} = one clip; else a second clip at the
    #                                      other end: {clip: same|title|file, title, file, seconds}
    callout_at: list = field(default_factory=list)   # [[seconds left, callout id]], on top of
    #                                      the countdown's own
    restore_after: int = 6               # seconds the screen stays up after the mode ends
    # what starts and ends it (item 147): "shot" (start_shot x start_count), "event <name>" or
    # "sequence" (PAD-314: start_sequence made in order); "drain" (its clock or the ball ending),
    # "clock" (its clock only) or "event <name>"
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
    # item 167: a multiball of the mode's own (MODE_SDK.md "A multiball of your own"): when it starts
    # the game serves balls until `balls` are in play, with its own ball save; the mode ends when one
    # ball is left (its clock still counts when `seconds` is not 0). A shot may add a ball.
    multiball: bool = False
    balls: int = 3                       # 2-6 in play together (cut to what the machine has)
    ball_save: int = 10                  # seconds a drained ball comes back for, 0-60
    add_ball_shot: str = ""              # a shot that puts one more ball in play; "" = none
    add_ball_max: int = 1                # ... up to this many times a run, 1-6
    # PAD-225: a ball save when it starts, with no multiball: a drained ball is served back for this many
    # seconds (1-60), through the game's own ball saver; 0 = none. A multiball uses its own ball_save.
    start_ball_save: int = 0
    # PAD-228: the balls come on this shot while the mode runs (the Action button: "press it now for a
    # multiball"), not when it starts; its clock is the window to hit it. "" = when it starts
    multiball_on_shot: str = ""
    # PAD-227: more than one thing to meet before it starts (MODE_PARAMETERS.md `trigger_also`, `after`)
    start_also: list = field(default_factory=list)   # [[shot name, count]]: hit these too, in one ball
    after: str = ""                      # another mode's NAME: starts only once that one has run; "" = none
    after_when: str = "game"             # ball | game: ... this ball, or this game
    # PAD-314: with starts_on "sequence", the shots to make in THIS order, in one ball (2-8 names;
    # MODE_PARAMETERS.md `trigger_seq`). A shot of the sequence made out of turn starts the player
    # over; sequence_reset_any makes every other playfield shot do so too (`trigger_seq_reset`)
    start_sequence: list = field(default_factory=list)
    sequence_reset_any: bool = False
    # PAD-381: while it runs, every hit of the shot the magnet sits at (the profile's magnet_shot: on Godzilla
    # the Godzilla target), the one that starts it included, holds the ball on the magnet this many ms
    # (MAGNET_MIN_MS..MAGNET_MAX_MS; the runtime's own limits still apply); 0 = never
    magnet_ms: int = 0
    # PAD-381: while it runs, a ball that settles in the scoop is held there this many ms more once the game
    # is done with it (SCOOP_MIN_MS..SCOOP_MAX_MS), then the game kicks it out as always; 0 = never
    scoop_hold_ms: int = 0
    # PAD-381: other mechanisms held like the magnet: [[coil name, ms, shot]] - the shot "" holds once as the mode
    # starts, a shot name on every hit of it while the mode runs (the profile's held_coils names the coils)
    coil_holds: list = field(default_factory=list)
    # PAD-392: while it runs the shield targets face the player (Godzilla Premium/LE's platform turns 1.5 s after it
    # starts, is kept there, and turns back when it ends) - only while the game's own shield feature sees no shots
    shield: bool = False
    # PAD-418: the game's own light show at its start and at its end, by the port's name for it (the profile's
    # game_shows); "" = none. The end's is skipped when the ball is ending (the game stops every show of its own then)
    show_start: str = ""
    show_end: str = ""
    # PAD-396: the mode on the title's OTHER models (the Pro beside the Premium/LE): {model word: {field: value}}
    # of MODEL_FIELDS, as the mode last was on that model, put back when it goes back (:func:`port_model`)
    models: dict = field(default_factory=dict)
    # PAD-396: MODEL_FIELDS as the last port to this model made them, so an edit made since can be told from it
    ported: dict = field(default_factory=dict)

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
    if not p.can("multiball"):
        spec.multiball = False
    if not p.can("ball_save"):
        spec.start_ball_save = 0
    if not p.can("magnet"):
        spec.magnet_ms = 0
    if not p.can("scoop"):
        spec.scoop_hold_ms = 0
    if not p.can("coils"):
        spec.coil_holds = []
    if not p.can("shield"):
        spec.shield = False
    if not p.can("shows"):
        spec.show_start = spec.show_end = ""
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


#: The model suffixes a Spike 2 game dir carries: the title behind ``godzilla_pro`` and
#: ``godzilla_le`` is ``godzilla``. ``james_bond_60th_le`` and ``james_bond_le`` stay two
#: titles, as do ``star_wars_le`` and ``star_wars_elg``, ``jurassic_park_le`` and
#: ``jurassic_park_the_pin``: only a model word comes off.
MODEL_SUFFIXES = ("_pro", "_le", "_premium", "_prem")


def title_family(game_dir):
    """The title behind a build's game dir with its model taken off (``turtles_pro`` and
    ``turtles_le`` -> ``turtles``), so the builds of one game can be told from another
    game's. A game dir with no model word is its own family (``beatles``, ``batman``)."""
    g = (game_dir or "").lower().strip()
    for s in MODEL_SUFFIXES:
        if g.endswith(s) and len(g) > len(s):
            return g[:-len(s)]
    return g


def family_of_key(key):
    """:func:`title_family` of a profile key (``godzilla_le_1_16`` -> ``godzilla``): a key
    is the game dir and the version with its dots as underscores, so the version comes off
    first. Answers for a title whose port this machine no longer has, too."""
    return title_family(re.sub(r"(_\d+)+$", "", str(key or "")))


def same_title(a, b):
    """Are profiles ``a`` and ``b`` builds of ONE title - another version, or the Pro beside
    the Premium/LE? Such builds number their calls alike: every callout the Pro and LE ports
    of Godzilla 1.16, TMNT 1.59 and Led Zeppelin 1.22 measured has the same id on both, as
    do Godzilla Pro 1.15 and 1.16, so a callout id typed on one is kept on the other
    (:func:`retarget`). Another title's id is some other sound, and is dropped."""
    return title_family(a.game_dir) == title_family(b.game_dir)


def retarget(spec, p):
    """``spec`` for title ``p``: a COPY whose shots are matched by NAME. Returns
    ``(copy, dropped)``, ``dropped`` being the shot names ``p`` does not have. A start
    shot it lacks becomes the port's example start shot; the parts the title cannot do
    are left as they are (the tab greys them and a build leaves them out)."""
    out = ModeSpec.from_json(spec.to_json())
    names = [n for n, _m in p.shots]
    dropped = []
    model_port = _port_model(out, spec.title, p)      # PAD-396: the Pro beside the Premium/LE
    if out.start_shot not in names:
        if out.start_shot:
            dropped.append(out.start_shot)
        out.start_shot = p.example_start_shot if p.example_start_shot in names else names[0]
    dropped += [s for s in out.scoring_shots if s not in names]
    out.scoring_shots = [s for s in out.scoring_shots if s in names]
    if isinstance(out.start_also, list):             # PAD-227: matched by name, as the start shot
        kept = []
        for row in out.start_also:
            shot = row[0] if isinstance(row, (list, tuple)) and len(row) == 2 else None
            if isinstance(shot, str) and shot not in names:
                dropped.append(shot)
                continue
            kept.append(row)
        out.start_also = kept
    if isinstance(out.start_sequence, list):         # PAD-314: the shots in order, matched by name
        gone = [s for s in out.start_sequence if isinstance(s, str) and s not in names]
        dropped += [s for s in gone if s not in dropped]
        out.start_sequence = [s for s in out.start_sequence if s not in gone]
    _retarget_advanced(out, spec.title, p, names, dropped)
    out.title = p.key
    if model_port:
        out.ported = _model_fields(out)
    return out, dropped


# ---- PAD-396: the Pro beside the Premium/LE ---------------------------------------------
#: The parts of a mode that belong to ONE model of a title: its shots and the mechanisms it holds. A
#: mode taken to another model of its title keeps these as they were in ``models[<old model>]`` and
#: takes that model's own from ``models[<new model>]`` when it has been there before, else they are
#: matched (:func:`_port_model`). Everything else - the name, clock, points, screen, clip, sounds,
#: lights - is the same mode on every model.
MODEL_FIELDS = ("start_shot", "start_also", "start_sequence", "scoring_shots", "shot_award", "end_shot",
                "add_ball_shot", "multiball_on_shot", "magnet_ms", "scoop_hold_ms", "coil_holds",
                "shield", "show_start", "show_end")
#: what each model word is called in the words
MODEL_WORDS = {"pro": "Pro", "le": "Premium/LE", "premium": "Premium", "prem": "Premium"}


def model_of_key(key):
    """The model word of a profile key (``godzilla_le_1_16`` -> ``le``, ``beatles_1_0`` -> ``""``)."""
    g = re.sub(r"(_\d+)+$", "", str(key or "")).lower()
    for s in MODEL_SUFFIXES:
        if g.endswith(s) and len(g) > len(s):
            return s[1:]
    return ""


def model_word(key):
    """``Pro`` / ``Premium/LE`` for a profile key; "" for a title with one model."""
    m = model_of_key(key)
    return MODEL_WORDS.get(m, m.upper())


def other_model(old_key, p):
    """Is title ``p`` the same game as ``old_key`` on ANOTHER model (the Pro beside the Premium/LE)?"""
    a, b = model_of_key(old_key), model_of_key(p.key)
    return bool(a and b and a != b and family_of_key(old_key) == title_family(p.game_dir))


def _model_fields(spec):
    return {f: json.loads(json.dumps(getattr(spec, f))) for f in MODEL_FIELDS}


def shot_twin(name, src, p):
    """The shot of ``p`` that ``name`` (a shot of ``src``, the same game) is: ``name`` itself when ``p``
    has it, else ``p``'s one shot on the same switches (Godzilla's Premium "Shield ramp spinner" is the
    Pro's "Right spinner"; the Premium's centre shield target is the switch the Pro calls its right one).
    None when ``p`` has neither."""
    have = dict(p.shots)
    if name in have:
        return name
    mask = dict(src.shots).get(name) if src is not None else None
    if not mask:
        return None
    same = [n for n, m in p.shots if m == mask]
    return same[0] if len(same) == 1 else None


def _map_shots(spec, fn):
    """Every shot name ``spec`` holds, put through ``fn`` (a name -> a name), lists kept free of repeats."""
    def one(n):
        return fn(n) if isinstance(n, str) and n else n

    def uniq(xs):
        out = []
        for x in xs:
            if x not in out:
                out.append(x)
        return out

    spec.start_shot = one(spec.start_shot)
    if isinstance(spec.scoring_shots, list):
        spec.scoring_shots = uniq([one(s) for s in spec.scoring_shots])
    if isinstance(spec.start_sequence, list):
        spec.start_sequence = [one(s) for s in spec.start_sequence]
    for key in ("start_also", "shot_award"):
        rows = getattr(spec, key)
        if isinstance(rows, list):
            setattr(spec, key, [[one(r[0]), r[1]] if isinstance(r, (list, tuple)) and len(r) == 2 else r
                                for r in rows])
    if isinstance(spec.end_shot, list):
        spec.end_shot = uniq([one(s) for s in spec.end_shot])
    elif spec.end_shot != END_SHOT_OTHERS:
        spec.end_shot = one(spec.end_shot)
    spec.add_ball_shot = one(spec.add_ball_shot)
    spec.multiball_on_shot = one(spec.multiball_on_shot)
    if isinstance(spec.coil_holds, list):
        spec.coil_holds = [[r[0], r[1], one(r[2])] if isinstance(r, (list, tuple)) and len(r) == 3 else r
                           for r in spec.coil_holds]


def _port_model(out, old_key, p):
    """Match ``out`` (a copy of a mode of ``old_key``) to title ``p`` when ``p`` is the same game, before
    :func:`retarget` matches it by name. Any version or model of it: a shot ``p`` names otherwise is
    taken by its switches (:func:`shot_twin`). Another MODEL (PAD-396): ``out``'s :data:`MODEL_FIELDS`
    are kept in ``out.models`` under the old model, and the new model's own, when the mode was there
    before, come back; else the mechanisms ``p`` cannot hold are left out. Returns True for another
    model."""
    if old_key == p.key or family_of_key(old_key) != title_family(p.game_dir):
        return False
    try:
        src = profile(old_key)
    except ModeProjectError:
        src = None
    # a copy: ``out`` came from to_json/from_json, which share the dict with the mode it was made from
    out.models = json.loads(json.dumps(out.models)) if isinstance(out.models, dict) else {}
    port = other_model(old_key, p)
    if port:
        out.models[model_of_key(old_key)] = _model_fields(out)
        mine = out.models.pop(model_of_key(p.key), None)
        if isinstance(mine, dict):
            for f in MODEL_FIELDS:
                if f in mine:
                    setattr(out, f, json.loads(json.dumps(mine[f])))
            src = p                     # its own shots: nothing to match
    _map_shots(out, lambda n: shot_twin(n, src, p) or n)
    if port:
        held = dict(p.held_coils) if p.can("coils") else {}
        if isinstance(out.coil_holds, list):
            out.coil_holds = [r for r in out.coil_holds
                              if isinstance(r, (list, tuple)) and r and r[0] in held]
        if not p.can("magnet"):
            out.magnet_ms = 0
        if not p.can("scoop"):
            out.scoop_hold_ms = 0
        if not p.can("shield"):
            out.shield = False
    return port


def port_words(old, new, p):
    """What taking ``old`` to title ``p`` did for the model (PAD-396), as phrases for
    :func:`retarget_words`: its own version for ``p`` put back, the shots it calls by another name there,
    the mechanisms ``p`` does not have; and that its old model's version is kept. [] for the same model,
    or when nothing differs."""
    if not other_model(old.title, p):
        return []
    was, now = model_word(old.title), p.label
    kept = "its %s shots and mechanisms are kept in the mode for when it goes back" % was
    try:
        src = profile(old.title)
    except ModeProjectError:
        src = None
    seen, twin = [], ModeSpec.from_json(json.loads(json.dumps(old.to_json())))
    _map_shots(twin, lambda n: seen.append(n) or shot_twin(n, src, p) or n)
    if isinstance(old.models, dict) and isinstance(old.models.get(model_of_key(p.key)), dict)             and _model_fields(new) != _model_fields(twin):
        return ["it takes back its own shots and mechanisms for %s, as you left them there" % now, kept]
    words = []
    for n in seen:
        line = "%s is %s on %s" % (n, shot_twin(n, src, p), now)
        if shot_twin(n, src, p) not in (None, n) and line not in words:
            words.append(line)
    held = dict(p.held_coils) if p.can("coils") else {}
    names = dict(getattr(src, "held_coils", ()) or ())
    gone = []
    for r in old.coil_holds if isinstance(old.coil_holds, list) else ():
        if isinstance(r, (list, tuple)) and r and r[0] not in held:
            label = "the " + names.get(r[0], str(r[0]))
            if label not in gone:
                gone.append(label)
    if _int_or_none(old.magnet_ms) and not new.magnet_ms:
        gone.append("the magnet")
    if _int_or_none(old.scoop_hold_ms) and not new.scoop_hold_ms:
        gone.append("the scoop")
    if old.shield is True and not new.shield:
        gone.append("the shield platform")
    shows = [s for s in (old.show_start, old.show_end)
             if isinstance(s, str) and s and s not in (new.show_start, new.show_end)]
    if gone:
        words.append("%s does not hold %s, so %s left out there" % (
            now, " or ".join(gone), "it is" if len(gone) == 1 else "they are"))
    if shows:                                        # PAD-418
        words.append("%s does not have the light show%s %s, so %s left out there" % (
            now, "" if len(shows) == 1 else "s", " or ".join(shows), "it is" if len(shows) == 1 else "they are"))
    if gone or shows:
        words.append(kept)
    return words


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
    "Ten seconds left" 1291 is 1387 on Jaws); any other id is dropped as ``"callout <id>"``
    - unless the two builds are ONE title (:func:`same_title`: another version, or the Pro
    beside the Premium/LE), whose sound table numbers its calls alike: then it is kept as it
    is. A row that is not ``[seconds, id]`` is left for :func:`validate` to name."""
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
    if isinstance(out.end_shot, list):                  # PAD-314: any of these shots, matched by name
        gone = [s for s in out.end_shot if isinstance(s, str) and s not in names]
        dropped += [s for s in gone if s not in dropped]
        out.end_shot = [s for s in out.end_shot if s not in gone]
    elif isinstance(out.end_shot, str) and out.end_shot and out.end_shot not in names \
            and out.end_shot != END_SHOT_OTHERS:        # PAD-314: "any other shot" names no shot
        if out.end_shot not in dropped:
            dropped.append(out.end_shot)
        out.end_shot = ""
    if isinstance(out.add_ball_shot, str) and out.add_ball_shot and out.add_ball_shot not in names:
        if out.add_ball_shot not in dropped:                # item 167
            dropped.append(out.add_ball_shot)
        out.add_ball_shot = ""
    if isinstance(out.multiball_on_shot, str) and out.multiball_on_shot and out.multiball_on_shot not in names:
        if out.multiball_on_shot not in dropped:            # PAD-228
            dropped.append(out.multiball_on_shot)
        out.multiball_on_shot = ""
    if old_key != p.key and isinstance(out.block_modes, list) and out.block_modes:
        # PAD-363: an id is a number in THAT game's mode table, so the list is matched by name
        try:
            was = {i: name for i, name, _on in profile(old_key).game_modes}
        except ModeProjectError:
            was = {}
        now = {}
        for i, name, _on in getattr(p, "game_modes", ()):
            now.setdefault(name, []).append(i)
        out.block_modes = sorted({j for i in out.block_modes if isinstance(i, int) for j in now.get(was.get(i), ())})
    if old_key != p.key and isinstance(out.keep_rules, list) and out.keep_rules:
        # PAD-398: kept by name; a feature the other game does not have is dropped
        have = {name for _n, name in getattr(p, "game_rules", ())}
        out.keep_rules = [r for r in out.keep_rules if r in have]
    if old_key != p.key:
        # PAD-418: a light show is the game's own, asked for by name: one the other game does not name is dropped
        have = {name for name, _k, _s in getattr(p, "game_shows", ())}
        for f in ("show_start", "show_end"):
            if isinstance(getattr(out, f), str) and getattr(out, f) not in have:
                setattr(out, f, "")
    if old_key == p.key or not isinstance(out.callout_at, list):
        return
    try:
        old = profile(old_key)
    except ModeProjectError:
        old = None
    was = {n: label for label, n in callout_choices(old) if n} if old is not None else {}
    now = {label: n for label, n in callout_choices(p) if n}
    family = family_of_key(old_key) == title_family(p.game_dir)
    kept = []
    for row in out.callout_at:
        cid = _int_or_none(row[1]) if isinstance(row, (list, tuple)) and len(row) == 2 else None
        if cid is None:
            kept.append(row)
        elif was.get(cid) in now:
            new = now[was[cid]]
            kept.append(row if new == cid else [row[0], new])
        elif family:
            kept.append(row)            # the same game's sound table: the id is the same call
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


def retarget_words(old, new, dropped, p):
    """What :func:`retarget` changed taking ``old`` to title ``p`` (``new`` and ``dropped``
    are its returns), as one sentence for the person; "" when nothing changed. The Modes
    tab says it in its status line when a mode is opened on another card's project, and
    :func:`copy_modes` in its report."""
    words = port_words(old, new, p)                  # PAD-396
    if old.start_shot and new.start_shot != old.start_shot and old.start_shot in dropped:
        words.append("%s is not a shot on %s, so it starts on %s until you pick one" % (
            old.start_shot, p.label, new.start_shot))
    gone = [s for s in old.scoring_shots if s in dropped]
    if gone:
        words.append("%s %s not on %s, so %s left out of the shots that score" % (
            ", ".join(gone), "is" if len(gone) == 1 else "are", p.label,
            "it is" if len(gone) == 1 else "they are"))
    seq = old.start_sequence if isinstance(old.start_sequence, list) else []
    gone = sorted({s for s in seq if s in dropped}, key=seq.index)   # PAD-314
    if gone:
        words.append("%s %s not a shot on %s, so %s left out of the shots that start the mode in order" % (
            ", ".join(gone), "is" if len(gone) == 1 else "are", p.label,
            "it is" if len(gone) == 1 else "they are"))
    words += retarget_advanced_words(old, new, dropped, p)
    return "; ".join(words)


def retarget_advanced_words(old, new, dropped, p):
    """The Advanced part of :func:`retarget_words`: per-shot points and an early-ending shot
    on a shot the title lacks, callouts of another game left out, and the measured callouts
    that moved to the title's own ids."""
    words = []
    rows = old.shot_award if isinstance(old.shot_award, list) else []
    paid = []
    for row in rows:
        if (isinstance(row, (list, tuple)) and len(row) == 2 and row[0] in dropped
                and row[0] not in paid):
            paid.append(row[0])
    if paid:
        words.append("%s %s not on %s, so %s own points %s left out" % (
            ", ".join(paid), "is" if len(paid) == 1 else "are", p.label,
            "its" if len(paid) == 1 else "their", "are"))
    if isinstance(old.end_shot, str) and old.end_shot and not new.end_shot:
        words.append("%s is not on %s, so no shot ends the mode early until you pick one" % (
            old.end_shot, p.label))
    elif isinstance(old.end_shot, list):             # PAD-314: any of these shots
        gone = [s for s in old.end_shot if s in dropped]
        if gone:
            words.append("%s %s not on %s, so %s left out of the shots that end the mode early" % (
                ", ".join(gone), "is" if len(gone) == 1 else "are", p.label,
                "it is" if len(gone) == 1 else "they are"))
    calls = dropped_callouts(dropped)
    if calls:
        words.append("%s %s a sound number of another game and no callout measured on %s, "
                     "so %s left out" % (", ".join(calls), "is" if len(calls) == 1 else "are each",
                                          p.label, "it is" if len(calls) == 1 else "they are"))
    before = old.callout_at if isinstance(old.callout_at, list) else []
    moved = ["callout %s is %s" % (a[1], b[1]) for a, b in zip(
        [r for r in before if isinstance(r, (list, tuple)) and len(r) == 2
         and CALLOUT_DROPPED % _int_or_none(r[1]) not in calls],
        [r for r in new.callout_at if isinstance(r, (list, tuple)) and len(r) == 2])
        if _int_or_none(a[1]) != _int_or_none(b[1])]
    if moved:
        words.append("%s on %s, the same call" % (", ".join(moved), p.label))
    return words


# ---- copying modes to another card's project ----------------------------------------
#: What :func:`copy_modes` says became of each mode.
COPY_CARRIED = "carried"      # saved for the destination's card: it builds there as it is
COPY_TO_FIX = "to fix"        # copied as it was: open it there and pick what the card lacks
COPY_CODE = "code"            # a code mode, copied as it is
COPY_SKIPPED = "skipped"      # not copied; ``words`` says why


@dataclass
class CopiedMode:
    slug: str                 # in the project it came from
    name: str
    state: str                # one of the COPY_* words
    new_slug: str = ""        # in the destination; "" when it was not copied
    words: str = ""           # what changed on the way, or why it was not copied

    def line(self, label):
        """One line for the log: where it went, and what to do about it."""
        if self.state == COPY_SKIPPED:
            return "%s: not copied: %s" % (self.name, self.words)
        where = "%s -> modes/%s" % (self.name, self.new_slug)
        if self.state == COPY_CODE:
            return "%s: a code mode, copied as it is (%s)" % (where, self.words)
        if self.state == COPY_TO_FIX:
            return "%s: open it there and pick again: %s" % (where, self.words)
        return "%s: runs on %s as it is%s" % (where, label, "; " + self.words if self.words else "")

    def to_json(self):
        return {"slug": self.slug, "name": self.name, "state": self.state,
                "new_slug": self.new_slug, "words": self.words}


@dataclass
class CopyReport:
    src: str
    dest: str
    label: str                # the destination card's title, as its port names it
    modes: list = field(default_factory=list)

    def of(self, state):
        return [m for m in self.modes if m.state == state]

    def lines(self):
        return [m.line(self.label) for m in self.modes]

    def summary(self):
        """The words for a message box: the counts, then a line per mode."""
        copied = [m for m in self.modes if m.state != COPY_SKIPPED]
        parts = []
        n = len(self.of(COPY_CARRIED))
        if n:
            parts.append("%d run%s on %s as %s" % (n, "s" if n == 1 else "", self.label,
                                                  "it is" if n == 1 else "they are"))
        n = len(self.of(COPY_TO_FIX))
        if n:
            parts.append("%d need%s a look there: open %s in that project's Modes tab and pick "
                         "what %s lacks" % (n, "s" if n == 1 else "", "it" if n == 1 else "each",
                                             self.label))
        n = len(self.of(COPY_CODE))
        if n:
            parts.append("%d code mode%s copied as %s" % (n, "" if n == 1 else "s",
                                                          "it is" if n == 1 else "they are"))
        n = len(self.of(COPY_SKIPPED))
        if n:
            parts.append("%d not copied" % n)
        head = "Copied %d mode%s into %s for %s." % (len(copied), "" if len(copied) == 1 else "s",
                                                     self.dest, self.label)
        if parts:
            head += " " + "; ".join(parts) + "."
        return head + ("\n\n" + "\n".join(self.lines()) if self.modes else "")

    def to_json(self):
        return {"src": self.src, "dest": self.dest, "label": self.label,
                "modes": [m.to_json() for m in self.modes]}


def _free_slug(project, base, taken):
    """``base``, else ``base_2``, ``base_3``...: the first not in ``taken`` and not a folder
    under ``project``'s modes."""
    slug, n = base, 2
    while slug in taken or os.path.exists(mode_folder(project, slug)):
        slug, n = "%s_%d" % (base, n), n + 1
    return slug


def copy_modes(src, dest, slugs=None, replace=False):
    """Copy the modes of project ``src`` into project ``dest``, for the card ``dest`` was made
    from. Each mode goes as its whole folder (picture, clip and sounds too) and is matched
    to that card's title the way opening it there would be (:func:`retarget`: shots by
    NAME, callouts by role or within the title family). A mode that loses nothing is saved
    for the title, so it builds there as it is; one that names a shot the card lacks is
    copied as it was, so a build there keeps refusing it until it is opened and its shots
    picked - its words say which. A code mode (``modes/<slug>/<slug>.c``) is copied as it
    is. ``slugs`` picks some; None takes them all. Nothing in ``src`` changes. ``replace``
    (:func:`port_modes`) puts a mode over the one of its folder name already in ``dest``: True
    each one, else those of the folder names it holds (PAD-402).

    Returns a :class:`CopyReport`. Raises :class:`ModeProjectError` when ``dest`` is
    ``src`` itself, names no card, or is a card with no port."""
    src = os.path.normpath(str(src or ""))
    dest = os.path.normpath(str(dest or ""))
    for folder in (src, dest):
        if not folder or not os.path.isdir(folder):
            raise ModeProjectError("%s is not a folder" % (folder or "(no folder)"))
    if _norm_path(src) == _norm_path(dest):
        raise ModeProjectError("that is this project: Duplicate copies a mode within it")
    card, p = project_profile(dest)
    if card is None:
        raise ModeProjectError("%s names no card, so the app does not know which game its modes "
                               "would be for: extract a card into it first (Extract tab)." % dest)
    if not card.game_dir:
        raise ModeProjectError("the app has not read which game the card of %s is: open that "
                               "project in the Extract tab first." % dest)
    if p is None:
        raise ModeProjectError(NO_PORT_HELP % card.label())
    from . import code_modes as CM
    found, broken = list_modes(src)
    specs, why_broken = dict(found), dict(broken)
    codes = CM.code_slugs(src)
    want = list(slugs) if slugs is not None else [s for s, _ in found] + codes
    report = CopyReport(src=src, dest=dest, label=p.label)
    there = list_modes(dest)[0]
    taken = {s for s, _ in there} | set(CM.code_slugs(dest))
    room = MAX_MODES - len(there)
    there_specs = dict(there)
    for slug in want:
        if slug in specs:
            spec = specs[slug]
            over = there_specs.get(slug) if _replaces(replace, slug) else None
            if over is not None:
                spec = _keep_their_model(spec, over, p)
            elif room <= 0:
                report.modes.append(CopiedMode(slug, spec.name, COPY_SKIPPED, words=(
                    "a card holds at most %d modes, and %s has them" % (MAX_MODES, dest))))
                continue
            new, dropped = retarget(spec, p)
            if over is not None:
                new_slug = slug
                shutil.rmtree(mode_folder(dest, slug))
            else:
                new_slug = _free_slug(dest, slug, taken)
                room -= 1
            shutil.copytree(mode_folder(src, slug), mode_folder(dest, new_slug))
            taken.add(new_slug)
            words = retarget_words(spec, new, dropped, p)
            if dropped:
                report.modes.append(CopiedMode(slug, spec.name, COPY_TO_FIX, new_slug, words))
            else:
                save(dest, new_slug, new)
                report.modes.append(CopiedMode(slug, spec.name, COPY_CARRIED, new_slug, words))
        elif slug in codes:
            try:
                name = CM.load(src, slug).name
            except (OSError, ValueError):
                name = slug.upper()
            if _replaces(replace, slug) and slug in CM.code_slugs(dest):
                new_slug = slug
                shutil.rmtree(mode_folder(dest, slug))
            else:
                new_slug = _free_slug(dest, slug, taken)
            shutil.copytree(mode_folder(src, slug), mode_folder(dest, new_slug))
            if new_slug != slug:
                # a code mode is modes/<slug>/<slug>.c: the file follows its folder's new name
                os.replace(os.path.join(mode_folder(dest, new_slug), slug + ".c"),
                           os.path.join(mode_folder(dest, new_slug), new_slug + ".c"))
                from . import block_modes as BM   # PAD-232: a blocks mode's C names its folder
                try:
                    BM.regenerate(dest, new_slug)
                except (OSError, ValueError):
                    pass                            # its old C, renamed, still builds
            taken.add(new_slug)
            report.modes.append(CopiedMode(slug, name, COPY_CODE, new_slug,
                                           "a build says if %s lacks a shot it names" % p.label))
        elif slug in why_broken:
            report.modes.append(CopiedMode(slug, slug, COPY_SKIPPED,
                                           words="its mode file does not load: %s" % why_broken[slug]))
        else:
            report.modes.append(CopiedMode(slug, slug, COPY_SKIPPED,
                                           words="no mode called %s in %s" % (slug, src)))
    return report


def _replaces(replace, slug):
    return replace is True or (not isinstance(replace, bool) and slug in (replace or ()))


def _keep_their_model(spec, over, p):
    """PAD-396: ``spec``, about to be put over ``over`` (the mode of its name already in a project of
    title ``p``), carrying ``over``'s shots and mechanisms as its version for ``p`` when they are the
    person's own: changed since the last port made them, or never a port's. A port's, unchanged, is
    made again from ``spec``."""
    if not other_model(spec.title, p) or model_of_key(over.title) != model_of_key(p.key):
        return spec
    theirs = _model_fields(over)
    if over.ported and theirs == over.ported:
        return spec
    out = ModeSpec.from_json(json.loads(json.dumps(spec.to_json())))
    out.models = dict(out.models) if isinstance(out.models, dict) else {}
    out.models[model_of_key(p.key)] = theirs
    return out


def port_modes(src, dest, slugs=None):
    """One click from a card's project to its game's other model (PAD-396, "port to Pro"): every mode of
    ``src`` into ``dest`` as :func:`copy_modes` copies them, but a mode already in ``dest`` under its
    folder name is REPLACED - the port made before - keeping the shots and mechanisms set for ``dest``'s
    model there. So porting again after an edit carries the edit, and the other model's choices stay."""
    return copy_modes(src, dest, slugs, replace=True)


def port_replaces(src, dest):
    """The names of ``src``'s modes :func:`port_modes` would put over modes already in ``dest``."""
    from . import code_modes as CM
    there = {s for s, _ in list_modes(dest)[0]}
    codes_there = set(CM.code_slugs(dest))
    return ([sp.name for s, sp in list_modes(src)[0] if s in there]
            + [s.upper() for s in CM.code_slugs(src) if s in codes_there])


def port_targets(project, folders):
    """``[(folder, words, model)]``: of ``folders`` (the app's known projects), those whose card is this
    project's game on ANOTHER model, with words like ``Godzilla Pro 1.16 (GZ Pro)`` and the model's word
    (``Pro``, :func:`model_word`). Reads only the
    projects' own files; a folder gone or naming no card is left out."""
    try:
        card, p = project_profile(project)
    except Exception:                                   # noqa: BLE001
        return []
    if p is None:
        return []
    out, seen = [], {_norm_path(project)}
    for folder in folders or ():
        key = _norm_path(folder)
        if not folder or key in seen or not os.path.isdir(folder):
            continue
        seen.add(key)
        try:
            _c, q = project_profile(folder)
        except Exception:                               # noqa: BLE001
            continue
        if q is not None and other_model(p.key, q):
            out.append((folder, "%s (%s)" % (q.label, os.path.basename(os.path.normpath(folder))),
                        model_word(q.key)))
    return out


# ---- a file of modes to share or keep (PAD-281) --------------------------------------
SHARE_MANIFEST = "pad_modes.json"
SHARE_KIND = "pad-modes"


def export_modes(project, zip_path, slugs=None):
    """Write modes of ``project`` (``slugs``; None: every form and code mode) to a zip: each
    mode's whole folder (picture, clip and sounds too) under ``modes/<slug>/``. Anyone loads
    it with :func:`import_modes`. Returns the slugs written."""
    import zipfile
    from . import code_modes as CM
    have = [s for s, _ in list_modes(project)[0]] + CM.code_slugs(project)
    want = [s for s in (have if slugs is None else slugs) if s in have]
    if not want:
        raise ModeProjectError("there are no modes to save")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(SHARE_MANIFEST, json.dumps(
            {"format": FORMAT, "kind": SHARE_KIND, "modes": want}, indent=1))
        for slug in want:
            top = mode_folder(project, slug)
            for root, _dirs, files in os.walk(top):
                for name in files:
                    if name.endswith(".tmp"):
                        continue
                    path = os.path.join(root, name)
                    rel = os.path.relpath(path, top).replace(os.sep, "/")
                    z.write(path, "%s/%s/%s" % (MODES_DIRNAME, slug, rel))
    return want


def import_modes(zip_path, project, replace=(), skip=()):
    """Load a file :func:`export_modes` wrote into ``project``: each mode is added beside the
    ones there (a clash of names gets ``_2``) and matched to the project's card the way
    :func:`copy_modes` matches a copy. PAD-402: a mode of a folder name in ``replace`` goes
    over the one of that name there instead, and one in ``skip`` is left out. Returns its
    :class:`CopyReport`, or None when every mode of the file is skipped."""
    import tempfile
    import zipfile
    bad = ModeProjectError("%s is not a file of modes saved by PAD" % os.path.basename(zip_path))
    try:
        z = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile):
        raise bad from None
    with z, tempfile.TemporaryDirectory(prefix="pad-modes-") as tmp:
        try:
            data = json.loads(z.read(SHARE_MANIFEST).decode("utf-8"))
        except (KeyError, ValueError):
            raise bad from None
        if not isinstance(data, dict) or data.get("kind") != SHARE_KIND:
            raise bad
        if data.get("format", FORMAT) > FORMAT:
            raise ModeProjectError("%s was saved by a newer PAD: update to load it"
                                   % os.path.basename(zip_path))
        slugs = [s for s in data.get("modes") or () if isinstance(s, str)
                 and re.match(r"^[A-Za-z0-9_-]+$", s)]
        root = os.path.realpath(modes_dir(tmp))
        for info in z.infolist():
            parts = info.filename.replace("\\", "/").split("/")
            if (info.is_dir() or len(parts) < 3 or parts[0] != MODES_DIRNAME
                    or parts[1] not in slugs or any(p in ("", ".", "..") for p in parts)
                    or ":" in info.filename):
                continue
            dest = os.path.realpath(os.path.join(tmp, *parts))
            if not dest.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        if not slugs:
            raise bad
        slugs = [s for s in slugs if s not in set(skip)]
        if not slugs:
            return None
        return copy_modes(tmp, project, slugs, replace=set(replace))


def share_conflicts(zip_path, project):
    """PAD-402 (DragonRR): what loading a file :func:`export_modes` wrote would do to the modes
    of ``project``. Returns ``(conflicts, same)``: each mode of the file whose folder name is a
    mode here with other contents, ``{"slug", "here", "file", "changed", "saved"}`` (its name
    here and in the file; the time of the newest file of it here, and in the file, as
    ``YYYY-MM-DD HH:MM``), and the folder names of the file's modes already here file for file.
    A file that is not one is ``([], [])``: :func:`import_modes` says why."""
    import time
    import zipfile
    from . import code_modes as CM
    try:
        z = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile):
        return [], []
    conflicts, same = [], []
    with z:
        try:
            data = json.loads(z.read(SHARE_MANIFEST).decode("utf-8"))
        except (KeyError, ValueError):
            return [], []
        if not isinstance(data, dict) or data.get("kind") != SHARE_KIND:
            return [], []
        specs = dict(list_modes(project)[0])
        codes = set(CM.code_slugs(project))
        for slug in data.get("modes") or ():
            if not isinstance(slug, str) or (slug not in specs and slug not in codes):
                continue
            top = "%s/%s/" % (MODES_DIRNAME, slug)
            theirs = {i.filename[len(top):]: i for i in z.infolist()
                      if i.filename.startswith(top) and not i.is_dir()}
            folder = mode_folder(project, slug)
            mine = {}
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    if not name.endswith(".tmp"):
                        path = os.path.join(root, name)
                        mine[os.path.relpath(path, folder).replace(os.sep, "/")] = path
            if set(mine) == set(theirs) and all(
                    _read_bytes(mine[r]) == z.read(theirs[r]) for r in mine):
                same.append(slug)
                continue
            if slug in specs:
                here = specs[slug].name
            else:
                try:
                    here = CM.load(project, slug).name
                except (OSError, ValueError):
                    here = slug.upper()
            try:
                there = json.loads(z.read(top + MODE_FILE).decode("utf-8")).get("name") or here
            except (KeyError, ValueError, AttributeError):
                there = here
            changed = max((os.path.getmtime(p) for p in mine.values()), default=0)
            saved = max((i.date_time for i in theirs.values()), default=None)
            conflicts.append({
                "slug": slug, "here": here, "file": str(there),
                "changed": time.strftime("%Y-%m-%d %H:%M", time.localtime(changed))
                if changed else "",
                "saved": "%04d-%02d-%02d %02d:%02d" % saved[:5] if saved else ""})
    return conflicts, same


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


#: PAD-402: where a load that replaces the user's own edits saves them first, in the project
BACKUP_DIR = "Backups"


def backup_path(project, loading):
    """A new zip path in ``project``'s :data:`BACKUP_DIR` for what is there before the file
    ``loading`` is loaded: ``Before loading <its name> <date time>.zip``."""
    import time
    stem = os.path.splitext(os.path.basename(str(loading)))[0]
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip(" .") or "a file"
    folder = os.path.join(project, BACKUP_DIR)
    os.makedirs(folder, exist_ok=True)
    base = "Before loading %s %s" % (stem, time.strftime("%Y-%m-%d %H.%M.%S"))
    path, n = os.path.join(folder, base + ".zip"), 2
    while os.path.exists(path):
        path, n = os.path.join(folder, "%s (%d).zip" % (base, n)), n + 1
    return path


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
    if int(spec.seconds) < 1 and not (spec.multiball and int(spec.seconds) == 0):
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
    from .mode_assets import layout_problems             # PAD-323
    out += ["The mode's screen cannot be placed: %s." % w for w in layout_problems(spec.screen_layout)]
    out += _validate_own_sounds(spec, folder)
    out += validate_starts(spec)
    out += _validate_film_cut(spec, folder)
    out += validate_parameters(spec, p, folder)
    out += _validate_starts_ends(spec, p)
    out += validate_display_lights(spec)
    out += validate_multiball(spec, p)
    out += validate_ball_save(spec, p)
    out += validate_magnet(spec, p)                    # PAD-381
    out += validate_scoop(spec, p)                     # PAD-381
    out += validate_coils(spec, p)                     # PAD-381
    out += validate_shield(spec, p)                    # PAD-392
    out += validate_shows(spec, p)                     # PAD-418
    out += validate_more_to_start(spec, p)
    out += validate_game_modes(spec, p)
    return out


# ---- PAD-363: the game's own modes while it runs -----------------------------------------
GAME_MODES = ("stack", "give_way", "block")


def held_off(spec, p):
    """The ids of *p*'s modes *spec* keeps from starting: its own list, else the port's checked defaults
    (what pad_mode_runtime.c does with an empty `block_modes`); () unless it blocks."""
    if spec.game_modes != "block":
        return ()
    if spec.block_modes:
        return tuple(sorted({int(i) for i in spec.block_modes if isinstance(i, int)}))
    return tuple(i for i, _name, on in getattr(p, "game_modes", ()) if on)


def validate_game_modes(spec, p):
    if spec.game_modes not in GAME_MODES:
        return ["What it does about the game's own modes is stack, give_way or block."]
    if spec.game_modes != "block":
        return []
    have = {i: name for i, name, _on in getattr(p, "game_modes", ())}
    if not have:
        return []         # the tab says why; the runtime gives way on a port that cannot hold them off
    out = []
    for i in spec.block_modes or ():
        if not isinstance(i, int) or isinstance(i, bool) or i not in have:
            out.append("%s has no mode the app can hold off numbered %r." % (p.label, i))
    if not out and not held_off(spec, p):
        out.append("Tick at least one of %s's modes to hold off." % p.label)
    rules = {name for _n, name in getattr(p, "game_rules", ())}            # PAD-398
    keep = spec.keep_rules if isinstance(spec.keep_rules, list) else None
    if keep is None:
        out.append("The game's features it keeps counting are a list of their names.")
    else:
        for r in keep:
            if r not in rules:
                out.append("%s has no feature called %r to keep counting." % (p.label, r))
    return out


def keep_rule_ids(spec, p):
    """PAD-398: the port's numbers (block_rule_<n>) of the features *spec* keeps counting while it blocks."""
    by = {name: n for n, name in getattr(p, "game_rules", ())}
    keep = spec.keep_rules if isinstance(spec.keep_rules, list) else []
    return sorted({by[r] for r in keep if r in by})


def game_modes_lines(spec, p=None):
    """The mode file's lines: what differs from the runtime's default. PAD-398: that default is "block" (a file
    that says nothing runs alone), so "stack" is written out and "block" is not."""
    if spec.game_modes == "give_way":
        return ["game_modes     give_way"]
    if spec.game_modes != "block":
        return ["game_modes     stack"]
    out = []
    ids = sorted({i for i in spec.block_modes or () if isinstance(i, int) and 0 <= i < 128})
    if ids:
        out.append("block_modes    " + " ".join(str(i) for i in ids))
    keep = keep_rule_ids(spec, p) if p is not None else []
    if keep:
        out.append("keep_rules     " + " ".join(str(n) for n in keep))
    return out


# ---- item 167: a multiball of the mode's own -------------------------------------------
MULTIBALL_BALLS = (2, 6)
BALL_SAVE_MAX = 60
ADD_BALL_MAX = 6


def validate_multiball(spec, p):
    """Every reason the multiball part cannot be built; nothing when the mode is not one."""
    out = []
    if not spec.multiball:
        return out
    if not p.can("multiball"):
        out.append("A multiball of the mode's own is not on %s yet (Mode says why)." % p.label)
    balls = _int_or_none(spec.balls)
    if balls is None or not MULTIBALL_BALLS[0] <= balls <= MULTIBALL_BALLS[1]:
        out.append("A multiball puts %d to %d balls in play." % MULTIBALL_BALLS)
    save = _int_or_none(spec.ball_save)
    if save is None or not 0 <= save <= BALL_SAVE_MAX:
        out.append("The multiball's ball save is 0 to %d seconds." % BALL_SAVE_MAX)
    if spec.add_ball_shot:
        if spec.add_ball_shot not in dict(p.shots):
            out.append("%s has no shot called %r to add a ball." % (p.label, spec.add_ball_shot))
        n = _int_or_none(spec.add_ball_max)
        if n is None or not 1 <= n <= ADD_BALL_MAX:
            out.append("A shot adds a ball 1 to %d times a multiball." % ADD_BALL_MAX)
    if spec.multiball_on_shot:                                       # PAD-228
        if spec.multiball_on_shot not in dict(p.shots):
            out.append("%s has no shot called %r to start the multiball on." % (p.label, spec.multiball_on_shot))
        if not _int_or_none(spec.seconds):
            out.append("A multiball that starts on a shot needs Runs for: its seconds are the time to hit the shot.")
    return out


def multiball_lines(spec, p):
    """The runtime lines of the multiball part: nothing unless the mode is one and the title can."""
    if not spec.multiball or not p.can("multiball"):
        return []
    lines = ["multiball      %d %d" % (int(spec.balls), int(spec.ball_save))]
    if spec.add_ball_shot:
        lines.append("add_ball       0x%08x %d" % (p.mask([spec.add_ball_shot]), int(spec.add_ball_max)))
    if spec.multiball_on_shot:                                       # PAD-228
        lines.append("multiball_on   0x%08x" % p.mask([spec.multiball_on_shot]))
    return lines


# ---- PAD-225: a ball save when the mode starts -----------------------------------------
def validate_ball_save(spec, p):
    """Every reason the ball save cannot be built; nothing when the mode has none (or is a multiball,
    which has its own)."""
    save = _int_or_none(spec.start_ball_save)
    if spec.multiball or save == 0:
        return []
    out = []
    if save is None or not 1 <= save <= BALL_SAVE_MAX:
        out.append("The ball save when the mode starts is 1 to %d seconds." % BALL_SAVE_MAX)
    if not p.can("ball_save"):
        out.append("A ball save of the mode's own is not on %s yet (Mode says why)." % p.label)
    return out


def ball_save_lines(spec, p):
    """The runtime line of the ball save: nothing without one, for a multiball, or where the title cannot."""
    if spec.multiball or not p.can("ball_save") or not _int_or_none(spec.start_ball_save):
        return []
    return ["ball_save      %d" % int(spec.start_ball_save)]


# ---- PAD-381: holding the ball on the magnet --------------------------------------------
def validate_magnet(spec, p):
    """Every reason the magnet part cannot be built; nothing when the mode has none."""
    ms = _int_or_none(spec.magnet_ms)
    if ms == 0:
        return []
    out = []
    if ms is None or not MAGNET_MIN_MS <= ms <= MAGNET_MAX_MS:
        out.append("The magnet holds the ball %g to %g seconds." % (MAGNET_MIN_MS / 1000, MAGNET_MAX_MS / 1000))
    if not p.can("magnet"):
        out.append("Holding the ball on the magnet is not on %s yet (Mode says why)." % p.label)
    return out


def magnet_lines(spec, p):
    """The runtime line of the magnet: nothing without one or where the title cannot. The shot is written
    out (the profile's magnet_shot), so the line does not lean on the port at run time."""
    ms = _int_or_none(spec.magnet_ms)
    if not ms or not p.can("magnet") or not p.magnet_shot:
        return []
    return ["magnet         %d 0x%08x" % (ms, p.mask([p.magnet_shot]))]


# ---- PAD-381: holding a ball in the scoop ---------------------------------------------
def validate_scoop(spec, p):
    """Every reason the scoop part cannot be built; nothing when the mode has none."""
    ms = _int_or_none(spec.scoop_hold_ms)
    if ms == 0:
        return []
    out = []
    if ms is None or not SCOOP_MIN_MS <= ms <= SCOOP_MAX_MS:
        out.append("The scoop holds a ball %g to %g seconds." % (SCOOP_MIN_MS / 1000, SCOOP_MAX_MS / 1000))
    if not p.can("scoop"):
        out.append("Holding a ball in the scoop is not on %s yet (Mode says why)." % p.label)
    return out


def scoop_lines(spec, p):
    """The runtime line of the scoop hold: nothing without one or where the title cannot."""
    ms = _int_or_none(spec.scoop_hold_ms)
    if not ms or not p.can("scoop"):
        return []
    return ["scoop_hold     %d" % ms]


# ---- PAD-381: other mechanisms held like the magnet ---------------------------------------
def validate_coils(spec, p):
    """Every reason the mechanisms part cannot be built; nothing when the mode holds none."""
    out = []
    held = dict(p.held_coils)
    shots = dict(p.shots)
    for row in spec.coil_holds or ():
        name, ms, shot = (list(row) + ["", 0, ""])[:3]
        label = held.get(name, name)
        if name not in held:
            out.append("%s has no mechanism called %r a mode can hold." % (p.label, name))
            continue
        n = _int_or_none(ms)
        top = min(COIL_MAX_MS, dict(getattr(p, "coil_caps", ()) or ()).get(name, COIL_MAX_MS))   # PAD-420: the game's own
        if n is None or not COIL_MIN_MS <= n <= top:
            out.append("The %s holds %g to %g seconds." % (label, COIL_MIN_MS / 1000, top / 1000))
        if shot and shot not in shots:
            out.append("%s has no shot called %r to hold the %s on." % (p.label, shot, label))
    if spec.coil_holds and not p.can("coils"):
        out.append("Holding the game's other mechanisms is not on %s yet (Mode says why)." % p.label)
    return out


def coil_lines(spec, p):
    """The runtime lines of the held mechanisms: ``coil_hold <name> <ms> [mask]``."""
    if not p.can("coils"):
        return []
    held, out = dict(p.held_coils), []
    for row in spec.coil_holds or ():
        name, ms, shot = (list(row) + ["", 0, ""])[:3]
        if name in held and _int_or_none(ms):
            out.append("coil_hold      %s %d%s" % (name, int(ms), " 0x%08x" % p.mask([shot]) if shot else ""))
    return out


# ---- PAD-392: the shield targets toward the player -----------------------------------------
def validate_shield(spec, p):
    """Every reason the shield part cannot be built; nothing when the mode leaves the platform alone. The
    platform stays turned only while the game's own shield feature sees no shots: the game's modes cannot
    start (``game_modes`` block) and that feature is not kept counting - else the game turns it back about 2 s
    after every move (emulator, PAD-392)."""
    if spec.shield is not True:
        return [] if spec.shield in (False, None) else ["The shield is on or off (true or false)."]
    if not p.can("shield"):
        return ["Turning the shield targets is not on %s yet (Mode says why)." % p.label]
    feature = p.shield_rule or "shield"
    if (spec.game_modes or "block") != "block":
        return ["The shield targets stay toward the player only while the game's modes cannot start: otherwise "
                "the game's own %s feature turns them back." % feature]
    if p.shield_rule and p.shield_rule in (spec.keep_rules or []):
        return ["The shield targets stay toward the player only while %s does not keep counting: it turns them "
                "back." % p.shield_rule]
    return []


def shield_lines(spec, p):
    """The runtime line of the shield: nothing unless it turns the platform, and only where the title can."""
    return ["shield         toward"] if spec.shield is True and p.can("shield") else []


# ---- PAD-418: the game's own light shows at the start and the end ---------------------------
def validate_shows(spec, p):
    """Every reason the light-show part cannot be built; nothing when the mode plays none."""
    out = []
    have = {name for name, _k, _s in getattr(p, "game_shows", ())}
    for f, when in (("show_start", "start"), ("show_end", "end")):
        v = getattr(spec, f)
        if v in ("", None):
            continue
        if not isinstance(v, str):
            out.append("The light show at its %s is a show's name." % when)
        elif not p.can("shows"):
            out.append("A light show of the game's is not on %s (Lights says why)." % p.label)
        elif v not in have:
            out.append("%s has no light show called %r to play at the mode's %s." % (p.label, v, when))
    return out


def show_lines(spec, p):
    """The runtime lines of the light shows: nothing unless the mode plays one, and only where the title can."""
    if not p.can("shows"):
        return []
    have = {name for name, _k, _s in p.game_shows}
    return ["%-14s %s" % (f, getattr(spec, f)) for f in ("show_start", "show_end") if getattr(spec, f) in have]


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


def starts_on_sequence(spec):
    """True when the mode starts on its ``start_sequence`` made in order (PAD-314)."""
    words = (spec.starts_on or "shot").split()
    return bool(words) and words[0] == "sequence"


def playfield_shots(p):
    """The title's shot names that are shots on the playfield: the cabinet buttons the port's
    `switch` lines add (``switch_shots``) are left out."""
    buttons = set(getattr(p, "switch_shots", ()) or ())
    return [n for n, _m in p.shots if n not in buttons]


def other_shots(spec, p):
    """The shots :data:`END_SHOT_OTHERS` means on title ``p``: every playfield shot that is not
    one of the mode's own - the shots that score and, in a multiball, the shot that adds a ball
    and the one the balls come on. The shots that start it are not its own: once it runs they are
    shots like any other."""
    own = set(spec.scoring_shots if isinstance(spec.scoring_shots, list) else ())
    if spec.multiball:
        own |= {spec.add_ball_shot, spec.multiball_on_shot}
    return [n for n in playfield_shots(p) if n not in own]


def end_shot_list(spec):
    """The shot names ``spec.end_shot`` picks: ``[]`` for none (or for :data:`END_SHOT_OTHERS`,
    which names no shot), a single name as a list of one, a list as it is (PAD-314)."""
    v = spec.end_shot
    if isinstance(v, list):
        return list(v)
    return [v] if isinstance(v, str) and v and v != END_SHOT_OTHERS else []


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
    if words[0] not in ("shot", "event", "sequence"):
        out.append("A mode starts on a shot, on shots made in order, or on one of the game's events.")
    elif words[0] == "sequence":                    # PAD-314
        seq = spec.start_sequence
        names = dict(p.shots)
        if not isinstance(seq, list) or not all(isinstance(s, str) for s in seq):
            out.append("The shots that start the mode in order are a list of shot names.")
        elif len(seq) < SEQUENCE_MIN:
            out.append("Pick at least two shots, in order, that start the mode.")
        elif len(seq) > SEQUENCE_MAX:
            out.append("A mode starts on at most %d shots in order." % SEQUENCE_MAX)
        else:
            for s in seq:
                if s not in names:
                    out.append("%s has no shot called %r in the shots that start it." % (p.label, s))
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
    lines += multiball_lines(spec, p)       # item 167: nothing unless the mode is a multiball
    lines += ball_save_lines(spec, p)       # PAD-225: nothing unless it has a ball save (and no multiball)
    lines += magnet_lines(spec, p)          # PAD-381: nothing unless it holds the ball on the magnet
    lines += scoop_lines(spec, p)           # PAD-381: nothing unless it holds a ball in the scoop
    lines += coil_lines(spec, p)            # PAD-381: the other mechanisms it holds
    lines += shield_lines(spec, p)          # PAD-392: the shield targets toward the player while it runs
    lines += show_lines(spec, p)            # PAD-418: the game's own light shows at its start and end
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
    lines += game_modes_lines(spec, p)       # PAD-363 / PAD-398
    lines += parameter_lines(spec, slug, p)
    lines += display_light_lines(spec)
    lines += more_to_start_lines(spec, p)    # PAD-227: nothing unless the mode has them
    lines = _starts_ends_lines(spec, lines, p)
    return "\n".join(lines) + "\n"


# ---- PAD-227: more than one thing to meet before it starts ---------------------------------
#: ``start_also`` rows mode_file.c takes (its ALSO_MAX)
START_ALSO_MAX = 3
AFTER_WHEN = ("ball", "game")


def _also_rows(spec):
    """``spec.start_also`` as ``[(shot, count)]``; None when it is not a list of pairs."""
    rows = spec.start_also
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            return None
        out.append((row[0], row[1]))
    return out


def validate_more_to_start(spec, p):
    """The reasons ``start_also`` / ``after`` cannot be built, as sentences."""
    out = []
    names = dict(p.shots)
    rows = _also_rows(spec)
    if rows is None or len(rows) > START_ALSO_MAX:
        out.append("A mode can also wait for up to %d other shots." % START_ALSO_MAX)
        rows = []
    for shot, count in rows:
        if shot not in names:
            out.append("%s has no shot called %r." % (p.label, shot))
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
            out.append("Each other shot it waits for is hit 1 to 20 times.")
    after = spec.after if isinstance(spec.after, str) else None
    if after is None:
        out.append("The mode it starts after is a mode's name.")
    elif after.strip():
        if after.strip() == spec.name.strip():
            out.append("A mode cannot wait for itself to run first.")
        if spec.after_when not in AFTER_WHEN:
            out.append("The mode it starts after has run this ball or this game.")
    return out


def more_to_start_lines(spec, p):
    """The ``trigger_also`` and ``after`` lines (nothing at the defaults, so every file made
    before PAD-227 stays byte-identical)."""
    lines = ["%-14s 0x%08x %d" % ("trigger_also", p.mask([shot]), int(count))
             for shot, count in _also_rows(spec) or ()]
    if isinstance(spec.after, str) and spec.after.strip():
        lines.append("%-14s %s %s" % ("after", spec.after_when, spec.after.strip()))
    return lines


def after_problems(modes):
    """``{slug: [sentence]}`` for each of ``modes`` (``[(slug, ModeSpec)]``, one project's)
    whose ``after`` names no mode of the project: on the card it would never start."""
    have = {spec.name.strip() for _slug, spec in modes}
    out = {}
    for slug, spec in modes:
        after = spec.after.strip() if isinstance(spec.after, str) else ""
        if after and after not in have:
            out[slug] = ["%s starts only after %s, and no mode is called that." % (spec.name.strip(), after)]
    return out


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
        out.append("The display priority is 0 (none) to 255.")
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
            if n is None or n == 0:                  # PAD-314: a minus number is a penalty
                out.append("%s's own points must be a whole number, not 0 (a minus number takes points away)." % shot)
            elif n < 0 and shot in spec.scoring_shots:
                out.append("%s scores, so it cannot take points away too: untick it under Shots that score." % shot)
            elif getattr(p, "score_bits", 64) == 32 and abs(n) > SCORE32_AWARD_MAX:
                out.append("%s's own points can be at most %s: %s keeps its scores in 32 bits."
                           % (shot, format(SCORE32_AWARD_MAX, ","), p.label))
    if spec.end_shot == END_SHOT_OTHERS:             # PAD-314
        if not other_shots(spec, p):
            out.append("Every shot scores, so no shot is left to end the mode.")
    elif isinstance(spec.end_shot, list):            # PAD-314: any of these shots
        if not all(isinstance(s, str) for s in spec.end_shot):
            out.append("The shots that end the mode are a list of shot names.")
        elif not spec.end_shot:
            out.append("Tick a shot that ends the mode, or pick (no shot).")
        else:
            for s in spec.end_shot:
                if s not in names:
                    out.append("%s has no shot called %r to end the mode." % (p.label, s))
    elif spec.end_shot and (not isinstance(spec.end_shot, str) or spec.end_shot not in names):
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
        n = _int_or_none(points)
        if n < 0:                                    # PAD-314: a minus number takes points away
            lines.append("shot_penalty   0x%08x %d" % (p.mask([shot]), -n))
        else:
            lines.append("shot_award     0x%08x %d" % (p.mask([shot]), n))
    if spec.end_shot == END_SHOT_OTHERS:      # PAD-314: one mask of every shot that is not the mode's own
        lines.append("end_shot       0x%08x" % p.mask(other_shots(spec, p)))
    elif end_shot_list(spec):                 # one shot, or (PAD-314) any of a list: one mask
        lines.append("end_shot       0x%08x" % p.mask(end_shot_list(spec)))
    if spec.clip_both and spec.clip != "none" and p.can("clip"):   # item 148 (j): no clip, no second
        other = "clip_end" if spec.clip_when == "start" else "clip_start"
        name = names["clip"] if spec.clip_both.get("clip") == "same" else second_clip_name(slug)
        lines.append("%-14s %s" % (other, name))
    for secs, cid in spec.callout_at:
        lines.append("callout_at     %d %d" % (_int_or_none(secs), _int_or_none(cid)))
    return lines


def _starts_ends_lines(spec, lines, p):
    """Item 147: an event start REPLACES the trigger line (so a mode.so older than events
    logs the file NOT VALID rather than starting it on a shot); a start on a shot and an
    end on the drain write exactly what they wrote before. PAD-314: a start on shots in
    order replaces it the same way, with one ``trigger_seq`` line per shot and, when any
    other shot starts the sequence over, a ``trigger_seq_reset`` of every playfield shot
    not in it."""
    event = starts_on_event(spec)
    out = list(lines)
    if event:
        out = [line for line in out if not line.startswith("trigger ")]
        out.insert(2, "starts_on      event %s" % event)
    elif starts_on_sequence(spec):
        out = [line for line in out if not line.startswith("trigger ")]
        seq = ["%-14s 0x%08x" % ("trigger_seq", p.mask([s])) for s in spec.start_sequence]
        if spec.sequence_reset_any:
            others = [n for n in playfield_shots(p) if n not in spec.start_sequence]
            if others:
                seq.append("%-14s 0x%08x" % ("trigger_seq_reset", p.mask(others)))
        out[2:2] = ["starts_on      sequence"] + seq
    kind, name = ends_on_parts(spec)
    if kind == "clock":
        out.append("ends_on        clock")
    elif kind == "event" and name:
        out.append("ends_on        event %s" % name)
    return out
