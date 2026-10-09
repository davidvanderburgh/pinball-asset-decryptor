"""PAD-484: a Spike 2 sweep, much faster - the game's own clock at k times the wall's, boots off the WSL disk.

David, 2026-10-09: "Need a way of sweeping a spike 2 image much much faster ... Consider how long PAD-420 took to
finish (over 2 days)". Measured on the rig before anything was built: a hidden rig in a game costs about half a core -
the game is WAITING on its own clock (Tech Alerts, ball savers, a 30 s mode), not starved - and a boot's minute or two
went on card reads through 9p under fuse2fs (79-130 s to attract from C:, 23 s from the WSL disk). So:

  * hwshim.c runs every clock the game reads, and every way it waits, k times fast once padspeed.py asks (the padsw
    block's speed_req); a run nobody speeds up takes exactly the old paths;
  * what waits on the HOST (the GL bridge's ring, the swap pacing, the video host's acks) stays on the wall clock;
  * the harness's physical times (a press, a ball's flight, a ball saver waited out) follow the same k;
  * watch.sh asks for PAD_SPEED once the game is in attract, rigbatch.sh --speed asks for every job, and rigbatch
    caches every card on the WSL disk ahead of the rigs.

Measured end to end (Godzilla Pro 1.16, the Modes tab's Check this game): 188 s before, 47 s at 4x, 36 s at 8x.

Source-level checks of the shim (it is ARM and runs under qemu), compiled checks of its clock arithmetic on the host,
and behaviour tests of the host helpers against a stand-in switch block.
"""
import mmap
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _text(*name):
    with open(os.path.join(RIG, *name), encoding="utf8", newline="") as f:
        return f.read()


def _func(src, name):
    """The body of a C function defined at file scope, by name."""
    m = re.search(r"\n[^\n]*\b%s\([^)]*\)\n\{(.*?)\n\}" % re.escape(name), src, re.S)
    assert m, name
    return m.group(1)


def _cfunc(src, name):
    """_func for a definition whose parameters hold parentheses of their own (a function pointer): the first
    `name(` whose next `\\n{` comes before any `;` is the definition."""
    i = 0
    while True:
        i = src.index("%s(" % name, i) + 1
        brace = src.index("\n{", i)
        if ";" not in src[i:brace]:
            return src[brace + 2:src.index("\n}", brace)]


def _sh_func(src, name):
    """A shell function's text, `name() {` to its closing `}` at column 0 or 4."""
    i = src.index("%s() {" % name)
    j = src.index("\n}", i)
    return src[i:j + 2]


# --------------------------------------------------------------------------
# the layout: one block, four copies
# --------------------------------------------------------------------------

def test_the_speed_fields_close_the_block():
    import padsw
    assert padsw.OFF_SPEED_REQ == padsw.OFF_STOP_ACK + 4 == 1112
    assert padsw.OFF_SPEED_NOW == 1116
    assert padsw.SIZE == 1120 <= 4096


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_padsw_h_puts_the_speed_fields_where_python_reads_them(tmp_path):
    import padsw
    src = tmp_path / "layout.c"
    src.write_text('#include <stdio.h>\n#include <stddef.h>\n#include "padsw.h"\n'
                   'int main(void){printf("%zu %zu %zu\\n", '
                   'offsetof(struct padsw_shm, speed_req), offsetof(struct padsw_shm, speed_now), '
                   'sizeof(struct padsw_shm));return 0;}\n')
    exe = tmp_path / "layout"
    subprocess.run(["gcc", "-std=gnu17", "-I", RIG, "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    assert [int(x) for x in out.split()] == [padsw.OFF_SPEED_REQ, padsw.OFF_SPEED_NOW, padsw.SIZE]


def test_the_shims_copy_of_the_block_carries_every_field_up_to_the_speed():
    """hwshim.c is built -nostdlib and keeps its own copy of struct padsw_shm. It had stopped at pause_req; the speed
    sits after the four stop_* fields, so those are in the copy now too, in padsw.h's order."""
    c = _text("hwshim.c")
    s = c[c.index("struct padsw_shm {"):]
    s = s[:s.index("};")]
    order = ["paused_ms", "pause_req", "stop_want", "stop_gen", "stop_n", "stop_ack", "speed_req", "speed_now"]
    at = [s.index(f) for f in order]
    assert at == sorted(at)


# --------------------------------------------------------------------------
# the shim: every way the game waits, and the old path at 1x
# --------------------------------------------------------------------------

#: the time imports of the game and every library it loads (PAD-484's census: libc, librt, glib, gstreamer, libusb,
#: dbus, curl, libstdc++), each one interposed
WAITS = ("clock_gettime", "gettimeofday", "time", "usleep", "nanosleep", "sleep", "clock_nanosleep", "select",
         "pselect", "poll", "ppoll", "syscall", "pthread_cond_timedwait", "timer_create", "timer_settime",
         "timer_gettime", "timer_delete")


def test_every_wait_the_game_imports_is_interposed():
    c = _text("hwshim.c")
    for sym in WAITS:
        assert '__asm__("%s")' % sym in c, sym


def test_a_run_nobody_speeds_up_takes_the_old_path():
    """w_on is set only by a speed other than 1, and until then each interposer is the real call."""
    c = _text("hwshim.c")
    poll = _func(c, "warp_poll")
    assert "if (req != 1000) w_on = 1;" in poll
    assert "if (!w_on || !req) return real_nsl(req, rem);" in _func(c, "shim_nanosleep")
    assert "if (!w_on) return real(s);" in _func(c, "shim_sleep")
    assert "if (!w_on || !tv) return real(n, r, w, e, tv);" in _func(c, "shim_select")
    assert "if (!w_on || ms <= 0) return real(fds, nfds, ms);" in _func(c, "shim_poll")
    assert "if (!w_on || !nv || !pause_clock(clk)) return real_tset(id, flags, nv, ov);" in \
        _func(c, "shim_timer_settime")
    sc = _func(c, "shim_syscall")
    assert sc.index("if (w_on) {") < sc.index("return real(n, a, b, c, d, e, f, g);")
    us = _func(c, "shim_usleep")
    assert "if (w_on) return warp_sleep((long long)us, 0);" in us
    assert us.rstrip().endswith("return real_usleep(us);")
    # the clocks: the speed's branch first, the pause's own lines untouched after it
    cg = _func(c, "shim_clock_gettime")
    assert cg.index("if (w_on && t && pause_clock(clk)) {") < cg.index("r = real(clk, t);")
    assert "pause_clock(clk) && (p = pause_total_ms()) != 0" in cg


def test_a_condvar_wait_is_never_woken_early():
    """One real deadline per wait, and a timeout handed back only when the GAME's clock has reached the game's
    deadline - never a made-up early 0, which only a caller looping on its predicate survives."""
    body = _cfunc(_text("hwshim.c"), "warp_cond_wait")
    assert "for (;;) {" in body
    assert "if (r != 110 /* ETIMEDOUT */ || game_clk_us(clk) >= dl) return r;" in body
    assert "r = 0" not in body
    cw = _func(_text("hwshim.c"), "shim_cond_timedwait")
    assert cw.index("if (w_on) return warp_cond_wait(") < cw.index("ts_add_ms(&dl, p0);")


def test_a_sleep_is_cut_in_slices_and_gives_back_a_signal():
    body = _func(_text("hwshim.c"), "warp_sleep")
    assert "if (r > 50000) r = 50000;" in body
    assert "*__errno_location() == 4 /* EINTR */" in body
    assert "prctl(29 /* PR_SET_TIMERSLACK */, 1, 0, 0, 0);" in body


def test_the_futex_timeouts_glib_and_libstdcxx_pass_are_shrunk():
    body = _func(_text("hwshim.c"), "shim_syscall")
    assert "n == 240 /* futex */ && d" in body
    assert "cmd == 0 /* FUTEX_WAIT: relative */" in body
    assert "cmd == 9 /* FUTEX_WAIT_BITSET: absolute */" in body


def test_a_timer_is_re_armed_when_the_speed_changes():
    c = _text("hwshim.c")
    assert "wt_rearm(was, req);" in _func(c, "warp_poll")
    re_arm = _func(c, "wt_rearm")
    assert "wt_scale(&cur.val, &k.val, was, now);" in re_arm
    assert "us_ts(wt[i].g_iv * 1000LL / now, &k.iv);" in re_arm
    # a nonzero game time never shrinks to the zero that would DISARM a timer
    assert "if (set && us < 1) us = 1;" in _func(c, "wt_scale")


def test_waits_on_the_host_stay_on_the_wall_clock():
    """The swap pacing, the GL ring and the video host's acks wait for the HOST: on the game's clock at 8x the
    bridge's 10 s "host stalled" limit would be 1.25 s, and the picture would be built 8 times as often."""
    egl = _text("eglshim.c")
    assert "extern long long pad_real_us(void) __attribute__((weak));" in egl
    assert "if (pad_real_us) return (unsigned long long)pad_real_us();" in _func(egl, "now_us")
    assert "if (pad_real_sleep_us) pad_real_sleep_us((long long)d);" in egl
    gl = _text("glbridge.c")
    assert "extern void pad_real_sleep_us(long long) __attribute__((weak));" in gl
    assert "usleep(50);\n" not in gl.replace("    else usleep(50);\n", "")
    assert gl.count("host_wait();") == 2
    vid = _text("gstvid.c")
    assert "while (c->ack_gen != gen && spins++ < 3000) pad_real_sleep_us(1000);" in vid
    # ...and the clip's own schedule still reads the game's clock (PAD-204's test asks for the same)
    assert "clock_gettime(1 /* CLOCK_MONOTONIC */, t);" in _func(vid, "vid_us")
    c = _text("hwshim.c")
    assert "return real_clk_us(1);" in _func(c, "pad_real_us")


def _warp_harness():
    """warp_poll and the arithmetic it rests on, lifted out of hwshim.c verbatim, with the clock, the block and the
    two side effects (timers, the answer) stood in for."""
    c = _text("hwshim.c")
    out = [r"""
#include <stdio.h>
#include <stdlib.h>
static long long now_P;                        /* the paused monotonic clock, us */
static unsigned req;                           /* the block's speed_req */
static int rearms, publishes;
static long long warp_P(void) { return now_P; }
static unsigned speed_req_x1000(void) { return req; }
static void wt_rearm(unsigned was, unsigned now) { (void)was; (void)now; rearms++; }
static void speed_publish(unsigned k, unsigned was, long long g) { (void)k; (void)was; (void)g; publishes++; }
"""]
    for decl in ("static volatile unsigned w_seq;", "static long long w_pa, w_d0;",
                 "static volatile unsigned w_k = 1000;", "static volatile int w_on;",
                 "static volatile int w_lock;", "static volatile unsigned w_seen = 1000;"):
        assert decl in c, decl
        out.append(decl)
    for name in ("warp_off", "speed_clamp", "warp_poll", "guard_us", "warp_budget"):
        m = re.search(r"\nstatic [^\n]*\b%s\([^)]*\)\n\{.*?\n\}" % name, c, re.S)
        assert m, name
        out.append(m.group(0))
    return "\n".join(out)


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_the_game_clock_is_continuous_across_a_change_and_never_runs_back(tmp_path):
    src = tmp_path / "warp.c"
    src.write_text(_warp_harness() + r"""
static long long game(void) { return now_P + warp_off(now_P); }
int main(void) {
    now_P = 10000000;                     /* 10 s in, never sped up */
    warp_poll();
    printf("%d %lld %d\n", w_on, game(), rearms);
    req = 4000; now_P = 20000000;         /* 4x asked at 20 s */
    warp_poll();
    printf("%d %lld %u %d %d\n", w_on, game(), w_k, rearms, publishes);
    now_P = 21000000;                     /* one real second later */
    printf("%lld\n", game());
    req = 1000; now_P = 22000000;         /* back to real time */
    { long long before = now_P + warp_off(now_P); warp_poll(); printf("%lld %lld\n", before, game()); }
    now_P = 23000000;
    printf("%lld %d\n", game(), w_on);
    req = 0;                              /* "never asked" reads 1x too */
    warp_poll();
    printf("%u %u %u\n", speed_clamp(50), speed_clamp(100000), w_k);
    return 0;
}
""")
    exe = tmp_path / "warp"
    subprocess.run(["gcc", "-std=gnu17", "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout.split("\n")
    assert out[0] == "0 10000000 0"                  # nothing asked: the real clock, untouched
    assert out[1] == "1 20000000 4000 1 1"           # continuous where it changed; timers re-armed, answer given
    assert out[2] == "24000000"                      # four game seconds per real one
    assert out[3] == "28000000 28000000"             # and continuous going back
    assert out[4] == "29000000 1"                    # one per one again, from where it was (never back)
    assert out[5] == "100 64000 1000"                # x0.1 .. x64; 0 = 1x


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_a_wait_gets_a_kth_of_its_time_and_a_watchdog_its_own(tmp_path):
    """PAD_SPEED_GUARD_MS (5 s): the dispatch loop's 10 s condvar wait is a watchdog (exit 5, PAD-200); at 8x a 1.25 s
    stall in a CPU-bound load would end the game. A wait that long keeps its real length."""
    src = tmp_path / "budget.c"
    src.write_text(_warp_harness() + r"""
int main(void) {
    w_k = 4000;
    printf("%lld %lld %lld %lld\n", warp_budget(1000000), warp_budget(10000000),
           warp_budget(0), warp_budget(-5));
    w_k = 500;                            /* slow motion: twice as long, guarded or not */
    printf("%lld %lld\n", warp_budget(1000000), warp_budget(10000000));
    return 0;
}
""")
    exe = tmp_path / "budget"
    subprocess.run(["gcc", "-std=gnu17", "-o", str(exe), str(src)], check=True)
    env = dict(os.environ)
    env.pop("PAD_SPEED_GUARD_MS", None)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True, env=env).stdout.split("\n")
    assert out[0] == "250000 10000000 0 0"
    assert out[1] == "2000000 20000000"


# --------------------------------------------------------------------------
# the host side: padsw.py, padspeed.py, the helpers
# --------------------------------------------------------------------------

@pytest.fixture
def block(tmp_path):
    import padsw
    p = tmp_path / "padsw"
    b = bytearray(4096)
    struct.pack_into("<I", b, padsw.OFF_MAGIC, padsw.MAGIC)
    p.write_bytes(bytes(b))
    m = padsw.open_block(str(p))
    yield m
    m.close()


def test_the_speed_reads_one_until_the_shim_answers(block):
    import padsw
    assert padsw.speed(block) == 1.0                     # never asked (and an older renderer's block)
    struct.pack_into("<I", block, padsw.OFF_SPEED_NOW, 4000)
    assert padsw.speed(block) == 4.0
    padsw.request_speed(block, 0.5)
    assert struct.unpack_from("<I", block, padsw.OFF_SPEED_REQ)[0] == 500


def test_a_physical_time_is_the_games(block, monkeypatch):
    import padsw
    struct.pack_into("<I", block, padsw.OFF_SPEED_NOW, 4000)
    slept = []
    monkeypatch.setattr(padsw.time, "sleep", slept.append)
    padsw.game_sleep(block, 0.4)
    assert slept == [pytest.approx(0.1)]
    now = [100.0]
    monkeypatch.setattr(padsw.time, "monotonic", lambda: now[0])
    clock = padsw.GameClock(block)
    assert clock.now() == 100.0                          # at 1x it IS time.monotonic()
    now[0] = 101.0
    assert clock.now() == pytest.approx(104.0)           # four game seconds in one real one
    struct.pack_into("<I", block, padsw.OFF_SPEED_NOW, 1000)
    now[0] = 102.0
    assert clock.now() == pytest.approx(105.0)           # never back when it slows


def test_padspeed_asks_and_waits_for_the_answer(block):
    import padsw
    import padspeed
    assert padspeed.parse_speed("4") == 4.0 and padspeed.parse_speed("x2") == 2.0
    assert padspeed.parse_speed("0.5x") == 0.5
    with pytest.raises(ValueError):
        padspeed.parse_speed("100")

    def shim():
        while struct.unpack_from("<I", block, padsw.OFF_SPEED_REQ)[0] != 8000:
            time.sleep(0.01)
        struct.pack_into("<I", block, padsw.OFF_SPEED_NOW, 8000)
    t = threading.Thread(target=shim)
    t.start()
    assert padspeed.ask(block, 8, wait=5) == 0
    t.join()
    assert padspeed.ask(block, 2, wait=0.2) == 1        # nobody took it up


def test_the_speed_waits_for_attract_not_the_boot_screen():
    """techalerts is said at the very start of a boot; sped up from there Godzilla Pro 1.16 reached attract before
    its scenes were loaded, took a Start and died on a null scene lookup. From attract the game has them all."""
    import padspeed
    assert padspeed.UP_STATES == ("attract",)


def test_the_helpers_keep_the_games_time():
    swpoke = _text("swpoke.py")
    assert "padsw.game_sleep(m, ms / 1000.0)" in swpoke and "time.sleep(ms" not in swpoke
    plunge = _text("plunge.py")
    assert "time.sleep(" not in plunge and plunge.count("padsw.game_sleep(m, ") == 8
    sx = _text("swexercise.py")
    assert "padsw.game_sleep(m, press_ms / 1000.0)" in sx and "padsw.game_sleep(m, gap_ms / 1000.0)" in sx
    bf = _text("ballfeed.py")
    assert "padsw.game_sleep(m, step[1])" in bf
    assert "gclock = padsw.GameClock(m)" in bf and "f.poll(m, d, gclock.now())" in bf
    assert "self.last_feed = now\n" in bf                 # on the same clock as every other `now` there


_GSLEEP = r'''
eval "$(sed -n '/^pad_speed() {/,/^}/p' "$R/padpath.sh")"
eval "$(sed -n '/^pad_gsleep() {/,/^}/p' "$R/padpath.sh")"
ROOT=$(mktemp -d); mkdir -p "$ROOT/dump"
echo "none $(pad_speed)"
echo "x4.000 game_ms=123" > "$ROOT/dump/padspeed"
echo "four $(pad_speed)"
t0=$(date +%s%N); pad_gsleep 0.8; t1=$(date +%s%N)
echo "slept $(( (t1 - t0) / 1000000 ))"
rm -rf "$ROOT"
'''


@pytest.mark.skipif(not shutil.which("bash") or sys.platform == "win32", reason="bash rig helpers")
def test_the_shell_half_reads_the_shims_answer():
    out = subprocess.run(["bash", "-c", _GSLEEP], env=dict(os.environ, R=RIG), capture_output=True, text=True,
                         timeout=30).stdout.split("\n")
    assert out[0] == "none 1"
    assert out[1] == "four 4.000"
    assert 150 <= int(out[2].split()[1]) < 600           # 0.8 game s at 4x is 0.2 real


def test_the_check_keeps_the_games_time_and_starts_from_attract():
    sh = _text("modes", "gamecheck.sh")
    press = _sh_func(sh, "press")
    assert "pad_gsleep 0.45" in press and "pad_gsleep 1.1" in press
    drain = _sh_func(sh, "drain_until_end")
    assert "pad_gsleep $(( 10 * n + 10 ))" in drain
    assert "end=$(( $(date +%s) + $(gsecs 7 2) ))" in drain
    # a wait FOR something stays a plain loop
    assert "        sleep 0.5\n" in _sh_func(sh, "wait_for")
    # the first Start waits for the attract show, and still tries if none is said
    play = sh[sh.index("guided_setup 0 &&"):sh.index('for attempt in 1 2 3; do')]
    assert 'wait_for 60 "\\[led\\] light show running" "$PAD_LOGDIR/gzwatch.log"' in play
    assert "starting anyway" in play


# --------------------------------------------------------------------------
# watch.sh, rigbatch.sh, cardstage.sh, cardmount.sh
# --------------------------------------------------------------------------

def test_watch_asks_for_the_speed_once_the_game_is_up():
    w = _text("watch.sh")
    i = w.index("# ★ GAME SPEED (PAD-484).")
    blk = w[i:w.index("\nfi\n", i)]
    assert 'if [ -n "${PAD_SPEED:-}" ] && [ "$PAD_SPEED" != 1 ]; then' in blk
    assert 'setsid_as_seer python3 -u "$S/padspeed.py" --when-up "$PAD_SPEED"' in blk
    assert "SPEEDPG=$!" in blk
    assert 'rm -f "$ROOT/dump/padspeed"' in w                       # no last run's x4
    assert "pad_pkill -9 -f 'padspeed[.]py --when-up'" in w          # torn down with the run


def test_a_helper_that_must_see_the_game_runs_as_the_game():
    """On a root run in a slot a dropped helper reads the guest's environment as unreadable = slot 0: autoattract
    said "the game is not running; nothing to do" on all four slots, and every sweep sat out Tech Alerts."""
    w = _text("watch.sh")
    seer = _sh_func(w, "setsid_as_seer")
    assert 'if [ "$DROP" = 1 ] && [ "$PAD_SLOT" != 0 ]; then setsid "$@"; else setsid_as_user "$@"; fi' in seer
    assert w.count('setsid_as_seer bash "$S/autoattract.sh"') == 1
    assert 'setsid_as_seer bash -c \'f=$1; b=$2; shift 2' in w      # the held-back launch too


def test_rigbatch_speeds_every_job_and_boots_cached_cards():
    rb = _text("rigbatch.sh")
    assert "--speed) SPEED=$2; shift 2 ;;" in rb
    assert "${SPEED:+PAD_SPEED=$SPEED}" in rb
    assert '[ "$STAGE" = cache ] && echo PAD_CARD_CACHE=1' in rb
    # any Windows drive, any number of rigs
    pick = rb[rb.index('if [ "$NOSTAGE" = 0 ] && [ -z "$STAGE" ]'):rb.index("SPID=")]
    assert "/mnt/[a-z]/" in pick and "STAGE=cache" in pick and "SLOTS[@]}\" -gt 1" not in pick
    # the line's own ENV still wins over the batch's
    job = rb[rb.index("${SPEED:+PAD_SPEED=$SPEED}"):]
    assert job.index("$envs") < job.index('PAD_SLOT="$slot"')


def test_the_cache_stager_copies_through_the_card_cache_one_at_a_time():
    cs = _text("cardstage.sh")
    blk = cs[cs.index('if [ "$STAGE" = cache ]; then'):cs.index("# THIS batch's own folder")]
    assert 'bash "$RIG/cardmount.sh" "$card" --cache-now' in blk
    assert blk.index("got=$( copy_lock") < blk.index("--cache-now")
    assert '*) echo "$card" > "$S/$i"; continue ;;   # on a Linux disk already' in blk
    assert "PAD_CACHE_KEEP_FREE_GB=${PAD_CACHE_KEEP_FREE_GB:-30}" in blk
    cm = _text("cardmount.sh")
    now = cm[cm.index('if [ "$MODE" = "--cache-now" ]; then'):]
    assert 'PAD_CARD_CACHE=1 cache_pick "$IMG" "$LABEL" sync' in now[:200]
    # before --precache's stand-down beside a live run: the runs it stages for read their own copies
    assert cm.index('"$MODE" = "--cache-now"') < cm.index('"$MODE" = "--precache"')


_CACHED = r'''
t=$(mktemp -d) || exit 1
mkdir -p "$t/rig" "$t/home" "$t/board" "$t/cards"
cp "$R"/padpath.sh "$R"/padslot.sh "$R"/riglock.sh "$R"/rigbatch.sh "$R"/cardstage.sh "$t/rig/"
printf '#!/bin/bash\necho 0\n' > "$t/rig/alive.sh"
printf '#!/bin/bash\n:\n' > "$t/rig/killgame.sh"
for c in a b; do head -c 1024 /dev/urandom > "$t/cards/$c.raw"; done
cat > "$t/job.sh" <<'JOB'
#!/bin/bash
echo "$1 $2 cache=$PAD_CARD_CACHE speed=$PAD_SPEED" >> "$JOBLOG"
echo "VERDICT $1 pass"
JOB
printf 'a|%s|\nb|%s|PAD_SPEED=1\n' "$t/cards/a.raw" "$t/cards/b.raw" > "$t/l.list"
export PAD_HOME="$t/home" PAD_BOARD="$t/board" PAD_SLOTS_MAX=3 JOBLOG="$t/jobs.txt"
export PAD_RIGBATCH_ASSUME_MOUNTED=1
bash "$t/rig/rigbatch.sh" -n 1 --who PAD-9 --out "$t/out" --stage cache --speed 4 "$t/l.list" \
    -- bash "$t/job.sh" > "$t/stdout" 2>&1
echo "rc=$?"
sed "s#$t#T#g" "$t/jobs.txt" | sort
rm -rf "$t"
'''


@pytest.mark.skipif(not os.path.isdir("/proc/1"), reason="Linux only, like the rig (setsid, flock)")
def test_a_cached_batch_hands_every_job_the_cache_and_the_speed():
    """A card already on a Linux disk is booted where it lies (there is no 9p to save); every job gets
    PAD_CARD_CACHE=1 and --speed's PAD_SPEED, and a line's own PAD_SPEED=1 wins."""
    out = subprocess.run(["bash", "-c", _CACHED], env=dict(os.environ, R=RIG), capture_output=True, text=True,
                         timeout=120)
    lines = out.stdout.split("\n")
    assert "rc=0" in lines, out.stdout + out.stderr
    assert "a T/cards/a.raw cache=1 speed=4" in lines
    assert "b T/cards/b.raw cache=1 speed=1" in lines
