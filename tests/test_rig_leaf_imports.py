r"""The emulator rigs import plugin leaf modules on a BARE interpreter.

``tools/spike1_emu/build_rootfs.py`` reads a Spike 1 card with the plugin's
own pure-Python ext reader, and ``start.sh`` runs it with the WSL distro's
``python3`` — deliberately, because a rootfs full of symlinks cannot be
written to a drvfs target.  That interpreter is whatever the distro shipped:
stdlib and nothing else, no pip, no ``requirements.txt``.

Importing ``pinball_decryptor.plugins.stern.ext4`` runs the *package*
``__init__`` first, so while those entry points imported their manufacturer
eagerly, the read pulled in every plugin sideways and died on the first
third-party dependency it met — ``ModuleNotFoundError: No module named
'Crypto'``, raised inside the Spooky plugin, from a script that only wanted
to walk an ext2 partition.  The Spike 1 emulator could not extract a card.

These tests run the imports in a child process whose only importable
top-level packages are the standard library's, which is what the distro's
python3 is, and check the entry points still register in the app.
"""

import ast
import importlib
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO, "pinball_decryptor", "plugins")

#: (module, the rig script that imports it under a bare python3).  Each of
#: these must stay importable with nothing installed.
RIG_LEAF_MODULES = [
    ("pinball_decryptor.plugins.stern.ext4", "tools/spike1_emu/build_rootfs.py"),
    ("pinball_decryptor.plugins.stern.formats", "tools/spike1_emu/build_rootfs.py"),
    ("pinball_decryptor.plugins.stern.spike1_emulate", "tools/spike1_emu/s1view.py"),
    ("pinball_decryptor.plugins.jjp.crypto", "tools/jjp_emu/pfimage.py"),
]

# Installed in the child before anything of ours is imported: every
# non-stdlib import then fails exactly the way it does on a distro python3.
_SANDBOX = '''
import sys, importlib.abc
ALLOW = set(sys.stdlib_module_names) | {"pinball_decryptor"}


class OnlyStdlib(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top not in ALLOW:
            raise ModuleNotFoundError("No module named %r" % top, name=name)
        return None          # stdlib: let the normal finders answer


sys.meta_path.insert(0, OnlyStdlib())
'''


def _plugin_packages():
    return sorted(name for name in os.listdir(PLUGIN_DIR)
                  if os.path.isfile(os.path.join(PLUGIN_DIR, name, "__init__.py")))


def _import_on_stdlib_only(*modules):
    code = _SANDBOX + "".join("import %s\n" % m for m in modules)
    env = dict(os.environ, PYTHONPATH=REPO)
    return subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                          capture_output=True, text=True)


@pytest.mark.parametrize("module,rig", RIG_LEAF_MODULES,
                         ids=[m for m, _ in RIG_LEAF_MODULES])
def test_rig_leaf_module_imports_with_nothing_installed(module, rig):
    done = _import_on_stdlib_only(module)
    assert done.returncode == 0, (
        "%s is imported by %s under the WSL distro's own python3, which has "
        "no third-party packages:\n%s" % (module, rig, done.stderr))


def test_every_plugin_entry_point_imports_with_nothing_installed():
    """Reaching any module of a plugin costs only what that module uses."""
    packages = _plugin_packages()
    assert "stern" in packages and "spooky" in packages   # discovery sanity
    done = _import_on_stdlib_only(
        *["pinball_decryptor.plugins." + p for p in packages])
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("package", _plugin_packages())
def test_entry_point_does_not_import_its_manufacturer_at_module_level(package):
    """The rule itself, stated where a new plugin will trip over it."""
    path = os.path.join(PLUGIN_DIR, package, "__init__.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    for node in tree.body:                      # module level only
        if isinstance(node, ast.ImportFrom) and node.module == "manufacturer":
            pytest.fail(
                "%s/__init__.py imports .manufacturer at module level; move it "
                "into register() — see pinball_decryptor/plugins/__init__.py"
                % package)


def test_load_plugins_registers_every_manufacturer(capsys):
    """The lazy entry points still register — load_plugins() calls them."""
    from pinball_decryptor.core.registry import (_PLUGIN_MODULES,
                                                 all_manufacturers,
                                                 load_plugins)
    load_plugins()                              # idempotent
    assert "Warning: failed to load plugin" not in capsys.readouterr().out

    for module_name in _PLUGIN_MODULES:
        mod = importlib.import_module(module_name)
        assert callable(getattr(mod, "register", None)), module_name

    keys = {m.key for m in all_manufacturers()}
    assert {"ap", "bof", "cgc", "dp", "jjp", "pb", "spooky", "stern",
            "williams", "data_east", "sega"} <= keys
