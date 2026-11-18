// PadModes.cs - PAD's managed mode runtime for Spooky's Unity titles
// (PAD-1387 proof of concept, built against Scooby-Doo's Assembly-CSharp).
//
// padunity.so calls Loader.Init() on a thread attached to the game's Mono
// domain.  Init waits (off the main thread) for the game to finish adding
// its modes (Machine.modes_loaded), then subscribes to Unity's
// Application.onBeforeRender, which runs on the main thread between frames -
// outside Machine.Update's walk over Modes.modes - and there registers a Mode
// of ours with the game's own Modes.add_mode.  From then on the game's
// Machine.process_messages hands our mode every message it hands its own:
// switch_active / switch_inactive, ball_start, end_of_ball, start_mode...
// Points go through Mode.score_points -> Game.score_points, the game's own.
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;

namespace PadModes {

public static class Loader {
    static readonly string LogPath =
        Environment.GetEnvironmentVariable("PADUNITY_LOG") ?? "/game/logs/padunity.log";
    static readonly object gate = new object();
    static bool registered;
    static int frames;
    static DateTime lastList = DateTime.MinValue;
    public const int ModeId = 9001;

    public static void Log(string s) {
        lock (gate)
            File.AppendAllText(LogPath, DateTime.Now.ToString("HH:mm:ss.fff") + " [managed] " + s + "\n");
    }

    public static void Init() {
        Log("loaded: PadModes " + typeof(Loader).Assembly.GetName().Version +
            " in domain \"" + AppDomain.CurrentDomain.FriendlyName + "\", CLR " + Environment.Version);
        var asm = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetName().Name).ToArray();
        Log("assemblies loaded: " + asm.Length + " (Assembly-CSharp " +
            (asm.Contains("Assembly-CSharp") ? "present" : "MISSING") + ")");
        // NOTHING of the game's may be touched on this thread: the first
        // access to a game class runs its static constructor here, and
        // Machine's then deadlocked against the main thread (the first run:
        // both threads in futex_wait, the game stuck after "sync").  Only
        // the event subscription (pure managed) happens here.
        UnityEngine.Application.onBeforeRender += OnFrame;
        Log("hooked Application.onBeforeRender; waiting for Machine.modes_loaded on the main thread");
    }

    // Main thread, once per frame.
    static void OnFrame() {
        try {
            frames++;
            if (frames == 1)
                Log("first frame callback on the main thread");
            if (!registered) {
                if (!Machine.modes_loaded) {
                    if (frames % 600 == 0)
                        Log("frame " + frames + ": waiting, Machine.modes_loaded false, " +
                            Modes.modes.Count + " modes so far");
                    return;
                }
                registered = true;
                Log("game says modes_loaded after " + frames + " frames; " + Modes.modes.Count + " modes");
                Log("first frame callback on the main thread (managed thread " +
                    Thread.CurrentThread.ManagedThreadId + ")");
                ListModes("live mode list");
                var m = new ProbeMode(Modes.machine);
                Modes.add_mode(m);
                Log("registered ProbeMode as mode " + ModeId + " via Modes.add_mode; now " +
                    Modes.modes.Count + " modes");
            }
            if ((DateTime.Now - lastList).TotalSeconds > 20) {
                lastList = DateTime.Now;
                var act = Modes.modes.Values.Where(x => x != null && x.active)
                    .Select(x => x.mode + ":" + x.GetType().Name);
                Log("active now: " + string.Join(" ", act) + " (frames " + frames + ")");
            }
        } catch (Exception e) { Log("frame: " + e); }
    }

    public static void ListModes(string what) {
        var sb = new StringBuilder(what + " (" + Modes.modes.Count + "):");
        foreach (var kv in Modes.modes.OrderBy(k => k.Key)) {
            var m = kv.Value;
            sb.Append("\n    " + kv.Key + " " + (m == null ? "null" : m.GetType().Name + " \"" + m.name + "\"" +
                (m.active ? " ACTIVE" : "")));
        }
        Log(sb.ToString());
    }
}

// The probe mode: logs every switch and ball event it is handed, and on the
// first three playfield switches during a game scores 1,000,000 through the
// game's own scoring and puts a popup on the game's screen.
public class ProbeMode : Mode {
    int awards;

    public ProbeMode(Machine m) : base(m) {
        name = "PAD probe";
        mode = Loader.ModeId;
    }

    public override int init() { Loader.Log("ProbeMode.init called by Modes.add_mode"); return 0; }
    public override int update() { return 0; }

    public override int process_message(int[] msg) {
        try {
            int what = msg[Messages.offset_message], data = msg[Messages.offset_data];
            if (what == Messages.switch_active) {
                string sw = Switches.get_switch_name(data);
                Loader.Log("switch_active " + data + " \"" + sw + "\" (sender " +
                    msg[Messages.offset_sender] + ", target " + msg[Messages.offset_target] + ")");
                Game g = machine.game;
                Player p = g != null && g.players != null && g.players.Count > 0 ? Mode.player() : null;
                if (p != null && awards < 3 && Playfield(sw)) {
                    long before = p.score;
                    long got = score_points(1000000, new[] { "base" });
                    awards++;
                    Loader.Log("scored via Mode.score_points(1000000, base): returned " + got +
                        ", player " + (g.current_player + 1) + " score " + before + " -> " + p.score);
                    try { popup_text("PAD MODE +1,000,000", true, 2f, null, false); Loader.Log("popup_text sent"); }
                    catch (Exception e) { Loader.Log("popup_text: " + e.Message); }
                }
            } else if (what == Messages.ball_start) {
                Loader.Log("ball_start (data " + data + ")");
            } else if (what == Messages.end_of_ball) {
                Loader.Log("end_of_ball (data " + data + ")");
            } else if (what == Messages.new_game_started) {
                Loader.Log("new_game_started");
            } else if (what == Messages.mode_started || what == Messages.mode_stopped) {
                Loader.Log((what == Messages.mode_started ? "mode_started " : "mode_stopped ") +
                    data + " " + Modes.get_mode_name(data));
            }
        } catch (Exception e) { Loader.Log("process_message: " + e.Message); }
        return 0;
    }

    static bool Playfield(string sw) {
        sw = (sw ?? "").ToLowerInvariant();
        foreach (var no in new[] { "trough", "start", "launch", "coin", "flipper", "tilt", "service",
                                   "volume", "door", "shooter", "eos", "back", "menu" })
            if (sw.Contains(no)) return false;
        return sw.Length > 0;
    }
}
}
