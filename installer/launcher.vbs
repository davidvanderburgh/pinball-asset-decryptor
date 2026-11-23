' Bundled launcher — invokes the bundled Python embeddable interpreter
' from the install directory.  Different from the repo-root launch.vbs
' which assumes a system-wide pythonw.exe.
'
' The app is started with the ShellExecute "runas" verb so EVERY launch
' runs elevated behind a standard one-click UAC prompt.  Direct-SSD /
' SD-card operations need Administrator, and the old flow (remember to
' right-click → Run as administrator) failed halfway through a run with
' WSL_E_ELEVATION_NEEDED_TO_MOUNT_DISK when forgotten.  The UAC dialog
' names pythonw.exe (publisher: Python Software Foundation) because
' that is the process being elevated.
'
' If the user declines the UAC prompt, ShellExecute errors — the
' On Error guard turns that into "app just doesn't start" instead of a
' Windows Script Host error dialog.
'
' The last argument is the SHOW state and it MUST be 1 (normal).  Windows
' applies a program's start state to the FIRST window it shows, and the
' app's first window is its main window: 0 started v1.0.0 / v1.0.1 with the
' window created and never shown (the Tk app got away with 0 because its
' first window was an invisible root).
'
' Arguments are passed on (PAD-1514): Explorer starts this with a card
' image's path when one is double-clicked, and the app opens on its write
' dialog.  Each is quoted again, since WScript.Arguments has unquoted them.
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
params = """" & appDir & "\Pinball Asset Decryptor.pyw"""
For Each a In WScript.Arguments
    params = params & " """ & a & """"
Next
' One launch is NOT elevated (PAD-1522): "--compact" as the first argument,
' Explorer's right-click > Compact with PAD on a card image.  It only makes
' the user's own file sparse, in a small window of its own, so it starts
' with the plain "open" verb and no UAC prompt.
compacting = False
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "--compact" Then compacting = True
End If
On Error Resume Next
If compacting Then
    CreateObject("Shell.Application").ShellExecute _
        appDir & "\python\pythonw.exe", params, appDir, "open", 1
    WScript.Quit
End If
CreateObject("Shell.Application").ShellExecute _
    appDir & "\python\pythonw.exe", params, appDir, "runas", 1
