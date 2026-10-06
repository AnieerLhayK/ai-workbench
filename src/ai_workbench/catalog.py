"""Portable, read-only presentation registration; no host-platform lookup."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Launcher:
    id: str
    title: str


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    launcher: Launcher | None = None


CATEGORIES = (
    Category("chatgpt", "ChatGPT", Launcher("commander", "Remote Desktop Commander")),
    Category("claude", "Claude"),
    Category("codex", "Codex"),
    Category("hermes", "Hermes", Launcher("hermes", "Hermes Bot")),
    Category("opencode", "OpenCode"),
)
LAUNCHERS = tuple(category.launcher for category in CATEGORIES if category.launcher)
DEFAULT_EXPANDED = ("chatgpt", "hermes")


def expanded_categories(preferences: dict) -> set[str]:
    """Missing/malformed fields use defaults; an empty list means all collapsed."""
    value = preferences.get("expanded_categories")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return set(DEFAULT_EXPANDED)
    return set(value) & {category.id for category in CATEGORIES}
