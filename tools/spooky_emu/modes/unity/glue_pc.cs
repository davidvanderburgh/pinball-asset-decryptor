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
