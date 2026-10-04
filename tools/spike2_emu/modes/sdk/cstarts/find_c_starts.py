"""PAD-363: the START of each of the game's own (non-multiball) modes on the titles where the C++ start slot does not
apply, read off the game program. Static; read-only on everything but its output folder.

    python find_c_starts.py [key ...]          (default: every title below)
    -> cstarts/json/<key>.json (the game programs: PAD_GAME_PROGRAMS/<key>.elf)

A start is the entry of the function that BEGINS one mode, entered only to start it; the runtime's veto moves its first
two words into a trampoline, so only starts whose two words are movable (game_mode_blocks.movable) are listed.

Two readers:

* plain C (and hand-rolled C++ without the framework's rule manager): the AUDIT WITNESS. Every mode has an
  AUD_<MODE>_STARTED / _STARTS / _START audit; the function that counts it (audit_add(id, 1) with the id made as a
  constant anywhere in the function - the tracker sees a movw made far ahead of the call) is the mode's start
  candidate. Its TRUE entry is found (a movw is often scheduled before the push), then the generic rules:
      multiball   it reaches the framework's multiball_serve (absolute: 2+ balls or unknown) or a relative add-balls
                  wrapper (1+ or unknown) within three calls (created process bodies count) -> rejected;
      movable     both entry words must move into the trampoline; a `bl` as word 2 is reported separately (the most
                  common reason, and one a trampoline that relocated a bl would lift);
      shared      it counts another mode's STARTED audit too -> one start for both (named for both) or rejected;
      reachable   something refers to it (a bl, a tail branch, a code or a data word) - a start nothing reaches is
                  dead code in this build;
      return      a caller that tests the result is a contract the veto (r0 = 1, "started") may break: medium.
  Per-title knowledge the generic rules can't see (a dispatcher that treats 1 as started and carries on, a better
  name, a start from another witness) is in HAND below, each with the evidence.
* C++ (cmode / crule) titles whose scanner found no start slot (Jurassic Park LE, Rush): the START SLOT is the slot
  of cmode's own start in cmode's (or cmode_null's) vtable - the one function that sets a per-player byte to 1 (the
  running byte) and increments a per-player word (the starts count); `add rX, rX, #1` first, then (John Wick, Sword
  of Rage) a count bumped through another register, lowest slot. It agrees with the scanner on all 22 C++ programs
  that have a slot (Godzilla 8, Deadpool 13, Venom 47, TMNT 39, Munsters 33, Mandalorian 38, Jaws 12, King Kong 11,
  Avengers 11, John Wick 47, Sword of Rage 31, Iron Maiden 8, Star Wars 8, D&D 50, Foo Fighters 41, Led Zeppelin
  33) and gives Jurassic Park LE 21, Rush 40. The mode objects
  come from the scanner's static-initialiser walk, or, where the ids are a descriptor filled at run time (Jurassic
  Park LE), from the constructor of the mode table the port names (`data stock_mode_table`).
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cstart_lib import (S, Title, audit_functions, ball_evidence, fmt_refs, hx, is_multiball_name,  # noqa: E402
                        movable, port_int, return_used, serves_balls, track_entry)
from pinball_decryptor.plugins.stern import stock_scan_cpp as C  # noqa: E402

C_TITLES = ["aerosmith_le-1.15", "batman-1.13", "beatles-1.29", "elvira3-1.13", "guardians_le-1.14",
            "james_bond_60th_le-1.11", "james_bond_le-1.06", "jurassic_park_the_pin-1.05", "metallica_spike-1.03",
            "metallica_spike-1.04", "star_wars_elg-1.10", "stranger_things_le-1.12", "uncanny_xmen_le-0.98"]
CPP_TITLES = ["jurassic_park_le-1.16", "rush_le-1.18"]

def _merge(*ds):
    out = {}
    for d in ds:
        out.update(d)
    return out


# ---- hand-confirmed knowledge, per title ------------------------------------------------------------------------
# "names": readable names for starts the audit witness finds (default: the audit name in words).
# "medium": starts kept at medium confidence, with why (a dispatcher carries on after the call, a table dispatch
#           not located statically, a second path of one mode).
# "reject": starts the generic rules would keep, with why.
# "extra":  starts from another witness (listed in full: name, start, how, confidence).
# "rejected": modes with no usable start that the audit witness can't show (index-driven chapters...), with why
#           and, where the start is known, its address (usable later if the runtime changes).
HAND = {
    "aerosmith_le-1.15": {
        "names": {0xfac8c: "Super Scoring", 0x3b3d4: "Double Scoring", 0x1310f0: "Upper Playfield Orbit Rule"},
        "medium": {0xfac8c: "also reached by a tail branch from 0xfadf0, whose caller gets the result"},
        "notes": "Live-records title: every timed mode's start asks live_records(lo, hi) at its entry and creates its own "
                 "records; the three kept starts each count their STARTED audit and create their records. The song "
                 "modes are multiballs (Toys in the Attic, Love in an Elevator, Medley: they serve balls).",
    },
    "guardians_le-1.14": {
        "names": {0x103f4c: "Super Scoring", 0x662e8: "Headphone Hurryup", 0x3d028: "Double Scoring",
                  0x3d490: "Double Scoring (2nd path)"},
        "medium": {0x103f4c: "also reached by a tail branch from 0x1040a8, whose caller gets the result",
                   0x3d490: "a second start of Double Scoring (callers 0xde05c): block both ids to keep it off"},
        "notes": "Same framework as Aerosmith (live records). The audit descriptor table is the SECOND {table, 271, 16} "
                 "record (0x57b9c8); stock_scan_c.audit_ids takes the first, whose +0x0a halfwords are not ids, so "
                 "its audit_add search finds nothing on this build.",
    },
    "batman-1.13": {
        "names": {0x4d7f0: "Catwoman (episodes 19-20)", 0x733f0: "Catwoman (episode 108)",
                  0xb0040: "Joker (episodes 5-6)", 0xbf370: "Joker (episode 104)",
                  0x156924: "Penguin (episodes 3-4)", 0x169cd8: "Penguin (episode 95)",
                  0x188954: "Riddler (episodes 1-2)", 0x196d40: "Riddler (episode 96)",
                  0x41184: "Bookworm (episodes 29-30)", 0x9558c: "Egghead (episodes 47-48)",
                  0x84f40: "Egghead (episodes 102-103)", 0x8d0c4: "Egghead (episode 109)",
                  0xdae3c: "King Tut (episodes 27-28)", 0xe3078: "King Tut (episodes 41-42)",
                  0xeb148: "King Tut (episodes 87-88)", 0xf38f8: "King Tut (episode 100)",
                  0xfb0b4: "King Tut (episode 117)", 0x10720c: "Mad Hatter (episodes 13-14)",
                  0x10f38c: "Mad Hatter (episodes 69-70)", 0x148d3c: "Mr. Freeze (episodes 53-54)",
                  0x2e38c: "Batphone Hurry-Up"},
        "medium": _merge({f: "a major villain's episode start, called through the villain's episode table (Catwoman: "
                           "0x58184c, 0x78 per episode, start at +0x30) by the villain's start wrapper (Catwoman "
                           "0x7fec8), which on a non-zero result marks the episode played and counts it: a refused "
                           "episode counts as played for that player"
                        for f in (0x4d7f0, 0x733f0, 0xb0040, 0xbf370, 0x156924, 0x169cd8, 0x188954, 0x196d40)},
                       {f: "a minor villain's episode start from the episode table at 0x59e44c (0x60 per episode, "
                             "start at +0); the dispatch site was not located statically, so how a non-zero result "
                             "is used is unchecked"
                          for f in (0x41184, 0x9558c, 0x84f40, 0x8d0c4, 0xdae3c, 0xe3078, 0xeb148, 0xf38f8, 0xfb0b4,
                                    0x10720c, 0x10f38c, 0x148d3c)},
                       {0x2e38c: "takes the hurry-up kind in r0 (0..3); its four bl callers count a hurry-up on a "
                                   "non-zero result (bookkeeping only)"}),
        "notes": "Episodes: each villain's episode starts sit in per-villain tables of function pointers (major "
                 "villains) or one episode table (minor villains); each start counts its episode's STARTS audit, "
                 "sets the villain's flag (major: flags 46-55) and creates its records. Catwoman 83-84 (0x5f980) and "
                 "Joker 118 (0xcb2d8) are compiled in but nothing refers to them (not in the episode tables): not "
                 "reachable on 1.13.",
    },
    "beatles-1.29": {
        "rejected": [
            {"name": "All My Loving", "start": 0x4b220, "covers": "ALL_MY_LOVING", "why": "return-checked: the song select 0x3ddc4 calls the song "
             "descriptor's start (table 0x4b60e0, 0x38 per song, start at +0xc) and on a non-zero result marks the "
             "song played, starts the song's display effect and counts it - a refused start (r0 = 1) leaves the "
             "song half-started. It also serves balls (a ball-added song). Usable only by a veto that returns 0"},
            {"name": "Drive My Car", "start": 0x4da44, "covers": "DRIVE_MY_CAR", "why": "return-checked (see All My Loving): usable only by a "
             "veto that returns 0 (the song select aborts cleanly on 0)"},
            {"name": "Should Have Known Better", "start": 0x50558, "covers": "SHOULD_HAVE", "why": "return-checked (see All My Loving): usable "
             "only by a veto that returns 0"},
            {"name": "Ticket to Ride", "start": 0x52cdc, "covers": "TICKET_TO_RIDE", "why": "return-checked (see All My Loving): usable only by a "
             "veto that returns 0"},
            {"name": "It Won't Be Long", "start": 0x5567c, "covers": "IT_WONT_BE_LONG", "why": "return-checked (see All My Loving): usable only by "
             "a veto that returns 0"},
        ],
        "notes": "The five song modes' STARTED audits are counted from the song descriptor, never as a constant; the "
                 "descriptor table (0x4b60e0, 0x38 bytes per song, the STARTED audit id as a u16 at +0x10) was found "
                 "from that id sequence (213, 217, 221, ...). Each song's start is the descriptor's +0xc function, "
                 "called by the song select 0x3ddc4 (and 0x3d8e8) through the descriptor and its result checked.",
    },
    "elvira3-1.13": {
        "names": {0xdd12c: "Houses (whichever House is selected)"},
        "medium": {0xdd12c: "the House manager's start: one start for every House (it finds the selected house, "
                            "calls its start and on success marks it played and counts AUD_HOUSE_STARTS), so a veto "
                            "here keeps every House off and marks none played; two callers (0x4a114, 0x4b8e8: the "
                            "scoop's action chain) take a non-zero result as 'a House started' (action 7)"},
        "rejected": [
            {"name": "Houses (15 House rules)", "covers": "^AUD_(ABOB|AOTGL|EEGAH|MTHOF|NOTLD|SCCTM|TBTWD|TFOS|TGGM|TKS|TM|TSROD|TWOW|TWW|THEY_CAME_FROM_SPACE)_STARTS$", "why": "return-checked: the House manager's start 0xdd12c finds the "
             "house in its map and calls the house's start (the House object's secondary-vtable slot 22, a thunk "
             "`sub r0, r0, #4; b <start>`: ABOB 0x33558, NOTLD 0x1064cc, ...) and on a non-zero result marks the "
             "house played, counts AUD_HOUSE_STARTS and calls the manager's v[14] - a refused start (r0 = 1) leaves the "
             "house marked played without running. Usable only by a veto that returns 0 (the manager aborts on 0)"},
            {"name": "Transient rules (Dance Fever, Make Out Mayhem, Run for Your Life, Scream Test, They Came from "
             "Space) and the other modes", "covers": "_STARTS$", "why": "not located: their STARTS audits are counted from rule data, never "
             "as a constant, and the rules walk 0xf489c starts them through C++ virtuals of hand-rolled rule classes "
             "(FreakFryerRule / TransientRule) whose start slot was not established in this pass"},
        ],
        "notes": "Elvira 3 runs its modes as C++ rule objects (House rules under a House manager, TransientRules in a "
                 "vector) without the cmode framework; the audit witness finds only AUD_HOUSE_STARTS (in the "
                 "manager) and the Junk Ray Gun multiballs.",
    },
    "james_bond_60th_le-1.11": {
        "extra": [
            {"name": "Villain Mode", "start": 0x9bb10, "obj": 0x5f20e0,
             "how": "VillainMode::start (the port's start, on the VillainMode object 0x5f20e0): bumps the villain level "
                    "(+0x34 = [+0x38] + 1), counts the player's villain modes, calls 0x11d83c(0x83, 0x9c774, 0) (the create-a-"
                    "process shape: id, body, 0) and starts game timer 2, whose records 137..138 are the port's mode_records_1; "
                    "only caller 0xa16b4 in the VillainMode shot handler 0xa0918 (result unused)",
             "confidence": "medium",
             "why_medium": "one witness (the port's records) and one call site; no STARTED audit on this title"},
        ],
        "notes": "No mode STARTED audits besides the multiball families (Villain / Bond / Gadget / Mission / 007 "
                 "multiballs, all serve balls). The one non-multiball mode the port names is the Villain Mode.",
    },
    "james_bond_le-1.06": {
        "names": {0x1c7df0: "Upside Down Hurry-Up", 0x1c9f60: "Upside Down 2 Hurry-Up", 0x5be50: "Bullshit Scoring",
                  0xb1b90: "Geiger Counter", 0x33cb8: "Attache Case", 0x2a860: "Aston Martin",
                  0x1c2818: "Under Water Powerpack", 0xffbb8: "Little Nellie", 0x1b2638: "Tarantula Hurry-Up",
                  0xf2ef0: "Knife Shoe Hurry-Up", 0x145340: "Oddjob Hat Hurry-Up", 0x18c4dc: "Shark Hurry-Up",
                  0x496d8: "Bird One Hurry-Up", 0x47ff4: "Bath-O-Sub Hurry-Up", 0x8cb88: "Double Scoring",
                  0x20530: "Ahoy Mr Bond Wizard Mode"},
        "medium": _merge({f: "a gadget mode's start from the gadget table 0x62f168 (0x34 per gadget, start at +4), "
                           "called by the next-gadget start 0x15f928 (result unused), which then clears flag 28, "
                           "moves the gadget's bit into the player's done mask and carries on: a refused gadget "
                           "counts as played"
                        for f in (0xb1b90, 0x33cb8, 0x2a860, 0x1c2818, 0xffbb8)},
                       {f: "a hurry-up's start from the hurry-up table 0x63d2e0 (0x34 per entry, start at +0); "
                             "the dispatch site was not located statically"
                          for f in (0x1b2638, 0xf2ef0, 0x145340, 0x18c4dc, 0x496d8, 0x47ff4)},
                       {0x5be50: "reached only by a tail branch from 0x5bfac, whose caller gets the result",
                          0x20530: "a wizard mode: it calls multiball_serve with 1 (serve until ONE ball is in "
                                   "play, i.e. no new ball), so it is kept as a mode; check on a machine",
                          0x1c7df0: "called through the pair table 0x63f8e0 by 0x1c6b80",
                          0x1c9f60: "called through the pair table 0x63f8e0 by 0x1c6b80",
                          0x8cb88: "five callers (award paths of other features); each starts Double Scoring"}),
        "reject": {0x8d4d0: "a second Double Scoring start that also adds a ball (calls the add-balls wrapper "
                            "0x3f5b2c with a computed count)"},
        "rejected": [
            {"name": "Villain / henchman modes (Mystery Villain / Henchman, Dr No's Lair, Orient Express, Oddjob "
             "Battles Bond, Cut Bond in Half, Mr Osato, Professor Dent, Mr Wint & Mr Kidd, Feeding Frenzy, Fiona "
             "Volpe, Under Water Fight, Training Grounds, Diamond Death Ray)",
             "covers": "^AUD_(MYSTERY_VILLAIN_MODE|MYSTERY_HENCHMAN_MODE|DR_NOS_LAIR|ORIENT_EXPRESS|ODDJOB_BATTLES_BOND"
                       "|CUT_BOND_IN_HALF|MR_OSATO|PROFESSOR_DENT|MR_WINT_MR_KIDD|FEEDING_FRENZY|FIONA_VOLPE"
                       "|UNDER_WATER_FIGHT|TRAINING_GROUNDS|DIAMOND_DEATH_RAY)_START",
             "why": "return-checked: the story start 0x136714 (entry not movable: a "
             "literal load) calls the chapter's start from the chapter table 0x62d080 (0x68 per chapter, start at "
             "+0xc) and on a non-zero result carries on (state, music, audits) - a refused chapter start leaves the "
             "story half-started. Usable only by a veto that returns 0"},
        ],
        "notes": "Same framework as Stranger Things (the audit names are shared). Bust Out, What's That and Victory "
                 "Laps start with push + bl and nothing refers to their entries.",
    },
    "jurassic_park_the_pin-1.05": {
        "names": {0x68090: "Restore Power"},
        "medium": {0x68090: "reached only by a tail branch from the Restore Power rule's shot handler (0x71e9c, its "
                            "lit-scoop branch), whose caller gets the result"},
        "notes": "The five dinosaur modes' starts (the port's flag witnesses 39-43) all begin `push; bl 0x93298` (a "
                 "shared can-start check), so they can't be vetoed as they are; their callers are the shared mode "
                 "select 0x93a20 and each dinosaur's completion handler. Escape Nublar serves 4 balls (a wizard "
                 "multiball).",
    },
    "metallica_spike-1.03": "METALLICA",
    "metallica_spike-1.04": "METALLICA",
    "star_wars_elg-1.10": {
        "notes": "The three shot modes (Inner Loop, Orbits, Ramps: the port's flag witnesses 86-88) begin `push; bl "
                 "0x69c04` and are only called by the shared mode select 0x6a100: no usable entry. Boba Fett has no "
                 "counting function; Super Pops / Double Spinner / Super Ramps are awards, not modes.",
    },
    "stranger_things_le-1.12": {
        "names": {0xa6ca8: "It's a Trap", 0xabf64: "Junk Yard", 0x3da74: "Bust Out", 0x1902a0: "What's That",
                  0x187da4: "Upside Down Hurry-Up", 0x18bd88: "Upside Down 2 Hurry-Up", 0x7a8e8: "Double Scoring",
                  0x7a97c: "Double Scoring (lit award)", 0x35274: "Bullshit Scoring", 0x18df7c: "Victory Laps"},
        "medium": {0xa6ca8: "from the award table 0x54ea80 (0x18 per award, start at +4), called by 0x5a5f4 (result "
                            "unused), which then counts the award and clears flags 44 and 23",
                   0xabf64: "from the award table 0x54ea80, called by 0x5a5f4 (result unused); see It's a Trap",
                   0x3da74: "from the mode table 0x54f690 ({id, start, stop}); dispatch site not located statically",
                   0x1902a0: "from the mode table 0x54f690; dispatch site not located statically",
                   0x7a97c: "a second Double Scoring start; its caller 0x7aa48 clears flag 112 on a non-zero result",
                   0x35274: "reached only by tail branches (0x3544c, 0x10965c)"},
        "rejected": [
            {"name": "Story chapters (Where's Barb, Monster Hunting, Bullies, Get Me Out, Operation Mirkwood, Follow "
             "the Compass, Quarter Hunt, Save Will, What Mama Says, Morse Code, Lure Dart, Turn Up the Heat; and the "
             "Mystery Mode start)",
             "covers": "^AUD_(WHERES_BARB|MONSTER_HUNTING|BULLIES|GET_ME_OUT|OPERATION_MIRKWOOD|FOLLOW_THE_COMPASS"
                       "|QUARTER_HUNT|SAVE_WILL|WHAT_MAMA_SAYS|MORSE_CODE|LURE_DART|TURN_UP_THE_HEAT|MYSTERY_MODE)_START",
             "starts": ["0xbe0d8", "0xc2110", "0xc5b54", "0xc8538", "0xced28", "0xd1360", "0xd62f0", "0xe04d4",
                        "0xea388", "0xf2924", "0xe48e8", "0xf9b2c"],
             "why": "return-checked: the story start 0xfe4c4 (entry not movable: a literal load) calls the chapter's "
                    "start from the chapter table 0x5564c8 (100 bytes per chapter, start at +0xc) and on a non-zero "
                    "result carries on (clears flag 23, sets the chapter state, starts its music, counts its STARTED "
                    "audit) - a refused chapter start (r0 = 1) leaves the story half-started. The chapter starts are "
                    "movable: usable by a veto that returns 0 (the story start aborts cleanly on 0)"},
            {"name": "Demogorgon Challenge", "start": 0x5ef8c, "covers": "DEMOGORGON_CHALLENGE",
             "why": "multiball: it serves 3 balls (multiball_serve(3) at 0x5f000); the port's flag witness 99 is set "
                    "here, and its STARTED audit is counted with a computed id"},
        ],
        "notes": "Break Out (0x31c00) begins push + bl.",
    },
    "uncanny_xmen_le-0.98": {
        "names": {0x5d120: "A Fiery Assault", 0x8fbd4: "Mayhem in Midtown", 0x6513c: "Bitter Rivalry",
                  0x7f668: "Genosha Under Siege", 0x950a0: "Rescue the Innocent", 0xa1fa4: "Sentinel Facility Raid",
                  0xaa98c: "Smuggled Cargo", 0xaf478: "Stopping a Juggernaut", 0x698e8: "Escape Nimrod",
                  0x6f954: "Future Hurry Up", 0xe825c: "Fastball Special", 0xa5dbc: "Sentinel Hurry Up",
                  0x792f8: "Future (mini wizard)", 0x990e4: "Save Senator Kelly Wizard"},
        "high_tail": [0x5d120, 0x8fbd4, 0x6513c, 0x7f668, 0x950a0, 0xa1fa4, 0xaa98c, 0xaf478, 0x698e8, 0x6f954],
        "medium": {0x792f8: "reached only by a tail branch from 0x7970c", 0x990e4: "a wizard mode with four "
                   "callers; check on a machine that it holds no ball"},
        "notes": "Each mode is a C++ singleton (Mode_<Name>) whose own slot-4 virtual is its start: it counts its "
                 "STARTS audit, creates its records and calls the shared Mode_Shared::v[2] (0xa8ce4, the port's "
                 "running byte +0x74). It is reached by the mode's non-virtual thunk (secondary base) and by the mode "
                 "start dispatcher 0x9c9e8 (a tail branch; 0x9c9e8's callers ignore the result). Hooking Mode_Shared's "
                 "shared start instead would need a block_obj per mode (the Mode_Shared subobject, at +8 per the port). Surrender Mutants serves 2 balls.",
    },
}


_SONG = ("a song mode's start from the song table (a data word only); it calls the relative add-balls wrapper with 0 "
         "(a ball save, no ball); the dispatch site was not located statically")
METALLICA = {
    "by_audit": {
        "AUD_BATTERY_MODE_STARTED": ("Battery", _SONG),
        "AUD_ENTER_SANDMAN_MODE_STARTED": ("Enter Sandman", _SONG),
        "AUD_FADE_TO_BLACK_MODE_STARTED": ("Fade to Black", _SONG),
        "AUD_FOR_WHOM_THE_BELL_TOLLS_MODE_STARTED": ("For Whom the Bell Tolls", _SONG),
        "AUD_FUEL_MODE_STARTED": ("Fuel", "its two callers test the result"),
        "AUD_ONE_MODE_STARTED": ("One", None),
        "AUD_SEVENTY_TWO_SEASONS_MODE_STARTED": ("Seventy Two Seasons", "reached by a tail branch only"),
        "AUD_HARDWIRED_MODE_STARTED": ("Hardwired", "reached by a tail branch only"),
        "AUD_COMBO_MODE_STARTED": ("Combo Mode (and Combo Challenge)", "one start for Combo and Combo Challenge (it "
                                   "counts either STARTED audit); it calls multiball_serve with 0 (no ball)"),
        "AUD_COMBO_CHALLENGE_MODE_STARTED": ("Combo Mode (and Combo Challenge)", None),
        "AUD_COFFIN_HURRY_UP_STARTED": ("Coffin Hurry-Up", "a caller tests the result"),
    },
    "shared_ok": [("AUD_COMBO_MODE_STARTED", "AUD_COMBO_CHALLENGE_MODE_STARTED")],
    "reject_audit": ["AUD_MODE_BONUS_LIT", "AUD_MODE_BONUS_SHOT_AWARDS", "AUD_MODE_BONUS_COLLECT_LIT",
                     "AUD_MODE_BONUS_COLLECT_AWARDS"],
    "notes": "Live-records title (the port's records name each song 'a song mode'). stock_scan_c.audit_ids reads this "
             "build's audit ids wrongly: it takes a junk {table, count, 8} record and falls back to the names' places, "
             "so its labels don't follow the ids (the port's 'labels do not follow the ids'); the real descriptor "
             "table gives ids that agree with the records each start creates (Enter Sandman 0xc5248 on 1.03, 0xc5718 on 1.04, creates 182, the "
             "port's first song record). The Mode Bonus audits are awards, not modes. The End of the Line adds a "
             "ball; The Unforgiven serves a computed count.",
}


# why the scanner finds no start slot on the two C++ titles (hand-confirmed, see REPORT.md)
HAND_CPP = {
    "jurassic_park_le-1.16":
        "Each mode constructor takes no arguments and hands its base constructor a descriptor filled at run time, so "
        "init_objects reads no ids (and finds 11 of the 24 objects; the cmode_manager constructor 0x13ad90 builds "
        "all 24 as function-local statics and stores them in the table 0x737350); find_mode_getter needs constant ids to vote and finds no getter - besides, the get-by-id "
        "accessor (cmode_manager::v[2] 0x13a2a4) is never called with a bl (callers inline it behind a vptr "
        "compare) - and find_award_add finds no award add, which the start-slot rule also requires.",
    "rush_le-1.18":
        "find_mode_getter picks get_rule 0x119d48 (manager v[24]; 520 call sites, nearly all with a constant RULE "
        "id) over get_mode 0x119fa0 (manager v[25]), the accessor the modes are fetched by; no get_rule call passes a "
        "mode id, so starter_slots has no (mode id, slot) votes. (After get_mode with a constant id the slots called "
        "are 4 x125, 44 x57, 14 x30, then 40 x10: even on the right getter the most-called slot is not the start.) "
        "Also cmode's vtable begins with pure "
        "virtuals whose words are 0 in the file (relocated to __cxa_pure_virtual), so class_model cuts cmode at 2 "
        "slots and own_slots counts every slot of every mode class as an override.",
}


# ---- names ------------------------------------------------------------------------------------------------------
def audit_words(aud):
    s = aud[4:] if aud.startswith("AUD_") else aud
    s = re.sub(r"^MODE_", "", s)
    s = re.sub(r"_(STARTED|STARTS|START)$", "", s)
    m = re.match(r"(.*)_MODE_EP_(\d+)(?:_(\d+))?(?:_(\d+))?$", s)
    if m:
        eps = [x for x in m.groups()[1:] if x]
        return "%s (episode%s %s)" % (S.readable(m.group(1)), "s" if len(eps) > 1 else "", "-".join(eps))
    return S.readable(s)


def words_hex(t, f):
    return ["0x%08x" % (t.p.word(f) or 0), "0x%08x" % (t.p.word(f + 4) or 0)]


def started_audit(name):
    return name.endswith(("_STARTED", "_STARTS", "_START"))


# ---- plain C ----------------------------------------------------------------------------------------------------
def how_c(t, f, fx, auds):
    p = t.p
    bits = []
    for va, v0, nm in fx["audits"]:
        if nm in auds:
            bits.append("counts %s (id %d) at 0x%x" % (nm, v0, va))
    if fx["flags_set"]:
        bits.append("sets game flag %s" % ",".join(str(a[1]) for a in fx["flags_set"] if a[1] is not None))
    made = [a for a in fx["creates"] if a[1] is not None]
    if made:
        bits.append("creates record(s) %s" % ",".join("%d (body 0x%x)" % (a[1], a[2]) if a[2] else str(a[1])
                                                      for a in made[:3]))
    r = fx["refs"]
    reach = []
    for s in r["bl"]:
        reach.append("bl 0x%x (fn 0x%x)" % (s, t.entry(s)))
    for s in r["b"]:
        reach.append("tail b 0x%x (fn 0x%x)" % (s, t.entry(s)))
    for s in r["code"]:
        reach.append("pointer made at 0x%x (fn 0x%x)" % (s, t.entry(s)))
    for s in r["data"]:
        reach.append("table word 0x%x" % s)
    bits.append("reached by " + ("; ".join(reach[:5]) + (" +%d more" % (len(reach) - 5) if len(reach) > 5 else "")))
    ev = fx.get("balls") or []
    if ev:
        bits.append("ball calls: %s (no ball served)" % ", ".join("%s(%s)" % (k, n) for _p, k, n in ev[:2]))
    return "; ".join(bits)


def c_title(key):
    t = Title(key)
    p = t.p
    hand = HAND.get(key, {})
    if isinstance(hand, str):
        hand = globals()[hand]
    by_audit = hand.get("by_audit", {})
    af = audit_functions(t)
    modes_aud = t.mode_audits()
    started_ids = {t.aud_id.get(a) for _k, a in modes_aud if started_audit(a)}
    by_fn = {}                                   # start -> [audit names]
    rejected = []
    for _k, aud in modes_aud:
        if aud in hand.get("reject_audit", ()):
            rejected.append({"name": audit_words(aud), "why": "%s is an award audit, not a mode's start" % aud})
            continue
        i = t.aud_id.get(aud)
        fs = af.get(i, [])
        if not fs:
            if is_multiball_name(aud):
                rejected.append({"name": audit_words(aud), "why": "multiball (%s); its count is not a constant "
                                 "anywhere" % aud})
            elif not any(re.search(r.get("covers", "^$"), aud) for r in hand.get("rejected", ())):
                rejected.append({"name": audit_words(aud), "why": "no function counts %s (id %s) with a constant id: "
                                 "counted from data (an index or a descriptor)" % (aud, i)})
            continue
        for f in fs:
            by_fn.setdefault(f, []).append(aud)
    out = []
    for f, auds in by_fn.items():
        fx = t.facts(f)
        name = hand.get("names", {}).get(f) or next((by_audit[a][0] for a in auds if a in by_audit), None)             or " / ".join(audit_words(a) for a in auds)
        words = words_hex(t, f)
        w1 = fx["words"][1]
        mbname = any(is_multiball_name(a) for a in auds)
        others = sorted({a[2] for a in fx["audits"] if a[1] in started_ids and a[2] not in auds and a[2]})
        r = fx["refs"]
        nref = sum(len(v) for v in r.values())
        why = None
        if f in hand.get("reject", {}):
            why = hand["reject"][f]
        elif mbname or fx["mb"]:
            ev = fx.get("balls") or []
            why = "multiball: %s" % ("named %s" % auds[0] if mbname else "")
            if ev:
                pth, k, n = ev[0]
                why += "%s%s via %s (%s)" % ("; " if mbname else "", "serves balls" if k == "serve" else "adds balls",
                                             " -> ".join(hx(x) for x in pth), "count %s" % n)
        elif not fx["movable"]:
            if w1 is not None and (w1 >> 24) & 0xF == 0xB and (w1 >> 28) != 0xF:
                why = "entry not movable: word 2 is bl 0x%x (a trampoline that relocated a bl would make it usable)" % (
                    S.branch_target(w1, f + 4))
            else:
                why = "entry not movable (words %s %s: a branch or a pc-relative load)" % tuple(words)
        elif others and not any(set(auds + others) <= set(pair) for pair in hand.get("shared_ok", ())):
            why = "shared: it also counts %s" % ", ".join(others)
        elif nref == 0:
            why = "nothing refers to its entry (not reachable in this build)"
        if why:
            rejected.append({"name": name, "start": hx(f), "words": words, "why": why})
            continue
        ru = [return_used(p, s) for s in r["bl"] + r["b"]]
        conf, note = "high", ""
        aud_note = next((by_audit[a][1] for a in auds if a in by_audit and by_audit[a][1]), None)
        if f in hand.get("medium", {}):
            conf, note = "medium", hand["medium"][f]
        elif aud_note:
            conf, note = "medium", aud_note
        elif any(ru) and f not in hand.get("high_tail", ()):
            conf, note = "medium", "a caller uses the result (%s)" % ", ".join(
                "0x%x: %s" % (s, u) for s, u in zip(r["bl"] + r["b"], ru) if u)
        how = how_c(t, f, fx, auds)
        if note:
            how += "; " + note
        out.append({"name": name, "start": hx(f), "words": words, "how": how, "confidence": conf, "risky": "",
                    "_sort": (min(t.aud_id.get(a, 9999) for a in auds), f)})
    for e in hand.get("extra", ()):
        f = e["start"]
        words = words_hex(t, f)
        if not movable(tuple(int(w, 16) for w in words)):
            rejected.append({"name": e["name"], "start": hx(f), "words": words, "why": "entry not movable"})
            continue
        row = {"name": e["name"], "start": hx(f), "words": words, "how": e["how"], "confidence": e["confidence"],
               "risky": e.get("risky", ""), "_sort": (10000, f)}
        if e.get("obj"):
            row["obj"] = hx(e["obj"])
        out.append(row)
    for e in hand.get("rejected", ()):
        row = dict(e)
        if isinstance(row.get("start"), int):
            row["start"] = hx(row["start"])
            row["words"] = words_hex(t, e["start"])
        rejected.append(row)
    out.sort(key=lambda m: m.pop("_sort"))
    for k, m in enumerate(out):
        m["id"] = k
    modes = [dict([("id", m["id"])] + [(k, v) for k, v in m.items() if k != "id"]) for m in out]
    eng = "engine: audit_add 0x%x%s%s%s%s" % (
        t.audit_add or 0, ", flag set 0x%x" % t.flag_set if t.flag_set else "",
        ", create-process 0x%x" % t.create if t.create else "",
        ", live_records 0x%x" % t.live_records if t.live_records else "",
        ", multiball_serve 0x%x" % t.mb_serve if t.mb_serve else "")
    return {"key": key, "family": "c", "modes": modes, "rejected": rejected,
            "notes": "%s. Method: the audit witness (the function that counts each mode's STARTED audit, true entry, "
                     "generic rules). %s" % (eng, hand.get("notes", ""))}


# ---- C++ ----------------------------------------------------------------------------------------------------------
def raw_slots(p, vt, n=200):
    out = []
    for k in range(n):
        f = p.word(vt + 8 + 4 * k)
        if f is None or (f and not p.in_text(f)):
            break
        out.append(f)            # 0: a pure virtual (its relocation to __cxa_pure_virtual is not in the file)
    return out


def start_signature(p, f, cap=400, strict=True):
    """(VAs of `strb rX(=1), [..]`, VAs of `add rY, rY, #1` + `str rY, [..]`) in the first *cap* words of *f*: the base
    start sets the per-player running byte to 1 and bumps the per-player starts count."""
    one, inc, s1, add1 = set(), [], [], set()
    for i in range(cap):
        va = f + 4 * i
        w = p.word(va)
        if w is None:
            break
        d = S.decode(w, va)
        if d[0] == "pushlr" and i > 6:
            break
        if d[0] == "mov" and d[2] == 1 and d[-1] == 0xE:
            one.add(d[1])
            continue
        if d[0] in ("bl", "blx"):
            one -= {0, 1, 2, 3, 12}
            add1 -= {0, 1, 2, 3, 12}
            continue
        if d[0] == "addi" and d[3] == 1 and (d[1] == d[2] or (not strict and d[2] not in (13, 15))):
            add1.add(d[1])
            continue
        if not strict and (w & 0x0FE00FF0) == 0x00800000 and ((w & 0xF) in one or ((w >> 16) & 0xF) in one):
            add1.add((w >> 12) & 0xF)                 # add rd, rn, r(=1)
            continue
        if d[0] == "stri" and d[1] in add1:
            inc.append(va)
            continue
        if (w & 0x0FF00000) == 0x05C00000 and ((w >> 12) & 0xF) in one:      # strb rt, [rn, #imm]
            s1.append(va)
            continue
        if d[0] in ("movw", "mvn", "ldri", "ldrlit", "movr", "mov", "subi", "andsi") and isinstance(d[1], int):
            one.discard(d[1])
            add1.discard(d[1])
    return s1, inc


def find_start_slot(p, model):
    """(slot, base function, base class, evidence) of cmode's own start, or Nones."""
    best = None
    for strict in (True, False):          # `add rX, rX, #1` first; then a count bumped through another register
        for base in ("cmode", "cmode_null"):
            m = model.get(base)
            if not m or not m.get("vtable"):
                continue
            for k, f in enumerate(raw_slots(p, m["vtable"])):
                if not f:
                    continue
                s1, inc = start_signature(p, f, strict=strict)
                if s1 and inc:
                    # a pre-thunk that falls into the real start shows the same hits: keep the closest start
                    # (relaxed pass: the lowest slot - the base's resume, three slots on, has the same shape)
                    cand = (s1[0] - f if strict else k, k, f, base, s1[0], inc[0])
                    if best is None or cand[0] < best[0]:
                        best = cand
            if best:
                break
        if best:
            break
    if not best:
        return None, None, None, None
    _d, k, f, base, a, b = best
    return k, f, base, "%s::v[%d] 0x%x sets the running byte (strb of 1 at 0x%x) and bumps the starts count (0x%x)" % (
        base, k, f, a, b)


def vptr_class(p, model, f, cap=600):
    """The class whose vptr a constructor stores last (movw/movt or literal of vtable + 8)."""
    vp2c = {m["vtable"] + 8: c for c, m in model.items() if m.get("vtable")}
    end, lits = S.function_extent(p, f)
    found, regs = [], {}
    for va in range(f, min(max(end, f + 64), f + 4 * cap), 4):
        if va in lits:
            continue
        d = S.decode(p.word(va), va)
        if d[0] == "movw":
            regs[d[1]] = d[2]
        elif d[0] == "movt":
            v = (d[2] << 16) | (regs.get(d[1], 0) & 0xFFFF)
            if v in vp2c:
                found.append(vp2c[v])
        elif d[0] == "ldrlit":
            v = p.word(d[2])
            if v in vp2c:
                found.append(vp2c[v])
        elif d[0] == "poppc" and d[-1] == 0xE:
            break
    return found[-1] if found else None


def table_objects(t, model, table, count):
    """{id: (object, class)} from the function that fills the mode table *table* (the manager's constructor: it
    stores each mode object's address at table + 4 * id, constructing function-local statics behind guards)."""
    p = t.p
    fill = None
    for x in p.references(table):
        f = t.entry(x)
        tr = track_entry(p, f)
        if sum(1 for c in tr.calls if isinstance(c["args"].get("r0"), S.Val)) >= count:
            fill = f
            break
    if fill is None:
        return {}, None
    regs, tab, va = {}, {}, fill
    for _n in range(4000):
        w = p.word(va)
        d = S.decode(w, va)
        if d[0] == "movw":
            regs[d[1]] = d[2]
        elif d[0] == "movt":
            regs[d[1]] = (d[2] << 16) | (regs.get(d[1], 0) & 0xFFFF)
        elif d[0] == "mov":
            regs[d[1]] = d[2]
        elif d[0] == "ldrlit":
            regs[d[1]] = p.word(d[2])
        elif d[0] == "movr":
            if d[2] in regs:
                regs[d[1]] = regs[d[2]]
            else:
                regs.pop(d[1], None)
        elif d[0] in ("addi", "subi"):
            if d[2] in regs:
                regs[d[1]] = (regs[d[2]] + (d[3] if d[0] == "addi" else -d[3])) & 0xFFFFFFFF
            else:
                regs.pop(d[1], None)
        elif d[0] == "stri":
            if regs.get(d[2]) == table and d[1] in regs and d[3] >= 0:
                tab[d[3] // 4] = regs[d[1]]
        elif (w & 0x0FD00000) == 0x09800000 and regs.get((w >> 16) & 0xF) == table:      # stmib table, {...}
            for j, rr in enumerate(i for i in range(16) if (w >> i) & 1):
                if rr in regs:
                    tab[1 + j] = regs[rr]
        elif d[0] == "ldri":
            regs.pop(d[1], None)
        elif d[0] == "poppc" and d[-1] == 0xE:
            break
        va += 4
    ctor_of = {}
    for c in track_entry(p, fill).calls:
        o = c["args"].get("r0")
        if isinstance(o, S.Val):
            ctor_of.setdefault(o.v, c["target"])
    out = {}
    for i, obj in tab.items():
        if i >= count:
            continue
        ctor = ctor_of.get(obj)
        out[i] = (obj, vptr_class(p, model, ctor) if ctor else None)
    return out, fill


def cpp_title(key):
    t = Title(key)
    p = t.p
    model = S.class_model(p)
    fam = C.family(model)
    reading = C.read(p, model)
    slot, base_fn, base_cls, sig = find_start_slot(p, model)
    root = fam[0]
    fw = set(C.FRAMEWORK) | {c for c in model if c.endswith("_null")}
    objs = C.init_objects(p, model, root)
    ids = [o for o in objs if o["id"] is not None and S.derives(model, o["class"], "cmode") and o["class"] not in fw]
    why_none = []
    if reading.engine.get("start_slot") is None:
        mode_ids = {o["id"] for o in ids}
        getter = reading.engine.get("mode_getter")
        why_none.append("computed: %d of %d mode objects have a constant id; mode getter %s%s; award add %s; class_model "
                        "gives cmode %s slots" % (
                            len(ids), sum(1 for o in objs if S.derives(model, o["class"], "cmode")
                                          and o["class"] not in fw),
                            hx(getter) if getter else "not found",
                            " (called with a constant MODE id at %d of its %d call sites)" % (
                                sum(1 for c in p.callers(getter) if p.const_before(c, 0) in mode_ids),
                                len(p.callers(getter))) if getter else "",
                            hx(reading.engine["award_add"]) if reading.engine.get("award_add") else "not found",
                            model.get("cmode", {}).get("nvirt")))
        why_none[-1] += "."
        why_none.append(HAND_CPP.get(key, ""))
    modes, rejected = [], []
    source = "the scanner's static-initialiser objects (constructor ids)"
    if ids:
        rows = sorted(((o["id"], o["obj"], o["class"]) for o in ids), key=lambda r: r[0])
    else:
        table = port_int(t.port, "data", "stock_mode_table")
        count = port_int(t.port, "value", "stock_mode_count") or 0
        tab, fill = table_objects(t, model, table, count) if table else ({}, None)
        rows = sorted((i, o, c) for i, (o, c) in tab.items() if c)
        source = ("the mode table 0x%x (the port's stock_mode_table, %d ids) as its filler 0x%x (the cmode_manager "
                  "constructor) stores it: id = table index" % (table, count, fill or 0))
    starts = {}
    for mid, obj, cls in rows:
        vt = model[cls]["vtable"]
        starts.setdefault(p.word(vt + 8 + 4 * slot), []).append(cls)
    chain_starts = {}
    for mid, obj, cls in rows:
        if cls in fw or not S.derives(model, cls, "cmode"):
            continue
        vt = model[cls]["vtable"]
        st = p.word(vt + 8 + 4 * slot)
        words = words_hex(t, st)
        name = S.class_words(cls)
        if S.derives(model, cls, "cmode_mball"):
            rejected.append({"name": name, "start": hx(st), "why": "multiball (%s derives cmode_mball)" % cls})
            continue
        if not movable((p.word(st), p.word(st + 4))):
            rejected.append({"name": name, "start": hx(st), "words": words, "why": "entry not movable"})
            continue
        # the leaf start calls up its base chain's start (super::start) - the slot's meaning, checked per class
        bases = {p.word(model[b]["vtable"] + 8 + 4 * slot) for b in S.chain_of(model, cls)
                 if model.get(b, {}).get("vtable")}
        bases |= {base_fn}
        sup = [c["target"] for c in track_entry(p, st).calls if c["target"] in bases]
        shared = len(starts.get(st, [])) > 1
        refs = fmt_refs(t, t.refs(st), 2)
        how = "%s's v[%d] (vtable 0x%x + 8 + 4*%d) on object 0x%x; %s; reached by %s" % (
            cls, slot, vt, slot, obj, "calls its base's start 0x%x (super::start)" % sup[0] if sup
            else "does not call a base start directly", refs)
        conf = "high" if sup and not shared else "medium"
        row = {"id": mid, "name": name, "start": hx(st), "words": words, "how": how, "confidence": conf, "risky": "",
               "obj": hx(obj)}
        if cls in ("cmode_escape_nublar", "cmode_2112_wizard"):
            row["confidence"] = "medium"
            row["how"] += "; a wizard mode (cmode, not cmode_mball): check on a machine that it serves no ball"
        modes.append(row)
    return {"key": key, "family": root, "start_slot": slot,
            "start_slot_how": "%s. Why stock_scan_cpp.read gives no start_slot: %s" % (
                sig, " ".join(why_none) or "-"),
            "modes": modes, "rejected": rejected,
            "notes": "Objects: %s. The same slot rule agrees with stock_scan_cpp on all 22 C++ programs that have a slot "
                     "(Godzilla 8, Deadpool 13, Venom 47, TMNT 39, Munsters 33, Mandalorian 38, Jaws 12, King Kong 11, "
                     "Avengers 11, John Wick 47, Sword of Rage 31, Iron Maiden 8, Star Wars 8, D&D 50, Foo Fighters "
                     "41, Led Zeppelin 33). ids here are the game's own mode ids." % source}


def main(argv):
    keys = argv or (C_TITLES + CPP_TITLES)
    for key in keys:
        res = cpp_title(key) if key in CPP_TITLES else c_title(key)
        path = os.path.join(HERE, "json", key + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print("%-28s %-6s modes %2d (high %2d)  rejected %2d%s" % (
            key, res["family"], len(res["modes"]), sum(m["confidence"] == "high" for m in res["modes"]),
            len(res["rejected"]), "  start_slot %s" % res["start_slot"] if "start_slot" in res else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
