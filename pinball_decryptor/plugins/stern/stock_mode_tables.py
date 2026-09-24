"""The stock-mode tables the app knows (item 145), in item 144's table grammar.

Each block describes ONE game program (its sha1), so a card is matched to its table by its
bytes, not by a file name. The grammar and what every token means are in MODE_SDK.md ("The
game's own modes"); :mod:`.stock_modes` reads it.

THE ROWS ARE ITEM 144'S, verbatim: the fenced ``stock-modes`` blocks of its
``plans/spike2_stock_modes_godzilla.md`` (2026-09-17 03:06, the survey of Godzilla Pro 1.15 and
Premium/LE 1.16 by ``tools/spike2_emu/modes/sdk/stock_modes.py``, live values folded in from its
Run A: ``seen runA`` = the same value at the same call site in that run's ``padmode.log``).
Regenerate this file from a newer table rather than editing rows by hand; the real-ELF test in
``tests/test_stern_stock_modes.py`` checks every word row against the game programs.

ITEM 159 (2026-09-23) ADDS, by hand at the end of each block: the tank path family (``path``,
``qword`` and the ``follows path`` rows) and ebirah's per-spinner spin counts (``insn``), and marks
the ``initial_mask`` rows of eight modes ``inert`` (item 158 measured two, the desk audit of
item 159 read the rest: their own start stores the lit mask again). See MODE_SDK.md, "Stock mode
shots as data (item 159)".

A number can only be changed in place when it is ONE word the code loads (class ``word``) or an
operator adjustment; ``code`` rows are listed so the Modes tab can say why they stay read-only.
Source sha1 of the blocks: 9dcdfa8b1189a258af77b024df12c4dde5c08cf4
"""

TABLE = """
build godzilla_pro 1.15 sha1 08d502998706d327bfbb6ea5f92ac0cee76be63b
# read by stock_modes.py: cmode_manager constructor 0xd27d4, 26 mode objects

mode 1 cmode_godzilla_multiball obj 0x7a18a8 vtable 0x629b98 title_msg 3235
ctor 1 a 1 award 10 b 2 timer -   # cmode_mball, ctor 0xafde0 called at 0xd325c; compared against cmode_mball_null, 63 virtuals
shots 1 0x0 v[44] 0xaecb0, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 1 initial_mask.lo 0 imm 0xaecb0 e3a00000 word inert start_rewrites  # v[44] returns it (0x0)
number 1 initial_mask.hi 0 imm 0xaecb4 e3a01000 word inert start_rewrites  # v[44] returns it (0x0)
number 1 title_msg 3235 movw 0x475f4 e3000ca3 word
number 1 audit_started 211 imm 0xb3d34 e3a000d3 word
number 1 audit_completed 212 imm 0xb3d3c e3a000d4 word
start 1 start: cmode_manager_get(1) at 0x12ee2c then v[8], in RuleBuildingLocks::v[25]
# 26 other cmode_manager_get(1) sites read it (is_running, is_active, or a slot not traced)
number 1 reset.adjustment 0 adj AD_GODZILLA_MULTIBALL_MUSIC_DEFAULT 201 e3a000c9 adjustment  # v[3] call 0xaed90; the id is imm 0xaed88, range 0..7
number 1 start.caward_add 500000 movwt 0xb16fc 0xb1704 e30a2120,e3402007 word  # v[8] call 0xb171c
number 1 start.game_event.id 13 imm 0xb1740 e3a0000d word  # v[8] call 0xb174c
number 1 end.game_event.id 17 imm 0xaf3c0 e3a00011 word  # v[10] call 0xaf3c4
number 1 shot.show_start.id 174 imm 0xb0f4c e3a000ae word  # v[41] call 0xb0f64
number 1 shot.event_post_replacing.id 340 imm 0xb12b4 e3a00f55 word  # v[41] call 0xb12c4
number 1 total_display.event_post_replacing.id 238 imm 0xaf178 e3a000ee word  # v[43] call 0xaf184
clip 1 godzilla_multiball_total movwt 0xaf1dc 0xaf1e4 e3093fcc,e3403062  # v[43] at 0xaf1e4: a name total_display loads
# display layers: BDLGodzillaMultiballBG BDLGodzillaMultiballStart

mode 2 cmode_mechagodzilla_multiball obj 0x7a1968 vtable 0x62caf0 title_msg 3234
ctor 2 a 1 award 11 b 3 timer -   # cmode_mball, ctor 0xd6864 called at 0xd320c; compared against cmode_mball_null, 63 virtuals
shots 2 0x0 v[44] 0xd53dc, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 2 initial_mask.lo 0 imm 0xd53dc e3a00000 word  # v[44] returns it (0x0)
number 2 initial_mask.hi 0 imm 0xd53e0 e3a01000 word  # v[44] returns it (0x0)
number 2 title_msg 3234 movw 0x475fc e3000ca2 word
number 2 audit_started 209 imm 0xdab28 e3a000d1 word
number 2 audit_completed 210 imm 0xdab30 e3a000d2 word
start 2 start: cmode_manager_get(2) at 0x15d204 then v[8], in RuleMechagodzillaShield::v[25]
# 24 other cmode_manager_get(2) sites read it (is_running, is_active, or a slot not traced)
number 2 end.game_event.id 49 imm 0xd597c e3a00031 word  # v[10] call 0xd5980
number 2 total_display.event_post_replacing.id 239 imm 0xd5824 e3a000ef word  # v[43] call 0xd5830
clip 2 mecha_missile_groundblowsup movwt 0xd5888 0xd5890 e30c3e58,e3403062  # v[43] at 0xd5890: a name total_display loads
clip 2 mecha_magnazilla2 movwt 0xdab5c 0xdab60 e30c0e30,e3400062  # BDLMechaGodzillaMultiballSuperJackpotLit::v[15] at 0xdab60: a name the display layer loads
# display layers: BDLMechaGodzillaMultiballSuperJackpotLit BDLMechagodzillaMultiballBG BDLMechagodzillaMultiballStart

mode 3 cmode_bridge_attack_multiball obj 0x7a1a08 vtable 0x6295d8 title_msg 3239
ctor 3 a 1 award 12 b 4 timer -   # cmode_mball, ctor 0xaa0ec called at 0xd31bc; compared against cmode_mball_null, 63 virtuals
shots 3 ? v[44] 0xa8ec8 returns the object's field +0x60: set by other code, not measured
number 3 title_msg 3239 movw 0xae064 e3000ca7 word
number 3 audit_started 215 imm 0xae06c e3a000d7 word
number 3 audit_completed 216 imm 0xae074 e3a000d8 word
start 3 start: cmode_manager_get(3) at 0x130cb4 then v[8], in fn 0x130c30
# 17 other cmode_manager_get(3) sites read it (is_running, is_active, or a slot not traced)
number 3 start.adjustment 0 adj AD_BRIDGE_ATTACK_MULTIBALL_DIFFICULTY 207 e3a000cf adjustment  # v[8] call 0xaa5c4; the id is imm 0xaa5ac, range 0..3
number 3 start.caward_add 250000 movwt 0xaa5d0 0xaa5d4 e30d2090,e3402003 word  # v[8] call 0xaa600
number 3 start.game_event.id 63 imm 0xaa654 e3a0003f word  # v[8] call 0xaa660
number 3 end.game_event.id 65 imm 0xa8f98 e3a00041 word  # v[10] call 0xa8f9c
number 3 total_display.event_post_replacing.id 254 imm 0xa9084 e3a000fe word  # v[43] call 0xa9090
clip 3 BridgeDestructionProgress_3 movwt 0xa90dc 0xa90e4 e3043da8,e3403062  # v[43] at 0xa90e4: a name total_display loads
# display layers: BDLBridgeAttackMultiballBG

mode 4 cmode_tank_attack_multiball obj 0x7a1b20 vtable 0x6300f8 title_msg 3240
ctor 4 a 1 award 13 b 5 timer -   # cmode_mball, ctor 0x10712c called at 0xd316c; compared against cmode_mball_null, 64 virtuals
shots 4 0x5800700800 v[44] 0x7d1e0, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 4 initial_mask.lo 7342080 movwt 0x7d1e0 0x7d1e8 e3a00b02,e3400070 word inert inline_copy  # v[44] returns it (0x700800) (the low word is a mov)
number 4 initial_mask.hi 88 imm 0x7d1e4 e3a01058 word inert inline_copy  # v[44] returns it (0x58)
number 4 title_msg 3240 movw 0x10b40c e3000ca8 word
number 4 audit_started 217 imm 0x10b414 e3a000d9 word
number 4 audit_completed 218 imm 0x10b41c e3a000da word
start 4 start: cmode_manager_get(4) at 0x17e1e0 then v[8], in fn 0x17e128
# 12 other cmode_manager_get(4) sites read it (is_running, is_active, or a slot not traced)
number 4 start.caward_add 250000 movwt 0x107588 0x107590 e30d2090,e3402003 word  # v[8] call 0x1075a0
number 4 start.game_event.id 50 imm 0x1075f4 e3a00032 word  # v[8] call 0x107600
number 4 end.game_event.id 52 imm 0x10772c e3a00034 word  # v[10] call 0x107730
number 4 shot.game_event.id 51 imm 0x10796c e3a00033 word  # v[41] call 0x107970
number 4 shot.caward_add ? code 0x107a04 - code  # v[41]: the value is computed before the call
number 4 shot.show_start.id 144 imm 0x107a60 e3a00090 word  # v[41] call 0x107a64
number 4 total_display.event_post_replacing.id 241 imm 0x105630 e3a000f1 word  # v[43] call 0x10563c
# display layers: BDLTankAttackMultiballBG BDLTankAttackMultiballStart

mode 5 cmode_saucer_attack_multiball obj 0x7a1be8 vtable 0x62f468 title_msg 3241
ctor 5 a 17 award 14 b 6 timer -   # cmode_mball, ctor 0xfc298 called at 0xd311c; compared against cmode_mball_null, 63 virtuals
shots 5 0x0 v[44] 0xfb2f8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 5 initial_mask.lo 0 imm 0xfb2f8 e3a00000 word  # v[44] returns it (0x0)
number 5 initial_mask.hi 0 imm 0xfb2fc e3a01000 word  # v[44] returns it (0x0)
number 5 title_msg 3241 movw 0x10001c e3000ca9 word
number 5 audit_started 219 imm 0x100024 e3a000db word
number 5 audit_completed 220 imm 0x10002c e3a000dc word
start 5 start: cmode_manager_get(5) at 0x59bc0 then v[8], in fn 0x595b8
start 5 start: cmode_manager_get(5) at 0x1718bc then v[8], in RuleSaucerAttack::v[25]
# 10 other cmode_manager_get(5) sites read it (is_running, is_active, or a slot not traced)
number 5 start.event_post_replacing.id 341 movw 0xfc6f0 e3000155 word  # v[8] call 0xfc6fc
number 5 start.caward_add 250000 movwt 0xfc704 0xfc714 e30d2090,e3402003 word  # v[8] call 0xfc718
number 5 start.game_event.id 68 imm 0xfc764 e3a00044 word  # v[8] call 0xfc774
number 5 end.game_event.id 70 imm 0xfb40c e3a00046 word  # v[10] call 0xfb410
number 5 total_display.event_post_replacing.id 253 imm 0xfb8d4 e3a000fd word  # v[43] call 0xfb8e0
clip 5 saucer_still movwt 0xfb92c 0xfb934 e3043b88,e3403062  # v[43] at 0xfb934: a name total_display loads
# display layers: BDLSaucerAttackMultiballBG

mode 6 cmode_battle_vs_megalon_and_gigan_mb obj 0x7a1d08 vtable 0x6286a8 title_msg 3263
ctor 6 a 25 award 15 b 7 timer -   # cmode_mball, ctor 0x9e7a0 called at 0xd30cc; compared against cmode_mball_null, 63 virtuals
shots 6 0x0 v[44] 0x9d9ac, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 6 initial_mask.lo 0 imm 0x9d9ac e3a00000 word  # v[44] returns it (0x0)
number 6 initial_mask.hi 0 imm 0x9d9b0 e3a01000 word  # v[44] returns it (0x0)
start 6 select: slot 5 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 6 select.slot5.mode_id 6 data 0x631f84 00000006 word  # which mode the selector's slot 5 starts
number 6 title_msg 3263 movw 0xa1480 e3000cbf word
number 6 audit_started 259 movw 0xa1488 e3000103 word
number 6 audit_completed 260 imm 0xa1490 e3a00f41 word
# 14 other cmode_manager_get(6) sites read it (is_running, is_active, or a slot not traced)
number 6 start.caward_add 250000 movwt 0x9e994 0x9e9a0 e30d2090,e3402003 word  # v[8] call 0x9e9ac
number 6 start.game_event.id 39 imm 0x9e9dc e3a00027 word  # v[8] call 0x9e9e0
number 6 end.game_event.id 42 imm 0x9da84 e3a0002a word  # v[10] call 0x9da88
number 6 end.game_event.id@2 40 imm 0x9daf0 e3a00028 word  # v[10] call 0x9daf4
number 6 end.game_event.id@3 41 imm 0x9db28 e3a00029 word  # v[10] call 0x9db2c
number 6 total_display.event_post_replacing.id 247 imm 0x9dca4 e3a000f7 word  # v[43] call 0x9dcb0
clip 6 Megalon_gigan_jetjag_godzilla11 movwt 0x9dcfc 0x9dd04 e3083c08,e3403062  # v[43] at 0x9dd04: a name total_display loads
clip 6 Megalon_gigan_highfive movwt 0xa14bc 0xa14c0 e3080bd0,e3400062  # BDLBattleVsMegalonAndGiganMBStart::v[15] at 0xa14c0: a name the display layer loads
clip 6 Megalon_gigan_jetjag_godzilla4 movwt 0xa14d0 0xa14d4 e3080be8,e3400062  # BDLBattleVsMegalonAndGiganMBSuperJackpotLit::v[15] at 0xa14d4: a name the display layer loads
# display layers: BDLBattleVsMegalonAndGiganMBStart BDLBattleVsMegalonAndGiganMBSuperJackpotLit BDLBattleVsMegalonAndGiganMB_BG

mode 7 cmode_planet_x_multiball obj 0x7a1d98 vtable 0x62ebb0 title_msg 3267
ctor 7 a 17 award 16 b 13 timer -   # cmode_mball, ctor 0xf3fb0 called at 0xd307c; compared against cmode_mball_null, 64 virtuals
shots 7 0x0 v[44] 0xf253c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 7 initial_mask.lo 0 imm 0xf253c e3a00000 word inert start_rewrites  # v[44] returns it (0x0)
number 7 initial_mask.hi 0 imm 0xf2540 e3a01000 word inert start_rewrites  # v[44] returns it (0x0)
number 7 title_msg 3267 movw 0xf9f58 e3000cc3 word
number 7 audit_started 221 imm 0xf9f60 e3a000dd word
number 7 audit_completed 222 imm 0xf9f68 e3a000de word
start 7 start: cmode_manager_get(7) at 0x59c10 then v[8], in fn 0x595b8
# 31 other cmode_manager_get(7) sites read it (is_running, is_active, or a slot not traced)
number 7 total_display.event_post_replacing.id 257 movw 0xf2a9c e3000101 word  # v[43] call 0xf2aa8
clip 7 planetx_outtro movwt 0xf2af4 0xf2afc e30f1160,e3401062  # v[43] at 0xf2afc: a name total_display loads
number 7 v63.caward_add 250000 movwt 0xf6e84 0xf6e90 e30d2090,e3402003 word  # v[63] new call 0xf6eac
number 7 v63.event_post_replacing.id 343 movw 0xf6ee4 e3000157 word  # v[63] new call 0xf6ee8
number 7 v63.game_event.id 75 imm 0xf6efc e3a0004b word  # v[63] new call 0xf6f00
clip 7 PlanetX_Normal_Loop movwt 0xf2580 0xf2584 13010474,13400062  # BDLPlanetXMultiballBG::v[14] at 0xf2584: a name the display layer loads
# display layers: BDLPlanetXMultiballBG BDLPlanetXMultiballStart

mode 8 cmode_monster_zero_victory_multiball obj 0x7a1e20 vtable 0x62dd98 title_msg 3270
ctor 8 a 17 award 17 b 14 timer -   # cmode_mball, ctor 0xe8b9c called at 0xd302c; compared against cmode_mball_null, 63 virtuals
shots 8 ? v[44] 0xeef74 computes the lit mask: code
number 8 title_msg 3270 movw 0xee1b0 e3000cc6 word
number 8 audit_started 225 imm 0xee1b8 e3a000e1 word
number 8 audit_completed 226 imm 0xee1c0 e3a000e2 word
start 8 start: cmode_manager_get(8) at 0xe7f34 then v[8], in fn 0xe7e98
# 14 other cmode_manager_get(8) sites read it (is_running, is_active, or a slot not traced)
number 8 start.game_event.id 125 imm 0xea3b8 e3a0007d word  # v[8] call 0xea3c4
number 8 end.game_event.id 126 imm 0xe53d8 e3a0007e word  # v[10] call 0xe53dc
number 8 shot.game_event.id 123 imm 0xe9a80 e3a0007b word  # v[41] call 0xe9a84
callout 8 1044 shot.callout_play movw 0xe9aa0 e3000414  # v[41] call 0xe9aa8

mode 9 cmode_terror_of_mechagodzilla obj 0x7a1e88 vtable 0x631078 title_msg 3271
ctor 9 a 17 award 18 b 15 timer -   # cmode_mball, ctor 0x11617c called at 0xd2fdc; compared against cmode_mball_null, 65 virtuals
shots 9 0x0 v[44] 0x119c38, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 9 initial_mask.lo 0 imm 0x119c38 e3a00000 word  # v[44] returns it (0x0)
number 9 initial_mask.hi 0 imm 0x119c3c e3a01000 word  # v[44] returns it (0x0)
number 9 title_msg 3271 movw 0x119c00 e3000cc7 word
number 9 audit_started 227 imm 0x119c08 e3a000e3 word
number 9 audit_completed 228 imm 0x119c10 e3a000e4 word
start 9 start: cmode_manager_get(9) at 0x1570b4 then v[8], in RuleKingOfTheMonsters::v[25]
# 25 other cmode_manager_get(9) sites read it (is_running, is_active, or a slot not traced)
number 9 start.caward_add 250000 movwt 0x1144ac 0x1144bc e30d2090,e3402003 word  # v[8] call 0x1144c4
number 9 start.event_post_replacing.id 344 imm 0x1144d0 e3a00f56 word  # v[8] call 0x1144d8
number 9 start.game_event.id 118 imm 0x114520 e3a00076 word  # v[8] call 0x114528
number 9 end.game_event.id 120 imm 0x110b90 e3a00078 word  # v[10] call 0x110b94
number 9 end.game_event.id@2 119 imm 0x110bc8 e3a00077 word  # v[10] call 0x110bcc
number 9 shot.fx.n 200 imm 0x11638c e3a000c8 word  # v[41] call 0x116390
number 9 shot.show_start.id 145 imm 0x116394 e3a00091 word  # v[41] call 0x116398
number 9 shot.show_start.id@2 348 imm 0x1163b0 e3a00f57 word  # v[41] call 0x1163b4
number 9 shot.show_start.id@3 342 movw 0x1163f8 e3000156 word  # v[41] call 0x1163fc
number 9 shot.show_start.id@4 359 movw 0x116460 e3000167 word  # v[41] call 0x116464
callout 9 403 shot.sound_request_play movw 0x11668c e3000193  # v[41] call 0x116690
number 9 shot.fx.n@2 200 imm 0x11669c e3a000c8 word  # v[41] call 0x1166a0
number 9 shot.show_start.id@5 145 imm 0x1166a4 e3a00091 word  # v[41] call 0x1166a8
number 9 shot.show_start.id@6 348 imm 0x1166c0 e3a00f57 word  # v[41] call 0x1166c4
number 9 shot.show_start.id@7 342 movw 0x116708 e3000156 word  # v[41] call 0x11670c
callout 9 1343 shot.callout_play movw 0x1167a8 e300053f  # v[41] call 0x1167ac
callout 9 1341 shot.callout_play@2 movw 0x1169ec e300053d  # v[41] call 0x1169f0
callout 9 402 shot.sound_request_play@2 movw 0x116ab0 e3000192  # v[41] call 0x116ab4
number 9 shot.fx.n@3 200 imm 0x116ac0 e3a000c8 word  # v[41] call 0x116ac4
callout 9 1343 shot.callout_play@3 movw 0x116c88 e300053f  # v[41] call 0x116c90
number 9 total_display.event_post_replacing.id 259 movw 0x110f2c e3000103 word  # v[43] call 0x110f38
clip 9 terror_outtro movwt 0x110f84 0x110f90 e3012280,e3402063  # v[43] at 0x110f90: a name total_display loads
callout 9 272 v63.sound_request_play imm 0x11462c 13a00e11  # v[63] new call 0x114630 (set by a conditional instruction)
callout 9 1330 v63.callout_play movw 0x114658 e3000532  # v[63] new call 0x114660
callout 9 359 v63.sound_request_play@2 movw 0x114678 e3000167  # v[63] new call 0x114680
callout 9 1328 v63.callout_play@2 imm 0x114688 e3a00e53  # v[63] new call 0x114690
callout 9 1329 v63.callout_play@3 movw 0x114694 e3000531  # v[63] new call 0x11469c
clip 9 MainTitle_Artbox movwt 0x111738 0x111740 e30b18b4,e3401062  # BDLTerrorOfMechagodzillaStart::v[13] at 0x111740: a name the display layer loads
# display layers: BDLTerrorOfMechagodzillaBG BDLTerrorOfMechagodzillaStart BDLTerrorOfMechagodzillaTotal

mode 10 cmode_king_of_the_monsters_multiball obj 0x7a1f00 vtable 0x62ae50 title_msg ?
ctor 10 a 17 award 27 b 16 timer -   # cmode_mball, ctor 0xc1858 called at 0xd2f8c; compared against cmode_mball_null, 64 virtuals
shots 10 0x1800700800 v[44] 0xd04f8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop
number 10 initial_mask.lo 7342080 movwt 0xd04f8 0xd0500 e3a00b02,e3400070 word  # v[44] returns it (0x700800) (the low word is a mov)
number 10 initial_mask.hi 24 imm 0xd04fc e3a01018 word  # v[44] returns it (0x18)
start 10 start: cmode_manager_get(10) at 0xc0e0c then v[8], in fn 0xc0dd0
# 28 other cmode_manager_get(10) sites read it (is_running, is_active, or a slot not traced)
number 10 shot.adjustment 5 adj AD_KOTM_TIME_ATTACK_BOUNTY_ADD_TIME 235 e3a000eb adjustment  # v[41] call 0xc38e8; the id is imm 0xc38e4, range 5..15
number 10 shot.caward_add ? code 0xc3a00 - code  # v[41]: the value is computed before the call
number 10 shot.event_post_replacing.id 345 movw 0xc3aec e3000159 word  # v[41] call 0xc3af4
callout 10 2026 shot.callout_play movw 0xc3bd4 e30007ea  # v[41] call 0xc3bd8
number 10 shot.caward_add@2 ? code 0xc3c68 - code  # v[41]: the value is computed before the call
callout 10 1366 shot.callout_play@2 movw 0xc3da4 e3000556  # v[41] call 0xc3da8
callout 10 1367 shot.callout_play@3 movw 0xc3db0 e3000557  # v[41] call 0xc3db4
number 10 shot.adjustment@2 3 adj AD_KOTM_TIME_ATTACK_SECTION_COMPLETE_ADD_TIME 234 e3a000ea adjustment  # v[41] call 0xc3ebc; the id is imm 0xc3eb8, range 3..15
number 10 shot.caward_add@3 ? code 0xc3f48 - code  # v[41]: the value is computed before the call
clip 10 kotm_stage2intro movwt 0xd0594 0xd0598 e30b04c8,e3400062  # BDLKingOfTheMonstersMultiballStart::v[15] at 0xd0598: a name the display layer loads
# display layers: BDLKingOfTheMonstersMultiballStart

mode 11 cmode_monster_island_madness obj 0x7a1f78 vtable 0x62d070 title_msg 3274
ctor 11 a 17 award 28 b 17 timer -   # cmode_mball, ctor 0xdd928 called at 0xd2f3c; compared against cmode_mball_null, 69 virtuals
shots 11 0x5800700800 v[44] 0xdbc1c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 11 initial_mask.lo 7342080 movwt 0xdbc1c 0xdbc24 e3a00b02,e3400070 word  # v[44] returns it (0x700800) (the low word is a mov)
number 11 initial_mask.hi 88 imm 0xdbc20 e3a01058 word  # v[44] returns it (0x58)
number 11 title_msg 3274 movw 0xdf16c e3000cca word
number 11 audit_started 241 imm 0xdf174 e3a000f1 word
number 11 audit_completed 242 imm 0xdf17c e3a000f2 word
start 11 start: cmode_manager_get(11) at 0xc3ac0 then v[8], in cmode_king_of_the_monsters_multiball::v[41]
# 20 other cmode_manager_get(11) sites read it (is_running, is_active, or a slot not traced)
number 11 start.adjustment 75 adj AD_MONSTER_ISLAND_MADNESS_TIMER 229 e3a000e5 adjustment  # v[8] call 0xde440; the id is imm 0xde438, range 90..60
number 11 start.game_event.id 145 imm 0xde7e8 e3a00091 word  # v[8] call 0xde7f0
number 11 end.game_event.id 146 imm 0xdbcac e3a00092 word  # v[10] call 0xdbcb0
number 11 total_display.event_post_replacing.id 261 movw 0xdbe2c e3000105 word  # v[43] call 0xdbe38
clip 11 megalon_monster_island_01 movwt 0xdbe90 0xdbe9c e30d2430,e3402062  # v[43] at 0xdbe9c: a name total_display loads
clip 11 kotm_game_over movwt 0xdcf04 0xdcf0c e30d1474,e3401062  # BDLMonsterIslandMadnessTotal::v[7] at 0xdcf0c: a name the display layer loads
# display layers: BDLMonsterIslandMadnessBG BDLMonsterIslandMadnessStart BDLMonsterIslandMadnessTotal

mode 12 cmode_battle_vs_ebirah obj 0x7a1fe0 vtable 0x6266c8 title_msg 3257
# seen runA: started at 439508 ms, stopped 83001 ms later, reason 0, by lr 0x7e1fc
ctor 12 a 10 award 19 b 7 timer 0   # cmode_battle, ctor 0x7f7e8 called at 0xd2ef0; compared against cmode_battle, 63 virtuals
shots 12 0x22200 v[44] 0x7e6e8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left spinner, top spinner, right spinner
number 12 initial_mask.lo 139776 movwt 0x7e6e8 0x7e6f0 e3a00c22,e3400002 word inert start_rewrites  # v[44] returns it (0x22200) (the low word is a mov)
number 12 initial_mask.hi 0 imm 0x7e6ec e3a01000 word inert start_rewrites  # v[44] returns it (0x0)
start 12 select: slot 0 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 12 select.slot0.mode_id 12 data 0x631f48 0000000c word  # which mode the selector's slot 0 starts
number 12 title_msg 3257 movw 0x8408c e3000cb9 word seen runA
number 12 audit_started 249 imm 0x84094 e3a000f9 word
number 12 audit_completed 250 imm 0x8409c e3a000fa word
start 12 start: cmode_manager_get(12) at 0xc461c then v[8], in cmode_king_of_the_monsters::v[8]
# 20 other cmode_manager_get(12) sites read it (is_running, is_active, or a slot not traced)
number 12 start.caward_add 250000 movwt 0x83ca4 0x83cac e30d2090,e3402003 word seen runA  # v[8] call 0x83cb8
number 12 start.game_event.id 18 imm 0x83d2c e3a00012 word  # v[8] call 0x83d3c
number 12 start.caward_add@2 250000 movwt 0x83d74 0x83d7c e30d2090,e3402003 word seen runA  # v[8] call 0x83d8c
number 12 end.game_event.id 20 imm 0x83f58 e3a00014 word  # v[10] call 0x83f5c
number 12 shot.caward_add ? code 0x80014 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@2 ? code 0x80084 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@3 25000000 movwt 0x801d4 0x801e0 e3072840,e340217d word  # v[41] call 0x801ec
number 12 shot.show_start.id 347 movw 0x80248 e300015b word  # v[41] call 0x8024c
number 12 shot.show_start.id@2 359 movw 0x80290 e3000167 word  # v[41] call 0x80294
number 12 shot.caward_add@4 ? code 0x80358 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@5 ? code 0x803f0 - code  # v[41]: the value is computed before the call
number 12 shot.caward_build.value 0 imm 0x80418 e3a01000 word  # v[41] call 0x8042c
number 12 shot.caward_add@6 ? code 0x804a8 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@7 ? code 0x80540 - code  # v[41]: the value is computed before the call
number 12 shot.caward_build.value@2 0 imm 0x80568 e3a01000 word  # v[41] call 0x8057c
number 12 shot.caward_add@8 ? code 0x805d4 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@9 ? code 0x805f0 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@10 ? code 0x80634 - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@11 ? code 0x80690 - code  # v[41]: the value is computed before the call
number 12 shot.caward_build.value@3 0 imm 0x806b8 e3a01000 word  # v[41] call 0x806cc
number 12 shot.caward_add@12 25000000 movwt 0x806d4 0x806dc e3072840,e340217d word  # v[41] call 0x806e8
number 12 shot.caward_add@13 ? code 0x8078c - code  # v[41]: the value is computed before the call
number 12 shot.caward_add@14 ? code 0x808ac - code  # v[41]: the value is computed before the call
number 12 shot.game_event.id 19 imm 0x80944 e3a00013 word  # v[41] call 0x80948
number 12 shot.game_event.id@2 31 imm 0x80998 e3a0001f word  # v[41] call 0x8099c
number 12 shot.caward_add@15 ? code 0x809e8 - code  # v[41]: the value is computed before the call
number 12 total_display.event_post_replacing.id 249 imm 0x7eb38 e3a000f9 word seen runA  # v[43] call 0x7eb44
clip 12 ebirah_fail movwt 0x7ebe0 0x7ebe4 e3063b3c,e3403062  # v[43] at 0x7ebe4: a name total_display loads
clip 12 ebirah_outtro movwt 0x7ec20 0x7ec28 e3063b2c,e3403062  # v[43] at 0x7ec28: a name total_display loads
number 12 timer.seconds 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # v[56] call 0x7ec9c; the id is imm 0x7ec98, range 30..70
number 12 timer.v57 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # v[57] call 0x7e788; the id is imm 0x7e784, range 30..70
clip 12 ebirah_attack1 movwt 0x840d4 0x840d8 e3060998,e3400062  # BDLBattleVSEbirahStart::v[15] at 0x840d8: a name the display layer loads
# display layers: BDLBattleVSEbirahBG BDLBattleVSEbirahStart

mode 13 cmode_battle_vs_titanosaurus obj 0x7a20c0 vtable 0x628f58 title_msg 3258
ctor 13 a 10 award 20 b 7 timer 1   # cmode_battle, ctor 0xa35e0 called at 0xd2e9c; compared against cmode_battle, 63 virtuals
shots 13 0x0 v[44] 0xa25a8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 13 initial_mask.lo 0 imm 0xa25a8 e3a00000 word inert start_rewrites  # v[44] returns it (0x0)
number 13 initial_mask.hi 0 imm 0xa25ac e3a01000 word inert start_rewrites  # v[44] returns it (0x0)
start 13 select: slot 1 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 13 select.slot1.mode_id 13 data 0x631f54 0000000d word  # which mode the selector's slot 1 starts
number 13 title_msg 3258 movw 0xa76f8 e3000cba word
number 13 audit_started 251 imm 0xa7700 e3a000fb word
number 13 audit_completed 252 imm 0xa7708 e3a000fc word
start 13 start: cmode_manager_get(13) at 0xc4644 then v[8], in cmode_king_of_the_monsters::v[8]
# 24 other cmode_manager_get(13) sites read it (is_running, is_active, or a slot not traced)
number 13 start.caward_add 250000 movwt 0xa73d8 0xa73e0 e30d2090,e3402003 word seen runA  # v[8] call 0xa73f0
number 13 start.caward_add@2 250000 movwt 0xa73f8 0xa7400 e30d2090,e3402003 word  # v[8] call 0xa740c
number 13 start.game_event.id 21 imm 0xa7424 e3a00015 word  # v[8] call 0xa7428
number 13 end.game_event.id 23 imm 0xa75c4 e3a00017 word  # v[10] call 0xa75c8
number 13 shot.game_event.id 22 imm 0xa455c e3a00016 word  # v[41] call 0xa4560
number 13 shot.caward_add 1000000 movwt 0xa45f0 0xa45f8 e3042240,e340200f word  # v[41] call 0xa4608
number 13 shot.event_post_replacing.id 337 movw 0xa469c e3000151 word  # v[41] call 0xa46a8
number 13 shot.caward_add@2 1000000 movwt 0xa46ac 0xa46b4 e3042240,e340200f word  # v[41] call 0xa46c0
number 13 shot.game_event.id@2 32 imm 0xa47d8 e3a00020 word  # v[41] call 0xa47dc
number 13 total_display.event_post_replacing.id 250 imm 0xa2918 e3a000fa word  # v[43] call 0xa2924
clip 13 titanosaurus_fail movwt 0xa29c0 0xa29c4 e3093400,e3403062  # v[43] at 0xa29c4: a name total_display loads
clip 13 titan_godzilla_titanflee movwt 0xa2a00 0xa2a08 e30933e4,e3403062  # v[43] at 0xa2a08: a name total_display loads
number 13 timer.seconds 60 adj AD_BATTLE_VS_TITANOSAURUS_TIMER 213 e3a000d5 adjustment  # v[56] call 0xa2ad8; the id is imm 0xa2ad4, range 30..70
number 13 timer.v57 60 adj AD_BATTLE_VS_TITANOSAURUS_TIMER 213 e3a000d5 adjustment  # v[57] call 0xa2644; the id is imm 0xa2640, range 30..70
clip 13 GodzillaVsTitanosaurus_Intro movwt 0xa7740 0xa7744 e30902c8,e3400062  # BDLBattleVSTitanosaurusStart::v[15] at 0xa7744: a name the display layer loads
# display layers: BDLBattleVSTitanosaurusBG BDLBattleVSTitanosaurusStart

mode 14 cmode_battle_vs_gigan obj 0x7a2178 vtable 0x627410 title_msg 3259
ctor 14 a 10 award 21 b 7 timer 2   # cmode_battle, ctor 0x8b880 called at 0xd2e44; compared against cmode_battle, 63 virtuals
shots 14 ? v[44] 0x8b088 returns the object's field +0x78: set by other code, not measured
start 14 select: slot 2 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 14 select.slot2.mode_id 14 data 0x631f60 0000000e word  # which mode the selector's slot 2 starts
number 14 title_msg 3259 movw 0x8fa24 e3000cbb word
number 14 audit_started 253 imm 0x8fa2c e3a000fd word
number 14 audit_completed 254 imm 0x8fa34 e3a000fe word
start 14 start: cmode_manager_get(14) at 0xc466c then v[8], in cmode_king_of_the_monsters::v[8]
# 17 other cmode_manager_get(14) sites read it (is_running, is_active, or a slot not traced)
number 14 start.caward_add 250000 movwt 0x8f714 0x8f71c e30d2090,e3402003 word seen runA  # v[8] call 0x8f72c
number 14 start.caward_add@2 250000 movwt 0x8f734 0x8f73c e30d2090,e3402003 word  # v[8] call 0x8f748
number 14 start.game_event.id 24 imm 0x8f760 e3a00018 word  # v[8] call 0x8f764
number 14 end.game_event.id 26 imm 0x8f8f0 e3a0001a word  # v[10] call 0x8f8f4
number 14 shot.game_event.id 25 imm 0x8f240 e3a00019 word  # v[41] call 0x8f244
number 14 shot.game_event.id@2 33 imm 0x8f2a4 e3a00021 word  # v[41] call 0x8f2a8
number 14 shot.event_post_replacing.id 335 movw 0x8f33c e300014f word  # v[41] call 0x8f350
number 14 total_display.event_post_replacing.id 251 imm 0x8b36c e3a000fb word  # v[43] call 0x8b378
clip 14 gigan_fail movwt 0x8b414 0x8b418 e30737dc,e3403062  # v[43] at 0x8b418: a name total_display loads
clip 14 gigan_ghidorah_vs_godzilla29 movwt 0x8b454 0x8b45c e30737bc,e3403062  # v[43] at 0x8b45c: a name total_display loads
number 14 timer.seconds 60 adj AD_BATTLE_VS_GIGAN_TIMER 214 e3a000d6 adjustment  # v[56] call 0x8b4d0; the id is imm 0x8b4cc, range 30..70
number 14 timer.v57 60 adj AD_BATTLE_VS_GIGAN_TIMER 214 e3a000d6 adjustment  # v[57] call 0x8b138; the id is imm 0x8b134, range 30..70
clip 14 gigan_good_intro movwt 0x8fa6c 0x8fa70 e3070688,e3400062  # BDLBattleVSGiganStart::v[15] at 0x8fa70: a name the display layer loads
# display layers: BDLBattleVSGiganBG BDLBattleVSGiganStart

mode 15 cmode_battle_vs_megalon obj 0x7a22a8 vtable 0x627fb8 title_msg 3260
ctor 15 a 10 award 22 b 7 timer 3   # cmode_battle, ctor 0x98070 called at 0xd2dec; compared against cmode_battle, 63 virtuals
shots 15 0x5800700800 v[44] 0x96eac, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 15 initial_mask.lo 7342080 movwt 0x96eac 0x96eb4 e3a00b02,e3400070 word inert start_rewrites  # v[44] returns it (0x700800) (the low word is a mov)
number 15 initial_mask.hi 88 imm 0x96eb0 e3a01058 word inert start_rewrites  # v[44] returns it (0x58)
start 15 select: slot 3 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 15 select.slot3.mode_id 15 data 0x631f6c 0000000f word  # which mode the selector's slot 3 starts
number 15 title_msg 3260 movw 0x9c194 e3000cbc word
number 15 audit_started 255 imm 0x9c19c e3a000ff word
number 15 audit_completed 256 imm 0x9c1a4 e3a00c01 word
start 15 start: cmode_manager_get(15) at 0xc4694 then v[8], in cmode_king_of_the_monsters::v[8]
# 24 other cmode_manager_get(15) sites read it (is_running, is_active, or a slot not traced)
number 15 start.caward_add 250000 movwt 0x9be60 0x9be68 e30d2090,e3402003 word seen runA  # v[8] call 0x9be78
number 15 start.caward_add@2 250000 movwt 0x9be80 0x9be88 e30d2090,e3402003 word  # v[8] call 0x9be94
number 15 start.game_event.id 27 imm 0x9beac e3a0001b word  # v[8] call 0x9beb0
number 15 end.game_event.id 30 imm 0x9c060 e3a0001e word  # v[10] call 0x9c064
number 15 shot.caward_build.value 0 imm 0x9b798 e3a01000 word  # v[41] call 0x9b7a8
number 15 shot.show_start.id 348 imm 0x9b810 e3a00f57 word  # v[41] call 0x9b814
number 15 shot.show_start.id@2 359 movw 0x9b858 e3000167 word  # v[41] call 0x9b85c
number 15 shot.event_post_replacing.id 336 imm 0x9b968 e3a00e15 word  # v[41] call 0x9b97c
number 15 total_display.event_post_replacing.id 252 imm 0x971fc e3a000fc word  # v[43] call 0x97208
clip 15 megalon_fail movwt 0x972a0 0x972a8 e30834dc,e3403062  # v[43] at 0x972a8: a name total_display loads
clip 15 Megalon_gigan_jetjag_godzilla41 movwt 0x972e0 0x972e8 e30834bc,e3403062  # v[43] at 0x972e8: a name total_display loads
number 15 timer.seconds 60 adj AD_BATTLE_VS_MEGALON_TIMER 215 e3a000d7 adjustment  # v[56] call 0x973c0; the id is imm 0x973bc, range 30..70
number 15 timer.v57 60 adj AD_BATTLE_VS_MEGALON_TIMER 215 e3a000d7 adjustment  # v[57] call 0x96f74; the id is imm 0x96f70, range 30..70
clip 15 GodzillaVsMegalon_Intro movwt 0x9c1dc 0x9c1e0 e3080338,e3400062  # BDLBattleVSMegalonStart::v[15] at 0x9c1e0: a name the display layer loads
# display layers: BDLBattleVSMegalonBG BDLBattleVSMegalonStart

mode 16 cmode_battle_vs_king_ghidorah obj 0x7a23c0 vtable 0x627968 title_msg 3261
ctor 16 a 26 award 23 b 7 timer 5   # cmode_battle, ctor 0x923c0 called at 0xd2d94; compared against cmode_battle, 63 virtuals
shots 16 ? v[44] 0x914f4 returns the object's field +0x78: set by other code, not measured
start 16 select: slot 4 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 16 select.slot4.mode_id 16 data 0x631f78 00000010 word  # which mode the selector's slot 4 starts
number 16 title_msg 3261 movw 0x95f84 e3000cbd word
number 16 audit_started 257 movw 0x95f8c e3000101 word
number 16 audit_completed 258 movw 0x95f94 e3000102 word
# 18 other cmode_manager_get(16) sites read it (is_running, is_active, or a slot not traced)
number 16 start.adjustment 30 adj AD_BATTLE_VS_KING_GHIDORAH_BALL_SAVE_TIMER 217 e3a000d9 adjustment  # v[8] call 0x95af0; the id is imm 0x95aec, range 28..40
number 16 start.caward_add 250000 movwt 0x95c48 0x95c54 e30d2090,e3402003 word  # v[8] call 0x95c60
number 16 start.game_event.id 35 imm 0x95c7c e3a00023 word  # v[8] call 0x95c80
number 16 start.event_post_replacing.id 338 movw 0x95ca8 e3000152 word  # v[8] call 0x95cac
number 16 end.game_event.id 38 imm 0x95d70 e3a00026 word  # v[10] call 0x95d74
number 16 end.game_event.id@2 36 imm 0x95db0 e3a00024 word  # v[10] call 0x95db4
number 16 end.game_event.id@3 37 imm 0x95de8 e3a00025 word  # v[10] call 0x95dec
number 16 shot.event_post_replacing.id 215 imm 0x93c4c e3a000d7 word  # v[41] call 0x93c58
number 16 total_display.event_post_replacing.id 246 imm 0x916cc e3a000f6 word  # v[43] call 0x916d8
clip 16 ghidorah_victory movwt 0x91724 0x9172c e3073c94,e3403062  # v[43] at 0x9172c: a name total_display loads
number 16 timer.seconds 75 adj AD_BATTLE_VS_KING_GHIDORAH_TIMER 216 e3a000d8 adjustment  # v[56] call 0x91808; the id is imm 0x91804, range 30..90
number 16 timer.v57 75 adj AD_BATTLE_VS_KING_GHIDORAH_TIMER 216 e3a000d8 adjustment  # v[57] call 0x91580; the id is imm 0x9157c, range 30..90
clip 16 mothra_rodan_intro movwt 0x95fc0 0x95fc4 e3070c80,e3400062  # BDLBattleVSKingGhidorahStart::v[15] at 0x95fc4: a name the display layer loads
# display layers: BDLBattleVSKingGhidorahBG BDLBattleVSKingGhidorahStart

mode 17 cmode_battle_vs_ghidorah_and_gigan obj 0x7a2470 vtable 0x626e50 title_msg 3265
ctor 17 a 26 award 24 b 7 timer 6   # cmode_battle, ctor 0x86a58 called at 0xd2d3c; compared against cmode_battle, 63 virtuals
shots 17 ? v[44] 0x8587c returns the object's field +0x78: set by other code, not measured
start 17 select: slot 6 of the 7-entry selector table 0x631f44 {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 17 select.slot6.mode_id 17 data 0x631f90 00000011 word  # which mode the selector's slot 6 starts
number 17 title_msg 3265 movw 0x8a1b8 e3000cc1 word
number 17 audit_started 261 movw 0x8a1c0 e3000105 word
number 17 audit_completed 262 movw 0x8a1c8 e3000106 word
# 16 other cmode_manager_get(17) sites read it (is_running, is_active, or a slot not traced)
number 17 start.adjustment 0 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_DIFFICULTY 220 e3a000dc adjustment  # v[8] call 0x89d84; the id is imm 0x89d80, range 0..2
number 17 start.adjustment@2 30 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_BALL_SAVE_TIMER 219 e3a000db adjustment  # v[8] call 0x89db4; the id is imm 0x89da0, range 28..40
number 17 start.caward_add 250000 movwt 0x89e7c 0x89e88 e30d2090,e3402003 word  # v[8] call 0x89e94
number 17 start.game_event.id 43 imm 0x89eb0 e3a0002b word  # v[8] call 0x89eb4
number 17 start.event_post_replacing.id 339 movw 0x89edc e3000153 word  # v[8] call 0x89ee0
number 17 end.game_event.id 46 imm 0x89fa4 e3a0002e word  # v[10] call 0x89fa8
number 17 end.game_event.id@2 44 imm 0x89fe4 e3a0002c word  # v[10] call 0x89fe8
number 17 end.game_event.id@3 45 imm 0x8a01c e3a0002d word  # v[10] call 0x8a020
number 17 shot.caward_add 50000 movw 0x87e58 e30c2350 word  # v[41] call 0x87e64
number 17 shot.show_start.id 348 imm 0x87f30 e3a00f57 word  # v[41] call 0x87f34
number 17 shot.show_start.id@2 342 movw 0x87f88 e3000156 word  # v[41] call 0x87f8c
number 17 shot.show_start.id@3 359 movw 0x88018 e3000167 word  # v[41] call 0x8801c
number 17 shot.fx.n 334 movw 0x88098 e300014e word  # v[41] call 0x880a0
number 17 shot.event_post_replacing.id 215 imm 0x880ac e3a000d7 word  # v[41] call 0x880b4
number 17 shot.caward_add@2 7500000 movwt 0x881bc 0x881c8 e30720e0,e3402072 word  # v[41] call 0x881d4
number 17 total_display.event_post_replacing.id 248 imm 0x85b58 e3a000f8 word  # v[43] call 0x85b64
clip 17 gigan_ghidorah_vs_godzilla81 movwt 0x85bb0 0x85bb8 e3073128,e3403062  # v[43] at 0x85bb8: a name total_display loads
number 17 timer.seconds 75 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER 218 e3a000da adjustment  # v[56] call 0x85c94; the id is imm 0x85c90, range 30..90
number 17 timer.v57 75 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER 218 e3a000da adjustment  # v[57] call 0x85908; the id is imm 0x85904, range 30..90
clip 17 ghidorah_gigan_intronew movwt 0x8a1f4 0x8a1f8 e3070110,e3400062  # BDLBattleVSGhidorahAndGiganStart::v[15] at 0x8a1f8: a name the display layer loads
# display layers: BDLBattleVSGhidorahAndGiganBG BDLBattleVSGhidorahAndGiganStart

mode 18 cmode_super_train obj 0x7a2528 vtable 0x62fb98 title_msg 3244
# seen runA: started at 221374 ms, stopped 37335 ms later, reason 0, by lr 0xd3e00
ctor 18 a 18 award 25 b 11 timer 17   # cmode_timed, ctor 0x1018f8 called at 0xd2ce4; compared against cmode_timed, 69 virtuals
number 18 timer.v57 30 code 0x7e5f8 - code shared 5  # the base default: mov #30 at 0x7e5f8, 0x11b398 - all of them, or a hook
shots 18 0x300000 v[44] 0x100714, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left ramp, right ramp
number 18 initial_mask.lo 3145728 imm 0x100714 e3a00603 word  # v[44] returns it (0x300000)
number 18 initial_mask.hi 0 imm 0x100718 e3a01000 word  # v[44] returns it (0x0)
number 18 title_msg 3244 movw 0x1042d8 e3000cac word seen runA
number 18 audit_started 245 imm 0x1042e0 e3a000f5 word
number 18 audit_completed 0 imm 0x7def0 e3a00000 word shared 4
start 18 start: cmode_manager_get(18) at 0x59914 then v[8], in fn 0x595b8
# 14 other cmode_manager_get(18) sites read it (is_running, is_active, or a slot not traced)
number 18 start.caward_add 100000 movwt 0x101d3c 0x101d44 e30826a0,e3402001 word seen runA  # v[8] call 0x101d58
number 18 start.game_event.id 114 imm 0x101d94 e3a00072 word  # v[8] call 0x101d98
number 18 end.game_event.id 117 imm 0x100774 e3a00075 word  # v[10] call 0x100778
number 18 end.game_event.id@2 116 imm 0x1007ac e3a00074 word  # v[10] call 0x1007b0
number 18 shot.caward_add ? code 0x1025a0 - code  # v[41]: the value is computed before the call
number 18 shot.event_post_replacing.id 227 imm 0x1025b8 e3a000e3 word  # v[41] call 0x1025bc
number 18 total_display.event_post_replacing.id 242 imm 0x100864 e3a000f2 word seen runA  # v[43] call 0x100870
clip 18 Godzilla_TrainThrow movwt 0x1008bc 0x1008c4 e30f3e64,e3403062  # v[43] at 0x1008c4: a name total_display loads
number 18 timer.seconds 25 adj AD_SUPER_TRAIN_TIMER 192 e3a000c0 adjustment  # v[56] call 0x104340; the id is imm 0x10433c, range 15..45
clip 18 Godzilla_TrainStomp movwt 0x1042fc 0x104300 e30f0e40,e3400062  # BDLSuperTrainAward::v[15] at 0x104300: a name the display layer loads
clip 18 Train_Scene2 movwt 0x104328 0x10432c e30f0e54,e3400062  # BDLSuperTrainBG::v[14] at 0x10432c: a name the display layer loads
# display layers: BDLSuperTrainAward BDLSuperTrainBG BDLSuperTrainStart

mode 19 cmode_o2_destroyer obj 0x7a25e8 vtable 0x62e7a8 title_msg 3245
# seen runA: started at 263390 ms, stopped 33001 ms later, reason 0, by lr 0x40842eec
# seen runB (the PATCHED card: tesla start award 1250000, jet fighter timer 10): started at 175258 ms, stopped 19534 ms later, reason 0, by lr 0xefc40
ctor 19 a 18 award 26 b 12 timer 18   # cmode_timed, ctor 0xefaf8 called at 0xd2c8c; compared against cmode_timed, 64 virtuals
number 19 timer.v57 30 code 0x7e5f8 - code shared 5  # the base default: mov #30 at 0x7e5f8, 0x11b398 - all of them, or a hook
shots 19 ? v[44] 0xef390 computes the lit mask: code
number 19 title_msg 3245 movw 0xf1d70 e3000cad word seen runB
number 19 audit_started 246 imm 0xf1d78 e3a000f6 word
number 19 audit_completed 247 imm 0xf1d80 e3a000f7 word
start 19 start: cmode_manager_get(19) at 0x163e34 then v[8], in fn 0x163e18
# 23 other cmode_manager_get(19) sites read it (is_running, is_active, or a slot not traced)
number 19 start.caward_add 500000 movwt 0xef4d0 0xef4dc e30a2120,e3402007 word seen runA seen runB  # v[8] call 0xef4e8
number 19 start.game_event.id 147 imm 0xef504 e3a00093 word  # v[8] call 0xef508
number 19 end.game_event.id 149 imm 0xef78c e3a00095 word  # v[10] call 0xef790
number 19 end.game_event.id@2 148 imm 0xef7b8 e3a00094 word  # v[10] call 0xef7bc
number 19 shot.caward_add 1000000 movwt 0xefcdc 0xefcec e3042240,e340200f word  # v[41] call 0xefcf8
number 19 shot.show_start.id 173 imm 0xefd48 e3a000ad word  # v[41] call 0xefd4c
number 19 start_display.award_screen.type 149 imm 0xef388 e3a00095 word  # v[42] call 0xef38c
number 19 initial_mask.adjustment 2 adj AD_O2_DESTROYER 164 e3a000a4 adjustment  # v[44] call 0xef398; the id is imm 0xef394, range 0..2
number 19 countdown.show_start.id 284 imm 0xef3f4 e3a00f47 word seen runA seen runB  # v[55] call 0xef3f8
number 19 countdown.fx.n 100 imm 0xef404 e3a00064 word  # v[55] call 0xef40c
number 19 countdown.show_start.id@2 285 movw 0xef410 e300011d word seen runB  # v[55] call 0xef414
number 19 countdown.fx.n@2 3000 movw 0xef41c e3000bb8 word  # v[55] call 0xef428
number 19 timer.seconds 12 adj AD_O2_DESTROYER_TIMER 193 e3a000c1 adjustment  # v[56] call 0xf1db4; the id is imm 0xf1db0, range 8..20
clip 19 o2destroyer_loop movwt 0xf1d9c 0xf1da0 e30e0970,e3400062  # BDLO2DestroyerBG::v[14] at 0xf1da0: a name the display layer loads
# display layers: BDLO2DestroyerBG

mode 20 cmode_king_of_the_monsters obj 0x7a2658 vtable 0x62ad50 title_msg ?
# seen runA: started at 302390 ms, stopped 47520 ms later, reason 0, by lr 0x40842eec
ctor 20 a 18 award 27 b 16 timer 25   # cmode_timed, ctor 0xbf8a8 called at 0xd2c38; compared against cmode_timed, 62 virtuals
number 20 timer.seconds ? code 0xbc8d8 - code  # v[56] computes it; not measured
number 20 timer.v57 84 imm 0xbc2b4 e3a00054 word  # v[57] returns it
shots 20 0x0 v[44] 0xd04d0, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 20 initial_mask.lo 0 imm 0xd04d0 e3a00000 word inert start_rewrites  # v[44] returns it (0x0)
number 20 initial_mask.hi 0 imm 0xd04d4 e3a01000 word inert start_rewrites  # v[44] returns it (0x0)
start 20 start: cmode_manager_get(20) at 0x56460 then v[8], in fn 0x5640c
start 20 stop: cmode_manager_get(20) at 0xbd540 then v[11], in cmode_king_of_the_monsters_multiball::v[11]
start 20 start: cmode_manager_get(20) at 0x156fc8 then v[8], in RuleKingOfTheMonsters::v[25]
# 117 other cmode_manager_get(20) sites read it (is_running, is_active, or a slot not traced)
number 20 start.adjustment 12 adj AD_KOTM_TIME_ATTACK_DEFAULT_TIME_BONUS 231 e3a000e7 adjustment  # v[8] call 0xc477c; the id is imm 0xc4774, range 8..25
number 20 start.event_post_replacing.id 346 movw 0xc4848 e300015a word seen runA  # v[8] call 0xc4850
number 20 shot.caward_add ? code 0xbcf14 - code  # v[41]: the value is computed before the call
number 20 shot.adjustment 12 adj AD_KOTM_TIME_ATTACK_DEFAULT_TIME_BONUS 231 e3a000e7 adjustment  # v[41] call 0xbcf28; the id is imm 0xbcf1c, range 8..25
number 20 shot.award_screen.type 106 imm 0xbcf44 e3a0006a word  # v[41] call 0xbcf48
number 20 shot.show_start.id 236 imm 0xbcfb0 e3a000ec word  # v[41] call 0xbcfbc
number 20 shot.fx.n 500 imm 0xbcfc8 e3a00f7d word  # v[41] call 0xbcfcc
number 20 shot.caward_add@2 2000000 movwt 0xbcfe8 0xbcff0 e3082480,e340201e word  # v[41] call 0xbd000
number 20 shot.adjustment@2 3 adj AD_KOTM_TIME_ATTACK_LOOP_ADD_TIME_BONUS 232 e3a000e8 adjustment  # v[41] call 0xbd00c; the id is imm 0xbd004, range 2..10
number 20 shot.adjustment@3 40 adj AD_KOTM_TIME_ATTACK_MAX_TIME_BONUS 233 e3a000e9 adjustment  # v[41] call 0xbd020; the id is imm 0xbd018, range 30..60
number 20 shot.award_screen.type@2 105 imm 0xbd04c e3a00069 word  # v[41] call 0xbd050
number 20 shot.show_start.id@2 236 imm 0xbd084 e3a000ec word  # v[41] call 0xbd088
number 20 shot.fx.n@2 100 imm 0xbd094 e3a00064 word  # v[41] call 0xbd0a0
clip 20 jj_timeadded movwt 0xbcf54 0xbcf5c e30b24dc,e3402062  # v[41] at 0xbcf5c: a name shot loads
clip 20 jj_timebuild movwt 0xbd05c 0xbd064 e30b34ec,e3403062  # v[41] at 0xbd064: a name shot loads
number 20 v53.event_post_replacing.id 345 movw 0xc0fe0 e3000159 word  # v[53] call 0xc0fe4
clip 20 kotm_intro2 movwt 0xc6294 0xc62a8 e30b08a8,e3400062  # BDLKingOfTheMonstersStart::v[13] at 0xc62a8: a name the display layer loads
clip 20 MainTitle_Artbox movwt 0xc62c0 0xc62c8 e30b18b4,e3401062  # BDLKingOfTheMonstersStart::v[13] at 0xc62c8: a name the display layer loads
# display layers: BDLKingOfTheMonstersBG BDLKingOfTheMonstersMBBG BDLKingOfTheMonstersStart BDLKingOfTheMonstersTotal

mode 21 cmode_jet_fighter_attack obj 0x7a2710 vtable 0x62a880 title_msg 3238
# seen runA: started at 133842 ms, stopped 33432 ms later, reason 0, by lr 0x11b160
# seen runB (the PATCHED card: tesla start award 1250000, jet fighter timer 10): started at 133725 ms, stopped 22333 ms later, reason 0, by lr 0x11b160
ctor 21 a 4 award 29 b 8 timer 7   # cmode_hurry_up, ctor 0xb82b4 called at 0xd2be0; compared against cmode_hurry_up_null, 68 virtuals
number 21 timer.seconds 20 imm 0xb75c0 e3a00014 word  # v[56] returns it; PROOF EDIT: 10 on the patched card, runB ran 22,333 ms to the timer expiry (lr 0x11b160) against runA's 33,432 ms
number 21 timer.v57 30 code 0x7e5f8 - code shared 5  # the base default: mov #30 at 0x7e5f8, 0x11b398 - all of them, or a hook
shots 21 0x14 v[44] 0xb75c8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 2, bit 4
number 21 initial_mask.lo 20 imm 0xb75c8 e3a00014 word  # v[44] returns it (0x14)
number 21 initial_mask.hi 0 imm 0xb75cc e3a01000 word  # v[44] returns it (0x0)
number 21 title_msg 3238 movw 0xbb264 e3000ca6 word seen runA seen runB
number 21 audit_started 213 imm 0xbb26c e3a000d5 word
number 21 audit_completed 214 imm 0xbb274 e3a000d6 word
start 21 start: cmode_manager_get(21) at 0x155c68 then v[8], in RuleJetFighters::v[25]
# 17 other cmode_manager_get(21) sites read it (is_running, is_active, or a slot not traced)
number 21 start.caward_add 250000 movwt 0xb816c 0xb8178 e30d2090,e3402003 word seen runA seen runB  # v[8] call 0xb8184
number 21 start.game_event.id 59 imm 0xb81c8 e3a0003b word  # v[8] call 0xb81d4
number 21 end.game_event.id 61 imm 0xb79b4 e3a0003d word  # v[10] call 0xb79b8
number 21 shot.show_start.id 229 imm 0xb8ca4 e3a000e5 word  # v[41] call 0xb8ca8
number 21 total_display.event_post_replacing.id 244 imm 0xb783c e3a000f4 word seen runA seen runB  # v[43] call 0xb7848
clip 21 fighter_total movwt 0xb7894 0xb789c e30a3b80,e3403062  # v[43] at 0xb789c: a name total_display loads
# display layers: BDLJetFighterAttackBG BDLJetFighterAttackStart

mode 22 cmode_planet_x_hurry_up obj 0x7a27f8 vtable 0x62edc8 title_msg 3268
# seen runA: started at 172357 ms, stopped 43019 ms later, reason 0, by lr 0x40842eec
ctor 22 a 20 award 16 b 13 timer 21   # cmode_hurry_up, ctor 0xf9a7c called at 0xd2b88; compared against cmode_hurry_up_null, 70 virtuals
number 22 timer.seconds ? code 0xf2590 - code  # v[56] reads the object's field +0x70; set elsewhere, not measured
number 22 timer.v57 30 code 0x7e5f8 - code shared 5  # the base default: mov #30 at 0x7e5f8, 0x11b398 - all of them, or a hook
shots 22 0x2000000000 v[44] 0xf9f80, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 37
number 22 initial_mask.lo 0 imm 0xf9f80 e3a00000 word inert start_rewrites  # v[44] returns it (0x0)
number 22 initial_mask.hi 32 imm 0xf9f84 e3a01020 word inert start_rewrites  # v[44] returns it (0x20)
number 22 title_msg 3268 movw 0xf9f70 e3000cc4 word
number 22 audit_started 0 imm 0x7dee8 e3a00000 word
number 22 audit_completed 0 imm 0x7def0 e3a00000 word shared 4
start 22 start: cmode_manager_get(22) at 0xf9834 then v[8], in cmode_planet_x_multiball::v[41]
# 7 other cmode_manager_get(22) sites read it (is_running, is_active, or a slot not traced)
number 22 end.game_event.id 78 imm 0xf282c e3a0004e word  # v[10] call 0xf2830
# display layers: BDLPlanetXHurryUpBG

mode 23 cmode_tesla_strike obj 0x7a2878 vtable 0x6307b8 title_msg 3242
# seen runA: started at 108391 ms, stopped 7451 ms later, reason 0, by lr 0x40842eec
# seen runA: started at 118841 ms, stopped 9000 ms later, reason 0, by lr 0x40842eec
# seen runB (the PATCHED card: tesla start award 1250000, jet fighter timer 10): started at 108458 ms, stopped 7267 ms later, reason 0, by lr 0x40842eec
# seen runB (the PATCHED card: tesla start award 1250000, jet fighter timer 10): started at 118724 ms, stopped 9001 ms later, reason 0, by lr 0x40842eec
ctor 23 a 0 award 30 b 9 timer -   # cmode, ctor 0x10ce08 called at 0xd2b30; compared against cmode, 50 virtuals
shots 23 0x7000 v[44] 0x10bfd4, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 12, top spinner
number 23 initial_mask.lo 28672 imm 0x10bfd4 e3a00a07 word  # v[44] returns it (0x7000)
number 23 initial_mask.hi 0 imm 0x10bfd8 e3a01000 word  # v[44] returns it (0x0)
number 23 title_msg 3242 movw 0x1101a4 e3000caa word seen runA seen runB
number 23 audit_started 243 imm 0x1101ac e3a000f3 word
number 23 audit_completed 244 imm 0x1101b4 e3a000f4 word
start 23 stop: cmode_manager_get(23) at 0x136808 then v[11], in fn 0x135bd0
start 23 start: cmode_manager_get(23) at 0x166810 then v[8], in fn 0x1666fc
# 18 other cmode_manager_get(23) sites read it (is_running, is_active, or a slot not traced)
number 23 start.caward_add 250000 movwt 0x10c228 0x10c234 e30d2090,e3402003 word seen runA  # v[8] call 0x10c240; PROOF EDIT: 1250000 on the patched card, runB paid v=1250000 at lr 0x10c244 (natural and forced starts) and its total screen read 1,250,000
number 23 start.game_event.id 92 imm 0x10c27c e3a0005c word  # v[8] call 0x10c28c
number 23 end.game_event.id 94 imm 0x10c038 e3a0005e word  # v[10] call 0x10c03c
number 23 shot.caward_add_scaled.mult 1 imm 0x10d164 e3a03001 word  # v[41] call 0x10d170
number 23 shot.fx.n 200 imm 0x10d3a8 e3a000c8 word  # v[41] call 0x10d3b8
number 23 shot.game_event.id 93 imm 0x10d488 e3a0005d word  # v[41] call 0x10d48c
number 23 total_display.event_post_replacing.id 245 imm 0x10c310 e3a000f5 word seen runA seen runB  # v[43] call 0x10c31c
clip 23 Mothra_godzilla_attack20 movwt 0x10c3b4 0x10c3b8 e3002a64,e3402063  # v[43] at 0x10c3b8: a name total_display loads
clip 23 Mothra_godzilla_powerlines10_2 movwt 0x10c3bc 0x10c3c0 e3003a44,e3403063  # v[43] at 0x10c3c0: a name total_display loads
clip 23 Mothra_godzilla_powerlines8 movwt 0x1101c8 0x1101cc e3000a28,e3400063  # BDLTeslaStrikeBG::v[14] at 0x1101cc: a name the display layer loads
# display layers: BDLTeslaStrikeBG

mode 24 cmode_monster_rampage obj 0x7a2900 vtable 0x62d700 title_msg 3243
# seen runA: started at 356407 ms, stopped 47501 ms later, reason 0, by lr 0x40842eec
ctor 24 a 18 award 31 b 10 timer 14   # cmode_timed, ctor 0xe08e0 called at 0xd2ae0; compared against cmode_timed, 63 virtuals
number 24 timer.v57 30 code 0x7e5f8 - code shared 5  # the base default: mov #30 at 0x7e5f8, 0x11b398 - all of them, or a hook
shots 24 0x100000 v[44] 0xdfd2c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left ramp
number 24 initial_mask.lo 1048576 imm 0xdfd2c e3a00601 word  # v[44] returns it (0x100000)
number 24 initial_mask.hi 0 imm 0xdfd30 e3a01000 word  # v[44] returns it (0x0)
number 24 title_msg 3243 movw 0xe4830 e3000cab word seen runA
number 24 audit_started 248 imm 0xe4838 e3a000f8 word
number 24 audit_completed 0 imm 0x7def0 e3a00000 word shared 4
start 24 start: cmode_manager_get(24) at 0x59ae4 then v[8], in fn 0x595b8
start 24 start: cmode_manager_get(24) at 0x15f524 then v[8], in fn 0x15f3a0
# 28 other cmode_manager_get(24) sites read it (is_running, is_active, or a slot not traced)
number 24 start.adjustment 3000000 adj AD_MONSTER_RAMPAGE_BASE_SCORE 188 e3a000bc adjustment  # v[8] call 0xe1af0; the id is imm 0xe1aec, range 1000000..20000000
number 24 start.adjustment@2 1250000 adj AD_MONSTER_RAMPAGE_INCR_SCORE 189 e3a000bd adjustment  # v[8] call 0xe1afc; the id is imm 0xe1af8, range 500000..10000000
number 24 start.caward_add 250000 movwt 0xe1b94 0xe1ba0 e30d2090,e3402003 word seen runA  # v[8] call 0xe1bbc
number 24 start.adjustment@3 45 adj AD_MONSTER_RAMPAGE_BALL_SAVE_TIMER 186 e3a000ba adjustment  # v[8] call 0xe1c08; the id is imm 0xe1bf8, range 40..60
number 24 start.adjustment@4 15 adj AD_MONSTER_RAMPAGE_BALL_SAVE_DECREMENT 187 e3a000bb adjustment  # v[8] call 0xe1c14; the id is imm 0xe1c10, range 5..20
number 24 start.game_event.id 53 imm 0xe1c6c e3a00035 word  # v[8] call 0xe1c78
number 24 end.game_event.id 56 imm 0xdfee8 e3a00038 word  # v[10] call 0xdfeec
number 24 end.game_event.id@2 54 imm 0xdff28 e3a00036 word  # v[10] call 0xdff2c
number 24 end.game_event.id@3 55 imm 0xdff60 e3a00037 word  # v[10] call 0xdff64
number 24 total_display.event_post_replacing.id 243 imm 0xe0150 e3a000f3 word seen runA  # v[43] call 0xe015c
clip 24 rampage_total movwt 0xe0198 0xe01a0 e30d3a10,e3403062  # v[43] at 0xe01a0: a name total_display loads
number 24 timer.seconds 16 adj AD_RAMPAGE_MODE_SHOT_TIMER 185 e3a000b9 adjustment  # v[56] call 0xe4890; the id is imm 0xe488c, range 8..20
# display layers: BDLMonsterRampageBG BDLMonsterRampageStart

mode 25 cmode_hedorah obj 0x7a29e8 vtable 0x62a430 title_msg 3593
# seen runA: started at 409908 ms, stopped 9017 ms later, reason 0, by lr 0x40842eec
# seen runB (the PATCHED card: tesla start award 1250000, jet fighter timer 10): started at 160741 ms, stopped 8517 ms later, reason 0, by lr 0x40842eec
ctor 25 a 0 award 33 b 19 timer -   # cmode, ctor 0xb4d30 called at 0xd2a88; compared against cmode, 48 virtuals
shots 25 0x5800700800 v[44] 0xb4698, the lit mask cmode's START takes (then tail-calls 0x1b3ae8, which may change it); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 25 initial_mask.lo 7342080 movwt 0xb4698 0xb46a0 e3a00b02,e3400070 code  # v[44] returns it (0x700800) (the low word is a mov)
number 25 initial_mask.hi 88 imm 0xb469c e3a01058 code  # v[44] returns it (0x58)
number 25 title_msg 3593 movw 0xb6c0c e3000e09 word seen runA seen runB
number 25 audit_started 263 movw 0xb6c14 e3000107 word
number 25 audit_completed 0 imm 0x7def0 e3a00000 word shared 4
start 25 start: cmode_manager_get(25) at 0x59b70 then v[8], in fn 0x595b8
start 25 start: cmode_manager_get(25) at 0x162b7c then v[8], in fn 0x162b60
# 6 other cmode_manager_get(25) sites read it (is_running, is_active, or a slot not traced)
number 25 start.caward_add 500000 movwt 0xb4e6c 0xb4e74 e30a2120,e3402007 word seen runA seen runB  # v[8] call 0xb4e88
number 25 start.show_start.id 210 imm 0xb4e8c e3a000d2 word seen runA seen runB  # v[8] call 0xb4e90
number 25 start.game_event.id 107 imm 0xb4eac e3a0006b word  # v[8] call 0xb4eb0
number 25 end.game_event.id 109 imm 0xb4688 e3a0006d word  # v[10] call 0xb468c
clip 25 Hedorah_Smoke_Grow movwt 0xb6c1c 0xb6c20 e30a0640,e3400062  # BDLHedorahAward::v[15] at 0xb6c20: a name the display layer loads
# display layers: BDLHedorahAward

mode 26 cmode_monster_zero obj 0x7a2a68 vtable 0x62dcc0 title_msg 3269
# seen runA: started at 424925 ms, stopped 8566 ms later, reason 0, by lr 0x40842eec
ctor 26 a 16 award 17 b 14 timer -   # cmode, ctor 0xe7498 called at 0xd2a38; compared against cmode, 48 virtuals
shots 26 0x0 v[44] 0xee194, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 26 initial_mask.lo 0 imm 0xee194 e3a00000 word  # v[44] returns it (0x0)
number 26 initial_mask.hi 0 imm 0xee198 e3a01000 word  # v[44] returns it (0x0)
number 26 title_msg 3269 movw 0xee17c e3000cc5 word seen runA
number 26 audit_started 223 imm 0xee184 e3a000df word
number 26 audit_completed 224 imm 0xee18c e3a000e0 word
start 26 start: cmode_manager_get(26) at 0x59d8c then v[8], in fn 0x595b8
start 26 start: cmode_manager_get(26) at 0x15702c then v[8], in RuleKingOfTheMonsters::v[25]
# 35 other cmode_manager_get(26) sites read it (is_running, is_active, or a slot not traced)
number 26 start.caward_add 25000000 movwt 0xe9eac 0xe9ebc e3072840,e340217d word seen runA  # v[8] call 0xe9ec4
number 26 start.adjustment 30 adj AD_MONSTER_ZERO_BALL_SAVE_TIMER 225 e3a000e1 adjustment  # v[8] call 0xe9ee0; the id is imm 0xe9edc, range 28..40
number 26 start.game_event.id 121 imm 0xe9f7c e3a00079 word  # v[8] call 0xe9f84
number 26 end.game_event.id 124 imm 0xe5378 e3a0007c word  # v[10] call 0xe537c
number 26 shot.game_event.id 122 imm 0xe8238 e3a0007a word  # v[41] call 0xe823c
number 26 shot.caward_add 250000 movwt 0xe82b8 0xe82c0 e30d2090,e3402003 word  # v[41] call 0xe82cc
callout 26 226 shot.sound_request_play imm 0xe82d8 e3a000e2  # v[41] call 0xe82f0
number 26 shot.show_start.id 146 imm 0xe8300 e3a00092 word  # v[41] call 0xe8318
callout 26 1043 shot.callout_play movw 0xe8394 e3000413  # v[41] call 0xe8398
number 26 shot.show_start.id@2 145 imm 0xe83ac e3a00091 word  # v[41] call 0xe83b0
number 26 shot.show_start.id@3 348 imm 0xe83c8 e3a00f57 word  # v[41] call 0xe83cc
number 26 shot.show_start.id@4 342 movw 0xe8410 e3000156 word  # v[41] call 0xe8414
number 26 shot.show_start.id@5 359 movw 0xe8478 e3000167 word  # v[41] call 0xe847c
number 26 shot.fx.n 100 imm 0xe84dc e3a00064 word  # v[41] call 0xe84e4
number 26 shot.show_start.id@6 145 imm 0xe84e8 e3a00091 word  # v[41] call 0xe84ec
number 26 shot.show_start.id@7 348 imm 0xe8504 e3a00f57 word  # v[41] call 0xe8508
number 26 shot.show_start.id@8 342 movw 0xe854c e3000156 word  # v[41] call 0xe8550
number 26 shot.caward_add@2 150000 movwt 0xe85d4 0xe85e0 e30429f0,e3402002 word  # v[41] call 0xe85ec
number 26 shot.show_start.id@9 146 imm 0xe86f4 e3a00092 word  # v[41] call 0xe870c
number 26 start_display.event_post_replacing.id 271 movw 0xe5410 e300010f word seen runA  # v[42] call 0xe5414
number 26 total_display.event_post_replacing.id 258 movw 0xe5930 e3000102 word seen runA  # v[43] call 0xe593c
clip 26 monster_zero_outtro movwt 0xe5988 0xe5990 e30ec3e0,e340c062  # v[43] at 0xe5990: a name total_display loads
clip 26 mt_fuji_loop movwt 0xe646c 0xe6480 e30e03f4,e3400062  # BDLMonsterZeroStart::v[13] at 0xe6480: a name the display layer loads
clip 26 MainTitle_Artbox movwt 0xe6498 0xe64a0 e30b18b4,e3401062  # BDLMonsterZeroStart::v[13] at 0xe64a0: a name the display layer loads
scene 26 4e0bf26631e0d64055ae92806c1a413634f6d72f movwt 0xe65ec 0xe65f0 e30e1404,e3401062  # BDLMonsterZeroStart::v[13] at 0xe65f0
clip 26 YouAreToReport_VO3 movwt 0xe672c 0xe6730 e30e1450,e3401062  # BDLMonsterZeroStart::v[13] at 0xe6730: a name the display layer loads
# display layers: BDLMonsterZeroBG BDLMonsterZeroStart BDLMonsterZeroTotal BDLMonsterZeroVictoryBG
# --- hand read (item 144): the screen that reads the selector table 0x631f44 ---
start 12 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 0
start 13 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 1
start 14 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 2
start 15 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 3
start 16 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 4
start 6 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 5
start 17 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 6
# --- hand read (item 144): tesla strike's start writes its OWN lit mask after cmode's START ---
shots 23 0x4800700000 its own start stores mov 0x700000 / mov 0x48 into the lit mask (strd at 0x10c280): left ramp, right ramp, building, bit 35, bit 38; MODE_API.md read the same 0x48_00700000
number 23 start.lit_mask.lo 7340032 imm 0x10c264 e3a08607 word  # tesla's v[8]
number 23 start.lit_mask.hi 72 imm 0x10c26c e3a09048 word  # tesla's v[8]
# --- hand read (item 144): planet X hurry-up's duration is its constructor's constant ---
number 22 timer.seconds.ctor 20 imm 0xf9aa0 e3a02014 word  # the constructor 0xf9a7c stores it at +0x70 (0xf9aa8), the field v[56] returns; AD_PLANET_X_HURRY_UP_TIMER (222, default 20) has no constant-id reader, so whether the operator's value replaces it is not measured
# --- hand read (item 144): mode 20's title is one of three message ids (v[27] 0xbc5e8) ---
number 20 title_msg@2 3275 movw 0xbc5f8 e3000ccb word  # when its first test (flag 40; Pro 1.15 0x1d91e4) is true
number 20 title_msg 3272 movw 0xbc604 e3003cc8 word  # when both tests (flags 40 and 41) are false; 3272 = "KING OF THE MONSTERS" (seen runA)
number 20 title_msg@3 3276 movw 0xbc608 e3002ccc word  # when its second test (flag 41) is true
# --- hand read (item 144): mode 10's title is one of three message ids (v[27] 0xbc674) ---
number 10 title_msg@2 3275 movw 0xbc684 e3000ccb word  # when its first test (flag 40; Pro 1.15 0x1d91e4) is true
number 10 title_msg 3273 movw 0xbc690 e3003cc9 word  # when both tests (flags 40 and 41) are false
number 10 title_msg@3 3276 movw 0xbc694 e3002ccc word  # when its second test (flag 41) is true
# --- hand read (item 144): scenes. A stock mode draws in SHARED template scenes plus a clip by name;
# only a few modes load a scene of their own. Read from the display layers' base classes and the
# unit (static initialiser) that loads each 40-hex id, and each scene's node names; not seen live. ---
scene 1 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 2 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 4 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 7 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 9 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 11 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 18 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 21 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 23 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 24 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x458fc 0x45904 e3021d20,e3401062  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 7 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x464a8 0x464b0 e3021dd8,e3401062  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 9 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x464a8 0x464b0 e3021dd8,e3401062  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 11 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x464a8 0x464b0 e3021dd8,e3401062  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 20 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x464a8 0x464b0 e3021dd8,e3401062  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 26 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x464a8 0x464b0 e3021dd8,e3401062  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 12 a1a15be43fa0e14f26dd704b624aa46a3f36525a movwt 0x46c90 0x46c98 e3021ec0,e3401062  # SHARED by the tier-1 battles: BDLModeTotalBattleTier1's unit loads it (which battles use that layer: by its name); holds: MODE NAME TOTAL, X CONTROLS CURRENT CITY
scene 13 a1a15be43fa0e14f26dd704b624aa46a3f36525a movwt 0x46c90 0x46c98 e3021ec0,e3401062  # SHARED by the tier-1 battles: BDLModeTotalBattleTier1's unit loads it (which battles use that layer: by its name); holds: MODE NAME TOTAL, X CONTROLS CURRENT CITY
scene 14 a1a15be43fa0e14f26dd704b624aa46a3f36525a movwt 0x46c90 0x46c98 e3021ec0,e3401062  # SHARED by the tier-1 battles: BDLModeTotalBattleTier1's unit loads it (which battles use that layer: by its name); holds: MODE NAME TOTAL, X CONTROLS CURRENT CITY
scene 15 a1a15be43fa0e14f26dd704b624aa46a3f36525a movwt 0x46c90 0x46c98 e3021ec0,e3401062  # SHARED by the tier-1 battles: BDLModeTotalBattleTier1's unit loads it (which battles use that layer: by its name); holds: MODE NAME TOTAL, X CONTROLS CURRENT CITY
scene 25 56fadc8a1342be85b087009f71a01c31c120faf5 movwt 0xb5f44 0xb5f4c e30a1654,e3401062  # hedorah's own unit (static initialiser); holds: HEDORAH, SMOG MONSTER FRENZY, SHOOT GREEN ARROW TO COLLECT
scene 24 7949bb14a9a21abf5e2885a01eb5ed4f9c3a8eca movwt 0xe1658 0xe1660 e30413a0,e3401062  # monster rampage's unit; the global it builds is read by cmode_monster_rampage and BDLMonsterRampageBG; holds: BaseGame: AWARD TITLE / AWARD VALUE
scene 26 4e0bf26631e0d64055ae92806c1a413634f6d72f movwt 0xe65ec 0xe65f0 e30e1404,e3401062  # BDLMonsterZeroStart::v[13] loads it; holds: Xilien console pop-up (Planet X voice lines)
scene 1 4fb4bb55515739e701b3893a997391221a4b9a6b movwt 0xb1b04 0xb1b0c e30a10c4,e3401062  # godzilla multiball's unit (next to BDLGodzillaMultiballBG); holds: SuperJackpot_Start
scene 2 a24cebb4d146eed3302abcd6577e4454f5f2c296 movwt 0xd8450 0xd8458 e30c1f80,e3401062  # mechagodzilla multiball's unit; holds: SuperJackpot_Start
# --- seen runA (item 144): sound requests / callouts in the first 12 s after each start, at a call site that is not a shared player; the id's word read at lr - 4. Credited by TIME (a function is credited to the first mode it spoke during); the call's function says whose code it is ---
callout 23 437 live.request code 0x16677c -  # seen runA +0 ms after the start, call 0x16677c in fn 0x1666fc; the id is not a constant at the call; also seen runB +0 ms
callout 23 569 live.request@2 code 0x1675fc -  # seen runA +30 ms after the start, call 0x1675fc in fn 0x166da4; the id is not a constant at the call; also seen runB +30 ms
callout 23 1244 live.callout code 0x1675ac -  # seen runA +7033 ms after the start, call 0x1675ac in fn 0x166da4; the id is not a constant at the call; also seen runB +7033 ms
callout 18 768 live.request code 0x104380 -  # seen runA +68 ms after the start, call 0x104380 in BDLSuperTrainStart::v[13]; the id is not a constant at the call
callout 19 670 live.request movw 0xefe60 e300029e  # seen runA +28 ms after the start, call 0xefe64 in fn 0xefdb0; also seen runB +38 ms
callout 19 1351 live.callout movw 0xf0100 e3000547  # seen runA +1034 ms after the start, call 0xf0108 in fn 0xefdb0; also seen runB +1050 ms
callout 19 332 live.request@2 code 0x1929f8 -  # seen runA +7536 ms after the start, call 0x1929f8 in fn 0x1929dc; the id is not a constant at the call
callout 19 331 live.request@3 code 0x1929f8 -  # seen runA +8551 ms after the start, call 0x1929f8 in fn 0x1929dc; the id is not a constant at the call
callout 20 895 live.request movw 0xc62b4 e300037f  # seen runA +68 ms after the start, call 0xc62b8 in BDLKingOfTheMonstersStart::v[13]
callout 20 2 live.request@2 imm 0xc6724 e3a00002  # seen runA +69 ms after the start, call 0xc6728 in BDLKingOfTheMonstersStart::v[13]
callout 20 1352 live.callout movw 0xc5754 e3000548  # seen runA +1969 ms after the start, call 0xc5758 in fn 0xc543c
callout 20 1353 live.callout@2 movw 0xc57d8 e3000549  # seen runA +10953 ms after the start, call 0xc57dc in fn 0xc543c
callout 25 1322 live.request code 0xb58e0 -  # seen runA +39 ms after the start, call 0xb58e0 in fn 0xb54f4; the id is not a constant at the call; also seen runB +35 ms
callout 26 871 live.request movw 0xe648c e3000367  # seen runA +67 ms after the start, call 0xe6490 in BDLMonsterZeroStart::v[13]
callout 26 2 live.request@2 imm 0xe68bc e3a00002  # seen runA +116 ms after the start, call 0xe68c0 in BDLMonsterZeroStart::v[13]
callout 26 1034 live.callout movw 0xea7ec e300040a  # seen runA +349 ms after the start, call 0xea7f0 in fn 0xea600
callout 26 513 live.request@3 movw 0xea880 e3000201  # seen runA +4017 ms after the start, call 0xea884 in fn 0xea600
callout 26 766 live.request@4 movw 0xea888 e30002fe  # seen runA +4017 ms after the start, call 0xea88c in fn 0xea600
callout 26 1035 live.callout@2 movw 0xea898 e300040b  # seen runA +4650 ms after the start, call 0xea89c in fn 0xea600
callout 26 512 live.request@5 imm 0xea6b4 e3a00c02  # seen runA +9050 ms after the start, call 0xea6b8 in fn 0xea600
callout 26 870 live.request@6 movw 0xea71c e3000366  # seen runA +9702 ms after the start, call 0xea720 in fn 0xea600
callout 26 1036 live.callout@3 movw 0xea724 e300040c  # seen runA +9703 ms after the start, call 0xea728 in fn 0xea600
# engine callout_play not located: not unique in the reference
# slots mapped from Pro 1.15: 41->42 42->43 43->44 44->45 45->46 46->47 47->48 48->49 49->50 50->51 51->52 52->53 53->54 54->55 55->56 56->57 57->58 58->59 59->60 60->61 61->62
# --- hand read (item 159, desk; the path edit emulator-proven by item 158 on Premium/LE 1.16): tank attack's shots
# are a six-entry PATH, not the lit mask. Each entry is 16 bytes {u64 position, u16 TANK lamp, u16 id, u32 0};
# tanks walk toward entry 2 (the Godzilla target) and die on the entry they stand on. Positions 0, 4 and 5 are
# also where tanks appear (seed words in code: 0x107484/0x108428, 0x1074a0, 0x107498/0x1083c4) and 2 is where they head
# (0x107440/0x1083b4/0x10841c), so those four stay as they are; 1 and 3 can be another shot the switches send alone,
# or none (= a copy of the neighbouring entry away from the target: the walk skips it, proven). The counted-shots
# words (v[46]) and the spot list (v[47]) follow the path. ---
number 4 path.0 0x800000000 path 0x630240 00000000,00000008,0b7f0072,00000000 word fixed seed  # TANK 1 (lamp 114): bit 35, where a tank appears
number 4 path.1 0x100000 path 0x630250 00100000,00000000,0b6d0090,00000000 word  # TANK 2 (lamp 144): Left ramp
number 4 path.2 0x80000 path 0x630260 00080000,00000000,0b6c0093,00000000 word fixed goal  # TANK 3 (lamp 147): Godzilla target, where every tank heads
number 4 path.3 0x800 path 0x630270 00000800,00000000,0b64009a,00000000 word  # TANK 4 (lamp 154): Top spinner (bit 11); path[3] := path[4] proven on Premium/LE 1.16 (item 158 live-3); this build's table is the same bytes (desk)
number 4 path.4 0x200000 path 0x630280 00200000,00000000,0b6e00ad,00000000 word fixed seed  # TANK 5 (lamp 173): Right ramp, where a tank appears
number 4 path.5 0x2000000000 path 0x630290 00000000,00000020,0b80007b,00000000 word fixed seed  # TANK 6 (lamp 123): bit 37, where a tank appears
number 4 path.counted.lo 0x380800 movwt 0x10654c 0x106554 03a00b02,03400038 word follows path  # v[46] counted shots (moveq/movteq), low half = the OR of the path
number 4 path.counted.hi 0x28 imm 0x106550 03a01028 word follows path  # v[46] counted shots, high half
number 4 path.spot.0 0x80000 qword 0x630210 00080000,00000000 word follows path  # v[47] spot list entry for path.2
number 4 path.spot.1 0x100000 qword 0x630218 00100000,00000000 word follows path  # v[47] spot list entry for path.1
number 4 path.spot.2 0x800 qword 0x630220 00000800,00000000 word follows path  # v[47] spot list entry for path.3
number 4 path.spot.3 0x200000 qword 0x630228 00200000,00000000 word follows path  # v[47] spot list entry for path.4
number 4 path.spot.4 0x800000000 qword 0x630230 00000000,00000008 word follows path  # v[47] spot list entry for path.0
number 4 path.spot.5 0x2000000000 qword 0x630238 00000000,00000020 word follows path  # v[47] spot list entry for path.5
# --- hand read (item 159, desk): battle vs ebirah needs N spins of each spinner; the counts are loaded per spinner
# by the refill 0x7f848 (ldr from the constructor's words 0x7f80c/0x7f81c, one of them shared by two spinners). Each load
# becomes `mov rd,#N` for a count of the app's own. Seen 15/40/15 at every START (item 158, Premium/LE 1.16). ---
number 12 spins.left 15 insn 0x7f850 e5905078 word  # ldr r5,[r0,#0x78] -> mov r5,#N: spins of the Left spinner (bit 0x200)
number 12 spins.top 40 insn 0x7f858 e594607c word  # ldr r6,[r4,#0x7c] -> mov r6,#N: spins of the Top spinner (bit 0x2000)
number 12 spins.shield 15 insn 0x7f868 e5945080 word  # ldr r5,[r4,#0x80] -> mov r5,#N: spins of the Shield ramp spinner (bit 0x20000)

build godzilla_le 1.16 sha1 ea8c6d36f130bfe1421b36c0a071bc66c9be4e99
# read by stock_modes.py: cmode_manager constructor 0xd4b64, 26 mode objects

mode 1 cmode_godzilla_multiball obj 0x7b4cb8 vtable 0x63a248 title_msg 3235
ctor 1 a 1 award 10 b 2 timer -   # cmode_mball, ctor 0xb173c called at 0xd55ec; compared against cmode_mball_null, 64 virtuals
shots 1 0x0 v[45] 0xb054c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 1 initial_mask.lo 0 imm 0xb054c e3a00000 word inert start_rewrites  # v[45] returns it (0x0)
number 1 initial_mask.hi 0 imm 0xb0550 e3a01000 word inert start_rewrites  # v[45] returns it (0x0)
number 1 title_msg 3235 movw 0x47744 e3000ca3 word
number 1 audit_started 211 imm 0xb5730 e3a000d3 word
number 1 audit_completed 212 imm 0xb5738 e3a000d4 word
start 1 start: cmode_manager_get(1) at 0x131e28 then v[8], in RuleBuildingLocks::v[25]
# 27 other cmode_manager_get(1) sites read it (is_running, is_active, or a slot not traced)
number 1 reset.adjustment 0 adj AD_GODZILLA_MULTIBALL_MUSIC_DEFAULT 201 e3a000c9 adjustment  # v[3] call 0xb062c; the id is imm 0xb0624, range 0..7
number 1 start.caward_add 500000 movwt 0xb30c4 0xb30cc e30a2120,e3402007 word  # v[8] call 0xb30e4
number 1 start.game_event.id 13 imm 0xb3108 e3a0000d word  # v[8] call 0xb3114
number 1 end.game_event.id 17 imm 0xb0d1c e3a00011 word  # v[10] call 0xb0d20
number 1 shot.show_start.id 174 imm 0xb2900 e3a000ae word  # v[42] call 0xb2918
number 1 shot.event_post_replacing.id 340 imm 0xb2c7c e3a00f55 word  # v[42] call 0xb2c8c
number 1 total_display.event_post_replacing.id 238 imm 0xb0ad4 e3a000ee word  # v[44] call 0xb0ae0
clip 1 godzilla_multiball_total movwt 0xb0b38 0xb0b40 e30a367c,e3403063  # v[44] at 0xb0b40: a name total_display loads
# display layers: BDLGodzillaMultiballBG BDLGodzillaMultiballStart

mode 2 cmode_mechagodzilla_multiball obj 0x7b4d78 vtable 0x63d1e8 title_msg 3234
ctor 2 a 1 award 11 b 3 timer -   # cmode_mball, ctor 0xd8d00 called at 0xd559c; compared against cmode_mball_null, 64 virtuals
shots 2 0x0 v[45] 0xd77a0, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 2 initial_mask.lo 0 imm 0xd77a0 e3a00000 word  # v[45] returns it (0x0)
number 2 initial_mask.hi 0 imm 0xd77a4 e3a01000 word  # v[45] returns it (0x0)
number 2 title_msg 3234 movw 0x4774c e3000ca2 word
number 2 audit_started 209 imm 0xdd124 e3a000d1 word
number 2 audit_completed 210 imm 0xdd12c e3a000d2 word
start 2 start: cmode_manager_get(2) at 0x160bc4 then v[8], in RuleMechagodzillaShield::v[25]
# 25 other cmode_manager_get(2) sites read it (is_running, is_active, or a slot not traced)
number 2 end.game_event.id 49 imm 0xd7e18 e3a00031 word  # v[10] call 0xd7e1c
number 2 total_display.event_post_replacing.id 239 imm 0xd7cc0 e3a000ef word  # v[44] call 0xd7ccc
clip 2 mecha_missile_groundblowsup movwt 0xd7d24 0xd7d2c e30d3550,e3403063  # v[44] at 0xd7d2c: a name total_display loads
clip 2 mecha_magnazilla2 movwt 0xdd158 0xdd15c e30d0528,e3400063  # BDLMechaGodzillaMultiballSuperJackpotLit::v[15] at 0xdd15c: a name the display layer loads
# display layers: BDLMechaGodzillaMultiballSuperJackpotLit BDLMechagodzillaMultiballBG BDLMechagodzillaMultiballStart

mode 3 cmode_bridge_attack_multiball obj 0x7b4e18 vtable 0x639c88 title_msg 3239
ctor 3 a 1 award 12 b 4 timer -   # cmode_mball, ctor 0xab954 called at 0xd554c; compared against cmode_mball_null, 64 virtuals
shots 3 ? v[45] 0xaa6cc returns the object's field +0x60: set by other code, not measured
number 3 title_msg 3239 movw 0xaf900 e3000ca7 word
number 3 audit_started 215 imm 0xaf908 e3a000d7 word
number 3 audit_completed 216 imm 0xaf910 e3a000d8 word
start 3 start: cmode_manager_get(3) at 0x133f7c then v[8], in fn 0x133ef0
# 17 other cmode_manager_get(3) sites read it (is_running, is_active, or a slot not traced)
number 3 start.adjustment 0 adj AD_BRIDGE_ATTACK_MULTIBALL_DIFFICULTY 207 e3a000cf adjustment  # v[8] call 0xabe4c; the id is imm 0xabe34, range 0..3
number 3 start.caward_add 250000 movwt 0xabe58 0xabe5c e30d2090,e3402003 word  # v[8] call 0xabe88
number 3 start.game_event.id 63 imm 0xabedc e3a0003f word  # v[8] call 0xabee8
number 3 end.game_event.id 65 imm 0xaa794 e3a00041 word  # v[10] call 0xaa798
number 3 total_display.event_post_replacing.id 254 imm 0xaa8ec e3a000fe word  # v[44] call 0xaa8f8
clip 3 BridgeDestructionProgress_3 movwt 0xaa944 0xaa94c e30533e0,e3403063  # v[44] at 0xaa94c: a name total_display loads
# display layers: BDLBridgeAttackMultiballBG

mode 4 cmode_tank_attack_multiball obj 0x7b4f30 vtable 0x640818 title_msg 3240
ctor 4 a 1 award 13 b 5 timer -   # cmode_mball, ctor 0x109964 called at 0xd54fc; compared against cmode_mball_null, 65 virtuals
shots 4 0x5800700800 v[45] 0x7e9a8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 4 initial_mask.lo 7342080 movwt 0x7e9a8 0x7e9b0 e3a00b02,e3400070 word inert inline_copy  # v[45] returns it (0x700800) (the low word is a mov)
number 4 initial_mask.hi 88 imm 0x7e9ac e3a01058 word inert inline_copy  # v[45] returns it (0x58)
number 4 title_msg 3240 movw 0x10dc44 e3000ca8 word
number 4 audit_started 217 imm 0x10dc4c e3a000d9 word
number 4 audit_completed 218 imm 0x10dc54 e3a000da word
start 4 start: cmode_manager_get(4) at 0x181bb8 then v[8], in fn 0x181b00
# 12 other cmode_manager_get(4) sites read it (is_running, is_active, or a slot not traced)
number 4 start.caward_add 250000 movwt 0x109dc0 0x109dc8 e30d2090,e3402003 word  # v[8] call 0x109dd8
number 4 start.game_event.id 50 imm 0x109e2c e3a00032 word  # v[8] call 0x109e38
number 4 end.game_event.id 52 imm 0x109f64 e3a00034 word  # v[10] call 0x109f68
number 4 shot.game_event.id 51 imm 0x10a1a4 e3a00033 word  # v[42] call 0x10a1a8
number 4 shot.caward_add ? code 0x10a23c - code  # v[42]: the value is computed before the call
number 4 shot.show_start.id 144 imm 0x10a298 e3a00090 word  # v[42] call 0x10a29c
number 4 total_display.event_post_replacing.id 241 imm 0x107e68 e3a000f1 word  # v[44] call 0x107e74
# display layers: BDLTankAttackMultiballBG BDLTankAttackMultiballStart

mode 5 cmode_saucer_attack_multiball obj 0x7b4ff8 vtable 0x63fb88 title_msg 3241
ctor 5 a 17 award 14 b 6 timer -   # cmode_mball, ctor 0xfea00 called at 0xd54ac; compared against cmode_mball_null, 64 virtuals
shots 5 0x0 v[45] 0xfda60, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 5 initial_mask.lo 0 imm 0xfda60 e3a00000 word  # v[45] returns it (0x0)
number 5 initial_mask.hi 0 imm 0xfda64 e3a01000 word  # v[45] returns it (0x0)
number 5 title_msg 3241 movw 0x102784 e3000ca9 word
number 5 audit_started 219 imm 0x10278c e3a000db word
number 5 audit_completed 220 imm 0x102794 e3a000dc word
start 5 start: cmode_manager_get(5) at 0x59ee0 then v[8], in fn 0x598b4
start 5 start: cmode_manager_get(5) at 0x175294 then v[8], in RuleSaucerAttack::v[25]
# 10 other cmode_manager_get(5) sites read it (is_running, is_active, or a slot not traced)
number 5 start.event_post_replacing.id 341 movw 0xfee58 e3000155 word  # v[8] call 0xfee64
number 5 start.caward_add 250000 movwt 0xfee6c 0xfee7c e30d2090,e3402003 word  # v[8] call 0xfee80
number 5 start.game_event.id 68 imm 0xfeecc e3a00044 word  # v[8] call 0xfeedc
number 5 end.game_event.id 70 imm 0xfdb74 e3a00046 word  # v[10] call 0xfdb78
number 5 total_display.event_post_replacing.id 253 imm 0xfe03c e3a000fd word  # v[44] call 0xfe048
clip 5 saucer_still movwt 0xfe094 0xfe09c e30531c0,e3403063  # v[44] at 0xfe09c: a name total_display loads
# display layers: BDLSaucerAttackMultiballBG

mode 6 cmode_battle_vs_megalon_and_gigan_mb obj 0x7b5118 vtable 0x638d58 title_msg 3263
ctor 6 a 25 award 15 b 7 timer -   # cmode_mball, ctor 0x9ff70 called at 0xd545c; compared against cmode_mball_null, 65 virtuals
shots 6 0x0 v[45] 0x9f17c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 6 initial_mask.lo 0 imm 0x9f17c e3a00000 word  # v[45] returns it (0x0)
number 6 initial_mask.hi 0 imm 0x9f180 e3a01000 word  # v[45] returns it (0x0)
start 6 select: slot 5 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 6 select.slot5.mode_id 6 data 0x64276c 00000006 word  # which mode the selector's slot 5 starts
number 6 title_msg 3263 movw 0xa2c84 e3000cbf word
number 6 audit_started 259 movw 0xa2c8c e3000103 word
number 6 audit_completed 260 imm 0xa2c94 e3a00f41 word
# 15 other cmode_manager_get(6) sites read it (is_running, is_active, or a slot not traced)
number 6 start.caward_add 250000 movwt 0xa0164 0xa0170 e30d2090,e3402003 word  # v[8] call 0xa017c
number 6 start.game_event.id 39 imm 0xa01ac e3a00027 word  # v[8] call 0xa01b0
number 6 end.game_event.id 42 imm 0x9f254 e3a0002a word  # v[10] call 0x9f258
number 6 end.game_event.id@2 40 imm 0x9f2c0 e3a00028 word  # v[10] call 0x9f2c4
number 6 end.game_event.id@3 41 imm 0x9f2f8 e3a00029 word  # v[10] call 0x9f2fc
number 6 total_display.event_post_replacing.id 247 imm 0x9f474 e3a000f7 word  # v[44] call 0x9f480
clip 6 Megalon_gigan_jetjag_godzilla11 movwt 0x9f4cc 0x9f4d4 e30932b8,e3403063  # v[44] at 0x9f4d4: a name total_display loads
clip 6 Megalon_gigan_highfive movwt 0xa2cc0 0xa2cc4 e3090280,e3400063  # BDLBattleVsMegalonAndGiganMBStart::v[15] at 0xa2cc4: a name the display layer loads
clip 6 Megalon_gigan_jetjag_godzilla4 movwt 0xa2cd4 0xa2cd8 e3090298,e3400063  # BDLBattleVsMegalonAndGiganMBSuperJackpotLit::v[15] at 0xa2cd8: a name the display layer loads
# display layers: BDLBattleVsMegalonAndGiganMBStart BDLBattleVsMegalonAndGiganMBSuperJackpotLit BDLBattleVsMegalonAndGiganMB_BG

mode 7 cmode_planet_x_multiball obj 0x7b51a8 vtable 0x63f2c0 title_msg 3267
ctor 7 a 17 award 16 b 13 timer -   # cmode_mball, ctor 0xf6718 called at 0xd540c; compared against cmode_mball_null, 65 virtuals
shots 7 0x0 v[45] 0xf4ca4, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 7 initial_mask.lo 0 imm 0xf4ca4 e3a00000 word inert start_rewrites  # v[45] returns it (0x0)
number 7 initial_mask.hi 0 imm 0xf4ca8 e3a01000 word inert start_rewrites  # v[45] returns it (0x0)
number 7 title_msg 3267 movw 0xfc6c0 e3000cc3 word
number 7 audit_started 221 imm 0xfc6c8 e3a000dd word
number 7 audit_completed 222 imm 0xfc6d0 e3a000de word
start 7 start: cmode_manager_get(7) at 0x59f30 then v[8], in fn 0x598b4
# 31 other cmode_manager_get(7) sites read it (is_running, is_active, or a slot not traced)
number 7 total_display.event_post_replacing.id 257 movw 0xf5204 e3000101 word  # v[44] call 0xf5210
clip 7 planetx_outtro movwt 0xf525c 0xf5264 e30f1880,e3401063  # v[44] at 0xf5264: a name total_display loads
number 7 v63.caward_add 250000 movwt 0xf95ec 0xf95f8 e30d2090,e3402003 word  # v[64] new call 0xf9614
number 7 v63.event_post_replacing.id 343 movw 0xf964c e3000157 word  # v[64] new call 0xf9650
number 7 v63.game_event.id 75 imm 0xf9664 e3a0004b word  # v[64] new call 0xf9668
clip 7 PlanetX_Normal_Loop movwt 0xf4ce8 0xf4cec 130109d4,13400063  # BDLPlanetXMultiballBG::v[14] at 0xf4cec: a name the display layer loads
# display layers: BDLPlanetXMultiballBG BDLPlanetXMultiballStart

mode 8 cmode_monster_zero_victory_multiball obj 0x7b5230 vtable 0x63e498 title_msg 3270
ctor 8 a 17 award 17 b 14 timer -   # cmode_mball, ctor 0xeb228 called at 0xd53bc; compared against cmode_mball_null, 64 virtuals
shots 8 ? v[45] 0xf16dc computes the lit mask: code
number 8 title_msg 3270 movw 0xf0918 e3000cc6 word
number 8 audit_started 225 imm 0xf0920 e3a000e1 word
number 8 audit_completed 226 imm 0xf0928 e3a000e2 word
start 8 start: cmode_manager_get(8) at 0xea5b0 then v[8], in fn 0xea514
# 14 other cmode_manager_get(8) sites read it (is_running, is_active, or a slot not traced)
number 8 start.game_event.id 125 imm 0xeca44 e3a0007d word  # v[8] call 0xeca50
number 8 end.game_event.id 126 imm 0xe79f8 e3a0007e word  # v[10] call 0xe79fc
number 8 shot.game_event.id 123 imm 0xec10c e3a0007b word  # v[42] call 0xec110

mode 9 cmode_terror_of_mechagodzilla obj 0x7b5298 vtable 0x6417a8 title_msg 3271
ctor 9 a 17 award 18 b 15 timer -   # cmode_mball, ctor 0x118a8c called at 0xd536c; compared against cmode_mball_null, 65 virtuals
shots 9 0x0 v[45] 0x11c548, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 9 initial_mask.lo 0 imm 0x11c548 e3a00000 word  # v[45] returns it (0x0)
number 9 initial_mask.hi 0 imm 0x11c54c e3a01000 word  # v[45] returns it (0x0)
number 9 title_msg 3271 movw 0x11c510 e3000cc7 word
number 9 audit_started 227 imm 0x11c518 e3a000e3 word
number 9 audit_completed 228 imm 0x11c520 e3a000e4 word
start 9 start: cmode_manager_get(9) at 0x15a70c then v[8], in RuleKingOfTheMonsters::v[25]
# 26 other cmode_manager_get(9) sites read it (is_running, is_active, or a slot not traced)
number 9 start.caward_add 250000 movwt 0x116d5c 0x116d6c e30d2090,e3402003 word  # v[8] call 0x116d74
number 9 start.event_post_replacing.id 344 imm 0x116d80 e3a00f56 word  # v[8] call 0x116d88
number 9 start.game_event.id 118 imm 0x116dd0 e3a00076 word  # v[8] call 0x116dd8
number 9 end.game_event.id 120 imm 0x1133c8 e3a00078 word  # v[10] call 0x1133cc
number 9 end.game_event.id@2 119 imm 0x113400 e3a00077 word  # v[10] call 0x113404
number 9 shot.fx.n 200 imm 0x118c9c e3a000c8 word  # v[42] call 0x118ca0
number 9 shot.show_start.id 145 imm 0x118ca4 e3a00091 word  # v[42] call 0x118ca8
number 9 shot.show_start.id@2 348 imm 0x118cc0 e3a00f57 word  # v[42] call 0x118cc4
number 9 shot.show_start.id@3 342 movw 0x118d08 e3000156 word  # v[42] call 0x118d0c
number 9 shot.show_start.id@4 359 movw 0x118d70 e3000167 word  # v[42] call 0x118d74
callout 9 403 shot.sound_request_play movw 0x118f9c e3000193  # v[42] call 0x118fa0
number 9 shot.fx.n@2 200 imm 0x118fac e3a000c8 word  # v[42] call 0x118fb0
number 9 shot.show_start.id@5 145 imm 0x118fb4 e3a00091 word  # v[42] call 0x118fb8
number 9 shot.show_start.id@6 348 imm 0x118fd0 e3a00f57 word  # v[42] call 0x118fd4
number 9 shot.show_start.id@7 342 movw 0x119018 e3000156 word  # v[42] call 0x11901c
callout 9 402 shot.sound_request_play@2 movw 0x1193c0 e3000192  # v[42] call 0x1193c4
number 9 shot.fx.n@3 200 imm 0x1193d0 e3a000c8 word  # v[42] call 0x1193d4
number 9 total_display.event_post_replacing.id 259 movw 0x113764 e3000103 word  # v[44] call 0x113770
clip 9 terror_outtro movwt 0x1137bc 0x1137c8 e30129b8,e3402064  # v[44] at 0x1137c8: a name total_display loads
callout 9 272 v63.sound_request_play imm 0x116edc 13a00e11  # v[64] new call 0x116ee0 (set by a conditional instruction)
callout 9 359 v63.sound_request_play@2 movw 0x116f28 e3000167  # v[64] new call 0x116f30
clip 9 MainTitle_Artbox movwt 0x113f70 0x113f78 e30b1f8c,e3401063  # BDLTerrorOfMechagodzillaStart::v[13] at 0x113f78: a name the display layer loads
# display layers: BDLTerrorOfMechagodzillaBG BDLTerrorOfMechagodzillaStart BDLTerrorOfMechagodzillaTotal

mode 10 cmode_king_of_the_monsters_multiball obj 0x7b5310 vtable 0x63b520 title_msg ?
ctor 10 a 17 award 27 b 16 timer -   # cmode_mball, ctor 0xc332c called at 0xd531c; compared against cmode_mball_null, 65 virtuals
shots 10 0x1800700800 v[45] 0xd28d0, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop
number 10 initial_mask.lo 7342080 movwt 0xd28d0 0xd28d8 e3a00b02,e3400070 word  # v[45] returns it (0x700800) (the low word is a mov)
number 10 initial_mask.hi 24 imm 0xd28d4 e3a01018 word  # v[45] returns it (0x18)
start 10 start: cmode_manager_get(10) at 0xc28e0 then v[8], in fn 0xc28a4
# 28 other cmode_manager_get(10) sites read it (is_running, is_active, or a slot not traced)
number 10 shot.adjustment 5 adj AD_KOTM_TIME_ATTACK_BOUNTY_ADD_TIME 235 e3a000eb adjustment  # v[42] call 0xc53bc; the id is imm 0xc53b8, range 5..15
number 10 shot.caward_add ? code 0xc54ec - code  # v[42]: the value is computed before the call
number 10 shot.event_post_replacing.id 345 movw 0xc55d8 e3000159 word  # v[42] call 0xc55e0
number 10 shot.caward_add@2 ? code 0xc5754 - code  # v[42]: the value is computed before the call
number 10 shot.adjustment@2 3 adj AD_KOTM_TIME_ATTACK_SECTION_COMPLETE_ADD_TIME 234 e3a000ea adjustment  # v[42] call 0xc59a8; the id is imm 0xc59a4, range 3..15
number 10 shot.caward_add@3 ? code 0xc5a34 - code  # v[42]: the value is computed before the call
clip 10 kotm_stage2intro movwt 0xd296c 0xd2970 e30b0ba0,e3400063  # BDLKingOfTheMonstersMultiballStart::v[15] at 0xd2970: a name the display layer loads
# display layers: BDLKingOfTheMonstersMultiballStart

mode 11 cmode_monster_island_madness obj 0x7b5388 vtable 0x63d768 title_msg 3274
ctor 11 a 17 award 28 b 17 timer -   # cmode_mball, ctor 0xdff24 called at 0xd52cc; compared against cmode_mball_null, 70 virtuals
shots 11 0x5800700800 v[45] 0xde218, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 11 initial_mask.lo 7342080 movwt 0xde218 0xde220 e3a00b02,e3400070 word  # v[45] returns it (0x700800) (the low word is a mov)
number 11 initial_mask.hi 88 imm 0xde21c e3a01058 word  # v[45] returns it (0x58)
number 11 title_msg 3274 movw 0xe1778 e3000cca word
number 11 audit_started 241 imm 0xe1780 e3a000f1 word
number 11 audit_completed 242 imm 0xe1788 e3a000f2 word
start 11 start: cmode_manager_get(11) at 0xc55ac then v[8], in cmode_king_of_the_monsters_multiball::v[42]
# 20 other cmode_manager_get(11) sites read it (is_running, is_active, or a slot not traced)
number 11 start.adjustment 75 adj AD_MONSTER_ISLAND_MADNESS_TIMER 229 e3a000e5 adjustment  # v[8] call 0xe0a3c; the id is imm 0xe0a34, range 90..60
number 11 start.game_event.id 145 imm 0xe0df4 e3a00091 word  # v[8] call 0xe0dfc
number 11 end.game_event.id 146 imm 0xde2a8 e3a00092 word  # v[10] call 0xde2ac
number 11 total_display.event_post_replacing.id 261 movw 0xde428 e3000105 word  # v[44] call 0xde434
clip 11 megalon_monster_island_01 movwt 0xde48c 0xde498 e30d2b28,e3402063  # v[44] at 0xde498: a name total_display loads
clip 11 kotm_game_over movwt 0xdf500 0xdf508 e30d1b6c,e3401063  # BDLMonsterIslandMadnessTotal::v[7] at 0xdf508: a name the display layer loads
# display layers: BDLMonsterIslandMadnessBG BDLMonsterIslandMadnessStart BDLMonsterIslandMadnessTotal

mode 12 cmode_battle_vs_ebirah obj 0x7b53f0 vtable 0x636d70 title_msg 3257
ctor 12 a 10 award 19 b 7 timer 0   # cmode_battle, ctor 0x80fb8 called at 0xd5280; compared against cmode_battle, 64 virtuals
shots 12 0x22200 v[45] 0x7feb8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left spinner, top spinner, right spinner
number 12 initial_mask.lo 139776 movwt 0x7feb8 0x7fec0 e3a00c22,e3400002 word inert start_rewrites  # v[45] returns it (0x22200) (the low word is a mov)
number 12 initial_mask.hi 0 imm 0x7febc e3a01000 word inert start_rewrites  # v[45] returns it (0x0)
start 12 select: slot 0 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 12 select.slot0.mode_id 12 data 0x642730 0000000c word  # which mode the selector's slot 0 starts
number 12 title_msg 3257 movw 0x8585c e3000cb9 word
number 12 audit_started 249 imm 0x85864 e3a000f9 word
number 12 audit_completed 250 imm 0x8586c e3a000fa word
start 12 start: cmode_manager_get(12) at 0xc6158 then v[8], in cmode_king_of_the_monsters::v[8]
# 21 other cmode_manager_get(12) sites read it (is_running, is_active, or a slot not traced)
number 12 start.caward_add 250000 movwt 0x85474 0x8547c e30d2090,e3402003 word  # v[8] call 0x85488
number 12 start.game_event.id 18 imm 0x854fc e3a00012 word  # v[8] call 0x8550c
number 12 start.caward_add@2 250000 movwt 0x85544 0x8554c e30d2090,e3402003 word  # v[8] call 0x8555c
number 12 end.game_event.id 20 imm 0x85728 e3a00014 word  # v[10] call 0x8572c
number 12 shot.caward_add ? code 0x817e4 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@2 ? code 0x81854 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@3 25000000 movwt 0x819a4 0x819b0 e3072840,e340217d word  # v[42] call 0x819bc
number 12 shot.show_start.id 347 movw 0x81a18 e300015b word  # v[42] call 0x81a1c
number 12 shot.show_start.id@2 359 movw 0x81a60 e3000167 word  # v[42] call 0x81a64
number 12 shot.caward_add@4 ? code 0x81b28 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@5 ? code 0x81bc0 - code  # v[42]: the value is computed before the call
number 12 shot.caward_build.value 0 imm 0x81be8 e3a01000 word  # v[42] call 0x81bfc
number 12 shot.caward_add@6 ? code 0x81c78 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@7 ? code 0x81d10 - code  # v[42]: the value is computed before the call
number 12 shot.caward_build.value@2 0 imm 0x81d38 e3a01000 word  # v[42] call 0x81d4c
number 12 shot.caward_add@8 ? code 0x81da4 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@9 ? code 0x81dc0 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@10 ? code 0x81e04 - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@11 ? code 0x81e60 - code  # v[42]: the value is computed before the call
number 12 shot.caward_build.value@3 0 imm 0x81e88 e3a01000 word  # v[42] call 0x81e9c
number 12 shot.caward_add@12 25000000 movwt 0x81ea4 0x81eac e3072840,e340217d word  # v[42] call 0x81eb8
number 12 shot.caward_add@13 ? code 0x81f5c - code  # v[42]: the value is computed before the call
number 12 shot.caward_add@14 ? code 0x8207c - code  # v[42]: the value is computed before the call
number 12 shot.game_event.id 19 imm 0x82114 e3a00013 word  # v[42] call 0x82118
number 12 shot.game_event.id@2 31 imm 0x82168 e3a0001f word  # v[42] call 0x8216c
number 12 shot.caward_add@15 ? code 0x821b8 - code  # v[42]: the value is computed before the call
number 12 total_display.event_post_replacing.id 249 imm 0x80308 e3a000f9 word  # v[44] call 0x80314
clip 12 ebirah_fail movwt 0x803b0 0x803b4 e30731e4,e3403063  # v[44] at 0x803b4: a name total_display loads
clip 12 ebirah_outtro movwt 0x803f0 0x803f8 e30731d4,e3403063  # v[44] at 0x803f8: a name total_display loads
number 12 timer.seconds 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # v[57] call 0x8046c; the id is imm 0x80468, range 30..70
number 12 timer.v57 60 adj AD_BATTLE_VS_EBIRAH_TIMER 212 e3a000d4 adjustment  # v[58] call 0x7ff58; the id is imm 0x7ff54, range 30..70
clip 12 ebirah_attack1 movwt 0x858a4 0x858a8 e3070040,e3400063  # BDLBattleVSEbirahStart::v[15] at 0x858a8: a name the display layer loads
# display layers: BDLBattleVSEbirahBG BDLBattleVSEbirahStart

mode 13 cmode_battle_vs_titanosaurus obj 0x7b54d0 vtable 0x639608 title_msg 3258
ctor 13 a 10 award 20 b 7 timer 1   # cmode_battle, ctor 0xa4de4 called at 0xd522c; compared against cmode_battle, 65 virtuals
shots 13 0x0 v[45] 0xa3dac, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 13 initial_mask.lo 0 imm 0xa3dac e3a00000 word inert start_rewrites  # v[45] returns it (0x0)
number 13 initial_mask.hi 0 imm 0xa3db0 e3a01000 word inert start_rewrites  # v[45] returns it (0x0)
start 13 select: slot 1 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 13 select.slot1.mode_id 13 data 0x64273c 0000000d word  # which mode the selector's slot 1 starts
number 13 title_msg 3258 movw 0xa8efc e3000cba word
number 13 audit_started 251 imm 0xa8f04 e3a000fb word
number 13 audit_completed 252 imm 0xa8f0c e3a000fc word
start 13 start: cmode_manager_get(13) at 0xc6180 then v[8], in cmode_king_of_the_monsters::v[8]
# 24 other cmode_manager_get(13) sites read it (is_running, is_active, or a slot not traced)
number 13 start.caward_add 250000 movwt 0xa8bdc 0xa8be4 e30d2090,e3402003 word  # v[8] call 0xa8bf4
number 13 start.caward_add@2 250000 movwt 0xa8bfc 0xa8c04 e30d2090,e3402003 word  # v[8] call 0xa8c10
number 13 start.game_event.id 21 imm 0xa8c28 e3a00015 word  # v[8] call 0xa8c2c
number 13 end.game_event.id 23 imm 0xa8dc8 e3a00017 word  # v[10] call 0xa8dcc
number 13 shot.game_event.id 22 imm 0xa5d60 e3a00016 word  # v[42] call 0xa5d64
number 13 shot.caward_add 1000000 movwt 0xa5df4 0xa5dfc e3042240,e340200f word  # v[42] call 0xa5e0c
number 13 shot.event_post_replacing.id 337 movw 0xa5ea0 e3000151 word  # v[42] call 0xa5eac
number 13 shot.caward_add@2 1000000 movwt 0xa5eb0 0xa5eb8 e3042240,e340200f word  # v[42] call 0xa5ec4
number 13 shot.game_event.id@2 32 imm 0xa5fdc e3a00020 word  # v[42] call 0xa5fe0
number 13 total_display.event_post_replacing.id 250 imm 0xa411c e3a000fa word  # v[44] call 0xa4128
clip 13 titanosaurus_fail movwt 0xa41c4 0xa41c8 e3093ab0,e3403063  # v[44] at 0xa41c8: a name total_display loads
clip 13 titan_godzilla_titanflee movwt 0xa4204 0xa420c e3093a94,e3403063  # v[44] at 0xa420c: a name total_display loads
number 13 timer.seconds 60 adj AD_BATTLE_VS_TITANOSAURUS_TIMER 213 e3a000d5 adjustment  # v[57] call 0xa42dc; the id is imm 0xa42d8, range 30..70
number 13 timer.v57 60 adj AD_BATTLE_VS_TITANOSAURUS_TIMER 213 e3a000d5 adjustment  # v[58] call 0xa3e48; the id is imm 0xa3e44, range 30..70
number 13 v63.fx.n 100 imm 0x80000 e3a00064 word  # v[64] new call 0x80010
clip 13 GodzillaVsTitanosaurus_Intro movwt 0xa8f44 0xa8f48 e3090978,e3400063  # BDLBattleVSTitanosaurusStart::v[15] at 0xa8f48: a name the display layer loads
# display layers: BDLBattleVSTitanosaurusBG BDLBattleVSTitanosaurusStart

mode 14 cmode_battle_vs_gigan obj 0x7b5588 vtable 0x637ab8 title_msg 3259
ctor 14 a 10 award 21 b 7 timer 2   # cmode_battle, ctor 0x8d050 called at 0xd51d4; compared against cmode_battle, 64 virtuals
shots 14 ? v[45] 0x8c858 returns the object's field +0x78: set by other code, not measured
start 14 select: slot 2 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 14 select.slot2.mode_id 14 data 0x642748 0000000e word  # which mode the selector's slot 2 starts
number 14 title_msg 3259 movw 0x911f4 e3000cbb word
number 14 audit_started 253 imm 0x911fc e3a000fd word
number 14 audit_completed 254 imm 0x91204 e3a000fe word
start 14 start: cmode_manager_get(14) at 0xc61a8 then v[8], in cmode_king_of_the_monsters::v[8]
# 17 other cmode_manager_get(14) sites read it (is_running, is_active, or a slot not traced)
number 14 start.caward_add 250000 movwt 0x90ee4 0x90eec e30d2090,e3402003 word  # v[8] call 0x90efc
number 14 start.caward_add@2 250000 movwt 0x90f04 0x90f0c e30d2090,e3402003 word  # v[8] call 0x90f18
number 14 start.game_event.id 24 imm 0x90f30 e3a00018 word  # v[8] call 0x90f34
number 14 end.game_event.id 26 imm 0x910c0 e3a0001a word  # v[10] call 0x910c4
number 14 shot.game_event.id 25 imm 0x90a10 e3a00019 word  # v[42] call 0x90a14
number 14 shot.game_event.id@2 33 imm 0x90a74 e3a00021 word  # v[42] call 0x90a78
number 14 shot.event_post_replacing.id 335 movw 0x90b0c e300014f word  # v[42] call 0x90b20
number 14 total_display.event_post_replacing.id 251 imm 0x8cb3c e3a000fb word  # v[44] call 0x8cb48
clip 14 gigan_fail movwt 0x8cbe4 0x8cbe8 e3073e8c,e3403063  # v[44] at 0x8cbe8: a name total_display loads
clip 14 gigan_ghidorah_vs_godzilla29 movwt 0x8cc24 0x8cc2c e3073e6c,e3403063  # v[44] at 0x8cc2c: a name total_display loads
number 14 timer.seconds 60 adj AD_BATTLE_VS_GIGAN_TIMER 214 e3a000d6 adjustment  # v[57] call 0x8cca0; the id is imm 0x8cc9c, range 30..70
number 14 timer.v57 60 adj AD_BATTLE_VS_GIGAN_TIMER 214 e3a000d6 adjustment  # v[58] call 0x8c908; the id is imm 0x8c904, range 30..70
clip 14 gigan_good_intro movwt 0x9123c 0x91240 e3070d38,e3400063  # BDLBattleVSGiganStart::v[15] at 0x91240: a name the display layer loads
# display layers: BDLBattleVSGiganBG BDLBattleVSGiganStart

mode 15 cmode_battle_vs_megalon obj 0x7b56b8 vtable 0x638668 title_msg 3260
ctor 15 a 10 award 22 b 7 timer 3   # cmode_battle, ctor 0x99840 called at 0xd517c; compared against cmode_battle, 64 virtuals
shots 15 0x5800700800 v[45] 0x9867c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 15 initial_mask.lo 7342080 movwt 0x9867c 0x98684 e3a00b02,e3400070 word inert start_rewrites  # v[45] returns it (0x700800) (the low word is a mov)
number 15 initial_mask.hi 88 imm 0x98680 e3a01058 word inert start_rewrites  # v[45] returns it (0x58)
start 15 select: slot 3 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 15 select.slot3.mode_id 15 data 0x642754 0000000f word  # which mode the selector's slot 3 starts
number 15 title_msg 3260 movw 0x9d964 e3000cbc word
number 15 audit_started 255 imm 0x9d96c e3a000ff word
number 15 audit_completed 256 imm 0x9d974 e3a00c01 word
start 15 start: cmode_manager_get(15) at 0xc61d0 then v[8], in cmode_king_of_the_monsters::v[8]
# 24 other cmode_manager_get(15) sites read it (is_running, is_active, or a slot not traced)
number 15 start.caward_add 250000 movwt 0x9d630 0x9d638 e30d2090,e3402003 word  # v[8] call 0x9d648
number 15 start.caward_add@2 250000 movwt 0x9d650 0x9d658 e30d2090,e3402003 word  # v[8] call 0x9d664
number 15 start.game_event.id 27 imm 0x9d67c e3a0001b word  # v[8] call 0x9d680
number 15 end.game_event.id 30 imm 0x9d830 e3a0001e word  # v[10] call 0x9d834
number 15 shot.caward_build.value 0 imm 0x9cf68 e3a01000 word  # v[42] call 0x9cf78
number 15 shot.show_start.id 348 imm 0x9cfe0 e3a00f57 word  # v[42] call 0x9cfe4
number 15 shot.show_start.id@2 359 movw 0x9d028 e3000167 word  # v[42] call 0x9d02c
number 15 shot.event_post_replacing.id 336 imm 0x9d138 e3a00e15 word  # v[42] call 0x9d14c
number 15 total_display.event_post_replacing.id 252 imm 0x989cc e3a000fc word  # v[44] call 0x989d8
clip 15 megalon_fail movwt 0x98a70 0x98a78 e3083b8c,e3403063  # v[44] at 0x98a78: a name total_display loads
clip 15 Megalon_gigan_jetjag_godzilla41 movwt 0x98ab0 0x98ab8 e3083b6c,e3403063  # v[44] at 0x98ab8: a name total_display loads
number 15 timer.seconds 60 adj AD_BATTLE_VS_MEGALON_TIMER 215 e3a000d7 adjustment  # v[57] call 0x98b90; the id is imm 0x98b8c, range 30..70
number 15 timer.v57 60 adj AD_BATTLE_VS_MEGALON_TIMER 215 e3a000d7 adjustment  # v[58] call 0x98744; the id is imm 0x98740, range 30..70
clip 15 GodzillaVsMegalon_Intro movwt 0x9d9ac 0x9d9b0 e30809e8,e3400063  # BDLBattleVSMegalonStart::v[15] at 0x9d9b0: a name the display layer loads
# display layers: BDLBattleVSMegalonBG BDLBattleVSMegalonStart

mode 16 cmode_battle_vs_king_ghidorah obj 0x7b57d0 vtable 0x638018 title_msg 3261
ctor 16 a 26 award 23 b 7 timer 5   # cmode_battle, ctor 0x93b90 called at 0xd5124; compared against cmode_battle, 64 virtuals
shots 16 ? v[45] 0x92cc4 returns the object's field +0x78: set by other code, not measured
start 16 select: slot 4 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 16 select.slot4.mode_id 16 data 0x642760 00000010 word  # which mode the selector's slot 4 starts
number 16 title_msg 3261 movw 0x97754 e3000cbd word
number 16 audit_started 257 movw 0x9775c e3000101 word
number 16 audit_completed 258 movw 0x97764 e3000102 word
# 18 other cmode_manager_get(16) sites read it (is_running, is_active, or a slot not traced)
number 16 start.adjustment 30 adj AD_BATTLE_VS_KING_GHIDORAH_BALL_SAVE_TIMER 217 e3a000d9 adjustment  # v[8] call 0x972c0; the id is imm 0x972bc, range 28..40
number 16 start.caward_add 250000 movwt 0x97418 0x97424 e30d2090,e3402003 word  # v[8] call 0x97430
number 16 start.game_event.id 35 imm 0x9744c e3a00023 word  # v[8] call 0x97450
number 16 start.event_post_replacing.id 338 movw 0x97478 e3000152 word  # v[8] call 0x9747c
number 16 end.game_event.id 38 imm 0x97540 e3a00026 word  # v[10] call 0x97544
number 16 end.game_event.id@2 36 imm 0x97580 e3a00024 word  # v[10] call 0x97584
number 16 end.game_event.id@3 37 imm 0x975b8 e3a00025 word  # v[10] call 0x975bc
number 16 shot.event_post_replacing.id 215 imm 0x9541c e3a000d7 word  # v[42] call 0x95428
number 16 total_display.event_post_replacing.id 246 imm 0x92e9c e3a000f6 word  # v[44] call 0x92ea8
clip 16 ghidorah_victory movwt 0x92ef4 0x92efc e3083344,e3403063  # v[44] at 0x92efc: a name total_display loads
number 16 timer.seconds 75 adj AD_BATTLE_VS_KING_GHIDORAH_TIMER 216 e3a000d8 adjustment  # v[57] call 0x92fd8; the id is imm 0x92fd4, range 30..90
number 16 timer.v57 75 adj AD_BATTLE_VS_KING_GHIDORAH_TIMER 216 e3a000d8 adjustment  # v[58] call 0x92d50; the id is imm 0x92d4c, range 30..90
clip 16 mothra_rodan_intro movwt 0x97790 0x97794 e3080330,e3400063  # BDLBattleVSKingGhidorahStart::v[15] at 0x97794: a name the display layer loads
# display layers: BDLBattleVSKingGhidorahBG BDLBattleVSKingGhidorahStart

mode 17 cmode_battle_vs_ghidorah_and_gigan obj 0x7b5880 vtable 0x6374f8 title_msg 3265
ctor 17 a 26 award 24 b 7 timer 6   # cmode_battle, ctor 0x88228 called at 0xd50cc; compared against cmode_battle, 64 virtuals
shots 17 ? v[45] 0x8704c returns the object's field +0x78: set by other code, not measured
start 17 select: slot 6 of the 7-entry selector table 0x64272c {slot, mode id, 0} (12 13 14 15 16 6 17); the screen that reads it is not traced by the tool
number 17 select.slot6.mode_id 17 data 0x642778 00000011 word  # which mode the selector's slot 6 starts
number 17 title_msg 3265 movw 0x8b988 e3000cc1 word
number 17 audit_started 261 movw 0x8b990 e3000105 word
number 17 audit_completed 262 movw 0x8b998 e3000106 word
# 16 other cmode_manager_get(17) sites read it (is_running, is_active, or a slot not traced)
number 17 start.adjustment 0 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_DIFFICULTY 220 e3a000dc adjustment  # v[8] call 0x8b554; the id is imm 0x8b550, range 0..2
number 17 start.adjustment@2 30 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_BALL_SAVE_TIMER 219 e3a000db adjustment  # v[8] call 0x8b584; the id is imm 0x8b570, range 28..40
number 17 start.caward_add 250000 movwt 0x8b64c 0x8b658 e30d2090,e3402003 word  # v[8] call 0x8b664
number 17 start.game_event.id 43 imm 0x8b680 e3a0002b word  # v[8] call 0x8b684
number 17 start.event_post_replacing.id 339 movw 0x8b6ac e3000153 word  # v[8] call 0x8b6b0
number 17 end.game_event.id 46 imm 0x8b774 e3a0002e word  # v[10] call 0x8b778
number 17 end.game_event.id@2 44 imm 0x8b7b4 e3a0002c word  # v[10] call 0x8b7b8
number 17 end.game_event.id@3 45 imm 0x8b7ec e3a0002d word  # v[10] call 0x8b7f0
number 17 shot.caward_add 50000 movw 0x89628 e30c2350 word  # v[42] call 0x89634
number 17 shot.show_start.id 348 imm 0x89700 e3a00f57 word  # v[42] call 0x89704
number 17 shot.show_start.id@2 342 movw 0x89758 e3000156 word  # v[42] call 0x8975c
number 17 shot.show_start.id@3 359 movw 0x897e8 e3000167 word  # v[42] call 0x897ec
number 17 shot.fx.n 334 movw 0x89868 e300014e word  # v[42] call 0x89870
number 17 shot.event_post_replacing.id 215 imm 0x8987c e3a000d7 word  # v[42] call 0x89884
number 17 shot.caward_add@2 7500000 movwt 0x8998c 0x89998 e30720e0,e3402072 word  # v[42] call 0x899a4
number 17 total_display.event_post_replacing.id 248 imm 0x87328 e3a000f8 word  # v[44] call 0x87334
clip 17 gigan_ghidorah_vs_godzilla81 movwt 0x87380 0x87388 e30737d0,e3403063  # v[44] at 0x87388: a name total_display loads
number 17 timer.seconds 75 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER 218 e3a000da adjustment  # v[57] call 0x87464; the id is imm 0x87460, range 30..90
number 17 timer.v57 75 adj AD_BATTLE_VS_GHIDORAH_AND_GIGAN_TIMER 218 e3a000da adjustment  # v[58] call 0x870d8; the id is imm 0x870d4, range 30..90
clip 17 ghidorah_gigan_intronew movwt 0x8b9c4 0x8b9c8 e30707b8,e3400063  # BDLBattleVSGhidorahAndGiganStart::v[15] at 0x8b9c8: a name the display layer loads
# display layers: BDLBattleVSGhidorahAndGiganBG BDLBattleVSGhidorahAndGiganStart

mode 18 cmode_super_train obj 0x7b5938 vtable 0x6402b8 title_msg 3244
ctor 18 a 18 award 25 b 11 timer 17   # cmode_timed, ctor 0x1040b4 called at 0xd5074; compared against cmode_timed, 70 virtuals
number 18 timer.v57 30 code 0x7fdc8 - code shared 5  # the base default: mov #30 at 0x7fdc8, 0x11dca8 - all of them, or a hook
shots 18 0x300000 v[45] 0x102e78, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left ramp, right ramp
number 18 initial_mask.lo 3145728 imm 0x102e78 e3a00603 word  # v[45] returns it (0x300000)
number 18 initial_mask.hi 0 imm 0x102e7c e3a01000 word  # v[45] returns it (0x0)
number 18 title_msg 3244 movw 0x106b10 e3000cac word
number 18 audit_started 245 imm 0x106b18 e3a000f5 word
number 18 audit_completed 0 imm 0x7f6b8 e3a00000 word shared 4
start 18 start: cmode_manager_get(18) at 0x59c34 then v[8], in fn 0x598b4
start 18 start: cmode_manager_get(18) at 0x188204 then v[8], in fn 0x18804c
# 15 other cmode_manager_get(18) sites read it (is_running, is_active, or a slot not traced)
number 18 start.caward_add 100000 movwt 0x1044f8 0x104500 e30826a0,e3402001 word  # v[8] call 0x104514
number 18 start.game_event.id 114 imm 0x104550 e3a00072 word  # v[8] call 0x104554
number 18 end.game_event.id 117 imm 0x102ed8 e3a00075 word  # v[10] call 0x102edc
number 18 end.game_event.id@2 116 imm 0x102f10 e3a00074 word  # v[10] call 0x102f14
number 18 shot.caward_add ? code 0x104d3c - code  # v[42]: the value is computed before the call
number 18 shot.event_post_replacing.id 227 imm 0x104d54 e3a000e3 word  # v[42] call 0x104d58
number 18 total_display.event_post_replacing.id 242 imm 0x103020 e3a000f2 word  # v[44] call 0x10302c
clip 18 Godzilla_TrainThrow movwt 0x103078 0x103080 e3003584,e3403064  # v[44] at 0x103080: a name total_display loads
number 18 timer.seconds 25 adj AD_SUPER_TRAIN_TIMER 192 e3a000c0 adjustment  # v[57] call 0x106b78; the id is imm 0x106b74, range 15..45
clip 18 Godzilla_TrainStomp movwt 0x106b34 0x106b38 e3000560,e3400064  # BDLSuperTrainAward::v[15] at 0x106b38: a name the display layer loads
clip 18 Train_Scene2 movwt 0x106b60 0x106b64 e3000574,e3400064  # BDLSuperTrainBG::v[14] at 0x106b64: a name the display layer loads
# display layers: BDLSuperTrainAward BDLSuperTrainBG BDLSuperTrainStart

mode 19 cmode_o2_destroyer obj 0x7b59f8 vtable 0x63eeb0 title_msg 3245
ctor 19 a 18 award 26 b 12 timer 18   # cmode_timed, ctor 0xf2260 called at 0xd501c; compared against cmode_timed, 65 virtuals
number 19 timer.v57 30 code 0x7fdc8 - code shared 5  # the base default: mov #30 at 0x7fdc8, 0x11dca8 - all of them, or a hook
shots 19 ? v[45] 0xf1af8 computes the lit mask: code
number 19 title_msg 3245 movw 0xf44d8 e3000cad word
number 19 audit_started 246 imm 0xf44e0 e3a000f6 word
number 19 audit_completed 247 imm 0xf44e8 e3a000f7 word
start 19 start: cmode_manager_get(19) at 0x167808 then v[8], in fn 0x1677ec
# 23 other cmode_manager_get(19) sites read it (is_running, is_active, or a slot not traced)
number 19 start.caward_add 500000 movwt 0xf1c38 0xf1c44 e30a2120,e3402007 word  # v[8] call 0xf1c50
number 19 start.game_event.id 147 imm 0xf1c6c e3a00093 word  # v[8] call 0xf1c70
number 19 end.game_event.id 149 imm 0xf1ef4 e3a00095 word  # v[10] call 0xf1ef8
number 19 end.game_event.id@2 148 imm 0xf1f20 e3a00094 word  # v[10] call 0xf1f24
number 19 shot.caward_add 1000000 movwt 0xf2444 0xf2454 e3042240,e340200f word  # v[42] call 0xf2460
number 19 shot.show_start.id 173 imm 0xf24b0 e3a000ad word  # v[42] call 0xf24b4
number 19 start_display.award_screen.type 149 imm 0xf1af0 e3a00095 word  # v[43] call 0xf1af4
number 19 initial_mask.adjustment 2 adj AD_O2_DESTROYER 164 e3a000a4 adjustment  # v[45] call 0xf1b00; the id is imm 0xf1afc, range 0..2
number 19 countdown.show_start.id 284 imm 0xf1b5c e3a00f47 word  # v[56] call 0xf1b60
number 19 countdown.fx.n 100 imm 0xf1b6c e3a00064 word  # v[56] call 0xf1b74
number 19 countdown.show_start.id@2 285 movw 0xf1b78 e300011d word  # v[56] call 0xf1b7c
number 19 countdown.fx.n@2 3000 movw 0xf1b84 e3000bb8 word  # v[56] call 0xf1b90
number 19 timer.seconds 12 adj AD_O2_DESTROYER_TIMER 193 e3a000c1 adjustment  # v[57] call 0xf451c; the id is imm 0xf4518, range 8..20
clip 19 o2destroyer_loop movwt 0xf4504 0xf4508 e30f0080,e3400063  # BDLO2DestroyerBG::v[14] at 0xf4508: a name the display layer loads
# display layers: BDLO2DestroyerBG

mode 20 cmode_king_of_the_monsters obj 0x7b5a68 vtable 0x63b418 title_msg ?
ctor 20 a 18 award 27 b 16 timer 25   # cmode_timed, ctor 0xc12a4 called at 0xd4fc8; compared against cmode_timed, 63 virtuals
number 20 timer.seconds ? code 0xbe2d4 - code  # v[57] computes it; not measured
number 20 timer.v57 84 imm 0xbdcb0 e3a00054 word  # v[58] returns it
shots 20 0x0 v[45] 0xd28a8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 20 initial_mask.lo 0 imm 0xd28a8 e3a00000 word inert start_rewrites  # v[45] returns it (0x0)
number 20 initial_mask.hi 0 imm 0xd28ac e3a01000 word inert start_rewrites  # v[45] returns it (0x0)
start 20 start: cmode_manager_get(20) at 0x56730 then v[8], in fn 0x566dc
start 20 stop: cmode_manager_get(20) at 0xbef3c then v[11], in cmode_king_of_the_monsters_multiball::v[11]
start 20 start: cmode_manager_get(20) at 0x15a620 then v[8], in RuleKingOfTheMonsters::v[25]
# 119 other cmode_manager_get(20) sites read it (is_running, is_active, or a slot not traced)
number 20 start.adjustment 12 adj AD_KOTM_TIME_ATTACK_DEFAULT_TIME_BONUS 231 e3a000e7 adjustment  # v[8] call 0xc62b8; the id is imm 0xc62b0, range 8..25
number 20 start.event_post_replacing.id 346 movw 0xc6384 e300015a word  # v[8] call 0xc638c
number 20 shot.caward_add ? code 0xbe910 - code  # v[42]: the value is computed before the call
number 20 shot.adjustment 12 adj AD_KOTM_TIME_ATTACK_DEFAULT_TIME_BONUS 231 e3a000e7 adjustment  # v[42] call 0xbe924; the id is imm 0xbe918, range 8..25
number 20 shot.award_screen.type 106 imm 0xbe940 e3a0006a word  # v[42] call 0xbe944
number 20 shot.show_start.id 236 imm 0xbe9ac e3a000ec word  # v[42] call 0xbe9b8
number 20 shot.fx.n 500 imm 0xbe9c4 e3a00f7d word  # v[42] call 0xbe9c8
number 20 shot.caward_add@2 2000000 movwt 0xbe9e4 0xbe9ec e3082480,e340201e word  # v[42] call 0xbe9fc
number 20 shot.adjustment@2 3 adj AD_KOTM_TIME_ATTACK_LOOP_ADD_TIME_BONUS 232 e3a000e8 adjustment  # v[42] call 0xbea08; the id is imm 0xbea00, range 2..10
number 20 shot.adjustment@3 40 adj AD_KOTM_TIME_ATTACK_MAX_TIME_BONUS 233 e3a000e9 adjustment  # v[42] call 0xbea1c; the id is imm 0xbea14, range 30..60
number 20 shot.award_screen.type@2 105 imm 0xbea48 e3a00069 word  # v[42] call 0xbea4c
number 20 shot.show_start.id@2 236 imm 0xbea80 e3a000ec word  # v[42] call 0xbea84
number 20 shot.fx.n@2 100 imm 0xbea90 e3a00064 word  # v[42] call 0xbea9c
clip 20 jj_timeadded movwt 0xbe950 0xbe958 e30b2bb4,e3402063  # v[42] at 0xbe958: a name shot loads
clip 20 jj_timebuild movwt 0xbea58 0xbea60 e30b3bc4,e3403063  # v[42] at 0xbea60: a name shot loads
number 20 v53.event_post_replacing.id 345 movw 0xc2ab4 e3000159 word  # v[54] call 0xc2ab8
clip 20 kotm_intro2 movwt 0xc7dd0 0xc7de4 e30b0f80,e3400063  # BDLKingOfTheMonstersStart::v[13] at 0xc7de4: a name the display layer loads
clip 20 MainTitle_Artbox movwt 0xc7dfc 0xc7e04 e30b1f8c,e3401063  # BDLKingOfTheMonstersStart::v[13] at 0xc7e04: a name the display layer loads
# display layers: BDLKingOfTheMonstersBG BDLKingOfTheMonstersMBBG BDLKingOfTheMonstersStart BDLKingOfTheMonstersTotal

mode 21 cmode_jet_fighter_attack obj 0x7b5b20 vtable 0x63af40 title_msg 3238
ctor 21 a 4 award 29 b 8 timer 7   # cmode_hurry_up, ctor 0xb9cb0 called at 0xd4f70; compared against cmode_hurry_up_null, 69 virtuals
number 21 timer.seconds 20 imm 0xb8fbc e3a00014 word  # v[57] returns it; PROOF EDIT: 10 on the patched card, runB ran 22,333 ms to the timer expiry (lr 0x11b160) against runA's 33,432 ms
number 21 timer.v57 30 code 0x7fdc8 - code shared 5  # the base default: mov #30 at 0x7fdc8, 0x11dca8 - all of them, or a hook
shots 21 0x14 v[45] 0xb8fc4, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 2, bit 4
number 21 initial_mask.lo 20 imm 0xb8fc4 e3a00014 word  # v[45] returns it (0x14)
number 21 initial_mask.hi 0 imm 0xb8fc8 e3a01000 word  # v[45] returns it (0x0)
number 21 title_msg 3238 movw 0xbcc60 e3000ca6 word
number 21 audit_started 213 imm 0xbcc68 e3a000d5 word
number 21 audit_completed 214 imm 0xbcc70 e3a000d6 word
start 21 start: cmode_manager_get(21) at 0x1592c0 then v[8], in RuleJetFighters::v[25]
# 17 other cmode_manager_get(21) sites read it (is_running, is_active, or a slot not traced)
number 21 start.caward_add 250000 movwt 0xb9b68 0xb9b74 e30d2090,e3402003 word  # v[8] call 0xb9b80
number 21 start.game_event.id 59 imm 0xb9bc4 e3a0003b word  # v[8] call 0xb9bd0
number 21 end.game_event.id 61 imm 0xb93b0 e3a0003d word  # v[10] call 0xb93b4
number 21 shot.show_start.id 229 imm 0xba6a0 e3a000e5 word  # v[42] call 0xba6a4
number 21 total_display.event_post_replacing.id 244 imm 0xb9238 e3a000f4 word  # v[44] call 0xb9244
clip 21 fighter_total movwt 0xb9290 0xb9298 e30b3248,e3403063  # v[44] at 0xb9298: a name total_display loads
# display layers: BDLJetFighterAttackBG BDLJetFighterAttackStart

mode 22 cmode_planet_x_hurry_up obj 0x7b5c08 vtable 0x63f4e0 title_msg 3268
ctor 22 a 20 award 16 b 13 timer 21   # cmode_hurry_up, ctor 0xfc1e4 called at 0xd4f18; compared against cmode_hurry_up_null, 71 virtuals
number 22 timer.seconds ? code 0xf4cf8 - code  # v[57] reads the object's field +0x70; set elsewhere, not measured
number 22 timer.v57 30 code 0x7fdc8 - code shared 5  # the base default: mov #30 at 0x7fdc8, 0x11dca8 - all of them, or a hook
shots 22 0x2000000000 v[45] 0xfc6e8, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 37
number 22 initial_mask.lo 0 imm 0xfc6e8 e3a00000 word inert start_rewrites  # v[45] returns it (0x0)
number 22 initial_mask.hi 32 imm 0xfc6ec e3a01020 word inert start_rewrites  # v[45] returns it (0x20)
number 22 title_msg 3268 movw 0xfc6d8 e3000cc4 word
number 22 audit_started 0 imm 0x7f6b0 e3a00000 word
number 22 audit_completed 0 imm 0x7f6b8 e3a00000 word shared 4
start 22 start: cmode_manager_get(22) at 0xfbf9c then v[8], in cmode_planet_x_multiball::v[42]
# 7 other cmode_manager_get(22) sites read it (is_running, is_active, or a slot not traced)
number 22 end.game_event.id 78 imm 0xf4f94 e3a0004e word  # v[10] call 0xf4f98
# display layers: BDLPlanetXHurryUpBG

mode 23 cmode_tesla_strike obj 0x7b5c88 vtable 0x640ed8 title_msg 3242
ctor 23 a 0 award 30 b 9 timer -   # cmode, ctor 0x10f640 called at 0xd4ec0; compared against cmode, 51 virtuals
shots 23 0x7000 v[45] 0x10e80c, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: bit 12, top spinner
number 23 initial_mask.lo 28672 imm 0x10e80c e3a00a07 word  # v[45] returns it (0x7000)
number 23 initial_mask.hi 0 imm 0x10e810 e3a01000 word  # v[45] returns it (0x0)
number 23 title_msg 3242 movw 0x1129dc e3000caa word
number 23 audit_started 243 imm 0x1129e4 e3a000f3 word
number 23 audit_completed 244 imm 0x1129ec e3a000f4 word
start 23 stop: cmode_manager_get(23) at 0x139c20 then v[11], in fn 0x138fe8
start 23 start: cmode_manager_get(23) at 0x16a1e8 then v[8], in fn 0x16a0d4
# 18 other cmode_manager_get(23) sites read it (is_running, is_active, or a slot not traced)
number 23 start.caward_add 250000 movwt 0x10ea60 0x10ea6c e30d2090,e3402003 word  # v[8] call 0x10ea78; PROOF EDIT: 1250000 on the patched card, runB paid v=1250000 at lr 0x10c244 (natural and forced starts) and its total screen read 1,250,000
number 23 start.game_event.id 92 imm 0x10eab4 e3a0005c word  # v[8] call 0x10eac4
number 23 end.game_event.id 94 imm 0x10e870 e3a0005e word  # v[10] call 0x10e874
number 23 shot.caward_add_scaled.mult 1 imm 0x10f99c e3a03001 word  # v[42] call 0x10f9a8
number 23 shot.fx.n 200 imm 0x10fbe0 e3a000c8 word  # v[42] call 0x10fbf0
number 23 shot.game_event.id 93 imm 0x10fcc0 e3a0005d word  # v[42] call 0x10fcc4
number 23 total_display.event_post_replacing.id 245 imm 0x10eb48 e3a000f5 word  # v[44] call 0x10eb54
clip 23 Mothra_godzilla_attack20 movwt 0x10ebec 0x10ebf0 e301218c,e3402064  # v[44] at 0x10ebf0: a name total_display loads
clip 23 Mothra_godzilla_powerlines10_2 movwt 0x10ebf4 0x10ebf8 e301316c,e3403064  # v[44] at 0x10ebf8: a name total_display loads
clip 23 Mothra_godzilla_powerlines8 movwt 0x112a00 0x112a04 e3010150,e3400064  # BDLTeslaStrikeBG::v[14] at 0x112a04: a name the display layer loads
# display layers: BDLTeslaStrikeBG

mode 24 cmode_monster_rampage obj 0x7b5d10 vtable 0x63ddf8 title_msg 3243
ctor 24 a 18 award 31 b 10 timer 14   # cmode_timed, ctor 0xe2eec called at 0xd4e70; compared against cmode_timed, 63 virtuals
number 24 timer.v57 30 code 0x7fdc8 - code shared 5  # the base default: mov #30 at 0x7fdc8, 0x11dca8 - all of them, or a hook
shots 24 0x100000 v[45] 0xe2338, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: left ramp
number 24 initial_mask.lo 1048576 imm 0xe2338 e3a00601 word  # v[45] returns it (0x100000)
number 24 initial_mask.hi 0 imm 0xe233c e3a01000 word  # v[45] returns it (0x0)
number 24 title_msg 3243 movw 0xe6e50 e3000cab word
number 24 audit_started 248 imm 0xe6e58 e3a000f8 word
number 24 audit_completed 0 imm 0x7f6b8 e3a00000 word shared 4
start 24 start: cmode_manager_get(24) at 0x59e04 then v[8], in fn 0x598b4
start 24 start: cmode_manager_get(24) at 0x162ef8 then v[8], in fn 0x162d74
# 29 other cmode_manager_get(24) sites read it (is_running, is_active, or a slot not traced)
number 24 start.adjustment 3000000 adj AD_MONSTER_RAMPAGE_BASE_SCORE 188 e3a000bc adjustment  # v[8] call 0xe4110; the id is imm 0xe410c, range 1000000..20000000
number 24 start.adjustment@2 1250000 adj AD_MONSTER_RAMPAGE_INCR_SCORE 189 e3a000bd adjustment  # v[8] call 0xe411c; the id is imm 0xe4118, range 500000..10000000
number 24 start.caward_add 250000 movwt 0xe41b4 0xe41c0 e30d2090,e3402003 word  # v[8] call 0xe41dc
number 24 start.adjustment@3 45 adj AD_MONSTER_RAMPAGE_BALL_SAVE_TIMER 186 e3a000ba adjustment  # v[8] call 0xe4228; the id is imm 0xe4218, range 40..60
number 24 start.adjustment@4 15 adj AD_MONSTER_RAMPAGE_BALL_SAVE_DECREMENT 187 e3a000bb adjustment  # v[8] call 0xe4234; the id is imm 0xe4230, range 5..20
number 24 start.game_event.id 53 imm 0xe428c e3a00035 word  # v[8] call 0xe4298
number 24 end.game_event.id 56 imm 0xe24f4 e3a00038 word  # v[10] call 0xe24f8
number 24 end.game_event.id@2 54 imm 0xe2534 e3a00036 word  # v[10] call 0xe2538
number 24 end.game_event.id@3 55 imm 0xe256c e3a00037 word  # v[10] call 0xe2570
number 24 total_display.event_post_replacing.id 243 imm 0xe275c e3a000f3 word  # v[44] call 0xe2768
clip 24 rampage_total movwt 0xe27a4 0xe27ac e30e3110,e3403063  # v[44] at 0xe27ac: a name total_display loads
number 24 timer.seconds 16 adj AD_RAMPAGE_MODE_SHOT_TIMER 185 e3a000b9 adjustment  # v[57] call 0xe6eb0; the id is imm 0xe6eac, range 8..20
# display layers: BDLMonsterRampageBG BDLMonsterRampageStart

mode 25 cmode_hedorah obj 0x7b5df8 vtable 0x63aae0 title_msg 3593
ctor 25 a 0 award 33 b 19 timer -   # cmode, ctor 0xb672c called at 0xd4e18; compared against cmode, 49 virtuals
shots 25 0x5800700800 v[45] 0xb6094, the lit mask cmode's START takes (then tail-calls 0x1b7f44, which may change it); this mode has its own start, which can write another mask: top spinner, left ramp, right ramp, building, bit 35, big loop, bit 38
number 25 initial_mask.lo 7342080 movwt 0xb6094 0xb609c e3a00b02,e3400070 code  # v[45] returns it (0x700800) (the low word is a mov)
number 25 initial_mask.hi 88 imm 0xb6098 e3a01058 code  # v[45] returns it (0x58)
number 25 title_msg 3593 movw 0xb8608 e3000e09 word
number 25 audit_started 263 movw 0xb8610 e3000107 word
number 25 audit_completed 0 imm 0x7f6b8 e3a00000 word shared 4
start 25 start: cmode_manager_get(25) at 0x59e90 then v[8], in fn 0x598b4
start 25 start: cmode_manager_get(25) at 0x166550 then v[8], in fn 0x166534
# 6 other cmode_manager_get(25) sites read it (is_running, is_active, or a slot not traced)
number 25 start.caward_add 500000 movwt 0xb6868 0xb6870 e30a2120,e3402007 word  # v[8] call 0xb6884
number 25 start.show_start.id 210 imm 0xb6888 e3a000d2 word  # v[8] call 0xb688c
number 25 start.game_event.id 107 imm 0xb68a8 e3a0006b word  # v[8] call 0xb68ac
number 25 end.game_event.id 109 imm 0xb6084 e3a0006d word  # v[10] call 0xb6088
clip 25 Hedorah_Smoke_Grow movwt 0xb8618 0xb861c e30a0cf8,e3400063  # BDLHedorahAward::v[15] at 0xb861c: a name the display layer loads
# display layers: BDLHedorahAward

mode 26 cmode_monster_zero obj 0x7b5e78 vtable 0x63e3c0 title_msg 3269
ctor 26 a 16 award 17 b 14 timer -   # cmode, ctor 0xe9b14 called at 0xd4dc8; compared against cmode, 49 virtuals
shots 26 0x0 v[45] 0xf08fc, the lit mask cmode's START takes (returned as a constant); this mode has its own start, which can write another mask: none
number 26 initial_mask.lo 0 imm 0xf08fc e3a00000 word  # v[45] returns it (0x0)
number 26 initial_mask.hi 0 imm 0xf0900 e3a01000 word  # v[45] returns it (0x0)
number 26 title_msg 3269 movw 0xf08e4 e3000cc5 word
number 26 audit_started 223 imm 0xf08ec e3a000df word
number 26 audit_completed 224 imm 0xf08f4 e3a000e0 word
start 26 start: cmode_manager_get(26) at 0x5a0ac then v[8], in fn 0x598b4
start 26 start: cmode_manager_get(26) at 0x15a684 then v[8], in RuleKingOfTheMonsters::v[25]
# 42 other cmode_manager_get(26) sites read it (is_running, is_active, or a slot not traced)
number 26 start.caward_add 25000000 movwt 0xec538 0xec548 e3072840,e340217d word  # v[8] call 0xec550
number 26 start.adjustment 30 adj AD_MONSTER_ZERO_BALL_SAVE_TIMER 225 e3a000e1 adjustment  # v[8] call 0xec56c; the id is imm 0xec568, range 28..40
number 26 start.game_event.id 121 imm 0xec608 e3a00079 word  # v[8] call 0xec610
number 26 end.game_event.id 124 imm 0xe7998 e3a0007c word  # v[10] call 0xe799c
number 26 shot.game_event.id 122 imm 0xea8b4 e3a0007a word  # v[42] call 0xea8b8
number 26 shot.caward_add 250000 movwt 0xea934 0xea93c e30d2090,e3402003 word  # v[42] call 0xea948
callout 26 226 shot.sound_request_play imm 0xea954 e3a000e2  # v[42] call 0xea96c
number 26 shot.show_start.id 146 imm 0xea97c e3a00092 word  # v[42] call 0xea994
number 26 shot.show_start.id@2 145 imm 0xeaa28 e3a00091 word  # v[42] call 0xeaa2c
number 26 shot.show_start.id@3 348 imm 0xeaa44 e3a00f57 word  # v[42] call 0xeaa48
number 26 shot.show_start.id@4 342 movw 0xeaa8c e3000156 word  # v[42] call 0xeaa90
number 26 shot.show_start.id@5 359 movw 0xeaaf4 e3000167 word  # v[42] call 0xeaaf8
number 26 shot.fx.n 100 imm 0xeab58 e3a00064 word  # v[42] call 0xeab60
number 26 shot.show_start.id@6 145 imm 0xeab64 e3a00091 word  # v[42] call 0xeab68
number 26 shot.show_start.id@7 348 imm 0xeab80 e3a00f57 word  # v[42] call 0xeab84
number 26 shot.show_start.id@8 342 movw 0xeabc8 e3000156 word  # v[42] call 0xeabcc
number 26 shot.caward_add@2 150000 movwt 0xeac50 0xeac5c e30429f0,e3402002 word  # v[42] call 0xeac68
number 26 shot.show_start.id@9 146 imm 0xead70 e3a00092 word  # v[42] call 0xead88
number 26 start_display.event_post_replacing.id 271 movw 0xe7a30 e300010f word  # v[43] call 0xe7a34
number 26 total_display.event_post_replacing.id 258 movw 0xe7fac e3000102 word  # v[44] call 0xe7fb8
clip 26 monster_zero_outtro movwt 0xe8004 0xe800c e30ecae8,e340c063  # v[44] at 0xe800c: a name total_display loads
clip 26 mt_fuji_loop movwt 0xe8ae8 0xe8afc e30e0afc,e3400063  # BDLMonsterZeroStart::v[13] at 0xe8afc: a name the display layer loads
clip 26 MainTitle_Artbox movwt 0xe8b14 0xe8b1c e30b1f8c,e3401063  # BDLMonsterZeroStart::v[13] at 0xe8b1c: a name the display layer loads
scene 26 4e0bf26631e0d64055ae92806c1a413634f6d72f movwt 0xe8c68 0xe8c6c e30e1b0c,e3401063  # BDLMonsterZeroStart::v[13] at 0xe8c6c
clip 26 YouAreToReport_VO3 movwt 0xe8da8 0xe8dac e30e1b58,e3401063  # BDLMonsterZeroStart::v[13] at 0xe8dac: a name the display layer loads
# display layers: BDLMonsterZeroBG BDLMonsterZeroStart BDLMonsterZeroTotal BDLMonsterZeroVictoryBG
# --- hand read (item 144): the screen that reads the selector table 0x64272c ---
start 12 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 0
start 13 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 1
start 14 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 2
start 15 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 3
start 16 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 4
start 6 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 5
start 17 start: the battle select screen reads that table (UIBattleSelectScreen, scene cac32730: flippers change the monster, action button selects); on Pro 1.15 its select 0x18cfc0 calls 0x122070, which starts cmode_manager_get(entry[index].id)->v[8]; this mode is entry 6
# --- hand read (item 144): tesla strike's start writes its OWN lit mask after cmode's START ---
shots 23 0x4800700000 its own start stores mov 0x700000 / mov 0x48 into the lit mask (strd at 0x10eab8): left ramp, right ramp, building, bit 35, bit 38; MODE_API.md read the same 0x48_00700000
number 23 start.lit_mask.lo 7340032 imm 0x10ea9c e3a08607 word  # tesla's v[8]
number 23 start.lit_mask.hi 72 imm 0x10eaa4 e3a09048 word  # tesla's v[8]
# --- hand read (item 144): planet X hurry-up's duration is its constructor's constant ---
number 22 timer.seconds.ctor 20 imm 0xfc208 e3a02014 word  # the constructor 0xfc1e4 stores it at +0x70 (0xfc210), the field v[56] returns; AD_PLANET_X_HURRY_UP_TIMER (222, default 20) has no constant-id reader, so whether the operator's value replaces it is not measured
# --- hand read (item 144): mode 20's title is one of three message ids (v[27] 0xbdfe4) ---
number 20 title_msg@2 3275 movw 0xbdff4 e3000ccb word  # when its first test (flag 40; Pro 1.15 0x1d91e4) is true
number 20 title_msg 3272 movw 0xbe000 e3003cc8 word  # when both tests (flags 40 and 41) are false; 3272 = "KING OF THE MONSTERS" (seen runA)
number 20 title_msg@3 3276 movw 0xbe004 e3002ccc word  # when its second test (flag 41) is true
# --- hand read (item 144): mode 10's title is one of three message ids (v[27] 0xbe070) ---
number 10 title_msg@2 3275 movw 0xbe080 e3000ccb word  # when its first test (flag 40; Pro 1.15 0x1d91e4) is true
number 10 title_msg 3273 movw 0xbe08c e3003cc9 word  # when both tests (flags 40 and 41) are false
number 10 title_msg@3 3276 movw 0xbe090 e3002ccc word  # when its second test (flag 41) is true
# --- hand read (item 144): scenes. A stock mode draws in SHARED template scenes plus a clip by name;
# only a few modes load a scene of their own. Read from the display layers' base classes and the
# unit (static initialiser) that loads each 40-hex id, and each scene's node names; not seen live. ---
scene 1 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 2 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 4 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 7 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 9 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 11 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 18 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 21 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 23 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 24 6b877640812fd0e512212950f109dd79d2ac33b7 movwt 0x45a4c 0x45a54 e3031280,e3401063  # SHARED by 10 modes: their BDL<Mode>Start layer derives from BDLModeStart, whose unit loads it (tesla strike's is BDLPowerlineAttackStart, by name); holds: GenericMode: MODE TITLE
scene 7 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x465f8 0x46600 e3031338,e3401063  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 9 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x465f8 0x46600 e3031338,e3401063  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 11 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x465f8 0x46600 e3031338,e3401063  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 20 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x465f8 0x46600 e3031338,e3401063  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
scene 26 6a22f74b53423c1dafb22964b3731bca02dbd56c movwt 0x465f8 0x46600 e3031338,e3401063  # SHARED by 5 modes: their BDL<Mode>Total layer derives from BDLModeTotal, whose unit loads it (planet X's total taken as the multiball's, by name); holds: MODE NAME TOTAL
# scene a1a15be4 for 12,13,14,15: not located on this build (0x46c50 not located: not unique in the reference)
scene 25 56fadc8a1342be85b087009f71a01c31c120faf5 movwt 0xb7940 0xb7948 e30a1d0c,e3401063  # hedorah's own unit (static initialiser); holds: HEDORAH, SMOG MONSTER FRENZY, SHOOT GREEN ARROW TO COLLECT
scene 24 7949bb14a9a21abf5e2885a01eb5ed4f9c3a8eca movwt 0xe3c78 0xe3c80 e30419d8,e3401063  # monster rampage's unit; the global it builds is read by cmode_monster_rampage and BDLMonsterRampageBG; holds: BaseGame: AWARD TITLE / AWARD VALUE
scene 26 4e0bf26631e0d64055ae92806c1a413634f6d72f movwt 0xe8c68 0xe8c6c e30e1b0c,e3401063  # BDLMonsterZeroStart::v[13] loads it; holds: Xilien console pop-up (Planet X voice lines)
# scene 4fb4bb55 for 1: not located on this build (0xb1ad4 not located: not unique in the reference)
# scene a24cebb4 for 2: not located on this build (0xd8420 not located: not unique in the reference)
# --- hand read (item 159, desk; the path edit emulator-proven by item 158 on Premium/LE 1.16): tank attack's shots
# are a six-entry PATH, not the lit mask. Each entry is 16 bytes {u64 position, u16 TANK lamp, u16 id, u32 0};
# tanks walk toward entry 2 (the Godzilla target) and die on the entry they stand on. Positions 0, 4 and 5 are
# also where tanks appear (seed words in code: 0x109cbc/0x10a660, 0x109cd8, 0x109cd0/0x10a5fc) and 2 is where they head
# (0x109c78/0x10a5ec/0x10a654), so those four stay as they are; 1 and 3 can be another shot the switches send alone,
# or none (= a copy of the neighbouring entry away from the target: the walk skips it, proven). The counted-shots
# words (v[47]) and the spot list (v[48]) follow the path. ---
number 4 path.0 0x800000000 path 0x640960 00000000,00000008,0b7f0072,00000000 word fixed seed  # TANK 1 (lamp 114): bit 35, where a tank appears
number 4 path.1 0x100000 path 0x640970 00100000,00000000,0b6d0090,00000000 word  # TANK 2 (lamp 144): Left ramp
number 4 path.2 0x80000 path 0x640980 00080000,00000000,0b6c0093,00000000 word fixed goal  # TANK 3 (lamp 147): Godzilla target, where every tank heads
number 4 path.3 0x800 path 0x640990 00000800,00000000,0b64009a,00000000 word  # TANK 4 (lamp 154): Top spinner (bit 11); path[3] := path[4] proven (item 158 live-3, this build)
number 4 path.4 0x200000 path 0x6409a0 00200000,00000000,0b6e00ad,00000000 word fixed seed  # TANK 5 (lamp 173): Right ramp, where a tank appears
number 4 path.5 0x2000000000 path 0x6409b0 00000000,00000020,0b80007b,00000000 word fixed seed  # TANK 6 (lamp 123): bit 37, where a tank appears
number 4 path.counted.lo 0x380800 movwt 0x108d84 0x108d8c 03a00b02,03400038 word follows path  # v[47] counted shots (moveq/movteq), low half = the OR of the path
number 4 path.counted.hi 0x28 imm 0x108d88 03a01028 word follows path  # v[47] counted shots, high half
number 4 path.spot.0 0x80000 qword 0x640930 00080000,00000000 word follows path  # v[48] spot list entry for path.2
number 4 path.spot.1 0x100000 qword 0x640938 00100000,00000000 word follows path  # v[48] spot list entry for path.1
number 4 path.spot.2 0x800 qword 0x640940 00000800,00000000 word follows path  # v[48] spot list entry for path.3
number 4 path.spot.3 0x200000 qword 0x640948 00200000,00000000 word follows path  # v[48] spot list entry for path.4
number 4 path.spot.4 0x800000000 qword 0x640950 00000000,00000008 word follows path  # v[48] spot list entry for path.0
number 4 path.spot.5 0x2000000000 qword 0x640958 00000000,00000020 word follows path  # v[48] spot list entry for path.5
# --- hand read (item 159, desk): battle vs ebirah needs N spins of each spinner; the counts are loaded per spinner
# by the refill 0x81018 (ldr from the constructor's words 0x80fdc/0x80fec, one of them shared by two spinners). Each load
# becomes `mov rd,#N` for a count of the app's own. Seen 15/40/15 at every START (item 158, Premium/LE 1.16). ---
number 12 spins.left 15 insn 0x81020 e5905078 word  # ldr r5,[r0,#0x78] -> mov r5,#N: spins of the Left spinner (bit 0x200)
number 12 spins.top 40 insn 0x81028 e594607c word  # ldr r6,[r4,#0x7c] -> mov r6,#N: spins of the Top spinner (bit 0x2000)
number 12 spins.shield 15 insn 0x81038 e5945080 word  # ldr r5,[r4,#0x80] -> mov r5,#N: spins of the Shield ramp spinner (bit 0x20000)
"""
