"""Tests for the Stern Spike 2 Spine exporter (``plugins/stern/spine.py``).

* **Algorithmic parity** -- the ported skeleton scan + verbatim emit must match
  the standalone RE script ``export_spine.py`` (validated 14 skel / 698 anim on
  Elvira) byte-for-byte.  Skips when the script isn't present locally.
* **Synthetic phase** -- ``extract_spine`` over a fake ext4 reader.
"""

import importlib.util
import json
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import spine

_RE_SCRIPT = os.path.expanduser("~/Documents/stern/re_scratch/export_spine.py")


def _load_re_script():
    if not os.path.isfile(_RE_SCRIPT):
        pytest.skip("RE cross-check script export_spine.py not present")
    spec = importlib.util.spec_from_file_location("_re_export_spine", _RE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lp(s):
    if isinstance(s, str):
        s = s.encode("ascii")
    return struct.pack("<Q", len(s)) + s


_SKEL = {
    "skeleton": {"hash": "abc123", "spine": "3.1.08", "width": 200,
                 "height": 100},
    "bones": [{"name": "root"}, {"name": "b1"}],
    "slots": [{"name": "s1", "bone": "root", "attachment": "a1"}],
    "skins": {"default": {"s1": {"a1": {"width": 64, "height": 32}}}},
    "animations": {"idle": {}, "walk": {}, "run": {}},
}


def _make_radium(skel=_SKEL, group="spine.Gargoyle"):
    js = json.dumps(skel, separators=(",", ":")).encode("utf-8")
    # group tag (short LP), then the skeleton JSON as a u64-LP string, embedded
    # in some filler so offsets aren't trivially zero.
    return (b"RADM" + _lp(group) + b"\x00" * 13 + _lp(js)
            + b"\xff" * 9), js


# --- skeleton scan --------------------------------------------------------

def test_extract_skeleton_returns_group_and_verbatim_json():
    data, js = _make_radium()
    res = spine.extract_skeleton(data)
    assert res is not None
    group, out = res
    assert group == "spine.Gargoyle"
    assert out == js                     # byte-exact verbatim slice


def test_extract_skeleton_none_without_magic():
    assert spine.extract_skeleton(b"no skeleton here" * 10) is None


def test_extract_skeleton_none_on_invalid_json():
    # Has the magic but the LP body isn't valid JSON -> not returned.
    bad = b'{"skeleton" but not json}'
    data = b"X" + _lp(bad) + b"Y"
    assert spine.extract_skeleton(data) is None


def test_lp_scanner_handles_multimegabyte():
    # A skeleton bigger than 64 KiB must still be found (max_len >= 16 MiB).
    big = dict(_SKEL)
    big["animations"] = {f"anim{i}": {"bones": {}} for i in range(4000)}
    data, js = _make_radium(big)
    assert len(js) > 70000
    res = spine.extract_skeleton(data)
    assert res is not None and res[1] == js


def test_parity_with_re_script(tmp_path):
    re = _load_re_script()
    data, js = _make_radium()
    rp = tmp_path / "scene.radium"
    rp.write_bytes(data)
    ref = re.extract_skeleton(str(rp))
    mine = spine.extract_skeleton(data)
    assert mine is not None and ref is not None
    assert mine[0] == ref[0]             # same group
    assert mine[1] == ref[1] == js       # byte-exact same JSON


# --- atlas manifest -------------------------------------------------------

def test_build_atlas_counts_and_attachments():
    atlas = spine.build_atlas(_SKEL)
    assert atlas["spine"] == "3.1.08"
    assert atlas["bones"] == 2
    assert atlas["slots"] == 1
    assert atlas["animations"] == 3
    assert atlas["animation_names"] == ["idle", "run", "walk"]
    assert len(atlas["attachments"]) == 1
    a = atlas["attachments"][0]
    assert (a["skin"], a["slot"], a["name"]) == ("default", "s1", "a1")
    assert a["w"] == 64 and a["h"] == 32
    assert "not decoded" in atlas["frame_source"]


# --- end-to-end phase -----------------------------------------------------

class _FakeReader:
    def __init__(self, files):
        self._files = files

    def iter_regular_files(self, min_size=1):
        for path, data in self._files.items():
            yield path, 0, {"size": len(data), "_data": data}

    def read_file_bytes(self, node):
        return node["_data"]


def test_extract_spine_end_to_end(tmp_path):
    data, js = _make_radium(group="spine.Gargoyle")
    reader = _FakeReader({
        "/g/spine/Gargoyle/scene.radium": data,
        "/g/other/readme.txt": b"hello",
    })
    out = tmp_path / "out"
    n = spine.extract_spine(reader, str(out))
    assert n == 1
    sp = out / "spine"
    jsons = sorted(p.name for p in sp.glob("spine.Gargoyle__*.json")
                   if not p.name.endswith(".atlas.json"))
    assert len(jsons) == 1
    # verbatim byte-exact
    assert (sp / jsons[0]).read_bytes() == js
    idx = json.loads((sp / "index.json").read_text())
    assert len(idx) == 1
    assert idx[0]["group"] == "spine.Gargoyle"
    assert idx[0]["animations"] == 3
    # atlas sidecar exists
    assert (sp / (jsons[0][:-5] + ".atlas.json")).exists()


def test_extract_spine_no_skeletons(tmp_path):
    reader = _FakeReader({"/g/x/scene.radium": b"not a spine scene at all"})
    assert spine.extract_spine(reader, str(tmp_path)) == 0


def test_extract_spine_no_radium(tmp_path):
    reader = _FakeReader({"/g/readme.txt": b"hi"})
    assert spine.extract_spine(reader, str(tmp_path)) == 0
