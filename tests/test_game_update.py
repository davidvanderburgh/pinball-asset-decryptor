"""PAD-1585: "Update to 1.0.1" - a machine's project carried onto Stern's newer build (core/game_update.py, the
app's _start_machine_update gate, My machines' machines_update)."""
from types import SimpleNamespace

import pytest

from pinball_decryptor.core import game_update as G


def _reader(table):
    return lambda card: table[card]


def test_the_new_image_must_be_the_same_game_and_newer():
    r = _reader({"old.raw": ("godzilla_pro", "1.15.0"), "new.raw": ("godzilla_pro", "1.16.0"),
                 "same.raw": ("godzilla_pro", "1.15.0"), "older.raw": ("godzilla_pro", "1.9.0"),
                 "kk.raw": ("king_kong_pro", "1.01.0")})
    old, new = G.check_new_card("old.raw", "new.raw", r)
    assert "1.15" in old and "1.16" in new
    for bad, words in (("same.raw", "already runs"), ("older.raw", "already runs"), ("kk.raw", "own game")):
        with pytest.raises(G.UpdateRefused, match=words):
            G.check_new_card("old.raw", bad, r)


def test_versions_compare_as_numbers_not_text():
    r = _reader({"a": ("g", "1.9.0"), "b": ("g", "1.10.0")})
    assert G.check_new_card("a", "b", r)


def test_an_unreadable_new_image_is_refused_in_words():
    def boom(card):
        raise ValueError("no game program")
    with pytest.raises(G.UpdateRefused, match="not a Stern Spike 2 card image"):
        G.check_new_card("old.raw", "x.raw", boom)


def _plan(**over):
    plan = {"audio": {"matched": [1, 2], "remapped": [3], "flagged": [], "dropped": []},
            "video": {"matched": [1], "dropped": []}, "image": {"matched": [], "dropped": []},
            "text": {"matched": [1, 2, 3, 4], "dropped": []}}
    plan.update(over)
    return plan


def test_a_clean_update_says_what_carries_and_asks_nothing_more():
    rep = G.carry_report(_plan(), [("info", "moved")], new_label="Godzilla Pro 1.16")
    assert rep["clean"] and rep["carried"] == ["3 sounds", "1 video", "4 text edits"]
    title, msg = G.question(rep)
    assert "Everything in the project carries over" in msg and "1.16" in title


def test_what_cant_be_carried_is_named_before_the_build():
    lines = [("error", "Transfer: 1 audio replacement(s) can NOT be carried"), ("info", "fine"),
             ("warning", "Transfer: 2 video replacement(s) went to the clip in the same place")]
    rep = G.carry_report(_plan(text={"matched": [], "dropped": [1, 2]}), lines,
                         "This project's 3 modes can't run on Godzilla Pro 1.16 yet: ...", True, "Godzilla Pro 1.16")
    assert not rep["clean"]
    assert len(rep["left_out"]) == 3 and rep["left_out"][-1].startswith("2 text edits cannot be carried")
    title, msg = G.question(rep)
    assert "without these" in title
    assert "can NOT be carried" in msg and "modes can't run" in msg and "or wait" in msg
    assert "nothing has been written" in msg


def test_modes_that_can_run_are_not_listed_as_left_out():
    rep = G.carry_report(_plan(), [], "This project's 3 modes run on Godzilla Pro 1.16.", False)
    assert rep["clean"] and not rep["modes"]


def test_a_long_list_is_capped_with_the_rest_in_the_log():
    rep = G.carry_report(_plan(), [("error", "x%d" % i) for i in range(20)])
    _t, msg = G.question(rep, cap=5)
    assert "and 15 more" in msg


# ---- the app's chain: the question stops it before anything is applied or built ----------------------
def test_the_gate_runs_after_the_plan_and_before_apply_and_a_no_skips_the_build(monkeypatch):
    from pinball_decryptor import app as A
    from pinball_decryptor.core import mod_port, mod_transfer
    calls = []
    monkeypatch.setattr(mod_transfer, "plan_transfer",
                        lambda *a, **kw: calls.append("plan") or {"totals": {"transfer": 3, "flagged": 0}})
    monkeypatch.setattr(mod_transfer, "plan_detail_lines", lambda plan: [])
    monkeypatch.setattr(mod_transfer, "apply_transfer", lambda *a, **kw: calls.append("apply") or {})

    def gate(ws, plan):
        calls.append("gate")
        raise mod_port.PortSkip("stopped before building: nothing was written")

    got = {}

    def run_ports(jobs, extract, transfer, stage, write, log, cancel):
        try:
            transfer("ws")
        except mod_port.PortSkip as e:
            got["skip"] = str(e)
        return [(jobs[0], "skipped", got.get("skip", ""))]

    monkeypatch.setattr(mod_port, "run_ports", run_ports)
    q = []
    app = SimpleNamespace(msg_queue=SimpleNamespace(put=q.append), _cancel_requested=False,
                          _report_news=lambda *a, **kw: None, _CARD_SIZE_ENV="PAD_STERN_CARD_SIZE",
                          _apply_card_size_env=lambda *a: None, _card_size_setting=lambda: "",
                          _port_sub_runner=lambda: (lambda *a, **k: None, None, None,
                                                    SimpleNamespace(step_done=None)))
    after = []
    A.App._run_port_chain(app, "proj", [{"workspace": "ws", "raw": "new.raw", "output": "out.raw"}],
                          gate=gate, after=after.append)
    assert calls == ["plan", "gate"]                       # never applied
    assert "nothing was written" in got["skip"]
    assert [type(m).__name__ for m in q] == ["DoneMsg", "UiCallMsg"]
    q[1].fn()                                             # the after-callback, on the UI thread
    assert after and after[0][0][1] == "skipped"


# ---- My machines: the RPC and the hand-over to the Write tab ------------------------------------------
class _Var:
    def __init__(self):
        self.v = ""

    def set(self, v):
        self.v = v

    def get(self):
        return self.v


def test_machines_update_starts_the_update_and_hands_the_build_to_the_write_tab(monkeypatch, tmp_path):
    from pinball_decryptor.webui import shellx_machines as SM
    build = tmp_path / "godzilla_pro-1_16_0 - proj.raw"; build.write_bytes(b"x")
    started, rebound, shown, tabs = {}, [], [], []
    host = SM.ShellxMachines.__new__(SM.ShellxMachines) if hasattr(SM, "ShellxMachines") else None
    if host is None:
        cls = next(c for c in vars(SM).values() if isinstance(c, type) and hasattr(c, "machines_update"))
        host = cls.__new__(cls)
    row = {"name": "My Godzilla", "transfer": True, "card_missing": False, "project": "proj", "card": "old.raw"}
    monkeypatch.setattr(type(host), "_open_machine_project", lambda self, mid: row, raising=False)
    monkeypatch.setattr(type(host), "machines_rebind", lambda self, mid, path=None: rebound.append(path),
                        raising=False)
    monkeypatch.setattr(SM.compat.messagebox, "showinfo", lambda t, m: shown.append(m))
    w = SimpleNamespace(write_upd_var=_Var(), write_assets_var=_Var(), write_output_var=_Var(),
                        write_filename_var=_Var(), select_tab=tabs.append)

    def start(mid, project, card, on_built=None):
        started.update(mid=mid, project=project, card=card)
        on_built(str(build), "ws_new", "new.raw")
        return True

    host.window = w
    touched = []
    host.app = SimpleNamespace(_start_machine_update=start, _registry_touch=touched.append,
                               _save_settings=lambda: touched.append("saved"))
    fn = getattr(type(host).machines_update, "__wrapped__", type(host).machines_update)
    assert fn(host, "m1") is True
    assert started == {"mid": "m1", "project": "proj", "card": "old.raw"}
    assert w.write_upd_var.v == "new.raw" and w.write_assets_var.v == "ws_new"
    assert w.write_filename_var.v == build.name and rebound == [str(build)] and tabs == ["write"]
    assert "Send to machine" in shown[0] and "Keep the card's own settings" in shown[0]
    assert touched == ["ws_new", "saved"]                  # the new project is known, so the row names it


def test_the_row_offers_the_update_only_with_a_project_and_newer_code():
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "pinball_decryptor" / "webui" / "static" / "js"
          / "shell.js").read_text(encoding="utf-8")
    m = re.search(r'\$\{r\.newer && proj && r\.transfer \? html`<\$\{Button\}[^`]*machines_update[^`]*Update to '
                  r'\$\{r\.newer\}', js)
    assert m, "the Update to <newer> button on the My machines row"


# ---- modes: checked by shot name before the question, carried after a yes ---------------------------
def _modes(monkeypatch, found, broken=(), codes=(), port=True, dropped=None, problems=None):
    from pinball_decryptor.plugins.stern import code_modes as CM
    from pinball_decryptor.plugins.stern import mode_project as MP
    p = SimpleNamespace(label="King Kong LE 1.01")
    monkeypatch.setattr(MP, "list_modes", lambda proj: (list(found), list(broken)))
    monkeypatch.setattr(CM, "code_slugs", lambda proj: list(codes))
    monkeypatch.setattr(MP, "project_profile", lambda ws: (object(), p if port else None))
    monkeypatch.setattr(MP, "retarget", lambda spec, prof: (spec, (dropped or {}).get(spec.name, [])))
    monkeypatch.setattr(MP, "validate", lambda spec, folder=None: (problems or {}).get(spec.name, []))
    monkeypatch.setattr(MP, "mode_folder", lambda proj, slug: proj + "/modes/" + slug)
    return MP


def test_modes_that_keep_every_shot_carry_and_the_rest_are_named(monkeypatch):
    found = [("kong", SimpleNamespace(name="KONG RAMPAGE")), ("skull", SimpleNamespace(name="SKULL ISLAND")),
             ("boat", SimpleNamespace(name="BOAT"))]
    _modes(monkeypatch, found, broken=[("bad", "bad json")], codes=["mycode"],
           dropped={"SKULL ISLAND": ["Left Skull Ramp"]}, problems={"BOAT": ["it needs a ball save"]})
    carry, left = G.modes_check("old", "ws")
    assert carry == ["kong", "mycode"]
    assert any("SKULL ISLAND" in l and "Left Skull Ramp" in l and "stays in the old project" in l for l in left)
    assert any("BOAT" in l and "ball save" in l for l in left)
    assert any("bad" in l and "does not load" in l for l in left)
    rep = G.carry_report(_plan(), [], modes_left=left, new_label="King Kong LE 1.01")
    assert not rep["clean"] and len(rep["left_out"]) == 3


def test_no_port_for_the_new_build_carries_no_modes_and_lets_mode_news_say_it(monkeypatch):
    _modes(monkeypatch, [("kong", SimpleNamespace(name="KONG"))], port=False)
    assert G.modes_check("old", "ws") == ([], [])


def test_carry_modes_copies_only_the_ones_that_carry(monkeypatch):
    MP = _modes(monkeypatch, [])
    got = {}

    def copy_modes(src, dest, slugs=None, replace=False):
        got.update(src=src, dest=dest, slugs=slugs)
        return SimpleNamespace(lines=lambda: ["KONG -> modes/kong: runs on KK as it is"],
                               summary=lambda: "Copied 1 mode into ws for KK.\n\nKONG ...")
    monkeypatch.setattr(MP, "copy_modes", copy_modes)
    logs = []
    assert G.carry_modes("old", "ws", ["kong"], log=lambda t, l="info": logs.append(t)) == \
        "Copied 1 mode into ws for KK."
    assert got == {"src": "old", "dest": "ws", "slugs": ["kong"]} and logs
    assert G.carry_modes("old", "ws", []) == ""


def test_the_gates_follow_up_runs_after_the_transfer_is_applied(monkeypatch):
    from pinball_decryptor import app as A
    from pinball_decryptor.core import mod_port, mod_transfer
    calls = []
    monkeypatch.setattr(mod_transfer, "plan_transfer",
                        lambda *a, **kw: {"totals": {"transfer": 3, "flagged": 0}})
    monkeypatch.setattr(mod_transfer, "plan_detail_lines", lambda plan: [])
    monkeypatch.setattr(mod_transfer, "apply_transfer",
                        lambda *a, **kw: calls.append("apply") or {"audio": 1, "video": 0, "image": 0, "text": 2})
    got = {}

    def run_ports(jobs, extract, transfer, stage, write, log, cancel):
        got["detail"] = transfer("ws")
        return [(jobs[0], "ok", got["detail"])]
    monkeypatch.setattr(mod_port, "run_ports", run_ports)
    app = SimpleNamespace(msg_queue=SimpleNamespace(put=lambda m: None), _cancel_requested=False,
                          _report_news=lambda *a, **kw: None, _CARD_SIZE_ENV="PAD_STERN_CARD_SIZE",
                          _apply_card_size_env=lambda *a: None, _card_size_setting=lambda: "",
                          _port_sub_runner=lambda: (lambda *a, **k: None, None, None,
                                                    SimpleNamespace(step_done=None)))
    A.App._run_port_chain(app, "proj", [{"workspace": "ws", "raw": "n.raw", "output": "o.raw"}],
                          gate=lambda ws, plan: (lambda ws2: calls.append("modes") or "Copied 1 mode"))
    assert calls == ["apply", "modes"] and got["detail"].endswith("; Copied 1 mode")
