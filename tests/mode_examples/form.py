"""Godzilla's four form modes (KAIJU RUSH, ATOMIC BREATH, MOTHRA'S SONG, MECHAGODZILLA), test material only.

PAD-691: the app offered them as examples on a Godzilla card until David took every game-specific example out ("we
don't need game-specific demo modes like this committed to the app"); TARGET RUSH (mode_project.examples_for) is
the one example now. The tests still build, write and retarget these, so they live here, exactly as the app had them.

KAIJU RUSH is the mode as it ran on a real Godzilla Premium 1.16 (2026-09-16: video, audio, scenes and scoring all
working); the others are variations on it that need no file of their own (a generated panel and a title card each).
"""
from pinball_decryptor.plugins.stern import mode_project as MP

#: PAD-414: their shakes, where the game can shake its cabinet (:func:`godzilla_examples`): MECHAGODZILLA starts big
#: (the game's own multiball start) and every Godzilla target is a jackpot (the game's jackpot shake)
SHAKES = {"MECHAGODZILLA": [["start", "multiball_start", 0, ""], ["shot", "jackpot", 0, "Godzilla target"]]}


def example_specs():
    """``[(name, ModeSpec)]``, a fresh copy each call."""
    def make(name, **kw):
        return name, MP.ModeSpec(name=name, **kw)
    return [
        make("KAIJU RUSH", start_shot="Maser target", start_count=3, seconds=30,
             scoring_shots=["Powerline left", "Powerline center", "Powerline right",
                            "Left ramp", "Right ramp"],
             award=1000000, screen=True, clip="title", clip_when="start",
             countdown=True, lights=True, light_color="#00ff00"),
        make("ATOMIC BREATH", start_shot="Godzilla target", start_count=2, seconds=25,
             scoring_shots=["Building", "Left ramp", "Right ramp"], award=750000,
             panel_color="#0b3d91", title_color="#7fe7ff", clip="title", clip_when="start",
             light_color="#00c8ff"),
        make("MOTHRA'S SONG", start_shot="Big loop", start_count=2, seconds=40,
             scoring_shots=["Shield target left", "Shield target right", "Big loop"],
             award=500000, panel_color="#6b4e00", title_color="#fff1a8", clip="title",
             clip_when="end", light_color="#ffd200"),
        make("MECHAGODZILLA", start_shot="Building", start_count=3, seconds=20,
             scoring_shots=["Powerline center", "Maser target", "Godzilla target"],
             award=1500000, panel_color="#3a3a3a", title_color="#ff3b3b", clip="title",
             clip_when="start", light_color="#ff0000"),
    ]


def example(name):
    """The mode called ``name``, or None."""
    for n, spec in example_specs():
        if n == name:
            return spec
    return None


def godzilla_examples(p):
    """The four for title ``p``, as the app made them there: each where every shot it names exists, with its shakes
    where the game can shake its cabinet, and what ``p`` cannot do switched off."""
    names = {n for n, _m in p.shots}
    out = []
    for name, spec in example_specs():
        if spec.start_shot in names and all(s in names for s in spec.scoring_shots):
            spec.title = p.key
            games = {n for n, _l in getattr(p, "shakes", ())}
            shakes = SHAKES.get(name, [])
            if p.can("shaker") and all(r[1] in games and (not r[3] or r[3] in names) for r in shakes):
                spec.shakes = [list(r) for r in shakes]
            out.append((name, MP._switch_off_what_it_cannot(spec, p)))
    return out
