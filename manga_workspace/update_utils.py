"""Pure helpers for release comparison and archive validation."""
import re
from pathlib import PurePosixPath


def version_key(value):
    text = str(value or "").strip().lower().lstrip("v")
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(alpha|beta|rc)(\d*)?)?$", text)
    if not match:
        return (0, 0, 0, -1, 0)
    major, minor, patch = (int(match.group(i) or 0) for i in range(1, 4))
    stage = match.group(4)
    rank = {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage]
    stage_number = int(match.group(5) or 0)
    return (major, minor, patch, rank, stage_number)


def is_newer(candidate, current):
    return version_key(candidate) > version_key(current)


def safe_archive_names(names):
    for name in names:
        normalized = str(name).replace("\\", "/")
        path = PurePosixPath(normalized)
        if (not normalized or normalized.startswith("/") or ":" in normalized or
                any(part in ("", ".", "..") for part in path.parts)):
            return False
        if path.parts[0] not in ("manga_workspace", "manga_workspace.desktop",
                                 "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
                                 "CHANGELOG.md"):
            return False
    return True
