"""The one-click port sequencing (core.mod_port).

The heavy steps (extract / transfer / stage / write) are injected callables,
so these cover the pure chain logic: job planning + naming, skip-if-already-
extracted, continue-past-a-failed-target, the nothing-transfers skip, and
cancellation at each boundary."""

import os

import pytest

from pinball_decryptor.core import mod_port
from pinball_decryptor.core.checksums import CHECKSUMS_FILE


def _jobs(tmp_path, n=2):
    raws = []
    for i in range(n):
        raw = tmp_path / ("stock%d.raw" % i)
        raw.write_bytes(b"card")
        raws.append(str(raw))
    return mod_port.plan_ports(str(tmp_path / "proj"), raws,
                               str(tmp_path / "out"))


def _recorder(calls, name, result=None, boom=None):
    def fn(*a):
        calls.append((name,) + tuple(os.path.basename(str(x)) for x in a))
        if boom is not None:
            raise boom
        return result
    return fn


def _quiet(_t, _l="info"):
    pass


def test_plan_names_keep_target_and_project_apart(tmp_path):
    jobs = _jobs(tmp_path, 1)
    j = jobs[0]
    assert os.path.basename(j["output"]) == "stock0 - proj.raw"
    assert os.path.basename(j["workspace"]) == (
        "stock0" + mod_port.EXTRACT_SUFFIX)
    assert os.path.dirname(j["output"]) == str(tmp_path / "out")


def test_full_chain_runs_every_step_in_order(tmp_path):
    jobs = _jobs(tmp_path, 2)
    calls = []
    res = mod_port.run_ports(
        jobs,
        extract=_recorder(calls, "extract"),
        transfer=_recorder(calls, "transfer", result="3 things"),
        stage=_recorder(calls, "stage"),
        write=_recorder(calls, "write"),
        log=_quiet, cancel=lambda: False)
    assert [s for _j, s, _d in res] == ["ok", "ok"]
    assert res[0][2] == "3 things"
    steps = [c[0] for c in calls]
    assert steps == ["extract", "transfer", "stage", "write"] * 2


def test_existing_extract_is_reused(tmp_path):
    jobs = _jobs(tmp_path, 1)
    ws = jobs[0]["workspace"]
    os.makedirs(ws)
    with open(os.path.join(ws, CHECKSUMS_FILE), "w") as f:
        f.write("x")
    calls = []
    res = mod_port.run_ports(
        jobs,
        extract=_recorder(calls, "extract"),
        transfer=_recorder(calls, "transfer"),
        stage=_recorder(calls, "stage"),
        write=_recorder(calls, "write"),
        log=_quiet, cancel=lambda: False)
    assert res[0][1] == "ok"
    assert "extract" not in [c[0] for c in calls]


def test_failed_target_does_not_stop_the_rest(tmp_path):
    jobs = _jobs(tmp_path, 3)
    calls = []

    def flaky_write(raw, ws, out):
        calls.append(("write", os.path.basename(raw)))
        if raw == jobs[1]["raw"]:
            raise RuntimeError("disk full")
    res = mod_port.run_ports(
        jobs,
        extract=_recorder(calls, "extract"),
        transfer=_recorder(calls, "transfer"),
        stage=_recorder(calls, "stage"),
        write=flaky_write,
        log=_quiet, cancel=lambda: False)
    assert [s for _j, s, _d in res] == ["ok", "failed", "ok"]
    assert "disk full" in res[1][2]


def test_nothing_to_transfer_skips_the_build(tmp_path):
    jobs = _jobs(tmp_path, 1)
    calls = []

    def no_mods(ws):
        raise mod_port.PortSkip("no matching slots")
    res = mod_port.run_ports(
        jobs,
        extract=_recorder(calls, "extract"),
        transfer=no_mods,
        stage=_recorder(calls, "stage"),
        write=_recorder(calls, "write"),
        log=_quiet, cancel=lambda: False)
    assert res[0][1] == "skipped" and "no matching slots" in res[0][2]
    assert "write" not in [c[0] for c in calls]      # never an unmodified copy


def test_cancel_between_targets_and_mid_step(tmp_path):
    jobs = _jobs(tmp_path, 3)
    state = {"cancel": False}

    def cancelling_write(raw, ws, out):
        state["cancel"] = True          # user hits Stop during the 1st build
        raise RuntimeError("Operation cancelled by user.")
    res = mod_port.run_ports(
        jobs,
        extract=lambda raw, ws: None,
        transfer=lambda ws: "t",
        stage=lambda ws: None,
        write=cancelling_write,
        log=_quiet, cancel=lambda: state["cancel"])
    # the interrupted target counts as cancelled, not failed, and nothing
    # after it runs
    assert [s for _j, s, _d in res] == ["cancelled"] * 3


def test_summarize_names_every_target(tmp_path):
    jobs = _jobs(tmp_path, 2)
    text = mod_port.summarize([
        (jobs[0], "ok", "5 things"),
        (jobs[1], "failed", "disk full"),
    ])
    assert "1 of 2" in text
    assert "stock0.raw" in text and "5 things" in text
    assert "stock1.raw" in text and "disk full" in text
