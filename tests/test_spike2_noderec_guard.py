"""Nothing may reach a switch node record without asking whether one exists.

PAD-102's root cause. `SW_NODEREC(n)` is an offset from the switch STRUCT, and
`sw_struct_addr()` returns `&sw_shadow[0]` when the table was found by shape
instead of configured - an EIGHT-BYTE array in the shim's own .bss standing in
for a struct that does not exist. `SW_NODEREC(0)` is already 16 bytes past the
end of it.

`sw_prime()` wrote an at-rest word through that pointer into `rec[12..19]` and
`rec[20..27]` - the same eight bytes twice, eight bytes apart. Under a shadow
that is `&sw_shadow[0] + 28` and `+36`, which in the shipped build were
hwshim's own `game_segv_fn` and `real_sigaction`. The word is
`{0xff,0x0f,0x0f,0,0,0,0,0}` = `{0x000f0fff, 0}`, so `real_sigaction` became an
odd address inside the GAME's text; `shim_sigaction`'s tail call `bx`ed to it,
flipped the CPU into Thumb, and a user's Godzilla died four seconds into every
boot.

Three sites used `SW_NODEREC` and exactly ONE checked `sw_shadow[0]` first. The
fix is not a guard at the call site that happened to bite - it is that there is
now one accessor, `sw_noderec()`, which refuses under a shadow, and no caller
touches `SW_NODEREC` directly. This test is what keeps a fourth caller from
reintroducing it by forgetting, which is the whole reason the guard was moved.

Pure text, no compiler: the property is "who calls what", which the source
answers exactly.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIM = os.path.join(ROOT, "tools", "spike2_emu", "hwshim.c")

pytestmark = pytest.mark.skipif(not os.path.isfile(SHIM), reason="rig not present")


def _src():
    return open(SHIM, encoding="utf-8", errors="replace").read()


def _code_lines():
    """Source lines with block comments and // comments stripped, so prose that
    merely mentions SW_NODEREC does not read as a use of it."""
    src = re.sub(r"/\*.*?\*/", "", _src(), flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return [(i + 1, l) for i, l in enumerate(src.split("\n"))]


def test_the_accessor_exists_and_refuses_under_a_shadow():
    body = re.search(r"static unsigned char \*sw_noderec\(unsigned node\)\s*\{(.*?)\n\}",
                     _src(), re.S)
    assert body, "sw_noderec() is gone - the guard has no home"
    b = body.group(1)
    assert "sw_shadow[0]" in b, "the accessor no longer checks for a shadow table"
    assert re.search(r"if\s*\(\s*sw_shadow\[0\]\s*\)\s*return\s+0", b), \
        "the shadow check must REFUSE (return 0), not merely notice"


def test_no_caller_dereferences_SW_NODEREC_directly():
    """The property the fix rests on: exactly one use of the macro, inside the
    accessor. Any other use is a caller that skipped the guard."""
    uses = [(n, l.strip()) for n, l in _code_lines()
            if "SW_NODEREC" in l and not l.lstrip().startswith("#define")]
    assert len(uses) == 1, (
        "SW_NODEREC is used outside sw_noderec() - that caller can splat the "
        "shim's own .bss under a shadow table:\n" +
        "\n".join("  hwshim.c:%d  %s" % u for u in uses))


def _sw_prime_body():
    """sw_prime's DEFINITION, not its forward declaration - the declaration at
    the top of the file ends in ';' so anchoring on '){' picks the real one."""
    m = re.search(
        r"static void sw_prime\(unsigned nid, const unsigned char bits\[8\]\)\s*\{(.*?)\n\}",
        _src(), re.S)
    assert m, "sw_prime() is gone or was renamed"
    return m.group(1)


def test_sw_prime_goes_through_the_accessor():
    b = _sw_prime_body()
    assert "sw_noderec(" in b, "sw_prime no longer asks whether a record exists"
    assert re.search(r"rec\s*=\s*sw_noderec\(nid\)\s*;\s*if\s*\(!rec\)\s*return\s*;", b), \
        "sw_prime must bail when there is no record, BEFORE writing"


def test_sw_prime_does_not_mark_primed_when_it_refuses():
    """A shadow can be replaced by a real table later in the run. Marking the
    node primed on refusal would lose the priming for the whole run."""
    body = _sw_prime_body()
    bail = re.search(r"if\s*\(!rec\)\s*return\s*;", body)
    mark = body.index("primed[nid] = 1")
    assert bail, "sw_prime no longer bails when there is no record"
    assert bail.start() < mark, \
        "primed[] is set before the refusal - priming is lost for the run"


def test_the_at_rest_word_is_still_the_one_that_did_the_damage():
    """Not a rule, an anchor: if this constant ever changes, the PAD-102 story
    in the comments (and this file) stops matching the code."""
    m = re.search(r"idle\[8\]\s*=\s*\{([^}]*)\}", _src())
    assert m, "the at-rest word is gone - update the PAD-102 notes"
    vals = [v.strip() for v in m.group(1).split(",")]
    assert vals[:3] == ["0xff", "0x0f", "0x0f"], \
        "the at-rest word changed; it used to read {0x000f0fff, 0} as two words"
