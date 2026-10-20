"""PAD-643 (luvthatapex, James Bond LE): a mode's challenge ball is launched for the player - once its start clip is
over, a set time after it starts, or by the player - and the game's own ball-start work that it leaves out of every
challenge game (Bond's skill shot: the left flipper button's loop through the top control gate at the launch) runs in a
mode's challenge game as at any other ball's start (MODE_SDK.md "A mode in the game's Challenge list").

What is worth failing on:
  * THE FINDER READS EACH BUILD: the framework's launch-button handler (one, with its two auto plunger flags) on every
    build with challenges, Bond's skill-shot handler on Bond LE / Pro only - and the shipped ports carry them.
  * WHEN THE LAUNCH IS DUE, FROM THE STATE ALONE: the clip setting waits for the start clip, a time waits that long,
    the player's never launches.
  * THE SETTING GETS THERE: the mode file's `challenge_launch`, the Modes tab's spec, the blocks' hat.
"""
import os
import pathlib
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portchallenge as PC
from pinball_decryptor.plugins.stern import portgen as G

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
PORTS = SDK / "ports"
ELVES = next((d for d in (os.environ.get("PAD_ELVES", ""), r"C:\tmp\PAD-619\elves", "/mnt/c/tmp/PAD-619/elves")
              if d and os.path.isdir(d)), None)
CHALLENGE_PORTS = sorted(p.stem for p in PORTS.glob("*.port")
                         if "challenge_on_flag" in MP.read_port(str(p))["value"])


def _host():
    from tests import test_spike2_mode_roster as R
    return R


# ---- the ports --------------------------------------------------------------------------------
@pytest.mark.parametrize("key", CHALLENGE_PORTS)
def test_every_challenge_port_names_the_launch_and_its_flags(key):
    port = MP.read_port(str(PORTS / ("%s.port" % key)))
    assert "ball_launch" in port["site"], key
    ball, wait = int(port["value"]["ball_launch_flag"]), int(port["value"]["ball_launch_wait_flag"])
    assert wait == ball + 1 and 11 <= ball <= 12, key                  # FG_MBDEV_AUTO_PLUNGER_BALL_IN_DEVICE, _PLAYER_CONTROL
    plain = sorted(k for k in port["site"] if k.startswith("challenge_plain_"))
    assert plain == (["challenge_plain_0"] if key.startswith("james_bond_") else []), key


def test_bond_le_names_the_handlers_proven_in_the_emulator():
    port = MP.read_port(str(PORTS / "james_bond_le-1.06.port"))
    assert port["site"]["ball_launch"][0] == 0x3F382C
    assert port["site"]["challenge_plain_0"][0] == 0x18DD50


@pytest.mark.parametrize("key", CHALLENGE_PORTS)
def test_the_ports_carry_what_the_finder_reads_off_the_game(key):
    elf = os.path.join(ELVES or "", key + ".elf")
    if not ELVES or not os.path.isfile(elf):
        pytest.skip("the game program is not on this machine")
    e = PC.Elf(elf)
    names = PC.flag_names(e)
    lines = PC.launch_lines(e, names) + PC.plain_lines(e, names, names.index("FG_PLAYER_CHALLENGE_MODE_ACTIVE"))
    assert [line for line in lines if not line.startswith("#")][:1], key
    assert [line for line in PC.missing_from(lines, (PORTS / ("%s.port" % key)).read_text(encoding="utf-8"))
            if not line.startswith("#")] == [], key


def test_the_lines_are_the_builds_own_never_a_references():
    for key, rest in (("site", "ball_launch 0x1 0x2 0x3"), ("value", "ball_launch_flag 12"),
                      ("value", "ball_launch_wait_flag 13"), ("site", "challenge_plain_0 0x1 0x2 0x3")):
        assert G.generated(key, rest), rest


def test_the_finder_wants_one_launch_handler_of_the_shape():
    def elf(words):
        return type("E", (), {"words": tuple(words), "text_va": 0x10000})()
    names = ["FG_%d" % i for i in range(20)]
    names[12], names[13] = "FG_MBDEV_AUTO_PLUNGER_BALL_IN_DEVICE", "FG_MBDEV_AUTO_PLUNGER_PLAYER_CONTROL"
    # Bond LE 0x3f382c, its first 28 words
    fn = [0xE92D4010, 0xE30B44D4, 0xE3404089, 0xE24DD008, 0xE1D401B4, 0xE3500000, 0x1A000002, 0xE3A00001,
          0xE28DD008, 0xE8BD8010, 0xE28D1007, 0xEB000000, 0xE3A0000D, 0xEB000000, 0xE3500000, 0x1A000005,
          0xE5DD3007, 0xE3530000, 0x1A000002, 0xE3A0000C, 0xEB000000, 0xE3500000, 0x0AFFFFEF, 0xE3A01000,
          0xE1D401B4, 0xE1A03001, 0xE3A02008, 0xEB000000]
    lines = PC.launch_lines(elf([0] * 4 + fn + [0] * 40), names)
    assert lines[1:] == ["site  ball_launch         0x00010010 0xe92d4010 0xe30b44d4",
                         "value ball_launch_flag       12", "value ball_launch_wait_flag  13"]
    assert PC.launch_lines(elf(fn + fn + [0] * 40), names) == []               # two of them: not the one
    assert PC.launch_lines(elf([0] * 4 + fn + [0] * 40), names[:12]) == []    # no auto plunger flags


# ---- the runtime --------------------------------------------------------------------------------
def test_the_launch_is_due_after_the_start_clip_or_the_set_time_never_for_the_player(tmp_path):
    R = _host()
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    defines = "\n".join(line for line in src.splitlines() if line.startswith("#define LAUNCH_"))
    code = "#include <stdio.h>\n" + defines + "\n" + R._lift(src, "static int launch_due(int how, unsigned long since, int clip_on)") + """
int main(void)
{
    static const int how[] = { -1, 0, 3000 };
    static const unsigned long at[] = { 0, 1000, 1499, 1500, 2999, 3000, 29999, 30000 };
    unsigned h, t, c;
    for (h = 0; h < 3; h++) for (t = 0; t < 8; t++) for (c = 0; c < 2; c++)
        printf("%d,%lu,%u:%d\\n", how[h], at[t], c, launch_due(how[h], at[t], (int)c));
    return 0;
}
"""
    out = dict(line.split(":") for line in R._host_run(tmp_path, code).split())
    due = {k for k, v in out.items() if v == "1"}
    assert not {k for k in due if k.startswith("-1,")}                                   # the player launches it
    assert {k for k in due if k.startswith("0,")} == {"0,1500,0", "0,2999,0", "0,3000,0", "0,29999,0",
                                                      "0,30000,0", "0,30000,1"}      # the clip over (30 s at most)
    assert {k for k in due if k.startswith("3000,")} == {"3000,3000,0", "3000,3000,1", "3000,29999,0",
                                                         "3000,29999,1", "3000,30000,0", "3000,30000,1"}


def test_the_runtime_launches_from_the_tick_and_wraps_the_plain_handlers():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    tick = src[src.index("static void on_tick(unsigned *r)"):]
    tick = tick[:tick.index("\n}\n")]
    assert "launch_tick();" in tick
    began = src[src.index("static void chg_began(void)\n{"):]
    began = began[:began.index("\n}\n")]
    assert "launch_began();" in began
    arm = src[src.index("static void plain_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    assert "hook_wrap(fn(key), (void *)plain_wraps[k])" in arm
    call = src[src.index("static unsigned plain_call("):]
    call = call[:call.index("\n}\n")]
    # the challenge flag cleared for the game's call only, and only in a mode's challenge game
    assert call.index("if (!chg_ours_now()) return plain_orig[k](a, b, c, d);") < call.index("game_flag_clear(on);") \
        < call.index("ret = plain_orig[k](a, b, c, d);") < call.index("game_flag_set(on);")
    assert "challenges_n || site(\"challenge_menu\")) plain_arm();" in src
    for name in ("int pm_challenge_launch(unsigned slot, int ms);", "#define PM_LAUNCH_PLAYER  (-1)"):
        assert name in (SDK / "pad_mode.h").read_text(encoding="utf-8")


# ---- the mode file -------------------------------------------------------------------------------
HARNESS_EXTRA = r"""
static int (*ch_claimed[32])(unsigned);
int pm_challenge_claim(unsigned slot, int (*f)(unsigned)) { if (slot >= 5) return 0; ch_claimed[slot] = f; printf("CHCLAIM %u\n", slot); return 1; }
void pm_challenge_release(unsigned slot) { if (slot < 32) ch_claimed[slot] = 0; printf("CHRELEASE %u\n", slot); }
const char *pm_challenge_name(unsigned slot) { return slot == 16 ? "OWN" : slot < 5 ? "Ahoy Mr. Bond" : 0; }
int pm_challenge_menu(void) { return 1; }
int pm_challenge_title(unsigned slot, const char *w) { printf("CHTITLE %u %s\n", slot, w); return 1; }
int pm_challenge_add(const char *w, int (*f)(unsigned)) { ch_claimed[16] = f; printf("CHADD %s\n", w); return 16; }
int pm_challenge_launch(unsigned slot, int ms) { printf("CHLAUNCH %u %d\n", slot, ms); return 1; }
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    R = _host()
    cc = R._cc()
    d = tmp_path_factory.mktemp("launch")
    text = R.HARNESS.replace("int main(int argc, char **argv)", HARNESS_EXTRA + "\nint main(int argc, char **argv)")
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


CHALLENGE_ONLY = "name YOLT\nchallenge 1\nseconds 30\nshots 0x00000004\naward 1000000\n"


@pytest.mark.parametrize("line,ms", [("", 0), ("challenge_launch clip\n", 0), ("challenge_launch player\n", -1),
                                     ("challenge_launch 6\n", 6000), ("challenge_launch 600\n", 60000)])
def test_a_mode_file_says_who_launches_its_challenge_ball(harness, tmp_path, line, ms):
    out = _host()._run(harness, tmp_path, CHALLENGE_ONLY + line)
    assert "CHCLAIM 1" in out and ("CHLAUNCH 1 %d" % ms) in out, out
    out = _host()._run(harness, tmp_path, CHALLENGE_ONLY.replace("challenge 1", "challenge new") + line)
    assert ("CHLAUNCH 16 %d" % ms) in out, out


# ---- the Modes tab's spec, and the blocks --------------------------------------------------------
LE = MP.profile_from_port(str(PORTS / "james_bond_le-1.06.port"))


def _lines(**kw):
    spec = MP.blank_spec(LE)
    for k, v in kw.items():
        setattr(spec, k, v)
    return [line for line in MP.runtime_cfg(spec, "ch").splitlines() if line and not line.startswith("#")]


def test_the_form_writes_the_launch_only_when_it_is_not_the_start_clip():
    assert not [l for l in _lines(starts_on="challenge", challenge=1) if l.startswith("challenge_launch")]
    assert "challenge_launch player" in _lines(starts_on="challenge", challenge=1, challenge_launch=-1)
    assert "challenge_launch 6" in _lines(starts_on="challenge", challenge=MP.CHALLENGE_NEW, challenge_launch=6000)
    assert not [l for l in _lines(challenge=1, challenge_launch=-1) if l.startswith("challenge")]   # starts on a shot


YOLT = {"name": "YOLT WIZARD", "seconds": 30, "scripts": [
    {"hat": {"kind": "challenge", "challenge": "Ahoy Mr. Bond"}, "do": [{"op": "start_mode"}]},
    {"hat": {"kind": "challenge", "challenge": BM.CHALLENGE_NEW, "launch": "player"}, "do": [{"op": "start_mode"}]}]}


def test_the_blocks_hat_says_who_launches_and_the_c_tells_the_runtime():
    assert [BM.challenge_launch_ms(h) for h in ({}, {"launch": "clip"}, {"launch": "player"}, {"launch": "6"},
                                                 {"launch": "99"})] == [0, 0, -1, 6000, 60000]
    c = BM.to_c(YOLT, "yolt")
    assert "static const int CHALLENGE_LAUNCH[2] = { 0, -1 };" in c
    init = c[c.index("static void on_init(void)"):]
    init = init[:init.index("\n}\n")]
    assert init.count("pm_challenge_launch((unsigned)CHALLENGE_AT[i], CHALLENGE_LAUNCH[i]);") == 2
    challenges = ["Ahoy Mr. Bond", BM.CHALLENGE_NEW]
    assert BM.problems(YOLT, challenges=challenges) == []
    bad = {"name": "Y", "seconds": 30, "scripts": [
        {"hat": {"kind": "challenge", "challenge": "Ahoy Mr. Bond", "launch": "later"}, "do": [{"op": "start_mode"}]}]}
    assert BM.problems(bad, challenges=challenges) == [
        "Script 1's ball launch must be when its start clip is over, by the player, or 1 to 60 seconds after it starts."]
