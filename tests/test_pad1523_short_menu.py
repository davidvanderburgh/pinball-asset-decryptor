"""PAD-1523: Write to a card / Compact with PAD on Windows 11's short menu.

The handler (tools/padmenu/padmenu.c, built to pinball_decryptor/shell/
padmenu64.dll) and its signed sparse package (padmenu.msix) are committed
prebuilt; these hold them to their sources, to each other, to the verbs the
app writes (webui/open_image.py) and to the installer, and drive the real DLL
through COM on Windows.
"""
import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

import pytest

from pinball_decryptor.webui import open_image, shell_menu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools", "padmenu")
SHELL = os.path.join(ROOT, "pinball_decryptor", "shell")
ISS = os.path.join(ROOT, "installer", "pinball_decryptor.iss")
NS = {"f": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
      "com": "http://schemas.microsoft.com/appx/manifest/com/windows10",
      "d5": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/5",
      "b": "http://schemas.microsoft.com/appx/2010/blockmap"}


def _build():
    spec = importlib.util.spec_from_file_location(
        "padmenu_build", os.path.join(TOOLS, "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _manifest():
    with zipfile.ZipFile(os.path.join(SHELL, "padmenu.msix")) as z:
        return ET.fromstring(z.read("AppxManifest.xml"))


def _c_source():
    with open(os.path.join(TOOLS, "padmenu.c"), encoding="utf-8") as f:
        return f.read()


def _c_guids():
    """The two CLSIDs padmenu.c spells out, as manifest-style strings"""
    out = []
    for m in re.finditer(
            r"\{0x([0-9a-f]+), 0x([0-9a-f]+), 0x([0-9a-f]+), "
            r"\{((?:0x[0-9a-f]+, ){7}0x[0-9a-f]+)\}\}", _c_source()):
        tail = [int(x, 16) for x in m.group(4).split(", ")]
        out.append("%08X-%04X-%04X-%02X%02X-%s" % (
            int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16),
            tail[0], tail[1], "".join("%02X" % b for b in tail[2:])))
    return out


# ------------------------------------------------------------ the build

def test_stamp_matches_sources_and_binaries():
    stamp = shell_menu.stamp()
    build = _build()
    assert stamp["sources"] == build.source_hash(), (
        "tools/padmenu changed: rebuild (tools/padmenu/build.py) and commit")
    assert stamp["version"] == build.VERSION
    assert stamp["dll"] == _sha(os.path.join(SHELL, "padmenu64.dll"))
    assert stamp["msix"] == _sha(os.path.join(SHELL, "padmenu.msix"))
    assert stamp["cer"] == _sha(os.path.join(SHELL, "padmenu.cer"))
    assert stamp["thumbprint"] == build.thumbprint(
        os.path.join(SHELL, "padmenu.cer"))


def test_package_is_signed_and_its_block_map_holds():
    with zipfile.ZipFile(os.path.join(SHELL, "padmenu.msix")) as z:
        names = z.namelist()
        assert {"AppxManifest.xml", "logo.png", "AppxBlockMap.xml",
                "[Content_Types].xml", "AppxSignature.p7x"} <= set(names)
        bm = ET.fromstring(z.read("AppxBlockMap.xml"))
        files = bm.findall("b:File", NS)
        assert {f.get("Name") for f in files} == {"AppxManifest.xml",
                                                  "logo.png"}
        for f in files:
            data = z.read(f.get("Name"))
            assert int(f.get("Size")) == len(data)
            blocks = [b.get("Hash") for b in f.findall("b:Block", NS)]
            want = [base64.b64encode(hashlib.sha256(
                data[i:i + 65536]).digest()).decode()
                for i in range(0, len(data), 65536)]
            assert blocks == want


def test_manifest_names_the_certificate_the_dll_and_the_verbs():
    m = _manifest()
    ident = m.find("f:Identity", NS)
    assert ident.get("Name") == shell_menu.NAME
    assert ident.get("Version") == shell_menu.stamp()["version"]
    assert ident.get("Publisher") == _build().SUBJECT
    classes = [c.get("Id") for c in m.iter(
        "{%s}Class" % NS["com"])]
    assert sorted(classes) == sorted(_c_guids())
    assert {c.get("Path") for c in m.iter("{%s}Class" % NS["com"])} == {
        shell_menu.DLL}
    write, compact = _c_guids()
    types = {t.get("Type"): [v.get("Clsid") for v in t.findall("d5:Verb", NS)]
             for t in m.iter("{%s}ItemType" % NS["d5"])}
    # Write wherever the app writes its verb, Compact where it compacts
    assert set(types) == set(open_image.IMAGE_EXTENSIONS)
    for ext, verbs in types.items():
        assert verbs[0] == write
        assert (compact in verbs) == (ext in open_image.COMPACT_EXTENSIONS)


def test_dll_bridges_the_apps_own_verb_names():
    src = _c_source()
    assert 'L"%s"' % open_image.VERB in src
    assert 'L"%s"' % open_image.COMPACT_VERB in src


def test_installer_trusts_and_removes_the_same_certificate_and_package():
    with open(ISS, encoding="utf-8") as f:
        iss = f.read()
    assert (r'-addstore TrustedPeople ""{app}\pinball_decryptor\shell'
            r'\padmenu.cer"""') in iss
    assert "MinVersion: 10.0.22000" in iss
    assert "-delstore TrustedPeople %s" % shell_menu.stamp()["thumbprint"] \
        in iss
    assert "-Name ' +\n       '%s | Remove-AppxPackage" % shell_menu.NAME \
        in iss
    assert r"{localappdata}\pinball_decryptor\shell_menu" in iss


# ------------------------------------------------------ registering it

@pytest.fixture
def fake(monkeypatch, tmp_path):
    calls = []
    state = {"installed": [], "trusted": True, "build": 26100}
    monkeypatch.setattr(shell_menu, "windows_build", lambda: state["build"])
    monkeypatch.setattr("pinball_decryptor.webui.shell_icon.supported",
                        lambda: True)
    monkeypatch.setattr(shell_menu, "trusted", lambda t: state["trusted"])
    monkeypatch.setattr(
        shell_menu, "installed",
        lambda version=None: [n for n in state["installed"]
                              if version is None or ("_%s_" % version) in n])

    def ps(script, timeout=120):
        calls.append(script)
        if "Add-AppxPackage" in script:
            state["installed"] = ["%s_%s_x64__x" % (
                shell_menu.NAME, shell_menu.stamp()["version"])]
        return True, ""
    monkeypatch.setattr(shell_menu, "_ps", ps)
    return calls, state, str(tmp_path / "stage")


def test_register_adds_the_package_from_a_staged_copy_once(fake):
    calls, state, root = fake
    assert shell_menu.register(root=root) is True
    assert len(calls) == 1
    folder = json.load(open(os.path.join(root, shell_menu.RECORD)))["folder"]
    assert os.path.isfile(os.path.join(folder, shell_menu.DLL))
    assert "Remove-AppxPackage" in calls[0]
    assert "Add-AppxPackage -Path '%s'" % os.path.join(
        SHELL, shell_menu.MSIX) in calls[0]
    assert "-ExternalLocation '%s'" % folder in calls[0]
    # registered already: the next start changes nothing
    assert shell_menu.register(root=root) is False
    assert len(calls) == 1
    # taken away outside the app: it comes back
    state["installed"] = []
    assert shell_menu.register(root=root) is True


@pytest.mark.parametrize("what", ["windows10", "untrusted"])
def test_register_leaves_the_package_alone_where_it_cannot_work(fake, what):
    calls, state, root = fake
    if what == "windows10":
        state["build"] = 19045
    else:
        state["trusted"] = False
    assert shell_menu.register(root=root) is False
    assert calls == []
    assert not os.path.exists(root)


def test_unregister_removes_the_package_and_its_copies(fake):
    calls, state, root = fake
    shell_menu.register(root=root)
    assert shell_menu.unregister(root=root) is True
    assert "Remove-AppxPackage" in calls[-1]
    assert not os.path.exists(root)


# ------------------------------------------ the DLL itself, through COM

windows = pytest.mark.skipif(sys.platform != "win32",
                             reason="the handler is a Windows DLL")

EXT = ".pad1523test"


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


P = ctypes.c_void_p


def _vt(obj, i, *argtypes, restype=ctypes.c_long):
    vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(P))[0],
                       ctypes.POINTER(P))
    return ctypes.WINFUNCTYPE(restype, P, *argtypes)(vtbl[i])


@pytest.fixture
def verbs(tmp_path):
    """A throwaway extension carrying the app's two verbs, whose commands
    leave a marker file beside the item"""
    import winreg
    cmd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                       "System32", "cmd.exe")
    keys = []
    for verb, label in ((open_image.VERB, "Write to a card with PAD"),
                        (open_image.COMPACT_VERB, "Compact with PAD")):
        base = r"Software\Classes\SystemFileAssociations\%s\shell\%s" % (
            EXT, verb)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, label)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ,
                              r"C:\icons\%s.ico" % verb)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              base + r"\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ,
                              '"%s" /c type nul > "%%1.%s"' % (cmd, verb))
        keys.append(base)
    yield tmp_path
    for base in keys:
        for sub in (base + r"\command", base):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
    for sub in (r"Software\Classes\SystemFileAssociations\%s\shell" % EXT,
                r"Software\Classes\SystemFileAssociations\%s" % EXT):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass


def _command(compact):
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    dll = ctypes.WinDLL(os.path.join(SHELL, shell_menu.DLL))
    write, comp = _c_guids()
    clsid = GUID.of(comp if compact else write)
    factory = P()
    dll.DllGetClassObject.argtypes = [ctypes.POINTER(GUID),
                                      ctypes.POINTER(GUID), ctypes.POINTER(P)]
    assert dll.DllGetClassObject(
        ctypes.byref(clsid),
        ctypes.byref(GUID.of("00000001-0000-0000-C000-000000000046")),
        ctypes.byref(factory)) == 0
    cmd = P()
    hr = _vt(factory, 3, P, ctypes.POINTER(GUID), ctypes.POINTER(P))(
        factory, None,
        ctypes.byref(GUID.of("A08CE4D0-FA25-44AB-B57C-C7B1C323E0B9")),
        ctypes.byref(cmd))
    assert hr == 0 and cmd
    return dll, cmd


def _items(path):
    shell32 = ctypes.windll.shell32
    item, arr = P(), P()
    shell32.SHCreateItemFromParsingName.argtypes = [
        ctypes.c_wchar_p, P, ctypes.POINTER(GUID), ctypes.POINTER(P)]
    assert shell32.SHCreateItemFromParsingName(
        path, None,
        ctypes.byref(GUID.of("43826D1E-E718-42EE-BC55-A1E261C37BFE")),
        ctypes.byref(item)) == 0
    shell32.SHCreateShellItemArrayFromShellItem.argtypes = [
        P, ctypes.POINTER(GUID), ctypes.POINTER(P)]
    assert shell32.SHCreateShellItemArrayFromShellItem(
        item, ctypes.byref(GUID.of("B63EA76D-1F85-456F-A19C-48159EFA858B")),
        ctypes.byref(arr)) == 0
    return arr


def _string(cmd, slot, items):
    out = ctypes.c_wchar_p()
    hr = _vt(cmd, slot, P, ctypes.POINTER(ctypes.c_wchar_p))(
        cmd, items, ctypes.byref(out))
    return hr, out.value


def _state(cmd, items):
    st = ctypes.c_int(-1)
    assert _vt(cmd, 7, P, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(
        cmd, items, 1, ctypes.byref(st)) == 0
    return st.value


def _make_sparse(path, size):
    """A file of *size* bytes with no disk behind it (a compact card)"""
    import subprocess
    open(path, "wb").close()
    subprocess.run(["fsutil", "sparse", "setflag", path], check=True,
                   capture_output=True)
    with open(path, "r+b") as f:
        f.truncate(size)


@windows
@pytest.mark.parametrize("compact", [False, True])
def test_dll_reads_label_icon_and_runs_the_verb(verbs, compact):
    card = str(verbs / ("card" + EXT))
    with open(card, "wb") as f:
        f.write(b"\0" * 4096)
    _dll, cmd = _command(compact)
    items = _items(card)
    verb = open_image.COMPACT_VERB if compact else open_image.VERB
    hr, title = _string(cmd, 3, items)
    assert hr == 0
    assert title == ("Compact with PAD" if compact
                     else "Write to a card with PAD")
    hr, icon = _string(cmd, 4, items)
    assert (hr, icon) == (0, r"C:\icons\%s.ico" % verb)
    assert _state(cmd, items) == 0                      # ECS_ENABLED
    assert _vt(cmd, 8, P, P)(cmd, items, None) == 0     # Invoke
    marker = card + "." + verb
    for _ in range(50):
        if os.path.exists(marker):
            break
        time.sleep(0.1)
    assert os.path.exists(marker), "the verb's command did not run"


@windows
def test_compact_hides_on_a_card_already_compact(verbs):
    card = str(verbs / ("compact" + EXT))
    _make_sparse(card, 64 * 1024 * 1024)
    for compact, want in ((True, 2), (False, 0)):       # ECS_HIDDEN, ENABLED
        _dll, cmd = _command(compact)
        assert _state(cmd, _items(card)) == want


@windows
def test_entries_hide_where_the_app_has_no_verb(tmp_path):
    other = str(tmp_path / "card.pad1523none")
    open(other, "wb").close()
    for compact in (False, True):
        _dll, cmd = _command(compact)
        assert _state(cmd, _items(other)) == 2           # ECS_HIDDEN
