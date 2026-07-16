# MyGitClient

A cross-platform desktop Git client built with Python and PySide6.

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
