"""PAD-458: the app in Spanish, German and French.

The page translates what it shows (static/js/core/i18n.js) from the
catalogs in static/i18n/; Python does the same lookup (webui/i18n.py) for
the ? window's words.  These pin the lookup on both sides, the DOM layer in
a real browser (Preact writing English over a translation, text split
across nodes, the log left alone, English put back), the gear menu's
Language and its setting, and the shipped catalogs' shape.
"""

import json
import os
import re

import pytest

from pinball_decryptor.webui import i18n
from pinball_decryptor.webui.tips_render import render, plain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "pinball_decryptor", "webui", "static")
I18N_JS = os.path.join(STATIC, "js", "core", "i18n.js")

MAPPING = {
    "Scan": "Escanear",
    "Saved {} files": "{} archivos guardados",
    "{} of {} slots changed": "{0} de {1} ranuras cambiadas",
    "Copy {} to {}": "Copiar a {1} desde {0}",
    "Tips — {}": "Consejos — {}",
    "Audio": "Audio-ES",
    "Click **Scan** to read the card, then see [Write](#write).":
        "Pulsa **Escanear** para leer la tarjeta y mira [Escribir](#write).",
    "Pick a card": "Elige una tarjeta",
    "{}: {}": "never used: no words of its own",
    "{} of {}": "{} de {}",
    "{} slots changed{}": "{} ranuras cambiadas{}",
    "{} file{} replaced": "{} archivo{} reemplazado",
    "{} files replaced": "{} archivos reemplazados",
    "This scene {} not start with a picture.": "Esta escena no empieza con una imagen.",
    "{} changed": "{} cambiado",
    "{} of {} rows changed{}": "{0} de {1} filas cambiadas{2}",
    "{} mode{}{}": "{} modo{}{}",
    "The {} tab": "La pestaña {}",
    "Nothing in {} yet, so {} is idle.": "Nada en {} aún, así que {} está inactiva.",
    "{} file(s) — {}": "{} archivo(s) — {}",
    "The folder is new.": "La carpeta es nueva.",
}

#: (text, what the lookup gives) through Python and the page alike
CASES = [
    ("Scan", "Escanear"),
    ("Saved 12 files", "12 archivos guardados"),
    ("69 of 69 slots changed", "69 de 69 ranuras cambiadas"),
    ("Copy a to b", "Copiar a b desde a"),
    ("Tips — Audio", "Consejos — Audio-ES"),
    ("Not in the catalog", None),
    ("a: b", None),
    ("Elvira's House of Horrors", None),
    ("3 slots changed", "3 ranuras cambiadas"),
    ("2 files replaced", "2 archivos reemplazados"),
    ("1 file replaced", "1 archivo reemplazado"),
    ("This scene does not start with a picture.", None),
    # the most specific template wins, whichever bucket it is in
    ("69 of 70 rows changed", "69 de 70 filas cambiadas"),
    # a path is never translated, nor a word inside it
    (r"C:\Users\me\heisei modes\proj", None),
    ("/home/me/heisei modes", None),
    ("heisei modes", None),           # open at both ends, one word of its own
    # open at both ends, but with a shape of its own
    ("69 file(s) — 40.2 MB", "69 archivo(s) — 40.2 MB"),
    # sentences put together: each known, or the whole stays English
    ("The folder is new. Saved 3 files", "La carpeta es nueva. 3 archivos guardados"),
    ("The folder is new. Something else.", None),
    # pieces set side by side: the known ones translated, the rest kept
    ("Saved 6 files · .pkg", "6 archivos guardados · .pkg"),
    ("Odd · .pkg", None),
    # a hole's own words, by a template, with its first letter as it was
    ("Nothing in proj yet, so the Audio tab is idle.",
     "Nada en proj aún, así que la pestaña Audio-ES está inactiva."),
]


# ------------------------------------------------------------ the lookup
def test_exact_and_template_lookups():
    c = i18n.Catalog(MAPPING)
    assert c.tr("Scan") == "Escanear"
    assert c.tr("  Scan ") == "Escanear"            # blanks count loosely
    assert c.tr("Saved 12 files") == "12 archivos guardados"
    assert c.tr("Saved my.wav files") == "my.wav archivos guardados"
    assert c.tr("69 of 69 slots changed") == "69 de 69 ranuras cambiadas"
    assert c.tr("Copy a to b") == "Copiar a b desde a"   # numbered holes reorder
    assert c.tr("Tips — Audio") == "Consejos — Audio-ES"  # a hole's own words looked up
    assert c.tr("Not in the catalog") == "Not in the catalog"
    assert c.lookup("a: b") is None                      # a key with no words is dropped
    # too few words of its own: a game called "House of Horrors" stays itself
    assert c.lookup("Elvira's House of Horrors") is None
    assert c.tr("3 slots changed") == "3 ranuras cambiadas"   # a hole may be empty
    # an English plural ending or grammar word in a hole is no match: the
    # spelled-out entry wins, or the text stays English whole
    assert c.tr("2 files replaced") == "2 archivos reemplazados"
    assert c.tr("1 file replaced") == "1 archivo reemplazado"
    assert c.lookup("This scene does not start with a picture.") is None


def test_the_lookup_cases():
    c = i18n.Catalog(MAPPING)
    assert [(t, c.lookup(t)) for t, _ in CASES] == CASES


def test_english_is_the_identity_and_unknown_codes_are_english():
    assert i18n.language("ES") == "es"
    assert i18n.language("xx") == "en"
    assert i18n.language(None) == "en"
    assert i18n.translator("en")("Scan") == "Scan"
    assert i18n.catalog("en") is None


def test_the_tips_window_translates_a_block_whole():
    """Bold and links would split a sentence into runs: the block is looked up
    before that, and the anchor stays the English heading's."""
    c = i18n.Catalog(MAPPING)
    body = "Click **Scan** to read\nthe card, then see [Write](#write).\n\n### Pick a card"
    blocks = render(body, tr=c.tr)
    assert blocks[0]["r"] == [["t", "Pulsa "], ["b", "Escanear"],
                              ["t", " para leer la tarjeta y mira "],
                              ["a", "Escribir", "write"], ["t", "."]]
    assert blocks[1]["t"] == "h" and blocks[1]["id"] == "pick-a-card"
    assert plain([blocks[1]]) == "Elige una tarjeta"
    # and with no translator it is exactly what it always was
    assert render(body) == render(body, tr=None)
    assert "\n" in plain(render(body))


# --------------------------------------------------------- the catalogs
HOLE = re.compile(r"\{(\d*)\}")


@pytest.mark.parametrize("code", ["es", "de", "fr"])
def test_each_catalog_is_whole_and_well_formed(code):
    path = os.path.join(i18n.CATALOG_DIR, code + ".json")
    with open(path, encoding="utf-8") as f:
        cat = json.load(f)
    assert len(cat) > 5000, len(cat)
    for k, v in cat.items():
        holes = HOLE.findall(v)
        assert len(holes) == k.count("{}"), (k, v)
        nums = [h for h in holes if h]
        if nums:
            assert sorted(int(h) for h in nums) == list(range(len(holes))), (k, v)
        assert k.count("**") == v.count("**"), (k, v)
    c = i18n.catalog(code)
    # the gear menu, the rail and the tab names are all there
    for word in ("Language", "Appearance", "Extract", "Audio", "Write", "Scenes",
                 "Settings", "Cancel", "Scan"):
        assert c.lookup(word) is not None, (code, word)


def test_the_page_and_python_offer_the_same_languages():
    assert list(i18n.CODES) == ["en", "en-gb", "es", "de", "fr"]
    assert [lang[2] for lang in i18n.LANGUAGES] == ["EN-US", "EN-GB", "ES", "DE", "FR"]
    for code in i18n.CODES[1:]:
        assert os.path.isfile(os.path.join(i18n.CATALOG_DIR, code + ".json"))
    assert i18n.language("en-GB") == i18n.language("en_gb") == "en-gb"


# ------------------------------------------------------------- English
def _harvester():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import i18n_extract
    return i18n_extract


_SEEN = []


def _harvest():
    """Every string the page can show (scripts/i18n_extract.py), read once."""
    if not _SEEN:
        _SEEN.append(_harvester().harvest())
    return _SEEN[0]


def test_english_uk_is_the_same_words_spelled_the_british_way():
    X = _harvester()
    with open(os.path.join(i18n.CATALOG_DIR, "en-gb.json"), encoding="utf-8") as f:
        cat = json.load(f)
    assert len(cat) > 400
    for k, v in cat.items():
        assert v == X.british(k) and v != k, (k, v)
    c = i18n.catalog("en-gb")
    assert c.tr("Color profile") == "Colour profile"
    assert c.tr("Dark gray") == "Dark grey"
    assert c.tr("Canceled") == "Cancelled"
    assert c.tr("Scan") == "Scan"                       # the same in both: left alone
    # and the words that depend on their sense stay as the app writes them
    assert X.british("the game program's license meter") == "the game program's license meter"
    assert X.british("Recognized, unrecognized, normalizing") == "Recognised, unrecognised, normalising"


def test_the_apps_english_is_american_throughout():
    """The app writes American English (PAD-458): a British spelling in what
    the page shows would read wrong next to the rest, and English (UK) is made
    from the American words."""
    X = _harvester()
    seen = _harvest()
    british = {k: X.british_words(k) for k in seen if X.british_words(k)}
    assert not british, list(british.items())[:10]


def test_english_uk_covers_every_american_spelling():
    """A string added later with "color" in it needs `--british` run again,
    or English (UK) shows it the American way."""
    X = _harvester()
    with open(os.path.join(i18n.CATALOG_DIR, "en-gb.json"), encoding="utf-8") as f:
        cat = json.load(f)
    missing = [k for k in _harvest() if X.british(k) != k and k not in cat]
    assert not missing, ("run python scripts/i18n_extract.py --british", missing[:10])


# ------------------------------------------------------- the gear menu
def test_set_language_is_published_and_saved(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path) as w:
        sh = w.state("shell")
        assert sh["lang"] == "en"
        assert [x[0] for x in sh["languages"]] == ["en", "en-gb", "es", "de", "fr"]
        w.call("ui.set_language", "de")
        w.drain()
        assert w.state("shell")["lang"] == "de"
        assert w.app._settings["ui_language"] == "de"
        w.call("ui.set_language", "klingon")
        w.drain()
        assert w.state("shell")["lang"] == "en"
    # the next start opens in the saved language
    with web_app(tmp_path, settings={"ui_language": "fr"}) as w:
        assert w.state("shell")["lang"] == "fr"


def test_the_tips_window_follows_the_language(tmp_path):
    from tests.webui_harness import web_app
    with web_app(tmp_path) as w:
        en = w.call("shellx.tips", "Extract")
        w.call("ui.set_language", "es")
        w.drain()
        es = w.call("shellx.tips", "Extract")
    assert en["title"] == "Tips — Extract"
    assert es["title"] != en["title"] and "Extra" in es["title"]
    assert [s[2] for s in es["sections"]] == [s[2] for s in en["sections"]]   # anchors kept
    assert [s[0] for s in es["sections"]] != [s[0] for s in en["sections"]]


def test_the_page_wires_it():
    with open(os.path.join(STATIC, "js", "shell.js"), encoding="utf-8") as f:
        shell = f.read()
    assert 'setLanguage(shell.lang || "en")' in shell
    assert 'call("ui.set_language", code)' in shell
    # the top bar's own language button (a globe and the code), on every view,
    # marked with a dot until first opened; the gear menu keeps its submenu
    assert '<${LangBtn} shell=${shell} />' in shell
    assert '<${Icon} name="globe" />' in shell and 'pad.lang.seen' in shell
    assert '{ label: "Language", submenu: languageItems(shell) }' in shell
    with open(os.path.join(STATIC, "js", "core", "ui.js"), encoding="utf-8") as f:
        assert "  globe: " in f.read()
    assert '<div class="lines notr"' in shell                   # the log stays English
    # Preact sets translate="no" as the DOM property (it comes out "yes"):
    # the page marks what it never translates with the class instead
    assert 'translate=' not in shell


# ------------------------------------------------- the page, in a browser
_PAGE = """
async ([src, mapping, cases]) => {
  const mod = await import("data:text/javascript;base64," + btoa(unescape(encodeURIComponent(src))));
  const tick = () => new Promise((r) => setTimeout(r, 30));
  document.body.innerHTML = `
    <div id="a">Scan</div>
    <div id="b"></div>
    <div id="log" translate="no"><div class="line">Scan</div></div>
    <input id="i" placeholder="Pick a card">
    <div id="multi">Scan\\nPick a card</div>
    <div id="mixed">Scan <b>Audio</b> Scan</div>`;
  const b = document.getElementById("b");
  for (const t of ["Saved ", "12", " files"]) b.appendChild(document.createTextNode(t));
  const out = {};
  await mod.setLanguage("es", mapping);
  await tick();
  const txt = (id) => document.getElementById(id).textContent;
  out.a = txt("a"); out.b = txt("b"); out.log = txt("log");
  out.ph = document.getElementById("i").placeholder;
  out.multi = txt("multi"); out.mixed = txt("mixed");
  out.lang = document.documentElement.lang;
  // Preact writes new English over a translation
  document.getElementById("a").firstChild.data = "Pick a card";
  b.childNodes[1].data = "7";
  await tick();
  out.a2 = txt("a"); out.b2 = txt("b");
  // a node the page adds later
  const d = document.createElement("div"); d.id = "late"; d.textContent = "Saved 3 files";
  document.body.appendChild(d);
  document.getElementById("i").setAttribute("placeholder", "Scan");
  await tick();
  out.late = txt("late"); out.ph2 = document.getElementById("i").placeholder;
  // back to English: every word as the page wrote it
  await mod.setLanguage("en");
  await tick();
  out.en = [txt("a"), txt("b"), txt("late"), document.getElementById("i").placeholder,
            txt("multi"), txt("mixed"), document.documentElement.lang];
  // and the parity cases through the page's own lookup
  const c = mod.compile(mapping);
  out.parity = cases.map((s) => mod.lookup(c, s));
  return out;
}
"""


_PREACT = """
async ([src, preact, mapping]) => {
  const imp = (code) => import("data:text/javascript;base64," + btoa(unescape(encodeURIComponent(code))));
  const mod = await imp(src);
  const { html, render, useState } = await imp(preact);
  const tick = () => new Promise((r) => setTimeout(r, 30));
  let setN = null;
  function App() {
    const [n, set] = useState(12);
    setN = set;
    return html`<div><p id="saved">Saved ${n} files</p>
      <p id="game" class="notr">Scan</p><p id="label">${n > 20 ? "Pick a card" : "Scan"}</p></div>`;
  }
  document.body.innerHTML = '<div id="root"></div>';
  render(html`<${App} />`, document.getElementById("root"));
  await mod.setLanguage("es", mapping);
  await tick();
  const txt = (id) => document.getElementById(id).textContent;
  const out = { first: [txt("saved"), txt("game"), txt("label")] };
  setN(40);
  await tick();
  out.after = [txt("saved"), txt("game"), txt("label")];
  await mod.setLanguage("en");
  await tick();
  out.en = [txt("saved"), txt("label")];
  setN(41);
  await tick();
  out.en2 = [txt("saved"), txt("label")];
  return out;
}
"""


def _browser_page():
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:                              # noqa: BLE001
        pytest.skip("no playwright: %s" % e)
    browser = None
    for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            browser = pw.chromium.launch(**kw)
            break
        except Exception:                               # noqa: BLE001
            continue
    if browser is None:
        pw.stop()
        pytest.skip("no browser")
    page = browser.new_page()
    page.set_content("<html><body></body></html>")
    return pw, browser, page


def test_preact_writing_over_a_translation_is_translated_again():
    """The app's own Preact re-renders a translated text node with new
    English: the page translates that too, and English comes back whole."""
    with open(I18N_JS, encoding="utf-8") as f:
        src = f.read()
    with open(os.path.join(STATIC, "js", "vendor", "preact-htm.js"), encoding="utf-8") as f:
        preact = f.read()
    pw, browser, page = _browser_page()
    try:
        out = page.evaluate(_PREACT, [src, preact, MAPPING])
    finally:
        browser.close()
        pw.stop()
    assert out["first"] == ["12 archivos guardados", "Scan", "Escanear"]
    assert out["after"] == ["40 archivos guardados", "Scan", "Elige una tarjeta"]
    assert out["en"] == ["Saved 40 files", "Pick a card"]
    assert out["en2"] == ["Saved 41 files", "Pick a card"]


def test_the_page_translates_what_it_shows_in_a_real_browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with open(I18N_JS, encoding="utf-8") as f:
        src = f.read()
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:                              # noqa: BLE001
        pytest.skip("no playwright: %s" % e)
    try:
        browser = None
        for kw in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
            try:
                browser = pw.chromium.launch(**kw)
                break
            except Exception:                           # noqa: BLE001
                continue
        if browser is None:
            pytest.skip("no browser")
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        out = page.evaluate(_PAGE, [src, MAPPING, [t for t, _ in CASES]])
        browser.close()
    finally:
        pw.stop()
    assert out["a"] == "Escanear"
    assert out["b"] == "12 archivos guardados"          # three nodes looked up joined
    assert out["log"] == "Scan"                         # translate="no": the log
    assert out["ph"] == "Elige una tarjeta"
    assert out["multi"] == "Escanear\nElige una tarjeta"
    assert out["mixed"] == "Escanear Audio-ES Escanear"
    assert out["lang"] == "es"
    assert out["a2"] == "Elige una tarjeta"
    assert out["b2"] == "7 archivos guardados"
    assert out["late"] == "3 archivos guardados"
    assert out["ph2"] == "Escanear"
    assert out["en"] == ["Pick a card", "Saved 7 files", "Saved 3 files", "Scan",
                         "Scan\nPick a card", "Scan Audio Scan", "en"]
    assert out["parity"] == [want for _, want in CASES]
