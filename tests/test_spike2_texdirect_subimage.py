"""PAD-359: the Spike 2 renderer's direct-texture (video) path replaces a
frame's pixels with glTexSubImage2D when the texture's level 0 already has
that shape, instead of re-specifying it with glTexImage2D on every frame.

The risk in that trade is a STALE shape: a sub-image upload into a texture
whose level 0 something else redefined (or never defined) is a GL error and a
dropped frame. So every path in padglhost.c that can redefine a guest
texture's level 0 has to forget the remembered shape, and the sub-image branch
has to check the object GL really has bound.
"""
import os
import re

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def _src():
    with open(os.path.join(RIG, "padglhost.c"), encoding="utf-8",
              errors="replace") as fh:
        return fh.read()


def _case(src, op):
    """The dispatch case for `op` (the LAST one: the journal's comes first),
    up to the next case label."""
    ms = list(re.finditer(r"^    case %s\b.*?(?=^    case |^    default:)" % op,
                          src, re.M | re.S))
    assert ms, "no case %s" % op
    return ms[-1].group(0)


def test_texdirect_uses_subimage_only_on_a_known_shape():
    body = _case(_src(), "PADGL_TEXDIRECT")
    assert "p_glTexSubImage2D(0x0DE1, 0, 0, 0, (int)w, (int)h" in body
    m = re.search(r"if \(!vid_texfull(.*?)\)\s*\{\s*p_glTexSubImage2D", body, re.S)
    assert m, "the sub-image branch lost its guard"
    guard = m.group(1)
    for need in ("(unsigned)bound == obj", "texd_obj[b] == obj",
                 "texd_w[b] == w", "texd_h[b] == h"):
        assert need in guard, need
    # the re-spec branch is still there, records the shape it defined, and
    # the completeness fix-up after the upload is untouched
    assert "p_glTexImage2D(0x0DE1, 0, 0x1908" in body
    assert "texd_w[b] = (unsigned short)w" in body
    assert body.index("p_glTexImage2D(0x0DE1, 0, 0x1908") < body.index(
        "min_filter_val[cur_tex_unit_binding & (MAXNAME-1)];\n            if (!mf)")


@pytest.mark.parametrize("op", ["PADGL_GENTEX", "PADGL_TEXIMAGE",
                                "PADGL_TEXCOMPRESSED", "PADGL_FBOTEX"])
def test_every_level0_redefinition_forgets_the_shape(op):
    src = _src()
    bodies = [m.group(0) for m in re.finditer(
        r"^    case %s\b.*?(?=^    case |^    default:)" % op, src, re.M | re.S)]
    assert any("p_gl" in b and "texd_obj[" in b and "] = 0" in b
               for b in bodies), op


def test_world_reset_forgets_every_shape():
    assert "memset(texd_obj, 0, sizeof texd_obj);" in _src()


def test_full_respec_knob_and_upload_timing_are_reported():
    src = _src()
    assert 'getenv("PAD_VID_TEXFULL")' in src
    assert '"  upload %.3f ms/f (%ld sub)\\n"' in src
