"""PAD-1132: a ticket or item tree has no .venv of its own, so the app
borrows the dev checkout's interpreter instead of running on a system
Python without pywebview (which put it in the browser)."""

import json
import os
import sys

from pinball_decryptor.webui import host


def _venv(base):
    exe = (os.path.join(base, ".venv", "Scripts", "pythonw.exe")
           if sys.platform == "win32"
           else os.path.join(base, ".venv", "bin", "python"))
    os.makedirs(os.path.dirname(exe))
    open(exe, "w").close()
    return os.path.normpath(os.path.join(base, ".venv")), exe


def _no_git(monkeypatch):
    def boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(host.subprocess if hasattr(host, "subprocess")
                        else __import__("subprocess"), "run", boom)


def test_own_venv_first(tmp_path, monkeypatch):
    _no_git(monkeypatch)
    venv, exe = _venv(str(tmp_path / "tree"))
    assert host._checkout_venv(str(tmp_path / "tree")) == (venv, exe)


def test_pad_triage_ticket_tree_uses_the_dev_checkout(tmp_path, monkeypatch):
    _no_git(monkeypatch)
    monkeypatch.delenv("PAD_DEV_VENV", raising=False)
    dev = tmp_path / "somewhere" / "my-dev"
    venv, exe = _venv(str(dev))
    triage = tmp_path / "pad-triage"
    tree = triage / "work" / "tickets" / "PAD-7"
    tree.mkdir(parents=True)
    (triage / "config.json").write_text(
        json.dumps({"repo": {"dev_checkout": str(dev)}}))
    assert host._checkout_venv(str(tree)) == (venv, exe)


def test_pad_triage_without_config_finds_the_sibling_checkout(tmp_path,
                                                              monkeypatch):
    _no_git(monkeypatch)
    monkeypatch.delenv("PAD_DEV_VENV", raising=False)
    venv, exe = _venv(str(tmp_path / "pinball-asset-decryptor"))
    tree = tmp_path / "pad-triage" / "work" / "tickets" / "PAD-7"
    tree.mkdir(parents=True)
    assert host._checkout_venv(str(tree)) == (venv, exe)


def test_worktree_uses_the_checkout_holding_its_git(tmp_path, monkeypatch):
    monkeypatch.delenv("PAD_DEV_VENV", raising=False)
    venv, exe = _venv(str(tmp_path / "main"))
    common = str(tmp_path / "main" / ".git")

    class R:
        stdout = common + "\n"
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    tree = tmp_path / "wt" / "item-9"
    tree.mkdir(parents=True)
    assert host._checkout_venv(str(tree)) == (venv, exe)


def test_an_installed_copy_finds_none(tmp_path, monkeypatch):
    _no_git(monkeypatch)
    monkeypatch.delenv("PAD_DEV_VENV", raising=False)
    assert host._checkout_venv(str(tmp_path / "Program Files" / "PAD")) is None
