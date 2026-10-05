"""Every method the API calls on the service must actually exist.

Written after `home_gantry` was deleted by a slice that was aiming at the two
methods either side of it. main.py still called it, so homing answered with an
unhandled AttributeError -- a plain-text 500 that the browser could not even
parse. Nothing caught it: no test touches the motion endpoints, and both files
import fine on their own because the call is only resolved when the route runs.

This checks the join between them without needing a running Klipper.
"""

import ast
import pathlib
import sys
import types

sys.modules["smbus2"] = types.ModuleType("smbus2")
sys.modules["spidev"] = types.ModuleType("spidev")

from greenthumb.services.automation import GreenThumbAutomation
from tests.helpers import temp_state, temp_store


class _Nul:
    """Stands in for anything with hardware behind it."""
    addresses = [0x36]
    mode = "off"; color = (0, 0, 0); brightness = 0
    def read_one(self, a): return None
    def status(self): return {"ok": True, "homed": True, "position": 0.0}
    def __getattr__(self, n): return lambda *a, **k: {}


# Checked against an instance, not the class: history, leds and plants are
# assigned in __init__, so a class-level hasattr reports them missing and the
# test would cry wolf about three things that are fine.
service = GreenThumbAutomation(
    _Nul(), _Nul(), _Nul(), _Nul(),
    history=temp_store(), state_path=temp_state(),
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN = ROOT / "greenthumb" / "main.py"

tree = ast.parse(MAIN.read_text(encoding="utf-8"))

# Every `automation.<name>` the API reaches for.
wanted = sorted({
    node.attr
    for node in ast.walk(tree)
    if isinstance(node, ast.Attribute)
    and isinstance(node.value, ast.Name)
    and node.value.id == "automation"
})

assert wanted, "found no automation.* references; the parser is wrong, not the code"

missing = [name for name in wanted if not hasattr(service, name)]
assert not missing, (
    f"main.py calls automation.{missing} which does not exist. "
    "Each of these is a 500 the moment that route is hit."
)
print(f"ok: all {len(wanted)} automation members the API calls exist")

# The same trap one layer down: the service reaching into the Klipper client.
from greenthumb.hardware.klipper_client import KlipperClient

AUTOMATION = ROOT / "greenthumb" / "services" / "automation.py"
service_tree = ast.parse(AUTOMATION.read_text(encoding="utf-8"))
klipper_calls = sorted({
    node.attr
    for node in ast.walk(service_tree)
    if isinstance(node, ast.Attribute)
    and isinstance(node.value, ast.Attribute)
    and node.value.attr == "klipper"
})
missing = [name for name in klipper_calls if not hasattr(KlipperClient, name)]
assert not missing, f"automation calls self.klipper.{missing} which does not exist"
print(f"ok: all {len(klipper_calls)} KlipperClient members the service calls exist")

print("\nall wiring checks passed")
