"""An out-of-memory transcription is not a finding about the audio.

A tester ran two copies of the app to extract two card versions at once.  180
of his 927 clips came back with allocation failures from three different
layers, and every one of them was written into callouts.csv as "non-speech",
counted in the skipped total, and left unnamed -- the run summary said
"Transcribed 113 speech sample(s); skipped 803 non-speech sample(s)" with
nothing to say a fifth of the skips were failures.

Those clips now come back as kind "error", get retried once the worker pool has
released its models, and are counted and explained if they still fail.
"""
import pinball_decryptor.core.transcribe as T


class _Boom:
    """A model whose transcribe() raises for the first *n* calls."""

    def __init__(self, exc, fails=99, text="hello there"):
        self.exc, self.fails, self.text, self.calls = exc, fails, text, 0

    def transcribe(self, path, **kw):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        seg = type("S", (), {"text": self.text})()
        info = type("I", (), {"duration": 1.0})()
        return iter([seg]), info


# --- recognising the failure ----------------------------------------------

def test_every_allocator_the_tester_hit_is_recognised():
    for msg in ("mkl_malloc: failed to allocate memory",
                "could not create a memory object",
                "[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : ... Status "
                "Message: bad allocation",
                "[Errno 12] Cannot allocate memory",
                "Unable to allocate 209. MiB for an array with shape "
                "(95107, 576) and data type float32"):
        assert T._looks_like_out_of_memory(msg), msg
        assert T._looks_like_out_of_memory(RuntimeError(msg)), msg


def test_a_real_audio_problem_is_not_mistaken_for_memory():
    assert not T._looks_like_out_of_memory(ValueError("file does not start "
                                                      "with RIFF id"))


# --- what _transcribe_one does with it ------------------------------------

def test_a_transient_squeeze_is_retried_and_succeeds(monkeypatch):
    monkeypatch.setattr(T, "_OOM_RETRY_WAITS", (0.0, 0.0))
    model = _Boom(RuntimeError("mkl_malloc: failed to allocate memory"),
                  fails=2)
    rel, kind, text, err = T._transcribe_one(model, "audio/idx0001.wav",
                                             "x.wav", 20.0)
    assert (kind, text, err) == ("speech", "hello there", None)
    assert model.calls == 3


def test_a_clip_that_never_fits_is_an_error_not_non_speech(monkeypatch):
    monkeypatch.setattr(T, "_OOM_RETRY_WAITS", (0.0, 0.0))
    model = _Boom(RuntimeError("mkl_malloc: failed to allocate memory"))
    rel, kind, text, err = T._transcribe_one(model, "audio/idx0419.wav",
                                             "x.wav", 20.0)
    assert kind == "error"
    assert "mkl_malloc" in err


def test_a_non_memory_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(T, "_OOM_RETRY_WAITS", (0.0, 0.0))
    model = _Boom(ValueError("not a WAV"))
    _rel, kind, _text, err = T._transcribe_one(model, "audio/idx0001.wav",
                                               "x.wav", 20.0)
    assert kind == "error" and "not a WAV" in err
    assert model.calls == 1          # one attempt, no backoff


def test_retries_can_be_switched_off_for_the_rescue_pass():
    model = _Boom(RuntimeError("mkl_malloc: failed to allocate memory"))
    T._transcribe_one(model, "audio/idx0001.wav", "x.wav", 20.0, oom_retries=0)
    assert model.calls == 1


# --- tallying --------------------------------------------------------------

def test_errors_are_counted_apart_from_skips():
    c = T._new_counts()
    for kind in ("speech", "non-speech", "music", "error", "error"):
        T._tally(c, kind)
    assert (c["speech"], c["non"], c["music"], c["error"]) == (1, 1, 1, 2)


def test_an_untranscribed_row_does_not_read_as_silence():
    assert T._row_tag("error", "") == "[not transcribed]"
    assert T._row_tag("non-speech", "") == "[no speech]"
    assert T._row_tag("music", "") == "[music]"
    assert T._row_tag("speech", "hi") == "hi"


# --- the rescue pass -------------------------------------------------------

class _Pipe(T.TranscribePipeline):
    """A pipeline with the model load and the WAV read stubbed out."""

    def __init__(self, assets_dir, model):
        # BasePipeline binds _log as an INSTANCE attribute, so capture through
        # the callback rather than by overriding the method.
        self.logged = []
        super().__init__(assets_dir,
                         lambda msg, level="info": self.logged.append(msg),
                         lambda *a: None, lambda *a, **k: None,
                         lambda *a, **k: None)
        self._model = model

    def _load_model(self):
        return self._model

    def _check_cancel(self):
        pass


def test_the_pool_leftovers_are_retried_one_at_a_time(tmp_path):
    model = _Boom(RuntimeError("mkl_malloc"), fails=0, text="close your eyes")
    p = _Pipe(str(tmp_path), model)
    counts = T._new_counts()
    for kind in ("speech", "error", "error"):
        T._tally(counts, kind)
    counts["oom"] = ["audio/idx0419.wav", "audio/idx0722.wav"]
    rows = [("audio/idx0001.wav", "speech", "ok"),
            ("audio/idx0419.wav", "error", ""),
            ("audio/idx0722.wav", "error", "")]

    rows = p._retry_out_of_memory(rows, counts)

    assert rows[1] == ("audio/idx0419.wav", "speech", "close your eyes")
    assert rows[2] == ("audio/idx0722.wav", "speech", "close your eyes")
    assert counts["error"] == 0 and counts["speech"] == 3
    assert counts["oom"] == []
    assert any("Recovered 2 of 2" in m for m in p.logged)


def test_a_clip_that_fails_the_retry_stays_an_error(tmp_path):
    model = _Boom(RuntimeError("mkl_malloc: failed to allocate memory"))
    p = _Pipe(str(tmp_path), model)
    counts = T._new_counts()
    T._tally(counts, "error")
    counts["oom"] = ["audio/idx0419.wav"]
    rows = [("audio/idx0419.wav", "error", "")]

    rows = p._retry_out_of_memory(rows, counts)

    assert rows[0][1] == "error"
    assert counts["error"] == 1
    assert model.calls == 1          # no second round of in-worker backoff


def test_nothing_to_retry_is_a_no_op(tmp_path):
    p = _Pipe(str(tmp_path), _Boom(RuntimeError("x")))
    rows = [("audio/idx0001.wav", "speech", "ok")]
    assert p._retry_out_of_memory(list(rows), T._new_counts()) == rows
    assert p.logged == []
