"""BOOT MENU FLIPPER (Simon, 2026-11-25, on the table: "in the service menu ... there is no "custom" so there is no way
to enable or disable the right flipper action"): a Service menu tab row the owner ticks, which the Write puts in the
game's own menu (1 Off, 2 after 20 s, 3 after 60 s), and ``padmenu.cfg`` beside the mode runtime saying where its value
is, for padmenu.so (codeselect/test/padmenu_flip_test.sh proves the reading under qemu)."""
import inspect
import os

import pytest

CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _program(card):
    if not os.path.isfile(card):
        pytest.skip("no %s on this machine" % os.path.basename(card))
    from pinball_decryptor.plugins.stern.explorer import CardImage
    from pinball_decryptor.plugins.stern.mode_tryit import card_title
    game, _version, part = card_title(card)
    with CardImage(card) as img:
        return img.preview(part, "/%s/game" % game, cap=256 << 20)


@pytest.fixture
def project(tmp_path, monkeypatch):
    from pinball_decryptor.core import staged_changes
    side = {}
    monkeypatch.setattr(staged_changes, "load", lambda p: dict(side))
    monkeypatch.setattr(staged_changes, "save", lambda p, d: (side.clear(), side.update(d)))
    return str(tmp_path), side


def test_the_row_is_unticked_to_start_and_ticks_like_the_others(project):
    from pinball_decryptor.plugins.stern import service_menu as SM
    path, side = project
    assert SM.FLIP_KEY == "boot_flip" and SM.FLIP_KEY in SM.TICK_KEYS
    assert SM.FLIP_KEY not in SM.on_keys(path)              # Simon: "Everything should be unchecked by default"
    SM.save(path, {"order": [], "on": [SM.FLIP_KEY]})
    assert side[SM.STAGED_KEY]["on"] == [SM.FLIP_KEY]
    assert SM.FLIP_KEY in SM.on_keys(path)
    assert SM.FLIP_KEY not in SM.off_keys(path) and SM.FLIP_KEY not in SM.OFF_KEYS   # never a placeholder


def test_a_ticked_row_is_wanted_by_the_write(project, monkeypatch):
    from pinball_decryptor.plugins.stern import boot_flip as BF
    from pinball_decryptor.plugins.stern import service_menu as SM
    path, _side = project
    assert not [w for w in SM.wanted(path) if w[0] == "boot_flip"]
    SM.save(path, {"on": ["boot_flip"]})
    got = [w for w in SM.wanted(path) if w[0] == "boot_flip"]
    assert got == [("boot_flip", 121, [], {"default": 16, "help_text": BF.MENU_HELP, "from_zero": True})]


def test_the_values_and_help():
    from pinball_decryptor.plugins.stern import boot_flip as BF
    from pinball_decryptor.plugins.stern import menu_settings as MS
    # Simon (2026-11-26): "we let the user set the values" - seconds, 0 Off, 15 to start with
    assert (BF.MAX_SECONDS, BF.MENU_VALUES, BF.DEFAULT_SECONDS, BF.MENU_DEFAULT) == (120, 121, 15, 16)
    assert MS.WIDE_VALUES == {"boot_flip": 121}
    assert len(BF.MENU_HELP) <= 63                          # the spare help lines' room
    assert BF.MENU_HELP == "R flipper 5s: boot menu. 0 Off, secs after game. Min/default 15"   # Simon's wording
    assert MS.SETTINGS[MS.BOOT_FLIP][1:] == ("BOOT MENU FLIPPER", "Boot Menu Flipper", 16)


def test_the_cfg_line_padmenu_reads():
    from pinball_decryptor.plugins.stern import boot_flip as BF
    assert BF.cfg_text(0x1234abcd, "boot_flip") == "flip_secs\t0x1234abcd\tboot_flip\t15\n"
    assert BF.cfg_text(0xFADE0008, "boot_flip", 0) == "flip_secs\t0xfade0008\tboot_flip\t0\n"
    src = open(os.path.join(ROOT, "tools", "spike2_emu", "codeselect", "padmenu.c"), encoding="utf-8").read()
    assert '"/usr/local/padmode/padmenu.cfg"' in src and "flip_secs %lx %39s %d" in src
    assert "quiet = v * 1000L;" in src and "if (v == 0)" in src
    assert '"/dump/pad_settings.state"' in src                 # the runtime's file for a MORE SETTINGS word
    assert "flip_row_ok()" in src                              # an address the game has not mapped is never read


def test_the_write_puts_the_row_and_its_file_on_the_card():
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    src = inspect.getsource(E)
    assert "flip_menu = (_BootFlipMenu(log) if not _is_spike3(disk_f)" in src
    assert "image_menu, saved_menu, flip_menu], log)" in src
    assert "mode_plan.flip_file = flip_cfg" in src
    assert "settings_cfg or flip_cfg)):" in src                # the runtime's files go on for this row alone too
    assert "or flip_cfg):" in src
    assert "flip_file" in {f.name for f in __import__("dataclasses").fields(MW.ModePlan)} \
        if hasattr(MW, "ModePlan") else "flip_file: str = \"\"" in inspect.getsource(MW)
    assert 'getattr(result, "flip_file", "")' in inspect.getsource(MW)


def test_the_cfg_file_from_a_planned_row(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E

    class _S:
        live, default = 0x00a1b2c4, 15
    job = E._BootFlipMenu(lambda *a, **k: None)
    job.setting = _S()
    path = E._boot_flip_cfg(job, str(tmp_path))
    assert os.path.basename(path) == "padmenu.cfg"
    assert open(path, encoding="utf-8").read() == "flip_secs\t0x00a1b2c4\tboot_flip\t15\n"


def test_the_service_menu_tab_offers_it(project, monkeypatch):
    from pinball_decryptor.webui.tabs import svcmenu
    keys = [k for k, _n, _w in svcmenu.SETTINGS]
    assert "boot_flip" in keys
    assert dict((k, n) for k, n, _w in svcmenu.SETTINGS)["boot_flip"] == "Boot Menu Flipper"
    src = inspect.getsource(svcmenu.ServiceMenuTab)
    assert "elif key in SM.TICK_KEYS:" in src and "elif key == SM.FLIP_KEY:" in src


def test_it_plans_on_godzilla_116_with_the_other_rows():
    from pinball_decryptor.plugins.stern import boot_flip as BF
    from pinball_decryptor.plugins.stern import menu_settings as MS
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    t = AdjustmentTable(_program(LE116))
    row = ("boot_flip", 121, (), {"default": 16, "help_text": BF.MENU_HELP, "from_zero": True})
    settings, _w, _c, refused = MS.plan_many(t, [row])
    assert not refused, refused
    s = next(s for s in settings if s.key == "boot_flip")
    assert not MS.is_shared(s) and s.live and s.default == 15 and s.help == BF.MENU_HELP
    assert (s.low, s.values) == (0, 121)
    # with five more rows the spare ones run out: it shares MORE SETTINGS and its word is the runtime's
    from pinball_decryptor.plugins.stern import coop_play as CP, handicap as HC
    from pinball_decryptor.plugins.stern import service_menu as SM
    names = list(SM.PLACEHOLDER_NAMES)
    rows = [(k, len(names), names) for k in SM.OFF_KEYS]
    rows += [("coop_play", CP.MENU_VALUES, (), {"default": 1, "help_text": CP.MENU_HELP, "from_zero": True}),
             ("handicap", HC.MENU_VALUES, (), {"default": 1, "help_text": HC.MENU_HELP, "onoff": True}), row]
    settings, _w, _c, refused = MS.plan_many(AdjustmentTable(_program(LE116)), rows)
    assert not refused, refused
    s = next(s for s in settings if s.key == "boot_flip")
    if MS.is_shared(s):
        assert s.live >= MS.SHARED_BASE
        assert "boot_flip" in MS.shared_cfg_text(settings)


def test_the_card_installer_and_the_emulator_carry_the_file():
    """The first end-to-end Write refused it: "padmenu.cfg is not a file the mode runtime reads"."""
    import importlib.util
    path = os.path.join(ROOT, "tools", "spike2_emu", "mode_install.py")
    spec = importlib.util.spec_from_file_location("mode_install_bf", path)
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("padmenu.cfg", 0o100644) in mi.EXTRA_FILES and "padmenu.cfg" in mi.STANDALONE_FILES
    emu = os.path.join(ROOT, "tools", "spike2_emu")
    tryit = open(os.path.join(emu, "modes", "tryit.sh"), encoding="utf-8").read()
    assert 'put "$S/padmenu.cfg" "$DUMP/padmenu.cfg"' in tryit
    assert tryit.count('"$DUMP"/padmenu.cfg') == 2              # cleared with the other runtime files
    cm = open(os.path.join(emu, "modes", "cardmodes.sh"), encoding="utf-8").read()
    assert cm.count('"$DUMP/padmenu.cfg"') == 1 and cm.count('"$DUMP"/padmenu.cfg') == 1   # both clear-outs
    src = open(os.path.join(emu, "codeselect", "padmenu.c"), encoding="utf-8").read()
    assert '"/dump/padmenu.cfg"' in src                        # the rig's place for it


def test_the_row_alone_is_a_write_of_its_own():
    """The second end-to-end Write (the row and nothing else) stopped twice: "Screen times: the app could not tell which
    game..." and then "none of the project's random clips can go on this card"."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    src = inspect.getsource(E)
    assert 'else "Service menu settings")' in src
    assert "if (flip_cfg or settings_cfg) and not (mode_list or code_list):" in src
    assert "scenes_prof, _menu_prof))" in src
    assert "menu_prof=_menu_prof or _mprof if (flip_cfg or settings_cfg) else None" in src
    assert "menu_prof=None" in str(inspect.signature(MW.plan))
    plan_src = inspect.getsource(MW.plan)
    assert "if result is None and menu_prof is not None:" in plan_src
    assert "result = menu_plan(project, game_elf, menu_prof)" in plan_src


def test_menu_plan_carries_the_runtime_and_the_port(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW

    class _P:
        label = "Godzilla LE 1.16"
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: "/x/game.port")
    plan = MW.menu_plan("proj", b"elf", _P())
    assert plan.port == "/x/game.port" and plan.build is None and plan.profile.label == "Godzilla LE 1.16"

    def _no(prof, elf):
        raise MW.ModeWriteError("no")
    monkeypatch.setattr(MW, "find_port", _no)
    with pytest.raises(MW.ModeWriteError, match="service menu settings"):
        MW.menu_plan("proj", b"elf", _P())


def test_the_emulator_runs_a_multi_boot_cards_own_runtime_files():
    """A multi-boot card's hook preloads padmenu.so and the runtime on one line; the rig looked for the plain hook only
    and ran neither the card's runtime nor its padmenu.cfg."""
    src = open(os.path.join(ROOT, "tools", "spike2_emu", "modes", "cardmodes.sh"), encoding="utf-8").read()
    assert 'grep -qF -e "$HOOK" -e "PADPRE:}$CARD_DIR/mode.so"' in src
    assert 'FLIPROW=$(grep -c "^flip_secs\t" "$S/padmenu.cfg"' in src
    assert '[ "$SCENES" = 0 ] && [ "$FLIPROW" = 0 ]; }; then' in src
