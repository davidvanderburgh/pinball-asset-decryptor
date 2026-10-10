"""PAD-436: a mode can be the GAME's own mini-wizard (James Bond LE 1.06's four): when it starts - on a film done, a
shot, shots in order - the player is handed the game's mode (pad_mode_runtime.c pm_game_wizard), lit for its start
shot or started at once, and nothing of the mode's own runs.

What is worth failing on:
  * THE WIZARDS ARE THE PORT'S: the profile lists the port's wizard lines by name and film, as the runtime arms them;
    a title whose port names none cannot, and says why.
  * A HAND-OVER WRITES ONLY WHAT IT USES: its name, what starts it, how often, and `game_wizard light|start <name>` -
    no clock, shots, screen, lights or sounds - and is valid with no clock (mode_file.c's runs()).
  * THE MODE FILE HANDS IT OVER INSTEAD OF RUNNING: pm_game_wizard_named is called with the name and how, no START of
    a mode of ours, no screen; how often it can start still holds.
  * A NAME IS CHECKED, and goes with the model like the light shows.
  * THE BLOCK hands one over by name, refused where the game has none.
  * THE RUNTIME keeps a refused start lit: a mode of ours that holds the game's modes off vetoes Ahoy Mr. Bond's
    start, and the game's start would otherwise unlight it and mark it played.
  * THE ONE HANDED OVER IS THE ONE THAT STARTS (PAD-457): the game's own lighting lights every one not played and its
    selection shots cycle among the lit ones, so a Bond owner who finished From Russia With Love got Duel on the
    Disco Volante off the Right ramp. Until the game starts it, it is the only one lit and the one selected; the
    game's own are lit again after. A start the game refuses (the film's last part comes from a mode still running)
    starts the moment the game would, that ball; two handed over start in order; a new game drops them.
  * A MINI-WIZARD A MODE HANDS OUT IS ITS MODE'S (PAD-457, then): the same owner played Duel on the Disco Volante off
    Thunderball and the Right ramp lit the next one with no film done - once a part is in all six films, the game's
    own lighting lights them all again at every more of it. The modes claim theirs as they load (a mode file's
    `game_wizard`, a blocks mode's init), the game's lighting (`site wizard_light`, vetoed) leaves a claimed one
    unlit and lights the rest, and nothing claimed is given back. A blocks mode saved by an older app is translated
    again before a build, so its claims are in.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
BOND_PORT = SDK / "ports" / "james_bond_le-1.06.port"
BOND = MP.profile_from_port(str(BOND_PORT))


def _without_wizards(name):
    """The port with its mini-wizard lines taken out: a title the app has found none on (PAD-473 gave Godzilla's its
    own; this keeps the tests' title-without-them)."""
    import tempfile
    text = (SDK / "ports" / name).read_text(encoding="utf-8")
    text = "\n".join(ln for ln in text.splitlines() if not re.match(r"(data|text|site|value)\s+wizard_", ln))
    d = pathlib.Path(tempfile.mkdtemp(prefix="pad473-"))
    (d / name).write_text(text + "\n", encoding="utf-8")
    return MP.profile_from_port(str(d / name))


GZ = _without_wizards("godzilla_le-1.16.port")
NAMES = ["Chaos at Crab Key", "Ahoy Mr. Bond", "Goldfinger's Jackpot", "Duel on the Disco Volante"]


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (BOND, GZ):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "w").splitlines() if line and not line.startswith("#")]


# ---- the profile -----------------------------------------------------------------------------
def test_the_profile_lists_the_ports_wizards_with_their_films():
    assert [n for n, _f in BOND.game_wizards] == NAMES
    assert dict(BOND.game_wizards)["Ahoy Mr. Bond"] == "From Russia With Love"      # its insert is ROSA KLEBB
    assert dict(BOND.game_wizards)["Duel on the Disco Volante"] == "Thunderball"     # its insert is LARGO
    assert BOND.wizard_shot == "Right ramp"
    assert all(len(n) < MP.WIZARD_NAME_MAX for n in NAMES)
    assert "james_bond_le-1.06" in MP.WIZARDS_PROVEN and BOND.can("wizard")


def test_titles_without_wizards_cannot_and_say_why():
    assert not GZ.can("wizard") and GZ.game_wizards == () and "Godzilla Premium/LE 1.16" in GZ.why_not("wizard")
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        # PAD-473: a port that names them offers them once the build is proven
        assert p.can("wizard") == (bool(p.game_wizards) and "%s-%s" % (p.game_dir, p.version) in MP.WIZARDS_PROVEN), key
        if not p.game_wizards:
            assert p.label in p.why_not("wizard"), key


def test_the_runtime_needs_its_lines():
    port = MP.read_port(str(BOND_PORT))
    assert MP._game_wizards(port)
    for kind, name in (("site", "wizard_start"), ("data", "wizard_state"), ("data", "wizard_table"),
                       ("data", "lamps_dirty")):
        cut = MP.read_port(str(BOND_PORT))
        del cut[kind][name]
        assert MP._game_wizards(cut) == (), name


#: (build, its starts in the table, its own lighting): PAD-473 found LE 1.06's code on Pro 1.06, 0xfcc lower
BOND_BUILDS = [("james_bond_le-1.06", [0x92bd8, 0x20530, 0xbd4dc, 0x7e0b0], 0x110cac),
               ("james_bond_pro-1.06", [0x92a90, 0x20530, 0xbd2c4, 0x7dfd8], 0x10fce0)]


@pytest.mark.parametrize("key,want,light", BOND_BUILDS)
def test_the_port_lines_match_the_game_program_when_it_is_here(key, want, light):
    """The start's words, and the table the runtime checks at its arm (index, bit, a start in the code)."""
    env = "PAD_BOND_%s_106_ELF" % key.split("_")[2].split("-")[0].upper()     # PAD_BOND_LE_106_ELF, ..._PRO_...
    elf = next((p for p in (os.environ.get(env, ""), r"C:\tmp\PAD-420\elf\%s.elf" % key,
                            "/mnt/c/tmp/PAD-420/elf/%s.elf" % key) if p and os.path.isfile(p)), None)
    if not elf:
        pytest.skip("%s's game program is not here" % key)
    import struct
    b = open(elf, "rb").read()
    text = (SDK / "ports" / ("%s.port" % key)).read_text(encoding="utf-8")

    def word(addr):                         # the program's first PT_LOAD is at 0x8000, file offset 0
        return struct.unpack_from("<I", b, addr - 0x8000)[0]
    m = re.search(r"^site\s+wizard_start\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)", text, re.M)
    addr, w0, w1 = (int(x, 16) for x in m.groups())
    assert (word(addr), word(addr + 4)) == (w0, w1)
    table = int(re.search(r"^data\s+wizard_table\s+(0x[0-9a-f]+)", text, re.M).group(1), 16)
    starts = []
    for n in range(4):
        e = [word(table + 0x20 * n + 4 * k) for k in range(4)]
        assert e[0] == n and e[1] == 1 << n
        starts.append(e[3])
    assert starts == want
    assert "site block_start_6      0x00020530" in text            # Ahoy's start: a mode of ours may veto it
    m = re.search(r"^site\s+wizard_light\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)", text, re.M)
    addr, w0, w1 = (int(x, 16) for x in m.groups())
    assert addr == light and (word(addr), word(addr + 4)) == (w0, w1)


def test_a_game_with_no_mini_wizards_leaves_the_section_out(monkeypatch):
    """PAD-473: a game with none of its own says so and is `absent`, as a machine part the machine lacks; a game
    not listed stays as it was (greyed, the app has not found them) and a port that names some wins."""
    for name, has in (("munsters_le-1.28", "Munster Madness"), ("munsters_pro-1.28", "Munster Madness"),
                      ("star_wars_elg-1.10", "Jedi Multiball"), ("james_bond_60th_le-1.11", "007 Mode")):
        p = MP.profile_from_port(str(SDK / "ports" / (name + ".port")))
        assert "wizard" in p.absent and "has no mini-wizards of its own (%s" % has in p.why_not("wizard"), name
    assert "wizard" not in GZ.absent and "has not found" in GZ.why_not("wizard")
    assert set(MP.NO_GAME_WIZARDS) <= set(MP.MACHINE_HARDWARE)                      # real game directories
    monkeypatch.setattr(MP, "NO_GAME_WIZARDS", {"godzilla_le": "its own story", "james_bond_le": "never"})
    gz = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))         # its port names three
    assert gz.game_wizards and "wizard" not in gz.absent
    assert MP.profile_from_port(str(BOND_PORT)).can("wizard") and "wizard" not in MP.profile_from_port(
        str(BOND_PORT)).absent


# ---- PAD-473: the C++ titles' mode route: the profile ------------------------------------------
def test_a_mode_route_port_names_its_wizards_and_which_it_can_light():
    gz = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    assert [n for n, _f in gz.game_wizards] == ["Monster Zero", "Terror of Mechagodzilla", "Planet X Multiball"]
    assert gz.wizard_lights == () and not gz.wizard_claims and BOND.wizard_claims
    assert BOND.wizard_lights == tuple(NAMES)
    sw = MP.profile_from_port(str(SDK / "ports" / "star_wars_le-1.31.port"))
    assert sw.wizard_lights == ("Lightsaber Duel",) and sw.wizard_shot == "Left ramp"
    port = MP.read_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    assert MP._wizard_route(port) == 2 and MP._wizard_route(MP.read_port(str(BOND_PORT))) == 1
    del port["value"]["stock_slot_start"]
    assert MP._wizard_route(port) == 0 and MP._game_wizards(port) == ()


def test_every_mode_route_port_is_whole():
    """Each `wizard_obj_<n>` has its name, numbered from 1 with no gap, every name fits mode_file.c, and a port's
    START / ACTIVE slots are the ones its block lines and its stack route already use."""
    for path in sorted((SDK / "ports").glob("*.port")):
        port = MP.read_port(str(path))
        objs = sorted(int(k.rsplit("_", 1)[1]) for k in port["data"] if k.startswith("wizard_obj_"))
        if not objs:
            continue
        assert objs == list(range(1, len(objs) + 1)), path.name
        p = MP.profile_from_port(str(path))
        assert len(p.game_wizards) == len(objs), path.name
        assert all(len(n) < MP.WIZARD_NAME_MAX for n, _f in p.game_wizards), path.name
        assert all("wizard_obj_%d" % k in port["data"] for k in range(1, len(objs) + 1)), path.name
        if p.wizard_lights:
            assert port["text"].get("wizard_shot"), path.name


def test_one_the_game_lights_for_no_shot_is_written_as_start(monkeypatch):
    monkeypatch.setattr(MP, "WIZARDS_PROVEN", MP.WIZARDS_PROVEN | {"godzilla_le-1.16"})
    gz = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    monkeypatch.setitem(MP.PROFILES, gz.key, gz)
    spec = _spec(gz, name="MZ", game_wizard="Monster Zero", wizard_how="light")
    assert MP.validate(spec) == []
    assert _lines(spec)[-1] == "game_wizard    start Monster Zero"


def test_bond_pro_has_the_les_wizards_and_is_proven():
    """PAD-473: the Pro's port names the same four, films and start shot, and the build was seen handing them over."""
    pro = MP.profile_from_port(str(SDK / "ports" / "james_bond_pro-1.06.port"))
    assert pro.game_wizards == BOND.game_wizards and pro.wizard_shot == "Right ramp"
    assert "james_bond_pro-1.06" in MP.WIZARDS_PROVEN and pro.can("wizard")


# ---- the mode ----------------------------------------------------------------------------------
def test_a_hand_over_writes_only_what_it_uses():
    spec = _spec(BOND, name="FRWL WIZARD", starts_on="event film_frwl", starts="once_per_game",
                 game_wizard="Ahoy Mr. Bond", wizard_how="start", screen=True, lights=True)
    assert MP.validate(spec) == []
    assert _lines(spec) == ["name           FRWL WIZARD", "starts_on      event film_frwl",
                            "starts         once_per_game", "game_wizard    start Ahoy Mr. Bond"]
    shot = _spec(BOND, name="GF", game_wizard="Goldfinger's Jackpot")
    lines = _lines(shot)
    assert lines[1].startswith("trigger ") and lines[-1] == "game_wizard    light Goldfinger's Jackpot"
    assert not any(line.split()[0] in ("seconds", "shots", "award", "screen_scene", "light_all", "callout_end",
                                       "game_modes", "ends_on") for line in lines)


def test_a_hand_over_needs_none_of_a_modes_own_parts():
    spec = _spec(BOND, game_wizard="Chaos at Crab Key", seconds=0, scoring_shots=[], award=0)
    assert MP.validate(spec) == []
    spec.game_wizard = ""
    assert "It has to run for at least a second." in MP.validate(spec)


def test_a_mode_of_its_own_writes_no_wizard_line():
    assert MP.ModeSpec().game_wizard == "" and MP.ModeSpec().wizard_how == "light"
    assert not any(line.startswith("game_wizard") for line in _lines(_spec(BOND)))


def test_the_refusals_name_the_mode_page():
    from pinball_decryptor.webui.tabs.modes import problem_pages
    bad = MP.validate(_spec(BOND, game_wizard="Nope"))
    assert bad == ["James Bond 007 LE 1.06 has no mini-wizard called 'Nope'."]
    how = MP.validate(_spec(BOND, game_wizard="Ahoy Mr. Bond", wizard_how="later"))
    assert how == ["The game's mini-wizard is lit for its start shot, or started at once."]
    gz = MP.validate_wizard(_spec(GZ, game_wizard="Ahoy Mr. Bond"), GZ)
    assert gz == ["A mini-wizard of the game's is not on Godzilla Premium/LE 1.16 (Mode says why)."]
    assert problem_pages(bad) == problem_pages(how) == problem_pages(gz) == ["mode"]
    assert MP.blank_spec(GZ).game_wizard == ""


def test_the_fields_round_trip_and_belong_to_the_model(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=_spec(BOND, game_wizard="Duel on the Disco Volante", wizard_how="start"))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.game_wizard, back.wizard_how) == ("Duel on the Disco Volante", "start")
    assert "game_wizard" in MP.MODEL_FIELDS


def test_a_hand_over_takes_no_screen_clip_or_sound_on_the_card():
    """Its own parts are kept in the mode (for the way back to a mode of its own) but nothing is built for them;
    its mode file still goes on the card in its slot."""
    import inspect
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    spec = _spec(BOND, game_wizard="Ahoy Mr. Bond", sound_start="s.wav", music="m.wav")
    assert MS.wants(spec) == ()
    spec.game_wizard = ""
    assert MS.wants(spec) == ("sound_start", "music")
    src = inspect.getsource(MA.build)
    assert "own = [(slug, spec) for slug, spec in found if not spec.game_wizard]" in src
    assert "for slug, spec in own if spec.screen" in src and "for slug, spec in own if spec.clip" in src
    assert "for slot, (slug, spec) in enumerate(found):" in src


def test_another_game_drops_the_wizard_and_says_so():
    spec = _spec(BOND, game_wizard="Ahoy Mr. Bond")
    on_gz, _dropped = MP.retarget(spec, GZ)
    assert on_gz.game_wizard == ""


# ---- the mode file -----------------------------------------------------------------------------
def _harness(tmp_path_factory):
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + "\nint pm_game_wizard_named(const char *name, int how) "
                            "{ printf(\"GAMEWIZARD %s how %d at %lu\\n\", name, how, now_ms); "
                            "return how == PM_WIZARD_START ? PM_WIZARD_STARTED : PM_WIZARD_LIT; }"
                            "\nint pm_game_wizard_claim_named(const char *name) "
                            "{ printf(\"CLAIM %s at %lu\\n\", name, now_ms); return 1; }")]
    return _build(tmp_path_factory, stubs, "gamewizard")


@pytest.fixture(scope="module")
def harness_wizard(tmp_path_factory):
    return _harness(tmp_path_factory)


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


AHOY = "name AHOY\ntrigger 0x08000000 1\nstarts once_per_game\ngame_wizard start Ahoy Mr. Bond\n"


def test_the_mode_file_hands_it_over_instead_of_running(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY, "shot", "0x08000000", "tick", "200")
    assert "NOT VALID" not in out
    assert '"AHOY": when it starts, the game\'s mini-wizard "Ahoy Mr. Bond" is started instead' in out
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMEWIZARD ")] == \
        ["GAMEWIZARD Ahoy Mr. Bond how 1"], out
    assert "AHOY START (trigger shot): the game's Ahoy Mr. Bond, started for player 1" in out
    assert "AHOY END" not in out and "own screen" not in out


def test_how_often_still_holds_and_light_is_light(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY, "shot", "0x08000000", "tick", "30", "shot", "0x08000000", "tick", "30")
    assert out.count("GAMEWIZARD ") == 1 and "AHOY not started (trigger shot): already ran this game" in out
    out = _run(harness_wizard, tmp_path, AHOY.replace("start Ahoy", "light Ahoy").replace("starts once_per_game\n", ""),
               "shot", "0x08000000", "tick", "30", "shot", "0x08000000", "tick", "30")
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMEWIZARD ")] == \
        ["GAMEWIZARD Ahoy Mr. Bond how 0"] * 2
    assert "the game's Ahoy Mr. Bond, lit for its start shot for player 1" in out


def test_the_mode_file_claims_its_mini_wizard_as_it_loads(harness_wizard, tmp_path):
    """PAD-457: before any shot or film - the game's own lighting must leave it alone from the game's start."""
    out = _run(harness_wizard, tmp_path, AHOY, "tick", "30")
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("CLAIM ")] == ["CLAIM Ahoy Mr. Bond"]
    assert "GAMEWIZARD" not in out
    out = _run(harness_wizard, tmp_path, AHOY.replace("game_wizard start Ahoy Mr. Bond\n", "seconds 20\n"), "tick", "30")
    assert "CLAIM" not in out


def test_a_bad_how_is_skipped_and_the_file_is_not_valid(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY.replace("game_wizard start", "game_wizard later"),
               "shot", "0x08000000", "tick", "30")
    assert 'game_wizard "later Ahoy Mr. Bond" is not light or start - skipped' in out
    assert "NOT VALID" in out and "GAMEWIZARD" not in out


# ---- the runtime -------------------------------------------------------------------------------
#: the runtime's wizard code, lifted verbatim, over a fake game: the table, the player's words, the refresh byte and a
#: start that answers as the game's does (it starts the selected one when "ready", unlights them all, marks it played).
#: Built non-PIE so every address fits the runtime's 32-bit words, as on the machine.
WIZ_HOST = r'''
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#define PM_CAN_GAME_WIZARDS 0x2000000u
#define PM_WIZARD_LIGHT 0
#define PM_WIZARD_START 1
#define PM_WIZARD_LIT 1
#define PM_WIZARD_STARTED 2
#define MAP_R 1u
#define MAP_X 2u
#define MAP_GAME 4u
#define pm_snprintf snprintf
struct pm_mode { int x; };
static unsigned can = PM_CAN_GAME_WIZARDS;
static unsigned state[12], table[4][8];
static unsigned char dirty;
static int ready = 1, in_game = 1, starts, run[4];
static unsigned player = 1, stock_ball_ends, games;
typedef int (*veto_fn)(unsigned *regs);
static unsigned long now = 10000;
static const struct pm_mode ours = { 1 }, *block_owner, *running;
static char block_who[40] = "RUSH";
static int game_start(void) { starts++; return 1; }
static int run0(void) { return run[0]; }
static int run1(void) { return run[1]; }
static int run2(void) { return run[2]; }
static int run3(void) { return run[3]; }
static int (*const RUN[4])(void) = { run0, run1, run2, run3 };
static int wizard_start(void)                 /* the game's 0x110d98: ready = nothing of its own in the way */
{
    unsigned p = player, sel = state[p - 1];
    if (!ready || !state[4 + p - 1] || run[0] || run[1] || run[2] || run[3]) return 0;
    starts += 100 * (int)(sel + 1);           /* which one it started */
    run[sel & 3] = 1;
    state[4 + p - 1] = 0;
    state[8 + p - 1] |= table[sel & 3][1];
    return 1;
}
unsigned long pm_ms(void) { return now; }
int pm_event(const char *n) { return !strcmp(n, "game_start") ? 7 : -1; }
static unsigned event_count(int id) { return id == 7 ? games : 0; }
static void say(const char *fmt, ...) { va_list a; va_start(a, fmt); printf("SAY "); vprintf(fmt, a); printf("\n"); va_end(a); }
static unsigned data(const char *n)
{
    return !strcmp(n, "wizard_state") ? (unsigned)(unsigned long)state : !strcmp(n, "wizard_table")
        ? (unsigned)(unsigned long)table : !strcmp(n, "lamps_dirty") ? (unsigned)(unsigned long)&dirty : 0;
}
static unsigned fn(const char *n) { return !strcmp(n, "wizard_start") ? (unsigned)(unsigned long)wizard_start : 0; }
long pm_port_value(const char *n, long f) { return !strcmp(n, "wizard_entry") ? 32 : f; }
static const char *const NAMES[] = { "Chaos at Crab Key", "Ahoy Mr. Bond", "Goldfinger's Jackpot", "Duel on the Disco Volante" };
const char *pm_port_text(const char *n)
{
    int k;
    if (strncmp(n, "wizard_name_", 12)) return 0;
    k = atoi(n + 12);
    return k >= 1 && k <= 4 ? NAMES[k - 1] : 0;
}
unsigned pm_player(void) { return player; }
int pm_in_game(void) { return in_game; }
static int wizards_n = 4;
static struct { int n; unsigned p, sel, lit, played; } wiz_hold;
static int wiz_route = 1;                       /* PAD-473: Bond's table; the mode route has its own host below */
static int wizm_hand(int n, int how) { return 0; }
static void wizm_tick(void) {}
static int wizm_claim(int n) { return 0; }
%(due)s
%(lifted)s
int main(int argc, char **argv)
{
    int i, k;
    for (k = 0; k < 4; k++) {
        table[k][0] = (unsigned)k; table[k][1] = 1u << k; table[k][3] = 0x1000u + (unsigned)k;
        table[k][4] = (unsigned)(unsigned long)RUN[k];
    }
    wiz_light_hooked = 1;
    for (i = 1; i < argc; i++) {
        const char *c = argv[i];
        if (!strcmp(c, "light") || !strcmp(c, "start")) {
            int r = pm_game_wizard_named(argv[++i], !strcmp(c, "start") ? PM_WIZARD_START : PM_WIZARD_LIGHT);
            printf("R %d\n", r);
        } else if (!strcmp(c, "notready")) ready = 0;
        else if (!strcmp(c, "ready")) ready = 1;
        else if (!strcmp(c, "nogame")) in_game = 0;
        else if (!strcmp(c, "player")) player = (unsigned)atoi(argv[++i]);
        else if (!strcmp(c, "block")) block_owner = running = &ours;
        else if (!strcmp(c, "unblock")) running = 0;
        else if (!strcmp(c, "ramp_vetoed")) {    /* the Right ramp while a mode of ours refuses the start */
            wizard_refused(table[state[player - 1] & 3][3]);
            state[4 + player - 1] = 0;          /* what the game's start then does anyway */
            state[8 + player - 1] |= table[state[player - 1] & 3][1];
        } else if (!strcmp(c, "light_all")) {   /* the game's 0x110cac: every one not played, one selected */
            state[4 + player - 1] = ~state[8 + player - 1] & 0xfu;
            state[player - 1] = (unsigned)atoi(argv[++i]);
        } else if (!strcmp(c, "cycle")) {       /* the game's 0x110c38: the next lit one selected */
            unsigned s = state[player - 1] & 3, t = s;
            do t = (t + 1) & 3; while (t != s && !(state[4 + player - 1] & (1u << t)));
            state[player - 1] = t;
        } else if (!strcmp(c, "ramp")) wizard_start();   /* the Right ramp's handler */
        else if (!strcmp(c, "ends")) run[0] = run[1] = run[2] = run[3] = 0;   /* the running one ends */
        else if (!strcmp(c, "ball_end")) stock_ball_ends++;
        else if (!strcmp(c, "wait")) now += 300;
        else if (!strcmp(c, "new_game")) {      /* the game's player set-up (0x1109dc), then its game_start event */
            state[player - 1] = ~0u; state[4 + player - 1] = state[8 + player - 1] = 0; games++;
        } else if (!strcmp(c, "claim")) {
            printf("C %d\n", pm_game_wizard_claim_named(argv[++i]));
        } else if (!strcmp(c, "unhooked")) wiz_light_hooked = 0;
        else if (!strcmp(c, "game_light")) {   /* the game's 0x110cac through its hook: the veto first */
            const char *sel = argv[++i];
            if (!wizard_light_veto(0)) {
                state[4 + player - 1] = ~state[8 + player - 1] & 0xfu;
                state[player - 1] = (unsigned)atoi(sel);
            }
        } else if (!strcmp(c, "tick")) wizards_tick();
        dirty = 0;
        printf("S p%u sel %u lit %x played %x starts %d\n", player, state[player - 1], state[4 + player - 1],
               state[8 + player - 1], starts);
        (void)game_start;
    }
    return 0;
}
'''


def _wiz(tmp_path, *args):
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    from tests.test_spike2_mode_roster import _host_run, _lift
    lifted = "\n".join(_lift(src, sig) for sig in (
        "static unsigned *wizard_entry(int n)", "static const char *wizard_name(int n)",
        "static void wizard_refused(unsigned start)\n{", "static int wizard_running(int n)",
        "static void wizard_pin(unsigned p)", "static void wizard_due_next(unsigned p)",
        "static void wizard_due_start(unsigned p)", "static void wizards_tick(void)",
        "int pm_game_wizard(int n, int how)", "static int wizard_by_name(const char *name)",
        "int pm_game_wizard_named(const char *name, int how)", "static int wizard_light_veto(unsigned *r)",
        "int pm_game_wizard_claim(int n)", "int pm_game_wizard_claim_named(const char *name)"))
    due = re.search(r"#define WIZ_DUE_MAX \d+\n", src).group(0) + re.search(
        r"static struct \{\n    unsigned char n\[WIZ_DUE_MAX\];.*?\} wiz_due\[4\];\nstatic unsigned wiz_game;.*?"
        r"\nstatic int wiz_light_hooked;", src, re.S).group(0)
    code = WIZ_HOST.replace("%(due)s", due).replace("%(lifted)s", lifted)
    out = _host_run(tmp_path, code, flags=("-no-pie", "-fno-pie"), args=args)
    return out.splitlines()


def _states(out):
    return [line for line in out if line.startswith("S ")]


def test_the_runtime_lights_one_as_the_game_does(tmp_path):
    out = _wiz(tmp_path, "light", "goldfinger's jackpot")
    assert "R 1" in out and out[-1] == "S p1 sel 2 lit 4 played 0 starts 0"
    assert any("lit and selected for player 1" in line for line in out)


def test_the_runtime_starts_one_through_the_games_own_start(tmp_path):
    out = _wiz(tmp_path, "start", "Ahoy Mr. Bond")
    assert "R 2" in out and out[-1] == "S p1 sel 1 lit 0 played 2 starts 200"       # the game started entry 1
    assert any("the game started it (its own start), player 1" in line for line in out)


def test_the_runtime_leaves_it_lit_when_the_game_would_not_start_one(tmp_path):
    out = _wiz(tmp_path, "notready", "start", "Chaos at Crab Key")
    assert "R 1" in out and out[-1] == "S p1 sel 0 lit 1 played 0 starts 0"
    assert any("would not start it now" in line for line in out)


def test_the_runtime_lights_instead_of_starting_while_a_mode_of_ours_blocks(tmp_path):
    out = _wiz(tmp_path, "block", "start", "Ahoy Mr. Bond")
    assert "R 1" in out and out[-1] == "S p1 sel 1 lit 2 played 0 starts 0"
    assert any("RUSH holds the game's modes off, so it is lit, not started" in line for line in out)


def test_the_runtime_keeps_a_vetoed_start_lit_on_the_next_tick(tmp_path):
    out = _wiz(tmp_path, "player", "2", "light", "Ahoy Mr. Bond", "ramp_vetoed", "tick")
    states = [line for line in out if line.startswith("S ")]
    assert states[-2] == "S p2 sel 1 lit 0 played 2 starts 0"          # the game's start, refused, unlit it
    assert states[-1] == "S p2 sel 1 lit 2 played 0 starts 0"          # and the tick put it back
    assert any("its start was refused while RUSH runs - kept lit for player 2" in line for line in out)


def test_the_one_handed_over_is_the_one_the_ramp_starts_when_the_game_lit_them_all(tmp_path):
    """PAD-457, the report: From Russia With Love done (Ahoy Mr. Bond handed over) on top of the game's own lighting
    (every one not played), a selection shot, and the Right ramp started Duel on the Disco Volante."""
    out = _wiz(tmp_path, "light_all", "3", "light", "Ahoy Mr. Bond", "cycle", "tick", "light_all", "0", "tick",
               "ramp", "tick")
    s = _states(out)
    assert s[1] == "S p1 sel 1 lit 2 played 0 starts 0"        # handed over: the only one lit, and selected
    assert s[2] == "S p1 sel 1 lit 2 played 0 starts 0"        # the selection shot has nowhere else to go
    assert s[5] == "S p1 sel 1 lit 2 played 0 starts 0"        # the game lit them all again: pinned back
    assert s[6] == "S p1 sel 1 lit 0 played 2 starts 200"      # the Right ramp started Ahoy Mr. Bond
    assert s[7] == "S p1 sel 1 lit d played 2 starts 200"      # and the game's own three are lit again
    assert any("the game lit 0xd for player 1 as well" in line for line in out)
    assert any("the ones the game lit itself (0xd) are lit again for player 1" in line for line in out)


def test_a_start_the_game_refuses_starts_the_moment_it_would(tmp_path):
    """The film's last part comes from a henchman, villain or Q Branch mode still running, which the game's own check
    counts as in the way: "Start it at once" then starts it as soon as that mode is done, not only off the ramp."""
    out = _wiz(tmp_path, "light_all", "3", "notready", "start", "Ahoy Mr. Bond", "tick", "wait", "tick", "ready",
               "tick", "wait", "tick", "tick")
    s = _states(out)
    assert "R 1" in out and s[2] == "S p1 sel 1 lit 2 played 0 starts 0"
    assert s[5] == "S p1 sel 1 lit 2 played 0 starts 0"        # in the way: still waiting, still the one lit
    assert s[7] == "S p1 sel 1 lit 2 played 0 starts 0"        # tried no more than every 250 ms
    assert s[9] == "S p1 sel 1 lit d played 2 starts 200"      # started, and the game's own lit again
    assert s[10] == s[9]
    assert any("started the moment the game would, this ball" in line for line in out)
    assert any("now that nothing is in its way, player 1" in line for line in out)


def test_a_refused_start_waits_for_the_ramp_once_its_ball_has_ended(tmp_path):
    out = _wiz(tmp_path, "notready", "start", "Ahoy Mr. Bond", "ball_end", "ready", "wait", "tick", "wait", "tick",
               "ramp", "tick")
    s = _states(out)
    assert s[7] == "S p1 sel 1 lit 2 played 0 starts 0"        # not started on the next ball by itself
    assert s[8] == "S p1 sel 1 lit 0 played 2 starts 200"      # the Right ramp starts it
    assert sum("the ball ended before the game would start it" in line for line in out) == 1


def test_a_start_held_off_by_a_mode_of_ours_starts_when_it_ends(tmp_path):
    out = _wiz(tmp_path, "block", "start", "Ahoy Mr. Bond", "wait", "tick", "unblock", "wait", "tick")
    s = _states(out)
    assert s[3] == "S p1 sel 1 lit 2 played 0 starts 0"
    assert s[-1] == "S p1 sel 1 lit 0 played 2 starts 200"


def test_two_handed_over_start_in_order(tmp_path):
    out = _wiz(tmp_path, "light", "Ahoy Mr. Bond", "light", "Duel on the Disco Volante", "cycle", "ramp", "tick",
               "ramp", "ends", "ramp", "tick")
    s = _states(out)
    assert s[1] == s[2] == "S p1 sel 1 lit 2 played 0 starts 0"   # Disco Volante waits its turn
    assert s[3] == "S p1 sel 1 lit 0 played 2 starts 200"
    assert s[4] == "S p1 sel 3 lit 8 played 2 starts 200"         # then it is the one lit
    assert s[5] == s[4]                                           # not while Ahoy Mr. Bond runs
    assert s[7] == "S p1 sel 3 lit 0 played a starts 600"
    assert s[8] == s[7]
    assert any("after Ahoy Mr. Bond, which was handed over first" in line for line in out)


def test_a_new_game_drops_what_was_handed_over(tmp_path):
    out = _wiz(tmp_path, "light", "Ahoy Mr. Bond", "new_game", "tick", "tick", "light_all", "0", "tick")
    s = _states(out)
    assert s[2] == s[3] == "S p1 sel 4294967295 lit 0 played 0 starts 0"
    assert s[5] == "S p1 sel 0 lit f played 0 starts 0"           # the game's own lighting, left alone


CLAIM_ALL = ("claim", "Chaos at Crab Key", "claim", "Ahoy Mr. Bond", "claim", "Goldfinger's Jackpot",
             "claim", "Duel on the Disco Volante")


def test_a_played_film_wizard_is_not_followed_by_the_games_own_lighting(tmp_path):
    """PAD-457, the second report: every film hands out its own, Thunderball done, Duel on the Disco Volante off the
    Right ramp and over, then another henchman (a part already in all six films): nothing lit, the ramp starts
    nothing."""
    out = _wiz(tmp_path, *CLAIM_ALL, "light", "Duel on the Disco Volante", "ramp", "tick", "ends", "tick",
               "game_light", "1", "tick", "ramp", "tick")
    s = _states(out)
    assert out.count("C 1") == 4
    assert s[5] == "S p1 sel 3 lit 0 played 8 starts 400"           # Duel on the Disco Volante played
    assert s[8] == "S p1 sel 3 lit 0 played 8 starts 400"           # the game's lighting left them all unlit
    assert s[-1] == s[8]                                            # and the ramp started nothing
    assert any("the game would light 0x7 for player 1 - 0x7 of them only this card's modes hand out: left unlit" in ln
               for ln in out)
    assert sum("handed out by this card's modes only" in ln for ln in out) == 4


def test_the_game_still_lights_the_ones_no_mode_hands_out(tmp_path):
    out = _wiz(tmp_path, "claim", "Ahoy Mr. Bond", "game_light", "1", "claim", "ahoy mr. bond", "game_light", "1")
    s = _states(out)
    assert s[1] == "S p1 sel 0 lit d played 0 starts 0"             # Ahoy left unlit, one of the others selected
    assert sum("handed out by this card's modes only" in ln for ln in out) == 1   # a second claim says nothing new
    out = _wiz(tmp_path, "game_light", "2")                         # nothing claimed: the game's lighting as it was
    assert _states(out)[-1] == "S p1 sel 2 lit f played 0 starts 0"
    assert not any("left unlit" in ln for ln in out)


def test_nothing_claimed_is_given_back_after_a_hand_over(tmp_path):
    """The game lit them all before the card's claims could stop it (or a port without the hook): a claimed one is
    not owed, the unclaimed ones are."""
    out = _wiz(tmp_path, "claim", "Ahoy Mr. Bond", "claim", "Goldfinger's Jackpot", "light_all", "0",
               "light", "Ahoy Mr. Bond", "ramp", "tick")
    s = _states(out)
    assert s[-2] == "S p1 sel 1 lit 0 played 2 starts 200"
    assert s[-1] == "S p1 sel 1 lit 9 played 2 starts 200"          # Chaos and Disco Volante back, not Goldfinger
    assert any("the game lit 0x9 for player 1 as well" in ln for ln in out)


def test_a_claim_needs_the_ports_lighting_site(tmp_path):
    out = _wiz(tmp_path, "unhooked", "claim", "Ahoy Mr. Bond", "claim", "Nope", "game_light", "3")
    assert out.count("C 0") == 2
    assert any("this game's port names no wizard_light - the game's own lighting lights it too" in ln for ln in out)
    assert any("\"Nope\": not one of this game's mini-wizards - nothing claimed" in ln for ln in out)
    assert _states(out)[-1] == "S p1 sel 3 lit f played 0 starts 0"


def test_the_runtime_refuses_with_no_game_or_no_such_wizard(tmp_path):
    out = _wiz(tmp_path, "nogame", "light", "Ahoy Mr. Bond", "ready", "light", "Nope")
    assert out.count("R 0") == 2 and out[-1] == "S p1 sel 0 lit 0 played 0 starts 0"
    assert any("not handed over - no game" in line for line in out)
    assert any("not one of this game's mini-wizards" in line for line in out)


def test_the_runtime_keeps_a_refused_start_lit_and_lights_a_start_while_a_mode_blocks():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    veto = src[src.index("static int on_block_start("):]
    veto = veto[:veto.index("\n}\n")]
    assert veto.index("wizard_refused(block_hooked[hook_n]);") < veto.index("return 1;")
    wiz = src[src.index("int pm_game_wizard(int n, int how)"):]
    wiz = wiz[:wiz.index("\n}\n")]
    assert wiz.index("block_owner && running == block_owner") < wiz.index('fn("wizard_start")')
    assert "wizards_tick();" in src[src.index("static void on_tick(unsigned *r)"):]
    arm = src[src.index("static void wizards_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'hook_veto(fn("wizard_light"), wizard_light_veto)' in arm     # PAD-457: the game's own lighting
    assert "pm_game_wizard_claim_named(cfg.wizard);" in (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "wizards_arm();" in src and "PM_CAN_GAME_WIZARDS" in (SDK / "pad_mode.h").read_text(encoding="utf-8")


# ---- PAD-473: the C++ titles' mode route ---------------------------------------------------------
#: the runtime's mode-route code, lifted verbatim, over fake mode objects: each a vtable whose START slot sets it
#: running and whose ACTIVE slot answers it, the word before the vtable a typeinfo naming the class; the game's mode
#: table holds them all. Objects: 0 Monster Zero, 1 Terror of Mechagodzilla (a multiball), 2 the mode that lights
#: Monster Zero, 3 another of the game's multiballs, 4 the game's base play.
WIZM_HOST = r'''
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#define PM_CAN_GAME_WIZARDS 0x2000000u
#define PM_WIZARD_LIGHT 0
#define PM_WIZARD_START 1
#define PM_WIZARD_LIT 1
#define PM_WIZARD_STARTED 2
#define PM_WIZARD_WAITING 3
#define PM_STOCK_ANY 0x1u
#define PM_STOCK_MULTIBALL 0x2u
#define PM_STOCK_BATTLE 0x4u
#define pm_snprintf snprintf
#define SLOT_START 5
#define SLOT_ACTIVE 7
#define MAP_R 1u
#define MAP_X 2u
#define MAP_GAME 4u
struct pm_mode { int x; };
static unsigned can = PM_CAN_GAME_WIZARDS;
static int in_game = 1, wiz_route = 2, wizards_n = 3, table_route = 1, stock_table_off;
static unsigned player = 1, stock_ball_ends, games;
static unsigned long now = 10000;
static const struct pm_mode ours = { 1 }, *block_owner, *running;
static char block_who[40] = "RUSH";
struct obj { unsigned vt; int on, k, en; };
static int need_enable, enable_slot = -1;       /* Foo Fighters: START does nothing unless the mode was enabled */
#define SLOT_ENABLE 9
static struct obj objs[5];
static unsigned vtab[5][1 + 10], ti[5][2];
static const char *const CLS[5] = { "18cmode_monster_zero", "29cmode_terror_of_mechagodzilla", "17cmode_mz_ready",
                                    "15cmode_other_mb", "10cmode_base" };
static const int MB[5] = { 0, 1, 0, 1, 0 };
static unsigned char stock_base[5];
static int start_fn(struct obj *o) { printf("START %d\n", o->k); if (!need_enable || o->en) o->on = 1; return 0; }
static int enable_fn(struct obj *o) { o->en = 1; printf("ENABLE %d\n", o->k); return 0; }
static int active_fn(struct obj *o) { return o->on; }
static int bad = -1;                              /* an object the build does not vouch for */
static int maps_has(unsigned long a, unsigned long len, unsigned how) { return bad < 0 || a != (unsigned long)&objs[bad]; }
unsigned long pm_ms(void) { return now; }
int pm_event(const char *n) { return !strcmp(n, "game_start") ? 7 : -1; }
static unsigned event_count(int id) { return id == 7 ? games : 0; }
static void say(const char *fmt, ...) { va_list a; va_start(a, fmt); printf("SAY "); vprintf(fmt, a); printf("\n"); va_end(a); }
static int str_eq(const char *a, const char *b) { return !strcmp(a, b); }
/* the function route (the plain-C titles): each mini-wizard's start function; its ACTIVE game flag is the object's
 * `on` (flag 100 + the object) */
static int fn_route, refuse[4], no_flag, arg1, wizf_starting;
static int go_k(int k, unsigned arg)
{
    struct obj *o = &objs[k == 3 ? 3 : k - 1];
    printf("GO %d arg %u\n", k, arg);
    if (refuse[k]) return 0;                        /* the game's own rules: not now */
    if (!no_flag) o->on = 1;
    return 1;
}
static int go1(unsigned a) { return go_k(1, a); }
static int go2(unsigned a) { return go_k(2, a); }
static int go3(unsigned a) { return go_k(3, a); }
static int game_flag(unsigned id) { return id >= 100 && id < 104 ? objs[id - 100].on : -1; }
static int proc_route;                          /* "proc": mini-wizard 2 says it runs by a process of its own, 223 */
static int proc_alive(unsigned id) { return id == 223 && objs[1].on; }
static unsigned data(const char *n)
{
    if (fn_route) return !strcmp(n, "game_flags") ? 1u : 0u;
    if (!strncmp(n, "wizard_obj_", 11) && atoi(n + 11) >= 1 && atoi(n + 11) <= 3)
        return atoi(n + 11) == 3 ? (unsigned)(unsigned long)&objs[3] : (unsigned)(unsigned long)&objs[atoi(n + 11) - 1];
    if (!strcmp(n, "wizard_ready_1")) return (unsigned)(unsigned long)&objs[2];
    return 0;
}
static unsigned fn(const char *n)
{
    if (!fn_route) return 0;
    if (!strcmp(n, "proc_exists")) return proc_route;
    return !strcmp(n, "wizard_go_1") ? (unsigned)(unsigned long)go1 : !strcmp(n, "wizard_go_2")
        ? (unsigned)(unsigned long)go2 : !strcmp(n, "wizard_go_3") ? (unsigned)(unsigned long)go3 : 0;
}
long pm_port_value(const char *n, long f)
{
    if (fn_route && proc_route && !strcmp(n, "wizard_proc_2")) return 223;
    if (fn_route && proc_route && !strcmp(n, "wizard_flag_2")) return f;
    if (fn_route && !strncmp(n, "wizard_flag_", 12)) return atoi(n + 12) == 3 ? 103 : 99 + atoi(n + 12);
    if (fn_route && !strcmp(n, "wizard_arg_1")) return arg1;
    return !strcmp(n, "stock_slot_start") ? SLOT_START : !strcmp(n, "stock_slot_active") ? SLOT_ACTIVE
        : !strcmp(n, "wizard_slot_enable") ? enable_slot : f;
}
static const char *const NAMES[] = { "Monster Zero", "Terror of Mechagodzilla", "Other Multiball" };
const char *pm_port_text(const char *n)
{
    int k;
    if (strncmp(n, "wizard_name_", 12)) return 0;
    k = atoi(n + 12);
    return k >= 1 && k <= 3 ? NAMES[k - 1] : 0;
}
unsigned pm_player(void) { return player; }
int pm_in_game(void) { return in_game; }
/* the stack's walk over the game's mode table (pad_mode_runtime.c item 164), over the five objects */
static int stock_generic_route(void) { return table_route; }
static const unsigned *stock_table(long *n, long *slot)
{
    static unsigned tab[5];
    int k;
    for (k = 0; k < 5; k++) tab[k] = (unsigned)(unsigned long)&objs[k];
    *n = 5; *slot = SLOT_ACTIVE;
    return tab;
}
static int stock_entry_class(long i, const unsigned *tab, long n, long slot) { return MB[i] ? 2 : 1; }
static int stock_entry_active(const unsigned *o, long slot)
{
    return (((int (*)(const void *))(unsigned long)((const unsigned *)(unsigned long)o[0])[slot])(o) & 0xff) != 0;
}
static int stock_named_base(const char *nm) { return 0; }
int pm_stock_mode_running(unsigned kinds) { int k; for (k = 0; k < 5; k++) if (objs[k].on && !stock_base[k] && k != 2) return MB[k] ? 2 : 4; return 0; }
/* Bond's route, which pm_game_wizard leaves for this one first */
#define WIZ_DUE_MAX 4
static struct { unsigned char n[WIZ_DUE_MAX]; unsigned char start[WIZ_DUE_MAX]; int count; unsigned owed; unsigned ball;
                unsigned long tried; } wiz_due[4];
static unsigned *wizard_entry(int n) { static unsigned e[8]; return e; }
static void wizard_pin(unsigned p) {}
static void wizard_due_next(unsigned p) {}
%(due)s
%(lifted)s
int main(int argc, char **argv)
{
    int i, k;
    for (k = 0; k < 5; k++) {
        ti[k][1] = (unsigned)(unsigned long)CLS[k];
        vtab[k][0] = (unsigned)(unsigned long)ti[k];
        vtab[k][1 + SLOT_START] = (unsigned)(unsigned long)start_fn;
        vtab[k][1 + SLOT_ACTIVE] = (unsigned)(unsigned long)active_fn;
        vtab[k][1 + SLOT_ENABLE] = (unsigned)(unsigned long)enable_fn;
        objs[k].vt = (unsigned)(unsigned long)&vtab[k][1];
        objs[k].k = k;
    }
    for (i = 1; i < argc; i++) {
        const char *c = argv[i];
        if (!strcmp(c, "light") || !strcmp(c, "start")) {
            int r = pm_game_wizard_named(argv[++i], !strcmp(c, "start") ? PM_WIZARD_START : PM_WIZARD_LIGHT);
            printf("R %d\n", r);
        } else if (!strcmp(c, "on")) objs[atoi(argv[++i])].on = 1;      /* the game starts one of its own */
        else if (!strcmp(c, "off")) objs[atoi(argv[++i])].on = 0;       /* ... and it ends */
        else if (!strcmp(c, "base")) stock_base[atoi(argv[++i])] = 1;
        else if (!strcmp(c, "bad")) bad = atoi(argv[++i]);
        else if (!strcmp(c, "fnroute")) fn_route = 1, wiz_route = 3, table_route = 0;
        else if (!strcmp(c, "refuse")) refuse[atoi(argv[++i])] = 1;
        else if (!strcmp(c, "allow")) refuse[atoi(argv[++i])] = 0;
        else if (!strcmp(c, "noflag")) no_flag = 1;
        else if (!strcmp(c, "proc")) proc_route = 1;
        else if (!strcmp(c, "arg")) arg1 = atoi(argv[++i]);
        else if (!strcmp(c, "needen")) need_enable = 1;
        else if (!strcmp(c, "enable")) enable_slot = SLOT_ENABLE;
        else if (!strcmp(c, "notable")) table_route = 0;
        else if (!strcmp(c, "nogame")) in_game = 0;
        else if (!strcmp(c, "block")) block_owner = running = &ours;
        else if (!strcmp(c, "unblock")) running = 0;
        else if (!strcmp(c, "ball_end")) stock_ball_ends++;
        else if (!strcmp(c, "wait")) now += 300;
        else if (!strcmp(c, "new_game")) games++;
        else if (!strcmp(c, "tick")) wizm_tick();
        printf("S on %d%d%d%d%d\n", objs[0].on, objs[1].on, objs[2].on, objs[3].on, objs[4].on);
    }
    return 0;
}
'''


def _wizm(tmp_path, *args):
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    from tests.test_spike2_mode_roster import _host_run, _lift
    lifted = "\n".join(_lift(src, sig) for sig in (
        "static const char *wizard_name(int n)", "static const unsigned *wizm_obj(int n, int ready)",
        "static unsigned wizm_vfn(const unsigned *o, const char *slot)", "static int wizm_active(const unsigned *o)",
        "static void wizm_start(const unsigned *o)", "static int wizm_obj_here(const unsigned *o)",
        "static int wizm_owns(const unsigned *o)\n{",
        "static int wizm_obj_ok(const unsigned *o)", "static unsigned wizf_go(int n)", "static int wizf_runs(int n)",
        "static unsigned wizf_start(int n)", "static int wizm_runs(int n)", "static const char *wizm_way(void)",
        "static void wizm_next(unsigned p)", "static int wizm_try(unsigned p)", "static int wizm_hand(int n, int how)\n{",
        "static void wizm_tick(void)\n{", "int pm_game_wizard(int n, int how)", "static int wizard_by_name(const char *name)",
        "int pm_game_wizard_named(const char *name, int how)"))
    due = re.search(r"static struct \{\n    unsigned char n\[WIZ_DUE_MAX\];     /\* handed over to start.*?\} wizm_due\[4\];\n"
                    r"static unsigned wizm_game;", src, re.S).group(0)
    code = WIZM_HOST.replace("%(due)s", due).replace("%(lifted)s", lifted)
    return _host_run(tmp_path, code, flags=("-no-pie", "-fno-pie"), args=args).splitlines()


def test_the_mode_route_starts_one_by_its_own_start(tmp_path):
    out = _wizm(tmp_path, "start", "monster zero")
    assert "START 0" in out and "R 2" in out and out[-1] == "S on 10000"
    assert any("game wizard 1 (Monster Zero): started for player 1 (the mode's own start" in ln for ln in out)


def test_the_mode_route_waits_while_one_of_the_games_modes_runs(tmp_path):
    out = _wizm(tmp_path, "on", "3", "start", "Monster Zero", "tick", "wait", "tick", "off", "3", "tick", "wait", "tick")
    assert "R 3" in out and out.count("START 0") == 1
    assert out.index("START 0") > out.index("S on 00000") - 1                      # only once 3 has ended
    assert sum("a multiball (cmode_other_mb) is in its way" in ln for ln in out) == 1    # said once, not each try
    assert out[-1] == "S on 10000"


def test_the_mode_route_does_not_count_the_base_play_or_a_ready_mode_in_its_way(tmp_path):
    out = _wizm(tmp_path, "on", "4", "base", "4", "on", "2", "start", "Terror of Mechagodzilla")
    assert "R 2" in out and "START 1" in out


def test_a_mini_wizard_running_is_never_the_games_base_play(tmp_path):
    """The rig: on Iron Maiden LE 1.18 the stack's ball-start window (open until the ball's first score) took 2 Minutes
    to Midnight, handed over before anything scored, for base play - and Number of the Beast started on top of it."""
    out = _wizm(tmp_path, "start", "Monster Zero", "base", "0", "start", "Terror of Mechagodzilla", "wait", "tick")
    assert "START 0" in out and "START 1" not in out and "R 3" in out
    assert any("one of the game's modes (cmode_monster_zero) is in its way" in ln for ln in out)
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    tick = src[src.index("static void stock_generic_tick(void)"):]
    assert "else if (open && !stock_base[i] && !wizm_owns(o))" in tick[:tick.index("\n}\n")]


def test_the_mode_route_waits_while_a_mode_of_ours_holds_the_games_modes_off(tmp_path):
    out = _wizm(tmp_path, "block", "start", "Monster Zero", "wait", "tick", "unblock", "wait", "tick")
    assert "R 3" in out and out[-1] == "S on 10000"
    assert any("RUSH (a mode of yours holding the game's modes off) is in its way" in ln for ln in out)


def test_the_mode_route_gives_up_when_the_ball_ends_first(tmp_path):
    out = _wizm(tmp_path, "on", "3", "start", "Terror of Mechagodzilla", "ball_end", "off", "3", "wait", "tick", "wait",
                "tick")
    assert "START 1" not in out
    assert any("the ball ended before nothing of the game's was in its way - not started" in ln for ln in out)


def test_the_mode_route_lights_through_the_games_own_ready_mode(tmp_path):
    out = _wizm(tmp_path, "light", "Monster Zero")
    assert "START 2" in out and "START 0" not in out and "R 1" in out
    assert any("lit (the game's own mode that lights it) for player 1 - the game's start shot starts it" in ln
               for ln in out)
    out = _wizm(tmp_path, "light", "Terror of Mechagodzilla")       # no mode lights it: started instead
    assert "START 1" in out and "R 2" in out
    assert any("lights it for no start shot of its own - started instead" in ln for ln in out)


def test_the_mode_route_starts_two_in_order_and_not_on_top_of_each_other(tmp_path):
    out = _wizm(tmp_path, "on", "3", "start", "Monster Zero", "start", "Terror of Mechagodzilla", "off", "3", "wait",
                "tick", "wait", "tick", "off", "0", "wait", "tick")
    starts = [ln for ln in out if ln.startswith("START ")]
    assert starts == ["START 0", "START 1"]
    assert out.index("START 1") > out.index("S on 00000") if "S on 00000" in out else True
    assert any("started for player 1 after Monster Zero" in ln for ln in out)


def test_the_mode_route_says_already_running_and_a_new_game_drops_them(tmp_path):
    out = _wizm(tmp_path, "on", "0", "start", "Monster Zero")
    assert "R 2" in out and "START 0" not in out and any("already running" in ln for ln in out)
    out = _wizm(tmp_path, "on", "3", "start", "Monster Zero", "new_game", "tick", "off", "3", "wait", "tick")
    assert "START 0" not in out


def test_the_mode_route_without_the_mode_table_asks_the_stack(tmp_path):
    out = _wizm(tmp_path, "notable", "on", "3", "start", "Monster Zero", "off", "3", "wait", "tick")
    assert any("a multiball is in its way" in ln for ln in out) and "START 0" in out


def test_the_mode_route_checks_each_object_against_the_build():
    """Nothing is ever called through an object the build does not vouch for: readable, its vtable readable through
    both slots, each slot's function in the game's own code - checked at every hand-over, as the game's static
    constructors have not written the vtables yet when the runtime arms (the rig: every object refused at 2 ms);
    the arm checks the port's two slot values and that each object is in the game's memory."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    ok = src[src.index("static int wizm_obj_ok(const unsigned *o)"):]
    ok = ok[:ok.index("\n}\n")]
    assert ok.count("MAP_R | MAP_X | MAP_GAME") == 3 and "wizm_obj_here(o)" in ok   # START, ACTIVE, ENABLE if named
    assert "(e < 0 || maps_has(((const unsigned *)(unsigned long)vt)[e]" in ok
    here = src[src.index("static int wizm_obj_here(const unsigned *o)"):]
    assert "maps_has((unsigned long)o, 4, MAP_R)" in here[:here.index("\n}\n")]
    arm = src[src.index("static void wizm_arm(void)\n{"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'pm_port_value("stock_slot_start", -1) < 0' in arm and "wizm_obj_here(wizm_obj(n, 0))" in arm
    assert arm.index("wizm_obj_here") < arm.index("can |= PM_CAN_GAME_WIZARDS") and "wizm_obj_ok" not in arm
    hand = src[src.index("static int wizm_hand(int n, int how)\n{"):]
    hand = hand[:hand.index("\n}\n")]
    assert hand.index("wizm_obj_ok(o)") < hand.index("wizm_runs(n)") < hand.index("wizm_start(")
    wa = src[src.index("static void wizards_arm(void)"):]
    assert 'if (data("wizard_obj_1")) wizm_arm();' in wa[:wa.index("\n}\n")]


def test_a_start_that_needs_the_mode_enabled_is_enabled_first(tmp_path):
    """Foo Fighters 1.04: a mode's START returns at once unless the player's enabled byte (its rules' qualify) is set,
    so `value wizard_slot_enable` makes the runtime call the mode's own ENABLE first; without it nothing runs."""
    out = _wizm(tmp_path, "needen", "start", "Monster Zero")
    assert "START 0" in out and out[-1] == "S on 00000"
    assert any("its start was called but it does not say it runs" in ln for ln in out)
    out = _wizm(tmp_path, "needen", "enable", "start", "Monster Zero")
    assert out.index("ENABLE 0") < out.index("START 0") and out[-1] == "S on 10000" and "R 2" in out


def test_the_mode_route_refuses_an_object_that_is_not_the_builds(tmp_path):
    out = _wizm(tmp_path, "bad", "0", "start", "Monster Zero", "start", "Terror of Mechagodzilla")
    assert "START 0" not in out and "START 1" in out and out.count("R 0") == 1
    assert any("game wizard 1 (Monster Zero): not handed over - its mode object" in ln for ln in out)


# ---- PAD-473: the plain-C titles' function route (the same harness: each one's start function, its ACTIVE flag) ----
def test_the_function_route_starts_one_by_its_own_start_function(tmp_path):
    out = _wizm(tmp_path, "fnroute", "start", "Monster Zero")
    assert "GO 1 arg 0" in out and "R 2" in out and out[-1] == "S on 10000"
    assert any("game wizard 1 (Monster Zero): started for player 1 (its own start, as the game's rules call it)" in ln
               for ln in out)
    out = _wizm(tmp_path, "fnroute", "arg", "1", "start", "Monster Zero")        # Stranger Things' Season One: r0 = 1
    assert "GO 1 arg 1" in out
    # Metallica's The End of the Line has no flag: its own process (223 here) says it runs
    out = _wizm(tmp_path, "fnroute", "proc", "start", "Terror of Mechagodzilla", "start", "Terror of Mechagodzilla")
    assert out.count("GO 2 arg 0") == 1 and any("already running" in ln for ln in out)


def test_the_function_route_waits_for_a_multiball_of_the_games(tmp_path):
    """Batman 1.14 on the rig: the Gas Attack Multiball's own start started it on top of the Batusi Multiball (both
    returned 1) - its rules ask only that it is not running itself - so the stack's query holds it back."""
    out = _wizm(tmp_path, "fnroute", "start", "Monster Zero", "start", "Terror of Mechagodzilla", "wait", "tick")
    assert out.count("GO 1 arg 0") == 1 and "GO 2 arg 0" not in out and "R 3" in out
    assert any("one of the game's modes is in its way" in ln for ln in out)
    out = _wizm(tmp_path, "fnroute", "on", "3", "start", "Monster Zero", "wait", "tick", "off", "3", "wait", "tick")
    assert out.count("GO 1 arg 0") == 1 and out[-1] == "S on 10000"
    assert out.index("GO 1 arg 0") > out.index("S on 00000")
    assert sum("a multiball is in its way" in ln for ln in out) == 1


def test_the_function_route_tries_again_while_the_games_own_rules_say_not_now(tmp_path):
    out = _wizm(tmp_path, "fnroute", "refuse", "1", "start", "Monster Zero", "wait", "tick", "wait", "tick", "allow", "1",
                "wait", "tick", "wait", "tick")
    assert "R 3" in out and out.count("GO 1 arg 0") == 4 and out[-1] == "S on 10000"
    assert sum("the game's own start would not start it now - started the moment it would, this ball" in ln
               for ln in out) == 1
    out = _wizm(tmp_path, "fnroute", "refuse", "1", "start", "Monster Zero", "ball_end", "wait", "tick", "allow", "1",
                "wait", "tick")
    assert out.count("GO 1 arg 0") == 1
    assert any("the ball ended before nothing of the game's was in its way - not started" in ln for ln in out)


def test_the_function_route_never_starts_one_twice(tmp_path):
    """A start that says it started (1) with its flag not up yet is done with: called again it would start it twice."""
    out = _wizm(tmp_path, "fnroute", "noflag", "start", "Monster Zero", "wait", "tick", "wait", "tick")
    assert out.count("GO 1 arg 0") == 1 and "R 2" in out
    assert any("its start says it started, its flag not yet" in ln for ln in out)
    out = _wizm(tmp_path, "fnroute", "on", "0", "start", "Monster Zero", "light", "Terror of Mechagodzilla")
    assert "GO 1 arg 0" not in out and any("already running" in ln for ln in out)
    assert any("lights it for no start shot of its own - started instead" in ln for ln in out)


def test_the_function_route_arms_only_on_a_whole_port():
    """Every one named needs its start (a site, so its words were checked against the build as the port loaded) and a
    running query: its game flag where the port names the bitmap, or a readable byte of its own."""
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    arm = src[src.index("static void wizf_arm(void)\n{"):]
    arm = arm[:arm.index("\n}\n")]
    assert 'pm_snprintf(key, sizeof key, "wizard_go_%d", n);\n        if (!fn(key))' in arm
    assert "if (!wizf_can_tell(n))" in arm and "hook_veto_n(fn(key), wizf_earned, (unsigned)n, 1)" in arm
    assert arm.index("wizards_n = 0;") < arm.index("can |= PM_CAN_GAME_WIZARDS") and "wiz_route = 3;" in arm
    tell = src[src.index("static int wizf_can_tell(int n)"):]
    tell = tell[:tell.index("\n}\n")]
    assert 'return data("game_flags") != 0;' in tell and 'return fn("proc_exists") != 0;' in tell
    assert "maps_has(run, 1, MAP_R)" in tell
    wa = src[src.index("static void wizards_arm(void)"):]
    assert 'else if (site("wizard_go_1")) wizf_arm();' in wa[:wa.index("\n}\n")]


def test_a_function_route_port_names_its_wizards_and_lights_none():
    port = {"site": {"wizard_go_1": 1, "wizard_go_2": 1}, "data": {"game_flags": 1}, "value": {"wizard_flag_1": 84,
            "wizard_flag_2": 86}, "text": {"wizard_name_1": "Batusi Multiball", "wizard_film_1": "f1",
            "wizard_name_2": "Gas Attack Multiball", "wizard_name_3": "Holy Multiball"}}
    assert MP._wizard_route(port) == 3
    assert MP._game_wizards(port) == (("Batusi Multiball", "f1"), ("Gas Attack Multiball", ""))   # 3 has no start
    assert MP._wizard_lights(port) == ()
    del port["data"]["game_flags"]                       # a flag with no bitmap says nothing
    assert MP._game_wizards(port) == ()
    del port["value"]["wizard_flag_1"]
    port["data"]["wizard_running_1"] = 0x645b18          # a byte of its own
    assert MP._game_wizards(port) == (("Batusi Multiball", "f1"),)
    del port["data"]["wizard_running_1"]
    port["value"]["wizard_proc_1"] = 223                 # its process: only with the game's proc_exists
    assert MP._game_wizards(port) == ()
    port["site"]["proc_exists"] = 1
    assert MP._game_wizards(port) == (("Batusi Multiball", "f1"),)


# ---- the blocks --------------------------------------------------------------------------------
PROG = {"name": "FILMS", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "event", "event": "film_frwl"}, "do": [{"op": "game_wizard", "name": "Ahoy Mr. Bond",
                                                             "how": "start"}]},
    {"hat": {"kind": "event", "event": "film_goldfinger"}, "do": [{"op": "game_wizard",
                                                                   "name": "Goldfinger's Jackpot"}]}]}


def test_the_block_hands_one_over_by_name_and_is_refused_where_there_is_none():
    assert BM.problems(PROG, game_wizards=NAMES) == [] and BM.problems(PROG) == []
    assert BM.problems(PROG, game_wizards=[]) == [
        "Script 1 hands the player a mini-wizard of the game's, which a mode cannot do on this card's game.",
        "Script 2 hands the player a mini-wizard of the game's, which a mode cannot do on this card's game."]
    bad = {**PROG, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "game_wizard", "name": "Nope"}, {"op": "game_wizard", "name": ""},
        {"op": "game_wizard", "name": "Ahoy Mr. Bond", "how": "later"}]}]}
    assert BM.problems(bad, game_wizards=NAMES) == [
        "Script 1 hands the player the game's mini-wizard Nope, which this card's game does not have.",
        "Script 1 hands the player the game's mini-wizard with none chosen.",
        "Script 1 lights the game's mini-wizard or starts it."]
    c = BM.to_c(BM.normalize(PROG), "films")
    assert 'game_wizard("Ahoy Mr. Bond", 1);' in c and 'game_wizard("Goldfinger\'s Jackpot", 0);' in c
    assert "pm_game_wizard_named(name, start ? PM_WIZARD_START : PM_WIZARD_LIGHT)" in c
    assert "pm_game_wizard_named" not in BM.to_c(BM.normalize({**PROG, "scripts": []}), "x")
    init = c[c.index("static void on_init(void)"):]                 # PAD-457: claimed as the mode loads
    init = init[:init.index("\n}\n")]
    assert init.count("pm_game_wizard_claim_named(") == 2
    assert 'pm_game_wizard_claim_named("Ahoy Mr. Bond");' in init
    assert "pm_game_wizard_claim_named" not in BM.to_c(BM.normalize({**PROG, "scripts": []}), "x")


def test_a_blocks_mode_saved_by_an_older_app_is_translated_again_before_a_build(tmp_path):
    """Its C is written only when its blocks are saved: one saved before PAD-457 never claimed its mini-wizards."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    from pinball_decryptor.plugins.stern import mode_write as MW
    project = str(tmp_path)
    slug, src = BM.new_blocks_mode(project, "FILM WIZARDS")
    BM.save(project, slug, PROG)
    fresh = pathlib.Path(src).read_text(encoding="utf-8")
    old = fresh.replace('    pm_game_wizard_claim_named("Ahoy Mr. Bond");\n', "")
    pathlib.Path(src).write_text(old, encoding="utf-8")
    other = tmp_path / "modes" / "mine"                              # a code mode of its own: never touched
    other.mkdir(parents=True)
    (other / "mine.c").write_text("/* mine */\n", encoding="utf-8")
    assert BM.refresh(project) == [slug]
    assert pathlib.Path(src).read_text(encoding="utf-8") == fresh
    assert BM.refresh(project) == []
    pathlib.Path(src).write_text(old, encoding="utf-8")
    assert [s for s, _p in MT.code_mode_sources(project)] == ["film_wizards", "mine"]
    assert pathlib.Path(src).read_text(encoding="utf-8") == fresh
    pathlib.Path(src).write_text(old, encoding="utf-8")
    try:
        MW.code_mode_list(project)
    except MW.ModeWriteError:                                        # "mine" has no assets.json: refreshed first anyway
        pass
    assert pathlib.Path(src).read_text(encoding="utf-8") == fresh
    assert (other / "mine.c").read_text(encoding="utf-8") == "/* mine */\n"
    (tmp_path / "modes" / slug / BM.BLOCKS_FILE).write_text("{not json", encoding="utf-8")
    assert BM.refresh(project) == []                                 # left for the build to report


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    (tmp_path / "films.c").write_text(BM.to_c(BM.normalize(PROG), "films"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "films.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_key_and_the_call():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert re.search(r"\| `game_wizard` \| `light\|start <name>`", doc)
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "## The game's own mini-wizards (PAD-436)" in sdk and "pm_game_wizard" in sdk


# ---- the Modes tab -------------------------------------------------------------------------------
def test_the_tab_offers_them_on_bond_and_greys_them_elsewhere(tmp_path):
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "bond", "james_bond_le-1_06_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["form"]["game_wizard"] == "(none)" and st["form"]["wizard_how"] == "light"
            assert not st["dis"]["wizard"] and "wizard" not in st["reasons"]
            assert st["profile"]["game_wizards"][1] == {"name": "Ahoy Mr. Bond", "film": "From Russia With Love"}
            assert st["profile"]["wizard_shot"] == "Right ramp"
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:start_event", "From Russia With Love done")
            w.call("ui.set", "modes", "f:starts_kind", "event")
            w.call("ui.set", "modes", "f:game_wizard", "Ahoy Mr. Bond")
            w.call("ui.set", "modes", "f:wizard_how", "start")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("wizard_how") == "start")
            saved = json.loads(path.read_text("utf-8"))
            assert saved["game_wizard"] == "Ahoy Mr. Bond" and saved["starts_on"] == "event film_frwl"
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:game_wizard", "(none)")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("game_wizard") == "")
            w.call("modes.new_blocks_mode", "Films")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_wizards_off"] == "" and [x["name"] for x in ch["game_wizards"]] == NAMES
            assert ch["wizard_shot"] == "Right ramp"
        proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["wizard"] and "Godzilla Premium/LE 1.16" in st["reasons"]["wizard"]
            assert st["profile"]["game_wizards"] == []
            w.call("modes.new_blocks_mode", "Films")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_wizards_off"].startswith("Not on this game: The app has not found Godzilla Premium/LE")
    finally:
        preview.enabled = old


def test_the_tab_leaves_the_section_out_on_a_game_with_none(tmp_path, monkeypatch):
    """PAD-473: a game with no mini-wizards of its own has no section and no block for one, as a machine part the
    machine lacks (PAD-420): no yellow reason."""
    from tests.test_webui_modes import _card_project, _project
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    monkeypatch.setattr(preview, "enabled", lambda feature: feature == "modes")
    proj = _card_project(tmp_path / "munsters", "munsters_le-1_28_0.raw")
    with web_app(tmp_path, mfr="stern") as w:
        _project(w, proj)
        w.call("modes.new")
        st = w.state("modes")
        assert st["dis"]["wizard"] and st["hide"].get("wizard") and "wizard" not in st["reasons"]
        w.call("modes.new_blocks_mode", "Films")
        ch = w.state("modes")["code"]["blocks"]["choices"]
        assert "wizard" in ch["absent"] and "has no mini-wizards of its own (Munster Madness" in ch["game_wizards_off"]
