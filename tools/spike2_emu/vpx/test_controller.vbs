' test_controller.vbs - drive PAD.Controller from the same VBScript engine
' Visual Pinball uses, with no table and no VPX install:
'
'     cscript //nologo tools\spike2_emu\vpx\test_controller.vbs [run]
'
' Without `run` it proves the COM half: creation, the properties core.vbs
' reads, and the SHAPE of ChangedLamps / ChangedSolenoids (a 2-D array whose
' rows are (number, state), or Empty). With `run` and a Spike 2 run up, it
' presses the left flipper button through the rig and expects the game's
' LEFT FLIPPER coil (1133 on godzilla_le) back in ChangedSolenoids.
Option Explicit
Dim c, chg, i, want, t0
Set c = CreateObject("PAD.Controller")
WScript.Echo "created: Version=" & c.Version
c.GameName = "godzilla_le"
WScript.Echo "GameName=" & c.GameName
c.SplashInfoLine = "x" : c.HandleKeyboard = 0 : c.HandleMechanics = 0
c.ShowDMDOnly = 1 : c.ShowFrame = 0 : c.ShowTitle = 0 : c.Hidden = 0
WScript.Echo "Games().Settings.Value(volume)=" & c.Games("godzilla_le").Settings.Value("volume")
WScript.Echo "Lamp(1860)=" & c.Lamp(1860) & "  Solenoid(1133)=" & c.Solenoid(1133) & "  Switch(1060)=" & c.Switch(1060)
chg = c.ChangedLamps
WScript.Echo "ChangedLamps before Run: IsEmpty=" & IsEmpty(chg)

want = (WScript.Arguments.Count > 0)
If Not want Then
	WScript.Echo "PASS (COM half). Add `run` with a godzilla_le run up for the rig half."
	WScript.Quit 0
End If

c.Run 0
WScript.Echo "Run: " & c.PadStatus
WScript.Sleep 400
chg = c.ChangedLamps
If IsEmpty(chg) Then
	WScript.Echo "ChangedLamps after Run: Empty"
Else
	WScript.Echo "ChangedLamps after Run: " & (UBound(chg, 1) + 1) & " rows x " & (UBound(chg, 2) + 1) & " cols; first " & chg(0, 0) & "=" & chg(0, 1)
End If
chg = c.ChangedSolenoids   ' drain whatever the attract did so far

' A Spike 2 game in attract has dead flippers, so: Start a game (the trough
' holds six balls on a rig run) and expect the TROUGH coil, then the left
' flipper button and expect its coil.
Dim seen
c.Switch(1036) = 1
WScript.Sleep 300
c.Switch(1036) = 0
seen = Collect(c, 4000)
WScript.Echo "after Start:   " & seen
If InStr(seen, "1129=") = 0 Then
	WScript.Echo "FAIL: 1129 (TROUGH) never fired after Start - no game started?"
	c.Stop
	WScript.Quit 1
End If
WScript.Sleep 1500
c.Switch(1060) = 1
WScript.Sleep 300
c.Switch(1060) = 0
seen = Collect(c, 1500)
WScript.Echo "after flipper: " & seen
WScript.Echo "status: " & c.PadStatus
c.Stop
If InStr(seen, "1133=") > 0 Then
	WScript.Echo "PASS: the trough answered Start and the left flipper coil answered the button"
	WScript.Quit 0
End If
WScript.Echo "FAIL: 1133 (LEFT FLIPPER) not among the changes"
WScript.Quit 1

' every (number=state) ChangedSolenoids reports over `ms`, in order
Function Collect(ctl, ms)
	Dim t, s, a, j
	s = "" : t = Timer
	Do While (Timer - t) * 1000 < ms
		a = ctl.ChangedSolenoids
		If Not IsEmpty(a) Then
			For j = 0 To UBound(a, 1)
				s = s & a(j, 0) & "=" & a(j, 1) & " "
			Next
		End If
		WScript.Sleep 10
	Loop
	Collect = s
End Function
