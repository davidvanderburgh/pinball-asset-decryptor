"""PAD-1230: Spike 3 video - a frame's time is the smallest time of the
packets still in flight, so the guest's table of them must hold every packet
that can be in flight. At 128 it lost the times of the ~190 packets a clip
opens with past the first 128, the frames from #128 on came out ~7.7 s in the
future, and Fallout's backbox held its picture until the game's clock got
there, once each time the clip started."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike3_emu")


def read(name):
    with open(os.path.join(EMU, name), encoding="utf-8") as f:
        return f.read()


def define(src, name):
    m = re.search(r"#define\s+%s\s+(\d+)" % name, src)
    assert m, name
    return int(m.group(1))


def test_the_pending_times_hold_far_more_than_the_packet_ring():
    pkts = define(read("s3vid.h"), "S3VID_PKTS")
    maxpts = define(read("s3vid.c"), "MAXPTS")
    # the ring, plus what the host has fed ffmpeg's pipe and decoder: a clip's
    # open alone had 271-326 packets in before its first frame
    assert maxpts >= 4 * pkts
    assert maxpts >= 1024


def test_a_full_table_is_said_not_silent():
    src = read("s3vid.c")
    body = src[src.index("int avcodec_send_packet"):src.index("struct held {")]
    assert "pts_lost" in body and "the table is full" in body


def test_the_frame_log_reports_how_many_times_were_pending():
    src = read("s3vid.c")
    assert "packet times pending" in src and "npts_peak" in src


def test_the_frame_trace_is_off_unless_asked():
    src = read("s3vid.c")
    assert 'getenv("PAD_S3_VID_TRACE")' in src
    for k in ('"R"', '"F"', '"B"'):
        assert "tracef(%s" % k in src
