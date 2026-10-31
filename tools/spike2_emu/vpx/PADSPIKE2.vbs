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
'     lamp     1000 + <node> * 100 + <LED index>  (led_io.txt)
'     solenoid the SMALL number the title's .vpxmap.json gives the coil:
'              core.vbs indexes SolCallback(68) and friends by it, so a
'              coil cannot be named 1000+; the flippers keep core.vbs's own
'              sLRFlipper 46 / sLLFlipper 48 / sULFlipper 36 / sURFlipper 34.
'
' A switch or lamp number below 1000 is looked up in the title's .vpxmap.json,
' for a table kept on its original numbering. The constants below are
' godzilla_le's cabinet; another title overrides them in its own table script
' before LoadVPM (they are Dim, not Const, for exactly that reason).

Option Explicit

' A line in %TEMP%\padspike2.log for each step of the load: a MsgBox stops
' the table, a log does not, and the controller's own log is right beside it.
Sub PadLog(msg)
	On Error Resume Next
	Dim fso, f
	Set fso = CreateObject("Scripting.FileSystemObject")
	Set f = fso.OpenTextFile(fso.GetSpecialFolder(2) & "\padspike2.log", 8, True)
	f.WriteLine Now & " " & msg
	f.Close
End Sub

' core.vbs is loaded from LoadVPM, NOT here. This file runs at the top of the
' table script, before its Consts, and core.vbs's load-time
' `IsEmpty(Eval("BallSize"))` brings an undefined BallSize into being - so
' the table's own `Const BallSize = 50` a few lines later died of "Name
' redefined", and with it everything after it. controller.vbs + SEGA.VBS
' load core.vbs from LoadVPM for the same reason.
Private Sub LoadCore
	Dim t
	On Error Resume Next
	t = GetTextFile("core.vbs")
	PadLog "GetTextFile(core.vbs): err=" & Err.Number & " " & Err.Description & " len=" & Len(t) & " head=" & Replace(Left(t, 80), vbCrLf, "|")
	If Err Then MsgBox "PADSPIKE2.vbs: GetTextFile(core.vbs) failed: " & Err.Description : Exit Sub
	ExecuteGlobal t
	PadLog "core.vbs executed: err=" & Err.Number & " " & Err.Description
	If Err Then MsgBox "PADSPIKE2.vbs: core.vbs raised " & Err.Number & ": " & Err.Description & " (" & Err.Source & ")" : Exit Sub
	t = GetTextFile("VPMKeys.vbs")
	If Err Then MsgBox "PADSPIKE2.vbs: GetTextFile(VPMKeys.vbs) failed: " & Err.Description : Exit Sub
	ExecuteGlobal t
	PadLog "VPMKeys.vbs executed: err=" & Err.Number & " " & Err.Description
	If Err Then MsgBox "PADSPIKE2.vbs: VPMKeys.vbs raised " & Err.Number & ": " & Err.Description : Exit Sub
End Sub

' ---- what controller.vbs would have defined (the table uses SoundFX and the
' DOF constants). `Controller` itself is core.vbs's Dim.
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
' the backglass (PAD-852). controller.vbs's LoadVPM makes `Controller` a
' B2S.Server, which runs VPinMAME inside itself and shows the .directb2s;
' here `Controller` is PAD.Controller, so B2S.Server runs beside it as
' B2SController - controller.vbs's own two-controller (LoadVPMALT) way.
' B2SOn stays False: `Controller.B2S...` calls would reach PAD.Controller.
' PadB2SName is the table's own ROM name, which the patch keeps: the name
' B2S and DOF know the table by. B2SOff = True before LoadVPM: none.
Dim B2SController
Dim B2SOff : B2SOff = False
Dim PadB2SName : PadB2SName = ""
Function SoundFX(sound, effect) : SoundFX = sound : End Function
Function SoundFXDOF(sound, DOFevent, State, effect) : SoundFXDOF = sound : End Function
Sub DOF(DOFevent, State) : End Sub

' ---- the controller. The VPM version string and the driver version are what
' core.vbs and LoadVPM's callers compare against. GameOnSolenoid is the
' controller's synthetic "flippers armed" solenoid (the .vpxmap.json's
' game_on): with UseSolenoids=2 core.vbs flips from the key the moment it is
' on, as on the machine, where the board fires the flipper from its button.
Const GameOnSolenoid = 40
Sub LoadVPM(VPMver, VBSfile, VBSver)
	LoadCore
	Set vpmShowDips = GetRef("padNoDips")
	On Error Resume Next
	Set Controller = CreateObject("PAD.Controller")
	PadLog "CreateObject(PAD.Controller): err=" & Err.Number & " " & Err.Description & " IsObject=" & IsObject(Controller)
	If Err Then MsgBox "Can't load PAD.Controller: register it with" & vbNewLine & _
		"  python tools\spike2_emu\vpx\padcontroller.py --register" & vbNewLine & Err.Description
	If VPinMAMEDriverVer < VBSver Or Err Then MsgBox "PADSPIKE2.vbs ver " & VBSver & " or higher required."
	PadStartB2S
	vpmSystemHelp = "Stern Spike 2 (PAD emulator) keys:" & vbNewLine &_
	  vpmKeyName(keyInsertCoin1)  & vbTab & "Left Coin"       & vbNewLine &_
	  vpmKeyName(keyInsertCoin2)  & vbTab & "Center Coin"     & vbNewLine &_
	  vpmKeyName(keyInsertCoin3)  & vbTab & "Right Coin"      & vbNewLine &_
	  vpmKeyName(keyBlack)        & vbTab & "Service Back"    & vbNewLine &_
	  vpmKeyName(keyGreen)        & vbTab & "Service Select"  & vbNewLine &_
	  vpmKeyName(keyRed)          & vbTab & "Service Plus"    & vbNewLine &_
	  vpmKeyName(keySlamDoorHit)  & vbTab & "Slam Tilt"
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

' ---- the keyboard. core.vbs's KeyDownHandler/KeyUpHandler call these and
' leave them to the system script (sega.vbs defines Whitestar's); the table
' script calls the handlers from Table1_KeyDown/KeyUp.
' The upper flippers follow VPMKeys.vbs's keyStagedFlipperL/R, which are the
' flipper keys themselves unless a table sets them: the machine's button
' closes both its switches, so the left key flips the upper left flipper too
' (PAD-878). Visual Pinball's own StagedLeftFlipperKey is Left Windows by
' default, and reading it left Godzilla's third flipper on a key nobody holds.
Function vpmKeyDown(ByVal keycode)
	vpmKeyDown = True ' Assume we handle the key
	Dim stagedFlipperL, stagedFlipperR
	If keyStagedFlipperL & "" = "" Then stagedFlipperL = -1 Else stagedFlipperL = keyStagedFlipperL
	If keyStagedFlipperR & "" = "" Then stagedFlipperR = -1 Else stagedFlipperR = keyStagedFlipperR
	With Controller
		Select Case keycode
			Case LeftFlipperKey
				.Switch(swLLFlip) = True : vpmKeyDown = False : vpmFlips.FlipL True
				If keycode = stagedFlipperL Then
					vpmFlips.FlipUL True
					If vpmFlips.FlipperSolNumber(2) <> 0 Then .Switch(swULFlip) = True
				End If
			Case RightFlipperKey
				.Switch(swLRFlip) = True : vpmKeyDown = False : vpmFlips.FlipR True
				If keycode = stagedFlipperR Then
					vpmFlips.FlipUR True
					If vpmFlips.FlipperSolNumber(3) <> 0 And swURFlip <> 0 Then .Switch(swURFlip) = True
				End If
			Case stagedFlipperL vpmFlips.FlipUL True : If vpmFlips.FlipperSolNumber(2) <> 0 Then .Switch(swULFlip) = True
			Case stagedFlipperR vpmFlips.FlipUR True : If vpmFlips.FlipperSolNumber(3) <> 0 And swURFlip <> 0 Then .Switch(swURFlip) = True
			Case keyInsertCoin1  vpmTimer.AddTimer 750,"vpmTimer.PulseSw swCoin1'" : If Not IsEmpty(Eval("SCoin")) Then Playsound SCoin
			Case keyInsertCoin2  vpmTimer.AddTimer 750,"vpmTimer.PulseSw swCoin2'" : If Not IsEmpty(Eval("SCoin")) Then Playsound SCoin
			Case keyInsertCoin3  vpmTimer.AddTimer 750,"vpmTimer.PulseSw swCoin3'" : If Not IsEmpty(Eval("SCoin")) Then Playsound SCoin
			Case StartGameKey    .Switch(swStartButton) = True
			Case keyBlack        .Switch(swBlack)       = True
			Case keyGreen        .Switch(swGreen)       = True
			Case keyRed          .Switch(swRed)         = True
			Case keySlamDoorHit  .Switch(swSlamTilt)    = True
			Case keyBangBack     vpmNudge.DoMechTilt
			Case Else            vpmKeyDown = False
		End Select
	End With
End Function

Function vpmKeyUp(ByVal keycode)
	vpmKeyUp = True ' Assume we handle the key
	Dim stagedFlipperL, stagedFlipperR
	If keyStagedFlipperL & "" = "" Then stagedFlipperL = -1 Else stagedFlipperL = keyStagedFlipperL
	If keyStagedFlipperR & "" = "" Then stagedFlipperR = -1 Else stagedFlipperR = keyStagedFlipperR
	With Controller
		Select Case keycode
			Case LeftFlipperKey
				.Switch(swLLFlip) = False : vpmKeyUp = False : vpmFlips.FlipL False
				If keycode = stagedFlipperL Then
					vpmFlips.FlipUL False
					If vpmFlips.FlipperSolNumber(2) <> 0 Then .Switch(swULFlip) = False
				End If
			Case RightFlipperKey
				.Switch(swLRFlip) = False : vpmKeyUp = False : vpmFlips.FlipR False
				If keycode = stagedFlipperR Then
					vpmFlips.FlipUR False
					If vpmFlips.FlipperSolNumber(3) <> 0 And swURFlip <> 0 Then .Switch(swURFlip) = False
				End If
			Case stagedFlipperL vpmFlips.FlipUL False : If vpmFlips.FlipperSolNumber(2) <> 0 Then .Switch(swULFlip) = False
			Case stagedFlipperR vpmFlips.FlipUR False : If vpmFlips.FlipperSolNumber(3) <> 0 And swURFlip <> 0 Then .Switch(swURFlip) = False
			Case StartGameKey    .Switch(swStartButton) = False
			Case keyBlack        .Switch(swBlack)       = False
			Case keyGreen        .Switch(swGreen)       = False
			Case keyRed          .Switch(swRed)         = False
			Case keySlamDoorHit  .Switch(swSlamTilt)    = False
			Case keyShowOpts     .Pause = True : vpmShowOptions : .Pause = False
			Case keyShowKeys     .Pause = True : vpmShowHelp : .Pause = False
			Case keyAddBall      .Pause = True : vpmAddBall  : .Pause = False
			Case keyReset        .Stop : BeginModal : .Run : vpmTimer.Reset : EndModal
			Case Else            vpmKeyUp = False
		End Select
	End With
End Function

' ---- the backglass: B2S.Server beside the controller, unless Visual
' Pinball's ForceDisableB2S setting or the table's B2SOff says not (as
' controller.vbs). No B2S installed: no backglass, and nothing else changes.
Private Sub PadStartB2S
	Dim off, name, e
	off = 0
	On Error Resume Next
	If VPBuildVersion >= 10704 Then off = CInt(Setting("Controller", "ForceDisableB2S"))
	Err.Clear
	If B2SOff Then off = 1
	If off <> 0 Then PadLog "B2S.Server: off (ForceDisableB2S or B2SOff)" : Exit Sub
	name = PadB2SName
	If name = "" Then name = Eval("cGameName")
	Err.Clear
	Set B2SController = CreateObject("B2S.Server")
	If Err Then PadLog "B2S.Server: none (" & Err.Description & ") - no backglass" : Err.Clear : Exit Sub
	B2SController.B2SName = name
	B2SController.Run
	e = Err.Number & " " & Err.Description   ' PadLog's return clears Err
	If Err = 0 Then B2SOnALT = True
	Err.Clear
	PadLog "B2S.Server: started as " & name & " err=" & e
End Sub

' the table's exit sub calls this beside Controller.Stop (the patch puts it there)
Sub PadStopB2S
	On Error Resume Next
	If IsObject(B2SController) Then B2SController.Stop
	B2SOnALT = False
End Sub

' no DIP switches on a Spike 2 machine: its settings are the game's own menu
' (vpmShowDips is core.vbs's Dim, so LoadVPM points it here after LoadCore)
Private Sub padNoDips : End Sub

' ---- flipper coils. core.vbs owns sLLFlipper (48), sLRFlipper (46),
' sULFlipper (36) and sURFlipper (34) as Consts, and vpmFlips is built on
' them, so they stay: the title's .vpxmap.json `solenoid_aliases` names the
' Spike 2 coil each of those numbers stands for (godzilla_le: 48 = LEFT
' FLIPPER 8/5, 46 = RIGHT FLIPPER 8/0, 36 = UP LEFT FLIP 8/6) and the
' controller reports the coil under both its alias and its 1000+ number.
