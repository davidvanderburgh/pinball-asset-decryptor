// glue_pc.cs - PadModes on the pinballController framework (PAD-1418): Texas Chainsaw Massacre
// (built with -d:TCM, Unity 2019), Halloween and Ultraman (Pinotaur).
//
// The game finds a mode's handlers by name, by reflection: sw_<symbol>_active(), sw_any(),
// evt_<event>().  A handler returning false stops the switch or event for the modes after it,
// so ours always return true.
//
//   Halloween, Ultraman  AddMode(m, 0) puts ours first in _modes; processMessage calls every mode's
//                        sw_any(number, symbol, state) before its sw_<symbol>_active, so ours sees
//                        every hit first.  Score(amount, force: true) adds the amount as it is (no
//                        multiplier, no rounding).  Mode.bail_on_tilt is true by default: ours is not.
//   Texas Chainsaw       add_mode(m) appends; switches go through a private cache
//                        (_cachedMethods["sw_<symbol>_active"], walked last to first) and sw_any only
//                        runs if no mode stopped the switch, so ours puts one generated handler per
//                        switch at the end of each cache list: it runs first.  The service menu drops
//                        added modes (destroyOnMenuEntry): Ensure() adds ours again.  addScore(amount,
//                        0, notValidForComboBet: true): amount x the playfield multiplier (1 or 2).
//
// The game's start and its balls are polled (PadRuntime.Track): Texas Chainsaw calls
// evt_game_started with no argument and Halloween with one, so no one signature takes both.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using UnityEngine;

namespace PadModes {

public class Hook : Mode {
    public Hook(pinballController g) : base(g, 9001, "PAD custom modes", "system") {
        // Halloween's Mode stops a tilted game's switches and events for bail_on_tilt modes, and
        // makes every mode one; Ultraman's has no such property (and no tilt gating)
        var bail = typeof(Mode).GetProperty("bail_on_tilt");
        if (bail != null && bail.CanWrite) bail.SetValue(this, false, null);
    }

#if !TCM
    public override bool sw_any(int sw, string name, int state) {
        try { if (state == 1) Loader.Runtime.OnSwitch(sw); } catch (Exception e) { Loader.Log("sw_any: " + e); }
        return true;
    }
#endif

    // Texas Chainsaw's generated handlers call this (one per switch, the number baked in)
    public static bool Hit(int sw) {
        try { Loader.Runtime.OnSwitch(sw); } catch (Exception e) { Loader.Log("switch: " + e); }
        return true;
    }

    public bool evt_ball_ending(string msg) {
        try { Loader.Runtime.OnBallEnd("the ball ended"); } catch (Exception e) { Loader.Log("evt_ball_ending: " + e); }
        return true;
    }

    // the game's ball save served a ball back (PAD-1424 start_on ball_saved)
#if TCM
    public bool evt_ballSaved_regular(string msg) {
#else
    public bool evt_ball_saving(string msg) {
#endif
        try { Loader.Runtime.GameEvent("ball_saved"); } catch (Exception e) { Loader.Log("ball saved: " + e); }
        return true;
    }
}

public static class Glue {
#if TCM
    public const string Framework = "pinballController-tcm";
#else
    public const string Framework = "pinballController";
#endif
    static Hook hook;
    static List<Sw> sw;
    static Dictionary<string, string> paths;

    static pinballController G {
#if TCM
        get { return pinAPI.game; }
#else
        get { return Pinotar._game; }
#endif
    }

    public static bool Ready() {
        var g = G;
        if (g == null || g._modes == null || g._modes.Count == 0 || g.soundmanager == null) return false;
#if TCM
        return g.soundmanager.finishedLoading == -2;
#else
        return g.soundmanager.finishedLoading <= -2;
#endif
    }

    public static bool Ensure(PadRuntime r) {
        var g = G;
        if (hook == null) hook = new Hook(g);
        bool added = false;
        if (!g._modes.Contains(hook)) {
#if TCM
            g.add_mode(hook);
#else
            g.AddMode(hook, 0);
#endif
            added = true;
        }
#if TCM
        if (HookSwitches(g)) Loader.Log("switch handlers: one per switch at the end of the game's switch cache (" + Switches().Count + ")");
#endif
        return added;
    }

#if TCM
    // One generated sw_<symbol>_active per switch, the last in its cache list (so the first called),
    // returning true.  Again whenever the game rebuilt its cache or the menu dropped ours.
    static bool HookSwitches(pinballController g) {
        var f = typeof(pinballController).GetField("_cachedMethods", BindingFlags.Instance | BindingFlags.NonPublic);
        var cache = f == null ? null : f.GetValue(g) as Dictionary<string, List<ValueTuple<MethodInfo, Mode>>>;
        if (cache == null) return false;
        var hit = typeof(Hook).GetMethod("Hit", BindingFlags.Static | BindingFlags.Public);
        bool any = false;
        foreach (var s in Switches()) {
            string key = "sw_" + s.Sym + "_active";
            List<ValueTuple<MethodInfo, Mode>> l;
            if (!cache.TryGetValue(key, out l)) cache[key] = l = new List<ValueTuple<MethodInfo, Mode>>();
            if (l.Count > 0 && l[l.Count - 1].Item2 == hook) continue;
            for (int i = l.Count - 1; i >= 0; i--) if (l[i].Item2 == hook) l.RemoveAt(i);
            var dm = new DynamicMethod("pad_" + key, typeof(bool), Type.EmptyTypes, typeof(Hook).Module, true);
            var il = dm.GetILGenerator();
            il.Emit(OpCodes.Ldc_I4, s.Num);
            il.Emit(OpCodes.Call, hit);
            il.Emit(OpCodes.Ret);
            l.Add(new ValueTuple<MethodInfo, Mode>(dm, hook));
            any = true;
        }
        return any;
    }
#endif

    public static int ModeCount() { return G._modes.Count; }

    public static void Poll(PadRuntime r) {
        var g = G;
#if TCM
        r.Track(g.gameStarted, g.current_player_number, g.ball, g.tiltmode != null && g.tiltmode.tilted);
#else
        r.Track(g.gameStarted && !(g.machinemode != null && g.machinemode.gameended), g.getCurrentPlayer(), g.ball,
            g.tiltmode != null && g.tiltmode.tilted);
#endif
    }

    public static List<Sw> Switches() {
        if (sw != null && sw.Count > 0) return sw;
        sw = new List<Sw>();
        if (SwitchConfig.switchKeyNum == null) return sw;
        foreach (var kv in SwitchConfig.switchKeyNum.OrderBy(kv => kv.Value)) {
            if (Placeholder(kv.Key)) continue;
            string label = SwitchConfig.switch_labels != null && SwitchConfig.switch_labels.ContainsKey(kv.Key)
                ? Convert.ToString(SwitchConfig.switch_labels[kv.Key]) : kv.Key;
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

    // ---- lamps, coils, balls (PAD-1424)
    // Lamps by the game's LightConfig name.  Texas Chainsaw's Warden RGB system has an overlay layer
    // (led_disable(..., isOverlay) hands the lamp back); Halloween and Ultraman's Pinotar has one
    // layer, last write wins: the core sets ours four times a second, and update_lamps() repaints
    // the game's when a lamp is handed back.
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
#if TCM
        pinAPI.led_color(n, c.r, c.g, c.b, 1, true);
#else
        Pinotar.led_color(n, c.r, c.g, c.b, 1);
#endif
        return true;
    }

    public static void LampRelease(string l) {
        string n = LampName(l);
        if (n == null) return;
#if TCM
        pinAPI.led_disable(n, 1, true);
#else
        Pinotar.led_disable(n);
#endif
        try { G.update_lamps(); } catch (Exception) { }
    }

#if TCM
    static coil CoilOf(string c) {
        string t = PadRuntime.Tok(c);
        if (coilControl.coils != null)
            foreach (var kv in coilControl.coils) if (PadRuntime.Tok(kv.Key) == t) return kv.Value;
        return null;
    }

    public static string CoilPulse(string c, int ms) {
        var k = CoilOf(c);
        if (k == null) return null;
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

    public static string AddBalls(int n) { G.trough.addMultiballs(n); return "trough.addMultiballs(" + n + ")"; }

    public static string BallSave(int secs, int balls) {
        if (balls > 1) { G.ballsavemode.startMBsave(secs); return "startMBsave " + secs + " s"; }
        return "start_standard_save " + secs + " s: " + G.ballsavemode.start_standard_save(secs);
    }

    public static void BallSaveOff(int secs) { }
#else
    static Coil CoilOf(string c) {
        string t = PadRuntime.Tok(c);
        foreach (var kv in G.Coils) if (PadRuntime.Tok(kv.Key) == t) return kv.Value;
        return null;
    }

    public static string CoilPulse(string c, int ms) {
        var k = CoilOf(c);
        if (k == null) return null;
        k.pulse(ms > 0 ? Math.Min(ms, 50) : -1);
        return ms > 0 ? "pulse " + Math.Min(ms, 50) + " ms" : "pulse, its own";
    }

    // Pinotar's patter (on ms, off ms): the coil held at power of 32 until disable_coil
    public static string CoilHold(string c, int power) {
        var k = CoilOf(c);
        if (k == null) return null;
        Pinotar.patter(k.num, (byte)power, (byte)(32 - power));
        return "Pinotar.patter " + power + "/" + (32 - power) + " ms";
    }

    public static void CoilRelease(string c) { var k = CoilOf(c); if (k != null) Pinotar.disable_coil(k.num); }

    // as the game's own multiballs: a multiball save that keeps all but n balls in the trough, then
    // TriggerBallLaunch() (check_for_launch ejects the difference and the shooter lane autolaunches)
    public static string AddBalls(int n) {
        var bs = G.ballsavemode;
        int keep = G.trough.num_balls() - n;
        bs.enable_mb_save(n, 10.0);
        bs.TriggerBallLaunch();
        return "ballsavemode.enable_mb_save(" + n + ") + TriggerBallLaunch (" + keep + " kept in the trough)";
    }

    public static string BallSave(int secs, int balls) {
        // enable_mb_save takes the balls beyond the one in play (it keeps the rest in the trough)
        if (balls > 1) { G.ballsavemode.enable_mb_save(balls - 1, secs); return "enable_mb_save " + balls + " balls " + secs + " s"; }
        G.ballsavemode.enable_save(secs, 1);
        return "enable_save " + secs + " s";
    }

    public static void BallSaveOff(int secs) { if (G.ballsavemode.save_enabled) G.ballsavemode.disable_save(); }
#endif

    // ---- balls and game modes (PAD-1424 start rules)
    public static int BallsPerGame() { return G.balls_per_game; }
    public static int Ball() { return HasPlayers() ? G.ball : 0; }
#if TCM
    public static int Player() { return HasPlayers() ? G.getCurrentPlayerIndex() : 0; }
    static global::Player Up() {
        if (!HasPlayers()) return null;
        int i = G.getCurrentPlayerIndex();
        return i >= 0 && i < G.players.Count ? G.players[i] : null;
    }
    public static int ExtraBallsLeft() { var p = Up(); return p == null ? 0 : p.extra_balls; }
    public static int ExtraBallsAwarded() { var p = Up(); return p == null ? -1 : p.extra_balls; }
    public static int BallsInPlay() { return HasPlayers() ? G.getBallsInPlay() : -1; }

    // Texas Chainsaw adds a game mode to _modes while it runs and takes it out when it is done
    public static List<string> RunningModes() {
        var o = new List<string>();
        foreach (var m in G._modes)
            if (m != null && m != hook) {        // the always-on ones never leave: never "ended"
                o.Add(m.GetType().Name);
                if (!string.IsNullOrEmpty(m.Name)) o.Add(m.Name);
            }
        return o;
    }
#else
    public static int Player() { return HasPlayers() ? Math.Max(0, G.getCurrentPlayer() - 1) : 0; }
    // one count for the game (extraballMode.extraballs): what the player up has to play
    public static int ExtraBallsLeft() { var e = G.extraballmode; return e == null ? 0 : e.extraballs; }
    public static int ExtraBallsAwarded() { var e = G.extraballmode; return HasPlayers() && e != null ? e.extraballs : -1; }
    public static int BallsInPlay() { return HasPlayers() && G.trough != null ? G.trough.BallsInPlay() : -1; }

    // Halloween and Ultraman keep every mode in _modes; a game mode says it runs with a flag of
    // its own (modeStarted, mb_started, incidental_running ...), read by reflection
    static readonly string[] RunFlags = { "modeStarted", "modestarted", "mb_started", "hedge_mb_started", "incidental_running",
        "IsCaptureMultiballRunning" };
    static readonly Dictionary<Type, MemberInfo[]> flags = new Dictionary<Type, MemberInfo[]>();

    static bool Runs(Mode m) {
        MemberInfo[] fs;
        var t = m.GetType();
        if (!flags.TryGetValue(t, out fs)) {
            var l = new List<MemberInfo>();
            foreach (var n in RunFlags) {
                var f = t.GetField(n, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (f != null && f.FieldType == typeof(bool)) { l.Add(f); continue; }
                var pr = t.GetProperty(n, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (pr != null && pr.PropertyType == typeof(bool) && pr.CanRead) l.Add(pr);
            }
            flags[t] = fs = l.ToArray();
        }
        foreach (var f in fs) {
            object v = f is FieldInfo ? ((FieldInfo)f).GetValue(m) : ((PropertyInfo)f).GetValue(m, null);
            if (v is bool && (bool)v) return true;
        }
        return false;
    }

    public static List<string> RunningModes() {
        var o = new List<string>();
        foreach (var m in G._modes)
            if (m != null && m != hook && Runs(m)) {
                o.Add(m.GetType().Name);
                if (!string.IsNullOrEmpty(m.Name)) o.Add(m.Name);
            }
        return o;
    }
#endif

    public static long PlayerScore() {
        if (!HasPlayers()) return 0;
#if TCM
        return G.getPlayerScore(G.getCurrentPlayer());
#else
        return G.Score();
#endif
    }

    public static void Award(long ask) {
#if TCM
        G.addScore((int)Math.Min(ask, int.MaxValue), 0.0, true);
#else
        G.Score(ask, true);
#endif
    }

    public static string ScoreNote() {
#if TCM
        return "addScore(amount, 0, notValidForComboBet), playfield multiplier " + G.playfieldMultiplier;
#else
        return "Score(amount, force)";
#endif
    }

    // the callouts: audioVoiceFiles.clips (key -> AudioClip, loaded from the assets' voice wavs)
    static Hashtable Clips() { return audioVoiceFiles.clips; }

    public static Dictionary<string, string> Voices() {
        var d = new Dictionary<string, string>();
        var c = Clips();
        if (c == null) return d;
        if (paths == null) paths = WavPaths();
        foreach (var k in c.Keys) {
            string key = Convert.ToString(k), p;
            if (string.IsNullOrEmpty(key)) continue;
            d[key] = paths.TryGetValue(key, out p) ? p : key;
        }
        return d;
    }

    // key -> the wav's path under the game's assets folder (/game/code/assets), for the port report
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
        var c = Clips();
        var clip = c != null && c.ContainsKey(name) ? c[name] as AudioClip : null;
        if (clip == null) { how = null; return null; }
        float t = audioHelper.playVoice(name);
        how = "(" + clip.name + ", " + clip.length.ToString("0.00") + " s) played with audioHelper.playVoice (" + t.ToString("0.00") + ")";
        return clip.name;
    }

    public static AudioSource VoiceChannel() { var g = G; return g != null && g.soundmanager != null ? g.soundmanager.voice_channel : null; }
    public static List<AudioSource> MusicSources() {
        var sm = audioHelper.manager;
        if (sm == null) return new List<AudioSource>();
#if TCM
        return sm.music_channel != null ? new List<AudioSource>(sm.music_channel) : new List<AudioSource>();
#else
        return new List<AudioSource> { sm.MusicSource };
#endif
    }

    public static List<string> Lamps() {
        var l = new List<string>();
        if (LightConfig.lights != null)
            foreach (var k in LightConfig.lights.Keys) l.Add(Convert.ToString(k));
        l.Sort(StringComparer.Ordinal);
        return l;
    }

    public static List<string> GameModes() {
        return G._modes.Where(m => m != null && m != hook).Select(m => m.Name ?? m.GetType().Name).ToList();
    }

    public static List<string> ModeClasses() {
        return G._modes.Where(m => m != null && m != hook).Select(m => m.GetType().Name).Distinct().OrderBy(x => x).ToList();
    }

    public static List<string> ScoreTags() { return new List<string>(); }
    public static List<string> ModeTags() { return new List<string>(); }
}
}
