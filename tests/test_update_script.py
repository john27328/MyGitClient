from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_portable_build_includes_the_manual_update_script() -> None:
    build_script = (PROJECT_ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")

    assert "Update-MyGitClient.ps1" in build_script
    assert "VERSION.txt" in build_script


def test_manual_update_script_verifies_download_and_requires_app_to_be_closed() -> None:
    script = (PROJECT_ROOT / "scripts" / "Update-MyGitClient.ps1").read_text(encoding="utf-8")

    assert "Get-Process -Name \"MyGitClient\"" in script
    assert "Get-FileHash -LiteralPath $archivePath -Algorithm SHA256" in script
    assert "The downloaded archive failed SHA-256 verification." in script
    assert "Move-Item -LiteralPath $target -Destination $backup" in script
