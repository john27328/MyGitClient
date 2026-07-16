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
