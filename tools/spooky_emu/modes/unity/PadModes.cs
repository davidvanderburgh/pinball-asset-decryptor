// PadModes.cs - PAD's custom mode runtime for Spooky's Unity titles (PAD-1417, PAD-1418; the
// PAD-1387 probe made into the runtime).  The core is the same on every title; how it joins the
// game is one glue file per framework (build.sh <Managed> <out> <framework>):
//
//   glue_scooby.cs   Scooby-Doo               Machine / Modes / int[] messages / Callouts
//   glue_bj.cs       Beetlejuice              Machine / Modes / Message struct / Media
//   glue_pc.cs       Texas Chainsaw (-d:TCM), pinballController: sw_* / evt_* by reflection,
//                    Halloween, Ultraman      audioHelper.playVoice
//   glue_ed.cs       Evil Dead                ed: sw_any, callAll evt_*, audio.playVoice
//
// Every glue file gives the core the same static class Glue: Ready() (the game's modes are
// loaded), Ensure() (our mode is in the game's mode list, added again if the game dropped it),
// Poll() (state the game does not announce), the game's switches, its score and scoring call,
// its callouts, its lights and its modes.  The glue's Mode subclass hands the core the game's
// switch hits and ball messages.
//
// padunity.so calls Loader.Init() on a thread attached to the game's Mono domain: the update's
// launch line preloads it (Scooby-Doo), or the update's own Mono config maps a library the game
// loads to it (dllmap: the other titles).  Init only subscribes to Application.onBeforeRender;
// everything else happens on the main thread.  The modes are the folder beside this assembly
// (pad/modes: title.cfg + *.mode, the JJP keys tools/jjp_emu/MODES.md describes; the ones this
// runtime takes are mkspkmodes.py's KEYS):
//
//   start / start_count   the game's switches that start it, and how many hits it takes
//   shots / points        the switches that score while it runs, and what each scores
//   seconds               how long it runs (0: until the ball ends)
//   complete / complete_points   shots that complete it, and the bonus for that
//   sound_start/_shot/_complete/_end   the game's own callouts
//   title, panel, fonts, colors        a panel of ours over the game's screen, in its fonts
//
// Points go through the game's own scoring call; points_scale (title.cfg, from the port report)
// is what that call multiplies by (Scooby-Doo: x10), and the runtime asks for points / scale.
//
// PADMODES_PORT=<file>: also write the title's port report there and, at the first ball of a
// game, measure the points scale (one 1,000-point award) into it.  unity/rigrun.sh --port.
//
// Log: PADUNITY_LOG (default /game/logs/padunity.log), the same file padunity.so writes.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;
using UnityEngine.Video;

namespace PadModes {

public static class Loader {
    public const string Version = "2";
    static readonly string LogPath =
        Environment.GetEnvironmentVariable("PADUNITY_LOG") ?? "/game/logs/padunity.log";
    static readonly object gate = new object();
    static bool started, ported;
    static int frames;
    public static PadRuntime Runtime;

    public static void Log(string s) {
        try {
            lock (gate)
                File.AppendAllText(LogPath, DateTime.Now.ToString("HH:mm:ss.fff") + " [managed] " + s + "\n");
        } catch (Exception) { }
    }

    public static void Init() {
        Log("loaded: PadModes runtime " + Version + " (" + Glue.Framework + ") in domain \"" +
            AppDomain.CurrentDomain.FriendlyName + "\", CLR " + Environment.Version + ", from " +
            typeof(Loader).Assembly.Location);
        // Nothing of the game's may be touched on this thread: the first access to a game
        // class runs its static constructor here, and Scooby-Doo's Machine then deadlocked
        // against the main thread (PAD-1387).  Only the event subscription happens here.
        Application.onBeforeRender += OnFrame;
    }

    // Main thread, once per frame.
    static void OnFrame() {
        try {
            frames++;
            if (!started) {
                if (!Glue.Ready()) return;
                started = true;
                Runtime = new PadRuntime();
                Runtime.Load();
            }
            if (Glue.Ensure(Runtime))
                Log("PadRuntime added as game mode " + PadRuntime.ModeId + " (" + Glue.Framework + ") after " +
                    frames + " frames; the game now has " + Glue.ModeCount() + " modes");
            if (!ported) { ported = true; Port.WriteIfAsked(); }
            Glue.Poll(Runtime);
            Runtime.Frame();
        } catch (Exception e) { Log("frame: " + e); }
    }
}

// One custom mode: its keys and where it is.
public class CMode {
    public string File, Name, Title;
    public Dictionary<string, string> K = new Dictionary<string, string>();
    public List<int> Start = new List<int>(), Shots = new List<int>(), Combo = new List<int>();
    public int StartCount = 1, Complete, Seconds = 20, ComboSeconds = 5;
    public long Points = 1000000, CompletePoints, StartScore;
    // start rules (PAD-1424): start_on events, start_after game modes, once a ball/game, reset
    public HashSet<string> StartOn = new HashSet<string>(), StartAfter = new HashSet<string>();
    public string Once = "no";
    public bool ResetEachBall;
    // state
    public int Hits, Made, ComboAt;
    public long Total;
    public bool Running, RanThisBall, RanThisGame;
    public float EndsAt, ComboTime;
    public HashSet<int> ScoreFired = new HashSet<int>();
    // lamps, coils, balls (PAD-1424)
    public List<string> Lamps = new List<string>();
    public Color32 LampColor = new Color32(255, 255, 255, 255);
    public int LampBlink = 4, MbBalls, MbSave = 10, AddTimes = 1, BallSave, Added;
    public List<int> MbOn = new List<int>(), AddBall = new List<int>(), HoldOn = new List<int>();
    public string HoldWhen = "shots", HoldCoil;
    public int HoldMs = 1000, HoldPower = 8;
    public bool HoldsOk, MbServed, MbSeen, Held;
    public float StartedAt, MbAt, OneSince, HeldUntil, LampAt;
    public int LampPhase = -1;
    // a mode's own files (PAD-1424)
    public bool MusicOn;
    public List<GameObject> Media = new List<GameObject>();

    public string Get(string k, string dflt) {
        string v;
        return K.TryGetValue(k, out v) && v.Length > 0 ? v : dflt;
    }
}

public class PadRuntime {
    public const int ModeId = 9001;
    public string Dir;
    public List<CMode> All = new List<CMode>();
    public Dictionary<string, string> Title = new Dictionary<string, string>();
    public long Scale = 1;
    bool ballLive;
    float ballAt;
    CMode shown;
    Panel panel;
    // our callouts in the game's queue, by clip name, until its voice channel takes them
    readonly List<string> queued = new List<string>();
    // what Track() saw last (the titles that do not announce a game or a ball)
    bool tActive, tTilted;
    int tPlayer = -1, tBall = -1;

    // ------------------------------------------------------------------ the mode folder
    public void Load() {
        Dir = Environment.GetEnvironmentVariable("PADMODES_DIR");
        if (string.IsNullOrEmpty(Dir))
            Dir = Path.Combine(Path.GetDirectoryName(typeof(Loader).Assembly.Location) ?? ".", "modes");
        if (!Directory.Exists(Dir)) { Loader.Log("no mode folder " + Dir + ": no custom modes"); return; }
        if (System.IO.File.Exists(Path.Combine(Dir, "off"))) { Loader.Log(Dir + "/off is there: custom modes are off"); return; }
        string tp = Path.Combine(Dir, "title.cfg");
        if (System.IO.File.Exists(tp))
            foreach (var kv in Parse(System.IO.File.ReadAllText(tp))) Title[kv.Key] = kv.Value;
        long.TryParse(Get(Title, "points_scale", "1"), out Scale);
        if (Scale < 1) Scale = 1;
        foreach (var f in Directory.GetFiles(Dir, "*.mode").OrderBy(x => x, StringComparer.Ordinal)) {
            var m = new CMode { File = Path.GetFileName(f) };
            foreach (var kv in Title) m.K[kv.Key] = kv.Value;
            foreach (var kv in Parse(System.IO.File.ReadAllText(f))) m.K[kv.Key] = kv.Value;
            m.Name = m.Get("name", m.File.Substring(0, m.File.Length - 5));
            m.Title = m.Get("title", m.Name);
            m.Start = SwitchList(m, "start");
            m.Shots = SwitchList(m, "shots");
            m.StartCount = Math.Max(1, Int(m.Get("start_count", "1")));
            m.Points = Long(m.Get("points", "1000000"));
            m.Seconds = Int(m.Get("seconds", "20"));
            m.Complete = Int(m.Get("complete", "0"));
            m.CompletePoints = Long(m.Get("complete_points", "0"));
            m.Combo = SwitchList(m, "start_combo");
            m.ComboSeconds = Math.Max(1, Int(m.Get("combo_seconds", "5")));
            m.StartScore = Long(m.Get("start_score", "0"));
            foreach (var w in Words(m.Get("start_on", ""))) m.StartOn.Add(w.ToLowerInvariant());
            foreach (var w in Words(m.Get("start_after", ""))) m.StartAfter.Add(w.ToLowerInvariant());
            m.Once = m.Get("start_once", "no");
            m.ResetEachBall = m.Get("start_count_reset", "game") == "ball";
            LampsCoilsBalls(m);
            All.Add(m);
            if (m.StartOn.Count + m.StartAfter.Count + m.Combo.Count > 0 || m.StartScore > 0)
                Loader.Log("mode " + m.File + " start rules: on " + string.Join(" ", m.StartOn.ToArray()) +
                    "; after " + string.Join(" ", m.StartAfter.ToArray()) + "; score " + m.StartScore +
                    "; combo " + Names(m.Combo) + " within " + m.ComboSeconds + " s; once " + m.Once +
                    "; count reset " + (m.ResetEachBall ? "ball" : "game"));
            Loader.Log("mode " + m.File + " \"" + m.Name + "\": start " + Names(m.Start) + " x" + m.StartCount +
                ", shots " + Names(m.Shots) + " " + m.Points + " each, " + m.Seconds + " s, complete " + m.Complete +
                " (+" + m.CompletePoints + ")");
        }
        Loader.Log(All.Count + " custom mode(s) from " + Dir + "; points scale " + Scale);
    }

    // PAD-1424: the game's lamps on a layer of ours, its coils, its balls (MODES.md "Balls and coils")
    void LampsCoilsBalls(CMode m) {
        m.Lamps = Words(m.Get("lamps", "")).ToList();
        var c = Panel.Colour(m.Get("lamp_color", "ffffff"));
        m.LampColor = new Color32((byte)(c.r * 255), (byte)(c.g * 255), (byte)(c.b * 255), 255);
        m.LampBlink = Math.Max(0, Math.Min(10, Int(m.Get("lamp_blink", "4"))));
        var mb = Words(m.Get("multiball", ""));
        m.MbBalls = mb.Length > 0 ? Math.Max(0, Math.Min(6, Int(mb[0]))) : 0;
        m.MbSave = mb.Length > 1 ? Math.Max(0, Math.Min(120, Int(mb[1]))) : 10;
        m.MbOn = SwitchList(m, "multiball_on");
        var ab = Words(m.Get("add_ball", "")).ToList();
        int t;
        if (ab.Count > 1 && int.TryParse(ab[ab.Count - 1], out t)) { m.AddTimes = Math.Max(1, Math.Min(6, t)); ab.RemoveAt(ab.Count - 1); }
        m.K["add_ball_switches"] = string.Join(" ", ab.ToArray());
        m.AddBall = SwitchList(m, "add_ball_switches");
        m.BallSave = Math.Max(0, Math.Min(120, Int(m.Get("ball_save", "0"))));
        var h = Words(m.Get("coil_hold", ""));
        if (h.Length > 0) {
            m.HoldCoil = h[0];
            m.HoldMs = h.Length > 1 ? Math.Max(100, Math.Min(5000, Int(h[1]))) : 1000;
            m.HoldPower = h.Length > 2 ? Math.Max(1, Math.Min(16, Int(h[2]))) : 8;
        }
        string on = m.Get("coil_hold_on", "shots");
        m.HoldWhen = on == "start" || on == "shots" ? on : "switches";
        if (m.HoldWhen == "switches") m.HoldOn = SwitchList(m, "coil_hold_on");
        m.HoldsOk = m.Get("coil_holds", "off") == "on";
        if (m.Lamps.Count > 0 || m.MbBalls > 0 || m.AddBall.Count > 0 || m.BallSave > 0 || m.HoldCoil != null ||
            m.Get("coil_start", "") + m.Get("coil_shot", "") + m.Get("coil_complete", "") != "")
            Loader.Log("mode " + m.File + ": lamps " + string.Join(" ", m.Lamps.ToArray()) + " #" + m.Get("lamp_color", "ffffff") +
                " x" + m.LampBlink + "/s; multiball " + m.MbBalls + " (save " + m.MbSave + " s, on " + Names(m.MbOn) +
                "); add_ball " + Names(m.AddBall) + " x" + m.AddTimes + "; ball_save " + m.BallSave + "; coils " +
                m.Get("coil_start", "-") + " / " + m.Get("coil_shot", "-") + " / " + m.Get("coil_complete", "-") +
                "; hold " + (m.HoldCoil ?? "-") + " " + m.HoldMs + " ms " + m.HoldPower + "/32 on " + m.HoldWhen);
    }

    static Dictionary<string, string> Parse(string text) {
        var d = new Dictionary<string, string>();
        foreach (var raw in text.Split('\n')) {
            var line = raw.Trim();
            if (line.Length == 0 || line[0] == '#' || line[0] == ';') continue;
            int eq = line.IndexOf('=');
            if (eq <= 0) continue;
            d[line.Substring(0, eq).Trim().ToLowerInvariant()] = line.Substring(eq + 1).Trim();
        }
        return d;
    }

    static string Get(Dictionary<string, string> d, string k, string dflt) {
        string v;
        return d.TryGetValue(k, out v) && v.Length > 0 ? v : dflt;
    }

    static int Int(string s) { long v = Long(s); return v > int.MaxValue ? int.MaxValue : (int)v; }
    static long Long(string s) {
        long v;
        return long.TryParse((s ?? "").Replace(",", "").Replace("_", ""), NumberStyles.Integer,
            CultureInfo.InvariantCulture, out v) ? v : 0;
    }

    // a lamp or coil name as a mode file writes it, to match the game's ("REAR MAGNET" = REAR_MAGNET)
    public static string Tok(string n) {
        return string.Join("_", (n ?? "").ToLowerInvariant().Split(new[] { ' ', '_', '\t' }, StringSplitOptions.RemoveEmptyEntries));
    }

    static string[] Words(string s) {
        return (s ?? "").Split(new[] { ' ', ',', '\t' }, StringSplitOptions.RemoveEmptyEntries);
    }

    // switch names -> the game's switch numbers
    List<int> SwitchList(CMode m, string key) {
        var o = new List<int>();
        foreach (var w in Words(m.Get(key, ""))) {
            int n = FindSwitch(w);
            if (n < 0) Loader.Log(m.File + ": " + key + " " + w + " is not one of this game's switches (ignored)");
            else o.Add(n);
        }
        return o;
    }

    // A switch by the game's own symbol ("right_inlane") or by its label ("RIGHT INLANE").
    public static int FindSwitch(string w) {
        foreach (var s in Glue.Switches())
            if (string.Equals(s.Sym, w, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(s.Label, w, StringComparison.OrdinalIgnoreCase)) return s.Num;
        return -1;
    }

    static string Names(List<int> l) {
        return l.Count == 0 ? "-" : string.Join(" ", l.Select(n => Glue.SwitchName(n)).ToArray());
    }

    // ------------------------------------------------------------------ the game's messages
    public void OnNewGame() {
        foreach (var m in All) {
            Stop(m, null);
            m.Hits = 0; m.ComboAt = 0; m.RanThisGame = false; m.ScoreFired.Clear();
        }
        extraSeen = -1;
        Loader.Log("new_game_started: start counts reset");
    }

    public void OnBallStart() {
        ballLive = true;
        ballAt = Time.unscaledTime;
        validSeen = false;
        mbSince = 0f; mbWas = false;
        lastRunning = null;
        extraSeen = -1;            // a new player's count, not an award
        int ball = Glue.Ball(), of = Glue.BallsPerGame();
        Loader.Log("ball_start (ball " + ball + " of " + of + ", player " + (Glue.Player() + 1) + ")");
        foreach (var m in All) {
            m.RanThisBall = false; m.ComboAt = 0;
            if (m.ResetEachBall) m.Hits = 0;
        }
        GameEvent("ball_start");
        if (ball == 1) GameEvent("first_ball");
        if (ball > 0 && of > 0 && ball >= of && Glue.ExtraBallsLeft() <= 0) GameEvent("last_ball");
    }

    // ------------------------------------------------------------------ start rules (PAD-1424)
    bool validSeen, mbWas;
    float mbSince, rulesAt;
    HashSet<string> lastRunning;
    int extraSeen = -1;

    // A start rule fired for m: one more toward its start_count.
    void Fire(CMode m, string why) {
        if (m.Running || !Playing()) return;
        if ((m.Once == "ball" && m.RanThisBall) || (m.Once == "game" && m.RanThisGame)) return;
        m.Hits++;
        Loader.Log(m.Name + ": " + why + " (" + m.Hits + " of " + m.StartCount + ")");
        if (m.Hits >= m.StartCount) StartMode(m);
    }

    // start_on: ball_start, first_ball, last_ball, valid_playfield, ball_saved, extra_ball, multiball_end
    public void GameEvent(string ev) {
        Loader.Log("game event " + ev);
        foreach (var m in All)
            if (m.StartOn.Contains(ev)) Fire(m, "start_on " + ev);
    }

    // The trough, the shooter lane, the buttons and the coin door are not the playfield.
    static readonly string[] NotPlayfield = { "trough", "shooter", "plunge", "launch", "flipper", "start",
        "coin", "door", "tilt", "slam", "outhole", "drain", "button", "service", "volume", "menu", "eject",
        "enter", "exit", "up", "down" };

    // by the switch's own words (right_inlane, LEFT FLIPPER EOS): a word that is, or starts with, one
    // of those (long ones only, so "upper" is not "up")
    public static bool IsPlayfield(int sw) {
        var words = (Glue.SwitchName(sw) ?? "").ToLowerInvariant().Split(new[] { '_', ' ', '-' },
            StringSplitOptions.RemoveEmptyEntries);
        foreach (var w in words)
            foreach (var x in NotPlayfield)
                if (w == x || (x.Length > 3 && w.StartsWith(x))) return false;
        return words.Length > 0;
    }

    void Combo(CMode m, int sw, float now) {
        if (m.Combo.Count < 2 || m.Running) return;
        if (m.ComboAt > 0 && now - m.ComboTime > m.ComboSeconds) m.ComboAt = 0;
        if (m.Combo[m.ComboAt] == sw) { m.ComboAt++; m.ComboTime = now; }
        else if (m.Combo[0] == sw) { m.ComboAt = 1; m.ComboTime = now; }
        if (m.ComboAt >= m.Combo.Count) { m.ComboAt = 0; Fire(m, "start_combo made"); }
    }

    // Ten times a second while a ball is in play: the player's score, extra balls, the balls in
    // play (a multiball's end) and the game's running modes (start_after).
    void Rules(float now) {
        if (!Playing() || now - rulesAt < 0.1f) return;
        rulesAt = now;
        int player = Glue.Player();
        long score = Glue.PlayerScore();
        foreach (var m in All)
            if (m.StartScore > 0 && score >= m.StartScore && !m.ScoreFired.Contains(player)) {
                m.ScoreFired.Add(player);
                Fire(m, "start_score " + m.StartScore + " reached (" + score + ")");
            }
        int extra = Glue.ExtraBallsAwarded();
        if (extra >= 0) {
            if (extraSeen >= 0 && extra > extraSeen) GameEvent("extra_ball");
            extraSeen = extra;
        }
        int inPlay = Glue.BallsInPlay();
        if (inPlay > 1) {
            if (mbSince == 0f) mbSince = now;
            if (now - mbSince >= 0.5f) mbWas = true;
        } else {
            mbSince = 0f;
            if (mbWas && inPlay >= 0) { mbWas = false; GameEvent("multiball_end"); }
        }
        if (!All.Any(m => m.StartAfter.Count > 0)) return;
        var running = new HashSet<string>(Glue.RunningModes().Select(x => x.ToLowerInvariant()));
        if (lastRunning != null)
            foreach (var ended in lastRunning.Where(x => !running.Contains(x)).ToList())
                foreach (var m in All)
                    if (m.StartAfter.Contains(ended) || m.StartAfter.Contains("any")) Fire(m, "start_after " + ended + " ended");
        lastRunning = running;
    }

    public void OnBallEnd(string why) {
        ballLive = false;
        foreach (var m in All) Stop(m, why);
    }

    public void OnGameEnd() {
        ballLive = false;
        foreach (var m in All) Stop(m, "the game ended");
    }

    // For the titles that do not announce a game or a ball (Evil Dead), or announce them with
    // calls whose arguments differ between titles (Texas Chainsaw, Halloween, Ultraman): what
    // the game says now, once a frame.  A new game when it goes active; a ball when the player
    // or the ball number changes while it is; the ball's end on tilt.
    public void Track(bool active, int player, int ball, bool tilted) {
        if (active && !tActive) { OnNewGame(); tPlayer = tBall = -1; }
        if (!active && tActive) OnGameEnd();
        if (active && ball > 0 && (player != tPlayer || ball != tBall)) {
            if (ballLive) OnBallEnd("the ball ended");
            tPlayer = player; tBall = ball;
            if (!tilted) OnBallStart();
        }
        if (tilted && !tTilted && ballLive) OnBallEnd("tilt");
        tActive = active; tTilted = tilted;
    }

    bool Playing() { return ballLive && Glue.HasPlayers(); }

    public void OnSwitch(int sw) {
        if (!Playing()) return;
        float now = Time.unscaledTime;
        if (!validSeen && IsPlayfield(sw)) { validSeen = true; GameEvent("valid_playfield"); }
        foreach (var m in All) {
            if (m.Running) {
                RunningSwitch(m, sw);
                if (m.Running && m.Shots.Contains(sw)) Shot(m, sw);
                continue;
            }
            Combo(m, sw, now);
            if (!m.Running && m.Start.Contains(sw)) Fire(m, "start switch " + Glue.SwitchName(sw) + " hit");
        }
    }

    void StartMode(CMode m) {
        m.Hits = 0;
        m.ComboAt = 0;
        m.RanThisBall = m.RanThisGame = true;
        m.Running = true;
        m.Made = 0;
        m.Total = 0;
        m.EndsAt = m.Seconds > 0 ? Time.unscaledTime + m.Seconds : 0f;
        Loader.Log(m.Name + ": STARTED (" + (m.Seconds > 0 ? m.Seconds + " s" : "until the ball ends") + ")");
        Sound(m, "sound_start");
        m.StartedAt = Time.unscaledTime;
        m.MbServed = false; m.OneSince = 0f; m.Added = 0; m.LampPhase = -1;
        try { Files.Music(this, m, true); Files.Show(this, m, true); } catch (Exception e) { Loader.Log(m.Name + ": files: " + e); }
        Coil(m, "coil_start");
        if (m.HoldWhen == "start") Hold(m);
        if (m.BallSave > 0) Save(m, m.BallSave, 1);
        if (m.MbBalls > 0 && m.MbOn.Count == 0) Multiball(m);
        shown = m;
        Draw();
    }

    void Shot(CMode m, int sw) {
        long got = Score(m.Points);
        m.Made++;
        m.Total += got;
        Loader.Log(m.Name + ": shot " + m.Made + (m.Complete > 0 ? " of " + m.Complete : "") + " on " +
            Glue.SwitchName(sw) + ": " + got + " points (player score " + Glue.PlayerScore() + ")");
        Sound(m, "sound_shot");
        Coil(m, "coil_shot");
        if (m.HoldWhen == "shots") Hold(m);
        shown = m;
        if (m.Complete > 0 && m.Made >= m.Complete) {
            long bonus = m.CompletePoints > 0 ? Score(m.CompletePoints) : 0;
            m.Total += bonus;
            Loader.Log(m.Name + ": COMPLETED, bonus " + bonus + ", mode total " + m.Total);
            Sound(m, "sound_complete");
            Coil(m, "coil_complete");
            Stop(m, null);
            return;
        }
        Draw();
    }

    void Stop(CMode m, string why) {
        if (!m.Running) return;
        m.Running = false;
        if (why != null) {
            Loader.Log(m.Name + ": ended (" + why + "), " + m.Made + " shot(s), total " + m.Total);
            Sound(m, "sound_end");
        }
        try {
            Files.Music(this, m, false);
            Files.Show(this, m, false);
            foreach (var l in m.Lamps) Glue.LampRelease(l);
            if (m.Lamps.Count > 0) Loader.Log(m.Name + ": lamps handed back to the game");
            Unhold(m);
            if (m.BallSave > 0 && m.MbBalls == 0) Glue.BallSaveOff(m.BallSave);
        } catch (Exception e) { Loader.Log(m.Name + ": hand back: " + e.Message); }
        if (shown == m) shown = All.FirstOrDefault(x => x.Running);
        Draw();
    }

    public void Frame() {
        float now = Time.unscaledTime;
        // the port report's points scale, 2 s into a ball: Texas Chainsaw sets its playfield
        // multiplier in its own ball-started event, after the ball number this saw change
        if (ballLive && now - ballAt > 2f) Port.Measure(this);
        Rules(now);
        Files.Poll();
        foreach (var m in All) {
            if (!m.Running) continue;
            if (m.MbServed && m.MbOn.Count > 0) m.EndsAt = 0f;      // the balls came: the clock stops
            if (m.EndsAt > 0 && now >= m.EndsAt) { Stop(m, "time ran out"); continue; }
            try { BallsTick(m, now); LampsTick(m, now); } catch (Exception e) { Loader.Log(m.Name + ": " + e.Message); }
            if (m.Held && now >= m.HeldUntil) Unhold(m);
        }
        if (shown != null && shown.Running && panel != null) panel.Timer(shown);
        // a queued callout: the game's queue sets voice_channel.clip and plays it when the channel is free
        if (queued.Count > 0) {
            var vc = Glue.VoiceChannel();
            if (vc != null && vc.clip != null && queued[0] == vc.clip.name) {
                Loader.Log("callout " + vc.clip.name + " handed to the game's voice channel (Play, playing " + vc.isPlaying + ")");
                queued.RemoveAt(0);
            }
        }
    }

    // ------------------------------------------------------------------ lamps, coils, balls (PAD-1424)
    void RunningSwitch(CMode m, int sw) {
        if (m.MbOn.Contains(sw) && !m.MbServed) Multiball(m);
        if (m.AddBall.Contains(sw) && m.Added < m.AddTimes) {
            m.Added++;
            Loader.Log(m.Name + ": add a ball on " + Glue.SwitchName(sw) + " (" + m.Added + " of " + m.AddTimes + "): " + Glue.AddBalls(1));
            Save(m, Math.Max(2, m.MbBalls > 0 ? m.MbSave : 2), Math.Max(2, Glue.BallsInPlay() + 1));
        }
        if (m.HoldWhen == "switches" && m.HoldOn.Contains(sw)) Hold(m);
    }

    // Our colour on the mode's lamps, blinking lamp_blink times a second; set again four times a
    // second (the game's own lighting writes the same lamps on titles with no layer of ours).
    void LampsTick(CMode m, float now) {
        if (m.Lamps.Count == 0) return;
        int phase = m.LampBlink > 0 ? (int)((now - m.StartedAt) * m.LampBlink * 2f) % 2 : 0;
        if (phase == m.LampPhase && now - m.LampAt < 0.25f) return;
        bool first = m.LampPhase < 0;
        m.LampPhase = phase; m.LampAt = now;
        var c = phase == 0 ? m.LampColor : new Color32(0, 0, 0, 255);
        var missing = new List<string>();
        foreach (var l in m.Lamps) if (!Glue.LampSet(l, c)) missing.Add(l);
        if (first)
            Loader.Log(m.Name + ": lamps " + string.Join(" ", m.Lamps.Where(x => !missing.Contains(x)).ToArray()) + " lit #" +
                m.Get("lamp_color", "ffffff") + (m.LampBlink > 0 ? ", " + m.LampBlink + " flashes a second" : "") +
                (missing.Count > 0 ? "; not this game's lamps: " + string.Join(" ", missing.ToArray()) : ""));
    }

    void Coil(CMode m, string key) {
        var w = Words(m.Get(key, ""));
        if (w.Length == 0) return;
        string how = Glue.CoilPulse(w[0], w.Length > 1 ? Int(w[1]) : 0);
        Loader.Log(m.Name + ": " + key + " " + w[0] + (how == null ? ": not one of this game's coils" : " pulsed (" + how + ")"));
    }

    void Hold(CMode m) {
        if (m.HoldCoil == null) return;
        if (!m.HoldsOk) { Loader.Log(m.Name + ": coil_hold " + m.HoldCoil + " refused: title.cfg has no coil_holds = on"); return; }
        string how = Glue.CoilHold(m.HoldCoil, m.HoldPower);
        if (how == null) { Loader.Log(m.Name + ": coil_hold " + m.HoldCoil + ": not one of this game's coils"); return; }
        m.Held = true;
        m.HeldUntil = Time.unscaledTime + m.HoldMs / 1000f;
        Loader.Log(m.Name + ": holding " + m.HoldCoil + " for " + m.HoldMs + " ms at " + m.HoldPower + " of 32 (" + how + ")");
    }

    void Unhold(CMode m) {
        if (!m.Held) return;
        m.Held = false;
        Glue.CoilRelease(m.HoldCoil);
        Loader.Log(m.Name + ": let go of " + m.HoldCoil);
    }

    void Save(CMode m, int secs, int balls) {
        Loader.Log(m.Name + ": ball save " + secs + " s (" + balls + " ball(s)): " + Glue.BallSave(secs, balls));
    }

    void Multiball(CMode m) {
        int have = Math.Max(1, Glue.BallsInPlay());
        m.MbServed = true; m.MbSeen = false; m.MbAt = Time.unscaledTime; m.OneSince = 0f;
        Loader.Log(m.Name + ": multiball, " + m.MbBalls + " balls in play wanted, " + have + " now" +
            (m.MbBalls > have ? ": " + Glue.AddBalls(m.MbBalls - have) : ""));
        if (m.MbSave > 0) Save(m, m.MbSave, Math.Max(2, m.MbBalls));       // every ball in play
    }

    // A multiball of ours ends the mode once one ball is left for 2 s, after its ball save and 3 s more,
    // counted from when the game has the balls in play (a trough still loading a ball serves ours late);
    // balls that never come in 20 s end it too.
    void BallsTick(CMode m, float now) {
        if (!m.MbServed) return;
        if (!m.MbSeen) {
            if (Glue.BallsInPlay() > 1) { m.MbSeen = true; m.MbAt = now; Loader.Log(m.Name + ": the balls are in play"); }
            else if (now - m.MbAt > 20f) Stop(m, "the multiball's balls never came");
            return;
        }
        if (now - m.MbAt < m.MbSave + 3) return;
        if (Glue.BallsInPlay() <= 1) {
            if (m.OneSince == 0f) m.OneSince = now;
            else if (now - m.OneSince >= 2f) Stop(m, "one ball left");
        } else m.OneSince = 0f;
    }

    // ------------------------------------------------------------------ the game's scoring
    public long Score(long points) {
        long before = Glue.PlayerScore();
        Glue.Award((points + Scale / 2) / Scale);
        return Glue.PlayerScore() - before;
    }

    // ------------------------------------------------------------------ the game's callouts
    void Sound(CMode m, string key) {
        string name = m.Get(key, "");
        if (name.Length == 0) return;
        if (Files.IsSound(name)) { Files.PlaySound(this, m, key, name); return; }
        string how;
        string watch = Glue.Voice(name, out how);
        if (how == null) { Loader.Log(m.Name + ": " + key + " " + name + ": no such callout in this game"); return; }
        if (!string.IsNullOrEmpty(watch)) queued.Add(watch);
        Loader.Log(m.Name + ": " + key + " " + name + " " + how);
    }

    // ------------------------------------------------------------------ the panel
    void Draw() {
        try {
            if (shown == null || !shown.Running || shown.Get("panel", "middle") == "none") {
                if (panel != null) panel.Show(false);
                return;
            }
            if (panel == null) panel = new Panel();
            panel.Set(shown);
        } catch (Exception e) { Loader.Log("panel: " + e.Message); }
    }
}

// A mode's own files (PAD-1424): sounds and music through Unity's own audio loader on sources of
// ours (the game's voice mixer group; its music sources muted while the mode's music plays), the
// picture and the video (VideoPlayer from the file: VP8 webm on Linux) on a canvas just under the
// panel, each fitted in its box.
public static class Files {
    static readonly Dictionary<string, AudioClip> clips = new Dictionary<string, AudioClip>();
    static readonly List<KeyValuePair<UnityWebRequest, Action<AudioClip>>> loading =
        new List<KeyValuePair<UnityWebRequest, Action<AudioClip>>>();
    static readonly Dictionary<string, List<Action<AudioClip>>> waiting = new Dictionary<string, List<Action<AudioClip>>>();
    static GameObject root;
    static AudioSource fx, music;
    static Canvas canvas;
    static List<AudioSource> muted = new List<AudioSource>();

    public static bool IsSound(string v) {
        string e = Path.GetExtension(v ?? "").ToLowerInvariant();
        return e == ".ogg" || e == ".wav";
    }

    static string PathOf(PadRuntime r, string name) { return Path.Combine(r.Dir, name); }

    static void Root() {
        if (root != null) return;
        root = new GameObject("PadModesFiles");
        UnityEngine.Object.DontDestroyOnLoad(root);
        fx = root.AddComponent<AudioSource>();
        music = root.AddComponent<AudioSource>();
        fx.playOnAwake = music.playOnAwake = false;
        fx.spatialBlend = music.spatialBlend = 0f;
    }

    // the clip, loaded once (UnityWebRequestMultimedia, polled each frame), then *then* with it
    static void Clip(PadRuntime r, string name, Action<AudioClip> then) {
        AudioClip c;
        if (clips.TryGetValue(name, out c)) { then(c); return; }
        List<Action<AudioClip>> w;
        if (waiting.TryGetValue(name, out w)) { w.Add(then); return; }
        waiting[name] = new List<Action<AudioClip>> { then };
        string path = PathOf(r, name);
        var type = Path.GetExtension(name).ToLowerInvariant() == ".wav" ? AudioType.WAV : AudioType.OGGVORBIS;
        var req = UnityWebRequestMultimedia.GetAudioClip("file://" + path, type);
        req.SendWebRequest();
        loading.Add(new KeyValuePair<UnityWebRequest, Action<AudioClip>>(req, got => {
            clips[name] = got;
            foreach (var a in waiting[name]) a(got);
            waiting.Remove(name);
        }));
    }

    public static void Poll() {
        for (int i = loading.Count - 1; i >= 0; i--) {
            var req = loading[i].Key;
            if (!req.isDone) continue;
            var then = loading[i].Value;
            loading.RemoveAt(i);
            AudioClip c = null;
            try { c = DownloadHandlerAudioClip.GetContent(req); } catch (Exception e) { Loader.Log("audio file: " + e.Message); }
            if (c == null || c.length <= 0f) { Loader.Log("audio file " + req.url + " could not be read: " + req.error); c = null; }
            else Loader.Log("audio file " + req.url + " read (" + c.length.ToString("0.00") + " s)");
            req.Dispose();
            try { then(c); } catch (Exception e) { Loader.Log("audio file: " + e.Message); }
        }
        if (muted.Count > 0) foreach (var s in muted) if (s != null && !s.mute) s.mute = true;
    }

    public static void PlaySound(PadRuntime r, CMode m, string key, string name) {
        Root();
        // sound_channel music: at the game's music level and mixer group; the others at its voice level
        bool asMusic = m.Get("sound_channel", "fanfare") == "music";
        Clip(r, name, c => {
            if (c == null) return;
            var vc = asMusic ? Glue.MusicSources().FirstOrDefault(x => x != null) : Glue.VoiceChannel();
            if (vc != null) fx.outputAudioMixerGroup = vc.outputAudioMixerGroup;
            fx.PlayOneShot(c, vc != null ? Math.Max(vc.volume, 0.2f) : 1f);
            Loader.Log(m.Name + ": " + key + " " + name + " (a file of the mode's own) playing at the game's " +
                (asMusic ? "music" : "voice") + " level");
        });
    }

    public static void Music(PadRuntime r, CMode m, bool on) {
        string name = m.Get("music", "");
        if (name.Length == 0) return;
        Root();
        if (on) {
            m.MusicOn = true;
            Clip(r, name, c => {
                if (c == null || !m.MusicOn) return;
                var game = Glue.MusicSources().Where(s => s != null).ToList();
                if (game.Count > 0) { music.outputAudioMixerGroup = game[0].outputAudioMixerGroup; music.volume = Math.Max(game.Max(s => s.volume), 0.2f); }
                music.clip = c; music.loop = true; music.Play();
                muted = game;
                foreach (var s in game) s.mute = true;
                Loader.Log(m.Name + ": music " + name + " playing (looped); the game's " + game.Count + " music source(s) muted");
            });
            return;
        }
        if (!m.MusicOn) return;
        m.MusicOn = false;
        music.Stop();
        foreach (var s in muted) if (s != null) s.mute = false;
        muted = new List<AudioSource>();
        Loader.Log(m.Name + ": music " + name + " stopped, the game's own music back");
    }

    public static void Show(PadRuntime r, CMode m, bool on) {
        foreach (var g in m.Media) if (g != null) UnityEngine.Object.Destroy(g);
        if (m.Media.Count > 0) Loader.Log(m.Name + ": picture/video taken off the screen");
        m.Media.Clear();
        if (!on) return;
        string pic = m.Get("picture", ""), vid = m.Get("video", "");
        if (pic.Length == 0 && vid.Length == 0) return;
        if (canvas == null) {
            var go = new GameObject("PadModesMedia");
            UnityEngine.Object.DontDestroyOnLoad(go);
            canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 29999;                 // under the panel (30000), over the game
            var sc = go.AddComponent<CanvasScaler>();
            sc.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            sc.referenceResolution = new Vector2(1920, 1080);
        }
        if (vid.Length > 0) {
            var g = new GameObject("video");
            g.transform.SetParent(canvas.transform, false);
            var img = g.AddComponent<RawImage>();
            var vp = g.AddComponent<VideoPlayer>();
            vp.playOnAwake = false;
            vp.source = VideoSource.Url;
            vp.url = "file://" + PathOf(r, vid);
            vp.isLooping = m.Get("video_loop", "yes") != "no";
            vp.audioOutputMode = VideoAudioOutputMode.None;      // silent, as on JJP
            vp.renderMode = VideoRenderMode.RenderTexture;
            var box = Box(m.Get("video_at", ""));
            vp.prepareCompleted += p => {
                var rt = new RenderTexture((int)Math.Max(16, p.width), (int)Math.Max(16, p.height), 0);
                p.targetTexture = rt;
                img.texture = rt;
                Place(img.rectTransform, box, p.width, p.height);
                p.Play();
                Loader.Log(m.Name + ": video " + vid + " (" + p.width + "x" + p.height + ") playing at " + string.Join(" ", box.Select(x => x.ToString()).ToArray()));
            };
            vp.errorReceived += (p, e) => Loader.Log(m.Name + ": video " + vid + ": " + e);
            Place(img.rectTransform, box, 16, 9);
            img.color = new Color(0, 0, 0, 0);
            vp.prepareCompleted += p => img.color = Color.white;
            vp.Prepare();
            m.Media.Add(g);
        }
        if (pic.Length > 0) {
            var tex = new Texture2D(2, 2);
            byte[] bytes = null;
            try { bytes = File.ReadAllBytes(PathOf(r, pic)); } catch (Exception e) { Loader.Log(m.Name + ": picture " + pic + ": " + e.Message); }
            if (bytes != null && ImageConversion.LoadImage(tex, bytes)) {
                var g = new GameObject("picture");
                g.transform.SetParent(canvas.transform, false);
                var img = g.AddComponent<RawImage>();
                img.texture = tex;
                var box = Box(m.Get("picture_at", ""));
                Place(img.rectTransform, box, tex.width, tex.height);
                m.Media.Add(g);
                Loader.Log(m.Name + ": picture " + pic + " (" + tex.width + "x" + tex.height + ") on the screen at " + string.Join(" ", box.Select(x => x.ToString()).ToArray()));
            } else if (bytes != null) Loader.Log(m.Name + ": picture " + pic + " could not be read");
        }
    }

    static int[] Box(string v) {
        var w = (v ?? "").Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries).Select(x => { int n; return int.TryParse(x, out n) ? n : -1; }).ToArray();
        return w.Length == 4 && w.Min() >= 0 && w[2] > 0 && w[3] > 0 ? w : new[] { 0, 0, 100, 100 };
    }

    // fitted in the box (x y w h, percent of the screen), its shape kept, centred
    static void Place(RectTransform rt, int[] b, double w, double h) {
        float sw = 1920f, sh = 1080f;
        float bw = sw * b[2] / 100f, bh = sh * b[3] / 100f;
        float k = Math.Min(bw / (float)Math.Max(w, 1), bh / (float)Math.Max(h, 1));
        float nw = (float)w * k, nh = (float)h * k;
        float cx = sw * b[0] / 100f + bw / 2f, cy = sh * b[1] / 100f + bh / 2f;
        rt.anchorMin = rt.anchorMax = new Vector2(0f, 1f);
        rt.pivot = new Vector2(0.5f, 0.5f);
        rt.sizeDelta = new Vector2(nw, nh);
        rt.anchoredPosition = new Vector2(cx, -cy);
    }
}

// A switch as the glue reports it: the game's symbol, its number, its label.
public struct Sw {
    public string Sym, Label;
    public int Num;
    public Sw(string sym, int num, string label) { Sym = sym; Num = num; Label = label; }
}

// The mode's panel: a canvas of ours over the game's screen (sorting order above the game's),
// the title, the mode's total and its time left, in the game's own TextMeshPro fonts.
public class Panel {
    GameObject root, box;
    Image back;
    TMPro.TextMeshProUGUI title, value, timer;
    string place;
    int lastSecs = -1;

    public Panel() {
        root = new GameObject("PadModesPanel");
        UnityEngine.Object.DontDestroyOnLoad(root);
        var c = root.AddComponent<Canvas>();
        c.renderMode = RenderMode.ScreenSpaceOverlay;
        c.sortingOrder = 30000;
        var sc = root.AddComponent<CanvasScaler>();
        sc.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        sc.referenceResolution = new Vector2(1920, 1080);
        box = new GameObject("box");
        box.transform.SetParent(root.transform, false);
        back = box.AddComponent<Image>();
        title = Text("title", 0.55f, 1.0f);
        value = Text("value", 0.22f, 0.58f);
        timer = Text("timer", 0.0f, 0.24f);
    }

    TMPro.TextMeshProUGUI Text(string n, float y0, float y1) {
        var g = new GameObject(n);
        g.transform.SetParent(box.transform, false);
        var rt = g.AddComponent<RectTransform>();
        rt.anchorMin = new Vector2(0.04f, y0);
        rt.anchorMax = new Vector2(0.96f, y1);
        rt.offsetMin = rt.offsetMax = Vector2.zero;
        var t = g.AddComponent<TMPro.TextMeshProUGUI>();
        t.alignment = TMPro.TextAlignmentOptions.Center;
        t.enableAutoSizing = true;
        t.fontSizeMin = 10;
        t.fontSizeMax = 200;
        t.enableWordWrapping = false;
        return t;
    }

    public void Show(bool on) { if (root.activeSelf != on) root.SetActive(on); }

    public void Set(CMode m) {
        Show(true);
        string p = m.Get("panel", "middle");
        if (p != place) {
            place = p;
            var rt = box.GetComponent<RectTransform>();
            float y0 = p == "top" ? 0.70f : p == "bottom" ? 0.03f : 0.36f;
            rt.anchorMin = new Vector2(0.22f, y0);
            rt.anchorMax = new Vector2(0.78f, y0 + 0.27f);
            rt.offsetMin = rt.offsetMax = Vector2.zero;
        }
        back.color = Colour(m.Get("panel_color", "000000b0"));
        Style(title, m.Get("font_title", ""), m.Get("title_color", "ffffff"));
        Style(value, m.Get("font_value", ""), m.Get("value_color", "ffdc00"));
        Style(timer, m.Get("font_timer", ""), m.Get("timer_color", "ffffff"));
        title.text = m.Title;
        value.text = m.Total.ToString("N0", CultureInfo.InvariantCulture);
        lastSecs = -1;
        Timer(m);
    }

    public void Timer(CMode m) {
        int secs = m.EndsAt > 0 ? Mathf.Max(0, Mathf.CeilToInt(m.EndsAt - Time.unscaledTime)) : -1;
        if (secs == lastSecs) return;
        lastSecs = secs;
        timer.text = secs < 0 ? "" : secs.ToString(CultureInfo.InvariantCulture);
    }

    static void Style(TMPro.TextMeshProUGUI t, string font, string rgba) {
        var f = Port.Font(font);
        if (f != null && t.font != f) t.font = f;
        t.color = Colour(rgba);
    }

    public static Color Colour(string hex) {
        hex = (hex ?? "").TrimStart('#');
        uint v;
        if (!uint.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out v)) return Color.white;
        if (hex.Length == 6) v = (v << 8) | 0xff;
        return new Color(((v >> 24) & 0xff) / 255f, ((v >> 16) & 0xff) / 255f, ((v >> 8) & 0xff) / 255f, (v & 0xff) / 255f);
    }
}

// The title's names, for the port report.
public static class Port {
    static Dictionary<string, TMPro.TMP_FontAsset> fonts;
    static bool measured;
    static long scaleSeen;

    public static TMPro.TMP_FontAsset Font(string name) {
        if (fonts == null) {
            fonts = new Dictionary<string, TMPro.TMP_FontAsset>();
            foreach (var f in Resources.FindObjectsOfTypeAll<TMPro.TMP_FontAsset>())
                if (f != null && !fonts.ContainsKey(f.name)) fonts[f.name] = f;
        }
        TMPro.TMP_FontAsset a;
        return !string.IsNullOrEmpty(name) && fonts.TryGetValue(name, out a) ? a : null;
    }

    static string Json(string s) {
        var b = new StringBuilder("\"");
        foreach (char c in s ?? "") {
            if (c == '"' || c == '\\') b.Append('\\').Append(c);
            else if (c < ' ') b.AppendFormat("\\u{0:x4}", (int)c);
            else b.Append(c);
        }
        return b.Append('"').ToString();
    }

    static string List(IEnumerable<string> l) { return "[" + string.Join(", ", l.Select(Json).ToArray()) + "]"; }
    static string Map(IEnumerable<KeyValuePair<string, string>> l) {
        return "{" + string.Join(", ", l.Select(kv => Json(kv.Key) + ": " + Json(kv.Value)).ToArray()) + "}";
    }

    public static void WriteIfAsked() {
        string to = Environment.GetEnvironmentVariable("PADMODES_PORT");
        if (string.IsNullOrEmpty(to)) return;
        try {
            Font("");
            var sw = Glue.Switches().Where(s => !string.IsNullOrEmpty(s.Sym)).ToList();
            var lamps = Glue.Lamps();
            var voices = Glue.Voices();
            var modes = Glue.GameModes();
            var b = new StringBuilder("{\n");
            b.Append("  \"engine\": \"unity\",\n");
            b.Append("  \"framework\": " + Json(Glue.Framework) + ",\n");
            b.Append("  \"product\": " + Json(Application.productName) + ",\n");
            b.Append("  \"unity\": " + Json(Application.unityVersion) + ",\n");
            b.Append("  \"game_version\": " + Json(Application.version) + ",\n");
            b.Append("  \"runtime\": " + Json(Loader.Version) + ",\n");
            b.Append("  \"switches\": " + List(sw.Select(s => s.Sym)) + ",\n");
            b.Append("  \"switch_ids\": {" + string.Join(", ", sw.Select(s => Json(s.Sym) + ": " + s.Num).ToArray()) + "},\n");
            b.Append("  \"switch_labels\": " + Map(sw.Select(s => new KeyValuePair<string, string>(s.Sym, s.Label))) + ",\n");
            b.Append("  \"lamps\": " + List(lamps) + ",\n");
            b.Append("  \"sounds\": " + List(voices.Keys.OrderBy(x => x, StringComparer.Ordinal)) + ",\n");
            b.Append("  \"sound_paths\": " + Map(voices.OrderBy(kv => kv.Key, StringComparer.Ordinal)) + ",\n");
            b.Append("  \"game_modes\": " + List(modes) + ",\n");
            b.Append("  \"mode_classes\": " + List(Glue.ModeClasses()) + ",\n");
            b.Append("  \"fonts\": " + List(fonts.Keys.OrderBy(x => x, StringComparer.Ordinal)) + ",\n");
            b.Append("  \"score_tags\": " + List(Glue.ScoreTags()) + ",\n");
            b.Append("  \"mode_tags\": " + List(Glue.ModeTags()) + ",\n");
            b.Append("  \"points_scale\": " + scaleSeen + "\n}\n");
            File.WriteAllText(to, b.ToString());
            Loader.Log("port report written to " + to + ": " + sw.Count + " switches, " + lamps.Count + " lamps, " +
                voices.Count + " callouts, " + modes.Count + " game modes, " + fonts.Count + " fonts" +
                (scaleSeen > 0 ? ", points scale " + scaleSeen : ", points scale not measured yet"));
        } catch (Exception e) { Loader.Log("port report: " + e); }
    }

    // The first ball of a game with PADMODES_PORT set: one award of 1,000 through the game's
    // own scoring tells the title's points scale.
    public static void Measure(PadRuntime r) {
        if (measured || string.IsNullOrEmpty(Environment.GetEnvironmentVariable("PADMODES_PORT"))) return;
        measured = true;
        long before = Glue.PlayerScore();
        Glue.Award(1000);
        long got = Glue.PlayerScore() - before;
        scaleSeen = got / 1000;
        Loader.Log("points scale: an award of 1000 scored " + got + " (" + Glue.ScoreNote() + ")");
        WriteIfAsked();
    }
}
}
