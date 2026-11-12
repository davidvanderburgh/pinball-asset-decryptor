"""glbridge.c answers the game's state queries with what the game set (PAD-1128).

The guest half of the GL bridge answers glGetIntegerv / glGetBooleanv /
glIsEnabled itself (a host round trip per call would cost a frame), and used
to answer with constants: every capability "on", everything else 0, and for
GL_VIEWPORT / GL_SCISSOR_BOX only the first of four ints written. Jaws LE
1.02 reads its blend state into a cache before a special draw and puts it
back afterwards (0x627654: GL_BLEND, both blend equations, all four blend
factors); with the constants it put back blending OFF and colour factors
ZERO, and its scissor helper (0x436e08) never clipped. After the video mode
the LCD showed a few HUD pieces over no video for the rest of the game
(Mike St P, PAD-1128).

This compiles the WHOLE glbridge.c with a small driver (no host attached:
every command is a no-op, the shadows still move) and checks, worth failing:

  * VIEWPORT and SCISSOR_BOX come back as set, all four ints, and as the
    surface size before the game sets one.
  * glIsEnabled / glGetBooleanv / glGetIntegerv of a capability follow
    glEnable / glDisable; GL_DITHER starts on, the rest off.
  * Bound framebuffer (draw and read), program, VAO, buffers, active texture
    and its 2D texture, blend equations and all four blend factors read back.
  * Jaws' own save -> change -> restore of the blend state lands where it
    started.
"""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "tools", "spike2_emu", "glbridge.c")
CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")

pytestmark = [pytest.mark.skipif(not os.path.isfile(BRIDGE), reason="rig not present")]

DRIVER = r"""
#include <stdio.h>
#ifdef __APPLE__
/* The emulator's shim supplies these and glbridge.c references them weakly.
 * Linux's linker leaves a missing weak one NULL; the Mac's refuses to link
 * (PAD-1153). Stand in with what the bridge does without them: the wall
 * clock, and no frame in the video ring. */
#include <unistd.h>
void pad_real_sleep_us(long long us) { usleep((useconds_t)us); }
long pad_vid_ring_offset(const void *p) { (void)p; return -1; }
#endif
int glViewport(int, int, int, int); int glScissor(int, int, int, int);
int glEnable(unsigned); int glDisable(unsigned); int glIsEnabled(unsigned);
int glGetIntegerv(unsigned, int *); int glGetBooleanv(unsigned, unsigned char *);
int glBindFramebuffer(unsigned, unsigned); int glUseProgram(unsigned);
int glBindVertexArray(unsigned); int glBindBuffer(unsigned, unsigned);
int glActiveTexture(unsigned); int glBindTexture(unsigned, unsigned);
int glBlendFunc(unsigned, unsigned); int glBlendFuncSeparate(unsigned, unsigned, unsigned, unsigned);
int glBlendEquation(unsigned); int glBlendEquationSeparate(unsigned, unsigned);
int pad_fb_width(void); int pad_fb_height(void);

static int one(unsigned p) { int v[4] = { -7, -7, -7, -7 }; glGetIntegerv(p, v); return v[0]; }
static void four(const char *tag, unsigned p)
{ int v[4] = { -7, -7, -7, -7 }; glGetIntegerv(p, v); printf("%s %d %d %d %d\n", tag, v[0], v[1], v[2], v[3]); }
static int boolean(unsigned p) { unsigned char b = 9; glGetBooleanv(p, &b); return b; }

/* Jaws LE 1.02, 0x627654: the blend state it saves before a special draw */
struct blend { unsigned char on; int eq_rgb, eq_a, src_rgb, dst_rgb, src_a, dst_a; };
static void save(struct blend *b)
{
    glGetBooleanv(0x0BE2, &b->on);
    glGetIntegerv(0x8009, &b->eq_rgb); glGetIntegerv(0x883D, &b->eq_a);
    glGetIntegerv(0x80C9, &b->src_rgb); glGetIntegerv(0x80CB, &b->src_a);
    glGetIntegerv(0x80C8, &b->dst_rgb); glGetIntegerv(0x80CA, &b->dst_a);
}
static void restore(const struct blend *b)
{
    if (b->on) glEnable(0x0BE2); else glDisable(0x0BE2);
    glBlendEquationSeparate(b->eq_rgb, b->eq_a);
    glBlendFuncSeparate(b->src_rgb, b->dst_rgb, b->src_a, b->dst_a);
}

int main(void)
{
    struct blend before, saved, after;
    pad_fb_width(); pad_fb_height();
    four("VP0", 0x0BA2);
    four("SC0", 0x0C10);
    glViewport(10, 20, 1360, 768); four("VP", 0x0BA2);
    glScissor(5, 6, 70, 80); four("SC", 0x0C10);
    printf("CAP0 blend=%d scissor=%d dither=%d depth=%d cull=%d\n", glIsEnabled(0x0BE2),
           glIsEnabled(0x0C11), glIsEnabled(0x0BD0), glIsEnabled(0x0B71), glIsEnabled(0x0B44));
    glEnable(0x0BE2); glEnable(0x0C11);
    printf("CAP1 blend=%d scissor=%d bool=%d int=%d\n", glIsEnabled(0x0BE2), glIsEnabled(0x0C11),
           boolean(0x0BE2), one(0x0C11));
    glDisable(0x0C11);
    printf("CAP2 scissor=%d bool=%d\n", glIsEnabled(0x0C11), boolean(0x0C11));
    glBindFramebuffer(0x8D40, 3); glBindFramebuffer(0x8CA8, 4);
    printf("FBO draw=%d read=%d\n", one(0x8CA6), one(0x8CAA));
    glUseProgram(9); glBindVertexArray(5); glBindBuffer(0x8892, 11); glBindBuffer(0x8893, 12);
    glActiveTexture(0x84C2); glBindTexture(0x0DE1, 33);
    printf("OBJ prog=%d vao=%d array=%d elem=%d unit=%d tex=%d\n", one(0x8B8D), one(0x85B5),
           one(0x8894), one(0x8895), one(0x84E0) - 0x84C0, one(0x8069));
    glBindVertexArray(6);
    printf("VAO6 elem=%d\n", one(0x8895));
    glBlendEquationSeparate(0x8006, 0x800B);
    glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303);
    save(&before);
    printf("BLEND on=%d eq=%d,%d f=%d,%d,%d,%d\n", before.on, before.eq_rgb, before.eq_a,
           before.src_rgb, before.dst_rgb, before.src_a, before.dst_a);
    /* the special draw changes everything, then puts back what it saved */
    save(&saved);
    glDisable(0x0BE2); glBlendEquation(0x800A); glBlendFunc(1, 1);
    restore(&saved);
    save(&after);
    printf("ROUNDTRIP %d\n", before.on == after.on && before.eq_rgb == after.eq_rgb
           && before.eq_a == after.eq_a && before.src_rgb == after.src_rgb
           && before.dst_rgb == after.dst_rgb && before.src_a == after.src_a
           && before.dst_a == after.dst_a);
    return 0;
}
"""


@pytest.fixture(scope="module")
def answers(tmp_path_factory):
    if not CC:
        pytest.skip("no C compiler on this host")
    d = tmp_path_factory.mktemp("glq")
    drv = d / "drv.c"
    drv.write_text(DRIVER, encoding="utf-8")
    exe = d / ("glq.exe" if os.name == "nt" else "glq")
    r = subprocess.run([CC, "-O1", "-w", "-o", str(exe), BRIDGE, str(drv), "-ldl", "-lpthread"],
                       capture_output=True, text=True)
    if r.returncode != 0 and ("cannot find" in r.stderr or "No such file" in r.stderr):
        pytest.skip("the bridge needs Linux headers/libraries to build: " + r.stderr[:200])
    assert r.returncode == 0, "glbridge.c + driver did not build:\n" + r.stderr
    env = {k: v for k, v in os.environ.items() if not k.startswith("PAD_GL")}
    env.update(PAD_GL_W="1360", PAD_GL_H="768")
    out = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    return dict(line.split(" ", 1) for line in out.stdout.splitlines())


def test_viewport_and_scissor_box_come_back_whole(answers):
    assert answers["VP0"] == "0 0 1360 768"          # the surface, before the game sets one
    assert answers["SC0"] == "0 0 1360 768"
    assert answers["VP"] == "10 20 1360 768"         # all four ints, never stack garbage
    assert answers["SC"] == "5 6 70 80"


def test_capabilities_follow_enable_and_disable(answers):
    assert answers["CAP0"] == "blend=0 scissor=0 dither=1 depth=0 cull=0"
    assert answers["CAP1"] == "blend=1 scissor=1 bool=1 int=1"
    assert answers["CAP2"] == "scissor=0 bool=0"


def test_bound_objects_read_back(answers):
    assert answers["FBO"] == "draw=3 read=4"
    assert answers["OBJ"] == "prog=9 vao=5 array=11 elem=12 unit=2 tex=33"
    assert answers["VAO6"] == "elem=0"               # the element buffer is the VAO's


def test_jaws_blend_save_and_restore_lands_where_it_started(answers):
    # GL_FUNC_ADD / GL_FUNC_REVERSE_SUBTRACT, SRC_ALPHA / ONE_MINUS_SRC_ALPHA, ONE / ONE_MINUS_SRC_ALPHA
    assert answers["BLEND"] == "on=1 eq=32774,32779 f=770,771,1,771"
    assert answers["ROUNDTRIP"] == "1"
