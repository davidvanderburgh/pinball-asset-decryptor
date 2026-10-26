"""PAD-740: Bird One's speech played under a mode's own music (James Bond LE 1.06).

A mode's own music rides Bond LE's music carrier, request 94, which is also Bird One Multiball's music. The game's
music sync asks the sound engine every tick which of its synced songs plays (the engine's "which of these requests
plays", sound_active + 0x40) and runs that song's cue lists against its position: 94's speech cues (1019-1049, "Base
calling Bird One", "8 minutes to interception") played from 55 s into the mode's music. While a request carries a
record of ours (a music swap armed on it, or pointed at a bed of ours), the runtime hands the engine the list without it.
The code is lifted from the runtime and run over a fake swap / bed table.
"""

import pytest

from tests.test_spike2_mode_roster import RUNTIME, _host_run, _lift

MAIN = r"""
#include <stdio.h>
static void say(const char *f, ...) {}
#define SWAPS_MAX 8
static struct { unsigned request; int music; } swaps[SWAPS_MAX];
static volatile int swaps_live;
#define SID_SLOTS 8
static struct { unsigned request; } sid_slot[SID_SLOTS];
%s
%s
static unsigned first(unsigned *r)          /* the engine: the first request of the list it is handed that plays */
{
    const unsigned short *l = (const unsigned short *)(unsigned long)r[0];
    unsigned i;
    for (i = 0; l[i]; i++) if (l[i] == 94 || l[i] == 114) return l[i];
    return 0;
}
static unsigned ask(const unsigned short *songs)
{
    unsigned r[6] = { 0 };
    r[0] = (unsigned)(unsigned long)songs;
    r[5] = 0x19c5e0;
    on_sound_first_active(r);
    return first(r);
}
int main(void)
{
    static const unsigned short songs[] = { 131, 129, 142, 112, 134, 98, 94, 83, 111, 133, 0 };
    static const unsigned short both[] = { 94, 114, 0 };
    static unsigned short many[300];
    unsigned i;
    printf("game's 94: %%u\n", ask(songs));
    swaps[3].request = 94; swaps_live = 1;
    printf("our call on 94: %%u\n", ask(songs));
    swaps[3].music = 1;
    printf("our music on 94: %%u\n", ask(songs));
    printf("and the game's 114: %%u\n", ask(both));
    swaps_live = 0;
    printf("swap over: %%u\n", ask(songs));
    swaps[3].request = 0; sid_slot[2].request = 94;
    printf("our bed on 94: %%u\n", ask(songs));
    for (i = 0; i < 299; i++) many[i] = (unsigned short)(i == 5 ? 94 : 1000 + i);
    printf("a list longer than ours: %%u\n", ask(many));
    return 0;
}
"""


def test_a_carrier_playing_ours_is_not_the_games_song(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    decl = src[src.index("static unsigned short own_on_list[256];"):src.index("static int own_on(unsigned request)")]
    body = _lift(src, "static int own_on(unsigned request)") + "\n" + _lift(src, "static void on_sound_first_active(unsigned *r)")
    out = _host_run(tmp_path, MAIN % (decl, body), flags=("-no-pie", "-fno-pie")).splitlines()
    if not out:
        pytest.skip("this host links above 4 GB even with -no-pie")
    assert out == ["game's 94: 94", "our call on 94: 94", "our music on 94: 0", "and the game's 114: 114", "swap over: 94",
                   "our bed on 94: 0", "a list longer than ours: 94"]


def test_the_engine_ask_is_found_after_sound_active_by_its_shape():
    """sound_active + 0x40 on all 53 newest builds; the runtime checks the six words before it hooks, and hooks it
    with the plain hook (its first word is a literal load, which that hook relocates)"""
    src = RUNTIME.read_text(encoding="utf-8")
    arm = _lift(src, "static void own_on_arm(void)")
    for w in ("0xE59FC000u", "0xE52DE004u", "0xE28CE000u", "0xE1A02000u", "0xE0D230B2u", "0xE3530000u"):
        assert w in arm
    assert 'fn("sound_active")' in arm and "a + 0x40" in arm and "hook(a + 0x40, on_sound_first_active)" in arm
    assert "swaps[free_i].music = priority < 0;" in _lift(src, "int pm_sound_swap(")
    assert "own_on_arm();" in src[src.index("lookup_hooked = 1;\n    own_on_arm();"):]
