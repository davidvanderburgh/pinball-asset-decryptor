"""THE PREVIEW SWITCH: the mode maker ships dark, and a personal code David signs turns it on.

core/preview.py (the code, its check, this run's state), tools/preview_code.py (the key
pair and the codes), and what the switch gates when it is OFF: a Write takes the path a
build without the mode editor family takes, leaves the project's modes and its changes to
the game's own modes out, and says so in one sentence.

Every test here signs with a MADE-UP key pair passed in (or patched in) as the public key;
the key the app ships is only checked for shape.
"""
import datetime as dt
import hashlib
import importlib.util
import io
import os
import pathlib
import shutil
import subprocess
import sys
import time

import pytest

from pinball_decryptor.core import ed25519 as E
from pinball_decryptor.core import preview as P

REPO = pathlib.Path(__file__).resolve().parents[1]

#: A made-up signing key for these tests (never the shipped one).
TEST_SECRET = hashlib.sha256(b"pad preview test key").digest()
TEST_PUB = E.public_key(TEST_SECRET).hex()
OTHER_SECRET = hashlib.sha256(b"somebody else's key").digest()
TODAY = dt.date(2026, 9, 18)
KEYS = (TEST_PUB,)


def make_code(name="Test Person", days=90, features=("modes",), issued=TODAY,
              secret=TEST_SECRET, code_id="a1b2c3", context=P.CONTEXT, version=None):
    """A code as tools/preview_code.py issues one, signed with *secret*."""
    payload = P.payload_bytes(features, name, issued, issued + dt.timedelta(days=days), code_id)
    if version is not None:
        payload = payload.replace(b'"v":1', b'"v":%d' % version)
    return P.encode(payload, E.sign(secret, context + payload))


def _split(code):
    import base64
    body = code[len(P.PREFIX):]
    raw = base64.b32decode(body + "=" * (-len(body) % 8))
    return raw[:-64], raw[-64:]


# ---- the code ----------------------------------------------------------------------------
def test_the_switch_is_off_by_default():
    assert not P.enabled("modes")
    assert P.load([]) == [] and not P.enabled("modes")
    assert P.active_features() == frozenset()


def test_a_valid_code_turns_the_mode_maker_on():
    code = make_code()
    assert code.startswith("PAD-PREVIEW-")
    g = P.check(code, TODAY, KEYS)
    assert (g.name, g.features, g.id) == ("Test Person", ("modes",), "a1b2c3")
    assert (g.issued, g.expires) == (TODAY, dt.date(2026, 12, 17))
    rows = P.load([code], TODAY, KEYS)
    assert P.enabled("modes") and rows[0].active
    assert rows[0].lines == ["Mode maker: on for Test Person, until 2026-12-17"]


def test_the_last_day_still_works_and_the_next_does_not():
    code = make_code(days=10)
    last = TODAY + dt.timedelta(days=10)
    assert P.check(code, last, KEYS).expires == last
    with pytest.raises(P.PreviewCodeError, match="ended on 2026-09-28"):
        P.check(code, last + dt.timedelta(days=1), KEYS)


def test_whitespace_line_breaks_case_and_dashes_do_not_matter():
    code = make_code()
    body = code[len(P.PREFIX):]
    wrapped = "  pad-preview-" + "\n".join(body[i:i + 40].lower() for i in range(0, len(body), 40))
    grouped = P.PREFIX + "-".join(body[i:i + 5] for i in range(0, len(body), 5)) + "\r\n"
    for text in (wrapped, grouped, "\t" + code + "  "):
        assert P.check(text, TODAY, KEYS).id == "a1b2c3"
        assert P.normalise(text) == code


@pytest.mark.parametrize("text,needle", [
    ("hello", "not a preview code"),
    ("", "not a preview code"),
    ("PAD-PREVIEW-", "incomplete or mistyped"),
    ("PAD-PREVIEW-!!!!", "incomplete or mistyped"),
    ("PAD-PREVIEW-AAAA", "incomplete or mistyped"),
])
def test_garbage_text_is_refused_in_a_sentence(text, needle):
    with pytest.raises(P.PreviewCodeError, match=needle):
        P.check(text, TODAY, KEYS)
    rows = P.load([text], TODAY, KEYS)
    assert not P.enabled("modes")
    assert [st.active for st in rows] == ([False] if text.strip() else [])


def test_a_truncated_code_is_refused():
    code = make_code()
    with pytest.raises(P.PreviewCodeError):
        P.check(code[:-20], TODAY, KEYS)


def test_a_code_signed_by_another_key_is_refused():
    code = make_code(secret=OTHER_SECRET)
    with pytest.raises(P.PreviewCodeError, match="not issued for this app"):
        P.check(code, TODAY, KEYS)
    rows = P.load([code], TODAY, KEYS)
    assert not P.enabled("modes") and "not issued for this app" in rows[0].error


@pytest.mark.parametrize("change", [
    (b'"n":"Test Person"', b'"n":"Test Persom"'),          # another name
    (b'"e":"2026-12-17"', b'"e":"2099-12-17"'),            # a later end
    (b'"f":["modes"]', b'"f":["mode2"]'),                  # another feature
])
def test_a_tampered_payload_is_refused(change):
    payload, sig = _split(make_code())
    old, new = change
    assert old in payload
    forged = P.encode(payload.replace(old, new), sig)
    with pytest.raises(P.PreviewCodeError, match="signature does not check out"):
        P.check(forged, TODAY, KEYS)
    P.load([forged], TODAY, KEYS)
    assert not P.enabled("modes")


def test_a_bad_signature_is_refused():
    payload, sig = _split(make_code())
    bad = P.encode(payload, sig[:10] + bytes([sig[10] ^ 0x40]) + sig[11:])
    with pytest.raises(P.PreviewCodeError, match="signature does not check out"):
        P.check(bad, TODAY, KEYS)


def test_a_signature_over_the_payload_alone_is_not_a_code():
    """What is signed is CONTEXT + payload: the same key signing anything else never makes
    a code."""
    with pytest.raises(P.PreviewCodeError, match="signature does not check out"):
        P.check(make_code(context=b""), TODAY, KEYS)


def test_an_expired_code_leaves_the_switch_off_and_says_so():
    code = make_code(days=5, issued=TODAY - dt.timedelta(days=30))
    with pytest.raises(P.PreviewCodeError, match="ended on"):
        P.check(code, TODAY, KEYS)
    rows = P.load([code], TODAY, KEYS)
    assert not P.enabled("modes") and not rows[0].active
    assert rows[0].lines == ["Mode maker: expired on 2026-08-24 (code for Test Person)"]


def test_a_code_for_another_feature_turns_nothing_on():
    code = make_code(features=("tables",))
    with pytest.raises(P.PreviewCodeError, match="does not have"):
        P.check(code, TODAY, KEYS)
    rows = P.load([code], TODAY, KEYS)
    assert not P.enabled("modes") and not rows[0].active
    assert "not in this version" in rows[0].lines[0]


def test_a_payload_of_another_version_is_refused():
    with pytest.raises(P.PreviewCodeError, match="another version of the app"):
        P.check(make_code(version=2), TODAY, KEYS)


def test_one_good_code_among_bad_ones_is_enough():
    rows = P.load(["junk", make_code(secret=OTHER_SECRET), make_code()], TODAY, KEYS)
    assert P.enabled("modes") and [st.active for st in rows] == [False, False, True]


def test_add_and_remove_keep_one_copy_per_code():
    a, b = make_code(code_id="aaaa11"), make_code(name="Another Person", code_id="bbbb22")
    codes, g = P.add_code([], a, TODAY, KEYS)
    assert codes == [a] and g.id == "aaaa11"
    codes, _g = P.add_code(codes, "  " + a.lower() + "\n", TODAY, KEYS)   # the same code again
    assert codes == [a]
    codes, _g = P.add_code(codes, b, TODAY, KEYS)
    assert codes == [a, b]
    with pytest.raises(P.PreviewCodeError):
        P.add_code(codes, "nonsense", TODAY, KEYS)
    assert P.remove_code(codes, a.lower()) == [b]
    assert P.remove_code(["junk", b], "junk") == [b]


def test_the_shipped_public_key_is_a_real_key_and_not_the_tests():
    assert P.PUBLIC_KEYS and TEST_PUB not in P.PUBLIC_KEYS
    for k in P.PUBLIC_KEYS:
        assert len(bytes.fromhex(k)) == 32 and E._decompress(bytes.fromhex(k)) is not None
    # a test code is not accepted by the shipped app
    with pytest.raises(P.PreviewCodeError, match="not issued for this app"):
        P.check(make_code())


def test_the_start_up_check_is_quick():
    """load() runs on the UI thread at start-up: a handful of codes must cost well under a
    second even on a slow runner (measured ~2 ms a code on David's PC)."""
    codes = [make_code(code_id="c0de%02d" % i) for i in range(5)]
    t0 = time.perf_counter()
    P.load(codes, TODAY, KEYS)
    assert time.perf_counter() - t0 < 1.0 and P.load_ms() < 1000.0
    assert P.enabled("modes")


def test_the_words_people_see_have_no_em_dash():
    from pinball_decryptor.gui import preview_dialog
    from pinball_decryptor.plugins.stern import mode_write as MW
    texts = [preview_dialog.INTRO, MW.PREVIEW_REFUSAL,
             "\n".join(P.describe(P.check(make_code(), TODAY, KEYS), TODAY))]
    for text, _n in (("hello", 0), ("PAD-PREVIEW-", 0), (make_code(secret=OTHER_SECRET), 0),
                     (make_code(days=1, issued=TODAY - dt.timedelta(days=9)), 0),
                     (make_code(features=("x",)), 0), (make_code(version=3), 0)):
        try:
            P.check(text, TODAY, KEYS)
        except P.PreviewCodeError as e:
            texts.append(str(e))
    for t in texts:
        assert "—" not in t, t


# ---- the tool ----------------------------------------------------------------------------
def _tool():
    spec = importlib.util.spec_from_file_location("preview_code_tool",
                                                  REPO / "tools" / "preview_code.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_init_writes_the_private_key_once_and_never_prints_it(tmp_path, capsys):
    tool = _tool()
    key = tmp_path / "signing" / "k.txt"
    assert tool.main(["init", "--key", str(key)]) == 0
    out = capsys.readouterr().out
    text = key.read_text(encoding="utf-8")
    assert text.startswith(tool.KEY_MARKER)
    secret = next(ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("secret="))
    pub = next(ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("public="))
    assert secret not in out and pub in out
    assert E.public_key(bytes.fromhex(secret)).hex() == pub
    with pytest.raises(SystemExit, match="already exists"):
        tool.main(["init", "--key", str(key)])
    assert key.read_text(encoding="utf-8") == text


def test_init_refuses_a_path_inside_a_git_checkout(tmp_path):
    tool = _tool()
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    target = tmp_path / "repo" / "keys" / "k.txt"
    with pytest.raises(SystemExit, match="inside the git checkout"):
        tool.main(["init", "--key", str(target)])
    assert not target.exists()
    if (REPO / ".git").exists():
        with pytest.raises(SystemExit, match="inside the git checkout"):
            tool.main(["init", "--key", str(REPO / "preview_signing_key.txt")])
        assert not (REPO / "preview_signing_key.txt").exists()


def test_the_default_key_path_is_outside_the_repo():
    tool = _tool()
    path = pathlib.Path(tool.default_key_path()).resolve()
    assert REPO not in path.parents
    assert path.name == "preview_signing_key.txt"


def test_issue_prints_a_code_the_app_accepts(tmp_path, capsys, monkeypatch):
    tool = _tool()
    key = tmp_path / "k.txt"
    tool.main(["init", "--key", str(key)])
    pub = capsys.readouterr().out.strip().splitlines()[-1]
    # a key the app does not ship is refused: its codes would never unlock anything
    with pytest.raises(SystemExit, match="not one this app ships"):
        tool.main(["issue", "--name", "Test Person", "--key", str(key)])
    monkeypatch.setattr(P, "PUBLIC_KEYS", (pub,))
    assert tool.main(["issue", "--name", "  Test   Person ", "--days", "30",
                      "--key", str(key)]) == 0
    code = capsys.readouterr().out.strip()
    g = P.check(code)
    assert g.name == "Test Person" and g.features == ("modes",)
    assert g.expires - g.issued == dt.timedelta(days=30)
    assert tool.main(["show", code]) == 0
    shown = capsys.readouterr().out
    assert "Mode maker: on for Test Person" in shown and "accepts it" in shown
    assert tool.main(["show", "nonsense"]) == 1
    with pytest.raises(SystemExit, match="Unknown feature"):
        tool.main(["issue", "--name", "X", "--feature", "tables", "--key", str(key)])


@pytest.mark.skipif(not shutil.which("git") or not (REPO / ".git").exists(),
                    reason="needs a git checkout")
def test_git_ignores_a_key_file_dropped_in_the_repo():
    for rel in ("preview_signing_key.txt", "tools/preview_signing_key.txt",
                "pinball_decryptor_signing/anything.txt"):
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=str(REPO),
                           capture_output=True)
        assert r.returncode == 0, rel


# ---- what the switch gates, OFF ----------------------------------------------------------
from pinball_decryptor.plugins.stern import engine                     # noqa: E402
from pinball_decryptor.plugins.stern import mode_project as MP         # noqa: E402
from pinball_decryptor.plugins.stern import mode_write as MW           # noqa: E402
from pinball_decryptor.plugins.stern import stock_modes as SM          # noqa: E402


def _hold_modes(project):
    """Two example modes, a code mode, and a mode whose file does not load."""
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(str(project), spec=spec)
    root = pathlib.Path(MP.modes_dir(str(project)))
    (root / "blitz").mkdir()
    (root / "blitz" / "blitz.c").write_text("/* a mode */\n")
    (root / "zz_broken").mkdir()
    (root / "zz_broken" / MP.MODE_FILE).write_text("{ not json")


def _stock_modes_staged(monkeypatch, n=3, only=None):
    """The project (or only the one at *only*) holds changes to the game's own modes (item
    145); the Write must never reach them with the switch off."""
    def never(*a, **k):
        raise AssertionError("the game's own modes were read with the switch off")

    def mine(project):
        return only is None or os.path.normcase(os.path.abspath(str(project))) == \
            os.path.normcase(os.path.abspath(str(only)))
    monkeypatch.setattr(SM, "pending_count", lambda project: n if mine(project) else 0)
    monkeypatch.setattr(SM, "manages", lambda project: mine(project))
    monkeypatch.setattr(SM, "compute_writes", never)
    monkeypatch.setattr(SM, "restore_count", never)


def test_the_gate_names_the_switch(tmp_path):
    ok, why = MW.gate(False, lambda: (True, ""), platform="linux")
    assert not ok and why == MW.PREVIEW_REFUSAL
    assert "Settings > Preview features" in why
    project = tmp_path / "p"
    _hold_modes(project)
    held = MW.held_modes(str(project))
    assert len(held) == 4 and held == sorted(held) and {"blitz", "zz_broken"} <= set(held)
    assert MW.preview_left_out(str(tmp_path / "empty")) == ""


def test_try_it_refuses_with_the_switch_off(tmp_path):
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    project = tmp_path / "p"
    _hold_modes(project)
    with pytest.raises(MW.ModeWriteError, match="Settings > Preview features"):
        MW.build_tryit_set(str(project), str(tmp_path / "card.raw"), str(tmp_path / "t"))
    with pytest.raises(MT.TryItError, match="Settings > Preview features"):
        MT.build_set(str(project), str(tmp_path / "card.raw"), base=str(tmp_path / "t"))


def test_a_write_of_only_modes_says_it_leaves_them_out(tmp_path, monkeypatch):
    project = tmp_path / "p"
    _hold_modes(project)
    _stock_modes_staged(monkeypatch)
    msgs = []
    with pytest.raises(engine.NothingToWrite) as got:
        engine._compute_patches(io.BytesIO(b""), [], str(project),
                                log=lambda m, lvl="info": msgs.append((lvl, m)),
                                progress=None, cancel=lambda: False)
    said = [m for _l, m in msgs if m.startswith(MW.PREVIEW_LEFT_OUT)]
    assert said == ["Left out of this build: this project's 4 preview item(s) (%s) and 3 "
                    "preview change(s): %s."
                    % (", ".join(MW.held_modes(str(project))), MW.PREVIEW_REFUSAL)]
    assert [lvl for lvl, m in msgs if m == said[0]] == ["warning"]
    assert str(got.value).startswith("Nothing to write: this project's 4 preview item(s) (")
    assert MW.PREVIEW_REFUSAL in str(got.value)
    # a copy without a code names no feature: not the mode maker, not modes
    for text in [m for _l, m in msgs] + [str(got.value)]:
        text = text.replace(str(tmp_path), "").lower()      # the test's own folder name
        assert "mode maker" not in text and "modes" not in text, text


def test_a_write_of_only_stock_mode_changes_refuses_as_it_always_did(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    _stock_modes_staged(monkeypatch)
    msgs = []
    with pytest.raises(engine.NothingToWrite) as got:
        engine._compute_patches(io.BytesIO(b""), [], str(project),
                                log=lambda m, lvl="info": msgs.append(m),
                                progress=None, cancel=lambda: False)
    assert str(got.value).startswith("Nothing to write: every sound")
    assert any("this project's 3 preview change(s): " in m for m in msgs)
    assert not [m for m in msgs if "mode" in m.replace(str(tmp_path), "").lower()]
    assert not engine._stock_mode_managed(str(project))
    assert engine._stock_mode_pending(str(project)) == 0
    assert not engine._stock_mode_restore_ok(str(project), str(tmp_path / "out.raw"))


def _write_off(monkeypatch, tmp_path, name, with_modes):
    """_compute_patches of a project with one LONGER replacement sound (the grow path, where
    the family changed the encode, the key mask and the durations), and optionally the
    modes, a broken mode and changes to the game's own modes."""
    from tests.test_stern_audio_grow import BLOCK, _edits, _grow_card, _params
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True, shadows=4)
    work = tmp_path / name
    work.mkdir()
    _reader, staged = _grow_card(monkeypatch, work, params, grown_rows=grown)
    assets, _wav = _edits(work, 2.0)
    if with_modes:
        _hold_modes(assets)
    seen = {"encode": [], "last_only": []}

    def encode(gr, img, prm, ed, np, lg, pr, cx, **k):
        seen["encode"].append(sorted(ed))
        return ({0x40000: b"\xaa" * 64} if ed else {}), []

    def chain(*a, **k):
        raise AssertionError("appended records chain-encoded with the switch off")
    real = engine._appended_body_offsets

    def offsets(patches, places, last_only=False):
        seen["last_only"].append(last_only)
        return real(patches, places, last_only)
    monkeypatch.setattr(engine, "_encode_cat0_sounds", encode)
    monkeypatch.setattr(engine, "_chain_encode_appended", chain)
    monkeypatch.setattr(engine, "_appended_body_offsets", offsets)
    monkeypatch.setattr(engine, "_select_changed_idx_wavs",
                        lambda a, b: {0: "audio/idx0000.wav"})
    msgs = []
    out = engine._compute_patches(io.BytesIO(b""), [], str(assets),
                                  log=lambda m, lvl="info": msgs.append(m),
                                  progress=None, cancel=lambda: False)
    return out, seen, msgs, staged


def _plan_shape(plan):
    """A plan with its scratch paths replaced by what the files hold."""
    if plan is None:
        return None
    out = {}
    for k, v in plan.items():
        if k == "jobs":
            out[k] = [(rel, hashlib.md5(open(src, "rb").read()).hexdigest()) for rel, src in v]
        elif k == "cleanup":
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def test_write_with_the_switch_off_is_the_write_without_modes(tmp_path, monkeypatch):
    """THE PROOF: a project holding modes, a broken mode, a code mode and changes to the
    game's own modes, written with the switch off, gives exactly the writes, counts and
    plan of the same project with none of them - on the path the family changed most (a
    longer replacement sound: no chain encode, only the LAST appended body left
    unrestored, as a build without the family does)."""
    _stock_modes_staged(monkeypatch, only=tmp_path / "with" / "assets")
    (w_a, c_a, p_a, am_a, vp_a), seen_a, msgs_a, st_a = _write_off(monkeypatch, tmp_path,
                                                                   "with", True)
    shape_a = _plan_shape(p_a)
    engine._rmtree_grow_plan(p_a)
    (w_b, c_b, p_b, am_b, vp_b), seen_b, msgs_b, st_b = _write_off(monkeypatch, tmp_path,
                                                                   "without", False)
    shape_b = _plan_shape(p_b)
    engine._rmtree_grow_plan(p_b)
    assert w_a == w_b
    assert tuple(c_a) == tuple(c_b) == (1, 0, 0, 0)
    assert c_a.stock_modes == c_b.stock_modes == 0 and not c_a.restored
    assert shape_a == shape_b
    assert shape_a["modes"] is None and shape_a["epoch"] is None
    assert (am_a, vp_a) == (am_b, vp_b)
    # the grown sound went through the ordinary encode, and every appended-body lookup
    # asked for the last one only
    assert seen_a["encode"] == seen_b["encode"] == [[0]]
    assert seen_a["last_only"] and all(seen_a["last_only"]) and all(seen_b["last_only"])
    # the one sentence, and nothing else of the modes, in the log
    left = [m for m in msgs_a if m.startswith(MW.PREVIEW_LEFT_OUT)]
    assert len(left) == 1 and "Settings > Preview features" in left[0]
    assert "zz_broken" in left[0] and "3 preview change(s)" in left[0]
    # neutral words: no line of either Write names modes or the mode maker
    assert not [m for m in msgs_b if "mode" in m.replace(str(tmp_path), "").lower()]
    assert not [m for m in msgs_a if "mode" in m.replace(str(tmp_path), "").lower()]


def test_the_same_write_with_the_switch_on_takes_the_familys_encode(tmp_path, monkeypatch,
                                                                     preview_modes_on):
    """The control: the switch really is what decides - on, the appended record goes
    through the chain encode (and the plain encode gets none of it)."""
    from tests.test_stern_audio_grow import BLOCK, _edits, _grow_card, _params
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True, shadows=4)
    _grow_card(monkeypatch, tmp_path, params, grown_rows=grown)
    assets, _wav = _edits(tmp_path, 2.0)
    seen = {"encode": [], "chain": []}
    monkeypatch.setattr(engine, "_encode_cat0_sounds",
                        lambda gr, img, prm, ed, *a, **k: (seen["encode"].append(sorted(ed))
                                                            or ({}, [])))
    monkeypatch.setattr(engine, "_chain_encode_appended",
                        lambda gr, img, prm, ed, *a, **k: (seen["chain"].append(sorted(ed))
                                                            or ({0x40000: b"\xaa" * 64}, prm)))
    monkeypatch.setattr(engine, "_select_changed_idx_wavs",
                        lambda a, b: {0: "audio/idx0000.wav"})
    _w, _c, plan, _m, _v = engine._compute_patches(
        io.BytesIO(b""), [], str(assets), log=lambda *a, **k: None, progress=None,
        cancel=lambda: False)
    engine._rmtree_grow_plan(plan)
    assert seen == {"encode": [[]], "chain": [[0]]}


def test_a_project_with_modes_is_not_forced_to_a_whole_build(tmp_path, monkeypatch):
    from pinball_decryptor import __version__
    project = tmp_path / "p"
    _hold_modes(project)
    prev = {"version": engine.BUILD_MANIFEST_VERSION, "app": __version__, "complete": True,
            "stock": {"path": os.path.abspath(str(tmp_path / "o.raw"))},
            "assets": str(project)}
    monkeypatch.setattr(engine, "_stamp_matches", lambda s, p: True)
    assert engine.build_update_reason(prev, tmp_path / "o.raw", tmp_path / "b.raw",
                                      str(project)) is None


def test_the_completion_notes_name_the_switch(tmp_path):
    from pinball_decryptor.plugins.stern import pipeline
    project = tmp_path / "p"
    _hold_modes(project)
    for note in (pipeline._image_modes_left_out_note(str(project), None),
                 pipeline._direct_sd_modes_note(str(project))):
        assert "this project's 4 preview item(s)" in note and "zz_broken" in note
        assert MW.PREVIEW_REFUSAL in note and "mode" not in note.lower()
    assert pipeline._image_modes_left_out_note(str(tmp_path / "none"), None) == ""


def test_the_emulate_tab_rebuilds_a_set_when_the_switch_changes(tmp_path):
    from pinball_decryptor.gui.emulate_tab import preview_modes_reason
    project = tmp_path / "p"
    _hold_modes(project)
    built_off = {"files": [], "modes_preview": False}
    assert "switched off" in preview_modes_reason({"files": [], "modes_preview": True},
                                                  str(project))
    assert preview_modes_reason(built_off, str(project)) == ""
    assert preview_modes_reason({"files": []}, str(project)) == ""
    assert "switched on" in preview_modes_reason(built_off, str(project), on=True)
    # a project without modes never rebuilds for it
    assert preview_modes_reason({"modes_preview": True}, str(tmp_path / "none")) == ""
    assert preview_modes_reason(None, str(project)) == ""


def test_a_settings_step_with_the_switch_off_writes_every_staged_setting():
    """app.py leaves a Modes-tab timer to the Write only with the switch on; off, the
    Write put nothing of the Modes tab's in the program, so the settings step writes it."""
    src = (REPO / "pinball_decryptor" / "app.py").read_text(encoding="utf-8")
    i = src.index("settings_already_built(")
    assert "_mode_write.preview_on()" in src[i - 400:i]


def test_init_refuses_appdata_from_a_packaged_windows_process(tmp_path, monkeypatch):
    """2026-09-18: init run from the Claude desktop app (an MSIX package) wrote the key to
    %APPDATA%, and Windows redirected it into the app's own folder, where Explorer could
    not see it. init now refuses the AppData default from a packaged process."""
    tool = _tool()
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(tool, "appdata_redirect_target",
                        lambda: str(tmp_path / "Local" / "Packages" / "Some.App_abc"
                                    / "LocalCache" / "Roaming"))
    with pytest.raises(SystemExit) as e:
        tool.main(["init", "--key", str(tmp_path / "Roaming" / "pinball_decryptor_signing"
                                         / tool.KEY_NAME)])
    assert "packaged app" in str(e.value) and "Some.App_abc" in str(e.value)
    assert not (tmp_path / "Roaming" / "pinball_decryptor_signing").exists()


def test_issue_finds_a_key_windows_redirected_into_a_package(tmp_path, monkeypatch, capsys):
    tool = _tool()
    if sys.platform != "win32":
        monkeypatch.setattr(tool.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    moved = tmp_path / "Local" / "Packages" / "Some.App_abc" / "LocalCache" / "Roaming" \
        / "pinball_decryptor_signing" / tool.KEY_NAME
    moved.parent.mkdir(parents=True)
    secret = bytes(range(32))
    moved.write_text("%s\npublic=%s\nsecret=%s\n" % (tool.KEY_MARKER,
                     E.public_key(secret).hex(), secret.hex()), encoding="utf-8")
    assert tool.redirected_keys() == [str(moved)]
    monkeypatch.setattr(tool.preview, "PUBLIC_KEYS", (E.public_key(secret).hex(),))
    assert tool.main(["issue", "--name", "Test Person", "--days", "3"]) == 0
    out = capsys.readouterr()
    assert out.out.strip().startswith("PAD-PREVIEW-")
    assert "redirected" in out.err
