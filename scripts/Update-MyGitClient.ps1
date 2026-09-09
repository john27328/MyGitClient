[CmdletBinding()]
param(
    [string]$InstallDirectory = $PSScriptRoot,
    [switch]$CheckOnly,
    [switch]$Yes,
    [switch]$RunFromTemporaryCopy
)

$ErrorActionPreference = "Stop"
$releaseApi = "https://api.github.com/repos/john27328/MyGitClient/releases/latest"
$headers = @{ Accept = "application/vnd.github+json"; "User-Agent" = "MyGitClient-Updater" }

if (-not $RunFromTemporaryCopy) {
    $bootstrapRoot = Join-Path ([IO.Path]::GetTempPath()) ("MyGitClient-updater-" + [guid]::NewGuid())
    $bootstrapScript = Join-Path $bootstrapRoot "Update-MyGitClient.ps1"
    try {
        New-Item -ItemType Directory -Path $bootstrapRoot | Out-Null
        Copy-Item -LiteralPath $PSCommandPath -Destination $bootstrapScript
        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $bootstrapScript,
            "-InstallDirectory",
            $PSScriptRoot,
            "-RunFromTemporaryCopy"
        )
        if ($CheckOnly) {
            $arguments += "-CheckOnly"
        }
        if ($Yes) {
            $arguments += "-Yes"
        }
        & powershell.exe @arguments
        $exitCode = $LASTEXITCODE
        exit $exitCode
    } finally {
        if (Test-Path -LiteralPath $bootstrapRoot) {
            Remove-Item -LiteralPath $bootstrapRoot -Recurse -Force
        }
    }
}

function Get-InstalledVersion([string]$Directory) {
    $versionFile = Join-Path $Directory "VERSION.txt"
    if (-not (Test-Path -LiteralPath $versionFile)) {
        return $null
    }
    $value = (Get-Content -LiteralPath $versionFile -Raw).Trim()
    try {
        return [version]$value
    } catch {
        return $null
    }
}

function Get-Checksum([string]$Path) {
    $value = (Get-Content -LiteralPath $Path -Raw).Trim()
    if ($value -notmatch '^([0-9a-fA-F]{64})(\s|$)') {
        throw "The downloaded checksum is invalid."
    }
    return $matches[1].ToLowerInvariant()
}

$target = (Resolve-Path -LiteralPath $InstallDirectory).Path
$executable = Join-Path $target "MyGitClient.exe"
if (-not (Test-Path -LiteralPath $executable)) {
    throw "MyGitClient.exe was not found in $target."
}
if (Get-Process -Name "MyGitClient" -ErrorAction SilentlyContinue) {
    throw "Close MyGitClient before running this script."
}

$release = Invoke-RestMethod -Uri $releaseApi -Headers $headers
$tag = [string]$release.tag_name
try {
    $latestVersion = [version]$tag.TrimStart("v")
} catch {
    throw "The latest release tag '$tag' is not a version number."
}
$installedVersion = Get-InstalledVersion $target
if ($installedVersion -and $latestVersion -le $installedVersion) {
    Write-Host "MyGitClient $installedVersion is already up to date."
    exit 0
}

$archive = @($release.assets | Where-Object {
    $_.name -match '^MyGitClient-.+-windows-x64\.zip$'
}) | Select-Object -First 1
if ($null -eq $archive) {
    throw "Release $tag does not contain a Windows x64 portable archive."
}
$checksum = @($release.assets | Where-Object {
    $_.name -eq "$($archive.name).sha256"
}) | Select-Object -First 1
if ($null -eq $checksum) {
    throw "Release $tag does not contain a SHA-256 checksum for $($archive.name)."
}

Write-Host "Available: MyGitClient $latestVersion"
if ($CheckOnly) {
    exit 0
}
if (-not $Yes) {
    $answer = Read-Host "Install this update? [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host "Update cancelled."
        exit 0
    }
}

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("MyGitClient-update-" + [guid]::NewGuid())
$archivePath = Join-Path $temporaryRoot $archive.name
$checksumPath = "$archivePath.sha256"
$staging = Join-Path $temporaryRoot "expanded"
$backup = Join-Path (Split-Path -Parent $target) "MyGitClient.update-backup"
if (Test-Path -LiteralPath $backup) {
    throw "A previous update backup exists at $backup. Review it before retrying."
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    Invoke-WebRequest -Uri $archive.browser_download_url -Headers $headers -OutFile $archivePath
    Invoke-WebRequest -Uri $checksum.browser_download_url -Headers $headers -OutFile $checksumPath
    $expected = Get-Checksum $checksumPath
    $actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "The downloaded archive failed SHA-256 verification."
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $staging -Force
    $source = Join-Path $staging "MyGitClient"
    if (-not (Test-Path -LiteralPath (Join-Path $source "MyGitClient.exe"))) {
        throw "The update archive does not contain MyGitClient.exe."
    }
    Move-Item -LiteralPath $target -Destination $backup
    try {
        Move-Item -LiteralPath $source -Destination $target
    } catch {
        Move-Item -LiteralPath $backup -Destination $target
        throw
    }
    Remove-Item -LiteralPath $backup -Recurse -Force
    Write-Host "Updated MyGitClient to $latestVersion."
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
