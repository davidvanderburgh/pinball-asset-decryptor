"""PAD-456: a seek into a clip starts the clip THERE, not at frame 0.

A tester's James Bond LE 1.06: "music stays in sync but sound effects and
callouts are 18-20 seconds behind the video". Their log had the game seeking
its film reels again and again - a 264 s reel to 3, 6, 13, 23, 31 and 39 s,
each time to how long the reel had been on, and its 28.8 s loops to 2-28 s -
and every one answered with

    [vid] ch1 seek to 38773 ms requested; only rewind is supported, restarting from 0

The video bridge could only rewind: the host decoder is one ffmpeg per request
and the request carried no position. So the picture ran up to half a minute
away from the effects and callouts the game plays with it, while the music,
which no picture keeps time with, sounded fine.

The guest half (gstvid.c) is ARM code with no cross compiler on the machines
this suite runs on, so it is pinned by SHAPE, as test_spike2_emu_video_threads
does. The host half is Python and is run: the ffmpeg it builds is executed
against a real clip and the first frame out must be the one at the time asked.
"""
import importlib.util
import os
import re
import shutil
import struct
import subprocess
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")
pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")
FFMPEG = shutil.which("ffmpeg")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _function(text, signature):
    """The DEFINITION, not a forward declaration of the same signature."""
    start = text.index(signature + "\n{")
    body = text[start:]
    return body[:body.index("\n}\n") + 2]


def _code_only(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _gst(signature):
    return _code_only(_function(_read("gstvid.c"), signature))


@pytest.fixture()
def vidhost(monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_ROOT", str(tmp_path))
    monkeypatch.setenv("PAD_GAME", "james_bond_le")
    monkeypatch.syspath_prepend(RIG)
    spec = importlib.util.spec_from_file_location("padvidhost_pad456",
                                                  os.path.join(RIG, "padvidhost.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "log", lambda msg: None)
    return mod


# ---- the shared block ------------------------------------------------------

def test_the_start_offset_sits_after_every_channel(vidhost):
    """Appended after ch[], where no older reader looks, so a guest or host the
    rig failed to rebuild reads nothing new and plays from 0 as before."""
    h = _code_only(_read("padvid.h"))
    shm = h[h.index("struct padvid_shm {"):]
    shm = shm[:shm.index("};")]
    assert re.search(r"struct padvid_chan ch\[PADVID_CHANNELS\];\s*"
                     r"unsigned start_ms\[PADVID_CHANNELS\];\s*$", shm)
    assert vidhost.START_BASE == vidhost.CH_BASE + vidhost.CHANNELS * vidhost.CH_BYTES == 4524
    assert vidhost.START_BASE + 4 * vidhost.CHANNELS <= vidhost.HDR


def test_no_version_bump_so_a_stale_half_still_shows_video(vidhost):
    """The version is an equality gate on all three readers: a bump would turn
    a half the rig did not rebuild into no video at all."""
    assert re.search(r"#define PADVID_VERSION 3\b", _read("padvid.h"))
    assert vidhost.VERSION == 3


def test_the_host_reads_each_channels_offset(vidhost):
    m = bytearray(vidhost.HDR)
    struct.pack_into("<I", m, vidhost.START_BASE + 4 * 5, 38773)
    assert vidhost.get_start_ms(m, 5) == 38773
    assert vidhost.get_start_ms(m, 4) == 0


# ---- the host decoder ------------------------------------------------------

def test_a_start_offset_is_an_input_seek(vidhost):
    cmd = vidhost.decode_cmd("/c.mp4", 928, 416, (928, 416), 38773)
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "38.773"
    assert cmd[cmd.index("-i") + 1] == "/c.mp4"


def test_the_start_of_a_clip_is_decoded_as_it_always_was(vidhost):
    cmd = vidhost.decode_cmd("/c.mp4", 928, 416, (928, 416), 0)
    assert "-ss" not in cmd
    assert cmd == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "/c.mp4",
                   "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]


def test_a_rescale_still_applies_with_an_offset(vidhost):
    cmd = vidhost.decode_cmd("/c.mp4", 640, 360, (928, 416), 5000)
    assert cmd[cmd.index("-vf") + 1] == "scale=640:360"


def test_serve_and_resume_build_the_same_command(vidhost):
    """Both decode paths go through decode_cmd, so a save-state resume of a
    sought clip counts its frames from the same place the serve did."""
    src = _read("padvidhost.py")
    for fn in ("def serve(", "def resume_serve("):
        body = src[src.index(fn):]
        body = body[:body.index("\ndef ")]
        assert "decode_cmd(" in body, fn
        assert '"ffmpeg"' not in body, fn


def test_a_mid_clip_start_never_touches_the_head_cache(vidhost):
    src = _read("padvidhost.py")
    body = src[src.index("def serve("):]
    body = body[:body.index("\ndef ")]
    assert re.search(r"if start_ms:\s*\n\s*hkey = None", body)


@pytest.mark.skipif(not FFMPEG, reason="no ffmpeg")
def test_the_first_frame_out_is_the_one_at_the_time_asked(vidhost, tmp_path):
    """Run for real: a clip whose frame N is grey level 4*N, a keyframe every
    second (so the seek has to decode forward from one), started at 1.5 s.
    Frame 45 is the answer; the keyframe before it (30) or frame 0 is the bug."""
    clip = str(tmp_path / "count.mp4")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=64x32:r=30:d=3",
                    "-vf", "geq=lum='4*N':cb=128:cr=128",
                    "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", clip],
                   check=True, timeout=120)
    w, h = 64, 32
    cmd = vidhost.decode_cmd(clip, w, h, (w, h), 1500)
    cmd[0] = FFMPEG
    out = subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout
    frame = w * h * 3 // 2
    assert len(out) >= frame
    luma = out[:w * h]
    level = sum(luma) / len(luma)
    assert abs(level - 4 * 45) < 6, level
    assert len(out) // frame == 90 - 45


# ---- the guest -------------------------------------------------------------

def test_a_seek_no_longer_restarts_from_zero():
    seek = _gst("int pad_vid_seek(void *pipeline, long long pos_ns)")
    assert "only rewind is supported" not in seek
    assert "restarting from 0" not in seek
    # the position rides into prepare() and is dropped after, whatever it did
    i_set = seek.index("s->want_ms = want;")
    i_prep = seek.index("pad_vid_prepare(pipeline)")
    i_clear = seek.index("s->want_ms = 0;")
    assert i_set < i_prep < i_clear


def test_only_a_rewind_can_be_absorbed_as_an_eos_reflex():
    seek = _gst("int pad_vid_seek(void *pipeline, long long pos_ns)")
    assert re.search(r"if \(!want && !s->playing && s->eos_us && s->eos_loop == 0", seek)
    prep = _gst("int pad_vid_prepare(void *pipeline)")
    assert re.search(r"s->eos_loop == 0 && !s->want_ms", prep)


def test_a_burst_absorbs_only_a_repeat_of_the_same_position():
    seek = _gst("int pad_vid_seek(void *pipeline, long long pos_ns)")
    assert re.search(r"burst && s->playing && want == s->start_ms", seek)


def test_prepare_publishes_the_offset_before_the_request():
    """The host reads start_ms when it notices the new generation, so it has
    to be there first - the same order as the path."""
    prep = _gst("int pad_vid_prepare(void *pipeline)")
    i_start = prep.index("vshm->start_ms[hw_of(s)] = start;")
    i_bump = prep.index("c->req_gen = gen;")
    assert prep.index("str_copy(c->path, s->location, PADVID_PATH_MAX);") < i_start < i_bump


def test_a_pre_arm_starts_at_zero_and_is_never_adopted_mid_clip():
    src = _code_only(_read("gstvid.c"))
    arm = src[src.index("int sp = spare_chan(s);"):]
    arm = arm[:arm.index("s->armed_chan1 = (unsigned)sp + 1;")]
    assert arm.index("vshm->start_ms[sp] = 0;") < arm.index("c->req_gen = s->armed_gen;")
    prep = _gst("int pad_vid_prepare(void *pipeline)")
    assert re.search(r"if \(!start && s->armed_chan1 && s->armed_gen", prep)


def test_the_position_the_game_reads_counts_from_the_start():
    """The game checks position against its own clock and seeks again when
    they disagree - a position counted from 0 after a seek to 38 s would read
    as 38 s behind and bring the next seek straight back."""
    thread = _gst("static void *vid_thread(void *arg)")
    assert "long long start_ns = (long long)s->start_ms * 1000000ll;" in thread
    assert "s->pos_ns = start_ns + (long long)consumed * delay * 1000ll;" in thread
    play = _gst("void pad_vid_play(void *pipeline)")
    assert "s->pos_ns = (long long)s->start_ms * 1000000ll;" in play
    prep = _gst("int pad_vid_prepare(void *pipeline)")
    assert "s->pos_ns = (long long)start * 1000000ll;" in prep
