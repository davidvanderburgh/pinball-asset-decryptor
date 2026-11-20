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

    // ---- lamps, coils, balls (PAD-1424)
    // Lamps on the LED controller's overlay layer (the game's lightshows use it too, and clear it
    // when one stops: the core sets ours again four times a second); black on the overlay hands
    // the lamp back to the game's base layer.
    static Dictionary<string, int> lampNums, coilNums;

    static int LampNum(string l) {
        if (lampNums == null) {
            lampNums = new Dictionary<string, int>();
            if (Lights.light_names != null)
                foreach (var kv in Lights.light_names) lampNums[PadRuntime.Tok(kv.Value)] = kv.Key;
        }
        int n;
        return lampNums.TryGetValue(PadRuntime.Tok(l), out n) ? n : -1;
    }

    public static bool LampSet(string l, Color32 c) {
        int n = LampNum(l);
        if (n < 0) return false;
        Warden.set_led_full_color((byte)n, c.r, c.g, c.b, true);
        return true;
    }

    public static void LampRelease(string l) {
        int n = LampNum(l);
        if (n >= 0) Warden.set_led((byte)n, Lights.black, true);
    }

    static int CoilNum(string c) {
        if (coilNums == null) {
            coilNums = new Dictionary<string, int>();
            foreach (var f in typeof(global::Coils).GetFields(BindingFlags.Static | BindingFlags.Public))
                if (f.IsLiteral && (f.FieldType == typeof(byte) || f.FieldType == typeof(int)) && f.Name != "num_coils")
                    coilNums[PadRuntime.Tok(f.Name)] = Convert.ToInt32(f.GetRawConstantValue());
        }
        int n;
        return coilNums.TryGetValue(PadRuntime.Tok(c), out n) ? n : -1;
    }

    public static string CoilPulse(string c, int ms) {
        int n = CoilNum(c);
        if (n < 0) return null;
        long own = 0;
        try { own = Mode.machine.settings.coil_settings[n].pulse_time_slider.current_value; } catch (Exception) { }
        if (ms > 0 && (own <= 0 || ms < own)) { Warden.pulse_for_ms((byte)n, (byte)ms); return "Warden.pulse_for_ms " + ms + " ms, its own " + own; }
        Warden.pulse((byte)n);
        return "Warden.pulse, its own " + own + " ms";
    }

    public static string CoilHold(string c, int power) {
        int n = CoilNum(c);
        if (n < 0) return null;
        Warden.set_pwm((byte)n, (byte)Math.Min(255, power * 255 / 32));
        return "Warden.set_pwm " + Math.Min(255, power * 255 / 32);
    }

    public static void CoilRelease(string c) {
        int n = CoilNum(c);
        if (n < 0) return;
        for (int i = 0; i < 3; i++) Warden.set_pwm((byte)n, 0);      // the game sends its off three times
    }

    // the game's own add-a-ball message: Trough_mode ejects n (RequestEject), counted in balls_in_play
    public static string AddBalls(int n) {
        Mode.machine.append_message(PadRuntime.ModeId, 0, Messages.add_a_ball, n);
        return "add_a_ball message, " + n + " ball(s)";
    }

    static Base_mode Base() { return Modes.modes.Values.OfType<Base_mode>().FirstOrDefault(); }

    // the base mode's ball save timer (the game adds 4 s of grace to every save it starts)
    public static string BallSave(int secs, int balls) {
        var b = Base();
        if (b == null || b.ballsave_timer == null) return "no base mode";
        if (b.ballsave_timer.isEnded() || b.ballsave_timer.seconds_remaining() < secs + 4)
            b.ballsave_timer.refresh(secs + 4.0);
        return "Base_mode.ballsave_timer " + b.ballsave_timer.seconds_remaining().ToString("0.0") + " s";
    }

    public static void BallSaveOff(int secs) {
        var b = Base();
        if (b != null && b.ballsave_timer != null && !b.ballsave_timer.isEnded() && b.ballsave_timer.seconds_remaining() <= secs + 4)
            b.ballsave_timer.refresh(0.0);
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
    public static List<AudioSource> MusicSources() {
        return new List<AudioSource> { Mode.machine.music_channel, Mode.machine.precision_timing_channel };
    }

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
