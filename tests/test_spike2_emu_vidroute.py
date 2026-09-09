"""``vidroute.py`` reads the clip off the video host's serving line.

The tool answers one question - is the game being served DISTINCT clips, or is
a channel nailed to a single file while the game keeps asking for others - by
counting how many different files each channel was asked to open.

It had stopped being able to answer it.  The `(acked ...)` clause was added to
the serving line after the tool was written, and its path pattern matched THAT
instead of the path, so every clip read as `(acked` and every channel reported
exactly one distinct clip.  The fault the tool exists to name could not appear
in its own output.  These pin both line shapes, because a reader that knows
only today's turns every log already on disk into "no serving lines".
"""
import os
import sys

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


@pytest.fixture()
def vidroute():
    if RIG not in sys.path:
        sys.path.insert(0, RIG)
    import vidroute as mod
    return mod


def _serving_line(path, acked=True):
    clause = "(acked 2.0 ms after notice) " if acked else ""
    return ("[padvid   10.11] ch0 serving 1360x768 300 frames %s%s\n"
            % (clause, path))


def _read(vidroute, line):
    m = vidroute.LINE.search(line)
    assert m, line
    return m.group(6), int(m.group(5))


def test_the_clip_is_read_not_the_acked_clause(vidroute):
    """The regression, stated as itself."""
    path = "./assets/lcd/auto_loaded/%s/scene.assets/2.asset/372.asset" % ("a" * 40)
    assert _read(vidroute, _serving_line(path)) == (path, 300)


def test_two_different_clips_read_as_two(vidroute):
    """What the miss actually cost: every channel reported ONE distinct clip,
    whatever it had really been served."""
    got = [vidroute.short(_read(
        vidroute, _serving_line("/g/scene.assets/2.asset/%d.asset" % n))[0])
        for n in (1, 2)]
    assert got == ["2.asset/1.asset", "2.asset/2.asset"]


def test_a_log_written_before_the_acked_clause_still_reads(vidroute):
    path = "/g/scene.assets/2.asset/5.asset"
    assert _read(vidroute, _serving_line(path, acked=False)) == (path, 300)


def test_the_scene_hash_is_dropped_from_what_it_prints(vidroute):
    """40 hex digits nobody can read, in a column meant to be scanned."""
    assert vidroute.short(
        "./assets/lcd/auto_loaded/%s/scene.assets/2.asset/9.asset" % ("b" * 40)
    ) == "2.asset/9.asset"


def test_a_path_with_no_scene_dir_is_left_alone(vidroute):
    assert vidroute.short("/tmp/loose.mp4") == "/tmp/loose.mp4"
