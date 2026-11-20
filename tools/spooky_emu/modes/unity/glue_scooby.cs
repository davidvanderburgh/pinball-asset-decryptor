// glue_scooby.cs - PadModes on Scooby-Doo's framework (PAD-1417): Machine, Modes.add_mode,
// int[] messages (Messages.offset_message / offset_data), Switches.get_switch_name, Callouts
// (static string fields -> Resources paths) and Machine.enqueue_callout, Game.score_points
// (x10, rounded to 100; one *mode* tag or it logs an error: "base", plus "bonus" for a flat award).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace PadModes {

public class Hook : Mode {
    public Hook(Machine m) : base(m) {
        name = "PAD custom modes";
        mode = PadRuntime.ModeId;
    }

    public override int init() { return 0; }
    public override int update() { return 0; }

    public override int process_message(int[] msg) {
        try {
            var r = Loader.Runtime;
            int what = msg[Messages.offset_message], data = msg[Messages.offset_data];
            if (what == Messages.switch_active) r.OnSwitch(data);
            else if (what == Messages.new_game_started) r.OnNewGame();
            else if (what == Messages.ball_start) r.OnBallStart();
            else if (what == Messages.end_of_ball) r.OnBallEnd("the ball ended");
            else if (what == Messages.tilt) r.OnBallEnd("tilt");
            else if (what == Messages.ball_saved) r.GameEvent("ball_saved");
            else if (what == Messages.mode_started && data == Modes.attract_mode) r.OnGameEnd();
        } catch (Exception e) { Loader.Log("process_message: " + e); }
        return 0;
    }
}

public static class Glue {
    public const string Framework = "scooby";
    static Hook hook;
    static List<Sw> sw;
    static Dictionary<string, string> callouts;
    public static readonly string[] Tags = { "base", "bonus" };

    public static bool Ready() { return Machine.modes_loaded; }

    public static bool Ensure(PadRuntime r) {
        if (hook != null) return false;
        hook = new Hook(Modes.machine);
        Modes.add_mode(hook);
        return true;
    }

    public static int ModeCount() { return Modes.modes.Count; }
    public static void Poll(PadRuntime r) { }

    public static List<Sw> Switches() {
        if (sw != null || global::Switches.name == null) return sw ?? new List<Sw>();
        sw = new List<Sw>();
        for (int i = 0; i < global::Switches.name.Count; i++) {
            string label = global::Switches.name[i], sym = null;
            if (string.IsNullOrEmpty(label) || label.StartsWith("UNUSED")) continue;
            try { sym = global::Switches.get_switch_name(i); } catch (Exception) { }
            if (!string.IsNullOrEmpty(sym)) sw.Add(new Sw(sym, i, label));
        }
        return sw;
    }

    public static string SwitchName(int n) {
        try { return global::Switches.get_switch_name(n); } catch (Exception) { return "#" + n; }
    }

    public static bool HasPlayers() {
        Game g = Mode.machine.game;
        return g != null && g.players != null && g.players.Count > 0;
    }

    // ---- balls and game modes (PAD-1424 start rules)
    static Player Up() { return HasPlayers() ? Mode.machine.game.player() : null; }
    public static int BallsPerGame() { return (int)Mode.machine.settings.balls_per_game.current_value; }
    // no ball number of its own: balls_remaining counts down at each ball's end (not an extra ball's)
    public static int Ball() { var p = Up(); return p == null ? 0 : (int)(BallsPerGame() - p.balls_remaining + 1); }
    public static int Player() { return HasPlayers() ? Mode.machine.game.current_player : 0; }
    public static int ExtraBallsLeft() { var p = Up(); return p == null ? 0 : p.extra_ball; }
    public static int ExtraBallsAwarded() { var p = Up(); return p == null ? -1 : p.extra_ball; }
    public static int BallsInPlay() { return HasPlayers() ? Mode.machine.game.balls_in_play : -1; }

    public static List<string> RunningModes() {
        var o = new List<string>();
        foreach (var m in Modes.modes.Values)
            if (m != null && m.active && m.mode != PadRuntime.ModeId) {
                o.Add(m.GetType().Name);
                if (!string.IsNullOrEmpty(m.name)) o.Add(m.name);
            }
        return o;
    }

    public static long PlayerScore() { return HasPlayers() ? Mode.machine.game.player().score : 0; }
    public static void Award(long ask) { hook.score_points(ask, Tags); }
    public static string ScoreNote() { return "score_points(base bonus), score_multiplier " + Mode.machine.game.score_multiplier; }

    public static Dictionary<string, string> Voices() {
        if (callouts != null) return callouts;
        callouts = new Dictionary<string, string>();
        foreach (var f in typeof(global::Callouts).GetFields(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
            if (f.FieldType == typeof(string)) {
                var v = f.GetValue(null) as string;
                if (!string.IsNullOrEmpty(v)) callouts[f.Name] = v;
            }
        return callouts;
    }

    // -> the clip name the voice channel will take (watched by the core), how = what was done
    public static string Voice(string name, out string how) {
        string path;
        if (!Voices().TryGetValue(name, out path)) path = name;
        AudioClip clip = global::Callouts.get(path);
        if (clip == null) { how = null; return null; }
        Mode.machine.enqueue_callout(clip);
        how = "(" + clip.name + ", " + clip.length.ToString("0.00") + " s) queued as a callout";
        return clip.name;
    }

    public static AudioSource VoiceChannel() { return Mode.machine.voice_channel; }

    public static List<string> Lamps() {
        return Lights.light_names == null ? new List<string>()
            : Lights.light_names.OrderBy(kv => kv.Key).Select(kv => kv.Value).Where(v => !string.IsNullOrEmpty(v)).ToList();
    }

    public static List<string> GameModes() {
        return Modes.modes.OrderBy(kv => kv.Key).Where(kv => kv.Value != null && kv.Key != PadRuntime.ModeId)
            .Select(kv => kv.Value.name ?? kv.Value.GetType().Name).ToList();
    }

    public static List<string> ModeClasses() {
        return Modes.modes.Values.Where(m => m != null && m.mode != PadRuntime.ModeId).Select(m => m.GetType().Name)
            .Distinct().OrderBy(x => x).ToList();
    }

    public static List<string> ScoreTags() {
        var g = Mode.machine.game;
        return g != null && g.recognized_tags != null ? g.recognized_tags : new List<string>();
    }

    public static List<string> ModeTags() {
        var g = Mode.machine.game;
        return g != null && g.mode_tags != null ? g.mode_tags : new List<string>();
    }
}
}
