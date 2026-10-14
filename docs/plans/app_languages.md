# The app in other languages (PAD-458)

Gear menu › **Language**: English, Español, Deutsch, Français. The choice is
saved (`ui_language` in settings.json) and applies at once, no restart.

## How it works

The page is written in English and translated **where it is shown**, not
where it is written. `static/js/core/i18n.js` watches the page (a
MutationObserver) and looks every text node, and every `placeholder`, up in
the language's catalog, `static/i18n/<lang>.json`, putting the translation
in its place. So the tabs, the labels and messages Python sends, dialogs,
menus, banners and tooltips all follow the language without any of that code
knowing about it, and a new tab or message needs nothing but a catalog entry.

- **Preact owns the text nodes.** When it updates one it writes new English
  over the translation; the observer sees text that is not what it put there
  and translates that. The English of every node is remembered, so switching
  back (or to another language) restores it exactly.
- **Text side by side is looked up joined.** `Saved ${n} files` renders as
  three text nodes; they are looked up as "Saved 12 files", so one sentence
  is one entry.
- **Templates.** A key with `{}` holes matches any run of text in each hole
  (numbers included: the harvester writes every number as a hole, so "MP4"
  is `MP{}`). The translation fills its holes in order, or by number
  (`{1} … {0}`) when the language wants them the other way round. A hole's
  own words are looked up too ("Tips — {}" with a tab name in it).
- **English plurals built from a suffix** (`{} file{}`, `{} cop{}`) cannot be
  translated as a template - the hole would put an English "s" or "ies" into
  the Spanish. The catalogs carry each such key spelled out instead
  (`{} file` / `{} files`, `{} copy` / `{} copies`); the spelled-out entry
  has more words of its own, so it is tried first.
- **The ? window** is laid out by Python (`tips_render.py`), and bold and
  links split its sentences into runs; so Python translates each block whole
  first, with the same lookup (`webui/i18n.py`). Heading anchors stay the
  English headings', so links inside the window still land.
- **Never translated:** anything inside class `notr`: the log (support
  reports read the same in every language), the names of games, projects and
  manufacturers, and the game's own words in the Text and Scenes tables; also
  text fields and `code`. Not `translate="no"`: Preact sets that as the DOM
  property and it comes out "yes". What does not match the catalog stays
  English.
- **Short templates are dropped** ("{} of {}" would turn a game called
  "House of Horrors" into "House de Horrors"): a template needs four letters
  of its own. A hole that catches an English grammar word or plural ending
  ("does", "s") is no match, so the text stays English whole rather than
  half-translated.
- Native file pickers are the operating system's own, already in its
  language; their file-type names are translated (`webui/dialogs.py`).

## The catalogs

`scripts/i18n_extract.py` harvests the strings: the page's JavaScript
(template text and string literals) and the Python behind the tabs (webui/,
app.py, core/) read with `ast`, f-strings and %-formats turned into
templates; the ? window's words a block at a time, as the window looks them
up. About 9,800 strings; each catalog translates about 9,200 of them (the
rest are code, file patterns and names, left out on purpose).

Adding strings later (a new tab, a new message):

    python scripts/i18n_extract.py --missing es > missing.txt   # what es.json lacks
    # translate into <name>.es.json / .de.json / .fr.json ({"English": "..."})
    python scripts/i18n_extract.py --merge <folder>

An untranslated string just shows in English; nothing breaks. Terms follow
one glossary (tab names as on the rail, card / project / slot / replacement
…); Spanish uses tú, German Sie, French vous.

`tests/test_pad458_languages.py` pins the lookup on both sides (the same
cases through Python and the page's own code), the DOM layer in a real
browser, the gear menu's setting, the ? window, and every catalog's holes and
markup.
