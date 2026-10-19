"""PAD-617: emulator video stutters and "runs back slightly".

The guest hands the game a video frame by pointing it at a padvid ring slot;
the game names that slot to the GL bridge, and padglhost reads the pixels
when it reaches the upload command - a frame or two later, and the game names
the same slot again every tick until it picks up the next frame. gstvid.c
used to free a slot (read_idx) the moment the NEXT frame was handed, and the
host decoder refills a slot as soon as read_idx lets it. With the renderer
behind - a busy machine - the slot already held a frame three ahead when it
was read: a frame from the future, then the one that should have shown.
Godzilla LE attract with the CPU loaded: 28 backward frames in 90 s before,
0 after; with the CPU idle 0 either way.

Now the GL bridge remembers which ring offsets an upload named, where in the
command stream and in which frame, and gstvid frees a slot only when no
unread upload names it and it is not the game's current frame.

The guest code is ARM with no cross compiler here, so most of this pins it by
shape (as test_spike2_video_seek does); the slot rule itself is compiled with
the host gcc and run where there is one.
"""
import os
import re
import shutil
import subprocess

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _code_only(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _function(text, signature):
    start = text.index(signature + "\n{")
    body = text[start:]
    return body[:body.index("\n}\n") + 2]


# ---- the guest stream thread ------------------------------------------------

def test_a_handoff_no_longer_frees_its_slot_straight_away():
    thread = _code_only(_function(_read("gstvid.c"),
                                  "static void *vid_thread(void *arg)"))
    assert "c->read_idx = consumed;" not in thread
    assert "c->read_idx" not in thread


def test_the_thread_frees_slots_at_the_top_and_while_it_waits():
    thread = _code_only(_function(_read("gstvid.c"),
                                  "static void *vid_thread(void *arg)"))
    call = "vid_free_slots(c, ring, my_gen, consumed, &freed, &held_at);"
    assert thread.count(call) == 2
    # the first is the loop's first statement, before the pause hold
    loop = thread[thread.index("while (s->run_id == my_run && s->playing && c->playing) {"):]
    assert loop.index(call) < loop.index("if (s->paused)")
    # the second sits inside the sleep to the next frame, in short steps
    sleep = loop[loop.index("long ahead = (long)(target - vid_us());"):]
    assert "while (ahead > 0) {" in sleep
    assert sleep.index(call) < sleep.index("ahead = (long)(target - vid_us());", 10)


def test_a_slot_held_too_long_is_let_go():
    """A game that keeps one frame on screen for ever must not stall the
    stream behind it: the hold is timed from read_idx last moving."""
    free = _code_only(_function(_read("gstvid.c"), (
        "static void vid_free_slots(struct padvid_chan *c, unsigned char *ring,\n"
        "                           unsigned gen, unsigned consumed, unsigned *freed,\n"
        "                           unsigned long *held_at)")))
    assert "if (c->req_gen != gen) return;" in free
    assert "if (ok < consumed) ok++;" in free
    assert "if (ok > *freed) *held_at = 0;" in free
    assert "vid_us() - *held_at >= VID_HOLD_MAX_US" in free
    assert "if (ok > *freed) c->read_idx = *freed = ok;" in free
    assert re.search(r"#define VID_HOLD_MAX_US 250000ul", _read("gstvid.c"))


def test_the_host_keeps_the_slot_of_distance_the_guest_leans_on():
    """read_idx is published one past the oldest frame still needed; that is
    only safe while padvidhost stops one slot short of a full ring."""
    host = _read("padvidhost.py")
    assert "if p - r >= SLOTS - 1:" in host
    assert "while produced - min(get(m, c, \"read_idx\"), produced) >= SLOTS - 1:" in host


def test_an_empty_ring_is_reported_when_the_wait_outlasts_a_frame():
    """It compared a wait counted in 1000 us steps with == against a 33333 us
    period, so it could never fire."""
    thread = _code_only(_function(_read("gstvid.c"),
                                  "static void *vid_thread(void *arg)"))
    assert "waited_us == delay" not in thread
    assert "if (waited_us >= delay && waited_us - 1000 < delay && budget) {" in thread
    hand = thread[thread.index("consumed++;"):]
    assert hand.index("waited_us = 0;") < hand.index("s->delivered = consumed;")


def test_the_bridge_calls_are_looked_up_not_linked():
    """hwshim.so must still load against a libGLESv2 built before PAD-617;
    without the calls it frees at handoff, as it always did."""
    src = _code_only(_read("gstvid.c"))
    assert 'dlsym((void *)0, "pad_gl_vid_ref")' in src
    assert 'dlsym((void *)0, "pad_gl_vid_progress")' in src
    safe = _function(src, "static unsigned vid_safe_read(unsigned char *ring, unsigned consumed)")
    assert "if (!gl_vid_ref || !gl_vid_progress || !gl_vid_progress(&tail, &fnow))" in safe
    assert "return consumed;" in safe


# ---- the GL bridge -----------------------------------------------------------

def test_every_ring_upload_is_noted_after_it_is_emitted():
    src = _code_only(_read("glbridge.c"))
    i_emit = src.index("a[3] = PADGL_SRC_VIDSHM; a[4] = (unsigned)off; a[5] = bytes;")
    tail = src[i_emit:]
    assert tail.index("emit(PADGL_TEXDIRECT, a, sizeof a, 0, 0);") < tail.index("vidref_note(off);")
    note = _function(src, "static void vidref_note(long off)")
    assert "vidref[i].pos = (unsigned)hdr->head;" in note
    assert "vidref[i].frame = frame_no;" in note


def test_padglhost_counts_frames_shown_out_of_order():
    """The instrument the fix was measured with stays: a user's log says
    whether their video ran backwards."""
    src = _code_only(_read("padglhost.c"))
    assert "vid_order_note(u[4]);" in src
    assert "video OUT OF ORDER" in src


# ---- the slot rule, compiled -------------------------------------------------

def _slot_rule_source():
    br = _read("glbridge.c")
    gv = _read("gstvid.c")
    m = re.search(r"#define VIDREF_MAX 64\n.*?\nint pad_gl_vid_progress\(unsigned \*tail, int \*frame\)\n\{.*?\n\}\n",
                  br, re.S)
    assert m
    safe = _function(gv, "static unsigned vid_safe_read(unsigned char *ring, unsigned consumed)")
    return ('#include "padgl.h"\n#include "padvid.h"\n#include <stdio.h>\n'
            "static padgl_hdr H, *hdr = &H;\nstatic int bridge_dead, frame_no;\n"
            "static unsigned char RING[1];\n"
            "static long pad_vid_ring_offset(const void *p) { (void)p; return 0; }\n"
            + m.group(0)
            + "static int (*gl_vid_ref)(long, unsigned *, int *) = pad_gl_vid_ref;\n"
            "static int (*gl_vid_progress)(unsigned *, int *) = pad_gl_vid_progress;\n"
            + safe + r"""
#define SLOT(f) ((long)((f) % PADVID_SLOTS) * PADVID_SLOT_BYTES)
static void upload(unsigned f) { hdr->head += 64; vidref_note(SLOT(f)); }
static void swap(void) { hdr->head += 16; frame_no++; }
static void read_all(void) { hdr->tail = hdr->head; }
int main(void) {
    /* frames 0..5 handed and shown, all read: the current one (5) is held */
    unsigned f;
    for (f = 0; f < 6; f++) { upload(f); swap(); }
    read_all();
    printf("%u\n", vid_safe_read(RING, 6));
    /* frame 6 handed; the game names 5 again, not read yet: 5 is held */
    upload(5);
    printf("%u\n", vid_safe_read(RING, 7));
    /* the renderer reads it, game still on 5 (its current): still 5 */
    read_all();
    printf("%u\n", vid_safe_read(RING, 7));
    /* the game picks 6 up and the renderer reads it: 5 is free, 6 held */
    upload(6); swap(); read_all();
    printf("%u\n", vid_safe_read(RING, 7));
    /* the game stops drawing this video: nothing names it, all free */
    swap(); swap(); swap();
    printf("%u\n", vid_safe_read(RING, 9));
    /* a renderer gone away holds nothing */
    bridge_dead = 1;
    upload(9);
    printf("%u\n", vid_safe_read(RING, 10));
    return 0;
}
""")


@pytest.mark.skipif(not shutil.which("gcc"), reason="no C compiler")
def test_a_slot_is_held_until_nothing_reads_it(tmp_path):
    src = tmp_path / "rule.c"
    src.write_text(_slot_rule_source(), encoding="utf-8")
    exe = tmp_path / "rule"
    subprocess.run(["gcc", "-std=gnu17", "-Wall", "-I", RIG, "-o", str(exe), str(src)],
                   check=True)
    out = subprocess.run([str(exe)], check=True, capture_output=True,
                         text=True).stdout.split()
    assert out == ["5", "5", "5", "6", "9", "10"]
