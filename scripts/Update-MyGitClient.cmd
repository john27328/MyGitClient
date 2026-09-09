@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-MyGitClient.ps1" %*
set updateExitCode=%errorlevel%
if not %updateExitCode%==0 pause
exit /b %updateExitCode%
