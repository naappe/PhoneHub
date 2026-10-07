Option Explicit
Dim shell, fso, root, launcher
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = Chr(34) & fso.BuildPath(root, "AndroidBridge-Lite.bat") & Chr(34)
shell.Run launcher, 0, False
