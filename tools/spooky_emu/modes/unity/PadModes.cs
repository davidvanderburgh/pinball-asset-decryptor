// PadModes.cs - PAD's custom mode runtime for Spooky's Unity titles (PAD-1417; the
// PAD-1387 probe made into the runtime).  Built against the title's own Managed/ (build.sh):
// it subclasses the game's Mode and calls the game's own scoring and callouts.
//
// padunity.so (LD_PRELOADed by the update's launch line) calls Loader.Init() on a thread
// attached to the game's Mono domain.  Init only subscribes to Application.onBeforeRender;
// on the main thread, once the game says Machine.modes_loaded, one Mode of ours (PadRuntime)
// is added with the game's own Modes.add_mode.  From then on the game's message loop hands
// it every switch and ball message it hands its own modes, and PadRuntime runs the custom
// modes in the folder beside this assembly (pad/modes: title.cfg + *.mode, the JJP keys
// tools/jjp_emu/MODES.md describes; the ones this runtime takes are mkspkmodes.py's KEYS):
//
//   start / start_count   the game's switches that start it, and how many hits it takes
//   shots / points        the switches that score while it runs, and what each scores
//   seconds               how long it runs (0: until the ball ends)
//   complete / complete_points   shots that complete it, and the bonus for that
//   sound_start/_shot/_complete/_end   the game's own callouts (Callouts.get + enqueue_callout)
//   title, panel, fonts, colors        a panel of ours over the game's screen, in its fonts
//
// Points go through the game's Mode.score_points -> Game.score_points, which multiplies
// what it is given by the title's scale (x10 on Scooby-Doo) and rounds to 100: the runtime
// asks for points / points_scale (title.cfg, from the port report) with the "bonus" tag, the
// game's tag for a flat award (no balls-in-play multiplier).
//
// PADMODES_PORT=<file>: also write the title's port report there (switches, lights, callouts,
// the game's modes, fonts, its score tags) and, at the first ball of a game, measure the
// points scale (one 1,000-point bonus award) into it.  tools/spooky_emu/modes/spkport.sh.
//
// Log: PADUNITY_LOG (default /game/logs/padunity.log), the same file padunity.so writes.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace PadModes {

public static class Loader {
    public const string Version = "1";
    static readonly string LogPath =
        Environment.GetEnvironmentVariable("PADUNITY_LOG") ?? "/game/logs/padunity.log";
    static readonly object gate = new object();
    static bool registered;
    static int frames;
    public static PadRuntime Runtime;

    public static void Log(string s) {
        try {
            lock (gate)
                File.AppendAllText(LogPath, DateTime.Now.ToString("HH:mm:ss.fff") + " [managed] " + s + "\n");
        } catch (Exception) { }
    }

    public static void Init() {
        Log("loaded: PadModes runtime " + Version + " in domain \"" + AppDomain.CurrentDomain.FriendlyName +
            "\", CLR " + Environment.Version + ", from " + typeof(Loader).Assembly.Location);
        // Nothing of the game's may be touched on this thread: the first access to a game
        // class runs its static constructor here, and Machine's then deadlocked against the
        // main thread (PAD-1387).  Only the event subscription happens here.
        Application.onBeforeRender += OnFrame;
    }

    // Main thread, once per frame.
    static void OnFrame() {
        try {
            frames++;
            if (!registered) {
                if (!Machine.modes_loaded) return;
                registered = true;
                Runtime = new PadRuntime(Modes.machine);
                Runtime.Load();
                Modes.add_mode(Runtime);
                Log("PadRuntime added as game mode " + PadRuntime.ModeId + " via Modes.add_mode after " +
                    frames + " frames; the game now has " + Modes.modes.Count + " modes");
                Port.WriteIfAsked();
            }
            Runtime.Frame();
        } catch (Exception e) { Log("frame: " + e); }
    }
}

// One custom mode: its keys and where it is.
public class CMode {
    public string File, Name, Title;
    public Dictionary<string, string> K = new Dictionary<string, string>();
    public List<int> Start = new List<int>(), Shots = new List<int>();
    public int StartCount = 1, Complete, Seconds = 20;
    public long Points = 1000000, CompletePoints;
    // state
    public int Hits, Made;
    public long Total;
    public bool Running;
    public float EndsAt;

    public string Get(string k, string dflt) {
        string v;
        return K.TryGetValue(k, out v) && v.Length > 0 ? v : dflt;
    }
}

public class PadRuntime : Mode {
    public const int ModeId = 9001;
    public string Dir;
    public List<CMode> All = new List<CMode>();
    public Dictionary<string, string> Title = new Dictionary<string, string>();
    long scale = 1;
    bool ballLive;
    CMode shown;
    Panel panel;
    // our callouts in the game's queue, by clip name, until its voice channel takes them
    readonly List<string> queued = new List<string>();

    public PadRuntime(Machine m) : base(m) {
        name = "PAD custom modes";
        mode = ModeId;
    }

    public override int init() { return 0; }
    public override int update() { return 0; }

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
        long.TryParse(Get(Title, "points_scale", "1"), out scale);
        if (scale < 1) scale = 1;
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
            All.Add(m);
            Loader.Log("mode " + m.File + " \"" + m.Name + "\": start " + Names(m.Start) + " x" + m.StartCount +
                ", shots " + Names(m.Shots) + " " + m.Points + " each, " + m.Seconds + " s, complete " + m.Complete +
                " (+" + m.CompletePoints + ")");
        }
        Loader.Log(All.Count + " custom mode(s) from " + Dir + "; points scale " + scale);
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

    static string[] Words(string s) {
        return (s ?? "").Split(new[] { ' ', ',', '\t' }, StringSplitOptions.RemoveEmptyEntries);
    }

    // switch names -> the game's switch numbers (Switches.name is indexed by number)
    List<int> SwitchList(CMode m, string key) {
        var o = new List<int>();
        foreach (var w in Words(m.Get(key, ""))) {
            int n = FindSwitch(w);
            if (n < 0) Loader.Log(m.File + ": " + key + " " + w + " is not one of this game's switches (ignored)");
            else o.Add(n);
        }
        return o;
    }

    // A switch by the game's own symbol (Switches.get_switch_name: "right_inlane"), or by its
    // label in Switches.name ("RIGHT INLANE").
    public static int FindSwitch(string w) {
        if (Switches.name == null) return -1;
        for (int i = 0; i < Switches.name.Count; i++) {
            string sym = null;
            try { sym = Switches.get_switch_name(i); } catch (Exception) { }
            if (string.Equals(sym, w, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(Switches.name[i], w, StringComparison.OrdinalIgnoreCase)) return i;
        }
        return -1;
    }

    // what the game's score_points is handed: "base" is its mode tag for a plain award (one mode
    // tag, or it logs an error per award), "bonus" its flat award (no balls-in-play multiplier)
    public static readonly string[] Tags = { "base", "bonus" };

    static string Names(List<int> l) {
        return l.Count == 0 ? "-" : string.Join(" ", l.Select(n => Switches.get_switch_name(n)).ToArray());
    }

    // ------------------------------------------------------------------ the game's messages
    public override int process_message(int[] msg) {
        try {
            int what = msg[Messages.offset_message], data = msg[Messages.offset_data];
            if (what == Messages.switch_active) Switch(data);
            else if (what == Messages.new_game_started) {
                foreach (var m in All) { Stop(m, null); m.Hits = 0; }
                Loader.Log("new_game_started: start counts reset");
            } else if (what == Messages.ball_start) {
                ballLive = true;
                Loader.Log("ball_start");
                Port.Measure(this);
            } else if (what == Messages.end_of_ball || what == Messages.tilt) {
                ballLive = false;
                foreach (var m in All) Stop(m, what == Messages.tilt ? "tilt" : "the ball ended");
            } else if (what == Messages.mode_started && data == Modes.attract_mode) {
                ballLive = false;
                foreach (var m in All) Stop(m, "the game ended");
            }
        } catch (Exception e) { Loader.Log("process_message: " + e); }
        return 0;
    }

    bool Playing() {
        Game g = Mode.machine.game;
        return ballLive && g != null && g.players != null && g.players.Count > 0;
    }

    void Switch(int sw) {
        if (!Playing()) return;
        foreach (var m in All) {
            if (m.Running) {
                if (m.Shots.Contains(sw)) Shot(m, sw);
            } else if (m.Start.Contains(sw)) {
                m.Hits++;
                Loader.Log(m.Name + ": start switch " + Switches.get_switch_name(sw) + " hit " + m.Hits + " of " + m.StartCount);
                if (m.Hits >= m.StartCount) StartMode(m);
            }
        }
    }

    void StartMode(CMode m) {
        m.Hits = 0;
        m.Running = true;
        m.Made = 0;
        m.Total = 0;
        m.EndsAt = m.Seconds > 0 ? Time.unscaledTime + m.Seconds : 0f;
        Loader.Log(m.Name + ": STARTED (" + (m.Seconds > 0 ? m.Seconds + " s" : "until the ball ends") + ")");
        Sound(m, "sound_start");
        shown = m;
        Draw();
    }

    void Shot(CMode m, int sw) {
        long got = Score(m.Points);
        m.Made++;
        m.Total += got;
        Loader.Log(m.Name + ": shot " + m.Made + (m.Complete > 0 ? " of " + m.Complete : "") + " on " +
            Switches.get_switch_name(sw) + ": " + got + " points (player score " + Score() + ")");
        Sound(m, "sound_shot");
        shown = m;
        if (m.Complete > 0 && m.Made >= m.Complete) {
            long bonus = m.CompletePoints > 0 ? Score(m.CompletePoints) : 0;
            m.Total += bonus;
            Loader.Log(m.Name + ": COMPLETED, bonus " + bonus + ", mode total " + m.Total);
            Sound(m, "sound_complete");
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
        if (shown == m) shown = All.FirstOrDefault(x => x.Running);
        Draw();
    }

    public void Frame() {
        float now = Time.unscaledTime;
        foreach (var m in All)
            if (m.Running && m.EndsAt > 0 && now >= m.EndsAt) Stop(m, "time ran out");
        if (shown != null && shown.Running && panel != null) panel.Timer(shown);
        // the game's callout queue sets voice_channel.clip and calls Play() when the channel is free
        var vc = Mode.machine.voice_channel;
        if (queued.Count > 0 && vc != null && vc.clip != null && queued[0] == vc.clip.name) {
            Loader.Log("callout " + vc.clip.name + " handed to the game's voice channel (Play, playing " + vc.isPlaying + ")");
            queued.RemoveAt(0);
        }
    }

    // ------------------------------------------------------------------ the game's scoring
    long Score() {
        Game g = Mode.machine.game;
        return g != null && g.players != null && g.players.Count > 0 ? g.player().score : 0;
    }

    public long Score(long points) {
        long before = Score();
        long ask = (points + scale / 2) / scale;
        score_points(ask, Tags);
        return Score() - before;
    }

    // ------------------------------------------------------------------ the game's callouts
    void Sound(CMode m, string key) {
        string name = m.Get(key, "");
        if (name.Length == 0) return;
        AudioClip clip = Port.Callout(name);
        if (clip == null) { Loader.Log(m.Name + ": " + key + " " + name + ": no such callout in this game"); return; }
        Mode.machine.enqueue_callout(clip);
        queued.Add(clip.name);
        Loader.Log(m.Name + ": " + key + " " + name + " (" + clip.name + ", " + clip.length.ToString("0.00") + " s) queued as a callout");
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

// The title's names, for the runtime and for the port report.
public static class Port {
    static Dictionary<string, string> callouts;
    static Dictionary<string, TMPro.TMP_FontAsset> fonts;
    static bool measured;

    // Callouts' static string fields: field name -> the clip's Resources path
    public static Dictionary<string, string> Callouts() {
        if (callouts != null) return callouts;
        callouts = new Dictionary<string, string>();
        foreach (var f in typeof(global::Callouts).GetFields(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic))
            if (f.FieldType == typeof(string)) {
                var v = f.GetValue(null) as string;
                if (!string.IsNullOrEmpty(v)) callouts[f.Name] = v;
            }
        return callouts;
    }

    public static AudioClip Callout(string name) {
        string path;
        if (!Callouts().TryGetValue(name, out path)) path = name;
        return global::Callouts.get(path);
    }

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

    static long scaleSeen;

    public static void WriteIfAsked() {
        string to = Environment.GetEnvironmentVariable("PADMODES_PORT");
        if (string.IsNullOrEmpty(to)) return;
        try {
            Font("");
            var g = Mode.machine.game;
            var sw = new List<string>();
            var swIds = new List<string>();
            var swLabels = new List<string>();
            if (Switches.name != null)
                for (int i = 0; i < Switches.name.Count; i++)
                    if (!string.IsNullOrEmpty(Switches.name[i]) && !Switches.name[i].StartsWith("UNUSED")) {
                        string sym = Switches.get_switch_name(i);
                        if (string.IsNullOrEmpty(sym)) continue;
                        sw.Add(sym);
                        swIds.Add(Json(sym) + ": " + i);
                        swLabels.Add(Json(sym) + ": " + Json(Switches.name[i]));
                    }
            var lamps = Lights.light_names == null ? new List<string>()
                : Lights.light_names.OrderBy(kv => kv.Key).Select(kv => kv.Value).Where(v => !string.IsNullOrEmpty(v)).ToList();
            var modes = Modes.modes.OrderBy(kv => kv.Key).Where(kv => kv.Value != null && kv.Key != PadRuntime.ModeId)
                .Select(kv => kv.Value.name ?? kv.Value.GetType().Name).ToList();
            var cls = Modes.modes.Values.Where(m => m != null && m.mode != PadRuntime.ModeId).Select(m => m.GetType().Name).Distinct().OrderBy(x => x).ToList();
            var b = new StringBuilder("{\n");
            b.Append("  \"engine\": \"unity\",\n");
            b.Append("  \"product\": " + Json(Application.productName) + ",\n");
            b.Append("  \"unity\": " + Json(Application.unityVersion) + ",\n");
            b.Append("  \"game_version\": " + Json(Application.version) + ",\n");
            b.Append("  \"runtime\": " + Json(Loader.Version) + ",\n");
            b.Append("  \"switches\": " + List(sw) + ",\n");
            b.Append("  \"switch_ids\": {" + string.Join(", ", swIds.ToArray()) + "},\n");
            b.Append("  \"switch_labels\": {" + string.Join(", ", swLabels.ToArray()) + "},\n");
            b.Append("  \"lamps\": " + List(lamps) + ",\n");
            b.Append("  \"sounds\": " + List(Callouts().Keys.OrderBy(x => x, StringComparer.Ordinal)) + ",\n");
            b.Append("  \"sound_paths\": {" + string.Join(", ", Callouts().OrderBy(kv => kv.Key, StringComparer.Ordinal)
                .Select(kv => Json(kv.Key) + ": " + Json(kv.Value)).ToArray()) + "},\n");
            b.Append("  \"game_modes\": " + List(modes) + ",\n");
            b.Append("  \"mode_classes\": " + List(cls) + ",\n");
            b.Append("  \"fonts\": " + List(fonts.Keys.OrderBy(x => x, StringComparer.Ordinal)) + ",\n");
            b.Append("  \"score_tags\": " + List(g != null && g.recognized_tags != null ? g.recognized_tags : new List<string>()) + ",\n");
            b.Append("  \"mode_tags\": " + List(g != null && g.mode_tags != null ? g.mode_tags : new List<string>()) + ",\n");
            b.Append("  \"points_scale\": " + scaleSeen + "\n}\n");
            File.WriteAllText(to, b.ToString());
            Loader.Log("port report written to " + to + ": " + sw.Count + " switches, " + lamps.Count + " lamps, " +
                Callouts().Count + " callouts, " + modes.Count + " game modes, " + fonts.Count + " fonts" +
                (scaleSeen > 0 ? ", points scale " + scaleSeen : ", points scale not measured yet"));
            // one callout loads, so the names are the right ones
            var first = Callouts().FirstOrDefault();
            var clip = first.Key == null ? null : Callout(first.Key);
            Loader.Log("callout check: " + first.Key + " -> " + first.Value + " -> " + (clip == null ? "NOT FOUND" : clip.name + " " + clip.length.ToString("0.00") + " s"));
        } catch (Exception e) { Loader.Log("port report: " + e); }
    }

    // The first ball of a game with PADMODES_PORT set: one award of 1,000 through the game's
    // own scoring tells the title's points scale.
    public static void Measure(PadRuntime r) {
        if (measured || string.IsNullOrEmpty(Environment.GetEnvironmentVariable("PADMODES_PORT"))) return;
        measured = true;
        var g = Mode.machine.game;
        long before = g.player().score;
        r.score_points(1000, PadRuntime.Tags);
        long got = g.player().score - before;
        scaleSeen = got / 1000;
        Loader.Log("points scale: score_points(1000, base bonus) scored " + got + " (score_multiplier " + g.score_multiplier + ")");
        WriteIfAsked();
    }
}
}
