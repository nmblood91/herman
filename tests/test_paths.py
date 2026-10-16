"""Where the planter writes, in a checkout and as an installed package.

The paths are fixed when greenthumb.paths is imported, so each case runs in a
fresh interpreter.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = (
    "import json; from greenthumb import paths, state, history, logging_setup; "
    "print(json.dumps({'packaged': paths.PACKAGED, 'state': str(state.DEFAULT_STATE_PATH), "
    "'db': str(history.DEFAULT_DB_PATH), 'log': str(logging_setup.LOG_FILE), "
    "'env': str(paths.ENV_FILE)}))"
)


def probe(root=ROOT, **env):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GREENTHUMB_")}
    environment.update(env)
    environment["PYTHONPATH"] = str(root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Run from inside the tree under test: `python -c` puts the current
    # directory first on the import path, ahead of PYTHONPATH, so running from
    # this checkout would import it instead of the copy being probed.
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, env=environment,
        cwd=root, check=True,
    ).stdout
    return json.loads(out)


found = probe()
assert found["packaged"] is False, found
assert Path(found["state"]) == ROOT / "data" / "state.json", found
assert Path(found["db"]) == ROOT / "data" / "greenthumb.db", found
assert Path(found["log"]) == ROOT / "logs" / "greenthumb.log", found
assert found["env"] == ".env", found
print("ok: a checkout keeps data, logs and .env inside itself")

override = Path(tempfile.mkdtemp())
found = probe(GREENTHUMB_DATA_DIR=str(override / "d"), GREENTHUMB_LOG_DIR=str(override / "l"))
assert Path(found["state"]) == override / "d" / "state.json", found
assert Path(found["db"]) == override / "d" / "greenthumb.db", found
assert Path(found["log"]) == override / "l" / "greenthumb.log", found
print("ok: GREENTHUMB_DATA_DIR and GREENTHUMB_LOG_DIR override them")

# An installed package: a copy of the code with BUILD_INFO.json beside it.
installed = Path(tempfile.mkdtemp())
subprocess.run(
    [sys.executable, "-c", "import shutil, sys; shutil.copytree(sys.argv[1], sys.argv[2], "
     "ignore=shutil.ignore_patterns('__pycache__'))", str(ROOT / "greenthumb"), str(installed / "greenthumb")],
    check=True,
)
(installed / "BUILD_INFO.json").write_text(json.dumps({"version": "0.2.0"}), encoding="utf-8")
found = probe(root=installed)
assert found["packaged"] is True, found
assert Path(found["state"]) == Path("/var/lib/greenthumb/state.json"), found
assert Path(found["log"]) == Path("/var/log/greenthumb/greenthumb.log"), found
assert Path(found["env"]) == Path("/etc/greenthumb/greenthumb.env"), found
print("ok: an installed package writes to /var/lib, /var/log and /etc, never beside its code")

print("\nall path checks passed")
