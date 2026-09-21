@echo off
setlocal EnableDelayedExpansion

set "ROOT="
set "DAY="
set "SIMSTART="
set "SIMEND="
set "FILES="
set "THRESHOLDKB="

:parse
if "%~1"=="" goto :parsed
if /I "%~1"=="--root" (set "ROOT=%~2" & shift & shift & goto :parse)
if /I "%~1"=="--day" (set "DAY=%~2" & shift & shift & goto :parse)
if /I "%~1"=="--sim-start" (set "SIMSTART=%~2" & shift & shift & goto :parse)
if /I "%~1"=="--sim-end" (set "SIMEND=%~2" & shift & shift & goto :parse)
if /I "%~1"=="--files" (set "FILES=%~2" & shift & shift & goto :parse)
if /I "%~1"=="--threshold-kb" (set "THRESHOLDKB=%~2" & shift & shift & goto :parse)
shift
goto :parse
:parsed

set "EXPORTS=%ROOT%\share\exports"
set "ARCHIVE=%ROOT%\archive"
set "TRUTHDIR=%ROOT%\logs\_truth"
set "TRUTHFILE=%TRUTHDIR%\archive_old.jsonl"
if not exist "%TRUTHDIR%" mkdir "%TRUTHDIR%"
if not exist "%ARCHIVE%" mkdir "%ARCHIVE%"

set "JOB=archive_old"
set "SKIPPED="
set "CREATED=" & set "MODIFIED=" & set "RENAMED=" & set "DELETED=" & set "BYTES=0" & set "EXT="

REM archive_old owns exactly this pattern and never wildcards the whole
REM folder: a clean-up job that eats a future canary file (case 10 in
REM SOLUTION_DESIGN.md) is a false INCIDENT.
set "PATTERN=epos_day_end_*.csv"

set /a THRESHOLDBYTES=%THRESHOLDKB%*1024
set /a TOTALBYTES=0
if exist "%EXPORTS%\%PATTERN%" (
  for %%F in ("%EXPORTS%\%PATTERN%") do set /a TOTALBYTES+=%%~zF
)

if %TOTALBYTES% LSS %THRESHOLDBYTES% (call :skip "below size threshold" & goto :eof)

set "SELECTED="
set /a COUNT=0
for /f "delims=" %%F in ('dir /b /o:n "%EXPORTS%\%PATTERN%" 2^>nul') do (
  if !COUNT! LSS %FILES% (
    set "SELECTED=!SELECTED! %%F"
    set /a COUNT+=1
  )
)

if %COUNT% EQU 0 (call :skip "no export files to archive" & goto :eof)

set "ZIPNAME=archive_day%DAY%_%RANDOM%.zip"
set "ZIPPATH=%ARCHIVE%\%ZIPNAME%"
set "LISTFILE=%TRUTHDIR%\archive_old_day%DAY%_%RANDOM%.filelist"
(for %%F in (!SELECTED!) do @echo %%F)>"%LISTFILE%"

REM The absolute path avoids picking up a different tar.exe earlier on
REM PATH (Git for Windows ships a GNU tar that reads "C:\..." as a remote
REM host:path spec and fails outright).
pushd "%EXPORTS%"
"%SystemRoot%\System32\tar.exe" -a -cf "%ZIPPATH%" -T "%LISTFILE%"
set "TAR_RESULT=%ERRORLEVEL%"
popd
del "%LISTFILE%"

if not "%TAR_RESULT%"=="0" (call :skip "archive step failed" & goto :eof)

set "DELETED="
for %%F in (!SELECTED!) do (
  if "!DELETED!"=="" (set "DELETED=share/exports/%%F") else (set "DELETED=!DELETED!|share/exports/%%F")
  del "%EXPORTS%\%%F"
)

for %%Z in ("%ZIPPATH%") do set "ZIPBYTES=%%~zZ"

set "CREATED=archive/%ZIPNAME%" & set "DELETED=%DELETED%" & set "BYTES=%ZIPBYTES%" & set "EXT=.zip|.csv"
call :write_truth
goto :eof

:skip
set "SKIPPED=%~1"
call :write_truth
goto :eof

:write_truth
powershell -NoProfile -Command "$c=$env:CREATED -split '\|' | Where-Object {$_ -ne ''}; $m=$env:MODIFIED -split '\|' | Where-Object {$_ -ne ''}; $r=$env:RENAMED -split '\|' | Where-Object {$_ -ne ''}; $d=$env:DELETED -split '\|' | Where-Object {$_ -ne ''}; $e=$env:EXT -split '\|' | Where-Object {$_ -ne ''}; $skip = if ($env:SKIPPED) {$env:SKIPPED} else {$null}; $obj=[ordered]@{job=$env:JOB;day=[int]$env:DAY;sim_start=$env:SIMSTART;sim_end=$env:SIMEND;skipped=$skip;created=@($c);modified=@($m);renamed=@($r);deleted=@($d);bytes_written=[int64]$env:BYTES;extensions=@($e)}; ($obj | ConvertTo-Json -Compress) | Add-Content -Path $env:TRUTHFILE -Encoding ascii"
goto :eof
