"""What is actually running, as opposed to what is checked out.

Twice now a pull has landed while the service kept serving the code it started
with: once as a 404 on a route the new page expected, once as settings that
should have reset and did not. Both were invisible until something broke oddly.

So this reports two commits, not one. `running` is captured when the process
starts and never changes; `checkout` is read live from the working tree. If
they differ, somebody pulled and did not restart, and the UI can say so instead
of leaving you to infer it from strange behaviour.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
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


def _package_version() -> str:
    try:
        from importlib.metadata import version
        return version("greenthumb")
    except Exception:
        pass
    # Not pip-installed, e.g. running straight from a checkout. The file is
    # right there, so read it rather than reporting "unknown".
    try:
        import tomllib
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data["project"]["version"])
    except Exception:
        return "unknown"


def checkout_commit() -> str | None:
    """The commit in the working tree right now."""
    return _git("rev-parse", "--short", "HEAD")


# Captured once, at import, which is what makes the comparison meaningful: it
# is the commit this process loaded its code from.
RUNNING_COMMIT = checkout_commit()
RUNNING_DESCRIBE = _git("describe", "--tags", "--always", "--dirty")


def status() -> dict[str, object]:
    current = checkout_commit()
    stale = bool(RUNNING_COMMIT and current and RUNNING_COMMIT != current)
    return {
        "version": _package_version(),
        "running_commit": RUNNING_COMMIT,
        "checkout_commit": current,
        "describe": RUNNING_DESCRIBE,
        # True when the files on disk have moved on from the process serving
        # them: a pull happened without a restart.
        "stale": stale,
    }
