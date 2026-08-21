"""swexercise.py's SAFETY POLICY, which is the half a screenshot cannot see.

REMAINING item 59. The Tech Alerts `CHECK SWITCH #n` rows are the machine's own
no-usage audit, so the fix is to work the switches - and the danger is entirely
in WHICH ones. A run proves that switches moved; it does not prove that the
coin switches stayed still, because a credit awarded by accident looks like a
machine behaving normally. So the refusals get the test.

Two properties are load-bearing and neither is obvious from reading the list:

  * the flagged switches are actually COVERED. turtles_pro's #80/#91 and
    stranger_things' #7..#22 are the sets seen on the glass, and a policy that
    refused any of them would clear nothing while looking busy.
  * a TROUGH switch is exercised the other way round. It rests CLOSED, so
    "press and release" would leave the trough reading six balls throughout
    and produce no edge the audit can see - the same shape as the bug item 20
    was, and the reason plunge.py exists.

FAST AND SYNTHETIC, like the rest of the rig's tests: no WSL, no emulator, no
shared memory. The rows are the real shapes on this disk - turtles_pro's upper
case and godzilla_pro's mixed case - written into a temporary switch_list.txt,
so what is under test is the policy and not the machine.
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


#: turtles_pro's own table, trimmed to one of every class the policy names.
#: `id num node bit name`, exactly the file swtable.py writes.
ROWS = """\
# turtles_pro switch list, from the shim's reading of the game's own table.
1      0     4     0    QR SCANNER STATUS READY
17     1     0     0    DIP 1
25     9     0     8    SERVICE SELECT
33     24    0     23   COIN DOOR INTERLOCK
34     80    1     2    LOCKDOWN BUTTON
35     93    1     8    TICKET NOTCH
36     83    1     11   START BUTTON
37     84    1     12   TOURNAMENT START BUTTON
38     91    1     14   TILT PENDULUM
39     86    1     16   LEFT COIN
45     94    1     22   SLAM TILT
64     10    8     24   RIGHT FLIPPER BUTTON
65     9     8     25   LEFT FLIPPER BUTTON
68     22    8     28   SHOOTER LANE
69     8     8     29   RIGHT SLINGSHOT
70     7     8     30   LEFT SLINGSHOT
71     12    8     31   RIGHT FLIPPER EOS
72     15    8     32   TROUGH 6
77     20    8     37   TROUGH 1
78     21    8     38   TROUGH JAM
"""

#: godzilla_pro names the same switches in mixed case, which is why every
#: comparison in the policy is on name.upper() rather than on the raw string.
ROWS_MIXED = """\
# godzilla_pro switch list.
33     24    0     23   Coin Door Interlock
34     70    1     2    Action Button
66     15    8     32   Trough 6
71     20    8     37   Trough 1
72     21    8     38   Trough Jam
"""


@pytest.fixture()
def sx(tmp_path, monkeypatch):
    """swexercise, pointed at a switch table written here."""
    import swexercise as mod

    def make(text=ROWS):
        p = tmp_path / "switch_list.txt"
        p.write_text(text)
        monkeypatch.setattr(mod.gameinfo, "table", lambda what, name=None: str(p))
        return mod

    return make


def names(entries):
    return {e[3].upper() for e in entries}


def by_name(entries, want):
    for e in entries:
        if e[3].upper() == want:
            return e
    return None


def test_refuses_everything_that_does_more_than_register_usage(sx):
    """Each refusal is a thing that would happen INSTEAD of usage being seen."""
    mod = sx()
    doing, refused = mod.plan()
    for name in ("START BUTTON", "TOURNAMENT START BUTTON", "SLAM TILT",
                 "LEFT COIN", "COIN DOOR INTERLOCK", "DIP 1", "SERVICE SELECT",
                 "QR SCANNER STATUS READY", "TICKET NOTCH"):
        assert name in names(refused), name
        assert name not in names(doing), name


def test_every_refusal_states_a_reason(sx):
    """A row this never clears has to be explainable, or it reads as broken."""
    mod = sx()
    _, refused = mod.plan()
    for sw, num, node, name, rest, why in refused:
        assert why and why.strip(), name


def test_covers_the_switches_actually_seen_flagged(sx):
    """turtles_pro's #80 and #91, and the #7..#22 band from stranger_things."""
    mod = sx()
    doing, _ = mod.plan()
    nums = {e[1] for e in doing}
    assert 80 in nums and 91 in nums          # LOCKDOWN BUTTON, TILT PENDULUM
    for n in (7, 8, 9, 10, 12, 15, 20, 21, 22):
        assert n in nums, "#%d is flagged on stranger_things and is refused" % n


def test_trough_is_exercised_open_then_closed(sx):
    """It rests CLOSED, so press-and-release would produce no edge at all."""
    mod = sx()
    doing, _ = mod.plan()
    for name in ("TROUGH 6", "TROUGH 1", "TROUGH JAM"):
        assert by_name(doing, name)[4] == 1, name
    assert by_name(doing, "SHOOTER LANE")[4] == 0
    assert by_name(doing, "LEFT SLINGSHOT")[4] == 0


def test_policy_is_case_insensitive(sx):
    """godzilla_pro writes `Trough 6` and `Coin Door Interlock`."""
    mod = sx(ROWS_MIXED)
    doing, refused = mod.plan()
    assert "COIN DOOR INTERLOCK" in names(refused)
    assert by_name(doing, "TROUGH 6")[4] == 1
    assert by_name(doing, "TROUGH JAM")[4] == 1
    assert "ACTION BUTTON" in names(doing)


def test_coins_are_opt_in_and_the_flag_really_opts_in(sx):
    mod = sx()
    assert "LEFT COIN" in names(mod.plan()[1])
    assert "LEFT COIN" in names(mod.plan(coins=True)[0])


def test_only_and_skip_narrow_without_losing_the_reason(sx):
    mod = sx()
    doing, refused = mod.plan(only=["TROUGH *"])
    assert names(doing) == {"TROUGH 6", "TROUGH 1", "TROUGH JAM"}
    assert by_name(refused, "SHOOTER LANE")[5] == "not in --only"
    doing, refused = mod.plan(skip=["*SLINGSHOT"])
    assert "LEFT SLINGSHOT" not in names(doing)
    assert by_name(refused, "LEFT SLINGSHOT")[5] == "in --skip"


def test_a_refusal_beats_an_only(sx):
    """--only is a narrowing, never a way to reach past the safety list."""
    mod = sx()
    doing, refused = mod.plan(only=["*"])
    assert "SLAM TILT" not in names(doing)
    assert "START BUTTON" not in names(doing)
