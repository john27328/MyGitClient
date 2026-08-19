# MyGitClient agent guide

These instructions apply to the entire repository.

## Start here

1. Read the roadmap board before changing the product. It lives outside this repository,
   in the user's notes vault — see `Roadmap board` below.
2. Inspect `git status` and preserve unrelated user changes.
3. Work in a small vertical slice that leaves the application runnable.
4. Move the matching card on the board when an item is completed or its scope changes.

## Roadmap board

The roadmap is not stored in this repository. It is an Obsidian Kanban board in the user's
notes vault, one Markdown card per item.

- Ask the user for the vault path when it is unknown, or locate it by searching for a
  `Мой гит клиент.md` note containing a ```board``` block, or for cards tagged
  `#git_client`. As of 2026-08-19 it was
  `D:\GitHub\home\notes\10 Проекты\Мой гит клиент`, but do not assume that path still
  holds — confirm it before relying on it.
- Never recreate a plan file inside this repository. `PLAN.md` was migrated to the board
  on 2026-08-19; its history stays in Git.

Columns, in order:

- `План` — raw, unprocessed AI-generated wishes. Anything an agent proposes lands here and
  waits for the user to triage it. Do not start work from this column on your own.
- `Бэклог` — triaged work that should actually be done.
- `Базовые задачи` — a card grouping a whole area (mirrors PLAN.md's old `##` sections).
- `В работе`, `Ревью`, `Готово` — the usual meanings.

Card conventions, matching the sibling `Fingrad` board in the same vault:

- `Статус` in the front matter is the column; `Порядок` is the position inside it.
- A card grouping an area lives in the `Базовые задачи` column. Item cards point back to it
  with `BaseTask: "[[…]]"` in the front matter; do not maintain a manual list of children on
  the group card — every card's `## Заметки` ends with a `dataviewjs` block that queries
  `BaseTask` and renders the children table automatically.
- Put the full wording in `## Цель` and any detail in `## Заметки`; keep the file name a
  short title.
- New cards should come from `90 Служебное\шаблоны\Мой гит клиент\Карточка.md`, which
  already has the `BaseTask` field and the `dataviewjs` block.

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
$env:TEMP = "$PWD\.test-tmp-session"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pyright.exe --pythonpath .\.venv\Scripts\python.exe
.\.venv\Scripts\pytest.exe -p no:cacheprovider --basetemp "$env:TEMP\full"
```

On Windows, always redirect `TEMP` and `TMP` to the workspace-local
`.test-tmp-session` directory before invoking pytest. The system pytest temp root under
`AppData\Local\Temp` can reject sandboxed processes even when the test code is correct. Use a
unique child of `.test-tmp-session` for each concurrent or repeated run, and remove the local
temp root after the final test run only after resolving it and verifying that it remains inside
the workspace. Never report a system-temp permission failure as a product or test failure.

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
- Do not move cards to `Готово` merely to make the board look current; record scope
  changes explicitly on the card instead.
