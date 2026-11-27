"""PAD-1630: on a Mac the multi-boot tools run from the copy of the rigs and
the few package files ``multiboot_docker.stage_rig`` puts in the container,
under a bare python3.  explorer.CardImage imports ``spike3`` inside a method
(it asks every card whether it is a Spike 3 one as it opens it), so the
module-level import check never saw it, and on v1.631.1 every Stern preview,
size check and build on a Mac died on "cannot import name 'spike3'".

These open a card the way the container does: from the staged tree alone,
with only the standard library importable."""
import os
import subprocess
import sys

import pytest

from pinball_decryptor.webui import multiboot_docker as D

from tests.test_rig_leaf_imports import _SANDBOX, REPO


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(D, "staged_repo", lambda: str(root))
    D.stage_rig(REPO)
    # not a checkout: nothing outside what was staged can be imported
    assert not (root / "pinball_decryptor" / "plugins" / "stern" / "mode_write.py").exists()
    card = tmp_path / "card.raw"
    with open(card, "wb") as fh:
        fh.truncate(4 << 20)
    return root, card


def _run(root, code):
    # the rigs' own scripts sit beside each other in tools/<rig>/ and import
    # one another (selectmedia -> editsource, mkmulticard -> treesync)
    rig = sorted({f[:-3] for d, _, fs in os.walk(root / "tools")
                  for f in fs if f.endswith(".py")})
    sandbox = _SANDBOX.replace('| {"pinball_decryptor"}',
                               '| {"pinball_decryptor"} | set(RIG_SCRIPTS)')
    assert sandbox != _SANDBOX
    code = "RIG_SCRIPTS = %r\n" % rig + sandbox + code
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, "-I", "-c", code],
                          cwd=str(root), env=env, capture_output=True,
                          text=True, timeout=120)


def _no_import_error(done):
    out = done.stdout + done.stderr
    assert "ImportError" not in out and "ModuleNotFoundError" not in out, out


def test_spike3_modules_are_staged():
    for rel in ("pinball_decryptor/plugins/stern/spike3.py",
                "pinball_decryptor/plugins/stern/spike3_keys.py"):
        assert rel in D._PACKAGE_FILES


def test_selectmedia_opens_a_card_from_the_staged_tree(staged):
    root, card = staged
    done = _run(root, (
        "import sys\n"
        "sys.path.insert(0, 'tools/spike2_emu')\n"
        "import selectmedia\n"
        "try:\n"
        "    selectmedia.open_card(%r)\n"
        "except (ImportError, ModuleNotFoundError):\n"
        "    raise\n"
        "except Exception as e:\n"
        "    print('refused as a card:', type(e).__name__)\n"
        "print('opened')\n") % str(card))
    _no_import_error(done)
    assert done.returncode == 0 and "opened" in done.stdout, done.stderr

