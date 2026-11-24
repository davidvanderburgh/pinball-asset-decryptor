' Bundled launcher — invokes the bundled Python embeddable interpreter
' from the install directory.  Different from the repo-root launch.vbs
' which assumes a system-wide pythonw.exe.
'
' The app starts WITHOUT Administrator rights, with the plain "open" verb
' (PAD-1563, GitHub issue #46: no UAC prompt on every launch).  The few
' jobs that need Administrator ask for it themselves when they start: a
' card read or flash, formatting the JJP USB stick, the HASP dongle's USB
' passthrough, Visual Pinball's controller, installing an update.  Reading
' or writing a game SSD directly (wsl --mount) needs the whole app
' elevated, so those tabs offer "Restart as administrator", which brings
' the app back up elevated on the same tab.  Before PAD-1563 every launch
' was elevated here with the "runas" verb.
'
' A ShellExecute error (a missing pythonw.exe, say) is swallowed by the
' On Error guard rather than shown as a Windows Script Host error dialog.
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
On Error Resume Next
CreateObject("Shell.Application").ShellExecute _
    appDir & "\python\pythonw.exe", params, appDir, "open", 1
