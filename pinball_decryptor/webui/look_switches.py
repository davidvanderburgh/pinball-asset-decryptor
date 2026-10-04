"""The preview's three colour switches (PAD-330) remembered between runs (PAD-348).

Scenes and the Video players each have the whole screen overlay, individual files and
machine screen switches.  They used to start all on at every launch; DragonRR: "Please
save and remember the user last known settings."  Each place keeps its own set in the
app's settings under ``look_switches`` -> ``{"scenes": {...}, "video": {...}}``."""

PARTS = ("overlay", "files", "screen")


def initial(window, where):
    """The switches *where* ("scenes" or "video") was left with, all on if never set."""
    sw = {k: True for k in PARTS}
    cb = getattr(window, "cb", None) or {}
    try:
        saved = (cb.get("initial_look_switches") or {}).get(where) or {}
        for k in PARTS:
            if k in saved:
                sw[k] = bool(saved[k])
    except Exception:                               # noqa: BLE001  a damaged settings file
        pass
    return sw


def save(window, where, sw):
    """Keep *sw* for the next launch (and this run's later services)."""
    cb = getattr(window, "cb", None) or {}
    got = dict(cb.get("initial_look_switches") or {})
    got[where] = {k: bool(sw.get(k, True)) for k in PARTS}
    try:
        cb["initial_look_switches"] = got
    except Exception:                               # noqa: BLE001
        pass
    fn = cb.get("on_look_switches_change")
    if fn is not None:
        fn(got)
