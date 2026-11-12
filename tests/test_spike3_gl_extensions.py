"""PAD-1182: the Spike 3 GL bridge lists the extensions it carries.

Godot 4's GLES3 renderer reads the extension list (glGetIntegerv
NUM_EXTENSIONS + glGetStringi) before it will attach an EGL image to an
ExternalTexture. The bridge answered an empty list, so Pokemon's DISCOVER
background (and every other video Godot plays through an ExternalTexture)
stayed black on the emulator although its frames were decoded. The bridge is
aarch64 C built against a card's libc, so this pins the source: the list,
its count and glGetStringi must agree, and the list must name exactly what is
bridged."""
import os
import re

S3GL = os.path.join(os.path.dirname(__file__), "..", "tools", "spike3_emu", "s3gl.c")


def _src():
    with open(S3GL, encoding="utf-8") as f:
        return f.read()


def _ext_list(src):
    m = re.search(r"static const char \*const s3_ext\[\] = \{(.*?)\};", src, re.S)
    assert m, "s3gl.c has no s3_ext[] extension list"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_godot_external_texture_extensions_are_listed():
    exts = _ext_list(_src())
    # Godot's config.cpp: external_texture_supported needs this one
    assert "GL_OES_EGL_image_external_essl3" in exts
    assert "GL_OES_EGL_image_external" in exts
    assert "GL_OES_EGL_image" in exts


def test_list_names_only_what_the_bridge_carries():
    # claiming an extension the bridge does not implement would send Godot
    # down a path that draws nothing (or worse), so the list stays exact
    assert sorted(_ext_list(_src())) == sorted([
        "GL_OES_EGL_image",
        "GL_OES_EGL_image_external",
        "GL_OES_EGL_image_external_essl3",
    ])


def test_count_and_strings_come_from_the_list():
    src = _src()
    assert re.search(r"case 0x821D: v\[0\] = S3_NEXT;", src), \
        "NUM_EXTENSIONS must answer the list's length"
    body = re.search(r"glGetStringi\(unsigned int name, unsigned int i\)\s*\{(.*?)\n\}", src, re.S)
    assert body, "glGetStringi not found"
    assert "0x1F03" in body.group(1) and "s3_ext[i]" in body.group(1)
    assert "S3_NEXT" in body.group(1), "an index past the list must not read past it"
    # the bridge itself answers glEGLImageTargetTexture2DOES (what the list promises)
    assert '"glEGLImageTargetTexture2DOES"' in src
