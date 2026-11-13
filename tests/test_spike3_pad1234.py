"""PAD-1234: Spike 3 video - a short clip is sent whole, end-of-stream drain
included, a few ms after it opens, before the host has decoded a frame (its
first comes 40-60 ms after the open). s3vid answered AVERROR_EOF 25 ms into
that drain, so Stern's decode thread called the clip over before it began:
Transformers' battle and mode clips (Solar Needle, Autobot Run) never showed,
the game's Play() timed out on each ("Play while loop timeout") and opened
the next, four a second, at 6 fps. A drain from the decode loop (its own
empty packet) now gets EOF only once every packet's frame is out; a teardown
(FlushDecoder's send_packet(NULL)) keeps the quick EOF."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMU = os.path.join(ROOT, "tools", "spike3_emu")


def read(name):
    with open(os.path.join(EMU, name), encoding="utf-8") as f:
        return f.read()


def body(src, start, end):
    return src[src.index(start):src.index(end)]


def test_a_null_drain_is_told_apart_from_an_empty_packet():
    send = body(read("s3vid.c"), "int avcodec_send_packet", "struct held {")
    drain = send[send.index("/* drain */"):]
    # the teardown's NULL is marked BEFORE the repeat-drain early return,
    # so a FlushDecoder after a natural drain still gets its quick EOF
    assert drain.index("if (!pkt) st[c].eof_flush = 1;") < drain.index("if (st[c].eof_sent) return AVERROR_EOF;")


def test_a_natural_drain_waits_for_the_frames_still_owed():
    recv = body(read("s3vid.c"), "int avcodec_receive_frame", "void avcodec_flush_buffers")
    drain = recv[recv.index("st[c].eof_sent) {"):recv.index("frame:")]
    assert "owed = st[c].npts;" in drain
    assert re.search(r"if \(!owed \|\| v->eos \|\| ms - st\[c\]\.drain_since >= EOF_WAIT_MS\)", drain)
    assert "return AVERROR(EAGAIN);" in drain
    # the teardown branch comes first and still ends quickly
    assert drain.index("if (st[c].eof_flush)") < drain.index("owed = st[c].npts;")


def test_the_wait_for_an_owed_frame_outlasts_the_first_frame_and_is_bounded():
    m = re.search(r"#define\s+EOF_WAIT_MS\s+(\d+)", read("s3vid.c"))
    assert m
    # past the host's first frame (40-60 ms) and the game's own ~275 ms
    # Play() wait, yet a packet that never makes a frame cannot hang a drain
    assert 300 <= int(m.group(1)) <= 1000


def test_a_flush_or_open_starts_the_drain_state_over():
    src = read("s3vid.c")
    flush = body(src, "void avcodec_flush_buffers", "void avcodec_free_context")
    for k in ("eof_sent = 0", "eof_flush = 0", "drain_since = 0"):
        assert "st[c]." + k in flush
    # open and a save-state resync clear the whole stream (memset)
    assert src.count("memset(&st[c], 0, sizeof st[c]);") >= 2


def test_the_caller_trace_is_level_two_only():
    src = read("s3vid.c")
    assert "trace_callers(\"F\");" in src
    assert "if (trace != 2) return;" in src
