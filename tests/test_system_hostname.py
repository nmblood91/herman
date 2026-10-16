"""Renaming the Pi from the web UI.

The name arrives from a browser and is handed to a script sudo runs as root,
so it is an allow-list or nothing, and the command is a list, never a string.
"""

import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")

from greenthumb import system_hostname

calls = []
outcome = {"returncode": 0, "stderr": ""}


def fake_run(cmd, **kwargs):
    calls.append(cmd)
    return types.SimpleNamespace(returncode=outcome["returncode"], stdout="", stderr=outcome["stderr"])


system_hostname.subprocess.run = fake_run
system_hostname.current = lambda: "herman"
system_hostname.socket.gethostname = lambda: "herman"

hostile = [
    "", "   ", "-herman", "herman-", "her man", "herman.local", "herman;reboot",
    "$(reboot)", "`reboot`", "../etc", "h" * 64, "herman_kitchen", "héran",
]
for value in hostile:
    calls.clear()
    try:
        system_hostname.rename(value)
    except ValueError:
        assert not calls, f"ran a command for rejected input {value!r}: {calls}"
    else:
        raise AssertionError(f"accepted {value!r}")
print(f"ok: {len(hostile)} malformed or hostile names rejected before any command runs")

calls.clear()
system_hostname.rename("Herman-Kitchen")
assert calls == [["sudo", "-n", system_hostname.HELPER, "herman-kitchen"]], calls
print("ok: a good name is lowercased and passed to the helper as a list with non-interactive sudo")

calls.clear()
assert system_hostname.rename("herman")["hostname"] == "herman"
assert not calls, "renaming to the current name should do nothing"
print("ok: renaming to the current name runs nothing")

assert system_hostname.clean("a") == "a"
assert system_hostname.clean("h" * 63) == "h" * 63
assert system_hostname.clean("herman-2") == "herman-2"
print("ok: one-character, 63-character and numbered names are accepted")

outcome.update(returncode=1, stderr="sudo: a password is required")
try:
    system_hostname.rename("herman-office")
except RuntimeError as exc:
    assert "installer" in str(exc), exc
else:
    raise AssertionError("a refused rename reported success")
print("ok: a missing permission is reported with how to fix it")

assert system_hostname.status()["address"] == "herman.local"
print("ok: status gives the .local address")

print("\nall hostname checks passed")
