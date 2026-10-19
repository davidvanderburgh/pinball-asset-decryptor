"""PAD-615: a mode in the game's Challenge list - Stern's Player Challenge game (one ball, picked as the game starts or
set by the service menu's Default Game Mode) starting a mode of ours in place of one of the game's own challenges.
James Bond LE/Pro 1.06 and Stranger Things 1.13 / LE 1.12 / LE 1.13 name their challenges (MODE_SDK.md "A mode in
the game's Challenge list"); emulator-proven on all five (``mode_project.CHALLENGE_PROVEN``).

What is worth failing on:
  * THE FINDER READS THE GAME: each named challenge's own ball-start handler, by its shape, in the flags' order.
  * ONLY THE PICK STARTS IT: `challenge <n>` in the trigger's place; the blocks hat claims the challenge as the mode
    loads and runs its script on the tick after the pick, never inside the game's handler.
  * ONLY WHERE PROVEN, AND NOWHERE ELSE: a game with no challenge list shows no such start.
  * THE RUNTIME TAKES A PICK ONLY IN A CHALLENGE GAME WITH THAT PICK; a mode file's claim, pick and lapse.
"""
import json
import os
import pathlib
import re
import struct
import subprocess
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portchallenge as PC

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
BOND = ("Chaos at Crab Key", "Ahoy Mr. Bond", "Goldfinger's Jackpot", "Duel on the Disco Volante",
        "Her Majesty's Secret Service")
ST = ("Demogorgon", "Send It Back", "Light the Fire", "Final Showdown")
PORTS = {"james_bond_le-1.06": BOND, "james_bond_pro-1.06": BOND, "stranger_things-1.13": ST,
         "stranger_things_le-1.12": ST, "stranger_things_le-1.13": ST}

LE = MP.profile_from_port(str(SDK / "ports" / "james_bond_le-1.06.port"))
STP = MP.profile_from_port(str(SDK / "ports" / "stranger_things-1.13.port"))
GZ = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
UNPROVEN = replace(LE, key="james_bond_le_1_06_challengenot", challenges=(),
                   cannot=tuple(LE.cannot) + MP._challenge_cannot(
                       "james_bond_le-9.99", LE.label, MP.read_port(str(SDK / "ports" / "james_bond_le-1.06.port"))))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, STP, GZ, UNPROVEN):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


# ---- the finder ---------------------------------------------------------------------------
def _arm_bl(at, to):
    return 0xEB000000 | (((to - at - 8) >> 2) & 0xFFFFFF)


def _fake_game(handlers=True, shape_ok=True):
    """A tiny ELF32 game program: an FG_ name table (FG_INVALID first, a challenge game flag and two named
    challenges among others), the "challenge game?" predicate (mov r0, #flag; b <get>) and one ball-start handler
    of the game's shape per named challenge."""
    base = 0x10000
    names = ["FG_INVALID", "FG_A", "FG_PLAYER_CHALLENGE_MODE_ACTIVE", "FG_B", "FG_C", "FG_D", "FG_E",
             "FG_SHARK_ATTACK_CHALLENGE", "FG_HER_MAJESTYS_SECRET_SERVICE_CHALLENGE", "FG_SHARK_ATTACK_CHALLENGE_ACTIVE",
             "FG_F", "FG_G"]
    blob = bytearray(b"\0" * 0x54)                              # ELF header + one program header
    strs = {}
    for n in names:
        strs[n] = base + len(blob)
        blob += n.encode() + b"\0"
    while len(blob) % 4:
        blob += b"\0"
    for n in names:
        blob += struct.pack("<I", strs[n])
    code = base + len(blob)
    words = []

    def at():
        return code + 4 * len(words)
    get = at()
    words += [0xE12FFF1E]                                       # bx lr: the flag get
    pred = at()
    words += [0xE3A00002, 0xEA000000 | (((get - pred - 4 - 8) >> 2) & 0xFFFFFF)]   # mov r0, #2; b get
    starts = []
    for flag in (7, 8):
        if not handlers:
            break
        h = at()
        words += [0xE92D4008, _arm_bl(h + 4, pred) if shape_ok else 0xE1A00000, 0xE3500000, 0x1A000001,
                  0xE3A00001, 0xE8BD8008, 0xE3A00000 | flag]
        words += [_arm_bl(at(), get), 0xE3500000, 0x0AFFFFF8, 0xE3A00001]
        start = 0x20000 + flag * 16
        words += [_arm_bl(at(), start), 0xE3A00001, 0xE8BD8008]
        starts.append((h, start))
    for w in words:
        blob += struct.pack("<I", w)
    struct.pack_into("<4sBBB", blob, 0, b"\x7fELF", 1, 1, 1)
    struct.pack_into("<HHIIIIIHHHHHH", blob, 16, 2, 40, 1, code, 0x34, 0, 0, 0x34, 32, 1, 40, 0, 0)
    struct.pack_into("<8I", blob, 0x34, 1, 0, base, base, len(blob), len(blob), 5, 0x1000)
    return bytes(blob), starts


def test_the_finder_reads_each_named_challenge_handler_in_flag_order():
    data, starts = _fake_game()
    lines, notes = PC.find(data)
    assert notes == []
    assert lines[0] == "value challenge_on_flag   2"
    sites = [l.split() for l in lines if l.startswith("site")]
    assert [s[1] for s in sites] == ["challenge_go_0", "challenge_go_1"]
    assert [int(s[2], 16) for s in sites] == [h for h, _s in starts]
    assert [int(s[3], 16) for s in sites] == [0xE92D4008, 0xE92D4008]     # the words the runtime checks
    assert "value challenge_flag_0  7" in lines and "value challenge_flag_1  8" in lines
    assert "text  challenge_name_0  Shark Attack" in lines
    assert "text  challenge_name_1  Her Majesty's Secret Service" in lines   # not the _ACTIVE flag
    assert any("Shark Attack: its handler starts 0x20070" in l for l in lines)


def test_the_finder_writes_nothing_without_a_list_or_a_handler():
    lines, notes = PC.find(_fake_game(handlers=False)[0])
    assert lines == [] and len(notes) == 2 and "0 handlers of the shape" in notes[0]
    lines, notes = PC.find(_fake_game(shape_ok=False)[0])
    assert lines == []                          # a push not followed by a call of the predicate is not a handler


def test_a_name_reads_as_the_game_says_it():
    assert PC.pretty("CHAOS_AT_CRAB_KEY") == "Chaos at Crab Key"
    assert PC.pretty("AHOY_MR_BOND") == "Ahoy Mr. Bond"
    assert PC.pretty("GOLDFINGERS_JACKPOT") == "Goldfinger's Jackpot"
    assert PC.pretty("DUEL_ON_THE_DISCO_VOLANTE") == "Duel on the Disco Volante"
    assert PC.pretty("LIGHT_THE_FIRE") == "Light the Fire"


# the five builds' game programs, when this machine has them (PAD-481's extracted programs)
FW = [os.environ.get("PAD_FW_GAMES", ""), r"C:\tmp\PAD-481\fw", "/mnt/c/tmp/PAD-481/fw"]
FW_DIR = next((d for d in FW if d and os.path.isdir(d)), None)
GAMES = {"james_bond_le-1.06": "james_bond_le-1_06_0.Release.16G", "james_bond_pro-1.06": "james_bond_pro-1_06_0.Release.16G",
         "stranger_things-1.13": "stranger_things-1_13_0.Release.8G",
         "stranger_things_le-1.12": "stranger_things_le-1_12_0.Release.8G",
         "stranger_things_le-1.13": "stranger_things_le-1_13_0.Release.8G"}


@pytest.mark.parametrize("key", sorted(GAMES))
def test_the_ports_carry_what_the_finder_reads_off_the_game(key):
    game = os.path.join(FW_DIR or "", GAMES[key] + ".sdcard.raw.game")
    if not FW_DIR or not os.path.isfile(game):
        pytest.skip("the game program is not on this machine")
    lines, _notes = PC.find(game)
    port = (SDK / "ports" / ("%s.port" % key)).read_text(encoding="utf-8")
    assert lines and PC.missing_from(lines, port) == []


@pytest.mark.parametrize("key", sorted(PORTS))
def test_each_port_names_its_challenges_in_order(key):
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))
    assert MP._challenges(port) == PORTS[key]
    assert int(port["value"]["challenge_on_flag"]) in (16, 18)          # FG_PLAYER_CHALLENGE_MODE_ACTIVE (LE 1.12: 16)
    flags = [int(port["value"]["challenge_flag_%d" % n]) for n in range(len(PORTS[key]))]
    assert flags == list(range(flags[0], flags[0] + len(flags)))      # one flag each, the game's order
    assert port["data"].get("game_flags")                               # the bitmap the runtime reads them from


# ---- the title profile --------------------------------------------------------------------
def test_the_named_builds_can_and_the_others_say_why_not():
    assert LE.can("challenge") and LE.challenges == BOND
    assert STP.can("challenge") and STP.challenges == ST
    assert not GZ.can("challenge") and GZ.challenges == ()
    assert GZ.why_not("challenge") == ("Godzilla Premium/LE 1.16's Player Challenge mode has no list of challenges a "
                                       "mode of yours can take a place in.")
    assert "has not yet seen a mode of yours start from one in the emulator" in UNPROVEN.why_not("challenge")
    assert not MP.GODZILLA_PRO_1_15.can("challenge")


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    seen = set()
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        if "%s-%s" % (p.game_dir, p.version) in MP.CHALLENGE_PROVEN:
            assert p.can("challenge") and p.challenges, key
            seen.add("%s-%s" % (p.game_dir, p.version))
        else:
            assert not p.can("challenge") and p.label in p.why_not("challenge"), key
    assert seen == set(MP.CHALLENGE_PROVEN) == set(PORTS)


# ---- the mode file, from the form ----------------------------------------------------------
def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "ch").splitlines() if line and not line.startswith("#")]


def test_the_pick_replaces_the_trigger_line():
    lines = _lines(_spec(LE, starts_on="challenge", challenge=1))
    assert "challenge      1" in lines and not [line for line in lines if line.startswith("trigger")]
    assert lines.index("challenge      1") == 1                       # where the trigger was, after the name
    shot = _lines(_spec(LE))
    assert [l for l in shot if l.startswith("trigger")] and not [l for l in shot if l.startswith("challenge")]
    # a challenge left over from a challenge start does nothing once it starts on its shot again
    assert not [l for l in _lines(_spec(LE, challenge=1)) if l.startswith("challenge")]


def test_its_refusals():
    assert MP.validate(_spec(LE, starts_on="challenge", challenge=4)) == []
    assert MP.validate(_spec(STP, starts_on="challenge", challenge=3)) == []
    pick = ["Pick the game's challenge the mode takes the place of."]
    assert MP.validate(_spec(LE, starts_on="challenge")) == pick
    assert MP.validate(_spec(LE, starts_on="challenge", challenge=5)) == pick
    assert MP.validate(_spec(GZ, starts_on="challenge", challenge=0)) == [
        "Starting as one of the game's challenges is not on Godzilla Premium/LE 1.16 yet (Mode says why)."]


def test_it_round_trips_and_a_game_without_a_list_starts_on_its_shot(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="YOLT", starts_on="challenge", challenge=1))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.starts_on, back.challenge) == ("challenge", 1) and MP.starts_on_challenge(back)
    spec = _spec(GZ, starts_on="challenge", challenge=0)
    MP._switch_off_what_it_cannot(spec, GZ)
    assert (spec.starts_on, spec.challenge) == ("shot", -1)


# ---- blocks ---------------------------------------------------------------------------------
YOLT = {"name": "YOLT WIZARD", "seconds": 30, "game_modes": "block", "vars": [], "scripts": [
    {"hat": {"kind": "event", "event": "film_yolt", "when": "any"}, "do": [
        {"op": "light_mode", "shot": "Right ramp exit opto", "insert": "BLOFELD", "color": "#00ff00", "pattern": "solid"}]},
    {"hat": {"kind": "challenge", "challenge": "Ahoy Mr. Bond"}, "do": [{"op": "start_mode"}]},
    {"hat": {"kind": "mode_start"}, "do": [{"op": "log", "text": "YOLT running"}]}]}


def test_a_blocks_challenge_is_checked_against_the_game():
    assert BM.problems(YOLT, challenges=list(BOND)) == []
    assert BM.problems(YOLT, challenges=list(ST)) == [
        "Script 2 waits for the challenge Ahoy Mr. Bond, which this card's game does not have."]
    assert BM.problems(YOLT, challenges=[]) == [
        "Script 2 waits for a challenge to be picked, which a mode cannot take the place of on this card's game."]
    none = json.loads(json.dumps(YOLT))
    none["scripts"][1]["hat"]["challenge"] = ""
    assert BM.problems(none, challenges=list(BOND)) == ["Script 2's When has no challenge chosen."]
    two = json.loads(json.dumps(YOLT))
    two["scripts"].append({"hat": {"kind": "challenge", "challenge": "Ahoy Mr. Bond"}, "do": [{"op": "start_mode"}]})
    assert BM.problems(two, challenges=list(BOND)) == ["Script 4 waits for Ahoy Mr. Bond too: one script per challenge."]
    idle = json.loads(json.dumps(YOLT))
    idle["scripts"][1]["do"] = [{"op": "log", "text": "picked"}]
    assert any("starts nothing: the game's own challenge does not run either" in n for n in BM.notes(idle))
    assert not any("challenge" in n for n in BM.notes(YOLT))


def test_the_blocks_c_claims_as_it_loads_and_runs_the_script_on_the_tick():
    c = BM.to_c(YOLT, "yolt")
    assert 'static const char *const CHALLENGE_NAMES[1] = { "Ahoy Mr. Bond" };' in c
    init = c[c.index("static void on_init(void)"):]
    init = init[:init.index("\n}\n")]
    assert "pm_challenge_claim((unsigned)CHALLENGE_AT[i], on_challenge)" in init
    assert "CHALLENGE_AT[i] = pm_challenge_named(CHALLENGE_NAMES[i]);" in init
    pick = c[c.index("static int on_challenge(unsigned at)"):]
    pick = pick[:pick.index("\n}\n")]
    assert "challenge_picked |= 1u << k;" in pick and "start(" not in pick     # the game's thread only marks it
    tick = c[c.index("static void on_tick(void)"):]
    tick = tick[:tick.index("\n}\n")]
    assert re.search(r"if \(challenge_picked\) \{\s+unsigned picked = challenge_picked;\s+challenge_picked = 0;", tick)
    assert re.search(r"if \(picked & 1u\) \{\s+start\(", tick)
    assert "CHALLENGE" not in BM.to_c({"name": "PLAIN", "scripts": [{"hat": {"kind": "mode_start"}, "do": []}]}, "p")


def test_the_page_offers_the_hat_only_where_the_game_names_challenges():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_blocks.js").read_text(encoding="utf-8")
    assert '...((ch.challenges || []).length ? [{ kind: "challenge", challenge: ch.challenges[0] }] : []),' in js
    assert 'case "challenge":' in js


# ---- the runtime (host-compiled where there is an ELF toolchain; the CI's Linux leg) -----------
def _host():
    from tests import test_spike2_mode_roster as R
    return R


def test_the_runtime_takes_a_pick_only_in_a_challenge_game_with_it(tmp_path):
    R = _host()
    src = R.RUNTIME.read_text(encoding="utf-8")
    code = "#include <stdio.h>\n" + R._lift(src, "static int challenge_takes(int held, int on, int picked)") + """
int main(void)
{
    int held, on, picked;
    for (held = 0; held < 2; held++) for (on = -1; on < 2; on++) for (picked = -1; picked < 2; picked++)
        printf("%d%d%d:%d\\n", held, on + 1, picked + 1, challenge_takes(held, on, picked));
    return 0;
}
"""
    out = R._host_run(tmp_path, code).split()
    took = [line[:3] for line in out if line.endswith(":1")]
    assert took == ["122"]                          # held, a challenge game (1) and that pick (1); -1 = no bitmap


def test_the_runtime_hooks_every_named_handler_and_refuses_with_its_own_1():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    arm = src[src.index("static void challenges_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert "hook_veto_n(fn(key), challenge_veto, n, 1)" in arm
    assert 'pm_port_value("challenge_on_flag", 0) <= 0' in arm and 'data("game_flags")' in arm
    assert "challenges_arm();" in src and "PM_CAN_CHALLENGE ? \" challenges\"" in src


HARNESS_EXTRA = r"""
static int (*ch_claimed[32])(unsigned);
int pm_challenge_claim(unsigned slot, int (*f)(unsigned)) { if (slot >= 5) return 0; ch_claimed[slot] = f; printf("CHCLAIM %u\n", slot); return 1; }
void pm_challenge_release(unsigned slot) { if (slot < 32) ch_claimed[slot] = 0; printf("CHRELEASE %u\n", slot); }
const char *pm_challenge_name(unsigned slot) { return slot == 16 ? "OWN" : slot < 5 ? "Ahoy Mr. Bond" : 0; }
int pm_challenge_menu(void) { return 1; }
int pm_challenge_title(unsigned slot, const char *w) { printf("CHTITLE %u %s\n", slot, w); return 1; }
int pm_challenge_add(const char *w, int (*f)(unsigned)) { ch_claimed[16] = f; printf("CHADD %s\n", w); return 16; }
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    R = _host()
    cc = R._cc()
    d = tmp_path_factory.mktemp("challenge")
    text = R.HARNESS.replace("int main(int argc, char **argv)", HARNESS_EXTRA + "\nint main(int argc, char **argv)")
    text = text.replace('''        } else if (!strcmp(argv[k], "ball_end")) {''', '''        } else if (!strcmp(argv[k], "chpick")) {
            unsigned s = (unsigned)atoi(argv[++k]);
            printf("CHPICK %u -> %d\\n", s, ch_claimed[s] ? ch_claimed[s](s) : -1);
        } else if (!strcmp(argv[k], "ball_end")) {''')
    assert "chpick" in text and "pm_challenge_claim" in text
    (d / "harness.c").write_text(text)
    stubs, _names = R.weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    return _host()._run(harness, tmp_path, cfg, *args)


CHALLENGE_ONLY = "name YOLT\nchallenge 1\nseconds 30\nshots 0x00000004\naward 1000000\n"


def test_a_challenge_needs_no_trigger_and_the_pick_starts_the_mode_on_the_next_tick(harness, tmp_path):
    out = _run(harness, tmp_path, CHALLENGE_ONLY, "chpick", "1", "tick", "2")
    assert "CHCLAIM 1" in out and "YOLT claims challenge 1 (Ahoy Mr. Bond)" in out
    assert "CHPICK 1 -> 1" in out
    head, tail = out.split("CHPICK 1 -> 1", 1)
    assert "START" not in head and "YOLT START (challenge pick)" in tail


def test_a_pick_lapses_when_the_ball_ends_first_and_a_word_claims_nothing(harness, tmp_path):
    out = _run(harness, tmp_path, CHALLENGE_ONLY, "chpick", "1", "ball_end", "tick", "2")
    assert "the ball ended before the challenge pick started" in out and "START" not in out.split("CHPICK", 1)[1]
    for bad in ("-1", "ahoy", "8"):
        out = _run(harness, tmp_path, CHALLENGE_ONLY.replace("challenge 1", "challenge " + bad))
        assert "CHCLAIM" not in out, bad


def test_the_claim_is_released_when_the_file_goes(harness, tmp_path):
    out = _run(harness, tmp_path, CHALLENGE_ONLY, "rm")
    assert "CHCLAIM 1" in out and "CHRELEASE 1" in out


# ---- the docs and the Modes tab ---------------------------------------------------------------
def test_the_docs_say_how():
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "## A mode in the game's Challenge list (PAD-615)" in sdk
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert re.search(r"\| `challenge` \| -1 \|", doc) and re.search(r"\| `challenge` \| `new`, or a challenge 0-7", doc) and "| `challenge_name` |" in doc
    assert "Start it as one of the game's challenges" in (SDK / "MODE_LIMITS.md").read_text(encoding="utf-8")


def test_the_tab_offers_the_challenges_on_bond_and_nothing_elsewhere(tmp_path):
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "bond", "james_bond_le-1_06_0.Release.16G.sdcard.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["profile"]["challenges"] == list(BOND) and st["profile"]["challenge_found"]
            assert not st["dis"]["challenge"] and st["form"]["starts_kind"] == "shot"
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:challenge", "Duel on the Disco Volante")
            w.call("ui.set", "modes", "f:starts_kind", "challenge")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("starts_on") == "challenge")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("challenge") == 3)
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:starts_kind", "shot")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("challenge") == -1)
        proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["profile"]["challenges"] == [] and not st["profile"]["challenge_found"] and st["dis"]["challenge"]
    finally:
        preview.enabled = old


# ---- round 2: our names on the game's start menu, and challenges of our own (Bond LE/Pro 1.06) ------------------
BOND_PORTS = ("james_bond_le-1.06", "james_bond_pro-1.06")


@pytest.mark.parametrize("key", BOND_PORTS)
def test_the_bond_ports_name_the_start_menu(key):
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))
    assert {"challenge_menu", "challenge_menu_pick"} <= set(port["site"])
    v = {k: int(port["value"]["challenge_menu_" + k]) for k in ("list_at", "count_at", "cap", "kind", "caption")}
    assert v == {"list_at": 388, "count_at": 92, "cap": 9, "kind": 3, "caption": 1921}
    words = (SDK / "ports" / ("%s.port" % key)).read_text(encoding="utf-8")
    assert re.search(r"site  challenge_menu      0x[0-9a-f]{8} 0xe2400001 0xe3500005", words)
    assert re.search(r"site  challenge_menu_pick 0x[0-9a-f]{8} 0xe2433001 0xe3530007", words)


def test_the_menu_lines_are_the_builds_own_never_a_references():
    from pinball_decryptor.plugins.stern import portgen as G
    for key, rest in (("site", "challenge_menu  0x1 0x2 0x3"), ("site", "challenge_menu_pick 0x1 0x2 0x3"),
                      ("value", "challenge_menu_cap 9"), ("value", "challenge_menu_list_at 388")):
        assert G.generated(key, rest), rest
    assert PC.menu_lines(PC.Elf(_fake_game()[0])) == []          # a program with no such menu: no lines


def test_bond_has_room_for_two_of_our_own_and_stranger_things_none():
    assert LE.challenge_menu == 2 and STP.challenge_menu == 0
    pro = MP.profile_from_port(str(SDK / "ports" / "james_bond_pro-1.06.port"))
    assert pro.challenge_menu == 2
    assert set(MP.CHALLENGE_MENU_PROVEN) == set(BOND_PORTS)


def test_a_challenge_of_its_own_is_written_as_new_and_refused_where_the_menu_is_not_ours():
    spec = _spec(LE, starts_on="challenge", challenge=MP.CHALLENGE_NEW)
    assert MP.validate(spec) == []
    lines = _lines(spec)
    assert "challenge      new" in lines and not [l for l in lines if l.startswith("trigger")]
    assert MP.validate(_spec(STP, starts_on="challenge", challenge=MP.CHALLENGE_NEW)) == [
        "A challenge of its own is not on Stranger Things 1.13: its start menu is not one the app can add to."]
    spec = _spec(STP, starts_on="challenge", challenge=MP.CHALLENGE_NEW)
    MP._switch_off_what_it_cannot(spec, STP)
    assert (spec.starts_on, spec.challenge) == ("shot", -1)


def test_the_blocks_add_the_mode_or_title_the_challenge_it_takes():
    own = {"name": "YOLT WIZARD", "seconds": 30, "scripts": [
        {"hat": {"kind": "challenge", "challenge": BM.CHALLENGE_NEW}, "do": [{"op": "start_mode"}]}]}
    assert BM.problems(own, challenges=list(BOND) + [BM.CHALLENGE_NEW]) == []
    assert BM.problems(own, challenges=list(ST)) == [
        "Script 1 waits for the challenge A new challenge of its own, which this card's game does not have."]
    c = BM.to_c(own, "yolt")
    assert 'CHALLENGE_NAMES[1] = { "" };' in c
    assert "CHALLENGE_AT[i] = pm_challenge_add(MODE_NAME, on_challenge);" in c
    c = BM.to_c(YOLT, "yolt")
    assert "pm_challenge_title((unsigned)CHALLENGE_AT[i], MODE_NAME);" in c


def test_a_mode_file_adds_its_own_or_names_the_one_it_takes(harness, tmp_path):
    out = _run(harness, tmp_path, CHALLENGE_ONLY.replace("challenge 1", "challenge new"), "chpick", "16", "tick", "2")
    assert "CHADD YOLT" in out and "its own challenge 16 (OWN) is on the game's start menu" in out
    assert "YOLT START (challenge pick)" in out.split("CHPICK 16 -> 1", 1)[1]
    out = _run(harness, tmp_path, CHALLENGE_ONLY.replace("challenge 1", "challenge new") + "challenge_name DIAMONDS\n")
    assert "CHADD DIAMONDS" in out
    out = _run(harness, tmp_path, CHALLENGE_ONLY)
    assert "CHCLAIM 1" in out and "CHTITLE 1 YOLT" in out and "the start menu shows challenge 1 as YOLT" in out


MENU_CONTEXT = r"""
#include <stdio.h>
#include <string.h>
#define N_CHALLENGE 8
#define N_OWN_CHALLENGE 4
static int (*challenge_fn[N_CHALLENGE])(unsigned slot);
static char challenge_title[N_CHALLENGE][40];
static int challenges_n = 5;
static struct { int (*fn)(unsigned slot); const void *by; char name[40]; } own_challenge[N_OWN_CHALLENGE];
static volatile int own_pending = -1;
static long pm_port_value(const char *n, long f)
{
    if (!strcmp(n, "challenge_menu_count_at")) return 92;
    if (!strcmp(n, "challenge_menu_list_at")) return 388;
    if (!strcmp(n, "challenge_menu_cap")) return 9;
    if (!strcmp(n, "challenge_menu_kind")) return 3;
    if (!strcmp(n, "challenge_menu_caption")) return 1921;
    return f;
}
#define say(...) (printf(__VA_ARGS__), putchar('\n'))
static int yes(unsigned s) { (void)s; return 1; }
"""

MENU_MAIN = r"""
int main(int argc, char **argv)
{
    unsigned stack[6 + 200], *r = stack, i, kinds[7] = { 0, 2, 3, 4, 5, 6, 7 };
    unsigned char *fsp = (unsigned char *)(stack + 6);
    int own = argc > 1 ? atoi(argv[1]) : 0, k;
    static const char *names[7] = { "STANDARD", "COMPETITION", "CHAOS", "AHOY", "GF", "DISCO", "HMSS" };
    memset(stack, 0, sizeof stack);
    *(unsigned *)(fsp + 92) = 7;
    for (i = 0; i < 7; i++) {
        *(unsigned *)(fsp + 388 + 12 * i) = kinds[i];
        *(unsigned short *)(fsp + 388 + 12 * i + 4) = i < 2 ? 1914 + i : 1921;
        *(unsigned *)(fsp + 388 + 12 * i + 8) = (unsigned)(unsigned long)names[i];
    }
    *(unsigned *)(fsp + 496) = 0xfeedface;                       /* the next local: must survive */
    challenge_fn[1] = yes; strcpy(challenge_title[1], "DAF WIZARD");
    for (k = 0; k < own; k++) { own_challenge[k].fn = yes; sprintf(own_challenge[k].name, "OWN %d", k); }
    challenge_menu_built(r);
    for (i = 0; i < *(unsigned *)(fsp + 92); i++) {      /* the name field is the game's u32: match it to whose */
        unsigned w = *(unsigned *)(fsp + 388 + 12 * i + 8), n;
        const char *who = "?";
        for (n = 0; n < 7; n++) if (w == (unsigned)(unsigned long)names[n]) who = names[n];
        for (n = 0; n < N_OWN_CHALLENGE; n++) if (w == (unsigned)(unsigned long)own_challenge[n].name) who = own_challenge[n].name;
        if (w == (unsigned)(unsigned long)challenge_title[1]) who = challenge_title[1];
        printf("E %u %u %s\n", *(unsigned *)(fsp + 388 + 12 * i), *(unsigned short *)(fsp + 388 + 12 * i + 4), who);
    }
    printf("NEXT %x\n", *(unsigned *)(fsp + 496));
    r[3] = 0x100 + 1; challenge_menu_picked(r); printf("PICK own %d kind %u\n", own_pending, r[3]);
    r[3] = 4; challenge_menu_picked(r); printf("PICK stock %d kind %u\n", own_pending, r[3]);
    return 0;
}
"""


def _menu(tmp_path, own):
    R = _host()
    src = R.RUNTIME.read_text(encoding="utf-8")
    code = MENU_CONTEXT + "#include <stdlib.h>\n#define CHALLENGE_MENU_KIND 0x100u\n" \
        + "static int challenge_menu_said, challenge_menu_room_said;\n" \
        + R._lift(src, "static void challenge_menu_built(unsigned *r)") + "\n" \
        + R._lift(src, "static void challenge_menu_picked(unsigned *r)") + MENU_MAIN
    return R._host_run(tmp_path, code, args=(str(own),)).splitlines()


def test_the_menu_names_a_taken_challenge_and_appends_ours_within_its_room(tmp_path):
    out = _menu(tmp_path, 2)
    entries = [l for l in out if l.startswith("E ")]
    assert entries[3] == "E 4 1921 DAF WIZARD"                   # Ahoy (kind 4) under the mode's name
    assert entries[7:] == ["E 256 1921 OWN 0", "E 257 1921 OWN 1"]
    assert "NEXT feedface" in out
    assert "PICK own 1 kind 3" in out and "PICK stock -1 kind 4" in out   # ours becomes Crab Key's kind; the game's stays


def test_the_menu_never_writes_past_its_room(tmp_path):
    out = _menu(tmp_path, 4)
    assert len([l for l in out if l.startswith("E ")]) == 9
    assert "NEXT feedface" in out
    assert any("no room for OWN 2" in l for l in out)


def test_the_tab_offers_a_challenge_of_its_own_on_bond(tmp_path):
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "bond", "james_bond_le-1_06_0.Release.16G.sdcard.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["profile"]["challenge_new"] == "A new challenge of its own" and st["profile"]["challenge_room"] == 2
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:challenge", "A new challenge of its own")
            w.call("ui.set", "modes", "f:starts_kind", "challenge")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("challenge") == MP.CHALLENGE_NEW)
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            assert _wait(w, lambda: w.state("modes")["form"]["challenge"] == "A new challenge of its own")
        proj = _card_project(tmp_path / "st", "stranger_things-1_13_0.Release.8G.sdcard.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            assert w.state("modes")["profile"]["challenge_new"] == ""
    finally:
        preview.enabled = old
