"""PAD-415: a hit answers (a strobe and the game's own rising hit sound) and a lit shot flashes (MODE_SDK.md "A hit
answers, and a lit shot flashes").

David: "the inserts that are lit for shots should pretty much always be flashing - when they're solid, they look
broken, especially if i hit the shot and i don't get audible or visual feedback that it registered."

What is worth failing on:
  * THE PORT'S RUN IS THE GAME'S OWN, LOW TO HIGH: eight consecutive requests, the Sound Test's PITCHED HIT ORCH 1-8.
  * THE RUNTIME NEVER FLOODS: two hit sounds 100 ms apart at least; a strobe never longer than 2 s; a strobe on an
    insert the mode does not hold hands it back after.
  * EVERY HIT THAT COUNTS ANSWERS, in the kit and in a form-built mode's scoring shot.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"


def _fn(src, sig):
    """A function's body from its definition (a prototype before it is skipped)."""
    i = src.index(sig)
    while src.find(";", i) < src.find("{", i):
        i = src.index(sig, i + 1)
    body = src[i:]
    return body[:body.index("\n}\n")]


def test_the_le_port_names_the_rising_run():
    port = (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    run = [int(re.search(r"^value hit_sound_%d\s+(\d+)" % n, port, re.M).group(1)) for n in range(1, 9)]
    assert run == list(range(367, 375))
    assert not re.search(r"^value hit_sound_9\b", port, re.M)


def test_the_runtime_never_floods():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    sound = _fn(src, "int pm_hit_sound(int n)")
    assert "now - last < 100" in sound and "if (n > count) n = count;" in sound
    flash = _fn(src, "int pm_lamp_flash(uint64_t shots, unsigned rgb, unsigned ms)")
    assert "if (ms > 2000) ms = 2000;" in flash and "h->flash_only = 1;" in flash
    assert "(h->owner && h->owner != me)) continue;" in flash                  # another mode's inserts: left alone
    tick = _fn(src, "static void lamps_tick(void)")
    assert "if (h->flash_only) { lamp_let_go(k); continue; }" in tick         # handed back once the strobe is over
    release = _fn(src, "static int lamp_release_list(")
    assert "h->flash_only = 1;" in release                                     # a release mid-strobe finishes it


def test_every_hit_that_counts_answers():
    kit = (SDK / "examples" / "intricate_kit.h").read_text(encoding="utf-8")
    fresh = _fn(kit, "static KIT_UNUSED int kit_fresh(")
    assert fresh.count("if (pm_running()) kit_hit(bit);") == 2
    hit = _fn(kit, "static KIT_UNUSED void kit_hit(uint64_t shot)")
    assert "pm_lamp_flash(shot, KIT_WHITE, KIT_HIT_FLASH_MS)" in hit and "pm_hit_sound(" in hit
    assert "kit_hit_reset();" in _fn(kit, "static KIT_UNUSED int kit_begin(")
    form = (SDK / "mode_file.c").read_text(encoding="utf-8")
    shot = _fn(form, "static void on_shot(uint64_t mask)")
    assert "pm_lamp_flash(mask & scoring_bits(M)" in shot and "pm_hit_sound(" in shot


def test_the_docs():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("pm_lamp_flash", "pm_hit_sound", "pm_hit_sounds"):
        assert "`%s(" % name in doc, name
    assert "### A hit answers, and a lit shot flashes (PAD-415)" in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
