' PADSPIKE2.vbs - the Visual Pinball system script for a table driven by the
' PAD Spike 2 emulator instead of Visual PinMAME.
'
' Loaded by a table script in place of controller.vbs + SEGA.VBS:
'
'     ExecuteGlobal GetTextFile("PADSPIKE2.vbs")
'     LoadVPM "01000000", "PADSPIKE2.vbs", 3.10
'
' It loads VPX's own core.vbs and VPMKeys.vbs (so cvpmBallStack, cvpmMagnet,
' vpmTimer, vpmNudge, vpmFlips and the key handlers all work unchanged), then
' creates the PAD.Controller COM object, which core.vbs drives exactly as it
' would drive VPinMAME.Controller: Switch(n) in, ChangedLamps and
' ChangedSolenoids out.
'
' NUMBERING. A Spike 2 machine has no Whitestar switch matrix, so every number
' a table script hands the controller is in ONE convention:
'
'     switch   1000 + <Spike 2 switch id>        (switch_list.txt's `id`)
'     solenoid 1000 + <node> * 16 + <coil index>  (device_xy.txt coil group->node)
'     lamp     1000 + <node> * 100 + <LED index>  (led_io.txt)
'
' Numbers below 1000 are looked up in the title's .vpxmap.json, for a table
' kept on its original numbering. The constants below are godzilla_le's
' cabinet; another title overrides them in its own table script before
' LoadVPM (they are Dim, not Const, for exactly that reason).

Option Explicit
LoadCore
Private Sub LoadCore
	On Error Resume Next
	ExecuteGlobal GetTextFile("core.vbs")    : If Err Then MsgBox "Can't open ""core.vbs"""    : Exit Sub
	ExecuteGlobal GetTextFile("VPMKeys.vbs") : If Err Then MsgBox "Can't open ""vpmkeys.vbs""" : Exit Sub
End Sub

' ---- what controller.vbs would have defined (the table uses SoundFX and the DOF constants)
Dim Controller
Const DOFContactors = 1
Const DOFKnocker = 2
Const DOFChimes = 3
Const DOFBell = 4
Const DOFGear = 5
Const DOFShaker = 6
Const DOFFlippers = 7
Const DOFTargets = 8
Const DOFDropTargets = 9
Const DOFOff = 0
Const DOFOn = 1
Const DOFPulse = 2
Dim B2SOn : B2SOn = False
Dim B2SOnALT : B2SOnALT = False
Function SoundFX(sound, effect) : SoundFX = sound : End Function
Function SoundFXDOF(sound, DOFevent, State, effect) : SoundFXDOF = sound : End Function
Sub DOF(DOFevent, State) : End Sub

' ---- the controller. The VPM version string and the driver version are what
' core.vbs and LoadVPM's callers compare against. GameOnSolenoid is the
' controller's synthetic "flippers armed" solenoid (the .vpxmap.json's
' game_on): with UseSolenoids=2 core.vbs flips from the key the moment it is
' on, as on the machine, where the board fires the flipper from its button.
Const GameOnSolenoid = 1999
Sub LoadVPM(VPMver, VBSfile, VBSver)
	On Error Resume Next
	Set Controller = CreateObject("PAD.Controller")
	If Err Then MsgBox "Can't load PAD.Controller: register it with" & vbNewLine & _
		"  python tools\spike2_emu\vpx\padcontroller.py --register" & vbNewLine & Err.Description
	If VPinMAMEDriverVer < VBSver Or Err Then MsgBox "PADSPIKE2.vbs ver " & VBSver & " or higher required."
End Sub

' ---- cabinet switches, Spike 2 godzilla_le ids + 1000 (switch_list.txt)
Dim swStartButton   : swStartButton   = 1036  ' Start Button
Dim swTilt          : swTilt          = 1038  ' Tilt Pendulum
Dim swSlamTilt      : swSlamTilt      = 1045  ' Slam Tilt
Dim swCoin1         : swCoin1         = 1039  ' Left Coin
Dim swCoin2         : swCoin2         = 1040  ' Center Coin
Dim swCoin3         : swCoin3         = 1041  ' Right Coin
Dim swLaunch        : swLaunch        = 1034  ' Action Button (ball launch)
Dim swLRFlip        : swLRFlip        = 1059  ' Right Flipper Button
Dim swLLFlip        : swLLFlip        = 1060  ' Left Flipper Button
Dim swULFlip        : swULFlip        = 1061  ' Up Left Flip Button
Dim swURFlip        : swURFlip        = 0     ' none on this title
' the coin door's service buttons on the three VPM service keys
Dim swBlack         : swBlack         = 1028  ' Service Back
Dim swGreen         : swGreen         = 1025  ' Service Select
Dim swRed           : swRed           = 1026  ' Service Plus
' never touch the coin door interlock: open = no 48 V for every coil
Dim swMemoryProtect : swMemoryProtect = 0

' ---- flipper coils, 1000 + node * 16 + index (godzilla_le: node 8)
Dim sLLFlipper : sLLFlipper = 1133  ' LEFT FLIPPER   8/5
Dim sLRFlipper : sLRFlipper = 1128  ' RIGHT FLIPPER  8/0
Dim sULFlipper : sULFlipper = 1134  ' UP LEFT FLIP   8/6
Dim sURFlipper : sURFlipper = 0

vpmSystemHelp = "Stern Spike 2 (PAD emulator) keys:" & vbNewLine &_
  vpmKeyName(keyInsertCoin1)  & vbTab & "Left Coin"       & vbNewLine &_
  vpmKeyName(keyInsertCoin2)  & vbTab & "Center Coin"     & vbNewLine &_
  vpmKeyName(keyInsertCoin3)  & vbTab & "Right Coin"      & vbNewLine &_
  vpmKeyName(keyBlack)        & vbTab & "Service Back"    & vbNewLine &_
  vpmKeyName(keyGreen)        & vbTab & "Service Select"  & vbNewLine &_
  vpmKeyName(keyRed)          & vbTab & "Service Plus"    & vbNewLine &_
  vpmKeyName(keySlamDoorHit)  & vbTab & "Slam Tilt"
