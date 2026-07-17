[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $root ".build\windows"
$distRoot = Join-Path $buildRoot "dist"
$workRoot = Join-Path $buildRoot "work"
$specRoot = Join-Path $buildRoot "spec"
$artifactsRoot = Join-Path $root "artifacts"
$packageRoot = Join-Path $distRoot "MyGitClient"

function Assert-ProjectPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing to modify a path outside the repository: $full"
    }
}

function Remove-BuildPath([string]$Path) {
    Assert-ProjectPath $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

if ($env:OS -ne "Windows_NT") {
    throw "This script builds the Windows portable archive and must run on Windows."
}

if (-not $Python) {
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $Python = $venvPython
    } else {
        $Python = "python"
    }
}

$versionLine = Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "(.+)"$'
if (-not $versionLine) {
    throw "Could not read the project version from pyproject.toml."
}
$version = $versionLine.Matches[0].Groups[1].Value
$architecture = if ([Environment]::Is64BitProcess) { "x64" } else { "x86" }
$archiveName = "MyGitClient-$version-windows-$architecture.zip"
$archivePath = Join-Path $artifactsRoot $archiveName

if (-not $SkipInstall) {
    & $Python -m pip install --disable-pip-version-check -e "$root[build]"
    if ($LASTEXITCODE -ne 0) {
        throw "Installing build dependencies failed."
    }
}

Remove-BuildPath $buildRoot
New-Item -ItemType Directory -Force $distRoot, $workRoot, $specRoot, $artifactsRoot |
    Out-Null

$icon = Join-Path $root "src\mygitclient\resources\icons\app-icon.ico"
$entryPoint = Join-Path $root "src\mygitclient\__main__.py"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name MyGitClient `
    --icon $icon `
    --collect-data mygitclient.resources `
    --distpath $distRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    $entryPoint
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

$launcher = @'
@echo off
start "" "%~dp0MyGitClient.exe"
'@
Set-Content -LiteralPath (Join-Path $packageRoot "Launch MyGitClient.cmd") `
    -Value $launcher -Encoding Ascii

$readme = @"
MyGitClient $version portable for Windows $architecture

Run MyGitClient.exe or double-click "Launch MyGitClient.cmd".
Python and application dependencies are included in this folder.
The system Git executable must still be installed and available in PATH.
"@
Set-Content -LiteralPath (Join-Path $packageRoot "README.txt") `
    -Value $readme -Encoding UTF8

if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}
& tar.exe -a -c -f $archivePath -C $distRoot "MyGitClient"
if ($LASTEXITCODE -ne 0) {
    throw "Creating the portable ZIP archive failed."
}

$sizeMb = [math]::Round((Get-Item -LiteralPath $archivePath).Length / 1MB, 1)
Write-Host "Built $archivePath ($sizeMb MB)"
