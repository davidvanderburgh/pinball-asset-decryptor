"""PAD-687 (luvthatapex, James Bond LE): a ball down the left outlane at the start of a mode's challenge game was saved
EARLY - the game served the new ball while the drained one was still on its way to the trough, so the framework's
balls in play read 2 for about a second. The runtime took that for one of the game's multiballs: BOND VS SUMO ended
("the game's own mode began") and, being the challenge game's mode, ended the ball - flippers dead, game over.

  * TWO BALLS ARE A MULTIBALL ONCE THEY STAY: two or more in play for STOCK_MB_SETTLE_MS (3 s), not at once.
  * THE COUNT IS KEPT EVERY TICK, so a question asked late in a long multiball still says multiball.

Emulator proof (Bond LE 1.06, the reporter's own bon_appetit_copy.c, C:/tmp/PAD-687 run.sh h_before / h_after):
main ended the mode 170 ms after the early save; with this the count went 2 -> 1 in 0.9 s and the mode ran on.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"


def _host():
    from tests import test_spike2_mode_roster as R
    return R


def test_two_balls_count_as_a_multiball_only_once_they_stay(tmp_path):
    R = _host()
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    defines = "\n".join(line for line in src.splitlines() if line.startswith("#define STOCK_MB_SETTLE_MS"))
    code = "#include <stdio.h>\n" + defines + "\n" + R._lift(
        src, "static int balls_multiball(unsigned n, unsigned long now, unsigned long *since)") + """
int main(void)
{
    /* (balls in play, ms): an outlane's early save (2 for 900 ms), then a real multiball from 10 s on */
    static const unsigned n[] = { 1, 2, 2, 1, 1, 2, 2, 2, 2, 1 };
    static const unsigned long at[] = { 1000, 2000, 2900, 3000, 9000, 10000, 12999, 13000, 60000, 61000 };
    unsigned long since = 0;
    unsigned i;
    for (i = 0; i < 10; i++) printf("%lu:%d\\n", at[i], balls_multiball(n[i], at[i], &since));
    return 0;
}
"""
    out = dict(line.split(":") for line in R._host_run(tmp_path, code).split())
    assert {k for k, v in out.items() if v == "1"} == {"13000", "60000"}


def test_the_runtime_keeps_the_count_every_tick_before_the_modes():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = src[src.index("static int stock_balls(unsigned kinds)"):]
    body = body[:body.index("\n}\n")]
    assert "balls_multiball(n, pm_ms(), &two_since)" in body
    assert "n >= 2 &&" not in body
    tick = src[src.index("static void on_tick(unsigned *r)"):]
    assert tick.index("stock_balls_tick();") < tick.index("EACH_MODE(m) if (m->tick)")
