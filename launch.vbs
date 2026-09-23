Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
' 1 = show normally: the app's first window is its main window, and a
' hidden start state (0) would keep it hidden (see installer/launcher.vbs).
WshShell.Run "pythonw.exe ""Pinball Asset Decryptor.pyw""", 1, False
