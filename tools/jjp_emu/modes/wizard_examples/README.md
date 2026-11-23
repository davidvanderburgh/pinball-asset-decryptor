# Wizard mode examples (PAD-1512)

One folder a JJP title, each with a wizard mode written for that title: `3_wizard.mode` (four of the
game's own modes played, or PAD WIZARD on the attract menu), and for Godfather 02.03
`3_kiss_the_ring.mode` (all 16 of the modes its stained-glass panes stand for, or KISS THE RING on
the menu, with the game's own Kiss the Ring sounds).

These are examples only. They are not starters: the app never copies them into anyone's mode folder,
and nothing in the runtime or the app knows about them. To use one, copy it into your own mode folder
for that title (the Modes tab's **Open the mode folder**) and change it as you like. Every key:
`tools/jjp_emu/MODES.md`, "A wizard mode and a game type".

`jjpport.py --wizard-example <folder>` writes a title's `3_wizard.mode` from its port report.
