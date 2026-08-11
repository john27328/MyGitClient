from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import cast

from PySide6.QtCore import QSettings

_PROFILES_KEY = "github/profiles"


@dataclass(frozen=True, slots=True)
class GitHubProfile:
    label: str
    login: str
    clone_transport: str = "https"
    user_name: str = ""
    user_email: str = ""

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Profile label cannot be empty")
        if not self.login.strip():
            raise ValueError("GitHub login cannot be empty")
        if self.clone_transport not in {"https", "ssh"}:
            raise ValueError("Clone transport must be HTTPS or SSH")


class GitHubProfileStore:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def profiles(self) -> tuple[GitHubProfile, ...]:
        value = self._settings.value(_PROFILES_KEY, "[]")
        if not isinstance(value, str):
            return ()
        try:
            records: object = json.loads(value)
        except json.JSONDecodeError:
            return ()
        if not isinstance(records, list):
            return ()
        result: list[GitHubProfile] = []
        for record in cast(list[object], records):
            if not isinstance(record, dict):
                continue
            values = cast(dict[str, object], record)
            try:
                profile = GitHubProfile(
                    label=_string_value(values, "label").strip(),
                    login=_string_value(values, "login").strip(),
                    clone_transport=_string_value(values, "clone_transport", "https"),
                    user_name=_string_value(values, "user_name").strip(),
                    user_email=_string_value(values, "user_email").strip(),
                )
            except ValueError:
                continue
            result.append(profile)
        return tuple(result)

    def save(self, profile: GitHubProfile, *, previous_label: str | None = None) -> None:
        profiles = list(self.profiles())
        replaced = previous_label or profile.label
        profiles = [item for item in profiles if item.label != replaced]
        if any(item.label == profile.label for item in profiles):
            raise ValueError(f"A GitHub profile named '{profile.label}' already exists")
        profiles.append(profile)
        profiles.sort(key=lambda item: item.label.casefold())
        self._write(profiles)

    def remove(self, label: str) -> None:
        self._write([profile for profile in self.profiles() if profile.label != label])

    def _write(self, profiles: list[GitHubProfile]) -> None:
        self._settings.setValue(
            _PROFILES_KEY,
            json.dumps([asdict(profile) for profile in profiles], ensure_ascii=False),
        )


def _string_value(values: dict[str, object], key: str, default: str = "") -> str:
    value = values.get(key, default)
    return value if isinstance(value, str) else default
