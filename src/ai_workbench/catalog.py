"""Portable, read-only presentation registration; no host-platform lookup."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Launcher:
    id: str
    title: str
    kind: str = "service"


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    launchers: tuple[Launcher, ...] = ()


CATEGORIES = (
    Category("chatgpt", "ChatGPT", (Launcher("commander", "Remote Desktop Commander"),)),
    Category("claude", "Claude", (Launcher("claude", "Claude Code", "terminal"),)),
    Category("codex", "Codex", (Launcher("codex", "Codex CLI", "terminal"),)),
    Category("hermes", "Hermes", (Launcher("hermes", "Hermes Bot"),)),
    Category("opencode", "OpenCode"),
)
LAUNCHERS = tuple(launcher for category in CATEGORIES for launcher in category.launchers)
SERVICE_LAUNCHERS = tuple(launcher for launcher in LAUNCHERS if launcher.kind == "service")
TERMINAL_LAUNCHERS = tuple(launcher for launcher in LAUNCHERS if launcher.kind == "terminal")
DEFAULT_EXPANDED = ("chatgpt", "hermes")


def expanded_categories(preferences: dict) -> set[str]:
    """Missing/malformed fields use defaults; an empty list means all collapsed."""
    value = preferences.get("expanded_categories")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return set(DEFAULT_EXPANDED)
    return set(value) & {category.id for category in CATEGORIES}
