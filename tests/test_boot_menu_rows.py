"""BOOT MENU and BOOT MENU TIMER: the multi-boot card's boot menu, changed from the games' service menus.

Simon (2026-11-27): "No boot menu with facility to enable/disable via service menu. Boot menu with ditto. Bootmenu - no
service menu option (always boots to menu). We should also be able to set boot menu timer OFF/15 seconds. 30 seconds".

- The Multi-boot tab's "Boot menu" choice: hidden + menu_rows=on, shown + menu_rows=on, or shown, always.
- Two rows the Service menu tab can tick, written like BOOT MENU FLIPPER: padmenu.cfg says where their values are.
- padmenu.so (in each game) keeps the card's one value in /data/padmenu.boot and puts it in the rows; codeselect reads
  it at power-up; the mode runtime loads it for the shared MORE SETTINGS rows.
"""
import inspect
import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CS = os.path.join(REPO, "tools", "spike2_emu", "codeselect")
RUNTIME = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def test_the_rows_values_and_help():
    from pinball_decryptor.plugins.stern import boot_flip as BF
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import menu_settings as MS
    key, values, names, opts = E._BootShowMenu(lambda *a: None).wanted()
    assert (key, values, names) == ("boot_show", 2, ())
    assert opts == {"default": 2, "help_text": BF.SHOW_HELP, "onoff": True}          # On to start with (2 counts from 1)
    key, values, names, opts = E._BootTimerMenu(lambda *a: None).wanted()
    assert (key, values) == ("boot_timer", 3)                                          # 0, 15, 30
    assert opts == {"default": 1, "help_text": BF.TIMER_HELP, "from_zero": True}      # 0 (Off) to start with
    assert MS.STEPS["boot_timer"] == 15
    assert len(BF.SHOW_HELP) <= 63 and len(BF.TIMER_HELP) <= 63
    # both take effect at the next power-up: "(*)" on their rows
    assert {"boot_show", "boot_timer"} <= MS.POWER_UP
    assert MS.shown_caption("boot_show") == "Boot Menu (*)"
    assert MS.SETTINGS["boot_timer"][1] == "BOOT MENU TIMER"


def test_ticked_on_the_service_menu_tab_the_write_asks_for_them(tmp_path):
    from pinball_decryptor.plugins.stern import service_menu as SM
    from pinball_decryptor.webui.tabs import svcmenu
    p = str(tmp_path)
    assert {"boot_show", "boot_timer"} <= set(SM.TICK_KEYS) and SM.BOOT_KEYS == ("boot_flip", "boot_show", "boot_timer")
    assert [k for k, _n, _w in svcmenu.SETTINGS if k.startswith("boot_")] == ["boot_show", "boot_timer", "boot_flip"]
    assert [r[0] for r in SM.wanted(p)] == []
    SM.save(p, {"on": ["boot_show", "boot_timer", "boot_flip"]})
    assert [r[0] for r in SM.wanted(p)] == ["boot_flip", "boot_show", "boot_timer"]


def test_the_cfg_file_names_every_row_that_went_on(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E

    def job(cls, live, default):
        j = cls(lambda *a, **k: None)
        j.setting = type("S", (), {"live": live, "default": default})()
        return j
    path = E._boot_flip_cfg(job(E._BootFlipMenu, 0x00a1b2c4, 15), str(tmp_path),
                            job(E._BootShowMenu, 0x00a1b2c8, 1), job(E._BootTimerMenu, 0xfade0008, 0))
    assert open(path, encoding="utf-8").read() == (
        "flip_secs\t0x00a1b2c4\tboot_flip\t15\n"
        "boot_show\t0x00a1b2c8\tboot_show\t1\n"
        "boot_timer\t0xfade0008\tboot_timer\t0\n")
    path = E._boot_flip_cfg(None, str(tmp_path), job(E._BootShowMenu, 0x00a1b2c8, 1))     # the show row alone
    assert open(path, encoding="utf-8").read() == "boot_show\t0x00a1b2c8\tboot_show\t1\n"
    src = inspect.getsource(E)
    assert "_ok = lambda m: m if m is not None and m.ok else None" in src     # a row that did not go on is left out


def test_the_card_builder_writes_and_reads_menu_rows():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mkmulticard", os.path.join(REPO, "tools", "spike2_emu",
                                                                              "mkmulticard.py"))
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    assert "menu_rows" in mk.CONF_KEYS
    src = inspect.getsource(mk)
    assert 'out.append("menu_rows=on")' in src
    assert 'conf["menu_rows"] = val.strip() == "on"' in src
    assert '"--menu-rows"' in src and '"--no-menu-rows"' in src
    assert 'menu_rows=conf.get("menu_rows")' in src                       # an inject rewrite keeps it


def test_the_tab_passes_the_choice():
    from pinball_decryptor.webui import multiboot_core as MC
    form = MC.MultiForm() if hasattr(MC, "MultiForm") else None
    if form is None:
        form = next(c for c in vars(MC).values() if isinstance(c, type) and "flip_guard" in
                    getattr(c, "__dataclass_fields__", {}))()
    form.boot_menu, form.menu_rows = "hidden", True
    args = MC.flip_args(form) if MC.backend_for(form).key == "stern" else ["--menu-rows"]
    assert "--menu-rows" in args
    js = _read(REPO, "pinball_decryptor", "webui", "static", "js", "tabs", "multiboot.js")
    for words in ("No boot menu: the service menu can turn it on", "Boot menu: the service menu can turn it off",
                  "Boot menu, always (the service menus cannot change it)"):
        assert words in js
    # David (PR #53 review: "flexibility for each person"): the countdown stays any seconds, as before; the note says
    # what the service menus' Boot Menu Timer can set it to
    assert 'k="timeout" value=${s.timeout} ...${num} max=${600}' in js and "timerOpts" not in js
    assert "can change it to Off, 15 or 30 s (Boot Menu Timer)" in js


def test_the_boot_menu_reads_the_card_value_only_where_the_card_allows():
    src = _read(CS, "codeselect.c")
    assert '#define BOOT_FILE "/data/padmenu.boot"' in src
    assert "if (c.menu_rows && !o.snapshot) {" in src
    i = src.index("if (c.menu_rows && !o.snapshot) {")
    assert i < src.index("timeout = o.timeout >= 0 ? o.timeout : c.timeout >= 0 ? c.timeout : DEF_TIMEOUT;")
    assert i < src.index("if (c.boot_menu == BOOT_MENU_HIDDEN && !pinned && !asked_menu) {")
    assert 'c->menu_rows = !strcmp(val, "on");' in _read(CS, "conf.c")


def test_padmenu_keeps_the_cards_value_and_puts_it_in_the_rows():
    src = _read(CS, "padmenu.c")
    assert '#define CARD_FILE      "/data/padmenu.boot"' in src
    assert 'if (!conf_word(conf, "menu_rows", w, sizeof w) || strcmp(w, "on"))' in src   # the tab's "always": nothing
    assert "card_tick(t);" in src and "card_init(conf, line);" in src
    assert "*(volatile uint32_t *)(uintptr_t)r->addr = v;" in src                        # the menu shows the card's:
    assert "((volatile unsigned char *)(uintptr_t)r->addr)[4] = (unsigned char)~" in src  # with its check byte
    assert "card_mapped(r->addr, 1)" in src                                              # only a writable word


def test_the_runtime_loads_the_cards_value_for_the_shared_rows():
    src = _read(RUNTIME)
    assert 'static const char MSET_BOOT_FILE[] = "/data/padmenu.boot";' in src
    body = src[src.index("static void mset_boot_card(void)"):]
    body = body[:body.index("\n}\n")]
    assert 'if (mset_boot_word(conf, n, "menu_rows", \'=\') != -2) return;' in body
    assert 'str_eq(mset_opt[k].key, "boot_show")' in body and 'str_eq(mset_opt[k].key, "boot_timer")' in body
    read = src[src.index("static void mset_state_read(void)"):]
    assert read.count("mset_boot_card();") == 2                          # with a state file and without


CARDS = os.environ.get("PAD494_CARDS", r"D:\Pinball\images\Stern\spike2")
LE116 = os.path.join(CARDS, "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw")


def test_all_three_plan_on_godzilla_116_with_co_op_and_handicap():
    if not os.path.isfile(LE116):
        pytest.skip("no godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw on this machine")
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import menu_settings as MS
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    from tests.test_svcmenu_placeholders_card import _program
    rows = [E._BootFlipMenu(lambda *a: None).wanted(), E._BootShowMenu(lambda *a: None).wanted(),
            E._BootTimerMenu(lambda *a: None).wanted(), E._HandicapMenu(lambda *a: None).wanted()]
    t = AdjustmentTable(_program(LE116))
    settings, _w, _c, refused = MS.plan_many(t, rows)
    assert not refused, refused
    keys = {s.key for s in settings}
    assert {"boot_flip", "boot_show", "boot_timer", "handicap"} <= keys
    timer = next(s for s in settings if s.key == "boot_timer")
    assert timer.low == 0
