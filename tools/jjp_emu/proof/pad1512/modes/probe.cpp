// PAD-1512 proof: the game_mode callback, jm_player and jm_played (jjp_mode.h API 2).
#include "jjp_mode.h"
static void game_mode(const char *name, const char *cls, int started)
{
    jm_log("game_mode %s (%s) %s - player %d; played cl_mode %d, CandyLaneMode %d, gobstopper_mb %d",
           name, cls, started ? "started" : "ended", jm_player(), jm_played("cl_mode"),
           jm_played("CandyLaneMode"), jm_played("gobstopper_mb"));
}
JM_REGISTER({ .api = JM_API, .game_mode = game_mode });
