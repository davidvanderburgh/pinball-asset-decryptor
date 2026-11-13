"""PAD-1221: a Start press during the co-op intro adds a player with no sound (pad_mode_runtime.c ci_join_cut,
ci_quiet, ci_start_poll). Every teammate's pick holding their serve, this ticket's other half, is PAD-1215's
(tests/test_pad1215_coop_pick_holds_serve.py)."""
from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

RUNTIME = T.RUNTIME


JOIN_MAIN = r"""
#include <stdio.h>
#define BUS_MUSIC_BIT 0x01u
@FN@
int main(void)
{
    printf("%d %d %d %d %d\n",
           ci_join_cut(0x2, 0, 5000),             /* no Start pressed: faded as before */
           ci_join_cut(0x2, 1001 | 1, 1550),      /* a callout 0.55 s after a Start: cut */
           ci_join_cut(0x1, 1001 | 1, 1550),      /* music: faded, to come back after the intro */
           ci_join_cut(0x4, 1001 | 1, 3999),      /* still inside the 3 s */
           ci_join_cut(0x2, 1001 | 1, 4001));     /* past it: faded */
    return 0;
}
"""


def test_a_sound_at_a_start_press_in_the_intro_is_cut_not_faded(tmp_path):
    """PAD-1221: "ANY ADDITIONAL START BUTTON PRESSES ADD PLAYERS BUT DO NOT PLAY ANY CALLOUTS OR AUDIO"."""
    src = RUNTIME.read_text(encoding="utf-8")
    fn = "#define CI_JOIN_CUT_MS 3000ul\n" + R._lift(src, "static int ci_join_cut(unsigned bus, unsigned long join_at, unsigned long now)")
    assert R._host_run(tmp_path, JOIN_MAIN.replace("@FN@", fn)).split() == ["0", "1", "0", "1", "0"]
    assert "ci.join_at = pm_ms() | 1ul;" in R._lift(src, "static void ci_start_poll(int formed)")
    assert "ci_join_cut(buses[i], ci.join_at, pm_ms())" in R._lift(src, "static void ci_quiet(void)")
