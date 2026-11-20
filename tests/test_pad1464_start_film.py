"""PAD-1464 (found by PAD-1410): a menu opened as a game starts (a whole-game mode's roster) was drawn under the game's
own start-of-game film (Uncanny X-Men 0.98's GameIntro, about 15 s) and ran out its time unseen. The runtime watches
the clips the game asks for at its start (pm_start_film, pad_mode_runtime.c "PAD-1464: the game's own start-of-game
film") and the kit's menu - so a blocks mode's Open the menu too - waits for the film: not drawn, its time held, its
buttons the game's, then up with its whole time.

Emulator-proven on every newest Spike 2 build (C:/tmp/PAD-1464: census_job.sh, the menu job)."""
import pathlib
import re

from tests import test_spike2_mode_roster as R
from tests.test_pad1404_menus import _picked, _prog
from tests.test_stern_block_modes import play

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"

MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    const char *names[] = { "GameIntro", "GameStartSplashScreen", "Game_Start1", "intro3", "INTRO",
                            "BlackKnight_PhotoShoot_TitleScreen", "JawsIntroToIsland_Title", "CityStreetMainPlay",
                            "MainplayBG_Taunt_MG", "Player_1_Up", "game_intro_loop", "TMNT_MainPlay_Start_Looping",
                            "JawsMapProgressBGLooping", "", 0 };
    int k;
    for (k = 0; names[k]; k++) printf("%d", sf_named_film(names[k]));
    printf("|%d%d%d%d", sf_listed(0, "GameIntro"), sf_listed("GameIntro", "GameIntro"), sf_listed("GameIntro", "GameIntro2"),
           sf_listed("GameIntro", "Game"));
    printf("%d%d%d", sf_listed("intro*", "intro4"), sf_listed("intro*", "outro"), sf_listed("GameStartSplashScreen GameIntro",
           "GameIntro"));
    printf("%d%d\n", sf_listed("-", "GameIntro"), sf_listed("-", "-"));
    return 0;
}
"""
FNS = ("static int sf_listed(const char *list, const char *name)", "static int sf_has(const char *name, const char *word)",
       "static int sf_named_loop(const char *name)", "static int sf_named_film(const char *name)")


def test_the_names_of_a_start_film(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    code = MAIN.replace("@FNS@", "\n".join(R._lift(src, s) for s in FNS))
    named, listed = R._host_run(tmp_path, code, flags=("-no-pie",)).strip().split("|")
    # intro / start / title in the name, any case, says film; a main-play background, a ball's screen or a loop does not
    # (Jaws' game_intro_loop after its film, TMNT's character select, Jurassic Park's map after its island flight)
    assert named == "11111110000000"
    # no line: -1; exact names and prefixes; "-" (the title's Start plays none) matches nothing
    assert listed == "-110010100"


def _menu_at(tmp_path, *between, seconds=4, hold="lane"):
    return play(tmp_path, _prog(hold=hold, seconds=seconds), "film", 1, "shot", "Building", *between,
                slug="episode_pick")


def test_a_menu_opened_under_the_start_film_waits_for_it_then_has_its_whole_time(tmp_path):
    out = _menu_at(tmp_path, "secs", 12,                                       # longer than its 4 s
                   "shot", "Right flipper button", "ms", 300,                    # the game's flipper, not the menu's
                   "film", 0, "ms", 500,
                   "shot", "Right flipper button", "secs", 5)
    assert "the game's start film is playing - it comes up when the film is over" in out
    assert re.search(r"the game's start film is over - up now, 4000 ms, \d+ button\(s\) held back", out)
    assert _picked(out) == [("3", "AGE OF APOCALYPSE", "its time ran out")]    # on 2, one right after the film
    film_end = int(re.search(r"^\s*(\d+) >> film 0", out, re.M).group(1))
    picked = int(re.search(r"^\s*(\d+) .*menu PadMode_episode_pick_Menu1: picked", out, re.M).group(1))
    assert picked - film_end >= 4000                                           # its whole time after the film
    before = out.split(">> film 0")[0]
    assert "BTNHIDE 7400000000000000" not in before                             # its buttons stayed the game's
    assert not re.search(r"SHOW PadMode_episode_pick_Menu1 1", before)          # not drawn under the film
    assert re.search(r"SHOW PadMode_episode_pick_Menu1 1", out.split(">> film 0")[1])


def test_a_lane_menu_under_the_film_takes_its_default_when_the_ball_is_plunged(tmp_path):
    out = _menu_at(tmp_path, "ms", 800, "shot", "Left ramp", "ms", 300, "film", 0, "secs", 6)
    assert _picked(out) == [("2", "DARK PHOENIX", "the ball moved on under the game's start film: Left ramp")]
    assert "BTNHIDE 7400000000000000" not in out


def test_with_no_film_the_menu_comes_up_at_once_as_before(tmp_path):
    out = play(tmp_path, _prog(seconds=4), "shot", "Building", "ms", 300, "shot", "Right flipper button",
               "secs", 5, slug="episode_pick")
    assert "start film" not in out
    assert _picked(out) == [("3", "AGE OF APOCALYPSE", "its time ran out")]


def test_the_sdk_declares_it_and_the_runtime_watches_every_clip_call():
    head = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert "int pm_start_film(void);" in head
    src = RUNTIME.read_text(encoding="utf-8")
    assert "int pm_start_film(void)\n{" in src
    for call in ("sv_sf = 1, sv_hook()", 'hook(fn("clip_play"), sf_on_clip_play)', 'hook(fn("layer_video"), sf_on_layer)'):
        assert call in src
    kit = (SDK / "examples" / "intricate_kit.h").read_text(encoding="utf-8")
    assert "m->film = pm_start_film();" in kit


def test_every_port_naming_its_films_names_real_words():
    """`text start_film_clips`: clip names (a trailing * a prefix), or "-" alone for a title whose Start plays none."""
    seen = 0
    for p in sorted(PORTS.glob("*.port")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("text start_film_clips"):
                words = line.split()[2:]
                assert words, p.name
                assert words == ["-"] or all(re.fullmatch(r"[A-Za-z0-9_.\-]+\*?", w) and w != "-" for w in words), \
                    (p.name, line)
                seen += 1
    assert seen >= 2
