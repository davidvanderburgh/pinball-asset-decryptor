// glue_ed.cs - PadModes on Evil Dead's framework (PAD-1418): the game class is `ed`
// (switches.game), its modes a List<Mode> (add_mode appends); every mode's handlers are found by
// name when it is made (CacheEventMethodsThisMode): sw_any(number, symbol, active) for every
// switch, evt_<name>(...) for callAll's broadcasts.  Return values are ignored and nothing stops
// a switch, so ours sees every hit.  The game does not broadcast a game's start or a ball's
// (machineMode calls its own modes directly): those are polled (PadRuntime.Track).
// addScore(amount, applyMux: false) adds the amount as it is.  audio.playVoice(key) plays a voice
// wav by its name (audioVoiceFiles.clips: key -> AudioClip, from the assets' voice folders).
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace PadModes {

public class Hook : Mode {
    public Hook(ed g) : base(9001, "PAD custom modes", "system") { game = g; }

    public void sw_any(int sw, string name, bool state) {
        try { if (state) Loader.Runtime.OnSwitch(sw); } catch (Exception e) { Loader.Log("sw_any: " + e); }
    }

    public void evt_ball_ending_mode() {
        try { Loader.Runtime.OnBallEnd("the ball ended"); } catch (Exception e) { Loader.Log("evt_ball_ending_mode: " + e); }
    }
}

public static class Glue {
    public const string Framework = "evil_dead";
    static Hook hook;
    static List<Sw> sw;
    static Dictionary<string, string> paths;

    static ed G { get { return switches.game; } }

    public static bool Ready() { return G != null && G.modes != null && G.modes.Count > 0 && loaderCheck.loadProgress >= 10; }

    public static bool Ensure(PadRuntime r) {
        var g = G;
        if (hook == null) hook = new Hook(g);
        if (g.modes.Contains(hook)) return false;
        g.add_mode(hook);
        return true;
    }

    public static int ModeCount() { return G.modes.Count; }

    static int savesSeen;

    public static void Poll(PadRuntime r) {
        var g = G;
        r.Track(g.gameActive, g.current_player_number, g.ball, g.tiltmode != null && g.tiltmode.tilted);
        // no ball-saved event: troughMode.checkForSaves counts each save it serves
        int saves = g.trough != null ? g.trough.savingBallCount : 0;
        if (saves > savesSeen && g.gameActive) r.GameEvent("ball_saved");
        savesSeen = saves;
        if (pendingBalls > 0 && (!g.gameActive || g.ball == 0)) pendingBalls = 0;
        if (pendingBalls > 0 && g.trough != null && g.trough.launch_lifecycle == 0) {
            int n = pendingBalls;
            pendingBalls = 0;
            Loader.Log("the trough's load finished: " + Launch(n));
        }
    }

    // ---- lamps, coils, balls (PAD-1424)
    // warden's named LEDs: last write wins (no layer), so the core sets ours four times a second;
    // led_disable_name gives a lamp back to the lampshow under it.
    static Dictionary<string, string> lampNames;

    static string LampName(string l) {
        if (lampNames == null) {
            lampNames = new Dictionary<string, string>();
            foreach (var n in Lamps()) lampNames[PadRuntime.Tok(n)] = n;
        }
        string n2;
        return lampNames.TryGetValue(PadRuntime.Tok(l), out n2) ? n2 : null;
    }

    public static bool LampSet(string l, Color32 c) {
        string n = LampName(l);
        if (n == null) return false;
        warden.led_color(n, c.r, c.g, c.b);
        return true;
    }

    public static void LampRelease(string l) { string n = LampName(l); if (n != null) warden.led_disable_name(n); }

    static coil CoilOf(string c) {
        string t = PadRuntime.Tok(c);
        foreach (var kv in coilControl.coils) if (PadRuntime.Tok(kv.Key) == t) return kv.Value;
        return null;
    }

    public static string CoilPulse(string c, int ms) {
        var k = CoilOf(c);
        if (k == null) return null;
        // its own pulse is the service menu's (pulse(-1)); an asked time is held to the menu's 50 ms top
        k.pulse(ms > 0 ? Math.Min(ms, 50) : -1);
        return ms > 0 ? "pulse " + Math.Min(ms, 50) + " ms" : "pulse, its own";
    }

    public static string CoilHold(string c, int power) {
        var k = CoilOf(c);
        if (k == null) return null;
        k.manualPWM((byte)(power * 100 / 32));
        return "manualPWM " + (power * 100 / 32) + "%";
    }

    public static void CoilRelease(string c) { var k = CoilOf(c); if (k != null) k.disable(); }

    // the trough's own multiball calls: more balls for one that runs, else one of ours.  Asked while
    // the trough is still loading a ball (launch_lifecycle not 0), the extra one never came out in the
    // rig: the request waits for the load to finish (Poll)
    static int pendingBalls;

    public static string AddBalls(int n) {
        if (G.trough.launch_lifecycle != 0) { pendingBalls += n; return "waiting for the trough's load to finish (" + pendingBalls + " ball(s))"; }
        return Launch(n);
    }

    static string Launch(int n) {
        var t = G.trough;
        if (t.multiballActive) return "trough.incMultiballFromTrough: " + t.incMultiballFromTrough(hook, n) + " added";
        t.createMultiballMode(hook, n, 100, remain => remain <= 1);
        return "trough.createMultiballMode(" + n + ")";
    }

    public static string BallSave(int secs, int balls) {
        if (balls > 1) { G.ballsavemode.startMBsave(secs); return "startMBsave " + secs + " s"; }
        return "start_standard_save " + secs + " s: " + G.ballsavemode.start_standard_save(secs);
    }

    public static void BallSaveOff(int secs) { if (G.ballsavemode.standardSaveActive) G.ballsavemode.disable_saves(); }

    // ---- balls and game modes (PAD-1424 start rules)
    static global::Player Up() {
        if (!HasPlayers()) return null;
        int i = G.getCurrentPlayerIndex();
        return i >= 0 && i < G.players.Count ? G.players[i] : null;
    }
    public static int BallsPerGame() { return G.balls_per_game; }
    public static int Ball() { return HasPlayers() ? G.ball : 0; }
    public static int Player() { return HasPlayers() ? G.getCurrentPlayerIndex() : 0; }
    public static int ExtraBallsLeft() { var p = Up(); return p == null ? 0 : p.extra_balls; }
    public static int ExtraBallsAwarded() { var p = Up(); return p == null ? -1 : p.extra_balls; }
    public static int BallsInPlay() { return HasPlayers() && G.trough != null ? G.trough.activeBalls : -1; }

    // a game mode runs while it is in the list and started (ended ones wait there to be removed)
    public static List<string> RunningModes() {
        var o = new List<string>();
        foreach (var m in G.modes)
            if (m != null && m != hook && m.modeStarted) {
                o.Add(m.GetType().Name);
                if (!string.IsNullOrEmpty(m.Name)) o.Add(m.Name);
            }
        return o;
    }

    public static List<Sw> Switches() {
        if (sw != null && sw.Count > 0) return sw;
        sw = new List<Sw>();
        if (switches.switchKeyNum == null) return sw;
        foreach (var kv in switches.switchKeyNum.OrderBy(kv => kv.Value)) {
            if (Placeholder(kv.Key)) continue;
            string label = switches.switch_labels != null && switches.switch_labels.ContainsKey(kv.Key)
                ? Convert.ToString(switches.switch_labels[kv.Key]) : kv.Key;
            sw.Add(new Sw(kv.Key, kv.Value, label));
        }
        return sw;
    }

    // "unused...", or a slot the game left its default name ("switch_0", "Switch_8", "_no_switch_31")
    static bool Placeholder(string sym) {
        if (string.IsNullOrEmpty(sym) || sym.StartsWith("unused", StringComparison.OrdinalIgnoreCase) ||
            sym.StartsWith("_no_switch")) return true;
        if (!sym.StartsWith("switch_", StringComparison.OrdinalIgnoreCase)) return false;
        int n;
        return int.TryParse(sym.Substring(7), out n);
    }

    public static string SwitchName(int n) {
        foreach (var s in Switches()) if (s.Num == n) return s.Sym;
        return "#" + n;
    }

    public static bool HasPlayers() { var g = G; return g != null && g.players != null && g.players.Count > 0; }
    public static long PlayerScore() { return HasPlayers() ? G.getPlayerScore(G.getCurrentPlayer()) : 0; }
    public static void Award(long ask) { G.addScore((int)Math.Min(ask, int.MaxValue), false); }
    public static string ScoreNote() { return "addScore(amount, applyMux: false)"; }

    public static Dictionary<string, string> Voices() {
        var d = new Dictionary<string, string>();
        var c = audioVoiceFiles.clips;
        if (c == null) return d;
        if (paths == null) paths = WavPaths();
        foreach (var k in c.Keys) {
            string key = Convert.ToString(k), p;
            if (string.IsNullOrEmpty(key)) continue;
            d[key] = paths.TryGetValue(key, out p) ? p : key;
        }
        return d;
    }

    static Dictionary<string, string> WavPaths() {
        var d = new Dictionary<string, string>();
        try {
            string root = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "assets"));
            if (!Directory.Exists(root)) return d;
            foreach (var f in Directory.GetFiles(root, "*.wav", SearchOption.AllDirectories)) {
                string key = Path.GetFileNameWithoutExtension(f);
                if (!d.ContainsKey(key)) d[key] = "assets/" + f.Substring(root.Length + 1).Replace('\\', '/');
            }
        } catch (Exception e) { Loader.Log("wav paths: " + e.Message); }
        return d;
    }

    public static string Voice(string name, out string how) {
        var c = audioVoiceFiles.clips;
        var clip = c != null && c.ContainsKey(name) ? c[name] as AudioClip : null;
        if (clip == null) { how = null; return null; }
        float t = audio.playVoice(name);
        how = "(" + clip.name + ", " + clip.length.ToString("0.00") + " s) played with audio.playVoice (" + t.ToString("0.00") + ")";
        return clip.name;
    }

    public static AudioSource VoiceChannel() { return audio.getVoiceChannel(); }
    public static List<AudioSource> MusicSources() {
        var sm = soundMaster.Instance;
        return sm != null && sm.music_channel != null ? new List<AudioSource>(sm.music_channel) : new List<AudioSource>();
    }

    public static List<string> Lamps() {
        var l = new List<string>();
        var f = typeof(LightConfig).GetField("lightList", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
        var d = f == null ? null : f.GetValue(null) as IDictionary;
        if (d != null) foreach (var k in d.Keys) l.Add(Convert.ToString(k));
        l.Sort(StringComparer.Ordinal);
        return l;
    }

    public static List<string> GameModes() {
        return G.modes.Where(m => m != null && m != hook).Select(m => m.Name ?? m.GetType().Name).ToList();
    }

    public static List<string> ModeClasses() {
        return G.modes.Where(m => m != null && m != hook).Select(m => m.GetType().Name).Distinct().OrderBy(x => x).ToList();
    }

    public static List<string> ScoreTags() { return new List<string>(); }
    public static List<string> ModeTags() { return new List<string>(); }
}
}
