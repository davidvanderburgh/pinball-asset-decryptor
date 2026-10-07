"""glbridge.c's object names: handed out round, never onto one still in use (PAD-441).

The guest half of the GL bridge allocates every texture, buffer, VAO, FBO and
shader/program name itself and the host keeps ONE object per guest name. Each
kind used to come off a bare counter that went back to 1 at its limit and
handed out whatever came next, live or not, so a long session of a game that
builds and drops textures as it plays (James Bond LE 1.06) came round and
re-pointed pictures the game was still drawing at newer textures: the screen
went to pieces after about half an hour.

This compiles the REAL allocator out of glbridge.c (brace-counted, the coil
tests' way - the text is never copied here) and drives it from stdin. What is
worth failing on:

  * A LIVE NAME IS NEVER HANDED OUT AGAIN while a free one exists, however many
    times the counter comes round.
  * A JUST-DELETED NAME IS THE LAST TO COME BACK: the counter still walks round
    (the host's graveyards keep a deleted object for save states and rely on
    the name staying unused for a while).
  * A KIND WITH EVERY NAME LIVE says so out loud.
  * The wiring: every glGen/glCreate takes from its own pool; texture, buffer
    and VAO deletes free the name; shader and program deletes do NOT (the
    host's save-state journal rebuilds a program from its shaders' names).
  * Coming round, and running out, reach the log the user sends.

Rig proof (2026-10-07, Bond LE 1.06 attract, PAD_GL_NAME_CAP=128): main's
counter re-issued 15 live textures and 18 live buffers on its first lap and
the attract screens broke the way the report showed; this allocator came round
five times with none re-issued and the screens stayed whole. Uncapped, attract
alone hands out ~1.5 texture names a second while holding 30-70.
"""
import os
import re
import shutil
import subprocess

import pytest

from tests._watch_event_filter import event_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "tools", "spike2_emu", "glbridge.c")

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
AWK = shutil.which("awk")

pytestmark = [
    pytest.mark.skipif(not os.path.isfile(BRIDGE), reason="rig not present"),
]

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int frame_no;
static void say(const char *s) { printf("SAY %%s", s); }
%s
static unsigned char live_t[4096];
static struct name_pool pool = { "texture", 1, 4096, 0, 0, 0, live_t };
int main(void)
{
    char op[8]; unsigned v;
    /* g = take one, d N = drop N, c = take one and drop it straight away
     * (a texture built and thrown out); one answer line per take */
    while (scanf("%%7s", op) == 1) {
        if (op[0] == 'g') printf("G %%u\n", name_take(&pool));
        else if (op[0] == 'c') { v = name_take(&pool); printf("G %%u\n", v);
                                 name_drop(&pool, v); }
        else if (op[0] == 'd' && scanf("%%u", &v) == 1) name_drop(&pool, v);
    }
    return 0;
}
"""


def _src():
    return open(BRIDGE, encoding="utf-8", errors="replace").read()


def _extract(name, src=None):
    """One static function's DEFINITION out of glbridge.c."""
    src = src if src is not None else _src()
    m = None
    for c in re.finditer(r"^static [^\n]*\b%s\(" % re.escape(name), src, re.M):
        brace, semi = src.find("{", c.start()), src.find(";", c.start())
        if brace >= 0 and (semi < 0 or brace < semi):
            m = c
            break
    assert m, "%s not found in glbridge.c - did it get renamed?" % name
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


def _public(name, src=None):
    """A public GL entry point's definition (int glX(...) { ... })."""
    src = src if src is not None else _src()
    m = re.search(r"^int %s\(" % re.escape(name), src, re.M)
    assert m, "%s not found in glbridge.c" % name
    depth, j = 0, src.index("{", m.start())
    while j < len(src):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
        j += 1
    raise AssertionError("unbalanced braces reading %s" % name)


@pytest.fixture(scope="module")
def names(tmp_path_factory):
    if not CC:
        pytest.skip("no C compiler on this host")
    src = _src()
    m = re.search(r"^struct name_pool \{.*?^\};", src, re.M | re.S)
    assert m, "struct name_pool moved"
    body = "\n".join([_extract("envint", src), m.group(0),
                      _extract("name_limit", src), _extract("name_step", src),
                      _extract("name_take", src), _extract("name_drop", src)])
    d = tmp_path_factory.mktemp("glnames")
    c = d / "glnames.c"
    c.write_text(HARNESS % body, encoding="utf-8")
    exe = d / ("glnames.exe" if os.name == "nt" else "glnames")
    r = subprocess.run([CC, "-O1", "-Wall", "-o", str(exe), str(c)],
                       capture_output=True, text=True)
    assert r.returncode == 0, "the bridge's name allocator did not compile:\n" + r.stderr
    return str(exe)


def _run(exe, ops, cap=None):
    env = dict(os.environ)
    env.pop("PAD_GL_NAME_CAP", None)
    if cap:
        env["PAD_GL_NAME_CAP"] = str(cap)
    r = subprocess.run([exe], input="\n".join(ops) + "\n", capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    return [int(l[2:]) for l in lines if l.startswith("G ")], \
        [l for l in lines if l.startswith("SAY ")]


def test_a_live_name_is_never_handed_out_again(names):
    # 300 names the game keeps for the whole session (fonts, the HUD), then
    # two rounds' worth of build-and-drop: the old counter handed 1..300 out
    # again on its second lap
    got, said = _run(names, ["g"] * 300 + ["c"] * 9000)
    kept, churn = set(got[:300]), got[300:]
    assert kept == set(range(1, 301))
    assert not kept & set(churn), \
        "a live name was handed out again: %s" % sorted(kept & set(churn))[:10]
    assert (min(churn), max(churn)) == (301, 4095)   # it did come round
    assert sum("came round" in s for s in said) == 2


def test_a_just_deleted_name_is_the_last_to_come_back(names):
    # 15 usable names: take 1..5, drop 2; the next takes walk on to 6..15
    # before 2 comes back, and 1, 3, 4, 5 never do
    got, said = _run(names, ["g"] * 5 + ["d 2"] + ["g"] * 11, cap=16)
    assert got[:5] == [1, 2, 3, 4, 5]
    assert got[5:] == list(range(6, 16)) + [2]
    assert any("came round" in s for s in said)


def test_a_full_kind_says_so_and_still_answers(names):
    got, said = _run(names, ["g"] * 8, cap=8)
    assert got[:7] == list(range(1, 8))
    assert 1 <= got[7] <= 7
    assert any("every texture name is in use" in s for s in said)


def test_a_drop_of_a_name_never_handed_out_changes_nothing(names):
    got, _ = _run(names, ["d 0", "d 3", "d 99999", "g", "g", "g"], cap=16)
    assert got == [1, 2, 3]


def test_every_gen_takes_from_its_own_pool():
    src = _src()
    for fn, pool in [("glGenTextures", "pool_tex"), ("glGenBuffers", "pool_buf"),
                     ("glGenVertexArrays", "pool_vao"),
                     ("glGenFramebuffers", "pool_fbo"),
                     ("glCreateShader", "pool_obj"), ("glCreateProgram", "pool_obj")]:
        assert "name_take(&%s)" % pool in _public(fn, src), fn
    assert "next_of" not in src, "a bare wrapping counter is back"


def test_deletes_free_names_only_where_the_host_allows_it():
    src = _src()
    for fn, pool in [("glDeleteTextures", "pool_tex"), ("glDeleteBuffers", "pool_buf"),
                     ("glDeleteVertexArrays", "pool_vao")]:
        assert "name_drop(&%s" % pool in _public(fn, src), fn
    # the save-state journal rebuilds programs from their shaders' guest names
    for fn in ("glDeleteShader", "glDeleteProgram"):
        assert "name_drop" not in _public(fn, src), fn


@pytest.mark.skipif(not AWK, reason="no awk")
def test_the_bridge_says_so_in_the_log_the_user_sends():
    """luvthatapex's log was 4000 lines of video events and not one that said
    what broke. The allocator's two loud lines reach the app's log pane through
    watch.sh's real [event] filter; the bridge's other chatter still does not."""
    lines = [
        "[bridge] texture names came round (round 1, 53 of 4095 live, frame "
        "47110); live ones are stepped over",
        "[bridge] every texture name is in use (4095) - handing out 12 AGAIN; "
        "whatever still uses it will draw wrong",
        "[bridge] item67: draw from 0x5bdc44 (fbo 0 tex 1 arg 6)",
        "[bridge] attached, ring 64 MB, host target 1360x768",
    ]
    out = subprocess.run([AWK, event_filter()], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = out.stdout.splitlines()
    assert got == ["[event] " + l for l in lines[:2]]
