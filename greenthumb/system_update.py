"""Checking for and installing a newer GreenThumb package from the web UI.

The API never runs apt. It starts one of two systemd units through a sudoers
rule that allows exactly that, and reads back the status file the units write:

- greenthumb-update-check.service refreshes the greenthumb package source, so
  apt knows whether a newer version exists. A timer runs it daily as well.
- greenthumb-update.service installs it. A unit of its own because the
  install restarts this API; anything the API ran itself would be killed
  halfway through.

Both run /usr/lib/greenthumb/greenthumb-update, which writes
update-status.json beside state.json.

Only an installed package can update this way. A git checkout reports that it
cannot, and is updated the way it always was.
"""

from __future__ import annotations

import json
import logging
import subprocess

from greenthumb import paths

logger = logging.getLogger(__name__)

SYSTEMCTL = "/usr/bin/systemctl"
UPDATE_UNIT = "greenthumb-update.service"
CHECK_UNIT = "greenthumb-update-check.service"
COMMAND_TIMEOUT = 10


def status_path():
    return paths.DATA_DIR / "update-status.json"


def _run(command: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("%s failed: %s", command[0], exc)
        return None


def installed_version() -> str | None:
    result = _run(["dpkg-query", "-W", "-f=${Version}", "greenthumb"])
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def newer(candidate: str | None, installed: str | None) -> bool:
    """Whether apt would treat `candidate` as an upgrade, by Debian's rules."""
    if not candidate or not installed:
        return False
    result = _run(["dpkg", "--compare-versions", candidate, "gt", installed])
    return result is not None and result.returncode == 0


def unit_active(unit: str) -> bool:
    """Whether a unit is running now. Activating counts: it has been started."""
    result = _run([SYSTEMCTL, "is-active", unit])
    return result is not None and result.stdout.strip() in ("active", "activating")


def _stored() -> dict[str, object]:
    try:
        data = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def status() -> dict[str, object]:
    """What is installed, what is available, and how the last check or update went."""
    if not paths.PACKAGED:
        return {
            "supported": False,
            "detail": (
                "This planter runs from a git checkout, so it is not updated from "
                "here. Install the greenthumb package to get updates in the web UI."
            ),
        }

    stored = _stored()
    # Installed is read live rather than from the file: after an update the
    # file can say what was installed before it.
    installed = installed_version()
    candidate = stored.get("candidate") if isinstance(stored.get("candidate"), str) else None
    updating = unit_active(UPDATE_UNIT)
    state = stored.get("state")
    if state == "running" and not updating:
        # The unit ended without writing done or failed -- killed, or the Pi
        # lost power mid-update. Say so rather than show it running for ever.
        state = "interrupted"
    went_wrong = state in ("failed", "interrupted") or stored.get("check_state") == "failed"
    return {
        "supported": True,
        "installed": installed,
        "available": candidate if newer(candidate, installed) else None,
        "checked_at": stored.get("checked_at"),
        "checking": unit_active(CHECK_UNIT),
        "check_failed": stored.get("check_state") == "failed",
        "updating": updating,
        "state": state,
        "from": stored.get("from"),
        "finished_at": stored.get("finished_at"),
        "log_tail": stored.get("log_tail") if went_wrong else None,
    }


def _start(unit: str) -> None:
    command = [SYSTEMCTL, "start", "--no-block", unit]
    allowed = _run(["sudo", "-n", "-l", *command])
    if allowed is None or allowed.returncode != 0:
        raise RuntimeError(
            "This planter is not allowed to update itself. Reinstall the greenthumb "
            "package, which adds the permission, or run sudo apt upgrade over SSH."
        )
    result = _run(["sudo", "-n", *command])
    if result is None or result.returncode != 0:
        detail = ((result.stderr or result.stdout).strip() if result else "") or "no output"
        raise RuntimeError(f"Could not start {unit}: {detail}")


def check() -> dict[str, object]:
    """Look for a newer version now, rather than waiting for the daily timer."""
    if not paths.PACKAGED:
        raise ValueError("Updates are only available on an installed package")
    _start(CHECK_UNIT)
    return status()


def start() -> None:
    """Begin installing the newer version. The caller holds the hardware lock."""
    _start(UPDATE_UNIT)
