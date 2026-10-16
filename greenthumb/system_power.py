"""Shutting the Pi down or rebooting it from the UI.

Pulling the plug on a running Pi can leave the SD card's filesystem dirty, and
the next boot then stops in a filesystem check or emergency mode with no SSH and
no web page. A shutdown button turns "unplug it" into "press this, wait, then
unplug it".

The service runs as pi, so this goes through a sudoers rule the installer
writes, scoped to exactly `systemctl poweroff` and `systemctl reboot`. The
command is a fixed list chosen from an allow-list, never built from the request.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

SYSTEMCTL = "/usr/bin/systemctl"
COMMAND_TIMEOUT = 10
# Long enough for the reply to reach the browser before the network goes down.
# Run immediately, the request would hang and the page would report a failure
# for a shutdown that worked.
DELAY_SECONDS = 2.0

VERBS = {"shutdown": "poweroff", "reboot": "reboot"}


def _run(command: list[str], on_failure: Callable[[], None] | None) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("Could not run %s: %s", " ".join(command), exc)
    else:
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        logger.error("%s failed: %s", " ".join(command), detail)
    if on_failure is not None:
        on_failure()


def request(
    action: str,
    delay: float | None = None,
    on_failure: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Schedule a shutdown or reboot, after checking it is allowed.

    The permission is checked up front with `sudo -n -l`, which runs nothing:
    the command itself runs after the reply has gone, so a refusal at that
    point could only be logged, and the page would show success for a Pi that
    stayed up.

    `on_failure` runs if the delayed command fails, so a caller holding
    something until the Pi goes down can let go of it again.
    """
    verb = VERBS.get(action)
    if verb is None:
        raise ValueError(f"Unknown power action: {action!r}")

    command = [SYSTEMCTL, verb]
    try:
        allowed = subprocess.run(
            ["sudo", "-n", "-l", *command],
            capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Could not run sudo: {exc}") from exc
    if allowed.returncode != 0:
        raise RuntimeError(
            f"This planter is not allowed to {action} itself yet. Re-run the "
            "installer, which adds the permission, or use "
            f"sudo systemctl {verb} over SSH."
        )

    if delay is None:
        delay = DELAY_SECONDS
    timer = threading.Timer(delay, _run, args=(["sudo", "-n", *command], on_failure))
    timer.daemon = True
    timer.start()
    logger.info("%s requested, running in %.0fs", action.capitalize(), delay)
    return {"status": "ok", "action": action, "in_seconds": delay}
