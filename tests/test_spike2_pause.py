"""PAD-204: the Pause key freezes the emulated game, and a long pause survives.

A tester: "It would be useful to be able to hit the pause key (or another key)
to completely freeze the game state ... I want to look at an animation."

padglhost owns the game window, so it owns the key: Pause (or F9) SIGSTOPs
every `game` process and the next press SIGCONTs them. The part that needs
guarding is the game's own watchdog - its dispatch loop waits with a 10 s
absolute pthread_cond_timedwait and exits 5 on ETIMEDOUT (PAD-200). Measured
on the rig, 2026-09-24, godzilla_pro attract: a bare 15 s SIGSTOP ended the
game on resume with GAME EXIT DISPATCH TIMEOUT; with the frozen time written to
padsw's paused_ms before the SIGCONT and hwshim moving the deadline out by it,
a pause of over a minute resumed and kept running.

These are source-level checks on the three copies of that contract (padsw.h,
padsw.py, hwshim's mirror) and on the order of padglhost's writes - the order
is the whole fix, and it is invisible to anything but a 10 s freeze on a rig.
"""
import io
import os
import re
import shutil
import struct
import subprocess
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
if RIG not in sys.path:
    sys.path.insert(0, RIG)


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf8", newline="") as f:
        return f.read()


def _func(src, name):
    """The body of a C function defined at file scope, by name."""
    m = re.search(r"\n[^\n]*\b%s\([^)]*\)\n\{(.*?)\n\}" % re.escape(name), src, re.S)
    assert m, name
    return m.group(1)


def test_the_pause_fields_close_the_block():
    import padsw
    assert padsw.OFF_PAUSED == 1084
    assert padsw.OFF_PAUSED_MS == 1088
    assert padsw.OFF_PAUSE_REQ == 1092
    assert (padsw.OFF_STOP_WANT, padsw.OFF_STOP_GEN,
            padsw.OFF_STOP_N, padsw.OFF_STOP_ACK) == (1096, 1100, 1104, 1108)
    assert padsw.SIZE == 1112


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_padsw_h_puts_the_pause_fields_where_python_reads_them(tmp_path):
    import padsw
    src = tmp_path / "layout.c"
    src.write_text('#include <stdio.h>\n#include <stddef.h>\n#include "padsw.h"\n'
                   'int main(void){printf("%zu %zu\\n", '
                   'offsetof(struct padsw_shm, paused), '
                   'offsetof(struct padsw_shm, paused_ms));'
                   'printf("%zu\\n", offsetof(struct padsw_shm, pause_req));return 0;}\n')
    exe = tmp_path / "layout"
    subprocess.run(["gcc", "-std=gnu17", "-I", RIG, "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout
    assert [int(x) for x in out.split()] == [padsw.OFF_PAUSED, padsw.OFF_PAUSED_MS,
                                             padsw.OFF_PAUSE_REQ]


def test_the_shim_hands_the_kernel_a_deadline_moved_by_the_pause():
    """The game's deadline is on its PAUSED clock, behind the kernel's by
    paused_ms: it goes to the kernel moved out by exactly that, and again by
    any pause that began during the wait."""
    body = _func(_text("hwshim.c"), "shim_cond_timedwait")
    assert body.index("p0 = pause_total_ms()") < body.index("ts_add_ms(&dl, p0);")
    assert body.index("ts_add_ms(&dl, p0);") < body.index("r = real(c, m, &dl);")
    assert "r = real(c, m, t);" not in body        # never the unmoved deadline
    assert "while (r == 110 /* ETIMEDOUT */ && (p1 = pause_total_ms()) != p0)" in body
    assert "ts_add_ms(&dl, p1 - p0);" in body
    # a real timeout with no pause in it is still returned as one
    assert body.rstrip().endswith("return r;")


# --- a TRUE pause: the game's clock stands still while it is frozen -----------
#
# A tester, on the fixed key: "it's not a true pause. it's just freezing that
# video frame, but not resuming from there when i continue." Measured on the
# rig (godzilla_pro attract, 8 s pause mid-clip, the old shim): the first
# delivery line after resume read "handed the game 220 frames in 2031 ms
# (108.3/s) early 166" - the clip's frame schedule, paced off CLOCK_MONOTONIC,
# caught up the frozen seconds in one burst, and the game's own timers jumped
# with it. So every clock the guest reads is its real value minus paused_ms.

def test_every_clock_the_game_reads_is_the_paused_one():
    c = _text("hwshim.c")
    for sym in ("clock_gettime", "gettimeofday", "time"):
        assert '__asm__("%s")' % sym in c, sym
    cg = _func(c, "shim_clock_gettime")
    assert 'dlsym(RTLD_NEXT, "clock_gettime")' in cg
    assert "pause_clock(clk) && (p = pause_total_ms()) != 0" in cg
    assert "ts_sub_ms(t, p);" in cg
    gt = _func(c, "shim_gettimeofday")
    assert 'dlsym(RTLD_NEXT, "gettimeofday")' in gt
    assert "pause_total_ms()" in gt
    assert "shim_gettimeofday(&tv, 0);" in _func(c, "shim_time")


def test_the_shim_s_own_millisecond_clock_stays_real():
    """pad_ms() stamps the [sw] lines host tools line up against their own
    CLOCK_MONOTONIC: it binds the REAL clock past the interposer."""
    body = _func(_text("hwshim.c"), "pad_ms")
    assert 'dlsym(RTLD_NEXT, "clock_gettime")' in body
    assert "pause_total_ms" not in body


def test_the_video_schedule_and_the_audio_bucket_read_the_paused_clock():
    """Both live in hwshim.so and call the plain symbols, which ARE the
    interposers - that is what stops the catch-up burst."""
    vid = _text("gstvid.c")
    assert "clock_gettime(1 /* CLOCK_MONOTONIC */, t);" in _func(vid, "vid_us")
    assert "dlsym" not in _func(vid, "vid_us")
    assert "gettimeofday(&t, 0);" in _func(_text("alsastub.c"), "now_us")


def _shim_time_helpers():
    c = _text("hwshim.c")
    out = ["struct shim_ts { long s, ns; };"]
    for name in ("ts_add_ms", "ts_sub_ms", "pause_clock"):
        m = re.search(r"\nstatic [^\n]*\b%s\([^)]*\)\n\{.*?\n\}" % name, c, re.S)
        assert m, name
        out.append(m.group(0))
    return "\n".join(out)


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_the_clock_arithmetic_borrows_and_carries(tmp_path):
    src = tmp_path / "ts.c"
    src.write_text("#include <stdio.h>\n" + _shim_time_helpers() + r"""
int main(void) {
    struct shim_ts t = { 100, 200000000L };
    ts_sub_ms(&t, 1300);            /* 100.2 - 1.3 = 98.9 */
    printf("%ld %ld\n", t.s, t.ns);
    ts_add_ms(&t, 1300);            /* and back */
    printf("%ld %ld\n", t.s, t.ns);
    t.s = 5; t.ns = 999000000L;
    ts_add_ms(&t, 2);               /* 5.999 + 0.002 = 6.001 */
    printf("%ld %ld\n", t.s, t.ns);
    printf("%d%d%d%d%d%d%d%d\n", pause_clock(0), pause_clock(1), pause_clock(4),
           pause_clock(7), pause_clock(11), pause_clock(2), pause_clock(3),
           pause_clock(-6));
    return 0;
}
""")
    exe = tmp_path / "ts"
    subprocess.run(["gcc", "-std=gnu17", "-o", str(exe), str(src)], check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True,
                         text=True).stdout.split("\n")
    assert out[0] == "98 900000000"
    assert out[1] == "100 200000000"
    assert out[2] == "6 1000000"
    # wall + monotonic clocks pause; the CPU-time ones (2, 3, per-thread) do not
    assert out[3] == "11111000"


def test_the_frozen_time_errs_short_so_the_clock_never_runs_back():
    """paused_ms IS the game's clock offset now. A credit longer than the real
    gap would step its monotonic clock backwards at resume; so the stop comes
    before the timer starts, and the credit is whole ms less one."""
    c = _text("padglhost.c")
    tog = _func(c, "pause_toggle")
    assert tog.index("pause_stop(SIGSTOP)") < tog.index("pause_t0 = now_s();")
    rel = _func(c, "pause_release")
    assert "unsigned ms = (unsigned)(held * 1000.0);" in rel
    assert "swshm->paused_ms += ms ? ms - 1 : 0;" in rel
    assert "+ 0.5" not in rel


def test_the_pause_key_toggles_and_presses_nothing():
    c = _text("padglhost.c")
    i = c.index("PAD-204: Pause / F9 freeze and resume")
    hook = c[i:i + 300]
    assert "0xff13" in hook and "0xffc6" in hook   # XK_Pause, XK_F9
    assert "if (press) pause_toggle();" in hook
    assert "break;" in hook                        # never reaches cab_key/binds
    assert i < c.index("cab_key(sym, press);")


def test_resume_counts_the_frozen_time_before_the_game_runs():
    body = _func(_text("padglhost.c"), "pause_release")
    assert body.index("swshm->paused_ms +=") < body.index("pause_stop(SIGCONT)")
    assert body.index("__sync_synchronize()") < body.index("pause_stop(SIGCONT)")


def test_pause_needs_the_switch_block_and_a_game():
    body = _func(_text("padglhost.c"), "pause_toggle")
    # no block = nothing to tell the shim, so no freeze the watchdog would kill
    assert body.index("if (!swshm)") < body.index("pause_stop(SIGSTOP)")
    assert "no running game to pause" in body


def test_a_stopping_renderer_never_leaves_the_game_frozen():
    c = _text("padglhost.c")
    assert c.index("pause_release();") < c.index('"[padglhost] stopped after %ld frames')


# --- the playfield window's Pause / F9 ------------------------------------------
#
# A tester, on v1.6.0: "it doesn't work. Neither F9 nor PAUSE." The rig proof
# had sent the key straight to the game window, but the playfield window is
# where hands usually are, and its keyboard forwarded neither key. It cannot
# signal the game itself (it is a Windows process), so its press goes down the
# swkeys pipe as a `pause` line, steps padsw's pause_req, and padglhost - which
# polls the block from its idle loop, and that loop runs on while the game is
# frozen - toggles once per step.

class _Block(bytearray):
    def flush(self):
        pass

    def close(self):
        pass


def _run_swkeys(monkeypatch, lines):
    import padsw
    import swkeys
    block = _Block(4096)
    monkeypatch.setattr(padsw, "open_block", lambda *a, **k: block)
    reqs = []

    class Stdin:
        def __iter__(self):
            for ln in lines:
                yield ln
                reqs.append(struct.unpack_from("<I", block, padsw.OFF_PAUSE_REQ)[0])

    monkeypatch.setattr(sys, "stdin", Stdin())
    assert swkeys.main() == 0
    return reqs, block


def test_a_pause_line_steps_the_counter_once_per_press(monkeypatch):
    import padsw
    reqs, block = _run_swkeys(monkeypatch, ["pause\n", "cab left 1\n", "pause\n"])
    assert reqs == [1, 1, 2]
    # a press is not a hold: EOF releases the button and leaves the count alone
    assert struct.unpack_from("<I", block, padsw.OFF_PAUSE_REQ)[0] == 2
    assert not any(block[padsw.OFF_SCR_CAB:padsw.OFF_SCR_CAB + padsw.CAB_N])
    assert not any(block[padsw.OFF_SCR_HELD:padsw.OFF_SCR_HELD + padsw.MAX_ID])


def test_the_counter_wraps_instead_of_raising(monkeypatch):
    import padsw
    block = _Block(4096)
    struct.pack_into("<I", block, padsw.OFF_PAUSE_REQ, 0xFFFFFFFF)
    padsw.request_pause(block)
    assert struct.unpack_from("<I", block, padsw.OFF_PAUSE_REQ)[0] == 0


def test_the_pipe_and_the_helper_agree_on_the_pause_line(monkeypatch):
    import swkeys
    playfield = pytest.importorskip("playfield")
    sent = io.BytesIO()
    pipe = playfield.SwitchPipe()
    monkeypatch.setattr(pipe, "_ensure", lambda: True)
    pipe._p = types.SimpleNamespace(stdin=types.SimpleNamespace(
        write=sent.write, flush=lambda: None))
    assert pipe.pause() is True
    assert sent.getvalue() == b"pause\n"
    assert swkeys.parse("pause\n") == ("pause", None, None)
    assert swkeys.parse("pause 1\n") is None


class _Pipe:
    def __init__(self):
        self.calls = []

    def _ensure(self):
        return True

    def set(self, sw, val):
        self.calls.append(("sw", sw, val))
        return True

    def set_cab(self, name, val):
        self.calls.append(("cab", name, val))
        return True

    def pause(self):
        self.calls.append(("pause",))
        return True

    def close(self):
        self.calls.append(("close",))


@pytest.mark.parametrize("code", ["Pause", "F9"])
def test_the_playfield_window_forwards_pause_and_f9(monkeypatch, code):
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "SwitchPipe", _Pipe)
    ctl = types.SimpleNamespace(view=None, drv=None)
    ki = pf.KeyInput(ctl, [])            # no rows: the WAITING window has it too
    sym = pf.code_to_keysym(code, code)
    assert sym in pf.PAUSE_KEYSYMS
    assert ki.key(sym, True) is True
    assert ki.key(sym, False) is True    # the release does nothing
    assert ki.pipe.calls == [("pause",)]
    ki.release_all()                     # a blur never sends a second toggle
    assert ki.pipe.calls == [("pause",)]


def test_the_page_sends_pause_and_f9():
    js = _text(os.path.join("pfpage", "pf.js"))
    codes = re.search(r"const PLAY_CODES = /\^\((.*)\)\$/;", js).group(1)
    assert "|Pause|F9" in codes


def test_padglhost_acts_on_the_playfield_s_presses():
    c = _text("padglhost.c")
    body = _func(c, "pause_poll")
    assert "(req - pause_req_seen) & 1u" in body    # odd steps toggle, even do not
    assert body.index("pause_toggle();") < body.index("pause_req_seen = req;")
    # called on every pump - the idle loop's too, so a frozen game still hears it
    assert "pause_poll();" in _func(c, "win_pump")
    # presses left in the block by an earlier session are not replayed
    assert "pause_req_seen = swshm->pause_req;" in _func(c, "sw_shm_open")


# --- the status bar: a Pause button and the volume ------------------------------

def _pf_block(tmp_path, paused):
    import padsw
    b = bytearray(4096)
    struct.pack_into("<I", b, 0, padsw.MAGIC)
    struct.pack_into("<I", b, padsw.OFF_PAUSED, paused)
    p = tmp_path / "padsw"
    p.write_bytes(bytes(b))
    return p


def test_the_pause_button_is_the_same_toggle(monkeypatch):
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "SwitchPipe", _Pipe)
    ctl = types.SimpleNamespace(keys=pf.KeyInput(
        types.SimpleNamespace(view=None, drv=None), []))
    assert pf.Playfield.api_pause(ctl) is True
    assert ctl.keys.pipe.calls == [("pause",)]
    assert pf.Playfield.api_pause(types.SimpleNamespace(keys=None)) is False


def test_the_button_says_resume_however_the_game_was_frozen(monkeypatch, tmp_path):
    """The flag is padglhost's, off the block: this button, Pause or F9 in
    either window - the bar shows the one truth."""
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "SW_PATH", str(_pf_block(tmp_path, 1)))
    run = pf.RunCtl(None)
    assert run.poll(10.0) is True
    assert run.dyn() == {"paused": True, "audio": None}     # no file: no volume row
    assert run.poll(10.1) is False                          # paced, and unchanged
    monkeypatch.setattr(pf, "SW_PATH", str(_pf_block(tmp_path, 0)))
    assert run.poll(11.0) is True and run.dyn()["paused"] is False
    monkeypatch.setattr(pf, "SW_PATH", str(tmp_path / "gone"))
    assert run.poll(12.0) is False                          # no block reads as running


def test_the_volume_row_writes_the_tab_s_file(monkeypatch, tmp_path):
    import json
    pf = pytest.importorskip("playfield")
    monkeypatch.setattr(pf, "SW_PATH", str(tmp_path / "gone"))
    ctl_file = tmp_path / "audio_ctl.json"
    ctl_file.write_text(json.dumps({"gain": 0.8, "muted": False}))
    run = pf.RunCtl(str(ctl_file))
    assert run.dyn()["audio"] == {"gain": 0.8, "muted": False}
    assert run.set_audio(gain=0.25) is True
    assert json.loads(ctl_file.read_text()) == {"gain": 0.25, "muted": False}
    assert run.set_audio(muted=True) is True                # the gain is kept
    assert json.loads(ctl_file.read_text()) == {"gain": 0.25, "muted": True}
    assert run.set_audio(gain=7) is True                    # clamped like the tab
    assert json.loads(ctl_file.read_text())["gain"] == 1.0
    # the tab moving it is picked up on the next poll
    ctl_file.write_text(json.dumps({"gain": 0.5, "muted": False}))
    os.utime(ctl_file, (1, 1))
    assert run.poll(100.0) is True
    assert run.dyn()["audio"] == {"gain": 0.5, "muted": False}
    assert pf.RunCtl(None).set_audio(gain=0.5) is False    # no file, no write


def test_the_page_draws_the_run_controls_and_lets_go_of_the_keys():
    js = _text(os.path.join("pfpage", "pf.js"))
    body = js[js.index("function runCluster(R)"):]
    body = body[:body.index("\n  }\n") + 4]
    assert 'api("pause")' in body
    assert 'api("volume", Number(vol.value))' in body
    assert 'api("mute", mute.checked)' in body
    # a focused slider eats the flipper arrows, a focused box the Action space
    assert "vol.blur()" in body and "mute.blur()" in body and "pause.blur()" in body
    assert 'r.paused ? "Resume" : "Pause"' in body
    assert "if (R && R.audio)" in body                     # no file, no volume row
    assert 'on("run", ' in js
    assert "const run = runCluster(S.run);" in js


def test_the_run_hands_the_window_the_control_file():
    w = _text("watch.sh")
    assert 'export WSLENV="${WSLENV:+$WSLENV:}PAD_AUDIO_CTL"' in w
    i = w.index('export WSLENV="${WSLENV:+$WSLENV:}PAD_AUDIO_CTL"')
    assert i < w.index('setsid_as_user "$PF_PY" "$PF_WIN"')


# --- the root hand: every run from the app (PAD-204, round 3) -----------------
#
# A tester, on v1.10.0 after restarting WSL: "this pause just does not do
# anything at all". Their log: `wsl.exe -u root ... PAD_PIVOT=1 ... watch.sh`
# and "[watch] running the guest as root, helpers as <user>". The renderer owns
# the key and runs as the user; the guest runs as root; kill() is refused. On
# the rig, the same launch (root watch.sh, the X socket the user's) reproduced
# it exactly - the game kept running and padglhost logged "no running game to
# pause" - and with pausekeep.py serving the stop as root, a 23.6 s pause froze
# the root game (state T) and resumed the same process, no watchdog exit.

def _block():
    import padsw
    return bytearray(4096), padsw


def _set(b, off, v):
    struct.pack_into("<I", b, off, v)


def _get(b, off):
    return struct.unpack_from("<I", b, off)[0]


def test_the_keeper_serves_a_request_and_answers_count_then_generation(monkeypatch):
    import pausekeep
    b, padsw = _block()
    sent = []
    # stand-in numbers: Windows' signal module has no SIGSTOP at all
    monkeypatch.setattr(pausekeep, "signal",
                        types.SimpleNamespace(SIGSTOP=19, SIGCONT=18))
    monkeypatch.setattr(pausekeep, "signal_games", lambda sig: sent.append(sig) or 2)
    assert pausekeep.serve(b) is None                      # nothing asked yet
    _set(b, padsw.OFF_STOP_WANT, 1)
    _set(b, padsw.OFF_STOP_GEN, 7)
    assert pausekeep.serve(b) == (1, 2)
    assert sent == [19]
    assert _get(b, padsw.OFF_STOP_N) == 2
    assert _get(b, padsw.OFF_STOP_ACK) == 7
    assert pausekeep.serve(b) is None                      # answered once only
    _set(b, padsw.OFF_STOP_WANT, 0)
    _set(b, padsw.OFF_STOP_GEN, 8)
    assert pausekeep.serve(b) == (0, 2)
    assert sent[-1] == 18


def test_the_keeper_writes_the_count_before_the_ack():
    src = _text("pausekeep.py")
    body = src[src.index("def serve("):src.index("def main(")]
    assert body.index("OFF_STOP_N, n)") < body.index("OFF_STOP_ACK, gen)")


def test_the_keeper_ignores_a_request_left_by_an_earlier_session():
    src = _text("pausekeep.py")
    main = src[src.index("def main("):]
    # the ack is caught up to the generation BEFORE the serving loop starts
    assert main.index("OFF_STOP_ACK, u32(m, padsw.OFF_STOP_GEN))") < main.index("while True:")


def test_the_keeper_never_leaves_the_game_frozen():
    src = _text("pausekeep.py")
    assert "signal.signal(signal.SIGTERM, resume_and_exit)" in src
    assert "if not renderer_up():\n                resume_and_exit()" in src


def test_padglhost_asks_the_keeper_when_the_run_has_one():
    c = _text("padglhost.c")
    body = _func(c, "pause_stop")
    assert 'getenv("PAD_PAUSE_KEEPER")' in body
    # what it wants BEFORE the new generation, then wait for that generation
    assert body.index("swshm->stop_want =") < body.index("++swshm->stop_gen")
    assert "swshm->stop_ack == gen" in body and "return (int)swshm->stop_n;" in body
    # a keeper that never answers is no worse than before
    assert body.rstrip().endswith("return pause_signal(sig);")
    assert "pause_stop(SIGSTOP)" in _func(c, "pause_toggle")
    assert "pause_stop(SIGCONT)" in _func(c, "pause_release")


def test_a_refused_signal_is_named_in_the_log():
    body = _func(_text("padglhost.c"), "pause_signal")
    assert "not allowed to signal the game" in body


def test_watch_starts_the_keeper_as_root_on_a_dropped_run():
    w = _text("watch.sh")
    assert 'PAUSE_KEEPER=0\n[ "$DROP" = 1 ] && PAUSE_KEEPER=1' in w
    assert 'PAD_PAUSE_KEEPER="$PAUSE_KEEPER"' in w            # the renderer is told
    start = 'setsid python3 "$S/pausekeep.py" "$SW_HOST" >> "$HOSTLOG" 2>&1 &'
    assert start in w                                         # root: NOT as_user
    assert w.index('PAD_PAUSE_KEEPER="$PAUSE_KEEPER"') < w.index(start)


def test_the_keeper_is_torn_down_and_counted():
    assert "pkill -9 -f 'pausekeep[.]py'" in _text("watch.sh")
    assert "pkill -9 -f 'pausekeep[.]py'" in _text("killgame.sh")
    assert "$(n -f 'pausekeep[.]py')" in _text("alive.sh")


def test_pause_lines_reach_the_app_s_log():
    assert r'/\[pause\]/              { print "[event] " $0; fflush(); next }' \
        in _text("watch.sh")
