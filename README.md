# MyGitClient

A cross-platform desktop Git client built with Python and PySide6.

Development conventions and architecture are documented in [AGENTS.md](AGENTS.md).
The current roadmap is maintained as a checklist in [PLAN.md](PLAN.md).

## Development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
mygitclient
```

Run the checks with:

```powershell
ruff check .
pyright --pythonpath python
pytest
```
# MyGitClient

## Branches

- `develop` is the working branch for ongoing development.
- `master` contains release-ready code only. Changes reach it through a reviewed merge
  from `develop`.
- Version tags such as `v0.1.0` are created from `master` and trigger the portable
  Windows build.

## Portable Windows build

Run from PowerShell:

```powershell
.\scripts\build-windows.ps1
```

The script installs the optional build dependencies into the selected Python
environment, bundles the application and Python runtime with PyInstaller, and writes
`artifacts/MyGitClient-<version>-windows-<architecture>.zip`.

By default it uses `.venv\Scripts\python.exe` when available. Pass `-Python` to select
another Python executable, or `-SkipInstall` when the build dependencies are already
installed:

```powershell
.\scripts\build-windows.ps1 -Python C:\Python312\python.exe -SkipInstall
```

The extracted archive can be started with `MyGitClient.exe` or
`Launch MyGitClient.cmd`. Git itself is not bundled and must be installed on the target
computer.

The build script extracts the finished ZIP into a clean temporary build directory and
starts that copy in smoke-test mode. It also writes a matching `.zip.sha256` checksum
file into `artifacts/`.

### GitHub Actions

The `Windows portable` workflow builds and smoke-tests the same archive on a clean
Windows runner. Run it manually from the Actions page, or push a tag whose name starts
with `v` (for example, `v0.1.0`). The workflow stores the ZIP and its SHA-256 checksum
as the `MyGitClient-windows-portable` workflow artifact.
