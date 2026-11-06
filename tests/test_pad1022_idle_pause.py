"""PAD-1022: inactivity pauses the game's timers on Guardians of the Galaxy (pad_mode_runtime.c "inactivity pauses the
game's timers", plugins/stern/idle_pause.py).

The game shows ALLOW INACTIVITY TO PAUSE TIMERS and never reads it. Its missions' clocks are their songs; the runtime
holds a song clock by letting the stored song position trail the voice while the player is inactive, and holds the
hurry-ups through the game's shared "are the timers paused" check. The rules are lifted verbatim and run on the host;
the wrap's trampoline for a function whose second word is a `bl` is checked word by word."""
import pathlib
import re

from tests import test_spike2_mode_roster as R

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"
SONG = 44100                                          # a second of a song, in samples

MAIN = r"""
#include <stdio.h>
#define IDLE_JUMP 88200u
@FNS@
int main(void)
{
    unsigned song = 0, player = 0, at = 0, held = 0, waited = 0, h, k;
    /* the setting and the quiet time */
    printf("paused %d %d %d %d\n", idle_is_paused(1, 10000, 4000, 6000), idle_is_paused(1, 9999, 4000, 6000),
           idle_is_paused(0, 60000, 0, 6000), idle_is_paused(1, 5, 10, 6000));
    /* song 7 plays for 3 s with the player active, 4 s inactive, 2 s active: a call every 1/4 s */
    for (k = 1; k <= 36; k++) {
        h = idle_song_step(7, 1, k * 11025u, k > 12 && k <= 28, &song, &player, &at, &held, &waited);
        if (k % 4 == 0) printf("t %u held %u waited %u\n", k / 4, h, waited);
    }
    /* the game plays it again from the table (a jump back to the held place): the voice is the table again */
    h = idle_song_step(7, 1, 5u * 44100u, 0, &song, &player, &at, &held, &waited);
    printf("again held %u waited %u\n", h, waited);
    /* another song, another player, a jump forward each start afresh too */
    idle_song_step(7, 1, 6u * 44100u, 1, &song, &player, &at, &held, &waited);
    printf("inactive waited %u\n", waited);
    printf("song held %u\n", idle_song_step(9, 1, 6u * 44100u + 100u, 1, &song, &player, &at, &held, &waited));
    idle_song_step(9, 1, 7u * 44100u, 1, &song, &player, &at, &held, &waited);
    printf("player held %u\n", idle_song_step(9, 2, 7u * 44100u + 100u, 1, &song, &player, &at, &held, &waited));
    idle_song_step(9, 2, 8u * 44100u, 1, &song, &player, &at, &held, &waited);
    printf("jump held %u\n", idle_song_step(9, 2, 20u * 44100u, 1, &song, &player, &at, &held, &waited));
    /* a 54 s song held at 30 s comes round under the hold: the clock stays at 30 s, then counts on from there */
    song = 4; player = 1; at = 30u * 44100u; held = at; waited = 0;
    for (k = 1; k <= 96; k++)                        /* 24 s of the song in quarters, inactive: 30 s -> 54 s */
        idle_song_step(4, 1, 30u * 44100u + k * 11025u, 1, &song, &player, &at, &held, &waited);
    printf("before %u\n", held);
    printf("round inactive %u\n", idle_song_step(4, 1, 11025u, 1, &song, &player, &at, &held, &waited));
    printf("round active %u\n", idle_song_step(4, 1, 22050u, 0, &song, &player, &at, &held, &waited));
    /* where a bl calls: Guardians Pro 0x41828 and LE 0x41838 (their checks' second words), and a call backwards */
    printf("bl %#x %#x %#x\n", bl_target(0x41828u, 0xeb0634ccu), bl_target(0x41838u, 0xeb07675au),
           bl_target(0x1000u, 0xebfffffeu));
    return 0;
}
"""


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static int idle_is_paused(unsigned adj_value, unsigned long now, unsigned long last, unsigned long quiet)",
        "static unsigned idle_song_step(unsigned song, unsigned player, unsigned at, int inactive, unsigned *last_song,",
        "static unsigned bl_target(unsigned addr, unsigned w)"))
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()


def test_inactive_means_the_setting_on_and_no_score_for_six_seconds(tmp_path):
    out = _run(tmp_path)
    assert out[0] == "paused 1 0 0 0"


def test_a_song_clock_holds_while_inactive_and_runs_on_after(tmp_path):
    out = _run(tmp_path)
    t = {int(l.split()[1]): (int(l.split()[3]), int(l.split()[5])) for l in out if l.startswith("t ")}
    assert t[1] == (SONG, 0) and t[3] == (3 * SONG, 0)              # active: the table is the voice
    assert t[4][0] == t[5][0] == t[6][0] == t[7][0] == 3 * SONG      # inactive 4 s: the clock holds at 3 s
    assert [t[k][1] for k in (4, 5, 6, 7)] == [SONG, 2 * SONG, 3 * SONG, 4 * SONG]
    assert t[8] == (4 * SONG, 4 * SONG) and t[9] == (5 * SONG, 4 * SONG)   # active again: on from where it held


def test_any_break_in_the_song_starts_from_the_voice_again(tmp_path):
    out = _run(tmp_path)
    assert "again held %d waited 0" % (5 * SONG) in out
    assert "inactive waited %d" % SONG in out
    assert "song held %d" % (6 * SONG + 100) in out and "player held %d" % (7 * SONG + 100) in out
    assert "jump held %d" % (20 * SONG) in out


def test_a_song_that_comes_round_under_a_hold_never_gives_the_clock_its_time_back(tmp_path):
    """Yaka Arrow's 54 s song ran out in a 30 s hold on the LE rig, came round to 0, and the mission's clock went back
    up to its full 54 s; it must stay where it held and count on from there."""
    out = _run(tmp_path)
    assert "before %d" % (30 * SONG) in out
    assert "round inactive %d" % (30 * SONG) in out
    assert "round active %d" % (30 * SONG + 11025) in out


def test_bl_target(tmp_path):
    out = _run(tmp_path)
    assert "bl 0x1ceb60 0x21b5a8 0x1000" in out


def _word(src, name):
    m = re.search(r"%s\s*=\s*(0x[0-9a-f]+)u;" % re.escape(name), src)
    return int(m.group(1), 16)


def test_the_wrap_calls_a_moved_bl_itself_and_comes_back():
    """Words 1-5 of the trampoline when the function's second word is a bl (ARM: pc reads 8 ahead)."""
    src = RUNTIME.read_text(encoding="utf-8")
    body = R._lift(src, "static void *hook_wrap_at(unsigned addr, void *wrapper, int opens_with_push)\n{")
    assert "if (i == 1 && opens_with_push && (w & 0xFF000000u) == 0xEB000000u) continue;" in body
    bl = body[body.index("PAD-1022: the second word is a call"):]
    t1, t2, t3 = _word(bl, "t[1]"), _word(bl, "t[2]"), _word(bl, "t[3]")
    base = 0x1000

    def at(k):
        return base + 4 * k
    # t[1] add lr, pc, #imm: lr = (t1 + 8) + imm must be t[3], where the call comes back to
    assert (t1 & 0xFFFFF000) == 0xE28FE000 and at(1) + 8 + (t1 & 0xFF) == at(3)
    # t[2] ldr pc, [pc, #+imm]: loads t[5], the bl's target
    assert (t2 & 0xFFFFF000) == 0xE59FF000 and at(2) + 8 + (t2 & 0xFFF) == at(5)
    # t[3] ldr pc, [pc, #-imm]: loads t[4], addr + 8
    assert (t3 & 0xFFFFF000) == 0xE51FF000 and at(3) + 8 - (t3 & 0xFFF) == at(4)
    assert "t[4] = addr + 8u;" in body and "t[5] = bl_target(addr + 4u, p[1]);" in body


def test_it_arms_before_the_score_gate_and_alone_on_a_card_with_no_modes():
    src = RUNTIME.read_text(encoding="utf-8")
    assert src.index("idle_arm();") < src.index("if (!insider_arm()) return;")
    assert "(clipv_only || sndm_only || pic_only || idle_only) && !attract_wanted() && !coop_wanted()" in src
    arm = R._lift(src, "static void idle_arm(void)")
    assert 'hook(fn("score_add"), on_idle_score)' in arm
    assert 'hook_wrap(fn("song_track")' in arm and 'hook_wrap(fn("timers_paused")' in arm


def _port(name):
    from pinball_decryptor.plugins.stern import mode_project as MP
    return MP.read_port(str(PORTS / name))


def test_both_guardians_builds_name_their_clocks():
    from pinball_decryptor.plugins.stern import idle_pause as IP
    want = {"guardians-1.15.port": ("0x00041824", "0xeb0634cc", "0x000fb518", "0x005f2770", "0x005f2610"),
            "guardians_le-1.15.port": ("0x00041834", "0xeb07675a", "0x000fb758", "0x005f46d8", "0x005f4578")}
    for name, (chk, w1, trk, now, pos) in want.items():
        text = (PORTS / name).read_text(encoding="utf-8")
        assert re.search(r"^site\s+timers_paused\s+%s 0xe92d4008 %s$" % (chk, w1), text, re.M), name
        assert re.search(r"^site\s+song_track\s+%s 0xe92d40f8 0xe30" % trk, text, re.M), name
        assert int(re.search(r"^value\s+song_now_at\s+(0x[0-9a-f]+)$", text, re.M).group(1), 16) + int(pos, 16) \
            == int(now, 16), name
        assert re.search(r"^data\s+song_positions\s+%s$" % pos, text, re.M), name
        assert re.search(r"^value\s+inactive_adj\s+175$", text, re.M), name
        assert IP.port_needs(_port(name)), name


def test_the_titles_that_read_their_setting_are_not_offered_it():
    from pinball_decryptor.plugins.stern import idle_pause as IP
    for name in ("godzilla_le-1.16.port", "turtles_le-1.59.port", "munsters_le-1.28.port"):
        assert not IP.port_needs(_port(name)), name
    offered = [p.name for p in sorted(PORTS.glob("*.port")) if IP.port_needs(_port(p.name))]
    assert offered == ["guardians-1.15.port", "guardians_le-1.15.port"]


def test_the_tick_is_kept_in_the_project(tmp_path):
    from pinball_decryptor.plugins.stern import idle_pause as IP
    assert not IP.load(str(tmp_path))
    assert IP.save(str(tmp_path), True) is False
    assert IP.load(str(tmp_path))
    assert IP.save(str(tmp_path), False) is True
    assert not IP.load(str(tmp_path))


def test_idle_cfg_says_only_when_the_card_has_no_modes():
    from pinball_decryptor.plugins.stern import idle_pause as IP
    assert "only" in IP.cfg_text(True).split() and "only" not in IP.cfg_text(False).split()
    assert "idle on" in IP.cfg_text(False)


def test_idle_cfg_rides_with_the_runtime():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", ROOT / "tools" / "spike2_emu" / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("idle.cfg", 0o100644) in mi.EXTRA_FILES and "idle.cfg" in mi.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        assert "idle.cfg" in (ROOT / "tools" / "spike2_emu" / "modes" / sh).read_text(encoding="utf-8"), sh


def test_mode_write_puts_idle_cfg_beside_the_runtime(tmp_path):
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import mode_project as MP
    prof = next(p for p in MP.profiles().values() if MP.port_path(p).endswith("guardians-1.15.port"))
    plan = MW.ModePlan(project=str(tmp_path), profile=prof, port=MP.port_path(prof), build=None)
    MW.idle_into(plan, str(tmp_path / "scratch"), only=True)
    assert pathlib.Path(plan.idle_file).read_text(encoding="utf-8").splitlines()[1:] == ["idle on", "only"]
    assert any(l.startswith("inactivity pauses timers: ") for l in plan.lines)
    other = next(p for p in MP.profiles().values() if MP.port_path(p).endswith("godzilla_le-1.16.port"))
    plan2 = MW.ModePlan(project=str(tmp_path), profile=other, port=MP.port_path(other), build=None)
    try:
        MW.idle_into(plan2, str(tmp_path / "scratch2"), only=True)
    except MW.ModeWriteError as e:
        assert "pauses its timers by itself" in str(e)
    else:
        raise AssertionError("a game that reads its own setting took idle.cfg")
