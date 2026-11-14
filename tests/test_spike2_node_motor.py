"""hwshim.c's node-board motor: the car john_wick_le screeched for (PAD-237).

David, 2026-09-01: "when i start a game, i continually hear car tire screeches.
I believe this is because the CarMec is supposed to move into position when
the game starts, and it is not getting the feedback that it needs."

The car is a motor the NODE BOARD runs. The game configures it (cmd 51: which
input is the stop switch at each end), sends it to an end (cmd 53 or 54) and
polls the board (cmd 52) until that end's switch reads made. Nothing moved the
switches and the reply to cmd 52 said both ends were made at once, so the game
sent the move again every ~0.9 s for ever - and every send plays the screech.

hwshim.c now plays the car: motor_note() reads the config and the moves off
the wire, motor_tick() lands the car at the end it was sent to. This compiles
those REAL functions out of hwshim.c (the text is extracted, never copied here)
with the switch write and the clock stubbed, and feeds them the frames
john_wick_le 1.01.0 actually sent (rig 2 trace, 2026-09-27). What is worth
failing on:

  * WHICH END IS WHICH. cmd 53 must stop on the config's FIRST switch (CAR
    MOTOR HOME, input 4) and cmd 54 on the SECOND (CAR MOTOR AWAY, input 3).
    Measured on the rig: a reply showing HOME made ended the 53 retries and
    AWAY made the 54 ones. Swapped, the car goes to the wrong end and the game
    retries exactly as before.
  * THE END IT LEAVES OPENS AT ONCE, the end it is sent to closes only after
    the travel time. A car at both ends at once is the state that caused this.
  * A RE-SEND WHILE TRAVELLING IS NOT A NEW MOVE. The game repeats the command
    while the car has not arrived; restarting the clock on each would mean it
    never arrives if the travel time were ever longer than the repeat.
  * PAD_NB_MOTOR=0 moves nothing, which is the comparison run's switch.

Skipped where there is no C compiler, which is most Windows checkouts; it runs
in WSL and anywhere with cc/gcc, which is where the shim is built anyway.
"""
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present"),
    pytest.mark.skipif(not CC, reason="no C compiler on this host"),
]

#: john_wick_le 1.01.0, node 9, as sent (PAD_NB_TRACE=1, 2026-09-27).
CONFIG = "8915510044430f000000d051520000800000000000008800"   # cmd 51, motor 0
HOME = "89075300fa14c8004700"                                  # cmd 53
AWAY = "89075400fa14c8004600"                                  # cmd 54
#: The same config on motor 1 of node 10, to see nothing is pinned to 9/0.
OTHER = "8a15510145420f000000d051520000800000000000008700"


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _extract(name):
    """One static function's text, brace-counted out of hwshim.c.

    The DEFINITION, not the forward declaration above it: a match with a `;`
    before its first `{` is a prototype and is skipped.
    """
    src = _src()
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in hwshim.c - did it get renamed?" % name
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _state():
    """The model's own declarations: #define NB_MOTORS .. the nb_motors array."""
    src = _src()
    m = re.search(r"^#define NB_MOTORS.*?^static struct nb_motor nb_motors\[.*?;$",
                  src, re.M | re.S)
    assert m, "the motor state declarations moved - update this test"
    return m.group(0)


HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char nb_motor_cfg[64];
static unsigned long now_ms;
static unsigned long pad_ms(void) { return now_ms; }
static void logmsg(const char *s) { (void)s; }
static void motor_switch(unsigned nid, int bit, int made)
{
    printf("E %%lu %%u %%d %%d\n", now_ms, nid, bit, made ? 1 : 0);
}

%s

int main(int argc, char **argv)
{
    int a;
    for (a = 1; a < argc; a++) {
        const char *s = argv[a];
        if (s[0] == 't') {                  /* t<ms>:<node> - clock, then tick */
            char *e;
            now_ms = strtoul(s + 1, &e, 10);
            motor_tick((unsigned)strtoul(e + 1, 0, 10));
        } else if (s[0] == 'r') {           /* r<node> - does it say its count */
            printf("R %%lu %%d\n", now_ms, nb_rx_count_says((unsigned)atoi(s + 1)));
        } else if (s[0] == 's') {           /* s<node>:<motor> - a cmd 52 reply */
            char *e;
            unsigned nid = (unsigned)strtoul(s + 1, &e, 10);
            unsigned char r[4] = {0xee, 0xee, 0xee, 0xee};
            if (motor_status(nid, (unsigned)strtoul(e + 1, 0, 10), r))
                printf("S %%lu %%02x%%02x%%02x%%02x\n", now_ms, r[0], r[1], r[2], r[3]);
            else
                printf("S %%lu none\n", now_ms);
        } else {                            /* f<hex> - a frame on the wire   */
            unsigned char f[64];
            int n = 0;
            s++;
            while (s[0] && s[1] && n < 64) {
                char t[3]; t[0] = s[0]; t[1] = s[1]; t[2] = 0;
                f[n++] = (unsigned char)strtoul(t, 0, 16);
                s += 2;
            }
            motor_note(f, n);
        }
    }
    return 0;
}
"""


@pytest.fixture(scope="module")
def cbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("nbmotor")
    body = chr(10).join([_state(), _extract("motor_place_bit"),
                         _extract("nb_motor_on"), _extract("motor_ms"),
                         _extract("motor_say"), _extract("motor_pos"),
                         _extract("motor_status"), _extract("motor_tick"),
                         _extract("motor_note"), _extract("nb_rx_count_on"),
                         _extract("nb_rx_count_says")])
    src = d / "motor.c"
    src.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("motor.exe" if os.name == "nt" else "motor")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(src)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the shim's motor did not compile:\n" + r.stderr
    return str(exe)


def _run(cbin, steps, **env):
    """The switch edges the model makes, as (ms, node, input, made)."""
    e = dict(os.environ)
    e.pop("PAD_NB_MOTOR", None)
    e.pop("PAD_MOTOR_MS", None)
    e.update(env)
    r = subprocess.run([cbin] + steps, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [tuple(int(x) for x in line.split()[1:])
            for line in r.stdout.splitlines() if line.startswith("E ")]


def test_home_is_the_first_stop_switch(cbin):
    """The car powers up at rest on input 4 (CAR MOTOR HOME), the config's
    first stop (PAD-1184), so the game's cmd 53 finds it there: no move."""
    edges = _run(cbin, ["t1000:9", "f" + CONFIG, "f" + HOME,
                        "t1599:9", "t1600:9"])
    assert edges == [(1000, 9, 4, 1)]


def test_away_opens_home_then_makes_away(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t5000:9", "f" + AWAY, "t5599:9", "t5600:9"])
    assert edges == [(0, 9, 4, 1),          # at rest home from the configure
                     (5000, 9, 4, 0),       # leaves home at once
                     (5600, 9, 3, 1)]       # reaches away after the travel


def test_never_at_both_ends(cbin):
    """The fault itself: HOME and AWAY made together is what kept it retrying."""
    steps = ["t0:9", "f" + CONFIG]
    t = 0
    for cmd in [HOME, AWAY, HOME, AWAY, AWAY, HOME]:
        t += 1000
        steps += ["t%d:9" % t, "f" + cmd]
        for dt in (100, 300, 599, 600, 900):
            steps.append("t%d:9" % (t + dt))
    made = {3: 0, 4: 0}
    for _ms, _node, bit, level in _run(cbin, steps):
        made[bit] = level
        assert not (made[3] and made[4]), "the car is at both ends at once"


def test_a_resend_while_travelling_is_not_a_new_move(cbin):
    """The game repeats the move until it sees the car arrive."""
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + AWAY,
                        "t300:9", "f" + AWAY, "t500:9", "f" + AWAY,
                        "t600:9", "t900:9"])
    assert edges == [(0, 9, 4, 1), (0, 9, 4, 0), (600, 9, 3, 1)]


def test_a_move_to_where_it_already_is_moves_nothing(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t2000:9", "f" + HOME, "t3000:9"])
    assert edges == [(0, 9, 4, 1)]


def test_turned_round_mid_travel(cbin):
    """Sent home while still on its way away: it goes home, nothing half-made."""
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "t1000:9", "f" + AWAY, "t1200:9", "f" + HOME,
                        "t1700:9", "t1800:9"])
    assert edges == [(0, 9, 4, 1), (1000, 9, 4, 0), (1800, 9, 4, 1)]


def test_no_config_no_car(cbin):
    """A move for a motor the game never configured is not ours to play."""
    assert _run(cbin, ["t0:9", "f" + HOME, "t5000:9"]) == []


def test_travel_time_knob(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + AWAY, "t249:9", "t250:9"],
                 PAD_MOTOR_MS="250")
    assert edges == [(0, 9, 4, 1), (0, 9, 4, 0), (250, 9, 3, 1)]


def test_off_moves_nothing(cbin):
    edges = _run(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                        "f" + AWAY, "t1200:9"], PAD_NB_MOTOR="0")
    assert edges == []


def test_node_and_motor_come_from_the_frame(cbin):
    """Node 10 motor 1, stops 5 and 2: nothing about john_wick is hard-coded."""
    edges = _run(cbin, ["t0:10", "f" + OTHER,
                        "f8a075401fa14c8004600", "t600:10"])
    assert edges == [(0, 10, 5, 1), (0, 10, 5, 0), (600, 10, 2, 1)]


# ---- PAD-249: an ENCODER motor, james_bond_le's JETPACK --------------------
#
# The game's EncoderMotor (JetPackMotor derives from it) homes the motor with
# cmd 53, sends it to a position with cmd 55, and every tick reads cmd 52's
# reply for THAT motor: bytes 0-1 the position the board counted, byte 2 the
# flags 0x01 moving / 0x08 homed and done / 0x40 fault. A poll with none of
# them set makes it configure and home the motor again from scratch; the zero
# reply did that every tick (20586 x cmd 53 in 40 s from Start). Frames:
# james_bond_le 1.06, node 9, rig 1 trace 2026-09-28.

#: cmd 51: motor 0, home opto input 1, encoder optos inputs 3 and 2.
JB_CONFIG = "89155100410000434200c04241200028010000000000bf00"
JB_HOME = "890753002820e803ea00"                 # cmd 53: speed 40, accel 32
JB_TO_10 = "890955000a0040e80300e400"            # cmd 55: to position 10
JB_TO_0 = "89095500000040e80300ee00"             # cmd 55: to position 0


def _replies(cbin, steps, **env):
    """The cmd 52 replies asked for with s<node>:<motor>, as (ms, hex)."""
    e = dict(os.environ)
    e.pop("PAD_NB_MOTOR", None)
    e.pop("PAD_MOTOR_MS", None)
    e.update(env)
    r = subprocess.run([cbin] + steps, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [(int(line.split()[1]), line.split()[2])
            for line in r.stdout.splitlines() if line.startswith("S ")]


def test_encoder_motor_homes_then_reports_done(cbin):
    """53: moving at once, then homed at position 0 with the home opto made."""
    steps = ["t0:9", "f" + JB_CONFIG, "s9:0", "t1000:9", "f" + JB_HOME,
             "s9:0", "t1300:9", "s9:0", "t1599:9", "s9:0", "t1600:9", "s9:0"]
    assert _replies(cbin, steps) == [
        (0, "00000000"),         # configured, never homed: the game homes it
        (1000, "00000100"),      # moving
        (1300, "00000100"),
        (1599, "00000100"),
        (1600, "00000800"),      # homed and done, position 0
    ]
    assert _run(cbin, steps) == [(1600, 9, 1, 1)]


def test_encoder_motor_goes_to_a_position(cbin):
    """55 to 10: leaves the home opto, the count climbs, then done at 10."""
    steps = ["t0:9", "f" + JB_CONFIG, "f" + JB_HOME, "t600:9",
             "t1000:9", "f" + JB_TO_10, "s9:0", "t1300:9", "s9:0",
             "t1600:9", "s9:0"]
    assert _replies(cbin, steps) == [
        (1000, "00000100"), (1300, "05000100"), (1600, "0a000800")]
    assert _run(cbin, steps) == [(600, 9, 1, 1), (1000, 9, 1, 0)]


def test_encoder_motor_back_to_zero_makes_home_again(cbin):
    steps = ["t0:9", "f" + JB_CONFIG, "f" + JB_HOME, "t600:9",
             "f" + JB_TO_10, "t1200:9", "f" + JB_TO_0, "t1800:9", "s9:0"]
    assert _replies(cbin, steps) == [(1800, "00000800")]
    assert _run(cbin, steps) == [(600, 9, 1, 1), (600, 9, 1, 0),
                                 (1800, 9, 1, 1)]


def test_encoder_motor_resend_is_not_a_new_move(cbin):
    """The game re-sends; the move under way keeps its own clock."""
    steps = ["t0:9", "f" + JB_CONFIG, "f" + JB_HOME, "t300:9", "f" + JB_HOME,
             "t600:9", "s9:0", "f" + JB_TO_10, "t900:9", "f" + JB_TO_10,
             "t1200:9", "s9:0", "f" + JB_TO_10, "t1300:9", "s9:0"]
    assert _replies(cbin, steps) == [
        (600, "00000800"), (1200, "0a000800"), (1300, "0a000800")]


def test_encoder_motor_never_reads_as_a_restart(cbin):
    """Once homed, no poll may show none of moving/done - that is a re-home."""
    steps = ["t0:9", "f" + JB_CONFIG, "f" + JB_HOME]
    t = 0
    for cmd in [None, JB_TO_10, JB_TO_0, JB_HOME, JB_TO_10, JB_TO_10, JB_TO_0]:
        t += 700
        steps += ["t%d:9" % t]
        if cmd:
            steps += ["f" + cmd]
        for dt in (0, 1, 299, 599, 600, 650):
            steps += ["t%d:9" % (t + dt), "s9:0"]
    for ms, hexs in _replies(cbin, steps):
        assert int(hexs[4:6], 16) & 0x09, "a restart reply at %d ms: %s" % (ms, hexs)


def test_end_stop_motor_keeps_its_own_reply(cbin):
    """john_wick's car names no encoder inputs: motor_status leaves it alone."""
    assert _replies(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "t600:9",
                           "s9:0"]) == [(600, "none")]


def test_encoder_motor_off(cbin):
    assert _replies(cbin, ["t0:9", "f" + JB_CONFIG, "f" + JB_HOME, "t600:9",
                           "s9:0"], PAD_NB_MOTOR="0") == [(600, "none")]


def _says(cbin, steps, **env):
    """nb_rx_count_says() at each r<node> step, as (ms, 0/1)."""
    e = dict(os.environ)
    for k in ("PAD_NB_MOTOR", "PAD_MOTOR_MS", "PAD_NB_RXCOUNT"):
        e.pop(k, None)
    e.update(env)
    r = subprocess.run([cbin] + steps, capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return [int(line.split()[2]) for line in r.stdout.splitlines()
            if line.startswith("R ")]


def test_every_board_says_its_frame_count(cbin):
    """PAD-255: the `ff` frame count is answered on every board, so no board is
    re-initialised at each service visit. batman's lamps and attract never
    needed the re-init's cmd 70 - its show is the swelf family the wide
    decoders read (see nb_rx_count in hwshim.c)."""
    assert _says(cbin, ["t0:9", "r9", "f" + JB_CONFIG, "r9", "r10"]) == [1, 1, 1]


def test_enc_keeps_the_encoder_only_gate(cbin):
    """PAD_NB_RXCOUNT=enc is PAD-249's rule, kept for the comparison run: only
    a board with a configured encoder motor says its count."""
    assert _says(cbin, ["t0:9", "r9", "f" + JB_CONFIG, "r9", "r10"],
                 PAD_NB_RXCOUNT="enc") == [0, 1, 0]
    assert _says(cbin, ["t0:9", "f" + CONFIG, "r9"], PAD_NB_RXCOUNT="enc") == [0]
    assert _says(cbin, ["t0:9", "f" + JB_CONFIG, "r9"], PAD_NB_RXCOUNT="enc",
                 PAD_NB_MOTOR="0") == [0]


def test_the_count_follows_the_off_switch(cbin):
    assert _says(cbin, ["t0:9", "f" + JB_CONFIG, "r9"], PAD_NB_RXCOUNT="0") == [0]


# ---- PAD-955: cmd 55 on an END-STOP motor, batman's turntable and crane ----
#
# batman 1.14 (rig 1 trace, 2026-11-03) configures node 9 motor 1 (the crane,
# stops 13 = POS. #1 HOME and 8 = POS. #6 AWAY, positions #2..#5 on inputs
# 12..9) and motor 2 (the turntable, stops 2 = POS. #1 HOME and 4 = POS. #3
# AWAY, POS. #2 on input 3), and in attract sends both a cmd 55 whose byte 4
# names the input to run to (0x40|bit). Ignored (PAD-249's rule), neither ever
# arrived, and the turntable a VPX table follows never turned.

BAT_CRANE = "891551014d480f000000b33534000080000014000000bc00"
BAT_TT = "8915510242440f000000b031320000800000e20400000100"
BAT_TT_POS2 = "89095502430080f401025d00"     # turntable to input 3 (POS. #2)
BAT_CRANE_POS6 = "89095501480080c800028600"  # crane to input 8 = its AWAY stop
BAT_TT_HOME = "89075302fa14c8004700"          # cmd 53 on motor 2


def test_cmd_55_runs_an_end_stop_motor_to_the_input_it_names(cbin):
    """The turntable, at rest HOME at boot, reaches POS. #2 (input 3)."""
    edges = _run(cbin, ["t0:9", "f" + BAT_TT, "t1000:9", "f" + BAT_TT_POS2,
                        "t1599:9", "t1600:9"])
    assert edges == [(0, 9, 2, 1), (1000, 9, 2, 0), (1600, 9, 3, 1)]


def test_cmd_55_leaves_the_stop_it_was_at(cbin):
    """Home, then POS. #2: home opens at once, #2 closes after the travel;
    then home again leaves #2 - never two positions made at once."""
    edges = _run(cbin, ["t0:9", "f" + BAT_TT, "f" + BAT_TT_HOME, "t600:9",
                        "t2000:9", "f" + BAT_TT_POS2, "t2600:9",
                        "t4000:9", "f" + BAT_TT_HOME, "t4600:9"])
    assert edges == [(0, 9, 2, 1),
                     (2000, 9, 2, 0), (2600, 9, 3, 1),
                     (4000, 9, 3, 0), (4600, 9, 2, 1)]


def test_cmd_55_resend_and_already_there_move_nothing(cbin):
    edges = _run(cbin, ["t0:9", "f" + BAT_TT, "f" + BAT_TT_POS2,
                        "t300:9", "f" + BAT_TT_POS2, "t600:9",
                        "t2000:9", "f" + BAT_TT_POS2, "t3000:9"])
    assert edges == [(0, 9, 2, 1), (0, 9, 2, 0), (600, 9, 3, 1)]


def test_cmd_55_to_a_stop_is_that_end(cbin):
    """The crane sent to input 8 is its cmd 54 end: a 54 after it is no move."""
    edges = _run(cbin, ["t0:9", "f" + BAT_CRANE, "f" + BAT_CRANE_POS6,
                        "t600:9", "t2000:9", "f89075401fa14c8004600",
                        "t3000:9"])
    assert edges == [(0, 9, 13, 1), (0, 9, 13, 0), (600, 9, 8, 1)]


def test_cmd_55_keeps_the_off_switch(cbin):
    """PAD_NB_MOTOR=0 still moves nothing and reports nothing."""
    assert _run(cbin, ["t0:9", "f" + BAT_TT, "f" + BAT_TT_POS2, "t600:9"],
                PAD_NB_MOTOR="0") == []
    assert _replies(cbin, ["t0:9", "f" + BAT_CRANE, "f" + BAT_CRANE_POS6,
                           "s9:1"], PAD_NB_MOTOR="0") == [(0, "none")]


# ---- PAD-971: a cmd 55 move reports when it is done, and batman homes ----
#
# batman 1.14 at boot sends the crane a test move to POS. #6 AWAY and the
# turntable one to POS. #2, polls cmd 52 for each, and on status 0x20 sends
# both HOME (`55 01 4d ..` = crane to input 13, `55 02 42 ..` = turntable to
# input 2). The node's raw switch byte never said 0x20, so both stayed at the
# test move: a VPX table following them showed the crane away from home.

BAT_CRANE_HOME = "890955014d0080c800067d00"   # crane to input 13 = POS. #1 HOME


def test_an_end_stop_motor_not_sent_a_55_keeps_the_switch_byte(cbin):
    """john_wick_le's car (53/54 only) is answered as PAD-237 measured it."""
    assert _replies(cbin, ["t0:9", "f" + CONFIG, "f" + HOME, "s9:0"]) == [(0, "none")]
    assert _replies(cbin, ["t0:9", "f" + BAT_CRANE, "s9:1"]) == [(0, "none")]


def test_a_55_move_reports_moving_then_done(cbin):
    steps = ["t0:9", "f" + BAT_CRANE, "f" + BAT_CRANE_POS6, "s9:1",
             "t599:9", "s9:1", "t600:9", "s9:1"]
    assert _replies(cbin, steps) == [(0, "00000100"), (599, "00000100"),
                                     (600, "00002000")]


def test_batman_boot_test_move_then_home(cbin):
    """The test move done, the game's HOME: the crane leaves POS. #6 and makes
    POS. #1 HOME, and says done again."""
    steps = ["t0:9", "f" + BAT_CRANE, "f" + BAT_CRANE_POS6, "t600:9", "s9:1",
             "t650:9", "f" + BAT_CRANE_HOME, "s9:1", "t1250:9", "s9:1"]
    assert _run(cbin, steps) == [(0, 9, 13, 1), (0, 9, 13, 0), (600, 9, 8, 1),
                                 (650, 9, 8, 0), (1250, 9, 13, 1)]
    assert _replies(cbin, steps) == [(600, "00002000"), (650, "00000100"),
                                     (1250, "00002000")]


def test_each_motor_reports_its_own_move(cbin):
    """The crane done while the turntable still runs."""
    steps = ["t0:9", "f" + BAT_CRANE, "f" + BAT_TT, "f" + BAT_CRANE_POS6,
             "t600:9", "f" + BAT_TT_POS2, "s9:1", "s9:2"]
    assert _replies(cbin, steps) == [(600, "00002000"), (600, "00000100")]


def test_cmd_55_without_an_input_flag_is_not_played(cbin):
    """A 55 whose byte 4 names no input (no 0x40) is left alone."""
    assert _run(cbin, ["t0:9", "f" + BAT_TT, "f89095502030080f401025d00",
                       "t5000:9"]) == [(0, 9, 2, 1)]


def test_batman_turntable_is_home_on_a_boot_with_no_test_move(cbin):
    """PAD-1184. batman 1.14 sends the turntable its test move only on a Guided
    Setup boot; on every later boot it configures it and sends nothing. With
    no position switch made it never commanded the turntable again, so no Bat
    Phone hurry-up ever turned it (Mike St P's v1.429.8 log; the rig on a
    second boot). Configured, it is at rest HOME: switch 77's input 2 made,
    the crane's HOME (input 13) the same, and nothing else."""
    assert _run(cbin, ["t0:9", "f" + BAT_CRANE, "f" + BAT_TT,
                       "t60000:9"]) == [(0, 9, 13, 1), (0, 9, 2, 1)]
    # a later move still leaves HOME first, never two places made at once
    assert _run(cbin, ["t0:9", "f" + BAT_TT, "t9000:9", "f" + BAT_TT_POS2,
                       "t9600:9"]) == [(0, 9, 2, 1), (9000, 9, 2, 0),
                                       (9600, 9, 3, 1)]
