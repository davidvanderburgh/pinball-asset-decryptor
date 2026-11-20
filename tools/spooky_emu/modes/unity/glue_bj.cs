// glue_bj.cs - PadModes on Beetlejuice's framework (PAD-1418): Machine.modes_loaded, Modes.add_mode,
// a Mode(float priority) with an abstract Load(), Message structs (Messages.Event, DataInt),
// Switches.switches (labels and numbers: no symbols, so the symbol is the label in lower case with
// underscores), Mode.ScorePoints(points, switch, digits to round) (multipliers only for the switches
// it is given: none for null; 0 digits: no rounding), Media's static Audio fields (VOICE ones are
// the callouts) and Media.CalloutEnqueue.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace PadModes {

public class Hook : Mode {
    // a priority no mode of the game's has: stop() clears the lights of the priority's layer
    public Hook() : base(9001.25f) { mode = PadRuntime.ModeId; }

    public override void Load() { }

    public override int process_message(Message m) {
        try {
            var r = Loader.Runtime;
            switch (m.Event) {
                case Messages.Event.switch_active: r.OnSwitch(m.DataInt); break;
                case Messages.Event.new_game_started: r.OnNewGame(); break;
                case Messages.Event.ball_start: r.OnBallStart(); break;
                case Messages.Event.end_of_ball: r.OnBallEnd("the ball ended"); break;
                case Messages.Event.tilt: r.OnBallEnd("tilt"); break;
                case Messages.Event.ball_saved: r.GameEvent("ball_saved"); break;
                case Messages.Event.end_of_game: r.OnGameEnd(); break;
                case Messages.Event.mode_started: if (m.DataInt == Modes.attract_mode) r.OnGameEnd(); break;
            }
        } catch (Exception e) { Loader.Log("process_message: " + e); }
        return 0;
    }
}

public static class Glue {
    public const string Framework = "beetlejuice";
    static Hook hook;
    static List<Sw> sw;
    static Dictionary<string, Media.Audio> voices;

    public static bool Ready() { return Machine.modes_loaded; }

    public static bool Ensure(PadRuntime r) {
        if (hook != null && Modes.modes.ContainsKey(PadRuntime.ModeId)) return false;
        if (hook == null) hook = new Hook();
        Modes.add_mode(hook);
        return true;
    }

    public static int ModeCount() { return Modes.modes.Count; }
    public static void Poll(PadRuntime r) { }

    public static string Sym(string label) {
        return string.Join("_", (label ?? "").ToLowerInvariant().Split(new[] { ' ', '-', '/', '.' },
            StringSplitOptions.RemoveEmptyEntries));
    }

    public static List<Sw> Switches() {
        if (sw != null || global::Switches.switches == null) return sw ?? new List<Sw>();
        sw = new List<Sw>();
        foreach (var s in global::Switches.switches)
            if (s != null && !string.IsNullOrEmpty(s.name) && !s.name.StartsWith("UNUSED"))
                sw.Add(new Sw(Sym(s.name), (int)s.number, s.name));
        return sw;
    }

    public static string SwitchName(int n) {
        foreach (var s in Switches()) if (s.Num == n) return s.Sym;
        return "#" + n;
    }

    public static bool HasPlayers() { return Machine.game != null && Machine.game.players != null && Machine.game.players.Count > 0; }
    // ---- balls and game modes (PAD-1424 start rules)
    static global::Player Up() { return HasPlayers() ? Machine.game.currentPlayer : null; }
    public static int BallsPerGame() { return Settings.balls_per_game; }
    public static int Ball() { var p = Up(); return p == null ? 0 : p.CurrentBall; }
    public static int Player() { return HasPlayers() ? Machine.game.current_player_index : 0; }
    public static int ExtraBallsLeft() { var p = Up(); return p == null ? 0 : p.extra_balls; }
    public static int ExtraBallsAwarded() { var p = Up(); return p == null ? -1 : p.extra_balls; }
    public static int BallsInPlay() { return HasPlayers() ? Game.balls_in_play : -1; }

    // a running mode by its name in the port report (its title, else its class) and by its class
    public static List<string> RunningModes() {
        var o = new List<string>();
        foreach (var m in Modes.modes.Values)
            if (m != null && m.active && m.mode != PadRuntime.ModeId) {
                o.Add(m.GetType().Name);
                if (!string.IsNullOrEmpty(m.title)) o.Add(m.title);
            }
        return o;
    }

    public static long PlayerScore() { return HasPlayers() ? Machine.game.currentPlayer.score : 0; }
    public static void Award(long ask) { hook.ScorePoints(ask, null, 0); }
    public static string ScoreNote() { return "Mode.ScorePoints(points, no switch, 0 digits)"; }

    static Dictionary<string, Media.Audio> VoiceTable() {
        if (voices != null) return voices;
        voices = new Dictionary<string, Media.Audio>();
        foreach (var f in typeof(Media).GetFields(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
            if (f.FieldType == typeof(Media.Audio)) {
                var a = f.GetValue(null) as Media.Audio;
                if (a != null && a.type == Media.AUDIO_TYPE.VOICE && !string.IsNullOrEmpty(a.path)) voices[f.Name] = a;
            }
        return voices;
    }

    public static Dictionary<string, string> Voices() { return VoiceTable().ToDictionary(kv => kv.Key, kv => kv.Value.path); }

    public static string Voice(string name, out string how) {
        Media.Audio a;
        AudioClip clip = VoiceTable().TryGetValue(name, out a) ? a.clip : null;
        if (clip == null) { how = null; return null; }
        float t = Media.CalloutEnqueue(clip);
        how = "(" + clip.name + ", " + clip.length.ToString("0.00") + " s) queued as a callout (CalloutEnqueue " + t.ToString("0.00") + ")";
        return clip.name;
    }

    public static AudioSource VoiceChannel() { return Media.voice_channel; }

    public static List<string> Lamps() {
        return Lights.serialLEDs == null ? new List<string>()
            : Lights.serialLEDs.Where(l => l != null && !string.IsNullOrEmpty(l.name)).Select(l => l.name).Distinct().ToList();
    }

    public static List<string> GameModes() {
        return Modes.modes.OrderBy(kv => kv.Key).Where(kv => kv.Value != null && kv.Key != PadRuntime.ModeId)
            .Select(kv => string.IsNullOrEmpty(kv.Value.title) ? kv.Value.GetType().Name : kv.Value.title).ToList();
    }

    public static List<string> ModeClasses() {
        return Modes.modes.Values.Where(m => m != null && m.mode != PadRuntime.ModeId).Select(m => m.GetType().Name)
            .Distinct().OrderBy(x => x).ToList();
    }

    public static List<string> ScoreTags() { return new List<string>(); }
    public static List<string> ModeTags() { return new List<string>(); }
}
}
