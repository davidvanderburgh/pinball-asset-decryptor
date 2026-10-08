"""PAD-460: Auto-name now names the sounds of a project that is already
extracted, and the voice recognition quality sits beside Auto-name call-outs.

A tester extracted without Auto-name call-outs, then found no way to name the
sounds short of extracting again, and had never found the quality setting in
the ⚙ menu at all.
"""

import csv
import os
import time
import wave

from tests.webui_harness import web_app


def until(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _wav(path):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\0\0" * 800)


def _extracted(tmp_path, name="proj"):
    """A project folder holding an extract: WAVs under audio/ + the baseline."""
    folder = tmp_path / name
    (folder / "audio").mkdir(parents=True)
    _wav(folder / "audio" / "idx0001.wav")
    _wav(folder / "audio" / "idx0002.wav")
    (folder / ".checksums.md5").write_text(
        "d41d8cd98f00b204e9800998ecf8427e  audio/idx0001.wav\n",
        encoding="utf-8")
    return folder


class _FakePipe:
    def __init__(self, done_cb, ok, summary):
        self.done_cb, self.ok, self.summary = done_cb, ok, summary

    def run(self):
        self.done_cb(self.ok, self.summary)

    def cancel(self):
        pass


def _fake_steps(monkeypatch, mfr, calls, callouts_ok=True):
    def transcribe(assets_dir, log_cb, phase_cb, progress_cb, done_cb,
                   rename_after=False, model_size="tiny.en"):
        calls.append(("callouts", assets_dir, model_size, rename_after))
        return _FakePipe(done_cb, callouts_ok,
                         "Transcribed 2 speech sample(s)." if callouts_ok
                         else "Auto-transcribe needs faster-whisper.")

    def music(assets_dir, log_cb, phase_cb, progress_cb, done_cb,
              rename_after=False):
        calls.append(("music", assets_dir, None, rename_after))
        return _FakePipe(done_cb, True, "Identified 1 of 1 music clip(s).")

    monkeypatch.setattr(mfr, "make_transcribe_pipeline", transcribe)
    monkeypatch.setattr(mfr, "make_music_id_pipeline", music)


def _spy_log(monkeypatch, win):
    lines = []
    real = win.append_log

    def spy(text, level="info"):
        lines.append((str(text), level))
        return real(text, level)
    monkeypatch.setattr(win, "append_log", spy)
    return lines


# ------------------------------------------------------------- the gate
def test_auto_name_now_waits_for_an_extract_and_an_option(tmp_path):
    folder = _extracted(tmp_path)
    bare = tmp_path / "empty"
    bare.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        w.run(win.extract_output_var.set, str(folder))
        w.run(win.transcribe_var.set, False)
        w.run(win.music_id_var.set, False)
        assert w.state("extract")["autoname_reason"] == (
            "Tick Auto-name call-outs or Auto-name music first.")
        assert w.call("extract.autoname_now") is False
        w.run(win.music_id_var.set, True)
        assert w.state("extract")["autoname_reason"] == ""
        w.run(win.music_id_var.set, False)
        w.run(win.transcribe_var.set, True)
        assert w.state("extract")["autoname_reason"] == ""
        w.run(win.extract_output_var.set, str(bare))
        assert w.state("extract")["autoname_reason"] == (
            "This project folder holds no extract yet.")
        assert w.call("extract.autoname_now") is False
        w.run(win.extract_output_var.set, "")
        assert w.state("extract")["autoname_reason"] == (
            "Choose a project folder first.")


# ------------------------------------------------------------- the run
def test_auto_name_now_names_the_project_without_extracting(
        tmp_path, monkeypatch):
    """Call-outs at the picked quality, then music, over the project folder;
    the run finishes as a naming run, not as an extract."""
    folder = _extracted(tmp_path)
    with web_app(tmp_path, mfr="stern",
                 settings={"voice_quality": "small.en"}) as w:
        app, win = w.app, w.window
        calls = []
        _fake_steps(monkeypatch, app._current_mfr, calls)
        lines = _spy_log(monkeypatch, win)
        rescans = []
        monkeypatch.setattr(win, "invalidate_asset_scans",
                            lambda *a: rescans.append(a))
        w.run(win.extract_output_var.set, str(folder))
        w.run(win.transcribe_var.set, True)
        w.run(win.music_id_var.set, True)
        assert w.call("extract.autoname_now") is True
        assert until(w, lambda: not win._is_running()
                     and any("Identified" in t for t, _l in lines))
        assert [c[0] for c in calls] == ["callouts", "music"]
        assert calls[0][1] == os.path.normpath(str(folder))
        assert calls[0][2] == "small.en"            # the picked quality
        assert calls[0][3] and calls[1][3]          # both rename
        text = "\n".join(t for t, _l in lines)
        assert "Auto-name call-outs:\nTranscribed 2" in text
        assert "Auto-name music:\nIdentified 1" in text
        assert "Extract completed" not in text
        assert rescans                              # the Replace tabs rescan
        assert not w.asked                          # no modal on success
        assert app._autoname_active is False
        assert w.state("shell")["running"] is False


def test_a_failed_step_says_so_and_the_next_still_runs(tmp_path, monkeypatch):
    folder = _extracted(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        app, win = w.app, w.window
        calls = []
        _fake_steps(monkeypatch, app._current_mfr, calls, callouts_ok=False)
        w.run(win.extract_output_var.set, str(folder))
        w.run(win.transcribe_var.set, True)
        w.run(win.music_id_var.set, True)
        assert w.call("extract.autoname_now") is True
        assert until(w, lambda: bool(w.asked))
        assert [c[0] for c in calls] == ["callouts", "music"]
        box = w.asked[-1]
        assert box["title"] == "Auto-name Failed"
        assert "Auto-name call-outs failed:" in box["message"]
        assert "Auto-name music:" in box["message"]
        assert until(w, lambda: not win._is_running())


def test_only_the_ticked_option_runs(tmp_path, monkeypatch):
    folder = _extracted(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        app, win = w.app, w.window
        calls = []
        _fake_steps(monkeypatch, app._current_mfr, calls)
        w.run(win.extract_output_var.set, str(folder))
        w.run(win.transcribe_var.set, True)
        w.run(win.music_id_var.set, False)
        assert w.call("extract.autoname_now") is True
        assert until(w, lambda: not win._is_running() and calls)
        assert [c[0] for c in calls] == ["callouts"]


# --------------------------------------------- re-running over a named folder
def test_callouts_csv_keeps_the_rows_of_files_named_before(tmp_path):
    from pinball_decryptor.core import transcribe as T
    (tmp_path / "audio").mkdir()
    _wav(tmp_path / "audio" / "idx0001 - Super jackpot.wav")
    _wav(tmp_path / "audio" / "idx0002.wav")
    with open(tmp_path / T.CALLOUTS_CSV, "w", encoding="utf-8",
              newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["folder", "file", "seconds", "classification", "text"])
        cw.writerow(["audio", "idx0001 - Super jackpot.wav", "0.100",
                     "speech", "Super jackpot!"])
        cw.writerow(["audio", "idx0002.wav", "0.100", "non-speech", ""])
        cw.writerow(["audio", "idx0009 - gone.wav", "0.100", "speech", "gone"])
    rows = T._keep_earlier_rows(
        str(tmp_path), [("audio/idx0002.wav", "speech", "Multiball")])
    assert rows == [
        ("audio/idx0001 - Super jackpot.wav", "speech", "Super jackpot!"),
        ("audio/idx0002.wav", "speech", "Multiball")]
    # no earlier CSV: this run's rows as they are
    other = tmp_path / "other"
    other.mkdir()
    new = [("b.wav", "speech", "x"), ("a.wav", "speech", "y")]
    assert T._keep_earlier_rows(str(other), new) is new


def test_a_folder_named_already_is_not_an_error(tmp_path):
    from pinball_decryptor.core import transcribe as T
    (tmp_path / "audio").mkdir()
    _wav(tmp_path / "audio" / "idx0001 - Super jackpot.wav")
    assert T._find_wavs(str(tmp_path)) == []
    assert T._has_named_wavs(str(tmp_path))
    done = {}
    p = T.TranscribePipeline(
        str(tmp_path), lambda *a: None, lambda *a: None, lambda *a: None,
        lambda ok, msg: done.update(ok=ok, msg=msg), rename_after=False)
    p.run()
    assert done["ok"] is True, done
    assert "already has a name" in done["msg"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not T._has_named_wavs(str(empty))


def test_music_titles_csv_keeps_the_rows_of_tracks_named_before(tmp_path):
    from pinball_decryptor.core import musicid as M
    _wav(tmp_path / "idx0139 - Led Zeppelin - Kashmir.wav")
    with open(tmp_path / M.MUSIC_IDS_CSV, "w", encoding="utf-8",
              newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["relative_path", "title", "artist", "score"])
        cw.writerow(["idx0139 - Led Zeppelin - Kashmir.wav", "Kashmir",
                     "Led Zeppelin", "0.970"])
        cw.writerow(["idx0200 - music.wav", "", "", "0.000"])
    lines = M._keep_earlier_titles(
        str(tmp_path), [["idx0200 - music.wav", "", "", "0.000"]])
    assert lines == [
        ["idx0139 - Led Zeppelin - Kashmir.wav", "Kashmir", "Led Zeppelin",
         "0.970"],
        ["idx0200 - music.wav", "", "", "0.000"]]


def test_music_over_a_folder_named_already_is_not_an_error(tmp_path):
    from pinball_decryptor.core import musicid as M
    _wav(tmp_path / "idx0139 - Led Zeppelin - Kashmir.wav")
    done = {}
    p = M.MusicIdPipeline(
        str(tmp_path), log_cb=lambda t, l: None, phase_cb=lambda i: None,
        progress_cb=lambda a, b, d: None,
        done_cb=lambda ok, msg: done.update(ok=ok, msg=msg),
        client_key="KEY", min_music_seconds=0.01, rename_after=True)
    p.run()
    assert done["ok"] is True, done
    assert "already has a name" in done["msg"]
