from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from PySide6.QtCore import QSettings

_BINDINGS_KEY = "github/repositoryProfileBindings"


class GitHubRepositoryBindingStore:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def profile_label(self, repository: Path) -> str | None:
        return self._bindings().get(str(repository.resolve()))

    def bind(self, repository: Path, profile_label: str | None) -> None:
        bindings = self._bindings()
        key = str(repository.resolve())
        if profile_label is None:
            bindings.pop(key, None)
        else:
            bindings[key] = profile_label
        self._settings.setValue(_BINDINGS_KEY, json.dumps(bindings, ensure_ascii=False))

    def remove_profile(self, profile_label: str) -> None:
        bindings = {
            path: label for path, label in self._bindings().items() if label != profile_label
        }
        self._settings.setValue(_BINDINGS_KEY, json.dumps(bindings, ensure_ascii=False))

    def _bindings(self) -> dict[str, str]:
        value = self._settings.value(_BINDINGS_KEY, "{}")
        if not isinstance(value, str):
            return {}
        try:
            parsed: object = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {
            path: label
            for path, label in cast(dict[object, object], parsed).items()
            if isinstance(path, str) and isinstance(label, str)
        }
