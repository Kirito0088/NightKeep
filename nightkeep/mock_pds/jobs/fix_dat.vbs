' The undocumented script nobody remembers.
'
' A job the district PDS software runs by itself, some nights only: standard
' library only (Scripting.FileSystemObject), everything it needs through
' argv. It knows nothing about Nightkeep.
'
' It renames outstanding .tmp allocation files to .dat, the finishing touch
' allocation_gen.py never learned to do itself, and rewrites a couple of
' already-.dat files in place, still valid text, a quirk nobody documented.
' The scheduler decides whether tonight is one of the nights it runs, via
' --run; either way it appends what it really did to its own ground-truth
' log, logs/_truth/fix_dat.jsonl.

Option Explicit

Dim fso, args, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set args = WScript.Arguments

Dim root, day, simStart, shouldRun
root = "" : day = "" : simStart = "" : shouldRun = False

i = 0
Do While i < args.Count
  Select Case LCase(args(i))
    Case "--root"
      root = args(i + 1) : i = i + 2
    Case "--day"
      day = args(i + 1) : i = i + 2
    Case "--sim-start"
      simStart = args(i + 1) : i = i + 2
    Case "--scale"
      i = i + 2
    Case "--run"
      shouldRun = True : i = i + 1
    Case Else
      i = i + 1
  End Select
Loop

Dim allocDir, truthDir, truthFile
allocDir = root & "\share\allocations"
truthDir = root & "\logs\_truth"
truthFile = truthDir & "\fix_dat.jsonl"
If Not fso.FolderExists(truthDir) Then fso.CreateFolder(truthDir)

Dim renamed, modified, skipped
renamed = "" : modified = "" : skipped = ""

If Not shouldRun Then
  skipped = "not scheduled tonight"
ElseIf Not fso.FolderExists(allocDir) Then
  skipped = "no allocation folder yet"
Else
  Dim folder, file, tmpNames(), datNames(), tmpCount, datCount
  Set folder = fso.GetFolder(allocDir)
  ReDim tmpNames(folder.Files.Count)
  ReDim datNames(folder.Files.Count)
  tmpCount = 0 : datCount = 0
  For Each file In folder.Files
    If LCase(fso.GetExtensionName(file.Name)) = "tmp" Then
      tmpNames(tmpCount) = file.Name
      tmpCount = tmpCount + 1
    ElseIf LCase(fso.GetExtensionName(file.Name)) = "dat" Then
      datNames(datCount) = file.Name
      datCount = datCount + 1
    End If
  Next

  Dim j, oldName, newName
  For j = 0 To tmpCount - 1
    oldName = tmpNames(j)
    newName = fso.GetBaseName(oldName) & ".dat"
    ' allocation_gen writes the same .tmp name every top-up night within a
    ' month, so a .dat from an earlier fix_dat pass may already sit here.
    ' MoveFile throws if the destination exists, so clear it first.
    If fso.FileExists(allocDir & "\" & newName) Then
      fso.DeleteFile allocDir & "\" & newName
    End If
    fso.MoveFile allocDir & "\" & oldName, allocDir & "\" & newName
    If renamed <> "" Then renamed = renamed & "|"
    renamed = renamed & "share/allocations/" & newName
  Next

  Dim rewriteLimit, k, ts, contents
  rewriteLimit = 2
  If datCount < rewriteLimit Then rewriteLimit = datCount
  For k = 0 To rewriteLimit - 1
    Set ts = fso.OpenTextFile(allocDir & "\" & datNames(k), 1, False)
    contents = ts.ReadAll
    ts.Close
    Set ts = fso.OpenTextFile(allocDir & "\" & datNames(k), 2, False)
    ts.Write contents & "touched_by_fix_dat_day=" & day & vbCrLf
    ts.Close
    If modified <> "" Then modified = modified & "|"
    modified = modified & "share/allocations/" & datNames(k)
  Next

  If renamed = "" And modified = "" Then skipped = "nothing to fix tonight"
End If

Dim bytesWritten, parts, p, fullPath
bytesWritten = 0
If renamed <> "" Then
  parts = Split(renamed, "|")
  For p = 0 To UBound(parts)
    fullPath = root & "\" & Replace(parts(p), "/", "\")
    If fso.FileExists(fullPath) Then bytesWritten = bytesWritten + fso.GetFile(fullPath).Size
  Next
End If
If modified <> "" Then
  parts = Split(modified, "|")
  For p = 0 To UBound(parts)
    fullPath = root & "\" & Replace(parts(p), "/", "\")
    If fso.FileExists(fullPath) Then bytesWritten = bytesWritten + fso.GetFile(fullPath).Size
  Next
End If

Dim skippedJson, extJson
If skipped = "" Then
  skippedJson = "null"
Else
  skippedJson = """" & skipped & """"
End If
If renamed <> "" Or modified <> "" Then
  extJson = "["".dat""]"
Else
  extJson = "[]"
End If

Dim line
line = "{""job"": ""fix_dat"", ""day"": " & day & _
  ", ""sim_start"": """ & simStart & """, ""sim_end"": """ & simStart & """" & _
  ", ""skipped"": " & skippedJson & _
  ", ""created"": [], ""modified"": " & JsonArray(modified) & _
  ", ""renamed"": " & JsonArray(renamed) & _
  ", ""deleted"": [], ""bytes_written"": " & bytesWritten & _
  ", ""extensions"": " & extJson & "}"

Dim outTs
Set outTs = fso.OpenTextFile(truthFile, 8, True)
outTs.WriteLine line
outTs.Close

Function JsonArray(pipedList)
  If pipedList = "" Then
    JsonArray = "[]"
  Else
    Dim items, q, out
    items = Split(pipedList, "|")
    out = "["
    For q = 0 To UBound(items)
      If q > 0 Then out = out & ", "
      out = out & """" & items(q) & """"
    Next
    out = out & "]"
    JsonArray = out
  End If
End Function
