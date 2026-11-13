"""PAD-1220: Starts during the co-op intro killed its sound. Each added player has the game's "player added" sound
(Godzilla 1.16 request 1161: priority 196, steal flag), on the intro carrier's bus and over its priority 3, so it took
the bus. The carrier plays at 255 while the intro does: pm_sound_priority (lifted verbatim) must let a request it
changed go past 9 and come back, and still refuse a record it never touched whose priority byte is past 9."""
from tests import test_spike2_mode_roster as R
from tests import test_pad1017_coop_turns as T

MAIN = r"""
#include <stdio.h>
#define PRIO_STOCK_MAX 48
static struct { unsigned request; int pair; } prio_stock[PRIO_STOCK_MAX];
static unsigned char table[20 * 8];
static unsigned count = 8;
static unsigned data(const char *name) { return name[13] == 's' ? (unsigned)(unsigned long)table : (unsigned)(unsigned long)&count; }
@FNS@
int main(void)
{
    int r;
    for (r = 0; r < 8; r++) { table[r * 20 + 8] = 1; table[r * 20 + 16] = 2; }
    table[5 * 20 + 16] = 0xc4; table[5 * 20 + 17] = 1;         /* the game's "player added": 196, steal */
    printf("arm %x\n", pm_sound_priority(3, 3, 0));             /* the carrier at its intro-idle 3 */
    printf("lift %x\n", pm_sound_priority(3, 255, 0));
    printf("read %x\n", pm_sound_priority(3, -1, -1));
    r = pm_sound_priority(3, 3, 0);                             /* (its own statement: printf's order is open) */
    printf("back %x now %d\n", r, table[3 * 20 + 16]);
    printf("untouched %d\n", pm_sound_priority(5, -1, -1));
    return 0;
}
"""

SIGS = ("int pm_sound_priority(unsigned request, int priority, int flags)",)


def _run(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in SIGS)
    # -no-pie: the runtime keeps addresses in 32 bits (the game's ARM), so the table must sit below 4 GB
    return R._host_run(tmp_path, MAIN.replace("@FNS@", fns), flags=("-no-pie",)).splitlines()


def test_the_intro_carrier_goes_to_255_and_back(tmp_path):
    out = _run(tmp_path)
    assert "arm 200" in out and "lift 300" in out and "read ff00" in out and "back ff00 now 3" in out


def test_a_record_never_changed_past_priority_9_is_still_refused(tmp_path):
    assert "untouched -1" in _run(tmp_path)


def test_the_runtime_lifts_the_carrier_while_the_intro_plays():
    src = T.RUNTIME.read_text(encoding="utf-8")
    assert "#define CI_PRIO_PLAYING 255" in src
    body = R._lift(src, "static void ci_sound_start(unsigned long now)")
    assert body.index("CI_PRIO_PLAYING") < body.index("pm_sound(ci.request)")   # raised before the play
    assert src.count("ci_sound_start(now);") == 2                                # both of the intro's routes
