' Bundled launcher — invokes the bundled Python embeddable interpreter
' from the install directory.  Different from the repo-root launch.vbs
' which assumes a system-wide pythonw.exe.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = appDir
WshShell.Run """" & appDir & "\python\pythonw.exe"" """ & appDir & "\Pinball Asset Decryptor.pyw""", 0, False
