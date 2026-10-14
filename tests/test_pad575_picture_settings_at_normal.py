"""PAD-575 (DragonRR): a Godzilla Heisei card stuttered on the machine, 7-9 pictures a second in busy
scenes, with Picture settings in the service menu on and all three at 5. The same card written
without them played smoothly (the tester's own A/B on the machine). PAD-537's step in every fragment
shader costs the machine's GPU on every pixel even when it changes nothing.

So the runtime adds the step only when the game last ran with a value away from 5: the values are
kept in /dump/pad_picture.state (the shaders are compiled at boot, before the game reads its
settings). At 5, only eglSwapBuffers is re-pointed, to note a change, and the game's shaders stay
its own; a change shows from the next start. Emulator-proven on the tester's V1.99B Kaiju card
(no state: shaders untouched, the store's 5s noted; BRIGHTNESS raised to 8 in the menu: noted,
"from its next start"; the next boot with that state: the step armed, "first fragment shader
carries the picture step"; the game back at 5: the state back to 5).

Round 2: the tester asked for them to be switched off for now. picture_settings.OFFERED is False:
the Write tab shows no tick, no build adds the rows or picture.cfg (a project that asked is told
why in the build log), and the Tips leave them out. The runtime half above stays, so a card that
still carries them never pays for them at 5."""

import os
import re

from pinball_decryptor.plugins.stern import picture_settings as PS
from pinball_decryptor.webui import help_content
from pinball_decryptor.webui.tabs import write as write_tab

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _body(src, head):
    """The C function starting at *head*, up to the closing brace in column 0."""
    start = src.index(head)
    return src[start:src.index("\n}\n", start)]


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def test_the_last_run_s_values_are_kept_where_the_runtime_can_write():
    src = _read(RUNTIME)
    m = re.search(r'PIC_STATE\[\]\s*=\s*"([^"]+)"', src)
    # /dump is the partition the runtime's own log and the game's core dumps already go to
    assert m and m.group(1) == "/dump/pad_picture.state"
    assert 'open("/dump/mode.log"' in src
    write = _body(src, "static void pic_state_write(void)")
    assert "O_CREAT" in write and "PIC_NAMES[PIC_B]" in write and "PIC_NAMES[PIC_S]" in write


def test_normal_is_the_factor_that_changes_nothing():
    src = _read(RUNTIME)
    away = _body(src, "static int pic_away(unsigned w, unsigned v)")
    assert "!= 1000" in away and "v <= pic_set[w].n" in away
    for key in PS.KEYS:
        assert PS.FACTORS[key][PS.NORMAL - 1] == 1000


def test_at_normal_only_the_swap_is_re_pointed_and_the_shaders_stay_the_game_s():
    arm = _body(_read(RUNTIME), "static void pic_arm(void)")
    # the decision is made from the last run before anything is re-pointed
    assert arm.index("pic_state_read();") < arm.index("pic_watching = !any;") < arm.index("if (pic_watching)")
    watch = arm[arm.index("if (pic_watching)"):arm.index("return;", arm.index("if (pic_watching)"))]
    assert "pic_got[PIC_SWAP]" in watch and "pic_watch_swap" in watch
    for other in ("PIC_SOURCE", "PIC_LINK", "PIC_USE", "pic_source", "pic_use"):
        assert other not in watch
    # the full step (every slot re-pointed) only after the watching branch has returned
    assert arm.index("if (pic_watching)") < arm.index("wrap[k]")
    # a rig's forced value still arms the step (the PAD-537 proofs)
    assert "pic_set[w].force ? pic_set[w].force : pic_ran[w]" in arm


def test_a_change_is_noted_with_the_step_on_or_off():
    src = _read(RUNTIME)
    note = _body(src, "static void pic_note(void)")
    assert "pic_state_write();" in note and "from its next start" in note
    # the game reading its store at boot (0 first) is not a value
    assert "v < 1 || v > pic_set[w].n" in note
    assert "pic_note();" in _body(src, "static unsigned pic_watch_swap(void *dpy, void *surf)")
    assert "pic_note();" in _body(src, "static void pic_tick(void)")


def test_the_menu_lines_and_tip_say_a_change_shows_from_the_next_start():
    for key in PS.KEYS:
        assert "after restart" in PS.HELP[key] and "5 is normal" in PS.HELP[key]
        assert len(PS.HELP[key]) <= 63
    tip = write_tab.PICTURE_TIP
    assert "next start" in tip and "draws exactly as it does without them" in tip
    assert "at once" not in tip


# ---- round 2: the tester asked for them to be switched off for now --------------------------------
def test_not_offered_a_saved_tick_is_kept_but_no_build_gets_them(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    assert PS.OFFERED is False
    PS.save(str(tmp_path), True)
    assert PS.asked(str(tmp_path)) is True and PS.load(str(tmp_path)) is False
    said = []
    assert E._picture_for_build(str(tmp_path), False, lambda m, *a: said.append(m)) is None
    assert said == [PS.SWITCHED_OFF]
    # a project that never asked: not a word
    said.clear()
    assert E._picture_for_build(str(tmp_path / "other"), False, lambda m, *a: said.append(m)) is None
    assert said == []


def test_not_offered_the_write_tab_shows_no_tick_and_refuses_one(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes

    class Mfr:
        key = "stern"
        current_era = "spike2"

    class Win:
        _running = False
        cb = {}

    monkeypatch.setattr(write_tab.WriteTab, "mfr", property(lambda self: Mfr()))
    svc = write_tab.WriteTab.__new__(write_tab.WriteTab)
    svc.window = Win()
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "cap", lambda n: True, raising=False)
    monkeypatch.setattr(svc, "_is_direct", lambda: False, raising=False)
    monkeypatch.setattr(svc, "_info_assets_dir", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "log", lambda *a, **k: None, raising=False)
    PS.save(str(tmp_path), True)
    svc._publish_picture()
    assert state == {"picture_cap": False}
    assert svc.set_picture(False) is False
    assert staged_changes.load(str(tmp_path))[PS.STAGED_KEY] == {"on": True}     # kept as it was


def test_not_offered_the_tips_leave_them_out():
    texts = list(_strings(help_content.HELP_CONTENT))
    assert not any("### Picture settings in the service menu" in t for t in texts)
