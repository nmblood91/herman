"""Reading and changing the Pi's network name, the <name> in <name>.local.

Every planter flashes as "herman". That only matters with two on one network:
mDNS gives the name to whichever boots first and calls the other herman-2, so
herman.local can mean a different planter after a reboot. Renaming one fixes
it, and the UI does that rather than an SSH session.

The rename itself runs as root, in deploy/pi/greenthumb-set-hostname, which the
installer copies to /usr/local/sbin. This module validates the name, which the
script checks again, and passes it as a list argument, never a shell string.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess

logger = logging.getLogger(__name__)

HELPER = "/usr/local/sbin/greenthumb-set-hostname"
COMMAND_TIMEOUT = 20
# One DNS label: what both a hostname and the part before .local must be.
VALID = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def current() -> str:
    return socket.gethostname()


def status() -> dict[str, object]:
    name = current()
    return {"status": "ok", "hostname": name, "address": f"{name}.local"}


def clean(name: object) -> str:
    """The name as it will be set, or ValueError saying what is wrong with it.

    Case is forgiven, since .local names are case-insensitive and someone will
    type "Herman-Kitchen". Everything else is refused rather than rewritten:
    quietly turning "my planter" into "my-planter" would leave them looking
    for an address they never chose.
    """
    candidate = str(name or "").strip().lower()
    if not candidate:
        raise ValueError("Enter a name")
    if len(candidate) > 63:
        raise ValueError("Keep the name to 63 characters or fewer")
    if not VALID.match(candidate):
        raise ValueError(
            "Use only letters, digits and hyphens, without a hyphen at the start or end"
        )
    return candidate


def rename(name: object) -> dict[str, object]:
    """Rename the Pi. It answers at the new .local address straight away."""
    candidate = clean(name)
    if candidate == current():
        return status()
    try:
        result = subprocess.run(
            ["sudo", "-n", HELPER, candidate],
            capture_output=True, text=True, timeout=COMMAND_TIMEOUT, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Could not rename the planter: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        if "password" in detail.lower() or "not allowed" in detail.lower():
            detail = "the planter is not allowed to rename itself yet. Re-run the installer, which adds the permission"
        raise RuntimeError(f"Could not rename the planter: {detail}")
    logger.info("Renamed the planter to %s", candidate)
    # Read back rather than assumed, so the page shows what the Pi now says.
    return status()
