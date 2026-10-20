"""Where the planter keeps what it writes, as opposed to what it runs.

A git checkout keeps everything inside the checkout: data/ and logs/ beside the
code, settings in .env. That is what development and the tests expect, and it
stays the default.

An installed package keeps its code in /opt/greenthumb and nothing else. The
planter's own data goes to /var/lib/greenthumb, its log to /var/log/greenthumb
and its settings to /etc/greenthumb, so an upgrade can replace the code without
touching any of it, and a read-only system image can later put just those on a
writable partition.

Packaged mode is recognized by BUILD_INFO.json, which only CI writes, rather
than by an environment variable. A command run by hand over SSH -- a
calibration pass, say -- has no service environment, and must still find the
same state.json the service uses rather than quietly starting a new one.
GREENTHUMB_DATA_DIR and GREENTHUMB_LOG_DIR override either default.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_INFO = ROOT / "BUILD_INFO.json"
PACKAGED = BUILD_INFO.exists()


def _dir(variable: str, packaged: str, checkout: str) -> Path:
    override = os.environ.get(variable)
    if override:
        return Path(override)
    return Path(packaged) if PACKAGED else ROOT / checkout


DATA_DIR = _dir("GREENTHUMB_DATA_DIR", "/var/lib/greenthumb", "data")
LOG_DIR = _dir("GREENTHUMB_LOG_DIR", "/var/log/greenthumb", "logs")
ENV_FILE = Path("/etc/greenthumb/greenthumb.env") if PACKAGED else Path(".env")
