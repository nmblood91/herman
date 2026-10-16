"""What is actually running, as opposed to what is on disk.

Twice now a pull has landed while the service kept serving the code it started
with: once as a 404 on a route the new page expected, once as settings that
should have reset and did not. Both were invisible until something broke oddly.

So this reports two commits, not one. `running` is captured when the process
starts and never changes; `checkout` is read live from disk. If they differ,
new code arrived without a restart, and the UI can say so instead of leaving
you to infer it from strange behaviour.

Two kinds of "on disk". A git checkout reads the working tree's commit. An
installed package has no git at all, and reads BUILD_INFO.json, which CI writes
into the package; there the same mismatch means a package was upgraded and the
service was not restarted.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from greenthumb import paths

logger = logging.getLogger(__name__)

REPO_ROOT = paths.ROOT
COMMAND_TIMEOUT = 5


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git unavailable: %s", exc)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_info() -> dict[str, object]:
    """BUILD_INFO.json from an installed package, or {} in a checkout."""
    try:
        data = json.loads(paths.BUILD_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _package_version() -> str:
    built = build_info().get("version")
    if isinstance(built, str):
        return built
    # Not installed as a package, e.g. running straight from a checkout. The
    # file is right there, so read it rather than reporting "unknown".
    try:
        import tomllib
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


def checkout_commit() -> str | None:
    """The commit on disk right now."""
    if paths.PACKAGED:
        commit = build_info().get("commit")
        return commit if isinstance(commit, str) else None
    return _git("rev-parse", "--short", "HEAD")


def klipper_commit() -> str | None:
    """The Klipper commit this release bundles and its firmware.bin matches."""
    pinned = build_info().get("klipper_commit")
    if isinstance(pinned, str):
        return pinned
    try:
        return (REPO_ROOT / "deploy" / "klipper" / "KLIPPER_COMMIT").read_text(encoding="utf-8").strip()
    except OSError:
        return None


# Captured once, at import, which is what makes the comparison meaningful: it
# is the code this process loaded.
RUNNING_COMMIT = checkout_commit()
RUNNING_VERSION = _package_version()
RUNNING_DESCRIBE = None if paths.PACKAGED else _git("describe", "--tags", "--always", "--dirty")


def status() -> dict[str, object]:
    current = checkout_commit()
    on_disk = _package_version()
    stale = bool(
        (RUNNING_COMMIT and current and RUNNING_COMMIT != current)
        or (paths.PACKAGED and on_disk != RUNNING_VERSION)
    )
    return {
        "version": RUNNING_VERSION,
        "packaged": paths.PACKAGED,
        "running_commit": RUNNING_COMMIT,
        "checkout_commit": current,
        "describe": RUNNING_DESCRIBE,
        "klipper_commit": klipper_commit(),
        # True when the code on disk has moved on from the process serving it:
        # a pull, or a package upgrade, without a restart.
        "stale": stale,
    }
