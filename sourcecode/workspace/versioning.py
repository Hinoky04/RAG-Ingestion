"""Version-label parsing used by workspace upload flows."""

from __future__ import annotations

import re


VERSION_PATTERN = re.compile(r"^(?:v)?(\d+)(?:\.(\d+))?$", re.IGNORECASE)


def parse_version_number(value: str) -> tuple[int, int] | None:
    match = VERSION_PATTERN.match(value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def next_version_label(existing_versions: list[str]) -> str:
    parsed_versions = [parsed for version in existing_versions if (parsed := parse_version_number(version)) is not None]
    if not parsed_versions:
        return "1"

    major, minor = max(parsed_versions)
    if minor == 0:
        return f"{major}.1"
    if minor < 9:
        return f"{major}.{minor + 1}"
    return f"{major + 1}.0"
