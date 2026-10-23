# PAD-664: the rules sheet, made from the Modes tab

David's Heisei card (PAD-658) went to the cabinet with a one-page "Godzilla Custom Modes" sheet written by hand
from the modes' sources. It went stale twice (still 1.96A, 14 modes, old starts and 8-15 s windows after round 3).
He asked for the sheet to be made from the Modes tab instead, so it is always current.

## What it does

**Rules sheet…** under the modes list opens a dialog (`webui/modes_sheet.py`, `static/js/tabs/modes_sheet.js`):

- the sheet as it prints (an HTML preview at the PDF's type size), Letter or A4, landscape;
- every mode with what the sheet says of it: tick to keep it on, arrows to reorder, the pencil to write the
  mode's own words (Start, Stages one a line, Cash out, a Tag); an empty field gives the app's words back;
- the title, the line under it and the foot, each editable the same way;
- **Save as PDF…** and **Save as HTML…**, by default into the project folder;
- **Print…** (PAD-695): the preview page itself prints through the system's print dialog (WebView2, a browser),
  on the paper chosen, landscape; before it prints the page fits its type to one page (`padFitPage()`, as the PDF
  does - Letter put the foot on a second page otherwise). Native windows that cannot print a page (macOS, Qt) open
  the sheet's PDF in the system's viewer instead (`sheet_print`).

Kept in the project: a mode's own words in `modes/<slug>/sheet.json` (they travel with the mode: Save/load, Copy
to and Port copy the whole folder), the sheet's title/line/foot/paper/order/left-off in `modes/rules_sheet.json`.

## Where the words come from (`plugins/stern/rules_sheet.py`)

- **Blocks** are played on the desk (`plugins/stern/blocks_sim.py`: the program's hats and blocks run as its C
  runs them - variables and their resets, timers in ms, the clock or none, Light the mode at, the shots it
  lights). The same start rule is written many ways (a hits count, a counter of its own, a light at a shot, a
  level that climbs, a shared variable another mode sets), so the player does not read patterns: it makes each
  not-running shot until the mode starts (or is lit, then the lit shot), three times over with each run played
  out between, which gives the 1st / 2nd / 3rd counts however the rule is built. Fallbacks in turn: the game's
  next mode of its own (JET JAGUAR "joins the game's next mode"), every shot in turn (EBIRAH's powerlines),
  rounds of the other modes that set its shared variables (SHIN GODZILLA). A split over two balls tells
  "in one ball"; other shots that count more say "counts 2".
  The first run is played by shooting what the mode lights (the shot that does most, never a shot that ends the
  mode early - that one is the Cash out). The stage variable (reset each run, stepped by 1, compared with stage
  numbers; stage/phase/wave/round/part names win) splits it into stages: each stage says the shots made in it,
  its name (the HUD title up longest, else the "NAME:" a HUD line gives it; never an instruction, a count or
  an end title), the clock it set when that differs from the mode's, the balls of a multiball it began, and the
  window for each shot when its HUD line counts one down ("… IN").
- **Form modes** say their fields (start shot and count, start-or/also shots, a sequence, an event; the scoring
  shots, the seconds, the balls).
- **C modes** say their clock (and HUD line); the rest is the person's to write.
- A form mode that is not ready to build is left off and named under the list.

The foot is worked out from the modes: the cash out (when any has one), the clock (one length, or "40 s or
more"), the good-shot top-up (Keep at least N s), one mode at a time (and waiting out the game's own modes when
any waits), shoot what is lit, a drain or tilt ends a mode (when every mode ends on a drain).

## The PDF (`core/pdf_sheet.py`)

No browser and no library: PDF 1.4 with the base-14 Helvetica and Helvetica-Bold (nothing embedded), text
measured with their AFM widths, WinAnsi text (dashes, middle dots, curly quotes; anything else as its plain
letter). The table's type shrinks from 8.6 pt to 5.6 pt until it fits one page, else it runs on over pages with
the head row repeated. The HTML uses the same sizes in Arial (Helvetica's widths), so it prints on one page too.

## Proof

- `tests/test_pad664_rules_sheet.py`: each start kind on the shipped blocks examples, every example worded, the
  desk game, form and C modes, own words / order / left off, the PDF (one page, Letter and A4 boxes, xref,
  text), a long sheet paging, the HTML, the dialog's calls and its whole flow.
- On David's real project (read only): the sheet from his 14 modes carries the hand-made sheet's starts,
  stage counts and Cash out column (`after_rules_sheet_pdf.png` beside his `before_rules_sheet_pdf.png`).
- `scripts/shot_pad664.py`: the served app on a copy of his modes - the button, the dialog, words written in
  the dialog saved to `sheet.json` and on the sheet at once.
