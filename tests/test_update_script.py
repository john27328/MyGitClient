from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_portable_build_includes_the_manual_update_script() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")

    assert "Update-MyGitClient.ps1" in build_script
    assert "Update-MyGitClient.cmd" in build_script
    assert "VERSION.txt" in build_script


def test_manual_update_script_verifies_download_and_requires_app_to_be_closed() -> None:
    script = (PROJECT_ROOT / "scripts" / "Update-MyGitClient.ps1").read_text(encoding="utf-8")

    assert "Get-Process -Name \"MyGitClient\"" in script
    assert "Get-FileHash -LiteralPath $archivePath -Algorithm SHA256" in script
    assert "The downloaded archive failed SHA-256 verification." in script
    assert "Move-Item -LiteralPath $target -Destination $backup" in script


def test_manual_updater_targets_its_own_folder_from_a_temporary_copy() -> None:
    script = (PROJECT_ROOT / "scripts" / "Update-MyGitClient.ps1").read_text(encoding="utf-8")
    launcher = (PROJECT_ROOT / "scripts" / "Update-MyGitClient.cmd").read_text(encoding="utf-8")

    assert "[string]$InstallDirectory = $PSScriptRoot" in script
    assert "[switch]$RunFromTemporaryCopy" in script
    assert "Copy-Item -LiteralPath $PSCommandPath -Destination $bootstrapScript" in script
    assert '"-RunFromTemporaryCopy"' in script
    expected_launcher = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass '
        '-File "%~dp0Update-MyGitClient.ps1" %*'
    )
    assert expected_launcher in launcher
    assert "set updateExitCode=%errorlevel%" in launcher
