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
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
On Error Resume Next
CreateObject("Shell.Application").ShellExecute _
    appDir & "\python\pythonw.exe", _
    """" & appDir & "\Pinball Asset Decryptor.pyw""", _
    appDir, "runas", 1
