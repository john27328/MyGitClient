# MyGitClient agent guide

These instructions apply to the entire repository.

## Start here

1. Read `PLAN.md` before changing the product.
2. Inspect `git status` and preserve unrelated user changes.
3. Work in a small vertical slice that leaves the application runnable.
4. Update `PLAN.md` when a listed item is completed or its scope changes.

## Product and stack

MyGitClient is a cross-platform desktop Git client.

- Python 3.12+
- PySide6 with Qt Widgets
- The user's system `git` executable is the source of truth
- `QProcess` is used for non-blocking Git commands
- `QSettings` stores lightweight application and workspace preferences
- pytest, pytest-qt, Ruff, and Pyright are required checks

Do not introduce GitPython, pygit2, QML, asyncio event-loop adapters, a database, or a
new UI framework without an explicit architectural decision from the user.

## Architecture boundaries

- `src/mygitclient/ui/`: widgets and presentation logic only.
- `src/mygitclient/git/`: Git commands, process execution, parsers, and Git models.
- `src/mygitclient/workspace/`: repository discovery and workspace persistence.
- `src/mygitclient/app.py`: application composition and startup.
- `tests/`: unit and integration tests; real temporary repositories are preferred for
  Git behavior.

UI code may call service APIs, but it must not construct ad-hoc Git subprocesses or
parse Git output. Git and workspace modules must not import UI widgets.

## Git integration rules

- Never block the Qt GUI thread. Use `GitRunner`/`QProcess` for application commands.
- Prefer stable machine-readable Git output such as porcelain v2 and NUL delimiters.
- Preserve filenames using UTF-8 with `surrogateescape` where raw Git output is parsed.
- Set `GIT_TERMINAL_PROMPT=0` for operations that cannot display an interactive prompt.
- Keep command arguments as sequences; never build shell command strings.
- Retain runner objects until completion so Qt cannot collect active processes.
- Destructive actions (discard, reset, delete, force push) require explicit UI
  confirmation and focused tests.
- Use `--force-with-lease`; do not expose plain force push as the default operation.

## UI conventions

- Use Qt Widgets and model/view APIs for data-heavy screens.
- Give widgets used by tests stable `objectName` values.
- Use signals and slots at asynchronous boundaries.
- Keep themes exclusive and restore the native system palette/style for System mode.
- User-facing failures must be understandable; detailed diagnostics belong in logs.
- Every long-running operation needs visible progress and a cancellation path.

## Local setup and checks

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pyright.exe --pythonpath .\.venv\Scripts\python.exe
.\.venv\Scripts\pytest.exe
```

On macOS/Linux, use `.venv/bin/` equivalents. Run GUI tests with
`QT_QPA_PLATFORM=offscreen` on headless Linux.

Before handing work back, run all three checks. For UI startup or process-lifecycle
changes, also perform an offscreen smoke launch. Do not claim checks passed unless they
were run successfully in the current working tree.

## Test expectations

- Parser edge cases get focused byte-level unit tests.
- Git operations get integration tests using a temporary real repository.
- UI behavior gets pytest-qt tests without modal dialogs blocking the test run.
- Tests must not depend on global Git user configuration, network access, GitHub, or a
  pre-existing repository.
- Configure test commit identity per command with `git -c user.name=... -c
  user.email=...`.

## Change discipline

- Keep strict Pyright clean; avoid broad `Any`, ignores, and untyped signal payloads.
- Keep Ruff clean and the line length at 100.
- Use `apply_patch` for intentional source edits.
- Do not commit, push, rewrite history, or publish unless the user asks.
- Do not edit completed checklist items merely to make the plan look current; record
  scope changes explicitly.

