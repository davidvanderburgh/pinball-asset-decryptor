"""A stock rule's shot logic rewritten in C (item 161): the desk-checkable parts. The header's
calls are in the runtime, both Godzilla ports carry the lines the accessors read, the example
registers Ebirah's rule, the project side finds a rewrite among the code modes and makes one from
the template, and Write's words name what it replaces. Nothing here runs the game."""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import stock_remap as SR
from pinball_decryptor.plugins.stern import stock_rewrite as SW

SDK = MR.sdk_dir()
HEADER = os.path.join(SDK, "pad_stock.h")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
EXAMPLE = os.path.join(SDK, "examples", "ebirah_rewrite.c")
_CALL = re.compile(r"^(?:[A-Za-z_][\w \*]*?\s\*?)(pm_[a-z_0-9]+)\s*\(", re.M)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_every_call_the_header_declares_is_defined_in_the_runtime():
    header = _read(HEADER)
    runtime = _read(RUNTIME)
    calls = sorted(set(_CALL.findall(header)))
    assert len(calls) >= 30 and "pm_stock_call_original" in calls and "pm_stock_final_blow" in calls
    for c in calls:
        assert re.search(r"^[A-Za-z_][\w \*]*?\b%s\s*\(" % re.escape(c), runtime, re.M), c
    # the section walk and the wrap's two branches
    assert "__start_pm_stock" in runtime and "stock161_attach();" in runtime
    assert "if (x->in_original) return x->orig(" in runtime and "stock161_first(x, &shot, s0)" in runtime
    assert '"pad_stock.h"' in runtime


def test_the_header_is_a_source_of_the_pinned_object():
    assert "pad_stock.h" in MR.SOURCES
    with open(MR.sources_file(), encoding="utf-8") as f:
        assert " pad_stock.h" in f.read()


@pytest.mark.parametrize("game_dir,version,slot_shot", [("godzilla_le", "1.16", 42), ("godzilla_pro", "1.15", 41)])
def test_both_godzilla_ports_carry_the_accessors_lines(game_dir, version, slot_shot):
    text = _read(MR.port_file(game_dir, version))
    values = dict(re.findall(r"^value\s+(\S+)\s+(\S+)", text, re.M))
    sites = re.findall(r"^site\s+(\S+)\s+0x[0-9a-f]+\s+0x[0-9a-f]+\s+0x[0-9a-f]+", text, re.M)
    data = re.findall(r"^data\s+(\S+)\s+0x[0-9a-f]+", text, re.M)
    for s in ("stock_rule_get", "caward_add", "caward_build", "show_start", "game_event", "event_post_replacing",
              "event_cancel", "ebirah_refill_counts", "ebirah_stage_done", "ebirah_award_screen", "ebirah_final_mask",
              "tank_maser_phase", "tank_destroy", "tank_seed_wave", "tank_advance"):
        assert s in sites, s
    assert int(values["stock_slot_shot"], 0) == slot_shot
    assert (int(values["stock_slot_start"], 0), int(values["stock_slot_stop"], 0), int(values["stock_slot_lit"], 0)) == (8, 11, 25)
    assert int(values["stock_field"], 0) == 0x18 and int(values["stock_award_at"], 0) == 0x50
    assert int(values["ebirah_rule"], 0) == 12 and int(values["tank_rule"], 0) == 4
    assert (int(values["ebirah_spin_left_bit"], 0), int(values["ebirah_spin_top_bit"], 0), int(values["ebirah_spin_shield_bit"], 0)) == (0x200, 0x2000, 0x20000)
    assert int(values["ebirah_final_shot"], 0) == 0x40 and int(values["ebirah_final_mask_hi"], 0) == 0x400
    assert (int(values["tank_records_at"], 0), int(values["tank_record_size"], 0)) == (0x68, 40)
    for d in ("ebirah_stage_awards", "ebirah_lamp_table", "tank_path", "tank_spot_list"):
        assert d in data, d
    # every site named once: the runtime keeps the first, so a repeat would hide a wrong word pair
    assert len(sites) == len(set(sites))
    # the ports still fit the runtime's tables (the caps grew for these lines)
    src = _read(RUNTIME)
    assert len(sites) <= int(re.search(r"#define N_SITES\s+(\d+)", src).group(1))
    assert len(values) <= int(re.search(r"#define N_VALUES\s+(\d+)", src).group(1))


def test_the_example_registers_ebirahs_rule_and_uses_only_port_names():
    text = _read(EXAMPLE)
    assert SW.rule_of(EXAMPLE) == 12
    assert 'pm_shot("Left ramp")' in text or '"Left ramp"' in text
    assert "pm_stock_final_blow" in text and "pm_ebirah_stage_award" in text and "PM_STOCK_RULE(" in text
    assert not re.search(r"0x[0-9a-f]{5,}", text.split("#include")[0]), "no address in the header comment"
    assert not re.search(r"\b0x(7b|d3|81|85)[0-9a-f]{4}\b", text), "no game address in the example"


def _project(tmp_path, image_name="godzilla_le-1_16_0.raw"):
    import json
    proj = tmp_path / "gz"
    proj.mkdir()
    with open(proj / ".extract_source.json", "w", encoding="utf-8") as f:
        json.dump({"input_path": str(proj / image_name), "input_name": image_name}, f)
    return str(proj)


def test_rows_and_a_new_rewrite_from_the_template(tmp_path):
    proj = _project(tmp_path)
    port = MP.port_path(MP.profile_for_card("godzilla_le", "1.16"))
    rows = SW.rows(proj, port)
    assert [(r["id"], r["slug"], r["template"]) for r in rows] == [(12, "", "ebirah_rewrite.c"), (4, "", "")]
    assert rows[0]["status"].startswith("the game's own (a template is ready")
    assert "no template" in rows[1]["status"]
    with pytest.raises(SW.StockRewriteError, match="no template"):
        SW.new_rewrite(proj, 4, port)
    with pytest.raises(SW.StockRewriteError, match="names no rule 99"):
        SW.new_rewrite(proj, 99, port)
    slug, path = SW.new_rewrite(proj, 12, port)
    assert slug == "ebirah_rewrite" and os.path.isfile(path)
    assert os.path.isfile(os.path.join(os.path.dirname(path), CM.ASSETS_FILE))
    assert SW.rewrites(proj) == {12: "ebirah_rewrite"}
    assert CM.code_slugs(proj) == ["ebirah_rewrite"] and MW.code_modes(proj) == ["ebirah_rewrite"]
    spec = CM.load(proj, slug)
    assert spec.name.startswith("EBIRAH") and not spec.has_assets()
    rows = SW.rows(proj, port)
    assert rows[0]["slug"] == "ebirah_rewrite" and rows[0]["status"] == "rewritten by modes/ebirah_rewrite/ebirah_rewrite.c"
    with pytest.raises(SW.StockRewriteError, match="already rewritten"):
        SW.new_rewrite(proj, 12, port)
    # a second folder for the same rule is not what the tab makes, but the scan keeps the first
    assert SW.describe_suffix(proj, slug, port) == (" - replaces the shots of Battle vs Ebirah (the game's own rule plays "
                                                    "its shots through this code)")
    assert SW.describe_suffix(proj, slug) == " - replaces the shots of rule 12 (the game's own rule plays its shots through this code)"


def test_write_carries_a_rewrite_as_a_code_mode_and_says_what_it_replaces(tmp_path):
    proj = _project(tmp_path)
    port = MP.port_path(MP.profile_for_card("godzilla_le", "1.16"))
    slug, path = SW.new_rewrite(proj, 12, port)
    lines = MW.pending_lines(proj)
    mine = [l for l in lines if "EBIRAH" in l]
    assert len(mine) == 1, lines
    assert "(code mode): its code (ebirah_rewrite.c), built into the card's mode.so" in mine[0]
    assert "replaces the shots of Battle vs Ebirah" in mine[0]

    class Ex:
        def to_exec_path(self, p):
            return "/mnt/" + p.replace("\\", "/").replace(":", "")
    cmd = MW.compile_command(Ex(), os.path.join(str(tmp_path), "mode.so"), [path])
    assert "build_mode.sh" in cmd and "ebirah_rewrite/ebirah_rewrite.c" in cmd and cmd.rstrip().endswith("mode_file.c")
