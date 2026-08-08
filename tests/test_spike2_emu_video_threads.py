"""The video bridge starts a thread per clip, so it must not keep them.

WHAT THIS IS GUARDING.  Reported 2026-08-08: the emulator came up correctly -
picture, sound, keyboard - and the game killed itself with a SEGV after about
seven minutes.  The last video line before it went was

    [vid] ch0 could not start the streaming thread

and every counter above it was healthy: 30.0 frames/s handed over, late 0,
early 0, right to the end.

``vid_thread`` plays a clip ONCE and returns; the game loops a clip by seeking,
and ``pad_vid_seek`` answers a seek by calling ``pad_vid_play`` again.  So a
channel showing a 5.6 s clip starts a new thread every 5.6 s, three channels
were looping, and the failure landed 435 s in - a few hundred threads.  Each
was created with a NULL attribute, which means JOINABLE, and a joinable thread
that exits is not finished: glibc holds its descriptor and its whole stack
(RLIMIT_STACK, normally 8 MB of address space) until somebody joins it.
Nothing did, and nothing could - the ``run_id`` handshake exists so a
superseded thread can leave without the starter waiting on it.  A few hundred
8 MB stacks is the entire address space of a 32-bit guest, which is both why
``pthread_create`` ran out and why the SEGV followed five seconds later.

PURE TEXT, for the reason ``test_spike2_emu_build.py`` gives at length: this is
ARM guest code, there is no cross compiler on the machines this suite runs on,
and a test nobody runs is not a test.  What is checkable here is the shape of
the call - created, detached, and the detach looked up rather than linked - and
the shape is the whole fix.
"""
import os
import re

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _read(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _function(text, signature):
    """The body of a top-level C function, signature line included.

    Ends at the first ``}`` in column 0, which is this file's brace style
    throughout and the only one that closes a function.
    """
    start = text.index(signature)
    body = text[start:]
    end = body.index("\n}\n")
    return body[:end + 2]


def _code_only(text):
    """Drop comments.  Every claim below is about what the shim DOES, and this
    file explains itself at length - a substring search that cannot tell prose
    from a call would be satisfied by the comment describing the bug."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _play():
    return _code_only(_function(_read("gstvid.c"), "void pad_vid_play(void *pipeline)"))


# ---- the fix itself -------------------------------------------------------

def test_the_streaming_thread_is_detached():
    """The whole bug in one assertion.  Without this the rig leaks a thread
    stack per clip loop and a long attract run walks off the end of a 32-bit
    address space."""
    play = _play()
    assert "pthread_create" in play, "pad_vid_play no longer starts the thread?"
    create = play.index("pthread_create")
    assert "vid_detach" in play[create:], (
        "the streaming thread is created joinable and never reaped")


def test_a_failed_create_is_not_detached():
    """A detach of a thread id that was never written is undefined behaviour,
    and the failure branch is reached exactly when the leak has already
    exhausted the process - the worst possible moment to add one."""
    play = _play()
    fail = play.index("could not start the streaming thread")
    tail = play[fail:]
    assert "return" in tail, "the failure branch must not fall through"
    assert tail.index("return") < (tail.index("vid_detach")
                                   if "vid_detach" in tail else len(tail)), (
        "the failure branch reaches the detach")


def test_the_detach_is_looked_up_at_run_time_and_never_linked():
    """THE ONE FAILURE THIS RIG CANNOT RECOVER FROM.  ``build.sh`` links the
    shim against libc and libdl only, and on the older glibc in a real Spike 2
    rootfs ``pthread_detach`` lives in libpthread.so.0.  A direct call would be
    an undefined symbol in an LD_PRELOADed object, which does not degrade - it
    stops the guest at start, for everybody, before any of this code runs.

    hwshim.c already resolves ``pthread_create`` through dlsym for exactly this
    reason; the new call follows it.
    """
    src = _code_only(_read("gstvid.c"))
    assert 'dlsym(RTLD_NEXT, "pthread_detach")' in src, (
        "pthread_detach must be resolved at run time")
    assert not re.search(r"extern\s+\w+\s+pthread_detach\s*\(", src), (
        "a declared pthread_detach is a link-time dependency on libpthread")


def test_a_guest_without_pthread_detach_still_runs():
    """The lookup can fail - that is the point of doing it at run time - and
    the answer to a failed lookup is the behaviour that shipped before, not a
    null call through a function pointer."""
    src = _read("gstvid.c")
    helper = _code_only(_function(src, "static void vid_detach(unsigned long th)"))
    assert re.search(r"if\s*\(\s*fn\s*\)", helper), (
        "the resolved pointer must be checked before it is called")


# ---- and what the log says if it ever happens again ------------------------

def test_the_thread_failure_reports_the_code_and_the_count():
    """The reported line named a channel and nothing else, so the leak was
    invisible in it - the diagnosis came from counting clip loops by hand.
    ``pthread_create`` returns its error directly (EAGAIN is 11) and does not
    set errno, and the count of threads started separates "this run leaked"
    from any future cause that does not."""
    play = _play()
    fail = play[play.index("could not start the streaming thread"):]
    assert "rc" in fail, "the error code the call returned"
    assert "vid_threads_started" in fail, "and how many had been started"


def test_the_counter_counts_plays_not_channels():
    """A per-channel counter would top out at PADVID_CHANNELS and say nothing.
    It has to be incremented where a thread is started, which is per clip
    play."""
    play = _play()
    assert "vid_threads_started++" in play


# ---- nothing else in the guest starts a thread of its own ------------------

def test_the_streaming_thread_is_the_only_one_this_file_starts():
    """If a second one is ever added, this test fails and whoever adds it reads
    the docstring above before deciding whether it needs the same treatment."""
    src = _code_only(_read("gstvid.c"))
    assert src.count("pthread_create") == 2, (
        "expected the extern declaration and one call site; a new thread in "
        "this file needs a detach too - see the module docstring")
